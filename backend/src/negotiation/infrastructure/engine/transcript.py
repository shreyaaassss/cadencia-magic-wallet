"""Transcript building logic extracted from NeutralEngine.

Handles serialization of offer history for LLM context and
conversation transcript building for RAG ingestion.
"""

from __future__ import annotations

from decimal import Decimal


def serialize_offer_history(offers: list, max_items: int = 20) -> list[dict]:
    """Serialize last N offers for LLM context (no PII).

    Returns a list of dicts with: round, role, price, terms, is_human.
    """
    return [
        {
            "round": o.round_number.value,
            "role": o.proposer_role.value,
            "price": float(o.price.amount),
            "terms": o.terms,
            "is_human": o.is_human_override,
        }
        for o in offers[-max_items:]
    ]


def build_rag_query(
    rfq_parsed_fields: dict | None,
    is_buyer: bool,
) -> str:
    """Build a semantically rich RAG query from RFQ context.

    Avoids UUIDs and round numbers — they have zero semantic value
    and waste embedding dimensionality.
    """
    _rpf = rfq_parsed_fields or {}
    product_hint = _rpf.get("product", "")
    parts = [f"{product_hint} negotiation" if product_hint else "commodity negotiation"]

    if _rpf.get("quantity"):
        parts.append(f"{_rpf['quantity']} {_rpf.get('quantity_unit', '')}")
    if _rpf.get("budget_max") and is_buyer:
        parts.append(f"budget {_rpf['budget_max']} INR")
    if _rpf.get("geography") or _rpf.get("delivery_city"):
        parts.append(f"{_rpf.get('geography') or _rpf.get('delivery_city', '')} delivery")
    if _rpf.get("_matched_item_grade"):
        parts.append(f"grade {_rpf['_matched_item_grade']}")

    return " ".join(parts)


def compute_price_gap(buyer_price: Decimal, seller_price: Decimal) -> float:
    """Compute the percentage gap between buyer and seller prices."""
    if seller_price <= 0:
        return 1.0
    return float(abs(seller_price - buyer_price) / seller_price)
