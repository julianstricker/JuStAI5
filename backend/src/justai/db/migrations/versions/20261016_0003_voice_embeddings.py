"""voice embeddings (voice profiles with consent)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-16 10:30:00
"""
from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "voice_embeddings",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=256), nullable=False),
        sa.Column("seconds", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"], name=op.f("fk_voice_embeddings_person_id_people"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_voice_embeddings")),
    )
    op.create_index(op.f("ix_voice_embeddings_person_id"), "voice_embeddings", ["person_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_voice_embeddings_person_id"), table_name="voice_embeddings")
    op.drop_table("voice_embeddings")
