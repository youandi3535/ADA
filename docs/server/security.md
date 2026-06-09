# VPS 보안 설정 기록

## SSH 설정 (`/etc/ssh/sshd_config`)

| 항목 | 값 | 설명 |
|---|---|---|
| `PasswordAuthentication` | `no` | 패스워드 로그인 차단 |
| `PermitRootLogin` | `no` | root 직접 로그인 차단 |
| `AllowUsers` | `ada` | ada 계정만 SSH 허용 |
| `MaxAuthTries` | `3` | 인증 시도 횟수 제한 |
| `ClientAliveInterval` | `300` | 5분 idle 시 연결 종료 |

적용일: 2026-06-09

---

## SSH 인가 키 (`~/.ssh/authorized_keys`)

| 키 이름 | 용도 |
|---|---|
| 나연-노트북(관리자) | 팀원 접속 |
| 정현-노트북 | 팀원 접속 |
| 효중-학원PC | 팀원 접속 |
| 창선-학원PC | 팀원 접속 |
| 정현-학원PC | 팀원 접속 |
| 나연-학원PC(관리) | 팀원 접속 |
| [서버]VPS-CICD배포 | GitHub Actions CI/CD 배포 |
| [백업]학원리눅스서버컴 | 로컬 서버 백업 pull |

> 키 값은 이 파일에 기록하지 않음. VPS `~/.ssh/authorized_keys` 직접 확인.

---

## 방화벽 (`ufw`)

| 포트 | 허용 대상 | 용도 |
|---|---|---|
| 22/tcp | 전체 | SSH |
| 80/tcp | 전체 | HTTP (→ HTTPS 리다이렉트) |
| 443/tcp | 전체 | HTTPS |
| 11434/tcp | 172.16.0.0/12 | Ollama (Docker 내부망만) |

---

## fail2ban

- 대상: `sshd`
- SSH 무차별 대입 공격 자동 차단
- 확인: `sudo fail2ban-client status sshd`

---

## TLS 인증서

- 발급: Let's Encrypt (certbot)
- 도메인: ada-aiagent.com
- 만료: 2026-09-07
- 자동갱신: systemd timer (`certbot.timer`)
- 갱신 훅: `/etc/letsencrypt/renewal-hooks/pre/stop-nginx.sh`, `post/start-nginx.sh`, `deploy/restart-nginx.sh`
