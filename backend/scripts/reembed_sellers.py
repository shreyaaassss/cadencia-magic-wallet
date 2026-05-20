#!/usr/bin/env python3
"""Re-embed all existing seller capability profiles using Google text-embedding-004.

Run this ONCE after setting GEMINI_API_KEY to backfill real semantic embeddings
for all sellers who previously had random hash embeddings.

Usage (from backend/ directory):
    GEMINI_API_KEY=<your-key> python scripts/reembed_sellers.py

What it does:
    1. Loads every CapabilityProfile from the DB
    2. Builds enriched embedding text (profile + all active catalogue items)
    3. Calls text-embedding-004 at 384 dims via the same _gemini_embed helper
    4. Writes updated embeddings back to the DB
    5. Prints a progress summary
"""

from __future__ import annotations

import asyncio
import os
import sys

# Ensure we can import src.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main() -> None:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("ERROR: GEMINI_API_KEY is not set. Export it before running this script.")
        sys.exit(1)

    from src.marketplace.infrastructure.rfq_parser import _gemini_embed
    from src.shared.infrastructure.db.session import get_session_factory
    from sqlalchemy import select

    factory = get_session_factory()

    async with factory() as session:
        # Load all capability profiles
        from src.marketplace.infrastructure.models import (
            CapabilityProfileModel,
            CatalogueItemModel,
        )

        profiles_result = await session.execute(select(CapabilityProfileModel))
        profiles = profiles_result.scalars().all()
        print(f"Found {len(profiles)} capability profiles to re-embed.")

        ok = 0
        failed = 0

        for profile in profiles:
            try:
                # Build the same enriched text as _recompute_embedding_standalone
                text_parts = [
                    profile.profile_text or "",
                    " ".join(profile.product_categories or []),
                    " ".join(profile.geography_scope or []),
                    profile.industry_vertical or "",
                ]

                # Fetch active catalogue items for this seller
                cat_result = await session.execute(
                    select(CatalogueItemModel).where(
                        CatalogueItemModel.enterprise_id == profile.enterprise_id,
                        CatalogueItemModel.is_active == True,  # noqa: E712
                    )
                )
                cat_items = cat_result.scalars().all()
                catalogue_lines = []
                for item in cat_items:
                    parts = [item.product_name, item.hsn_code, item.product_category]
                    if item.grade:
                        parts.append(item.grade)
                    if item.specification_text:
                        parts.append(item.specification_text[:200])
                    catalogue_lines.append(" | ".join(p for p in parts if p))
                if catalogue_lines:
                    text_parts.append(". ".join(catalogue_lines))

                text = " ".join(p for p in text_parts if p).strip()
                if not text:
                    print(f"  SKIP {profile.enterprise_id} — empty profile text")
                    continue

                # Call Gemini text-embedding-004
                embedding = await _gemini_embed(text)
                assert len(embedding) == 384, f"Expected 384 dims, got {len(embedding)}"

                profile.set_embedding(embedding)
                ok += 1
                print(f"  OK   {profile.enterprise_id} | catalogue_items={len(cat_items)}")

                # Small delay to respect 1 req/sec free tier rate limit
                await asyncio.sleep(0.7)

            except Exception as exc:
                failed += 1
                print(f"  FAIL {profile.enterprise_id} — {exc}")

        await session.commit()
        print(f"\nDone. Re-embedded: {ok}  Failed: {failed}")


if __name__ == "__main__":
    asyncio.run(main())
