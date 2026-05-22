<!--
ADA v2 — Pull Request Template
이 템플릿은 매 PR 생성 시 자동 로드됩니다.
4명 병렬 작업의 자가검증 도구로 사용하세요.
-->

## 📋 작업 정보

**Day**: Day __ (예: Day 3)

**역할** (하나만 체크):
- [ ] HJ — 시스템·메타·인프라
- [ ] CS — timeseries
- [ ] NY — anomaly
- [ ] jh — tabular

**브랜치**: `feat/{본인}-day{N}` → `main`

---

## 🎯 변경 요약

> 이 PR 에서 한 일을 2~3 줄로 (DoD 의 결과물 기준)

-
-

---

## ✅ DoD 체크리스트

> `TEAM_10DAY_SCHEDULE.md` 의 해당 Day · 본인 역할 행을 복붙하여 체크

- [ ]
- [ ]

---

## 🛡️ 영역 자가 검증 (필수)

다음 명령을 로컬에서 실행하고, 결과가 **본인 허용 경로에만** 있는지 확인:

```bash
git diff --stat origin/main..HEAD
```

- [ ] 본인 영역만 수정됨 ✅
- [ ] 공유 파일 수정 있음 ⚠️ — 사유:
  > _____________________

> 공유 파일 수정 시 CODEOWNERS 가 자동으로 HJ 리뷰를 요청합니다.

---

## 🧪 테스트 결과

다음 모두 그린이어야 머지 가능:

- [ ] `pytest tests/handlers/{본인카테고리}/ -q` 그린
- [ ] `pytest tests/ -q` (전체) 그린
- [ ] `ruff check {본인영역}/` 그린
- [ ] (해당 시) MLflow 에 학습 run 기록 확인

---

## 🤝 Contract Day 여부

본 PR 이 Day 4 / 6 / 8 / 9 작업이면 체크:

- [ ] **Day 4** — Guardrails 강화
- [ ] **Day 6** — `state.best_params` 추가 (인터페이스 변경)
- [ ] **Day 8** — InsightAgent 가드레일
- [ ] **Day 9** — `outputs/base.py` 훅 시그니처

Contract Day 면 추가 확인:
- [ ] 인터페이스 변경사항 슬랙/회의로 사전 공지 완료
- [ ] 본 PR 머지 후 다른 멤버가 rebase 해야 함을 안내

---

## 🔗 관련 (선택)

- 이슈 / 티켓:
- 관련 PR:
- 참고 문서:

---

## 📝 추가 메모 (선택)

> 리뷰어가 알면 좋을 컨텍스트, 의사결정 사유, 알려진 한계 등

-

---

<!--
머지 전 마지막 체크:
1) Required status checks 모두 그린
2) Code owner 리뷰 완료
3) Conversation resolution 완료
4) Branch up-to-date with main (rebase 완료)
-->
