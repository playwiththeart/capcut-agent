"""faster-whisper 기반 대본 추출 (크로스플랫폼).

★ 핵심 원칙: 전체 대본을 먼저 뽑는다(원본 시간 기준 세그먼트 + 단어).
   자막/NG 판단은 이 대본으로 한다(단어 단위가 아니라 세그먼트 단위).

기술 함정:
  - faster-whisper는 스레드안전 → ASR_LOCK으로 직렬화하지만 필수는 아님.
  - 캐시 키는 content hash(파일 내용). mtime 기반이면 매 업로드마다 miss.
  - ffmpeg로 오디오를 추출해서 faster-whisper에 전달.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from typing import Dict, List, Optional, Tuple

from . import config


def file_hash(path: str) -> str:
    """파일 내용 sha256 앞 16자리 (업로드 job_id와 동일 규칙)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _cache_path(h: str) -> str:
    return os.path.join(str(config.WORK_DIR), f"{h}.asr.json")


def transcribe(
    path: str,
    model: Optional[str] = None,
    language: Optional[str] = None,
) -> Dict:
    """영상 → 대본 dict {language, text, model, segments:[{start,end,text,words}]}.

    segments/words의 시간은 모두 '원본 영상' 기준(초). 컷 타임라인 매핑은 subtitle.py가 담당.
    """
    model = model or config.ASR_MODEL
    language = language or config.ASR_LANG
    config.WORK_DIR.mkdir(parents=True, exist_ok=True)

    h = file_hash(path)
    cp = _cache_path(h)
    if os.path.exists(cp):
        with open(cp, "r", encoding="utf-8") as f:
            return json.load(f)

    from faster_whisper import WhisperModel

    # 모델 로드 (device는 자동 감지: cuda/mps/cpu)
    whisper = WhisperModel(model, device="auto", compute_type="default")

    segments, info = whisper.transcribe(
        os.path.abspath(path),
        language=language,
        word_timestamps=True,
    )

    # 결과 변환 (faster-whisper의 generator를 list로 변환)
    result = {
        "language": info.language,
        "segments": list(segments),
    }

    segments = []
    for seg in result.get("segments", []):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        words = [
            {
                "word": (w.get("word") or "").strip(),
                "start": round(float(w["start"]), 3),
                "end": round(float(w["end"]), 3),
            }
            for w in seg.get("words", [])
            if w.get("word") and w.get("start") is not None and w.get("end") is not None
        ]
        segments.append({
            "start": round(float(seg["start"]), 3),
            "end": round(float(seg["end"]), 3),
            "text": text,
            "words": words,
        })

    transcript = {
        "language": result.get("language", language),
        "text": (result.get("text") or "").strip(),
        "model": model,
        "segments": segments,
    }
    with open(cp, "w", encoding="utf-8") as f:
        json.dump(transcript, f, ensure_ascii=False)
    return transcript


def build_cut_audio(input_path: str, keeps: List[Tuple[float, float]]) -> str:
    """보존 구간만 이어붙인 컷 오디오(wav)를 만들어 경로 반환.

    ★ 공백편집 > 자동자막: 무음을 먼저 제거한 오디오에 ASR을 돌리면, 자막 타임스탬프가
    잘린 결과 타임라인과 그대로 일치한다(원본→출력 매핑 불필요, 컷 경계에서 자연히 끊김).
    캐시 키 = 원본 내용 해시 + keeps. ffmpeg aselect로 한 번에 선택·이어붙임.
    """
    config.WORK_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    h.update(file_hash(input_path).encode())
    h.update(repr([(round(s, 3), round(e, 3)) for s, e in keeps]).encode())
    out = os.path.join(str(config.WORK_DIR), f"{h.hexdigest()[:16]}.cut.wav")
    if os.path.exists(out):
        return out

    sel = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in keeps)
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-nostats",
            "-i", os.path.abspath(input_path),
            "-vn", "-af", f"aselect='{sel}',asetpts=N/SR/TB",
            "-ac", "1", "-ar", "16000", out,
        ],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not os.path.exists(out):
        raise ValueError("컷 오디오 생성에 실패했습니다.")
    return out
