import asyncio, json, os, sys
sys.path.insert(0, "/app")
os.environ.setdefault("LLM_PROVIDER", "groq")

from src.marketplace.infrastructure.rfq_parser import get_document_parser

MULTI = """We are seeking quotations from verified suppliers for the procurement of professional camera equipment for commercial media and content production use. The requirement includes 5 Sony Cameras (HSN: 85258020) at a target price of Rs.30,000 per unit, 3 Nikon Cameras (HSN: 85258021) at Rs.50,000 per unit, and 2 DJI Cameras (HSN: 85258020) at Rs.60,000 per unit. Suppliers must provide genuine products with GST invoices, warranty support, and confirmed stock availability. Delivery is expected within 3-5 days from order confirmation."""

SINGLE = """We are looking for verified suppliers to provide quotations for the supply of Sony Cameras (HSN: 85258020) for commercial photography and media production purposes. The required quantity is 5 units at a target price of Rs.30,000 per unit, with delivery expected within 3 days of order confirmation. Suppliers must provide genuine products with GST invoices, warranty support, and confirmed stock availability."""

async def test(label, text):
    parser = get_document_parser()
    result = await parser.extract_rfq_fields(text)
    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print(f"{'='*60}")
    print(json.dumps(result, indent=2, default=str))
    product = result.get("product", "").lower()
    if "rice" in product and "camera" not in product:
        print("FAIL: rice bug still present!")
    elif not product:
        print("WARN: empty product")
    else:
        print(f"OK: product='{result.get('product')}' qty={result.get('quantity')} hsn={result.get('hsn_code')}")

async def main():
    await test("MULTI-PRODUCT (Sony+Nikon+DJI)", MULTI)
    await test("SINGLE-PRODUCT (Sony only)", SINGLE)

asyncio.run(main())
