# Cadencia -- Testing Guide for Judges

**Platform:** [https://cadenciaa.duckdns.org](https://cadenciaa.duckdns.org)

---

## Table of Contents

1. [Overview](#overview)
2. [Pre-Seeded Test Accounts](#pre-seeded-test-accounts)
3. [Buyer-Side Testing](#buyer-side-testing)
4. [Seller-Side Testing](#seller-side-testing)
5. [End-to-End Trade Flow (Buyer + Seller Together)](#end-to-end-trade-flow)
6. [Escrow & Blockchain Testing](#escrow--blockchain-testing)
7. [Compliance & Audit Testing](#compliance--audit-testing)
8. [Admin Dashboard Testing](#admin-dashboard-testing)
9. [Treasury Dashboard Testing](#treasury-dashboard-testing)
10. [AI/LLM Features to Observe](#aillm-features-to-observe)
11. [Wallet Integration Testing](#wallet-integration-testing)
12. [Quick Smoke Test (5 Minutes)](#quick-smoke-test-5-minutes)

---

## Overview

Cadencia is an **AI-native B2B trade marketplace** built for Indian MSMEs. It replaces manual procurement (phone calls, WhatsApp, manual compliance) with a single-upload autonomous workflow:

**Buyer uploads a free-text RFQ --> AI parses it --> Matches to sellers --> AI agents negotiate price autonomously --> Blockchain escrow secures payment --> Compliance records auto-generated**

The entire trade lifecycle -- from RFQ to settlement -- happens on-platform with AI agents, Algorand blockchain escrow, and auto-generated FEMA/GST compliance records.

---

## Pre-Seeded Test Accounts

### Industry-Specific Accounts (Recommended for Testing)

| Role   | Company Name                   | Email                              | Password         | Industry    |
|--------|--------------------------------|------------------------------------|------------------|-------------|
| BUYER  | TechWeave Garments Pvt Ltd     | buyer1@techweavegarments.com       | Test@Cadencia1   | Textiles    |
| BUYER  | SmartElec Devices Ltd          | buyer2@smartelecdevices.com        | Test@Cadencia1   | Electronics |
| BUYER  | MediQuick Pharma Industries    | buyer3@mediquickpharma.com         | Test@Cadencia1   | Pharma      |
| BUYER  | AutoAssemble Industries Ltd    | buyer4@autoassemble.com            | Test@Cadencia1   | Automotive  |
| BUYER  | GreenField Agro Pvt Ltd        | buyer5@greenfieldagro.com          | Test@Cadencia1   | Agriculture |
| SELLER | Maharashtra Cotton Mills Ltd   | seller1@mahacottonmills.com        | Test@Cadencia1   | Textiles    |
| SELLER | Pune PCB Technologies Pvt Ltd  | seller2@punpcbtech.com             | Test@Cadencia1   | Electronics |
| SELLER | Hyderabad Life Sciences Pvt Ltd| seller3@hydlifesciences.com        | Test@Cadencia1   | Pharma      |
| SELLER | Tamil Nadu Auto Components Ltd | seller4@tnautocomponents.com       | Test@Cadencia1   | Automotive  |
| SELLER | Gujarat Agro Chemicals Corp    | seller5@gujaratagrochemicals.com   | Test@Cadencia1   | Agriculture |

> **Tip:** For the best end-to-end test, use a **buyer + seller pair from the same industry** (e.g., buyer1 + seller1 for Textiles, buyer2 + seller2 for Electronics).

### You Can Also Register Fresh Accounts

You are free to register new buyer/seller accounts from the registration page to test the onboarding flow from scratch.

---

## Buyer-Side Testing

### Step 1: Login as a Buyer

1. Go to [https://cadenciaa.duckdns.org/login](https://cadenciaa.duckdns.org/login)
2. Enter a buyer email and password from the table above (e.g., `buyer1@techweavegarments.com` / `Test@Cadencia1`)
3. Click **Login**
4. You should be redirected to the **Dashboard**

**What to verify:**
- Dashboard loads with stats cards (Active Negotiations, Agreed Deals, etc.)
- Sidebar navigation is visible with all menu items
- User's company name appears in the header/profile area

---

### Step 2: View the Dashboard

**Navigate to:** `/dashboard`

**What to verify:**
- Stats cards show counts for: Active Negotiations, Agreed Deals, Released Escrows, Compliance Records
- Recent activity feed shows latest platform events
- Navigation works to all sections from the sidebar

---

### Step 3: Upload an RFQ (Request for Quotation)

This is the **core buyer action** -- uploading a free-text purchase requirement that the AI parses automatically.

**Navigate to:** `/marketplace`

1. Find the **RFQ upload** section
2. Type or paste a free-text requirement. Example RFQs to try:

   **Textiles (if logged in as buyer1):**
   ```
   We need 2000 meters of premium cotton fabric, 60s count, 
   width 58 inches, for our summer collection. Delivery to Mumbai 
   warehouse within 30 days. Budget Rs 180-220 per meter. 
   Need OEKO-TEX certification. Payment via LC at sight.
   ```

   **Electronics (if logged in as buyer2):**
   ```
   Require 5000 units of 4-layer PCB boards, FR-4 material, 
   1.6mm thickness, HASL finish. SMD assembly ready. 
   Delivery to Pune facility in 21 days. Budget Rs 85-120 per unit. 
   IPC Class 2 standards required. Payment NET 30.
   ```

   **Pharma (if logged in as buyer3):**
   ```
   Need 500 kg of Paracetamol API, IP grade, purity 99.5% minimum. 
   CoA and DMF documentation required. Delivery to Hyderabad 
   within 15 days. Budget Rs 800-1100 per kg. 
   WHO-GMP certified manufacturer only.
   ```

   **Automotive (if logged in as buyer4):**
   ```
   Require 10000 units of precision CNC machined brake calipers, 
   aluminum alloy 6061-T6, tolerance +/-0.02mm. IATF 16949 
   certified supplier only. Delivery to Chennai plant in 45 days. 
   Budget Rs 450-600 per unit. PPAP Level 3 documentation needed.
   ```

   **Agriculture (if logged in as buyer5):**
   ```
   Need 100 MT of DAP fertilizer, 18-46-0 grade, in 50kg bags. 
   BIS certified. Delivery to Punjab warehouse within 20 days. 
   Budget Rs 28000-32000 per MT. FCO compliance mandatory. 
   Payment 50% advance, 50% on delivery.
   ```

3. Submit the RFQ

**What to verify:**
- The AI **automatically parses** the free text and extracts structured fields:
  - Product name
  - HSN code (commodity classification)
  - Quantity and unit
  - Budget range (min/max)
  - Delivery window
  - Geography/location
- RFQ status transitions: `DRAFT` --> `PARSED`
- The parsed fields are displayed back to you for review

---

### Step 4: View Seller Matches

After the RFQ is parsed, the system uses **vector similarity search** (pgvector) to match your requirement against seller capability profiles.

**What to verify:**
- A list of matched sellers appears, ranked by relevance score
- Each match shows: seller name, match score, capabilities
- RFQ status transitions: `PARSED` --> `MATCHED`

---

### Step 5: Confirm a Match & Start Negotiation

1. Select your preferred seller match
2. Click **Confirm Match**
3. Click **Start Negotiations**

**What to verify:**
- RFQ status transitions: `MATCHED` --> `CONFIRMED`
- A new **Negotiation Session** is created
- You are redirected to the negotiations page or can navigate to `/negotiations`

---

### Step 6: Watch AI Negotiation in Real-Time

**Navigate to:** `/negotiations` then click on the active session

This is the **flagship feature** -- two AI agents (one representing the buyer, one representing the seller) negotiate price autonomously.

**What to verify:**
- **Live SSE streaming**: Offers appear in real-time without page refresh
- Each negotiation round shows:
  - Round number
  - Which side made the offer (Buyer Agent / Seller Agent)
  - Proposed price
  - Confidence score
  - Agent reasoning (why it chose this price)
- The **price gap narrows** over rounds (convergence visualization)
- Session status updates: `INIT` --> `SELLER_ANCHOR` --> `BUYER_RESPONSE` --> `ROUND_LOOP`
- When the gap reaches less than or equal to 2%, the session transitions to `AGREED`

**Human Override (Optional Test):**
- While negotiation is active, you can **inject a manual offer**
- This overrides the AI agent's next move
- The override is logged and the agent profile is updated for future sessions

---

### Step 7: View Negotiation Results

**Navigate to:** `/negotiations`

**What to verify:**
- All your sessions are listed with status filters (ACTIVE, AGREED, WALK_AWAY, TIMEOUT, etc.)
- Agreed sessions show the final negotiated price
- Session detail page shows the complete offer timeline

---

## Seller-Side Testing

### Step 1: Login as a Seller

1. Go to [https://cadenciaa.duckdns.org/login](https://cadenciaa.duckdns.org/login)
2. Enter a seller email and password (e.g., `seller1@mahacottonmills.com` / `Test@Cadencia1`)
3. Click **Login**

---

### Step 2: View Seller Dashboard

**Navigate to:** `/dashboard`

**What to verify:**
- Dashboard shows seller-relevant stats
- Incoming RFQ count is visible
- Recent activity shows matched RFQs and negotiation events

---

### Step 3: Manage Capability Profile

**Navigate to:** `/marketplace/profile`

This is where sellers describe their capabilities so the AI matching engine can find them when buyers upload relevant RFQs.

**What to verify:**
- Current capability profile is displayed (product categories, certifications, capacity, etc.)
- You can **edit** the profile:
  - Product categories
  - Certifications
  - Production capacity
  - Delivery regions
  - Payment terms
  - Quality standards
- After saving, the system **recomputes vector embeddings** for the updated profile

**Example profile update (for seller1 - Textiles):**
```
Premium cotton fabric manufacturer. Specialize in 40s-80s count cotton, 
polyester-cotton blends, and organic cotton fabrics. OEKO-TEX Standard 100 
certified. BIS certified facility. Capacity 50,000 meters/month. 
Delivery across PAN India within 7-21 days.
```

---

### Step 4: Manage Catalogue

**Navigate to:** `/marketplace/catalogue`

**What to verify:**
- You can **create** catalogue items with: product name, price, quantity, specifications
- Items are listed in a table/grid format
- You can **edit** item pricing and availability
- You can **deactivate/delete** items

---

### Step 5: View Incoming RFQs

**Navigate to:** `/marketplace` (as seller)

**What to verify:**
- If a buyer has uploaded an RFQ that matches your capability profile, it appears in your incoming RFQs list
- Each RFQ shows: buyer requirement summary, matched score, product details
- You can see which RFQs are pending response vs. already in negotiation

---

### Step 6: Monitor Negotiations (Seller Side)

**Navigate to:** `/negotiations`

When a buyer starts negotiations on a matched RFQ, the seller can monitor the AI agent negotiating on their behalf.

**What to verify:**
- Active sessions where you are the seller are listed
- Real-time SSE streaming shows your seller agent's offers and the buyer agent's counteroffers
- You can apply **Human Override** to inject your own price mid-negotiation
- Session results (AGREED, WALK_AWAY, etc.) are visible

---

## End-to-End Trade Flow

For the **complete experience**, test the full lifecycle using two browser windows (or incognito):

### Setup
- **Window 1:** Login as a buyer (e.g., `buyer2@smartelecdevices.com`)
- **Window 2:** Login as the matching seller (e.g., `seller2@punpcbtech.com`)

### Flow

| Step | Buyer (Window 1)                                         | Seller (Window 2)                                      |
|------|----------------------------------------------------------|--------------------------------------------------------|
| 1    | Upload an Electronics RFQ on `/marketplace`              | --                                                     |
| 2    | Wait for AI to parse the RFQ (few seconds)               | --                                                     |
| 3    | View matched sellers, confirm seller2                    | See incoming RFQ appear on dashboard/marketplace       |
| 4    | Click "Start Negotiations"                               | --                                                     |
| 5    | Watch AI negotiate on `/negotiations/[session_id]`       | Watch the same session from seller's perspective       |
| 6    | (Optional) Inject a human override offer                 | (Optional) Inject a human override offer               |
| 7    | See session reach AGREED status                          | See session reach AGREED status                        |
| 8    | Go to `/escrow` to select the deal for escrow            | --                                                     |
| 9    | Fund the escrow via Pera Wallet                          | See escrow funded status                               |
| 10   | --                                                       | Receive payment when admin releases escrow             |
| 11   | View compliance records on `/compliance`                 | View compliance records on `/compliance`               |

---

## Escrow & Blockchain Testing

**Navigate to:** `/escrow`

The escrow system uses **Algorand blockchain** smart contracts for trustless payment settlement.

### Escrow Lifecycle

1. **Select Deal** -- After a negotiation reaches AGREED, the buyer selects it for escrow
2. **Pending Approval** -- Admin must approve the escrow before smart contract deployment
3. **Deploy** -- Smart contract is deployed on Algorand (testnet)
4. **Fund** -- Buyer funds the escrow through Pera Wallet (atomic transaction)
5. **Release** -- Admin confirms delivery and releases funds to seller (anchors Merkle root on-chain)
6. **OR Refund** -- In case of dispute, admin can refund buyer
7. **Freeze/Unfreeze** -- Any party can freeze escrow during disputes

**What to verify:**
- Escrow status transitions are clearly displayed
- Algorand transaction IDs are shown and link to the blockchain explorer
- The multi-step escrow funding wizard guides you through the process
- Escrow amounts match the negotiated price

---

## Compliance & Audit Testing

**Navigate to:** `/compliance`

### Audit Log Tab

**What to verify:**
- Hash-chained audit log is displayed for each escrow
- Each entry shows: event type, timestamp, data, entry hash
- The **hash chain verifier** shows visual integrity confirmation
- Click "Verify" to run SHA-256 chain integrity check

### FEMA Tab (Cross-Border Compliance)

**What to verify:**
- FEMA records are auto-generated when an escrow is released
- Contains: transaction date, amount, purpose code, counterparty info
- Download available as PDF or CSV

### GST Tab (Domestic Compliance)

**What to verify:**
- GST records show: buyer GSTIN, seller GSTIN, HSN code, taxable value
- Tax breakdown: IGST / CGST / SGST amounts
- Download available as CSV

---

## Admin Dashboard Testing

**Navigate to:** `/admin`

> **Note:** Admin access requires an admin-level account. The platform admin account is `admin@cadencia.io`.

### Tabs to Explore

| Tab            | What It Shows                                                        |
|----------------|----------------------------------------------------------------------|
| **Overview**   | Platform-wide stats, health check status, pending escrows            |
| **Enterprises**| All registered enterprises, KYC status, role (Buyer/Seller/Both)     |
| **Users**      | All users with status, ability to suspend/reinstate                   |
| **Agents**     | Active AI negotiation agents, ability to pause/resume sessions        |
| **LLM Logs**   | Debug view of all LLM prompts and completions, searchable by session |
| **Activity Log**| Recent platform events (session created, escrow funded, etc.)        |

**What to verify:**
- Health check shows: DB connected, Redis connected, Algorand connected
- Enterprise list shows all registered companies with correct roles
- LLM logs show the actual prompts sent to the AI and responses received

---

## Treasury Dashboard Testing

**Navigate to:** `/treasury`

**What to verify:**
- **Pool Balances**: INR, USDC, and ALGO pool balances displayed
- **Live FX Rate**: Current INR/USDC exchange rate from Frankfurter API
- **Total Portfolio Value**: Aggregated in INR
- **FX Exposure Table**: Open positions with pair, direction, notional, entry rate, current rate, unrealized PnL
- **Liquidity Forecast**: 30-day runway chart showing projected balances

---

## AI/LLM Features to Observe

Throughout testing, pay attention to these AI-powered capabilities:

| Feature                      | Where to See It                                  | What Happens                                              |
|------------------------------|--------------------------------------------------|-----------------------------------------------------------|
| **NLP RFQ Parsing**          | Upload any free-text RFQ on `/marketplace`       | AI extracts product, quantity, budget, delivery, HSN code |
| **Vector Similarity Matching**| After RFQ parsing                               | pgvector cosine similarity ranks sellers by relevance     |
| **Dual-Agent Negotiation**   | `/negotiations/[session_id]`                     | Two AI agents autonomously negotiate price in real-time   |
| **Convergence Detection**    | During active negotiation                        | Session auto-agrees when price gap drops below 2%                  |
| **Stall Detection**          | If agents repeat same price 3+ rounds            | Session transitions to STALLED for human review           |
| **Agent Reasoning**          | Offer details in negotiation view                | Each offer shows the AI's reasoning for its price choice  |
| **Prompt Injection Defense** | Try injecting "ignore previous instructions" in RFQ | Input is sanitized, truncated at 8K chars, patterns blocked |

---

## Wallet Integration Testing

**Navigate to:** `/settings/wallet`

**What to verify:**
- **Link Wallet**: Connect a Pera Wallet (Algorand wallet) to your enterprise account
  - System generates a challenge nonce
  - You sign it with Pera Wallet to prove ownership
  - Wallet address is linked to your account
- **View Balance**: See ALGO, USDC, and INR-equivalent balances
- **Unlink Wallet**: Disconnect wallet from account

> **Note:** For testnet testing, you can get free testnet ALGO from the [Algorand Testnet Faucet](https://bank.testnet.algorand.network/).

---

## Quick Smoke Test (5 Minutes)

If you have limited time, here is the fastest way to see the core features:

1. **Login as buyer** (`buyer1@techweavegarments.com` / `Test@Cadencia1`) -- 30 sec
2. **Check dashboard** at `/dashboard` -- verify stats load -- 30 sec
3. **Upload an RFQ** on `/marketplace` with this text -- 60 sec:
   ```
   Need 1000 meters of organic cotton fabric, 60s count, 
   OEKO-TEX certified, delivery Mumbai 21 days, 
   budget Rs 200-250 per meter, LC payment
   ```
4. **Watch AI parse it** into structured fields (product, quantity, budget, etc.) -- 15 sec
5. **View seller matches** ranked by relevance score -- 15 sec
6. **Confirm a match and start negotiations** -- 30 sec
7. **Watch real-time AI negotiation** with SSE streaming on `/negotiations/[session_id]` -- 60 sec
8. **Open a second browser**, login as seller (`seller1@mahacottonmills.com`), see the same session from the seller's side -- 30 sec
9. **Check `/compliance`** for audit logs -- 15 sec
10. **Check `/escrow`** to see the escrow pipeline -- 15 sec

---

## Key Technical Highlights for Judges

| Aspect                    | Implementation                                                       |
|---------------------------|----------------------------------------------------------------------|
| **AI/LLM**               | Pluggable agent drivers (Gemini, Claude, OpenAI) for NLP parsing and autonomous negotiation |
| **Blockchain**            | Algorand smart contracts (Puya/Python, ARC-4) for trustless escrow   |
| **Vector Search**         | pgvector with IVFFlat/HNSW indexes for sub-2s seller matching        |
| **Real-Time**             | Server-Sent Events (SSE) for live negotiation streaming              |
| **Security**              | RS256 JWT, prompt injection defense, rate limiting, hash-chained audit logs |
| **Compliance**            | Auto-generated FEMA and GST records, 7-year retention, Merkle-root on-chain anchoring |
| **Architecture**          | Hexagonal/DDD with event-driven domain bus, Unit of Work pattern     |
| **Smart Contracts**       | Escrow with fund/release/refund/freeze methods, dry-run simulation   |
| **Data Residency**        | AWS ap-south-1 (Mumbai) for Indian data sovereignty                  |
| **x402 Protocol**         | Algorand-native micropayment protocol for premium analytics          |

---

## Troubleshooting

| Issue                          | Solution                                                      |
|--------------------------------|---------------------------------------------------------------|
| Login fails                    | Ensure you are using the exact email and password from the table above |
| RFQ parsing takes too long     | AI parsing typically completes in 3-8 seconds; wait for the spinner to finish |
| No seller matches found        | Use a buyer-seller pair from the same industry for guaranteed matches |
| Negotiation not starting       | Ensure you clicked both "Confirm Match" AND "Start Negotiations" |
| SSE stream not updating        | Refresh the page; ensure browser supports Server-Sent Events |
| Escrow funding fails           | Ensure Pera Wallet is connected and has testnet ALGO          |
| Page not loading               | Try clearing cache and hard-refreshing (Ctrl+Shift+R)        |

---

*This document covers the complete testing surface of the Cadencia platform. For the most impactful demo, follow the End-to-End Trade Flow section using two browser windows.*
