"""로컬 웹 서버 실행기.

    python serve.py            # http://127.0.0.1:8765
    python serve.py --port 9000 --reload
"""
from __future__ import annotations

import argparse
import os

import uvicorn


def main() -> None:
    p = argparse.ArgumentParser(description="캡컷 에이전트 로컬 웹")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8765)))
    p.add_argument("--reload", action="store_true", help="코드 변경 시 자동 재시작(개발용)")
    args = p.parse_args()

    print(f"▸ 캡컷 에이전트  →  http://{args.host}:{args.port}")
    uvicorn.run("agent.server:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
