"""aggiunge ruolo alle memberships

Revision ID: 82f0dfa3e9e1
Revises: 2d65904699b7
Create Date: 2026-09-03 13:15:36.232270

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '82f0dfa3e9e1'
down_revision: Union[str, None] = '2d65904699b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ruoli utente (3 settembre 2026, feedback dell'utente: "la chat è
    # piuttosto inutile" → discussione più ampia su cosa manca per essere
    # vendibile → ruoli scelti come priorità). Default "admin" per le righe
    # ESISTENTI: nessuno perde accesso che ha già — il vincolo più severo
    # ("chi si unisce con un codice invito parte come sola lettura") si
    # applica solo alle Membership create da ora in poi (vedi api/auth.py),
    # non va imposto retroattivamente su utenti reali già in uso.
    op.add_column("memberships", sa.Column("role", sa.String(length=20), nullable=False, server_default="admin"))


def downgrade() -> None:
    op.drop_column("memberships", "role")
