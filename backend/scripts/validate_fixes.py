import asyncio
from src.marketplace.infrastructure.rfq_parser import get_document_parser, StubDocumentParser

# Test 1: Resilient Embedding Generation
parser = get_document_parser()
vec = asyncio.run(parser.generate_embedding("Sony Camera HSN 85258020"))
print(f"Resilient embedding OK: dims={len(vec)}")

# Test 2: rice bug fix - 'price' should NOT match 'rice'
stub = StubDocumentParser()
result = asyncio.run(stub.extract_rfq_fields(
    "We need 5 Sony Cameras at a target price of 30000 per unit. HSN: 85258020"
))
print(f"Parser product={result.get('product')} (should be 'cameras' not 'rice')")
print(f"Parser quantity={result.get('quantity')}")
print("ALL CHECKS PASSED" if result.get('product','').lower() not in ('rice','') else "FAIL: rice bug still present")

