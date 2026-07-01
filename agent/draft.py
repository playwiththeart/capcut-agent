"""pycapcut 기반 점프컷 드래프트 빌더.

기술 함정 처리:
  1. draft_info.json — pycapcut은 draft_content.json만 기록하지만, 최신 CapCut(Mac)은
     draft_info.json을 읽는다. save() 후 동일 내용을 draft_info.json으로도 dump.
  2. tm_duration — draft_meta_info.json의 tm_duration이 0으로 남으면 CapCut 프로젝트
     목록에서 길이가 0:00으로 표시되거나 열리지 않는다. 타임라인 총 길이로 패치.
"""
from __future__ import annotations

import json
import os
import shutil
from typing import Dict, List, Tuple

import pycapcut as cc
from pycapcut import Timerange

from . import config
from .silence import probe_display_size

Interval = Tuple[float, float]


def _patch_subtitle_font(draft_path: str, resource_id: str, font_path: str) -> None:
    """draft_info.json의 모든 텍스트 소재에 사용자가 고른 폰트(id+실제 경로)를 주입.

    pycapcut FontType엔 한글 폰트가 없으므로, CapCut이 직접 저장한 폰트 정보를
    추출해 빌드 후 텍스트 소재 content에 그대로 박는다.
    """
    info_path = os.path.join(draft_path, "draft_info.json")
    try:
        with open(info_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError):
        return
    font = {"id": resource_id, "path": font_path}
    for mat in data.get("materials", {}).get("texts", []):
        try:
            content = json.loads(mat.get("content", "{}"))
        except (ValueError, TypeError):
            continue
        for st in content.get("styles", []):
            st["font"] = font
        mat["content"] = json.dumps(content, ensure_ascii=False)
    with open(info_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _localize_media(input_path: str, draft_path: str) -> str:
    """미디어를 드래프트 폴더 안으로 가져와 CapCut이 접근 가능한 경로로 만든다.

    함정: CapCut은 ~/Downloads 등 macOS 보호 폴더의 원본을 못 읽어 '영상 없음'이 된다.
    드래프트 폴더(=CapCut 자기 영역) 안으로 하드링크하면 추가 용량 0·즉시이고,
    원본을 옮기거나 지워도 드래프트가 살아 있다(self-contained). 다른 볼륨이면 복사로 폴백.
    """
    media_dir = os.path.join(draft_path, "linked_media")
    os.makedirs(media_dir, exist_ok=True)
    dst = os.path.join(media_dir, os.path.basename(input_path))
    if os.path.abspath(dst) == os.path.abspath(input_path):
        return input_path
    try:
        if os.path.lexists(dst):
            os.remove(dst)
        os.link(input_path, dst)          # 하드링크(같은 볼륨)
    except OSError:
        shutil.copy2(input_path, dst)     # 다른 볼륨 등 → 복사
    return dst


def build_jumpcut_draft(
    input_path: str,
    keeps: List[Interval],
    draft_name: str,
    draft_dir: str | None = None,
    fps: int | None = None,
    transcript: Dict | None = None,
    mode: str | None = None,
) -> Dict:
    """발화 구간(keeps)만 이어붙인 점프컷 드래프트를 생성하고 통계를 반환.

    transcript(컷-타임 대본)가 주어지면 짧게 쪼갠 자막을 텍스트 트랙으로 얹는다.
    mode("shorts"/"longform")로 자막 크기·위치 사전설정을 고른다(없으면 비율로 자동).
    """
    draft_dir = str(draft_dir or config.CAPCUT_DRAFT_DIR)
    fps = fps or config.DEFAULT_FPS
    input_path = os.path.abspath(input_path)

    folder = cc.DraftFolder(draft_dir)
    width, height = probe_display_size(input_path)  # 회전 보정된 표시 해상도로 캔버스
    resolved_mode = mode or config.default_mode(width, height)
    preset = config.get_preset(resolved_mode)

    script = folder.create_draft(draft_name, width, height, fps=fps, allow_replace=True)
    draft_path = os.path.join(draft_dir, draft_name)

    # 함정: CapCut이 못 읽는 경로(Downloads 등) 회피 → 드래프트 폴더 안으로 링크
    local_media = _localize_media(input_path, draft_path)
    material = cc.VideoMaterial(local_media)

    script.add_track(cc.TrackType.video)

    cursor = 0          # 타임라인 위치(µs)
    placed = 0
    for s, e in keeps:
        s_us = int(round(s * config.SEC))
        e_us = min(int(round(e * config.SEC)), material.duration)  # 소재 길이로 클램프
        if e_us <= s_us:
            continue
        dur = e_us - s_us
        segment = cc.VideoSegment(
            material,
            Timerange(cursor, dur),                 # 타임라인: 이어붙임
            source_timerange=Timerange(s_us, dur),  # 소스: 발화 구간만 발췌
            volume=1.0,
        )
        script.add_segment(segment)
        cursor += dur
        placed += 1

    if placed == 0:
        raise RuntimeError("보존할 구간이 없습니다 (전부 무음으로 판정됨)")

    # 자막: 대본을 컷된 출력 타임라인으로 매핑해 텍스트 트랙에 얹는다
    subtitle_count = 0
    if transcript:
        from .subtitle import subtitles_from_transcript

        total_out_sec = cursor / config.SEC
        subs = subtitles_from_transcript(
            transcript, total_out_sec,
            min_dur=config.SUB_MIN_DUR, max_chars=int(preset["max_chars"]),
        )
        if subs:
            script.add_track(cc.TrackType.text, "subtitle")
            style = cc.TextStyle(
                size=preset["size"], color=(1.0, 1.0, 1.0), align=1,
                bold=True, auto_wrapping=True, max_line_width=config.SUB_MAX_LINE_WIDTH,
            )
            border = cc.TextBorder(
                color=(0.0, 0.0, 0.0),
                width=preset.get("border_width", config.SUB_BORDER_WIDTH),
            )
            bgp = preset.get("background")
            bg = cc.TextBackground(
                color=bgp["color"], style=bgp["style"], alpha=bgp["alpha"],
                round_radius=bgp["round_radius"], height=bgp["height"], width=bgp["width"],
                horizontal_offset=bgp["horizontal_offset"], vertical_offset=bgp["vertical_offset"],
            ) if bgp else None
            clip = cc.ClipSettings(transform_y=preset["transform_y"])
            for sub in subs:
                s_us = int(round(sub["start"] * config.SEC))
                d_us = int(round((sub["end"] - sub["start"]) * config.SEC))
                if d_us <= 0:
                    continue
                seg = cc.TextSegment(
                    sub["text"], Timerange(s_us, d_us),
                    style=style, border=border, background=bg, clip_settings=clip,
                )
                script.add_segment(seg, "subtitle")
            subtitle_count = len(subs)

    script.save()  # → draft_content.json

    # 함정 1: CapCut이 실제로 읽는 draft_info.json으로도 기록
    script.dump(os.path.join(draft_path, "draft_info.json"))
    # 함정 3: 모드별 사용자 폰트(쇼츠=도현체 / 롱폼=학교안심 바른돋움)를 텍스트 소재에 주입
    if subtitle_count and preset.get("font_id"):
        _patch_subtitle_font(draft_path, preset["font_id"], preset["font_path"])
    # 함정 2: draft_meta_info.json의 tm_duration 패치
    _patch_meta_duration(draft_path, script.duration)

    return {
        "draft_name": draft_name,
        "draft_path": draft_path,
        "segments": placed,
        "width": width,
        "height": height,
        "source_duration_us": material.duration,
        "output_duration_us": cursor,
        "removed_us": material.duration - cursor,
        "subtitles": subtitle_count,
        "mode": resolved_mode,
    }


def _patch_meta_duration(draft_path: str, duration_us: int) -> None:
    """draft_meta_info.json의 tm_duration을 실제 타임라인 길이로 갱신."""
    meta_path = os.path.join(draft_path, "draft_meta_info.json")
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return

    data["tm_duration"] = int(duration_us)
    # 일부 CapCut 버전은 빈 draft_fold_path를 채워줘야 목록에 정상 표시됨
    if "draft_fold_path" in data and not data["draft_fold_path"]:
        data["draft_fold_path"] = draft_path

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
