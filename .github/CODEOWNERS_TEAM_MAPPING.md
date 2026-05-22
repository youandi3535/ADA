# CODEOWNERS — Team Username Mapping

> `.github/CODEOWNERS` 의 짧은 핸들을 실제 GitHub username 으로 매핑하는
> 절차 문서입니다.

## 🎯 왜 필요한가

GitHub 의 "Require review from Code Owners" 룰이 자동으로 작동하려면,
CODEOWNERS 파일의 핸들이 **실제로 존재하는 GitHub 계정**이어야 합니다.
현재는 짧은 핸들 (`@hj`, `@cs`, `@ny`, `@jh`) 로 작성되어 있어,
실제 GitHub username 과 다르면 자동 리뷰 지정이 동작하지 않습니다.

---

## 📋 매핑 표 (작성 필요)

| 짧은 핸들 | 멤버 | 담당 영역 | 실제 GitHub username |
|---|---|---|---|
| `@hj` | HJ | 시스템·메타·인프라 | `@youandi3535`  ← 실제 username 으로 확정/수정 |
| `@cs` | CS | timeseries     | `@________________` |
| `@ny` | NY | anomaly        | `@________________` |
| `@jh` | jh | tabular        | `@________________` |

> 위 표의 빈 칸을 실제 username 으로 채운 뒤 아래 절차 진행.
> 핸들과 실제 username 이 동일하면 (예: GitHub username 도 `cs`) 치환 불필요.

---

## 🔧 매핑 적용 방법

### 1) 사전 준비

GitHub 레포 Settings → Collaborators 에서 4명 모두 **Write 권한** 이상으로 추가되어 있어야 함.
(추가 안 된 username 은 CODEOWNERS 에서 무시됨)

### 2) CODEOWNERS 일괄 치환 (핸들과 username 이 다른 경우)

```bash
cd /path/to/ADA

# 백업
cp .github/CODEOWNERS .github/CODEOWNERS.bak

# 일괄 치환 (실제 username 으로 교체 — @hj 는 이미 youandi3535 가능)
sed -i 's/@hj\b/@youandi3535/g'          .github/CODEOWNERS
sed -i 's/@cs\b/@__realname_cs/g'        .github/CODEOWNERS
sed -i 's/@ny\b/@__realname_ny/g'        .github/CODEOWNERS
sed -i 's/@jh\b/@__realname_jh/g'        .github/CODEOWNERS

# 확인
grep "@" .github/CODEOWNERS | head -20
```

> macOS 의 경우 `sed -i ''` (BSD sed) 또는 `gsed` 사용.

### 3) 커밋 & 푸시

```bash
git checkout -b chore/codeowners-mapping
git add .github/CODEOWNERS
git rm .github/CODEOWNERS.bak  # 백업 제거
git commit -m "chore(HJ): map CODEOWNERS handles to real GitHub usernames"
git push origin chore/codeowners-mapping
```

### 4) PR 생성 후 자가검증

PR 페이지에서 **Reviewers 섹션을 확인** — 자동으로 4명이 영역별로 지정돼야 함:
- `agents/handlers/timeseries/` 변경 시 → CS 자동 지정
- `agents/handlers/anomaly/`    변경 시 → NY 자동 지정
- `agents/handlers/tabular/`    변경 시 → jh 자동 지정
- HJ 영역 변경 시              → HJ 자동 지정

---

## ✅ 매핑 완료 후 확인사항

1. [ ] GitHub 레포 Settings → Collaborators 에 4명 모두 추가됨
2. [ ] CODEOWNERS 파일에 핸들이 모두 실제 username 으로 치환됨
3. [ ] Settings → Branches 의 `main` 룰에 "Require review from Code Owners" 켜짐
4. [ ] 시험 PR 1회로 자동 리뷰어 지정 동작 확인

---

## 🔄 매핑 변경 (멤버 교체) 시

- 본 파일의 매핑 표 업데이트
- 위 sed 명령으로 CODEOWNERS 재치환
- 별도 PR 로 커밋 (`chore: update CODEOWNERS for new member X`)
- 신규 멤버에게 `git config user.email` 설정 안내 (`scripts/dev/check_scope.sh` 패턴 매칭 대상)
- `CLAUDE.md` / `docs/PARALLEL_WORK_GUARDS.md` / `TEAM_10DAY_SCHEDULE.md` 의 멤버 표기도 함께 갱신

---

## 📚 참고

- GitHub Docs — [About code owners](https://docs.github.com/en/repositories/managing-your-repositories-settings-and-features/customizing-your-repository/about-code-owners)
- 본 레포의 `.github/CODEOWNERS` (실제 매핑 적용 파일)
- 본 레포의 `CLAUDE.md` (AI 가드레일 — CODEOWNERS 와 동기)
