"""lesson_embeddings.kb_id UNIQUE 제약 추가 — KBRAG.index_lesson 의 ON CONFLICT 정상화.

Revision ID: 0003_lesson_unique
Revises: 0002_conversation_log
Create Date: 2026-05-26

배경:
    Day 1 (HJ) — SelfLearningAgent 가 distill 후 KBRAG.index_lesson 을 자동 호출하면서
    `INSERT ... ON CONFLICT (kb_id) DO UPDATE` 가 처음으로 호출 경로에 닿음.
    그러나 001_initial_v2_schema 가 lesson_embeddings.kb_id 를 FK 만으로 생성해
    Postgres 는 매칭되는 UNIQUE/EXCLUSION constraint 부재로 ON CONFLICT 를 거부.

수정:
    1) 잠재적 중복 데이터를 안전하게 정리 (가장 오래된 row 만 보존)
    2) UNIQUE (kb_id) 제약 추가
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0003_lesson_unique"
down_revision: Union[str, None] = "0002_conversation_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) 중복 정리 — 같은 kb_id 가 여러 row 면 가장 오래된 1건만 남김
    #    (KBRAG.index_lesson 은 사실상 upsert 의도였으므로 마지막 색인 값을 손해보지 않도록
    #     created_at DESC 로 정렬해 최신 1건 보존)
    op.execute(
        """
        DELETE FROM lesson_embeddings le
        USING (
            SELECT kb_id, MAX(created_at) AS max_created
            FROM lesson_embeddings
            WHERE kb_id IS NOT NULL
            GROUP BY kb_id
            HAVING COUNT(*) > 1
        ) dup
        WHERE le.kb_id = dup.kb_id
          AND le.created_at < dup.max_created;
        """
    )

    # 2) UNIQUE 제약 추가
    op.create_unique_constraint(
        "uq_lesson_embeddings_kb_id",
        "lesson_embeddings",
        ["kb_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_lesson_embeddings_kb_id",
        "lesson_embeddings",
        type_="unique",
    )
