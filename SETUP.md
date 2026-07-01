# 캡컷 자동 편집 에이전트 배포 가이드

## 🚀 Railway로 배포 (권장)

### Step 1: Railway 계정 생성
https://railway.app → Sign up with GitHub

### Step 2: 프로젝트 생성
1. Railway 대시보드 접속
2. **"Create New Project"** → **"Deploy from GitHub repo"**
3. GitHub 저장소 선택 (이 프로젝트)
4. **Deploy** 클릭

### Step 3: 환경 설정
Railway 대시보드에서:
- **Variables** 탭
- `ASR_MODEL=large-v3` (기본값, 권장)
- 또는 `ASR_MODEL=base` (빠르지만 정확도 낮음)

### Step 4: 배포 모니터링
- **Deployments** 탭에서 배포 상태 확인
- 빌드 완료 후 자동으로 URL 생성됨
- 예: `https://your-app-name.up.railway.app`

---

## 💻 로컬 개발 (로컬에서만 사용)

### 설치
```bash
cd /Users/hyunseo/캡컷
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 실행
```bash
python serve.py
# → http://127.0.0.1:8765
```

---

## 📝 사용 방법

### 웹 브라우저에서
1. Railway URL 또는 localhost:8765 접속
2. 영상 파일 드래그/드롭
3. 자동 편집 결과 확인
4. CapCut에서 드래프트 열기

### 명령줄에서
```bash
python cli_jumpcut.py video.mp4 --subtitle --mode shorts
```

---

## ⚠️ 주의사항

### 클라우드 배포 시
- **첫 빌드**: 10~15분 소요
- **모델 다운로드**: faster-whisper 초회만 3GB 다운로드
- **파일 크기**: Railway 무료 티어 100MB 제한
- **타임아웃**: 장시간 처리는 타임아웃될 수 있음

### 로컬 개발 시
- mlx-whisper 사용 가능 (Mac arm64에서 빠름)
- 대신 requirements.txt에서 faster-whisper → mlx-whisper로 변경 필요

---

## 🔧 트러블슈팅

### 배포 실패
- Railway 로그 확인
- Dockerfile 문법 체크
- ffmpeg 설치 확인

### 느린 첫 ASR
- 모델 캐시 다운로드 중
- 시간이 걸림 (15분 이상)

### 메모리 부족
- Railway Pro로 업그레이드
- 또는 ASR_MODEL=base 사용

---

## 🎯 다음 단계

배포 후:
1. 테스트 영상 업로드해서 작동 확인
2. CapCut에서 생성된 드래프트 확인
3. 필요시 자막 스타일 조정 (config.py)
