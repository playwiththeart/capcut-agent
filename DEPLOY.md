# 캡컷 자동 편집 에이전트 — Railway 배포 가이드

## 빠른 배포 (3분)

### 1. Railway 계정 가입
https://railway.app 접속 → GitHub 로그인

### 2. 프로젝트 배포
```bash
# 1. Git 초기화 및 커밋
cd /Users/hyunseo/캡컷
git init
git add .
git commit -m "Initial commit: capcut auto editor agent"

# 2. Railway CLI 설치
npm install -g @railway/cli

# 3. 배포
railway login
railway init
railway up
```

### 3. 확인
배포 후 Railway 대시보드에서:
- **Deployments** → 배포 상태 확인
- **Settings** → Public URL 확인 (https://your-app.up.railway.app)

## 로컬 테스트
```bash
.venv/bin/python serve.py
# → http://127.0.0.1:8765
```

## 주의사항
- **첫 빌드**: 5~10분 소요 (dependencies 설치)
- **모델 다운로드**: faster-whisper large-v3 (~3GB, 초회만)
- **업로드 제한**: Railway 무료 티어는 100MB 파일 크기 제한
- **메모리**: 1GB 이상 권장

## 커스터마이징
환경변수로 ASR 모델 변경:
- Railway 대시보드 → Variables
- `ASR_MODEL=base` (빠르지만 정확도 낮음)
- `ASR_MODEL=medium` (균형)
- `ASR_MODEL=large-v3` (정확도 높음, 기본값)
