"""Add industry_taxonomies table with seed data

Revision ID: 022
Revises: 021
Create Date: 2026-06-06

DB-driven industry taxonomy replaces hardcoded steel assumptions.
Each industry defines its own default units, certifications, and
capacity measurement unit so the platform is truly industry-agnostic.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "industry_taxonomies",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("industry_code", sa.String(20), unique=True, nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("parent_code", sa.String(20), nullable=True),
        sa.Column("default_units", JSONB(), server_default="[]", nullable=False),
        sa.Column("default_certifications", JSONB(), server_default="[]", nullable=False),
        sa.Column("capacity_unit", sa.String(20), server_default="MT", nullable=False),
        sa.Column("is_manufacturing", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # Seed initial taxonomies
    op.execute("""
        INSERT INTO industry_taxonomies (industry_code, display_name, default_units, default_certifications, capacity_unit, is_manufacturing) VALUES
        ('METALS', 'Metals & Steel', '["MT", "KG", "COIL", "BUNDLE"]', '["ISO 9001", "BIS", "RDSO"]', 'MT', true),
        ('ELECTRONICS', 'Electronics & Technology', '["PIECE", "UNIT", "BOX"]', '["CE", "FCC", "RoHS", "BIS"]', 'UNITS', true),
        ('TEXTILES', 'Textiles & Apparel', '["METRE", "KG", "PIECE", "DOZEN"]', '["ISO 9001", "OEKO-TEX"]', 'METRES', true),
        ('CHEMICALS', 'Chemicals & Pharma', '["KG", "LITRE", "MT"]', '["ISO 9001", "GMP", "WHO-GMP", "FSSAI"]', 'MT', true),
        ('AGRICULTURE', 'Agriculture & Food', '["KG", "MT", "QUINTAL"]', '["FSSAI", "ISO 22000", "APEDA"]', 'MT', true),
        ('CONSTRUCTION', 'Construction & Building Materials', '["MT", "PIECE", "SQFT", "CUBIC_M"]', '["ISO 9001", "BIS"]', 'MT', true),
        ('MACHINERY', 'Machinery & Equipment', '["PIECE", "UNIT"]', '["ISO 9001", "CE"]', 'UNITS', true),
        ('AUTOMOTIVE', 'Automotive & Auto Parts', '["PIECE", "UNIT", "KG"]', '["IATF 16949", "ISO 9001"]', 'UNITS', true),
        ('PACKAGING', 'Packaging & Paper', '["KG", "MT", "PIECE", "REAM"]', '["ISO 9001", "FSC"]', 'MT', true),
        ('ENERGY', 'Energy & Power', '["UNIT", "KW", "PIECE"]', '["ISO 9001", "IEC"]', 'UNITS', true),
        ('SERVICES', 'Professional Services', '["UNIT", "HOUR"]', '[]', 'UNITS', false),
        ('OTHERS', 'Others', '["PIECE", "KG", "UNIT"]', '[]', 'UNITS', false)
        ON CONFLICT (industry_code) DO NOTHING
    """)


def downgrade() -> None:
    op.drop_table("industry_taxonomies")
