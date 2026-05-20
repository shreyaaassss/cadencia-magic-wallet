import asyncio
from src.marketplace.infrastructure.rfq_parser import _gemini_embed, get_document_parser
from src.marketplace.infrastructure.rfq_parser import StubDocumentParser

# Test 1: Gemini embedding
vec = asyncio.run(_gemini_embed("Sony Camera HSN 85258020"))
print(f"Gemini embed OK: dims={len(vec)}")

# Test 2: rice bug fix - 'price' should NOT match 'rice'
stub = StubDocumentParser()
result = asyncio.run(stub.extract_rfq_fields(
    "We need 5 Sony Cameras at a target price of 30000 per unit. HSN: 85258020"
))
print(f"Parser product={result.get('product')} (should be 'cameras' not 'rice')")
print(f"Parser quantity={result.get('quantity')}")
print("ALL CHECKS PASSED" if result.get('product','').lower() not in ('rice','') else "FAIL: rice bug still present")
