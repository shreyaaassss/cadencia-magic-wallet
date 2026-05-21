# Cadencia -- Testing Guide for Judges

**Live Platform:** [https://cadencia-magic-wallet.duckdns.org](https://cadencia-magic-wallet.duckdns.org)

---

## Table of Contents

1. [Overview](#overview)
2. [How Authentication Works (Magic Wallet)](#how-authentication-works-magic-wallet)
3. [Registering a Buyer Account](#registering-a-buyer-account)
4. [Registering a Seller Account](#registering-a-seller-account)
5. [Buyer-Side Testing](#buyer-side-testing)
6. [Seller-Side Testing](#seller-side-testing)
7. [Complete End-to-End Trade Flow (Buyer + Seller)](#complete-end-to-end-trade-flow-buyer--seller)
8. [Escrow & Blockchain Testing](#escrow--blockchain-testing)
9. [Compliance & Audit Testing](#compliance--audit-testing)
10. [Treasury Dashboard Testing](#treasury-dashboard-testing)
11. [AI/LLM Features to Observe](#aillm-features-to-observe)
12. [Quick Smoke Test (10 Minutes)](#quick-smoke-test-10-minutes)
13. [Key Technical Highlights](#key-technical-highlights)
14. [Troubleshooting](#troubleshooting)

---

## Overview

Cadencia is an **AI-native B2B trade marketplace** built for Indian MSMEs. It replaces manual procurement (phone calls, WhatsApp, manual compliance) with a single-upload autonomous workflow:

```
Buyer uploads free-text RFQ
    --> AI parses it into structured fields
        --> Vector search matches relevant sellers
            --> AI agents negotiate price autonomously
                --> Buyer selects best offer
                    --> Seller accepts the deal
                        --> Blockchain escrow secures payment
                            --> Compliance records auto-generated
```

The entire trade lifecycle -- from RFQ to settlement -- happens on-platform with AI agents, Algorand blockchain escrow, and auto-generated FEMA/GST compliance records.

---

## How Authentication Works (Magic Wallet)

Cadencia uses **Magic.link** for passwordless authentication. There are **no passwords** anywhere in the system. Here is how login works:

1. You enter your **email address** on the login page
2. Magic sends a **one-time code (OTP)** to that email
3. You enter the OTP code (Magic handles this UI automatically)
4. You are authenticated and redirected to your dashboard

Behind the scenes, Magic also provisions an **Algorand blockchain wallet** for every user automatically -- this is used later for escrow funding and settlement. No separate wallet setup is needed.

> **Important:** You need access to a **real email inbox** to receive the OTP. Use any email you can access (Gmail, Outlook, etc.).

---

## Registering a Buyer Account

You need to register **fresh accounts** to test the platform. Here is how to register as a buyer.

### Go to the Registration Page

1. Open [https://cadencia-magic-wallet.duckdns.org/login](https://cadencia-magic-wallet.duckdns.org/login)
2. At the bottom of the login page, click the **"Register as Buyer"** link
3. This takes you to the registration form with the role pre-selected as BUYER

### Step 1 of 4: Enterprise Information

Fill in your company details:

| Field              | What to Enter                          | Example                  |
|--------------------|----------------------------------------|--------------------------|
| Legal Name         | Your company name                      | `Acme Textiles Pvt Ltd`  |
| PAN                | 10-character PAN (format: ABCDE1234F)  | `AATWE1234B`             |
| GSTIN              | 15-character GST number                | `27AATWE1234B1ZA`        |
| Trade Role         | Pre-selected as BUYER                  | `BUYER`                  |
| Industry Vertical  | Your industry                          | `Textiles`               |
| Geography          | Operating region                       | `PAN_INDIA`              |

> **Note on PAN/GSTIN:** These are validated for format. Use the format shown above. The GSTIN must start with a 2-digit state code and embed the PAN.

### Step 2 of 4: Delivery Location

Fill in where you want goods delivered:

| Field          | What to Enter                    | Example                        |
|----------------|----------------------------------|--------------------------------|
| Address Line 1 | Street / building / area         | `Plot 42, MIDC Industrial Area`|
| Address Line 2 | Landmark (optional)              | `Near Highway Junction`        |
| City           | City name                        | `Mumbai`                       |
| State          | Select from dropdown             | `Maharashtra`                  |
| Pincode        | 6-digit pincode                  | `400093`                       |
| Site Type      | Select from dropdown             | `WAREHOUSE` or `FACTORY`       |

### Step 3 of 4: Account Details

| Field     | What to Enter                                      |
|-----------|-----------------------------------------------------|
| Full Name | Your name                                           |
| Email     | A **real email** you can access (for OTP)           |

> There is **no password field**. The page says: "No password needed. We'll send a one-time code to your email to verify your identity."

### Step 4 of 4: Review & Submit

- Review all entered information across summary cards
- Each card has an **Edit** button to go back and fix anything
- Click **"Create Account"**
- Magic will send an OTP to your email -- enter it when prompted
- On success, you are logged in and redirected to the **Dashboard**

---

## Registering a Seller Account

### Go to the Registration Page

1. Open [https://cadencia-magic-wallet.duckdns.org/login](https://cadencia-magic-wallet.duckdns.org/login)
2. At the bottom of the login page, click the **"Register as Seller"** link
3. This takes you to the registration form with the role pre-selected as SELLER

### Step 1 of 5: Enterprise Information

Same as buyer, plus **seller-specific fields**:

| Field              | What to Enter                          | Example                   |
|--------------------|----------------------------------------|---------------------------|
| Legal Name         | Your company name                      | `Gujarat Cotton Mills Ltd`|
| PAN                | 10-character PAN                       | `FFMCO1234G`              |
| GSTIN              | 15-character GST number                | `27FFMCO1234G1ZF`         |
| Trade Role         | Pre-selected as SELLER                 | `SELLER`                  |
| Industry Vertical  | Your industry                          | `Textiles`                |
| Geography          | Operating region                       | `PAN_INDIA`               |
| Commodities        | Tag input -- type and press Enter      | `Cotton Fabric`, `Silk`   |
| Min Order Value    | Minimum order in INR                   | `100000`                  |
| Max Order Value    | Maximum order in INR                   | `50000000`                |

> **Commodities** is critical -- this is what the AI uses to match your seller profile to buyer RFQs. Add relevant product tags.

### Step 2 of 5: Facility & Location

| Field          | What to Enter                    | Example                         |
|----------------|----------------------------------|---------------------------------|
| Address Line 1 | Street / building / area         | `Survey No 123, Industrial Park`|
| Address Line 2 | Landmark (optional)              | `Opp. Railway Station`          |
| City           | City name                        | `Ahmedabad`                     |
| State          | Select from dropdown             | `Gujarat`                       |
| Pincode        | 6-digit pincode                  | `382330`                        |
| Facility Type  | Select from dropdown             | `MANUFACTURING_PLANT`           |

Options for Facility Type: `MANUFACTURING_PLANT`, `WAREHOUSE`, `TRADING_OFFICE`, `INTEGRATED`

### Step 3 of 5: Production & Capacity

| Field                   | What to Enter                         | Example                        |
|-------------------------|---------------------------------------|--------------------------------|
| Monthly Capacity        | Production capacity in MT/month       | `5000`                         |
| Shift Pattern           | Select from dropdown                  | `DOUBLE_SHIFT`                 |
| Avg Dispatch Days       | Days to dispatch after order (1-90)   | `14`                           |
| Max Delivery Radius     | Kilometers (optional, 50-5000)        | `2000`                         |
| Transport Modes         | Checkboxes: ROAD, RAIL, SEA, AIR      | Check `ROAD` and `RAIL`        |
| Has Own Transport       | Checkbox                              | Check if applicable            |
| Payment Terms Accepted  | Tag input with suggestions            | `LC at Sight`, `NET 30`        |
| Quality Certifications  | Tag input with suggestions            | `ISO 9001`, `BIS`              |
| Years in Operation      | Number (optional)                     | `15`                           |

> **Payment Terms suggestions:** Advance, LC at Sight, LC 30, LC 60, NET 30, NET 60, NET 90
>
> **Certification suggestions:** ISO 9001, BIS, RDSO, ISO 14001, NABL

### Step 4 of 5: Account Details

Same as buyer -- full name and a real email address. No password.

### Step 5 of 5: Review & Submit

- Review all information
- Click **"Create Account"**
- Enter the Magic OTP sent to your email
- Redirected to Dashboard on success

---

## Buyer-Side Testing

> **Prerequisite:** You must be logged in as a BUYER account.

### Step 1: View the Buyer Dashboard

**URL:** [https://cadencia-magic-wallet.duckdns.org/dashboard](https://cadencia-magic-wallet.duckdns.org/dashboard)

**What you see:**
- Welcome message with your name and company
- **"Buy Credits"** button (buyer-only feature)
- **Stat cards:** Active RFQs, Pending Escrows, Agreed Sessions, Total Trades
- **Recent RFQs table:** Your submitted RFQs with status (clickable rows)
- **Negotiation Sessions table:** Your active and completed negotiations
- **Escrow Activity table:** Escrow status with Algorand blockchain TX links
- **Recent Activity feed:** Combined timeline of all your activity
- **System Health:** Database, Redis, Algorand, LLM status indicators

**Sidebar navigation (buyer sees):**
- Dashboard
- **Marketplace** (buyer-only -- this is where you upload RFQs)
- Negotiations
- Escrow
- Treasury
- Compliance
- Settings

---

### Step 2: Upload an RFQ (Request for Quotation)

**Navigate to:** Marketplace (click in sidebar)

This is the **core buyer action**. You write what you need in plain English and the AI handles everything.

1. Click **"New RFQ"** to expand the RFQ form
2. Type or paste a free-text requirement in the textarea

**Sample RFQs to try (pick one matching your industry):**

**Textiles:**
```
We need 2000 meters of premium cotton fabric, 60s count,
width 58 inches, for our summer collection. Delivery to Mumbai
warehouse within 30 days. Budget Rs 180-220 per meter.
Need OEKO-TEX certification. Payment via LC at sight.
```

**Electronics:**
```
Require 5000 units of 4-layer PCB boards, FR-4 material,
1.6mm thickness, HASL finish. SMD assembly ready.
Delivery to Pune facility in 21 days. Budget Rs 85-120 per unit.
IPC Class 2 standards required. Payment NET 30.
```

**Pharma:**
```
Need 500 kg of Paracetamol API, IP grade, purity 99.5% minimum.
CoA and DMF documentation required. Delivery to Hyderabad
within 15 days. Budget Rs 800-1100 per kg.
WHO-GMP certified manufacturer only.
```

**Automotive:**
```
Require 10000 units of precision CNC machined brake calipers,
aluminum alloy 6061-T6, tolerance +/-0.02mm. IATF 16949
certified supplier only. Delivery to Chennai plant in 45 days.
Budget Rs 450-600 per unit. PPAP Level 3 documentation needed.
```

**Agriculture:**
```
Need 100 MT of DAP fertilizer, 18-46-0 grade, in 50kg bags.
BIS certified. Delivery to Punjab warehouse within 20 days.
Budget Rs 28000-32000 per MT. FCO compliance mandatory.
Payment 50% advance, 50% on delivery.
```

3. Click **"Submit RFQ"**

**What happens next (watch for this):**
- The AI **automatically parses** your free text and extracts structured fields:
  - Product name
  - HSN code (commodity classification)
  - Quantity and unit
  - Budget range (min/max)
  - Delivery window
  - Geography/location
- RFQ status changes: `DRAFT` --> `PARSED`
- The parsed fields appear in the **RFQ detail panel** on the right side of the page
- Your RFQ appears in the **RFQ list** on the left side

---

### Step 3: View Seller Matches

After parsing, the system uses **pgvector cosine similarity search** to match your requirement against all seller capability profiles.

**What you see in the detail panel:**
- **"Matched Sellers"** section with a count
- Each seller match shows:
  - Rank number (1, 2, 3...)
  - Seller enterprise name
  - Capabilities (as tags)
  - **Match score** (percentage -- how relevant this seller is)
- RFQ status changes: `PARSED` --> `MATCHED`

> **Important:** For matches to appear, there must be a registered seller with matching commodities/capabilities. Make sure you register a seller in the same industry (see [Registering a Seller Account](#registering-a-seller-account)).

---

### Step 4: Start AI Negotiations

Once you see matched sellers:

1. Click **"Start AI Negotiations with All Sellers"** button in the detail panel
2. This kicks off autonomous AI negotiation sessions with every matched seller simultaneously
3. A toast notification confirms: *"Negotiations started. AI agents are negotiating -- check the Negotiations page for live results."*
4. RFQ status changes: `MATCHED` --> `NEGOTIATING`

---

### Step 5: Watch AI Negotiation in Real-Time

**Navigate to:** Negotiations (click in sidebar), then click on an active session

This is the **flagship feature** -- two AI agents (one representing the buyer, one representing the seller) negotiate price autonomously in real-time.

**What you see on the session detail page:**

**Header:**
- Session ID
- Status badge (ACTIVE with green indicator, or AGREED, etc.)
- **Live indicator:** Green dot + "Live" when SSE stream is connected
- Your role ("You (Buyer)") and opponent name

**Gap Meter:**
- Visual bar showing the seller's latest offer (blue) and buyer's latest offer (green)
- **Gap percentage** showing how far apart the two sides are
- Color-coded: Green (close, under 2%), Amber (moderate), Red (far apart)

**Offers Timeline:**
- Each round shows: round number, which agent made the offer, price, confidence score
- Offers appear in **real-time via Server-Sent Events** (no page refresh needed)
- Agent reasoning is visible for each offer -- the AI explains why it chose that price

**Controls:**
- **"Next Turn"** -- Manually trigger the next negotiation round
- **"Override"** -- Inject your own price (overrides the AI agent's next move)

**Convergence:**
- Watch the price gap narrow over rounds
- When the gap reaches **2% or less**, the session automatically transitions to `AGREED`

---

### Step 6: Select the Best Offer

Once negotiations complete (sessions reach `AGREED` status):

**Navigate to:** Negotiations page

- You see all your sessions with their final status
- Sessions that reached `AGREED` show the **final negotiated price**
- The comparison table on the Marketplace page shows all seller negotiations side-by-side with:
  - Status (AGREED, FAILED, WALK_AWAY, TIMEOUT)
  - Latest offer price
  - Rounds completed

**Navigate to:** Escrow page

- Agreed sessions that don't have an escrow yet appear in the **"Select a Deal"** section
- For each agreed deal you see: seller name, agreed price, round count
- Click **"Select This Deal"** to create an escrow for that deal
- This creates the escrow in `PENDING_APPROVAL` status

---

## Seller-Side Testing

> **Prerequisite:** You must be logged in as a SELLER account.

### Step 1: View the Seller Dashboard

**URL:** [https://cadencia-magic-wallet.duckdns.org/dashboard](https://cadencia-magic-wallet.duckdns.org/dashboard)

**What you see:**
- Welcome message with your name and company
- **Stat cards:** Active RFQs, Pending Escrows, Agreed Sessions, Total Trades
- **Negotiation Sessions table** -- sessions where you are the seller
- **Escrow Activity table** -- escrows involving you
- **System Health** indicators

**Sidebar navigation (seller sees):**
- Dashboard
- **Seller Profile** (seller-only -- manage your capability profile)
- **Catalogue** (seller-only -- manage your product catalogue)
- Negotiations
- Escrow
- Treasury
- Compliance
- Settings

---

### Step 2: Set Up Your Seller Profile

**Navigate to:** Seller Profile (click in sidebar)

This is **critical** -- your capability profile is what the AI matching engine uses to find you when buyers upload relevant RFQs.

**What to verify:**
- Your current capability profile is displayed
- You can edit: product categories, certifications, production capacity, delivery regions, payment terms, quality standards
- After saving, the system **recomputes vector embeddings** so future RFQ matches use your updated profile

**Example profile description (Textiles seller):**
```
Premium cotton fabric manufacturer. Specialize in 40s-80s count cotton,
polyester-cotton blends, and organic cotton fabrics. OEKO-TEX Standard 100
certified. BIS certified facility. Capacity 50,000 meters/month.
Delivery across PAN India within 7-21 days.
```

---

### Step 3: Manage Your Catalogue

**Navigate to:** Catalogue (click in sidebar)

**What to verify:**
- You can **create** catalogue items with: product name, price, quantity, specifications
- Items are listed in a table format
- You can **edit** item pricing and availability
- You can **deactivate/delete** items

---

### Step 4: Monitor Negotiations

**Navigate to:** Negotiations (click in sidebar)

When a buyer starts negotiations on an RFQ that matched your profile, a negotiation session appears here with your AI agent negotiating on your behalf.

**What you see:**
- All sessions where you are the seller
- Status filters: ACTIVE, AGREED, WALK_AWAY, TIMEOUT, etc.
- Click on an active session to watch the **live negotiation** from the seller's perspective
- You see the same real-time SSE stream, gap meter, and offer timeline as the buyer
- You can use **"Override"** to inject your own price if you disagree with your AI agent's strategy

---

### Step 5: Accept the Deal (Escrow)

**Navigate to:** Escrow (click in sidebar)

When a buyer selects your agreed deal for escrow, it appears here in `PENDING_APPROVAL` status.

**What you do:**
1. You see the escrow card with: parties, amount, session ID, status stepper
2. The 6-step progress stepper shows you are at **Step 1: Deal Selected**
3. Click **"Accept Deal"** (green button)
4. This moves the escrow to `APPROVED` status --> **Step 2: Seller Approved**
5. The backend automatically deploys the smart contract on Algorand
6. Now you wait for the buyer to fund the escrow

**After buyer funds (Step 4: Buyer Funded):**
7. You see the escrow is now `FUNDED`
8. Click **"Mark Order Dispatched"** (blue button)
9. This moves to `DISPATCHED` status --> **Step 5: Order Dispatched**
10. Wait for buyer to confirm delivery

**After buyer confirms delivery:**
11. Escrow transitions to `RELEASED` --> **Step 6: Delivery Confirmed**
12. Funds are released to your Algorand wallet
13. You see: "Trade Complete! Funds released to seller."

---

## Complete End-to-End Trade Flow (Buyer + Seller)

For the **full experience**, open two browser windows (or use an incognito window for the second account).

### Prerequisites
- Register a **Buyer** account with one email (e.g., your personal email)
- Register a **Seller** account with a different email (e.g., a work email or second account)
- **Both accounts must be in the same industry** for the AI matching to connect them

### Step-by-Step Flow

| Step | Action | Who Does It | What Happens |
|------|--------|-------------|--------------|
| 1 | Register a buyer account | Buyer | Email OTP verification, account created |
| 2 | Register a seller account (same industry) | Seller | Email OTP verification, fill facility + capacity details |
| 3 | Set up seller capability profile | Seller | Go to Seller Profile, describe capabilities so AI can match |
| 4 | Upload an RFQ on the Marketplace page | Buyer | Type free-text requirement, click Submit RFQ |
| 5 | AI parses the RFQ | Automatic | Extracts product, quantity, budget, delivery, HSN code |
| 6 | AI matches to sellers | Automatic | pgvector cosine similarity finds matching sellers |
| 7 | Click "Start AI Negotiations with All Sellers" | Buyer | AI negotiation sessions launched for all matched sellers |
| 8 | Watch the live negotiation | Both | Open `/negotiations/[session_id]` -- see real-time offers via SSE |
| 9 | (Optional) Override the AI agent | Either | Inject a manual price offer |
| 10 | Negotiation reaches AGREED | Automatic | Price gap converges to under 2%, deal is struck |
| 11 | Buyer selects the best offer for escrow | Buyer | Go to Escrow page, click "Select This Deal" |
| 12 | Seller accepts the deal | Seller | Go to Escrow page, click "Accept Deal" |
| 13 | Smart contract deploys on Algorand | Automatic | Backend deploys escrow contract on testnet |
| 14 | Buyer funds the escrow | Buyer | Click "Fund via Pera Wallet" -- Magic signs the blockchain transaction |
| 15 | Seller marks order dispatched | Seller | Click "Mark Order Dispatched" |
| 16 | Buyer confirms delivery | Buyer | Click "Confirm Delivery -- Release Funds" |
| 17 | Funds released to seller on-chain | Automatic | Algorand smart contract transfers funds |
| 18 | Compliance records auto-generated | Automatic | FEMA + GST records created, Merkle root anchored on-chain |
| 19 | View compliance records | Both | Go to Compliance page -- audit logs, FEMA, GST downloads |

---

## Escrow & Blockchain Testing

**Navigate to:** Escrow (click in sidebar)

The escrow system uses **Algorand blockchain** smart contracts for trustless payment.

### The 6-Step Escrow Lifecycle

The escrow page shows a **visual progress stepper** with these 6 steps:

```
Step 1           Step 2            Step 3             Step 4           Step 5              Step 6
Deal Selected -> Seller Approved -> Contract Deployed -> Buyer Funded -> Order Dispatched -> Delivery Confirmed
(Buyer)          (Seller)           (Automatic)         (Buyer)          (Seller)            (Buyer)
```

| Step | Status             | Who Acts   | Action                              |
|------|--------------------|------------|-------------------------------------|
| 1    | PENDING_APPROVAL   | Buyer      | Selected a deal from agreed sessions|
| 2    | APPROVED           | Seller     | Clicks "Accept Deal"                |
| 3    | DEPLOYED           | Automatic  | Smart contract deployed on Algorand |
| 4    | FUNDED             | Buyer      | Clicks "Fund via Pera Wallet" -- Magic wallet signs the transaction |
| 5    | DISPATCHED         | Seller     | Clicks "Mark Order Dispatched"      |
| 6    | RELEASED           | Buyer      | Clicks "Confirm Delivery -- Release Funds" |

**Blockchain verification:**
- Each escrow card shows **Algorand transaction links** (opens Lora block explorer):
  - Contract App ID
  - Deploy TX ID
  - Fund TX ID
  - Release TX ID
- All transactions are on **Algorand Testnet** and publicly verifiable

**Wallet note:** The Magic wallet auto-provisions an Algorand wallet for every user. No separate wallet setup is needed. When funding, Magic handles the transaction signing in the background.

---

## Compliance & Audit Testing

**Navigate to:** Compliance (click in sidebar)

### Audit Log Tab

**What to verify:**
- Hash-chained audit log displayed for each escrow
- Each entry shows: event type, timestamp, event data, entry hash
- The **hash chain verifier** provides visual integrity confirmation
- Click "Verify" to run SHA-256 chain integrity check -- the system verifies that `entry_hash = SHA-256(event_data + prev_hash)` for every entry

### FEMA Tab (Cross-Border Compliance)

**What to verify:**
- FEMA records are auto-generated when an escrow is released
- Contains: transaction date, amount (INR equivalent), purpose code, counterparty country, RBI reference
- Download available as PDF or CSV
- 7-year retention enforced

### GST Tab (Domestic Compliance)

**What to verify:**
- GST records show: buyer GSTIN, seller GSTIN, HSN code, taxable value
- Tax breakdown: IGST / CGST / SGST amounts
- Download available as CSV
- 7-year retention enforced

---

## Treasury Dashboard Testing

**Navigate to:** Treasury (click in sidebar)

**What to verify:**
- **Pool Balance Cards**: INR, USDC, ALGO pool balances, and total portfolio value in INR
- **Live FX Rate**: Current INR/USDC exchange rate (from Frankfurter API) with update timestamp
- **FX Exposure Table**: Open positions with pair, direction, notional, entry rate, current rate, unrealized PnL
- **Liquidity Forecast Chart**: 30-day runway projection showing projected daily balances

---

## AI/LLM Features to Observe

Throughout testing, pay attention to these AI-powered capabilities:

| Feature                       | Where to See It                             | What Happens                                                    |
|-------------------------------|---------------------------------------------|-----------------------------------------------------------------|
| **NLP RFQ Parsing**           | Upload any free-text RFQ on Marketplace     | AI extracts product, quantity, budget, delivery, HSN code from plain English |
| **Vector Similarity Matching**| After RFQ is parsed (Marketplace detail panel)| pgvector cosine similarity ranks sellers by relevance score     |
| **Dual-Agent Negotiation**    | Negotiation session detail page             | Two AI agents autonomously negotiate price in real-time via SSE |
| **Convergence Detection**     | During active negotiation                   | Session auto-agrees when price gap drops to 2% or less          |
| **Stall Detection**           | If agents repeat same price 3+ rounds       | Session transitions to STALLED for human review                 |
| **Agent Reasoning**           | Offer details in negotiation timeline       | Each offer includes the AI's reasoning for its price choice     |
| **Human Override**            | Override button during active negotiation   | You can override the AI and inject your own offer mid-session   |
| **Prompt Injection Defense**  | Try entering "ignore previous instructions" as an RFQ | Input is sanitized, truncated at 8K chars, known jailbreak patterns blocked |

---

## Quick Smoke Test (10 Minutes)

If you have limited time, here is the fastest path to see all core features:

### Setup (3 minutes)
1. **Register as buyer** at `/register?role=buyer` -- fill enterprise info, delivery location, account details. Use a real email for OTP. (~90 sec)
2. **Open incognito window**, **register as seller** at `/register?role=seller` in the **same industry**. Fill enterprise info, facility, production capacity. Use a different real email. (~90 sec)

### Run the Flow (7 minutes)

| Time  | Action                                                                                    |
|-------|-------------------------------------------------------------------------------------------|
| 0:00  | **[Seller]** Go to Seller Profile, make sure capability profile is filled in              |
| 0:30  | **[Buyer]** Go to Marketplace, type a free-text RFQ, click Submit                         |
| 1:00  | **[Buyer]** Watch AI parse it into structured fields (product, quantity, budget, HSN code) |
| 1:30  | **[Buyer]** See matched sellers with relevance scores in the detail panel                 |
| 2:00  | **[Buyer]** Click "Start AI Negotiations with All Sellers"                                |
| 2:30  | **[Buyer]** Go to Negotiations, click on the active session to watch live                 |
| 3:00  | **[Seller]** Go to Negotiations, click on the same session from the seller's side         |
| 3:30  | **[Both]** Watch the real-time AI negotiation -- offers streaming in via SSE, gap narrowing|
| 5:00  | **[Both]** Session reaches AGREED -- see the final negotiated price                       |
| 5:30  | **[Buyer]** Go to Escrow page, click "Select This Deal"                                  |
| 6:00  | **[Seller]** Go to Escrow page, click "Accept Deal"                                      |
| 6:30  | **[Buyer]** Fund the escrow via Magic wallet                                              |
| 7:00  | **[Both]** Check Compliance page for auto-generated audit logs                            |

---

## Key Technical Highlights

| Aspect                    | Implementation                                                                         |
|---------------------------|----------------------------------------------------------------------------------------|
| **Authentication**        | Magic.link passwordless auth -- email OTP + auto-provisioned Algorand wallet           |
| **AI/LLM**               | Pluggable agent drivers (Gemini, Claude, OpenAI) for NLP parsing + autonomous negotiation |
| **Blockchain**            | Algorand smart contracts (Puya/Python, ARC-4 compliant) for trustless escrow           |
| **Vector Search**         | pgvector with IVFFlat/HNSW indexes for sub-2s seller matching across 1536-d embeddings |
| **Real-Time Streaming**   | Server-Sent Events (SSE) for live negotiation offer streaming                          |
| **Security**              | RS256 JWT, prompt injection defense, Redis rate limiting, hash-chained audit logs       |
| **Compliance**            | Auto-generated FEMA + GST records, 7-year retention, SHA-256 Merkle-root on-chain anchoring |
| **Architecture**          | Hexagonal / Domain-Driven Design with event-driven domain bus, Unit of Work pattern    |
| **Smart Contracts**       | Escrow with fund/release/refund/freeze methods, mandatory dry-run simulation           |
| **Data Residency**        | AWS ap-south-1 (Mumbai) for Indian data sovereignty                                    |
| **x402 Protocol**         | Algorand-native micropayment protocol for premium RFQ analytics                        |
| **Wallet**                | Magic Algorand Extension -- seamless wallet creation + transaction signing              |

---

## Troubleshooting

| Issue                                | Solution                                                                               |
|--------------------------------------|----------------------------------------------------------------------------------------|
| Not receiving OTP email              | Check spam/junk folder. Magic emails come from `magic.link` domain. Try a different email provider if blocked. |
| Registration fails at submit         | Verify PAN format (ABCDE1234F) and GSTIN format (2-digit state code + PAN + extras). Both are validated. |
| No seller matches after uploading RFQ| A seller in the same industry must be registered with a capability profile. Register a seller account first. |
| Negotiation not starting             | Make sure you clicked "Start AI Negotiations with All Sellers" on the Marketplace detail panel. |
| SSE stream not updating              | Refresh the page. Ensure the green "Live" indicator is showing on the session detail page. |
| Escrow "Accept Deal" not visible     | Only the seller sees the "Accept Deal" button. Login as the seller to accept. |
| Escrow "Fund" button not working     | Magic wallet is auto-provisioned. If issues persist, check Settings > Wallet for wallet status. |
| Page not loading                     | Clear browser cache, hard-refresh (Ctrl+Shift+R). Try a different browser. |
| OTP popup not appearing              | Ensure pop-ups are allowed for the site. Magic uses a popup for OTP entry. |

---

*For the most impactful demonstration, follow the [Complete End-to-End Trade Flow](#complete-end-to-end-trade-flow-buyer--seller) section using two browser windows with a buyer and seller from the same industry.*
