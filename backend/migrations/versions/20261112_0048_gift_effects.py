"""Gift opening effects (DM-016): ``messages.gift_effect``.

The sender of a gift picks what plays on screen when it is opened (petals, a water splash,
confetti or hearts). Like the gift catalog, the list is checked by the API, not here. Gifts sent
before this revision open with petals.

Revision ID: 0048
Revises: 0047
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("gift_effect", sa.Text(), nullable=True))
    op.execute("UPDATE messages SET gift_effect = 'petals' WHERE kind = 'gift'")
    op.create_check_constraint(
        op.f("ck_messages__gift_effect_per_kind"),
        "messages",
        "(kind = 'gift') = (gift_effect IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_messages__gift_effect_length"), "messages", "char_length(gift_effect) <= 32"
    )


def downgrade() -> None:
    for name in ("gift_effect_length", "gift_effect_per_kind"):
        op.drop_constraint(op.f(f"ck_messages__{name}"), "messages", type_="check")
    op.drop_column("messages", "gift_effect")
