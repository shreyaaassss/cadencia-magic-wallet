# Cadencia — Complete Feature Testing Guide

> **URL**: `https://cadencia-magic-wallet.duckdns.org`
> **Covers**: All features from both `deep_issue_review_and_plan.md` and `additional_technical_audit.md`
> **Method**: Manual browser testing + API verification
> **Last Updated**: 2026-06-06

---

## Pre-Requisites

1. Open `https://cadencia-magic-wallet.duckdns.org` in Chrome/Firefox
2. Have two accounts ready:
   - **Buyer account** (trade_role = BUYER)
   - **Seller account** (trade_role = SELLER)
3. If you don't have accounts, register them using Flow 1 below

---

## Flow 1: Seller Registration (Tests: Industry Dropdown, Pincode Autofill, Progressive Disclosure)

### Steps

1. Go to `/register`
2. **Step 1 — Enterprise Info:**
   - Fill: Legal Name = `Test Steel Ltd`, PAN = `ABCDE1234F`, GSTIN = `27ABCDE1234F1Z5`
   - Select Trade Role → **Seller**

   **[ ] TEST: Industry Vertical is a DROPDOWN** (not a text box)
   - Click the Industry Vertical field
   - Verify: 11 options appear (Metals & Steel, Electronics & Technology, Textiles & Apparel, etc.)
   - Select "Metals & Steel"

   **[ ] TEST: Geography is a DROPDOWN** (not a text box)
   - Click Geography field
   - Verify: 33 Indian states appear
   - Select "Maharashtra"

   - Add commodity "Steel", set Min Order = 50000, Max Order = 5000000
   - Click Next

3. **Step 2 — Facility & Location:**
   - Fill Address Line 1

   **[ ] TEST: Pincode autofills City and State**
   - Type `400001` in Pincode field
   - Verify: City auto-fills to "Mumbai", State auto-fills to "Maharashtra"
   - Clear pincode, type `110001`
   - Verify: City → "New Delhi", State → "Delhi"
   - Type `999999` (invalid)
   - Verify: City and State remain empty (manual entry)

   - Select Facility Type → **Manufacturing Plant**
   - Click Next

4. **Step 3 — Production & Capacity:**

   **[ ] TEST: Progressive Disclosure — Manufacturing fields shown**
   - Verify: "Monthly Capacity" field visible with "MT/month" hint
   - Verify: "Shift Pattern" dropdown visible (Single/Double/Triple/Continuous)
   - Fill capacity = 500, shift = Double Shift, dispatch = 5 days
   - Add payment term "NET 30"
   - Click Next

5. **Now go BACK to Step 2, change Facility Type → Trading Office, return to Step 3:**

   **[ ] TEST: Progressive Disclosure — Manufacturing fields HIDDEN**
   - Verify: Header says "Business Capacity" (not "Production & Capacity")
   - Verify: Shift Pattern field is HIDDEN
   - Verify: Info text shows "Manufacturing-specific fields are hidden for trading office facilities"

6. Complete Steps 4-5 (Account + Review), Submit

   **[ ] TEST: Registration completes successfully**

---

## Flow 2: Buyer Registration (Tests: Pincode Autofill for Buyers)

1. Go to `/register`, select Trade Role → **Buyer**
2. Fill Step 1 with different PAN/GSTIN/email
3. Step 2 — Delivery Location:

   **[ ] TEST: Buyer pincode autofill works**
   - Type `560001` → Verify: City = "Bangalore", State = "Karnataka"
   - Type `500001` → Verify: City = "Hyderabad", State = "Telangana"

4. Complete registration

---

## Flow 3: Catalogue Management (Tests: Free-form Categories, Spec Text, Commercial Fields, Bulk Tiers)

Login as **Seller**, go to `/marketplace/catalogue`

1. Click **"Add Product"**

   **[ ] TEST: Form has 4 sections**
   - Verify: Section 1 "Product Identity", Section 2 "Pricing & Availability", Section 3 "Bulk Pricing Tiers", Section 4 "Logistics & Compliance"

2. **[ ] TEST: Free-form product category**
   - Open Category dropdown
   - Verify: Shows steel categories + DSLR_CAMERA, ELECTRONICS, TEXTILE, etc.
   - Select "Other (type below)"
   - Type "Organic Turmeric Powder"
   - Verify: Custom input field appears and accepts the value

3. **[ ] TEST: Expanded units (10 options)**
   - Open Unit dropdown
   - Verify: MT, KG, PIECE, BUNDLE, COIL, LITRE, METRE, DOZEN, UNIT, BOX

4. **[ ] TEST: Specification text textarea**
   - Find the "Specification / Description" textarea
   - Type a multi-line description
   - Verify: Character counter shows (e.g., "145/2000")

5. **[ ] TEST: Floor price validation**
   - Set Price per unit = 50000
   - Set Floor Price = 60000 (higher than list price)
   - Submit → Verify: Validation error "floor_price_inr must be <= price_per_unit_inr"

6. **[ ] TEST: Floor price accepted when valid**
   - Set Floor Price = 45000 (lower than list price)
   - Verify: Accepted

7. **[ ] TEST: Max Discount %**
   - Set Max Discount = 15
   - Verify: Field accepts 0-50 range

8. **[ ] TEST: AI Negotiation toggle**
   - Toggle "AI Negotiation" OFF
   - Verify: Shows "Fixed price (no negotiation)"
   - Toggle back ON
   - Verify: Shows "Enabled"

9. **[ ] TEST: Bulk Pricing Tiers**
   - Click "+ Add Tier"
   - Enter: Min Qty = 100, Price/unit = 48000
   - Click "+ Add Tier" again
   - Enter: Min Qty = 500, Price/unit = 45000
   - Verify: Two tier rows visible with remove (trash) buttons
   - Click trash on first tier → Verify: Row removed

10. **[ ] TEST: Certifications**
    - Open certification dropdown → Select "ISO 9001"
    - Type "NABL" in custom input, press Enter
    - Verify: Both appear as chips with × remove buttons
    - Click × on ISO 9001 → Verify: Removed

11. Submit the product

    **[ ] TEST: Product created successfully with all new fields**

---

## Flow 4: Catalogue Listing Features (Tests: Search, Filter, Sort, Stock Badges, Embedding Status)

After adding several products, stay on `/marketplace/catalogue`

1. **[ ] TEST: Search bar**
   - Type a product name in the search bar
   - Verify: Table filters in real-time to matching items

2. **[ ] TEST: Filter buttons**
   - Click "Active" → Only active items shown
   - Click "Inactive" → Only inactive items
   - Click "All" → Everything

3. **[ ] TEST: Sort dropdown**
   - Select "Price" → Items sorted by price ascending
   - Select "Stock" → Items sorted by stock level
   - Select "Name" → Alphabetical

4. **[ ] TEST: Stock badges (color-coded)**
   - Items with stock = 0 → Red dot + red text
   - Items with stock < MOQ → Amber dot + amber text
   - Items with stock >= MOQ → Green dot + green text

5. **[ ] TEST: Stock column**
   - Verify: New "Stock" column visible between MOQ and Lead Time

6. **[ ] TEST: Embedding status banner**
   - After adding a new product, check for blue banner: "Profile embedding updating..."
   - Wait 10-15 seconds → Banner should disappear (embedding completes)

---

## Flow 5: Marketplace Discovery (Tests: Public Stats, Supplier Directory, Industry Filters)

Go to `/marketplace/discover`

1. **[ ] TEST: Platform stats banner**
   - Verify: 4 stat cards showing Total Sellers, Total Buyers, Deals Completed, Escrows Released

2. **[ ] TEST: Industry filter chips**
   - Verify: "All Industries" button + chips for each industry with registered sellers
   - Click an industry chip → Supplier cards filter to that industry
   - Click "All Industries" → All suppliers shown

3. **[ ] TEST: Search**
   - Type a product/industry in search box
   - Verify: Cards filter in real-time

4. **[ ] TEST: Anonymized supplier cards**
   - Verify: Each card shows: industry, categories (as colored chips), geography, certifications, years bucket, min order value
   - Verify: NO enterprise name or contact info shown (anonymized ID only)

5. **[ ] TEST: "Submit RFQ to Match" button**
   - Verify: Each card has this button

---

## Flow 6: Industry Taxonomies API (Tests: Backend Endpoint)

Open browser console or use Postman:

```
GET https://cadencia-magic-wallet.duckdns.org/v1/marketplace/industries
```

**[ ] TEST: Returns 12 industry taxonomies**
- Verify: Response has `status: "success"` and `data` array with 12 items
- Verify: Each item has: `industry_code`, `display_name`, `default_units`, `default_certifications`, `capacity_unit`, `is_manufacturing`
- Verify: METALS has `["MT", "KG", "COIL", "BUNDLE"]` in default_units
- Verify: ELECTRONICS has `["PIECE", "UNIT", "BOX"]` in default_units

---

## Flow 7: Platform Statistics API (Tests: Public Stats)

```
GET https://cadencia-magic-wallet.duckdns.org/v1/marketplace/stats
```

**[ ] TEST: Returns aggregate platform statistics**
- Verify: `total_sellers`, `total_buyers`, `negotiations_completed`, `escrows_released`, `total_value_settled_inr`, `industries_represented`
- Verify: No authentication required (public endpoint)

---

## Flow 8: Anonymized Supplier Directory API (Tests: Public Supplier List)

```
GET https://cadencia-magic-wallet.duckdns.org/v1/marketplace/suppliers
GET https://cadencia-magic-wallet.duckdns.org/v1/marketplace/suppliers?industry=Steel
```

**[ ] TEST: Returns anonymized seller profiles**
- Verify: Each supplier has `supplier_id` (opaque hash, not UUID)
- Verify: No enterprise name, PAN, GSTIN, or contact info exposed
- Verify: Industry filter works

---

## Flow 9: Wallet Transaction History (Tests: Wallet Ledger)

Login as any user, go to `/treasury`

**[ ] TEST: Transaction history table**
- Scroll down past the pool balances
- Verify: "Wallet Transactions" section exists
- If transactions exist: Table with Event, Direction, Amount (ALGO), TX ID, Date
- If no transactions: "No wallet transactions" empty state
- TX ID links should open Pera Explorer

---

## Flow 10: Negotiation Features (Tests: Manual Override, Agent Reasoning)

Login as **Buyer**, submit an RFQ, wait for matches and negotiation to start.

Go to `/negotiations/[session_id]`

1. **[ ] TEST: Agent reasoning displayed**
   - Verify: Each offer in the timeline shows the agent's reasoning text below the price
   - Verify: Strategy tags (CONCESSIVE, CONSERVATIVE, etc.) are visible

2. **[ ] TEST: Human override panel**
   - Look for "Override" or "Manual Counter-Offer" button
   - Verify: Clicking it shows a form to enter custom price + terms

3. **[ ] TEST: Information leak protection (Security Fixes)**
   - As Buyer: Verify you can see YOUR agent's reasoning but NOT the seller's reasoning
   - Seller offers should show `null` or no reasoning text

---

## Flow 11: Messaging System (Tests: Thread Creation, Chat, Auto-Close)

This requires an active negotiation between buyer and seller.

### Create a Thread

```
POST /v1/threads
{
  "buyer_enterprise_id": "<buyer_id>",
  "seller_enterprise_id": "<seller_id>",
  "session_id": "<negotiation_session_id>",
  "thread_type": "NEGOTIATION_QUERY",
  "subject": "Delivery timeline question"
}
```

**[ ] TEST: Thread created successfully**

### Send Messages

```
POST /v1/threads/<thread_id>/messages
{ "body": "Can you deliver by Friday?" }
```

**[ ] TEST: Message sent and appears in history**

### View Messages Page

Go to `/messages`

**[ ] TEST: Thread list shows conversations**
- Verify: Thread shows subject, type, status (OPEN/CLOSED)
- Click a thread → Opens message view

**[ ] TEST: Message view**
- Verify: Messages shown in chat bubble format
- Own messages aligned right (blue)
- Opponent messages aligned left (gray)
- Input field at bottom for new messages

### Auto-Close on Deal Completion

After escrow is RELEASED:

**[ ] TEST: Thread auto-closed**
- Verify: Thread status changes to "CLOSED"
- Verify: Lock icon appears
- Verify: Input field disabled with "read-only" message
- Verify: System message "Deal completed — this conversation is now read-only"
- Verify: Old messages still readable (history preserved)

---

## Flow 12: Procurement Documents (Tests: PO Generation)

After a negotiation reaches AGREED:

```
POST /v1/procurement/generate
{ "session_id": "<agreed_session_id>" }
```

**[ ] TEST: PO generated with sequential number**
- Verify: Response includes `po_number` (format: PO-2026-00001)
- Verify: Status is "PENDING_SELLER_ACCEPTANCE"

### List POs

```
GET /v1/procurement
```

**[ ] TEST: PO appears in list**

### Seller Accepts PO

Login as Seller:
```
PATCH /v1/procurement/<document_id>/seller-accept
```

**[ ] TEST: Status changes to "ACTIVE"**

---

## Flow 13: Escrow & Settlement Features (Tests: Pricing Mode, Milestone Schema)

### Pricing Cap

**[ ] TEST: ESCROW_PRICING_MODE documented**
- Escrow amounts on testnet are capped at 0.999 ALGO (TESTNET_DEMO mode)
- The escrow page should show ALGO amount alongside deal value

### Approval Deadline

**[ ] TEST: Auto-reject after 72 hours**
- If a seller doesn't respond to an escrow approval within 72 hours, it auto-rejects
- Background job runs every hour

### Dispatch Timeout

**[ ] TEST: Auto-freeze after 7 days**
- If delivery isn't confirmed within 7 days of dispatch, escrow is auto-frozen

---

## Flow 14: Agent Performance (Tests: Negotiation Insights)

After several negotiations complete:

Go to `/dashboard`

**[ ] TEST: Agent performance section (if AgentPerformanceDashboard is wired)**
- Should show: Win Rate, Total Deals, Avg Rounds, Avg Savings
- Strategy distribution chart

---

## Flow 15: SLA Dashboard (Admin)

Go to `/admin/sla`

**[ ] TEST: SLA tracking page**
- Verify: Stat cards (Active RFQs, Deals Completed, Avg Rounds, Escrows Released)
- Verify: Recent Deal Timelines table with session IDs, rounds, status, dates

---

## Flow 16: Onboarding Checklist & Tooltips

### Onboarding Checklist

**[ ] TEST: Component exists**
- The `OnboardingChecklist` component renders role-specific steps
- Buyer: Link wallet → Submit RFQ → View negotiation
- Seller: Link wallet → Add product → Complete profile
- Progress bar shows completion %

### Contextual Tooltips

**[ ] TEST: Tooltip component exists**
- The `ContextualTooltip` component renders a `?` icon
- Hovering shows explanatory text in a popover
- Used for: ALGO Balance, Merkle Root, FEMA Record, etc.

---

## Flow 17: Security Fixes Verification

### I1: Intelligence Endpoint

```
GET /v1/sessions/<session_id>/intelligence
Authorization: Bearer <buyer_token>
```

**[ ] TEST: Buyer cannot see seller's Bayesian profile**
- Verify: Response has `your_intelligence` (own data) + `opponent_classification` (just dominant_type + hint)
- Verify: No `seller_intelligence` or `buyer_intelligence` raw objects

### I2: Deal Quality Score

```
GET /v1/sessions/<agreed_session_id>
Authorization: Bearer <buyer_token>
```

**[ ] TEST: Buyer sees own savings only**
- Verify: `deal_quality_score` has `your_savings_inr` and `agreed_price_inr`
- Verify: NO `seller_surplus_inr` or `zopa_width_inr`

### I3: WALK_AWAY Reasoning

For a session that reached WALK_AWAY:

**[ ] TEST: No exact prices in reasoning**
- Check the last offer's `agent_reasoning`
- Verify: Contains "approximately X%" but NOT exact `₹X,XX,XXX` amounts for both parties

### I6: Agent Reasoning Role Filter

```
GET /v1/sessions/<session_id>
Authorization: Bearer <buyer_token>
```

**[ ] TEST: Opponent's reasoning is redacted**
- Check offers array
- Verify: Buyer's own offers have `agent_reasoning` populated
- Verify: Seller's offers have `agent_reasoning: null`

---

## Flow 18: Database Schema Verification

Open a terminal and run:

```bash
ssh ec2-user@13.204.194.47
cd ~/cadencia/backend && source venv/bin/activate
alembic current
```

**[ ] TEST: DB at revision 038 (head)**

### New Tables (12)

```sql
PGPASSWORD=cadencia_prod psql -h localhost -U cadencia -d cadencia -c "
SELECT table_name FROM information_schema.tables
WHERE table_schema='public'
AND table_name IN (
  'wallet_ledger','seller_ratings','negotiation_config',
  'agent_decision_audit','procurement_documents',
  'procurement_document_amendments','conversation_threads',
  'messages','approved_vendor_lists','escrow_milestones',
  'sla_events','order_splits'
)
ORDER BY table_name;
"
```

**[ ] TEST: All 12 tables exist**

---

## Quick Checklist Summary

| # | Feature | Where to Test | Status |
|---|---------|---------------|--------|
| 1 | Industry dropdown (not text) | Register Step 1 | [ ] |
| 2 | Geography dropdown (not text) | Register Step 1 | [ ] |
| 3 | Pincode autofill (buyer + seller) | Register Step 2 | [ ] |
| 4 | Progressive disclosure | Register Step 3 | [ ] |
| 5 | Free-form category | Catalogue → Add | [ ] |
| 6 | Expanded units (10) | Catalogue → Add | [ ] |
| 7 | Specification textarea | Catalogue → Add | [ ] |
| 8 | Floor price validation | Catalogue → Add | [ ] |
| 9 | Max discount % | Catalogue → Add | [ ] |
| 10 | Negotiation toggle | Catalogue → Add | [ ] |
| 11 | Bulk pricing tiers | Catalogue → Add | [ ] |
| 12 | Certifications chips | Catalogue → Add | [ ] |
| 13 | Search bar | Catalogue listing | [ ] |
| 14 | Active/Inactive filter | Catalogue listing | [ ] |
| 15 | Sort dropdown | Catalogue listing | [ ] |
| 16 | Stock badges | Catalogue listing | [ ] |
| 17 | Embedding status banner | Catalogue listing | [ ] |
| 18 | Discovery page stats | /marketplace/discover | [ ] |
| 19 | Supplier cards (anonymized) | /marketplace/discover | [ ] |
| 20 | Industry filter chips | /marketplace/discover | [ ] |
| 21 | GET /marketplace/stats | API (public) | [ ] |
| 22 | GET /marketplace/suppliers | API (public) | [ ] |
| 23 | GET /marketplace/industries | API (public) | [ ] |
| 24 | Wallet tx history table | /treasury | [ ] |
| 25 | Agent reasoning displayed | /negotiations/[id] | [ ] |
| 26 | Human override button | /negotiations/[id] | [ ] |
| 27 | Reasoning role-filtered | /negotiations/[id] | [ ] |
| 28 | Intelligence role-filtered | API /intelligence | [ ] |
| 29 | deal_quality_score redacted | API /sessions/[id] | [ ] |
| 30 | WALK_AWAY no exact prices | API offers | [ ] |
| 31 | Messaging thread create | API /threads | [ ] |
| 32 | Send message | API /threads/[id]/messages | [ ] |
| 33 | Thread list page | /messages | [ ] |
| 34 | Chat view page | /messages/[id] | [ ] |
| 35 | Thread auto-close on release | Escrow RELEASED event | [ ] |
| 36 | Closed thread read-only | /messages/[id] (closed) | [ ] |
| 37 | PO generation | API /procurement/generate | [ ] |
| 38 | Seller PO acceptance | API /procurement/[id]/seller-accept | [ ] |
| 39 | Background scheduler running | PM2 logs | [ ] |
| 40 | Approval deadline auto-reject | 72h timeout | [ ] |
| 41 | Dispatch timeout auto-freeze | 7d timeout | [ ] |
| 42 | SLA dashboard | /admin/sla | [ ] |
| 43 | Onboarding checklist component | Dashboard (if wired) | [ ] |
| 44 | Contextual tooltip component | Various pages | [ ] |
| 45 | DB at revision 038 | SSH → alembic current | [ ] |
| 46 | 12 new tables exist | SQL query | [ ] |
| 47 | 551 unit tests passing | pytest tests/unit/ | [ ] |
| 48 | 38 production smoke tests | production_smoke.sh | [ ] |
