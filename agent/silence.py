"""ffmpeg 기반 무음 감지 → 보존(발화) 구간 산출.

ffmpeg의 silencedetect 필터로 무음 구간을 찾고, 그 여집합(=발화 구간)을
약간의 여유(pad)와 함께 돌려준다. 오디오 트랙이 없으면 전체를 한 구간으로 보존.
"""
from __future__ import annotations

import json
import re
import subprocess
from typing import List, Optional, Tuple

from . import config

# (start_sec, end_sec)
Interval = Tuple[float, float]

_SIL_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SIL_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


def probe_duration(path: str) -> float:
    """영상 길이(초)를 ffprobe로 측정. 읽기 실패 시 사용자용 메시지로 변환."""
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise ValueError("영상을 읽을 수 없습니다 (손상됐거나 지원하지 않는 코덱일 수 있어요).")
    try:
        return float(proc.stdout.strip())
    except ValueError:
        raise ValueError("영상 길이를 확인할 수 없습니다.")


def probe_display_size(path: str) -> Tuple[int, int]:
    """회전 메타데이터를 반영한 '표시' 해상도 (가로, 세로).

    함정: 아이폰 세로 영상은 프레임을 1920×1080(가로)으로 저장하고 rotation=90
    메타데이터로 세로 표시한다. 코딩 해상도만 보면 세로 영상이 가로 캔버스가 된다.
    rotation이 ±90이면 가로·세로를 스왑해 실제 보이는 해상도를 돌려준다.
    """
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height:stream_tags=rotate:side_data=rotation",
            "-of", "json", path,
        ],
        capture_output=True, text=True,
    )
    try:
        st = (json.loads(out.stdout or "{}").get("streams") or [{}])[0]
    except (ValueError, IndexError):
        st = {}
    w = int(st.get("width") or 0)
    h = int(st.get("height") or 0)

    rot = 0
    for sd in st.get("side_data_list", []):
        if sd.get("rotation") is not None:
            rot = int(sd["rotation"])
            break
    if rot == 0:
        try:
            rot = int((st.get("tags") or {}).get("rotate", 0))
        except (TypeError, ValueError):
            rot = 0

    if w and h and abs(rot) % 180 == 90:
        return h, w
    return w, h


def detect_silences(
    path: str,
    noise_db: float = config.SILENCE_NOISE_DB,
    min_silence: float = config.MIN_SILENCE_SEC,
) -> List[Tuple[float, Optional[float]]]:
    """무음 구간 [(start, end), ...]을 반환. 끝이 영상 끝까지면 end=None."""
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", path,
        "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    text = proc.stderr
    starts = [float(m.group(1)) for m in _SIL_START.finditer(text)]
    ends = [float(m.group(1)) for m in _SIL_END.finditer(text)]

    silences: List[Tuple[float, Optional[float]]] = []
    for i, s in enumerate(starts):
        e: Optional[float] = ends[i] if i < len(ends) else None
        silences.append((max(0.0, s), e))
    return silences


def keep_intervals(
    duration: float,
    silences: List[Tuple[float, Optional[float]]],
    pad: float = config.KEEP_PAD_SEC,
    min_keep: float = config.MIN_KEEP_SEC,
) -> List[Interval]:
    """무음의 여집합(발화 구간)을 pad 적용 + 병합 + 미세조각 제거하여 반환."""
    # 무음 구간 정규화(끝 None → duration, 범위 클램프, 유효한 것만)
    sil: List[Interval] = []
    for s, e in silences:
        e_resolved = duration if e is None else e
        s_c, e_c = max(0.0, s), min(duration, e_resolved)
        if e_c > s_c:
            sil.append((s_c, e_c))
    sil.sort()

    # 여집합 = 발화 구간
    keeps: List[Interval] = []
    cursor = 0.0
    for s, e in sil:
        if s > cursor:
            keeps.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < duration:
        keeps.append((cursor, duration))

    # 발화 구간 앞뒤로 pad만큼 확장(말 첫/끝 음절 보호)
    padded = [(max(0.0, s - pad), min(duration, e + pad)) for s, e in keeps]

    # pad로 인해 겹치거나 맞닿은 구간 병합
    merged: List[Interval] = []
    for s, e in padded:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    # 너무 짧은 조각 제거
    return [(s, e) for s, e in merged if (e - s) >= min_keep]
