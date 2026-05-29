"""019_generalize_seller_schema

Generalise seller capacity + capability profiles to support all industries.

Changes:
  seller_capacity_profiles:
    - monthly_production_capacity_mt  → monthly_volume + volume_unit
    - available_capacity_mt           → available_volume
    - shift_pattern                   → operating_schedule
    - max_delivery_radius_km          → service_coverage
    - preferred_transport_modes       → fulfillment_method
  capability_profiles:
    - commodities                     → products_services
  enterprises:
    - facility_type VARCHAR(30)       → VARCHAR(50)  (no enum constraint; wider options)

Revision ID: 019
Revises: 018
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── seller_capacity_profiles ─────────────────────────────────────────────

    # Drop old check constraints that reference dropped columns
    op.drop_constraint("ck_shift_pattern",    "seller_capacity_profiles", type_="check")
    op.drop_constraint("ck_capacity_positive", "seller_capacity_profiles", type_="check")

    # Add new columns (nullable first so existing rows pass NOT NULL temporarily)
    op.add_column("seller_capacity_profiles",
        sa.Column("monthly_volume",    sa.Numeric(12, 4), nullable=True))
    op.add_column("seller_capacity_profiles",
        sa.Column("volume_unit",       sa.String(20), server_default="MT", nullable=False))
    op.add_column("seller_capacity_profiles",
        sa.Column("available_volume",  sa.Numeric(12, 4), nullable=True))
    op.add_column("seller_capacity_profiles",
        sa.Column("operating_schedule", sa.String(30), server_default="STANDARD_HOURS", nullable=False))
    op.add_column("seller_capacity_profiles",
        sa.Column("service_coverage",  sa.String(20), server_default="NATIONAL", nullable=False))
    op.add_column("seller_capacity_profiles",
        sa.Column("fulfillment_method", ARRAY(sa.String), nullable=True))

    # Migrate data from old → new columns
    op.execute("""
        UPDATE seller_capacity_profiles SET
            monthly_volume   = monthly_production_capacity_mt,
            available_volume = available_capacity_mt,
            operating_schedule = CASE shift_pattern
                WHEN 'SINGLE_SHIFT' THEN 'STANDARD_HOURS'
                WHEN 'DOUBLE_SHIFT' THEN 'EXTENDED_HOURS'
                WHEN 'TRIPLE_SHIFT' THEN 'EXTENDED_HOURS'
                WHEN 'CONTINUOUS'   THEN 'TWENTY_FOUR_SEVEN'
                ELSE 'STANDARD_HOURS'
            END,
            service_coverage = CASE
                WHEN max_delivery_radius_km IS NULL    THEN 'NATIONAL'
                WHEN max_delivery_radius_km <= 200     THEN 'LOCAL'
                WHEN max_delivery_radius_km <= 1000    THEN 'REGIONAL'
                WHEN max_delivery_radius_km > 3000     THEN 'INTERNATIONAL'
                ELSE 'NATIONAL'
            END,
            fulfillment_method = COALESCE(preferred_transport_modes, ARRAY[]::VARCHAR[])
    """)

    # Now enforce NOT NULL on monthly_volume
    op.alter_column("seller_capacity_profiles", "monthly_volume", nullable=False)

    # New check constraints
    op.create_check_constraint(
        "ck_monthly_volume_positive", "seller_capacity_profiles",
        "monthly_volume > 0",
    )
    op.create_check_constraint(
        "ck_service_coverage", "seller_capacity_profiles",
        "service_coverage IN ('LOCAL','REGIONAL','NATIONAL','INTERNATIONAL')",
    )
    op.create_check_constraint(
        "ck_operating_schedule", "seller_capacity_profiles",
        "operating_schedule IN ('STANDARD_HOURS','EXTENDED_HOURS','TWENTY_FOUR_SEVEN',"
        "'PROJECT_BASED','ON_DEMAND','SEASONAL')",
    )

    # Drop old columns
    op.drop_column("seller_capacity_profiles", "monthly_production_capacity_mt")
    op.drop_column("seller_capacity_profiles", "available_capacity_mt")
    op.drop_column("seller_capacity_profiles", "shift_pattern")
    op.drop_column("seller_capacity_profiles", "max_delivery_radius_km")
    op.drop_column("seller_capacity_profiles", "preferred_transport_modes")

    # ── capability_profiles: commodities → products_services ─────────────────
    op.add_column("capability_profiles",
        sa.Column("products_services", ARRAY(sa.String), nullable=True))
    op.execute(
        "UPDATE capability_profiles "
        "SET products_services = COALESCE(commodities, ARRAY[]::VARCHAR[])"
    )
    op.drop_column("capability_profiles", "commodities")

    # ── enterprises: widen facility_type to VARCHAR(50) ──────────────────────
    op.alter_column("enterprises", "facility_type",
        type_=sa.String(50), existing_type=sa.String(30), nullable=True)


def downgrade() -> None:
    # ── enterprises ──────────────────────────────────────────────────────────
    op.alter_column("enterprises", "facility_type",
        type_=sa.String(30), existing_type=sa.String(50), nullable=True)

    # ── capability_profiles ──────────────────────────────────────────────────
    op.add_column("capability_profiles",
        sa.Column("commodities", ARRAY(sa.String), nullable=True))
    op.execute(
        "UPDATE capability_profiles "
        "SET commodities = COALESCE(products_services, ARRAY[]::VARCHAR[])"
    )
    op.drop_column("capability_profiles", "products_services")

    # ── seller_capacity_profiles ─────────────────────────────────────────────
    op.drop_constraint("ck_operating_schedule",      "seller_capacity_profiles", type_="check")
    op.drop_constraint("ck_service_coverage",        "seller_capacity_profiles", type_="check")
    op.drop_constraint("ck_monthly_volume_positive", "seller_capacity_profiles", type_="check")

    op.add_column("seller_capacity_profiles",
        sa.Column("monthly_production_capacity_mt", sa.Numeric(12, 4), nullable=True))
    op.add_column("seller_capacity_profiles",
        sa.Column("available_capacity_mt", sa.Numeric(12, 4), nullable=True))
    op.add_column("seller_capacity_profiles",
        sa.Column("shift_pattern", sa.String(30), server_default="SINGLE_SHIFT", nullable=False))
    op.add_column("seller_capacity_profiles",
        sa.Column("max_delivery_radius_km", sa.Integer, nullable=True))
    op.add_column("seller_capacity_profiles",
        sa.Column("preferred_transport_modes", ARRAY(sa.String), nullable=True))

    op.execute("""
        UPDATE seller_capacity_profiles SET
            monthly_production_capacity_mt = COALESCE(monthly_volume, 0),
            available_capacity_mt          = available_volume,
            shift_pattern = CASE operating_schedule
                WHEN 'STANDARD_HOURS'   THEN 'SINGLE_SHIFT'
                WHEN 'EXTENDED_HOURS'   THEN 'DOUBLE_SHIFT'
                WHEN 'TWENTY_FOUR_SEVEN' THEN 'CONTINUOUS'
                ELSE 'SINGLE_SHIFT'
            END,
            preferred_transport_modes = COALESCE(fulfillment_method, ARRAY[]::VARCHAR[])
    """)

    op.alter_column("seller_capacity_profiles",
        "monthly_production_capacity_mt", nullable=False)
    op.create_check_constraint(
        "ck_capacity_positive", "seller_capacity_profiles",
        "monthly_production_capacity_mt > 0",
    )
    op.create_check_constraint(
        "ck_shift_pattern", "seller_capacity_profiles",
        "shift_pattern IN ('SINGLE_SHIFT','DOUBLE_SHIFT','TRIPLE_SHIFT','CONTINUOUS')",
    )

    op.drop_column("seller_capacity_profiles", "monthly_volume")
    op.drop_column("seller_capacity_profiles", "available_volume")
    op.drop_column("seller_capacity_profiles", "volume_unit")
    op.drop_column("seller_capacity_profiles", "operating_schedule")
    op.drop_column("seller_capacity_profiles", "service_coverage")
    op.drop_column("seller_capacity_profiles", "fulfillment_method")
