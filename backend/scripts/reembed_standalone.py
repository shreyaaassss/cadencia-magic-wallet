#!/usr/bin/env python3
"""Standalone re-embedding script — no dependency on updated src code.
Run inside the backend container after setting GEMINI_API_KEY.
"""
import asyncio
import os
import sys

sys.path.insert(0, "/app")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if not GEMINI_API_KEY:
    print("ERROR: GEMINI_API_KEY not set")
    sys.exit(1)


def gemini_embed_1536(text: str) -> list:
    from google import genai
    from google.genai.types import EmbedContentConfig
    client = genai.Client(api_key=GEMINI_API_KEY)
    result = client.models.embed_content(
        model="gemini-embedding-2",
        contents=text,
        config=EmbedContentConfig(output_dimensionality=1536),
    )
    return list(result.embeddings[0].values)


async def main():
    import json
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text
    import os

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        # Try loading from .env.production
        try:
            with open("/app/.env.production") as f:
                for line in f:
                    if line.startswith("DATABASE_URL="):
                        db_url = line.strip().split("=", 1)[1]
                        break
        except FileNotFoundError:
            pass
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    engine = create_async_engine(db_url, echo=False)

    async with engine.connect() as conn:
        # Fetch all capability profiles
        result = await conn.execute(text(
            "SELECT id, enterprise_id, profile_text, commodities, "
            "geographies_served, industry_vertical FROM capability_profiles"
        ))
        profiles = result.fetchall()
        print(f"Found {len(profiles)} seller profiles to re-embed.")

        ok = failed = 0
        for row in profiles:
            profile_id = row[0]
            enterprise_id = row[1]
            profile_text = row[2] or ""
            commodities = row[3] or []
            geographies = row[4] or []
            industry = row[5] or ""

            try:
                # Fetch active catalogue items for this enterprise
                cat_result = await conn.execute(text(
                    "SELECT product_name, hsn_code, product_category "
                    "FROM catalogue_items WHERE enterprise_id = :eid AND is_active = true"
                ), {"eid": enterprise_id})
                cat_items = cat_result.fetchall()

                text_parts = [
                    profile_text,
                    " ".join(commodities) if isinstance(commodities, list) else str(commodities),
                    " ".join(geographies) if isinstance(geographies, list) else str(geographies),
                    industry,
                ]
                lines = [
                    " | ".join(p for p in [r[0], r[1], r[2]] if p)
                    for r in cat_items
                ]
                if lines:
                    text_parts.append(". ".join(lines))

                embed_text = " ".join(p for p in text_parts if p).strip()
                if not embed_text:
                    print(f"  SKIP {enterprise_id} — empty text")
                    continue

                import asyncio as _a
                vec = await _a.to_thread(gemini_embed_1536, embed_text)
                assert len(vec) == 1536

                # Write directly via raw SQL — no ORM FK resolution needed
                vec_str = "[" + ",".join(str(v) for v in vec) + "]"
                await conn.execute(text(
                    "UPDATE capability_profiles SET embedding = :vec WHERE id = :id"
                ), {"vec": vec_str, "id": profile_id})
                await conn.commit()

                ok += 1
                print(f"  OK   {enterprise_id} | items={len(cat_items)}")
                await asyncio.sleep(0.7)

            except Exception as e:
                failed += 1
                print(f"  FAIL {enterprise_id} — {e}")
                try:
                    await conn.rollback()  # Reset aborted transaction so next row can proceed
                except Exception:
                    pass

    await engine.dispose()
    print(f"\nDone. Re-embedded={ok}  Failed={failed}")

asyncio.run(main())
