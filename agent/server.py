"""2단 웹 서버: drag/drop 업로드 → SSE 진행 스텝퍼 → 점프컷 드래프트.

검증된 1단 파이프라인(probe → silence → keep → build_jumpcut_draft)을 그대로 감싼다.

기술 함정 처리:
  - content hash 기반 job_id: mtime이 아니라 파일 내용 해시 → 같은 파일 재업로드 시
    캐시 hit (3단 ASR 캐시 키도 동일 해시 재사용 예정).
  - ASR_LOCK: numba(whisper) 비스레드안전 → 동시 호출 시 segfault. 3단부터 ASR을
    이 Lock으로 직렬화. 지금은 예약만 해 둔다.
  - StreamingResponse(text/event-stream) + X-Accel-Buffering:no → 프록시/버퍼링 없는 SSE.
  - 블로킹 작업(ffmpeg, 드래프트 빌드)은 asyncio.to_thread로 이벤트루프 보호.
  - 단계당 최소 MIN_STAGE_SEC 지연 → 캐시 hit이어도 스텝퍼 애니메이션 가시화.
  - 결과를 JOBS에 캐시 → EventSource 자동 재연결이 파이프라인을 재실행하지 않게 replay.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import AsyncIterator, Dict
from uuid import uuid4

from fastapi import FastAPI, UploadFile, HTTPException, Form
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse

from . import config
from . import asr
from .silence import detect_silences, keep_intervals, probe_duration
from .draft import build_jumpcut_draft
from .ng import ng_ranges, subtract_ranges

app = FastAPI(title="캡컷 에이전트", version=__import__("agent").__version__)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# job_id → {path, draft_name, filename, size, result?}
JOBS: Dict[str, dict] = {}

# 3단 예약: ASR은 이 Lock으로 직렬화 (numba 비스레드안전, 동시 호출 시 segfault)
ASR_LOCK = asyncio.Lock()


# ──────────────────────────── 유틸 ────────────────────────────
def _sanitize_name(stem: str) -> str:
    """파일명 → CapCut 드래프트 폴더로 안전한 이름 (한글 유지)."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", stem).strip().strip(".")
    return name or "jumpcut"


def _fmt(us: float) -> str:
    """µs → m:ss.s"""
    s = us / config.SEC
    return f"{int(s // 60)}:{s % 60:04.1f}"


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _min_delay(t0: float) -> None:
    elapsed = time.monotonic() - t0
    if elapsed < config.MIN_STAGE_SEC:
        await asyncio.sleep(config.MIN_STAGE_SEC - elapsed)


# ──────────────────────────── 동기 작업(스레드) ────────────────────────────
def _silence_work(path: str):
    duration = probe_duration(path)
    silences = detect_silences(path)
    keeps = keep_intervals(duration, silences)
    return duration, silences, keeps


# ──────────────────────────── 라우트 ────────────────────────────
@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")


@app.post("/api/upload")
async def upload(file: UploadFile, mode: str = Form(None)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in config.VIDEO_EXTS:
        raise HTTPException(400, f"지원하지 않는 형식: {ext or '확장자 없음'} "
                                 f"(허용: {', '.join(sorted(config.VIDEO_EXTS))})")

    config.WORK_DIR.mkdir(parents=True, exist_ok=True)
    tmp = config.WORK_DIR / f"_tmp_{uuid4().hex}{ext}"
    h = hashlib.sha256()
    size = 0
    max_size = 500 * 1024 * 1024  # 500MB
    with open(tmp, "wb") as out:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            if size > max_size:
                tmp.unlink(missing_ok=True)
                raise HTTPException(413, f"파일이 너무 커요 (최대 500MB, 현재 {size/(1024*1024):.1f}MB)")
            out.write(chunk)
            h.update(chunk)

    if size == 0:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, "빈 파일입니다.")

    job_id = h.hexdigest()[:16]
    final = config.WORK_DIR / f"{job_id}{ext}"
    was_cached = final.exists()
    if was_cached:
        tmp.unlink(missing_ok=True)        # 캐시 hit: 기존 파일 재사용
    else:
        os.replace(tmp, final)

    draft_name = _sanitize_name(os.path.splitext(os.path.basename(file.filename or "jumpcut"))[0])
    JOBS[job_id] = {
        "path": str(final),
        "draft_name": draft_name,
        "filename": file.filename,
        "size": size,
        "mode": mode if mode in ("shorts", "longform") else None,
    }
    return JSONResponse({
        "job_id": job_id,
        "draft_name": draft_name,
        "filename": file.filename,
        "size": size,
        "cached": was_cached,
    })


@app.get("/api/stream/{job_id}")
async def stream(job_id: str):
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "알 수 없는 job (서버 재시작? 다시 업로드해 주세요)")

    async def gen() -> AsyncIterator[str]:
        stages = [
            {"id": "preview", "label": "프리뷰 분석"},
            {"id": "draft", "label": "드래프트 빌드"},
        ]
        yield _sse("stages", stages)

        # 캐시된 결과가 있으면 재실행 없이 replay (EventSource 자동 재연결 대비)
        if "result" in job:
            for st in stages:
                yield _sse("stage", {"id": st["id"], "status": "done"})
            yield _sse("preview", job["preview_data"])
            yield _sse("result", job["result"])
            return

        try:
            # ── 프리뷰 분석 (무음 감지 + ASR + NG 감지) ──
            yield _sse("stage", {"id": "preview", "status": "running"})
            t0 = time.monotonic()
            duration, silences, keeps = await asyncio.to_thread(_silence_work, job["path"])

            transcript = None
            try:
                async with ASR_LOCK:
                    transcript = await asyncio.to_thread(asr.transcribe, job["path"])
            except Exception as e:
                print(f"⚠️ ASR 실패: {type(e).__name__}: {e}")
                transcript = None

            # NG 구간 계산 (ASR이 있으면 NG도 감지, 없으면 무음만)
            cut_ranges = []  # (start, end) 컷될 구간들
            if transcript and config.NG_ENABLED:
                ng_cut_ranges, _ = ng_ranges(transcript["segments"], config.NG_THRESHOLD, config.NG_CUT_FILLER)
                silence_ranges = silences
                # 모든 컷 구간 합치기
                all_cuts = sorted(silence_ranges + ng_cut_ranges)
                # 겹치는 구간 병합
                merged = []
                for s, e in all_cuts:
                    if merged and merged[-1][1] >= s:
                        merged[-1] = (merged[-1][0], max(merged[-1][1], e))
                    else:
                        merged.append((s, e))
                cut_ranges = merged
            else:
                cut_ranges = sorted(silences)

            await _min_delay(t0)
            yield _sse("stage", {
                "id": "preview", "status": "done",
                "detail": f"원본 {duration:.1f}s · 컷 {len(cut_ranges)}곳",
            })

            # 프리뷰 데이터 생성
            preview_data = {
                "duration": duration,
                "cuts": cut_ranges,  # [(start, end), ...]
                "keeps": keeps,      # [(start, end), ...]
                "transcribed": transcript is not None,
            }
            job["preview_data"] = preview_data
            yield _sse("preview", preview_data)

            # ── 드래프트 빌드 ──
            yield _sse("stage", {"id": "draft", "status": "running"})
            t0 = time.monotonic()
            stats = await asyncio.to_thread(
                build_jumpcut_draft, job["path"], keeps, job["draft_name"],
                transcript=transcript, mode=job.get("mode"),
            )
            await _min_delay(t0)
            yield _sse("stage", {
                "id": "draft", "status": "done",
                "detail": f"{stats['segments']}컷 · 자막 {stats['subtitles']}개 · {stats['mode']}",
            })

            result = {
                "draft_name": stats["draft_name"],
                "resolution": f"{stats['width']}×{stats['height']}",
                "segments": stats["segments"],
                "output": _fmt(stats["output_duration_us"]),
                "source": _fmt(stats["source_duration_us"]),
                "removed": _fmt(stats["removed_us"]),
                "removed_pct": round(stats["removed_us"] / max(1, stats["source_duration_us"]) * 100),
                "subtitles": stats.get("subtitles", 0),
                "mode": stats.get("mode"),
                "draft_path": stats["draft_path"],
            }
            job["result"] = result
            yield _sse("result", result)

        except ValueError as e:        # 사용자용(파일/형식) 오류: 메시지만 노출
            yield _sse("fail", {"message": str(e)})
        except Exception as e:         # noqa: BLE001 — 예기치 못한 오류
            yield _sse("fail", {"message": f"처리 오류 · {type(e).__name__}: {e}"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/video/{job_id}")
async def video(job_id: str):
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "알 수 없는 job")
    return FileResponse(job["path"], media_type="video/mp4")
