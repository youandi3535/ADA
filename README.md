# ADA - AI 에이전트 프로젝트

## 프로젝트 개요
데이터 자동 분석 AI 에이전트 시스템 개발 프로젝트입니다.

## 팀 구성
- **CI/CD 및 인프라 구축 담당**: youandi3535
- **백엔드 환경 담당**: 
- **에이전트 로직 담당(A)**:
- **에이전트 로직 담당(B)**:

## 프로젝트 구조
\`\`\`
ADA/
├── agents/        # 에이전트 모듈
├── work-orders/   # 에이전트 구축 작업 명령
└── .github/       # CI/CD 워크플로우
\`\`\`

## 개발 환경
- Python 3.11
- Docker
- WSL 2 (Ubuntu)

## 브랜치 전략
- \`main\`: 안정 버전 (직접 push 금지)
- \`feat/기능명\`: 새 기능 개발
- \`fix/버그명\`: 버그 수정
- \`ci/항목명\`: CI/CD 관련

## 작업 흐름
1. \`main\`에서 최신 코드 받기: \`git pull origin main\`
2. 새 브랜치 생성: \`git checkout -b feat/내기능\`
3. 작업 후 커밋: \`git commit -m "feat: 기능 설명"\`
4. push 후 PR 생성: \`git push -u origin feat/내기능\`
5. CI 통과 + 리뷰 승인 → 머지
