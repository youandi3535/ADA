# ADA 프로젝트 — 개발 환경 셋업 가이드

> 대상: 신규 합류 팀원 (Windows 사용자)
> 환경: Windows 10/11 + WSL2 + Ubuntu 22.04 + Python 3.10 + VS Code
> 예상 소요 시간: 약 60~90분 (네트워크 속도에 따라 ±20분)

---

## 0. 시작 전 확인

- [ ] Windows 10 (빌드 19041+) 또는 Windows 11
- [ ] 관리자 권한 사용 가능
- [ ] 디스크 여유 공간 20GB 이상
- [ ] GitHub 계정 + 팀 레포 (`youandi3535/ADA`) 접근 권한 부여됨
- [ ] VS Code 설치 (없으면 https://code.visualstudio.com/ 에서 받기)

---

## 1단계 — WSL2 + Ubuntu 22.04 설치

### 1.1 WSL 설치 확인

PowerShell을 **관리자 권한**으로 열고:

```powershell
wsl --version
```

- 버전이 나오면 → 이미 설치됨, 1.2로 이동
- "명령을 찾을 수 없음" → 아래 1.2 진행

### 1.2 Ubuntu 22.04 설치

```powershell
wsl --install -d Ubuntu-22.04
```

설치가 끝나면 **재부팅**.

### 1.3 Ubuntu 첫 실행

시작메뉴 → **"Ubuntu 22.04"** 검색해서 실행. 검은 터미널이 뜨면서:

```
Enter new UNIX username: <영문 소문자 유저명 입력>
New password: <비밀번호 입력 — 화면에 안 보이는 게 정상>
Retype new password: <한 번 더>
```

> ⚠️ 이 유저명은 본 가이드에서 `<유저명>` 으로 표기됩니다. 본인이 설정한 이름으로 바꿔서 명령어 실행하세요. (예: `user`, `ada` 등)

프롬프트가 `<유저명>@DESKTOP-XXX:~$` 형태로 뜨면 진입 완료.

### 1.4 설치 확인

PowerShell에서:
```powershell
wsl -l -v
```

다음과 같이 나오면 정상:
```
  NAME              STATE           VERSION
* Ubuntu-22.04      Running         2
```

---

## 2단계 — Ubuntu 환경 준비

**Ubuntu 22.04 터미널**에서 (PowerShell 아님!):

### 2.1 패키지 목록 최신화

```bash
sudo apt update && sudo apt upgrade -y
```

(비밀번호 입력. Y/n 묻는 게 나오면 엔터)

### 2.2 필수 패키지 설치

```bash
sudo apt install -y \
    python3.10 python3.10-venv python3.10-dev python3-pip \
    git build-essential libgomp1 libpq-dev curl
```

> Ubuntu 22.04는 Python 3.10이 기본 내장이라 보통 이미 깔려있음. 위 명령은 venv 등 누락 모듈 보강.

### 2.3 확인

```bash
python3.10 --version    # → Python 3.10.x
git --version           # → git version 2.x.x
pip3 --version          # → pip ... (python 3.10)
```

세 줄 모두 버전이 나오면 OK.

---

## 3단계 — Git 설정 + GitHub 인증

### 3.1 Git 사용자 정보 설정

본인 GitHub 계정 정보로:

```bash
git config --global user.name "본인_GitHub_사용자명"
git config --global user.email "본인_GitHub_이메일"
```

확인:
```bash
git config --global --list
```

### 3.2 GitHub CLI 설치

```bash
sudo apt install -y gh
gh --version
```

### 3.3 GitHub 로그인

```bash
gh auth login
```

대화형으로 다음과 같이 선택:

| 질문 | 답 |
|---|---|
| What account do you want to log into? | **GitHub.com** |
| What is your preferred protocol for Git operations? | **HTTPS** |
| Authenticate Git with your GitHub credentials? | **Y** |
| How would you like to authenticate GitHub CLI? | **Login with a web browser** |

화면에 일회용 코드 표시됨:
```
! First copy your one-time code: XXXX-XXXX
- Press Enter to open github.com in your browser...
```

1. 코드 복사 (드래그하면 자동 복사)
2. 엔터 → 브라우저 자동 실행 (안 되면 출력된 URL을 수동으로 윈도우 브라우저에 붙여넣기)
3. GitHub에서 코드 입력 → Authorize
4. 터미널에 `✓ Logged in as <본인계정>` 표시되면 성공

### 3.4 인증 확인

```bash
gh auth status
```

---

## 4단계 — 프로젝트 클론

### 4.1 작업 폴더 생성 + 클론

```bash
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/youandi3535/ADA.git
cd ADA
```

> ⚠️ **반드시 `~/projects` (리눅스 홈) 안에 클론할 것.** `/mnt/c/...` 같은 Windows 디스크에 두면 속도가 10배 이상 느려짐.

### 4.2 클론 확인

```bash
pwd          # → /home/<유저명>/projects/ADA
ls           # → README.md  agents  work-orders
git status   # → On branch main / nothing to commit
git remote -v  # → origin  https://github.com/youandi3535/ADA.git
```

---

## 5단계 — Python 가상환경 (venv)

### 5.1 venv 생성

ADA 폴더 안에서:

```bash
python3.10 -m venv .venv
```

확인:
```bash
ls -la .venv    # → bin, include, lib, pyvenv.cfg 존재
```

### 5.2 활성화 + pip 최신화

```bash
source .venv/bin/activate
pip install --upgrade pip
```

프롬프트 앞에 **`(.venv)`** 가 붙으면 활성화 성공:
```
(.venv) <유저명>@DESKTOP-XXX:~/projects/ADA$
```

### 5.3 확인

```bash
which python       # → /home/<유저명>/projects/ADA/.venv/bin/python
python --version   # → Python 3.10.x
pip --version      # → pip 25+ from .../ADA/.venv/...
```

### 5.4 .gitignore 확인

```bash
cat .gitignore
```

`.venv/`, `.env`, `__pycache__/` 가 포함되어 있어야 함 (현재 레포에 이미 셋업되어 있음).

---

## 6단계 — VS Code WSL Remote 셋업

### 6.1 윈도우 VS Code 확장 설치

윈도우 VS Code 실행 → 확장 사이드바(`Ctrl+Shift+X`) → 검색:

```
WSL
```

→ **Microsoft 제작 "WSL"** 확장 설치 (윈도우 쪽에).

### 6.2 WSL 폴더 열기

`F1` 또는 `Ctrl+Shift+P` → 검색:

```
WSL: Open Folder in WSL...
```

경로 입력란에:
```
/home/<유저명>/projects/ADA
```

→ 확인. 첫 연결 시 **"Installing VS Code Server..."** 진행 (10~30초).

### 6.3 연결 확인

- 상단 탭: **`ADA [WSL: Ubuntu-22.04]`** ✓
- 좌측 하단 모서리: **`WSL: Ubuntu-22.04`** 초록 박스 ✓

---

## 7단계 — VS Code 확장 설치 (WSL 쪽에)

> ⚠️ 모든 확장은 **`WSL: Ubuntu-22.04에 설치`** 버튼으로 설치. 윈도우 쪽 아님.

`Ctrl+Shift+X` 로 확장 사이드바 열고 검색해서 설치:

### 7.1 필수

| 확장 | 검색어 | 제작자 |
|---|---|---|
| Python | `python` | Microsoft |

> Python 깔면 **Pylance**, **Python Debugger** 자동 함께 설치됨.

### 7.2 강력 추천

| 확장 | 검색어 | 제작자 |
|---|---|---|
| Ruff | `ruff` | Astral Software |
| Docker | `docker` | Microsoft |

### 7.3 설치 위치 확인

검색창 비우면 카테고리별로 분리됨:
- `로컬 - 설치됨` (윈도우 쪽)
- `WSL: Ubuntu-22.04 - 설치됨` ← Python, Ruff, Docker 여기 있어야 함

---

## 8단계 — Python 인터프리터 지정

VS Code에서:

1. `Ctrl+Shift+P` → `Python: Select Interpreter`
2. 목록에서 선택:
   ```
   Python 3.10.x ('.venv': venv)   ./.venv/bin/python
   ```
3. 목록에 안 보이면 → `+ 인터프리터 경로 입력...` → 직접 입력:
   ```
   /home/<유저명>/projects/ADA/.venv/bin/python
   ```

---

## 9단계 — 검증

### 9.1 VS Code 터미널 열기

`Ctrl + ~` (또는 메뉴 → 터미널 → 새 터미널).

프롬프트가 자동으로 venv 활성화된 상태여야 함:
```
(.venv) <유저명>@DESKTOP-XXX:~/projects/ADA$
```

### 9.2 최종 확인

```bash
which python      # → /home/<유저명>/projects/ADA/.venv/bin/python
python --version  # → Python 3.10.x
```

✅ 여기까지 통과하면 기본 셋업 완료.

---

## 10단계 — Claude Code 셋업 (선택, 권장)

> Claude Code 사용 계정이 있는 팀원만 진행. Claude Pro/Max/Teams/Enterprise 또는 Console API 계정 필요.

### 10.1 Node.js 설치 (nvm 방식)

WSL 터미널에서:

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.bashrc
nvm install --lts
nvm use --lts
node --version    # → v20+ 또는 v22+
```

> ⚠️ `sudo npm` 절대 쓰지 말 것. nvm 사용 시 권한 문제 없음.

### 10.2 Claude Code CLI 설치

```bash
npm install -g @anthropic-ai/claude-code
claude --version
```

### 10.3 로그인

```bash
claude login
```

브라우저에서 인증 후 터미널로 복귀.

### 10.4 VS Code 확장 설치

확장 사이드바에서 검색:
```
Claude Code
```

- 제작자: **Anthropic**
- 버튼: **`WSL: Ubuntu-22.04에 설치`**

설치 후 `Ctrl+Shift+P` → `Claude Code: Focus on Claude Code View` 또는 좌측 활동 표시줄에서 Claude 아이콘 클릭.

---

## 일상 워크플로우 (셋업 이후 매일)

1. 시작메뉴 → **Ubuntu 22.04** 실행 (또는 VS Code 켜면 자동 연결)
2. 이동: `cd ~/projects/ADA`
3. (필요 시) venv 활성화: `source .venv/bin/activate`
4. VS Code 열기: `code .`
5. 최신 코드 받기: `git pull origin main`
6. 새 작업 브랜치: `git checkout -b feat/내기능명`
7. 작업 → `git add` → `git commit -m "feat: ..."` → `git push -u origin feat/내기능명`
8. GitHub에서 PR 생성 → 팀 리뷰 → main 머지

---

## 자주 만나는 문제 & 해결

### Q1. `code .` 가 동작 안 함
→ 윈도우 VS Code 한 번 닫고 재시작. 또는 `wsl --shutdown` 후 Ubuntu 재실행.

### Q2. WSL 안에서 인터넷 느림
→ 프로젝트 위치 확인. `/mnt/c/` 아래에 있으면 안 됨. 반드시 `~/projects/` 아래여야 함.

### Q3. VS Code 좌측 하단에 `WSL: Ubuntu-22.04` 안 보임
→ WSL 확장이 윈도우 쪽에 설치되었는지 확인. `F1` → `WSL: Connect to WSL` 명령으로 직접 연결.

### Q4. `pip install` 시 권한 에러
→ venv 활성화 안 된 상태. `source .venv/bin/activate` 다시 실행. 프롬프트 앞 `(.venv)` 확인.

### Q5. `gh auth login` 브라우저 자동 실행 실패
→ 무시하고 출력된 URL을 윈도우 브라우저에 수동으로 붙여넣어 진행. (`sudo apt install -y wslu` 깔면 다음부터 자동 실행됨)

### Q6. WSL 메모리/디스크 너무 차지
→ `%USERPROFILE%\.wslconfig` 파일 만들고 다음 내용 추가:
```ini
[wsl2]
memory=8GB
processors=4
```
저장 후 PowerShell에서 `wsl --shutdown` → 다시 실행.

---

## 체크리스트 (셋업 완료 검증)

- [ ] `wsl -l -v` → Ubuntu-22.04 Running
- [ ] Ubuntu에서 `python3.10 --version` → 3.10.x
- [ ] `gh auth status` → Logged in
- [ ] `~/projects/ADA` 폴더 존재, `git status` 깨끗
- [ ] `(.venv)` 활성화 상태에서 `which python` → venv 경로
- [ ] VS Code 좌측 하단 `WSL: Ubuntu-22.04` 표시
- [ ] VS Code 터미널 열면 자동 `(.venv)` 활성화
- [ ] (선택) `claude --version` 정상 표시

---

## 참고 링크

- WSL 공식 문서: https://learn.microsoft.com/ko-kr/windows/wsl/
- VS Code Remote-WSL: https://code.visualstudio.com/docs/remote/wsl
- Python venv: https://docs.python.org/3.10/library/venv.html
- GitHub CLI: https://cli.github.com/
- Claude Code: https://code.claude.com/docs/

---

## 작성/문의

- 작성: youandi3535 (CI/CD 및 인프라 구축 담당)
- 문서 버전: v1.0
- 막히는 부분 있으면 팀 채널에 스크린샷과 함께 문의
