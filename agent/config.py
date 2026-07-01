"""전역 설정 및 경로."""
from __future__ import annotations

import os
from pathlib import Path

# pycapcut 시간 단위: 1초 = 1e6 마이크로초
SEC = 1_000_000


def _default_draft_dir() -> Path:
    """CapCut 드래프트 루트 (Mac). CAPCUT_DRAFT_DIR 환경변수로 override 가능."""
    env = os.environ.get("CAPCUT_DRAFT_DIR")
    if env:
        return Path(env)
    return (
        Path.home()
        / "Movies"
        / "CapCut"
        / "User Data"
        / "Projects"
        / "com.lveditor.draft"
    )


CAPCUT_DRAFT_DIR = _default_draft_dir()


def _default_work_dir() -> Path:
    """업로드 원본 + ASR 캐시 작업 폴더. AGENT_WORK_DIR로 override 가능."""
    env = os.environ.get("AGENT_WORK_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / ".work"


WORK_DIR = _default_work_dir()

# SSE 단계당 최소 노출 시간(초). 캐시 hit으로 즉시 끝나도 스텝퍼 애니메이션이 보이게.
MIN_STAGE_SEC = 0.5

# 업로드 허용 확장자
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}

# --- 무음 감지 기본값 ---
SILENCE_NOISE_DB = -30.0   # 이 dB 이하를 무음으로 간주
MIN_SILENCE_SEC = 0.5      # 이 길이 이상 지속된 무음만 컷
KEEP_PAD_SEC = 0.08        # 발화 구간 앞뒤 여유(컷이 말 첫/끝 음절을 안 자르게)
MIN_KEEP_SEC = 0.20        # 이보다 짧은 보존 조각은 버림(미세 파편 방지)

DEFAULT_FPS = 30

# --- ASR (대본 추출) ---
# faster-whisper: 크로스플랫폼. large-v3 = 정확도 높음, base = 빠름
ASR_MODEL = os.environ.get("ASR_MODEL", "large-v3")
ASR_LANG = os.environ.get("ASR_LANG", "ko")

# --- 자막 스타일 (캡컷 정규화 좌표) ---
# 공통
SUB_MAX_LINE_WIDTH = 0.70  # 이 폭 넘으면 자동 줄바꿈
SUB_BORDER_WIDTH = 15.0    # 검은 외곽선 두께 0~100 (≈3~4px)
SUB_MIN_DUR = 0.30         # 자막 최소 노출 시간(초)

# 모드별 자막 사전설정 — CapCut에서 사용자가 직접 맞춘 값을 그대로 추출(폰트·크기·위치).
#   shorts(세로):   _IMG_3891에서 추출 — 도현체
#   longform(가로): 0629 프로젝트에서 추출 — 학교안심 바른돋움
_FONT_CACHE = ("/Users/hyunseo/Library/Containers/com.lemon.lvoverseas/Data/Movies/"
               "CapCut/User Data/Cache/effect")
SUBTITLE_PRESETS = {
    "shorts": {
        "size": 11.0, "transform_y": -0.2915, "max_chars": 12,
        "font_id": "6808056385679397389",
        "font_path": f"{_FONT_CACHE}/6808056385679397389/"
                     "046f11d9049144aa80e3723b5ed93b7a/DoHyeon-Regular.ttf",
        "border_width": 15.0,   # 0~100 (검정 외곽선)
        "background": None,     # 배경 박스 없음
    },
    "longform": {
        "size": 5.0, "transform_y": -0.707, "max_chars": 16,
        "font_id": "7347594840697213441",
        "font_path": f"{_FONT_CACHE}/7347594840697213441/"
                     "a3524291d190695f2a1992b9748333f5/학교안심 바른돋움.ttf",
        "border_width": 40.0,   # 0629 border_width 0.08 = 40/100*0.2
        "background": {         # 0629의 반투명 검정 배경 박스
            "color": "#000000", "alpha": 0.61, "style": 1, "round_radius": 0.4,
            "height": 0.28, "width": 0.28, "horizontal_offset": 0.0, "vertical_offset": 0.0,
        },
    },
}


# --- 4단: 잔말·NG(재촬영) 컷 ---
NG_ENABLED = True
NG_THRESHOLD = 0.75    # 재촬영 유사도 임계(낮을수록 공격적). 중간=0.75
NG_CUT_FILLER = True   # 순수 잔말(음/어/그) 제거, 마지막 테이크 유지


def get_preset(mode: str) -> dict:
    return SUBTITLE_PRESETS.get(mode, SUBTITLE_PRESETS["shorts"])


def default_mode(width: int, height: int) -> str:
    """세로(높이≥너비)=shorts, 가로=longform."""
    return "shorts" if height >= width else "longform"
