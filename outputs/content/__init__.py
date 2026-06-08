"""outputs.content — 슬라이드 콘텐츠 생성 & 검증 (Phase 3).

모듈:
    slide_writer.py      — SlideContentGenerator (LLM caller 주입 가능)
    so_what_scorer.py    — So-What 6 항목 자가 채점
    tone_calibrator.py   — 청중별 톤·종결어미 조정
    terminology.py       — 보고서 단위 용어 사전 + 일관성 강제
    speaker_notes.py     — 화자 노트 4파트 생성
    qa_anticipator.py    — Q&A 예상 + 백업 슬라이드 후보
"""
