"""1단 CLI: 입력 영상 → 무음 컷 점프컷 드래프트 (UI 없음, 핵심 검증용).

사용법:
  python cli_jumpcut.py <input.mp4> [--name NAME]
                        [--noise -30] [--min-silence 0.5] [--pad 0.08]
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from agent import config
from agent.silence import detect_silences, keep_intervals, probe_duration
from agent.draft import build_jumpcut_draft


def _fmt(us: float) -> str:
    """µs → mm:ss.ss"""
    s = us / config.SEC
    return f"{int(s // 60):02d}:{s % 60:05.2f}"


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="무음 컷 점프컷 드래프트 생성")
    p.add_argument("input", help="입력 영상 (mp4/mov)")
    p.add_argument("--name", default=None, help="드래프트 이름 (기본: jumpcut_<파일명>)")
    p.add_argument("--noise", type=float, default=config.SILENCE_NOISE_DB,
                   help=f"무음 임계 dB (기본 {config.SILENCE_NOISE_DB})")
    p.add_argument("--min-silence", type=float, default=config.MIN_SILENCE_SEC,
                   help=f"최소 무음 길이 초 (기본 {config.MIN_SILENCE_SEC})")
    p.add_argument("--pad", type=float, default=config.KEEP_PAD_SEC,
                   help=f"발화 앞뒤 여유 초 (기본 {config.KEEP_PAD_SEC})")
    p.add_argument("--subtitle", action="store_true",
                   help="mlx-whisper로 대본 추출 후 세그먼트 자막 생성")
    p.add_argument("--mode", choices=["shorts", "longform"], default=None,
                   help="자막 사전설정 (기본: 영상 비율로 자동)")
    p.add_argument("--no-ng", action="store_true",
                   help="잔말·NG(재촬영) 자동 컷 끄기")
    args = p.parse_args(argv)

    input_path = os.path.abspath(args.input)
    if not os.path.exists(input_path):
        sys.exit(f"입력 파일 없음: {input_path}")

    name = args.name or ("jumpcut_" + os.path.splitext(os.path.basename(input_path))[0])

    t0 = time.time()
    print(f"▸ 무음 감지  noise={args.noise}dB  min_silence={args.min_silence}s  pad={args.pad}s")
    duration = probe_duration(input_path)
    silences = detect_silences(input_path, args.noise, args.min_silence)
    keeps = keep_intervals(duration, silences, pad=args.pad, min_keep=config.MIN_KEEP_SEC)
    print(f"  원본 {duration:.2f}s · 무음 {len(silences)}곳 · 보존 {len(keeps)}조각")

    transcript = None
    if args.subtitle:
        from agent.asr import build_cut_audio, transcribe
        from agent.ng import ng_ranges, subtract_ranges
        # 1) 원본 대본 추출(재촬영이 세그먼트로 분리됨) → NG/잔말 감지
        print("▸ 대본 추출 (mlx-whisper)…")
        t1 = time.time()
        tr_orig = transcribe(input_path)
        print(f"  {len(tr_orig['segments'])}개 세그먼트 · {tr_orig['language']} · {time.time()-t1:.1f}s")
        if config.NG_ENABLED and not args.no_ng:
            ranges, ngc = ng_ranges(tr_orig["segments"], config.NG_THRESHOLD, config.NG_CUT_FILLER)
            before = sum(e - s for s, e in keeps)
            keeps = subtract_ranges(keeps, ranges)
            after = sum(e - s for s, e in keeps)
            print(f"▸ 잔말·NG 컷: 잔말 {ngc['filler']}개 · 재촬영 {ngc['retake']}개  (-{before-after:.1f}s)")
        # 2) 최종 컷(무음+NG 제거)에 자막용 ASR — 공백편집 → 자막
        print("▸ 컷 오디오 자막 ASR…")
        transcript = transcribe(build_cut_audio(input_path, keeps))

    print("▸ 드래프트 빌드…")
    stats = build_jumpcut_draft(input_path, keeps, name, transcript=transcript, mode=args.mode)

    print()
    print(f"✓ 드래프트  {stats['draft_name']}  ({stats['width']}x{stats['height']})")
    print(f"  세그먼트  {stats['segments']}개")
    if stats.get("subtitles"):
        print(f"  자막      {stats['subtitles']}개  [{stats.get('mode')}]")
    print(f"  길이      {_fmt(stats['output_duration_us'])}"
          f"  (원본 {_fmt(stats['source_duration_us'])}, "
          f"-{_fmt(stats['removed_us'])} 제거)")
    print(f"  경로      {stats['draft_path']}")
    print(f"  ⏱        {time.time() - t0:.1f}s")
    print()
    print("→ CapCut을 재시작하고 프로젝트 목록에서 위 드래프트를 열어 재생해 검증하세요.")


if __name__ == "__main__":
    main()
