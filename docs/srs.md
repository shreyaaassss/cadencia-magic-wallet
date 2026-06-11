# Cadencia — Software Requirements Specification
> IEEE 830-Compatible · Version 1.0 · April 2026

| Field | Value |
|-------|-------|
| Document Type | Software Requirements Specification (SRS) |
| Standard | IEEE 830 / ISO/IEC 25010 compatible |
| Product | Cadencia — Production Backend v3.0 |
| Date | April 2026 |
| Status | Approved for Development |
| Audience | Engineering, QA, Architecture, DevOps |
| Prepared by | Cadencia Engineering Team |

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Overall System Description](#2-overall-system-description)
3. [Functional Requirements](#3-functional-requirements)
4. [API Specification](#4-api-specification)
5. [Data Requirements](#5-data-requirements)
6. [Smart Contract Specification](#6-smart-contract-specification)
7. [Security Requirements](#7-security-requirements)
8. [Non-Functional Requirements](#8-non-functional-requirements)
9. [Testing Requirements](#9-testing-requirements)
10. [Deployment & Infrastructure Requirements](#10-deployment--infrastructure-requirements)
11. [Bounded Context & Interface Reference](#11-bounded-context--interface-reference)

---

## 1. Introduction

### 1.1 Purpose

This Software Requirements Specification (SRS) defines the complete functional and non-functional requirements for the Cadencia production backend. It serves as the contractual specification between Product and Engineering, the authoritative reference for QA test case derivation, and the baseline against which architecture decisions are evaluated.

### 1.2 Scope

This document covers the Cadencia backend system — FastAPI application, Algorand smart contracts, PostgreSQL/pgvector database, Redis cache, and all external integrations — as defined in the production architecture v3.0. It does not cover frontend applications, mobile clients, or third-party KYC provider internals.

### 1.3 Definitions & Acronyms

| Term / Acronym | Definition |
|----------------|------------|
| RFQ | Request for Quotation — primary trade initiation document uploaded by a buyer |
| HSN | Harmonised System of Nomenclature — mandatory goods classification code for GST |
| MSME | Micro, Small & Medium Enterprise — primary target user category |
| FEMA | Foreign Exchange Management Act — Indian cross-border payment regulation |
| GST | Goods and Services Tax — Indian indirect tax with IGST/CGST/SGST components |
| GSTIN | GST Identification Number — 15-character unique identifier for GST-registered entities |
| PAN | Permanent Account Number — 10-character Indian tax identifier |
| Puya / PuyaPy | Algorand Foundation's Python-based smart contract language (successor to PyTeal) |
| ARC-4 | Algorand ABI specification for typed smart contract method calls |
| ARC-56 | Extended Algorand contract metadata format enabling auto-generated typed clients |
| AlgoKit | Algorand developer toolkit providing compile, deploy, and test utilities |
| pgvector | PostgreSQL extension for storing and querying vector embeddings |
| IVFFlat | Approximate nearest-neighbour index type in pgvector for cosine similarity search |
| SSE | Server-Sent Events — HTTP/1.1 streaming for real-time push from server to browser |
| DDD | Domain-Driven Design — software architecture methodology organising code by business domain |
| Hexagonal | Ports and Adapters architecture pattern isolating domain logic from infrastructure |
| UoW | Unit of Work — design pattern ensuring atomic database commits |
| JWT | JSON Web Token — RS256-signed bearer token for API authentication |
| HMAC | Hash-Based Message Authentication Code — used for API key storage and webhook signing |
| LLM | Large Language Model — AI model used for NLP parsing and agent negotiation |
| Dry-run | Algorand transaction simulation via `algod.dryrun()` before broadcasting to the network |
| Merkle root | Cryptographic commitment to a set of hashed audit records, anchored on-chain |

### 1.4 Document Conventions

- Requirements identified by unique ID in the format `SRS-XX-NNN` (e.g., `SRS-FR-001`).
- **SHALL** denotes mandatory requirements. **SHOULD** denotes recommended but non-mandatory. **MAY** denotes optional.
- All monetary values in Indian Rupees (INR) unless stated otherwise.
- All time values in UTC unless stated otherwise.
- All Algorand amounts in microALGO (1 ALGO = 1,000,000 microALGO).

---

## 2. Overall System Description

### 2.1 Product Perspective

Cadencia is a standalone, API-first modular monolith exposing a versioned REST API (`/v1/*`). It is deployed as a containerised service on AWS ap-south-1 and interacts with the Algorand blockchain (testnet for prototype, mainnet for production) and external LLM providers (Google Gemini, Anthropic Claude, or OpenAI) via pluggable adapters.

### 2.2 System Context

| External System | Integration Type | Direction | Purpose |
|----------------|-----------------|-----------|---------|
| Algorand Blockchain (testnet/mainnet) | algosdk + AlgoKit typed client | Bidirectional | Smart contract deploy, fund, release, refund; Merkle root anchoring |
| LLM Provider (Gemini / Claude / OpenAI) | HTTP REST (`IAgentDriver` adapter) | Outbound | RFQ NLP parsing; buyer/seller agent negotiation turns |
| KYC Provider | HTTP REST (`kyc_adapter`, mocked v1) | Outbound | Enterprise KYC verification (stub in prototype) |
| Frankfurter FX Feed | HTTP REST (`fx_feed_adapter`) | Inbound | Live INR ↔ USDC exchange rate for treasury dashboard |
| On/Off Ramp Provider | HTTP REST (`IPaymentProvider`) | Bidirectional | INR ↔ USDC conversion for escrow funding |
| PostgreSQL 16 + pgvector | asyncpg (async SQLAlchemy) | Bidirectional | Primary data store; vector similarity search for matching |
| Redis 7 | redis-py async | Bidirectional | Session caching; rate limiting; event state |

### 2.3 Seven-Layer System Architecture

| Layer | Name | Primary Responsibility |
|-------|------|----------------------|
| 1 | Marketplace & Onboarding | RFQ upload, LLM NLP field extraction, pgvector similarity matching, Top-N seller ranking |
| 2 | Agent Personalization Engine | AgentProfile storage, strategy weights, history embeddings, industry playbook injection |
| 3 | API Gateway | FastAPI routing, JWT validation, rate limiting, CORS, unified error envelope, SSE streaming |
| 4 | Core Services | NeutralEngine (negotiation), SettlementService (escrow), ComplianceGenerator (FEMA/GST) |
| 5 | Algorand Interaction | Puya contract typed client, algosdk integration, dry-run safety, Merkle anchoring |
| 6 | Data Layer | PostgreSQL 16 + pgvector, async SQLAlchemy, Unit of Work, Redis caching, structlog |
| 7 | External Integrations | Milestone oracle, INR↔USDC on/off-ramp, Frankfurter FX feed |

### 2.4 Key Design Constraints

> ⚠️ **SRS-DC-001** — All Algorand smart contracts SHALL be written in Algorand Python (Puya). PyTeal is explicitly prohibited throughout the codebase.

> ⚠️ **SRS-DC-002** — Smart contracts SHALL be compiled offline via `algokit compile py`. Runtime compilation in production startup is prohibited.

> ⚠️ **SRS-DC-003** — The domain layer (`src/*/domain/`) SHALL NOT import FastAPI, SQLAlchemy, algosdk, or any infrastructure library. Violations are enforced by Ruff TID252 linting.

> ⚠️ **SRS-DC-004** — Cross-domain communication SHALL occur only via domain events (`publisher.py`). Direct imports between bounded contexts are prohibited.

> ⚠️ **SRS-DC-005** — `X402_SIMULATION_MODE` SHALL be `false` in production. `SIM-` prefix tokens SHALL be rejected in all code paths.

---

## 3. Functional Requirements

### 3.1 Identity & Authentication (`identity` context)

#### 3.1.1 Enterprise Registration

| ID | Requirement | Priority |
|----|-------------|----------|
| SRS-FR-001 | The system SHALL accept enterprise registration with: `legal_name` (VARCHAR 255), `pan` (VARCHAR 10, unique), `gstin` (VARCHAR 15, unique), `trade_role` (BUYER\|SELLER\|BOTH), `industry_vertical`, `geography` (default IN), `min_order_value`, `max_order_value`, `commodities` (text array), `algorand_wallet` (VARCHAR 64). | MUST |
| SRS-FR-002 | The system SHALL enforce PAN format validation: 10 alphanumeric characters (AAAAA9999A pattern). | MUST |
| SRS-FR-003 | The system SHALL enforce GSTIN format validation: 15-character alphanumeric. | MUST |
| SRS-FR-004 | The system SHALL create a default ADMIN user associated with the enterprise at registration. | MUST |
| SRS-FR-005 | The system SHALL implement a KYC state machine with states: `PENDING → KYC_SUBMITTED → VERIFIED → ACTIVE`. Transitions SHALL be audited. | MUST |
| SRS-FR-006 | The system SHALL support four user roles: `ADMIN`, `TREASURY_MANAGER`, `COMPLIANCE_OFFICER`, `AUDITOR`. | MUST |
| SRS-FR-007 | The system SHALL allow enterprises to link an Algorand wallet address (58-character base32 public key). | MUST |

#### 3.1.2 JWT Authentication

| ID | Requirement | Priority |
|----|-------------|----------|
| SRS-FR-010 | The system SHALL issue RS256-signed JWT access tokens with 15-minute expiry on successful login. | MUST |
| SRS-FR-011 | The system SHALL issue refresh tokens with 30-day expiry, delivered as httpOnly cookies. | MUST |
| SRS-FR-012 | The system SHALL validate JWT signature and expiry on every protected endpoint before executing any business logic. | MUST |
| SRS-FR-013 | The system SHALL support API key creation (HMAC-SHA256 hashed in DB) for M2M access via `X-API-Key` header. | MUST |
| SRS-FR-014 | The system SHALL support API key revocation; revoked keys SHALL be rejected within 1 minute. | MUST |
| SRS-FR-015 | The system SHALL enforce role-based access control via `require_role()` dependency on every protected route. | MUST |

#### 3.1.3 Rate Limiting

| ID | Requirement | Priority |
|----|-------------|----------|
| SRS-FR-020 | The system SHALL enforce Redis-backed rate limiting of 100 requests per 60 seconds per `enterprise_id`. | MUST |
| SRS-FR-021 | The system SHALL return HTTP 429 with a `Retry-After` header when the rate limit is exceeded. | MUST |
| SRS-FR-022 | The system SHALL use sliding window rate limiting with 1-minute granularity. | MUST |

---

### 3.2 Marketplace & RFQ (`marketplace` context)

#### 3.2.1 RFQ Upload & Parsing

| ID | Requirement | Priority |
|----|-------------|----------|
| SRS-FR-030 | The system SHALL accept RFQ upload as free-text (`document_type: free_text`) with no structured form requirement. | MUST |
| SRS-FR-031 | The system SHALL pass RFQ raw text through LLM NLP extraction (`rfq_parser.py`) to populate: `product`, `hsn_code`, `quantity`, `unit`, `budget_min`, `budget_max`, `delivery_window` (ISO 8601 date), `geography`. | MUST |
| SRS-FR-032 | All LLM inputs SHALL be sanitised for prompt injection: known injection patterns (`ignore previous instructions`, `system prompt`, `jailbreak`, token boundary markers) SHALL raise HTTP 422 before the LLM call. | MUST |
| SRS-FR-033 | LLM input SHALL be hard-truncated at 8,000 characters before submission. | MUST |
| SRS-FR-034 | The system SHALL implement the RFQ state machine: `DRAFT → PARSED → MATCHED → CONFIRMED → SETTLED`. | MUST |
| SRS-FR-035 | The system SHALL return `parsed_fields` in the RFQ response alongside the match list. | MUST |

#### 3.2.2 pgvector Seller Matching

| ID | Requirement | Priority |
|----|-------------|----------|
| SRS-FR-040 | The system SHALL store seller capability profiles as 1536-dimensional pgvector embeddings. | MUST |
| SRS-FR-041 | The system SHALL perform IVFFlat cosine similarity search returning Top-N ranked sellers in under 2 seconds across 10,000 profiles (p95). | MUST |
| SRS-FR-042 | The system SHALL expose a capability profile embedding recomputation endpoint. | MUST |
| SRS-FR-043 | The system SHALL allow buyers to confirm a specific `match_id`, triggering `RFQConfirmed` domain event and session creation. | MUST |

---

### 3.3 Negotiation Engine (`negotiation` context)

#### 3.3.1 Agent Negotiation

| ID | Requirement | Priority |
|----|-------------|----------|
| SRS-FR-050 | The system SHALL create a `NegotiationSession` for each confirmed RFQ match with status `ACTIVE`. | MUST |
| SRS-FR-051 | The system SHALL maintain an `AgentProfile` per enterprise with: `risk_profile` (risk_appetite, budget_ceiling, margin_floor), `automation_level`, `strategy_weights` (avg_deviation, avg_rounds, win_rate, stall_threshold), `playbook_config`. | MUST |
| SRS-FR-052 | Buyer agents SHALL never submit an offer exceeding `budget_ceiling` in `AgentProfile`. Violation SHALL raise `PolicyViolation` and the offer SHALL be blocked. | MUST |
| SRS-FR-053 | Seller agents SHALL never accept an offer below `margin_floor` in `AgentProfile`. | MUST |
| SRS-FR-054 | The `NeutralEngine` SHALL detect convergence when the price gap between the last buyer and last seller offer is ≤ 2% of the buyer's last price. | MUST |
| SRS-FR-055 | The `NeutralEngine` SHALL detect stall when `round_count ≥ stall_threshold` (default 10) and SHALL transition the session to `HUMAN_REVIEW`. | MUST |
| SRS-FR-056 | Agent output SHALL be validated as JSON with `action ∈ {OFFER, ACCEPT, REJECT, COUNTER}` and `price` as numeric. Non-conforming output SHALL raise `ValidationError`. | MUST |
| SRS-FR-057 | Session states SHALL be: `ACTIVE → AGREED \| FAILED \| EXPIRED \| HUMAN_REVIEW`. | MUST |
| SRS-FR-058 | On `SessionAgreed`, the system SHALL emit a `SessionAgreed` domain event to the settlement context within 1 second. | MUST |

#### 3.3.2 SSE Streaming & Human Override

| ID | Requirement | Priority |
|----|-------------|----------|
| SRS-FR-060 | The system SHALL expose a Server-Sent Events (SSE) stream at `GET /v1/sessions/{id}/stream` emitting one event per negotiation round. | MUST |
| SRS-FR-061 | SSE events SHALL include: event type (`offer \| agreed \| failed \| stalled`), round number, proposer role, price, confidence score, and `session_id`. | MUST |
| SRS-FR-062 | The system SHALL accept human override offers via `POST /v1/sessions/{id}/override`, replacing the agent's next offer with the human-provided price. | MUST |
| SRS-FR-063 | Human override events SHALL be logged as `HumanOverride` domain events and persisted as `is_human_override=true` in the offers table. | MUST |
| SRS-FR-064 | Human override data SHALL be used to update `AgentProfile` `strategy_weights` for future sessions. | SHOULD |

---

### 3.4 Settlement & Escrow (`settlement` context)

#### 3.4.1 Algorand Escrow Lifecycle

| ID | Requirement | Priority |
|----|-------------|----------|
| SRS-FR-070 | On `SessionAgreed` event, the system SHALL automatically deploy a `CadenciaEscrow` ARC-4 smart contract on Algorand with the agreed buyer, seller, amount (microALGO), and `session_id`. | MUST |
| SRS-FR-071 | ALL Algorand contract calls (deploy, fund, release, refund, freeze, unfreeze) SHALL be preceded by a dry-run simulation via `algod.dryrun()`. Dry-run failure SHALL raise `BlockchainSimulationError` and the transaction SHALL NOT be broadcast. | MUST |
| SRS-FR-072 | The escrow state machine SHALL enforce: `DEPLOYED(0) → FUNDED(1) → RELEASED(2) \| REFUNDED(3)`. `FROZEN` flag is orthogonal and prevents state transitions while set. | MUST |
| SRS-FR-073 | The `fund` operation SHALL be an atomic `PaymentTransaction` (amount == escrow.amount) + `AppCallTransaction`. Partial funding SHALL be rejected. | MUST |
| SRS-FR-074 | The `release` operation SHALL compute a Merkle root from all session audit events and anchor it in the Algorand transaction `Note` field before transferring funds to the seller. | MUST |
| SRS-FR-075 | The `refund` operation SHALL return the full escrow amount to the buyer address; it SHALL only succeed from `FUNDED` state. | MUST |
| SRS-FR-076 | Any party (buyer, seller, or platform admin) MAY freeze an escrow; only the platform admin (contract creator) MAY unfreeze. | MUST |
| SRS-FR-077 | Algorand transaction submission SHALL be idempotent — safe to retry without risk of double-spend. | MUST |

#### 3.4.2 Merkle Service

| ID | Requirement | Priority |
|----|-------------|----------|
| SRS-FR-080 | The system SHALL compute a SHA-256 hash chain over all audit log entries for a session. | MUST |
| SRS-FR-081 | The Merkle root SHALL be stored in `escrow_contracts.merkle_root` and anchored on-chain at release. | MUST |
| SRS-FR-082 | The system SHALL expose `GET /v1/audit/proof/{session_id}` returning the Merkle proof for independent verification. | MUST |

---

### 3.5 Compliance (`compliance` context)

| ID | Requirement | Priority |
|----|-------------|----------|
| SRS-FR-090 | The system SHALL generate a FEMA record on every `EscrowReleased` event containing: transaction date, amount (INR equivalent), purpose code, counterparty country, RBI reference. | MUST |
| SRS-FR-091 | The system SHALL generate a GST record on every `EscrowReleased` event containing: GSTIN of buyer and seller, HSN code, taxable value, IGST amount, CGST amount, SGST amount. | MUST |
| SRS-FR-092 | The system SHALL expose PDF and CSV export endpoints for both FEMA and GST records per session. | MUST |
| SRS-FR-093 | The system SHALL enforce 7-year minimum retention on all `audit_log` and `compliance_records` rows via PostgreSQL row-level policy. | MUST |
| SRS-FR-094 | The audit log SHALL be append-only; no `UPDATE` or `DELETE` operations SHALL be permitted on `audit_log` rows. | MUST |
| SRS-FR-095 | Each `audit_log` entry SHALL store `prev_hash` (SHA-256 of prior entry) and `entry_hash` (SHA-256 of this entry's data + `prev_hash`). | MUST |
| SRS-FR-096 | The system SHALL expose a bulk compliance export endpoint accepting a date range and returning a ZIP archive of PDF/CSV records. | SHOULD |

---

### 3.6 Treasury (`treasury` context)

| ID | Requirement | Priority |
|----|-------------|----------|
| SRS-FR-100 | The system SHALL expose `GET /v1/treasury/dashboard` returning: INR pool balance, USDC pool balance, current INR/USDC FX rate (from Frankfurter feed), total open escrow value. | MUST |
| SRS-FR-101 | The system SHALL expose `GET /v1/treasury/fx-exposure` returning open FX position summary (total INR-equivalent locked in USDC). | MUST |
| SRS-FR-102 | The system SHALL expose `GET /v1/treasury/liquidity-forecast` returning a 30-day liquidity runway calculation based on current pool and historical settlement rate. | SHOULD |

---

## 4. API Specification

### 4.1 Global API Standards

- All endpoints versioned under `/v1/` prefix.
- All responses follow the `ApiResponse[T]` envelope:
  ```json
  { "success": true,  "data": { ... }, "error": null,    "request_id": "uuid" }
  { "success": false, "data": null,    "error": { "code": "...", "message": "...", "details": {} }, "request_id": "uuid" }
  ```
- Pagination via `CursorPage[T]` (default) with `next_cursor` and `has_more` fields.
- `Content-Type: application/json` for all request/response bodies except the SSE stream.
- SSE stream `Content-Type: text/event-stream`.

### 4.2 HTTP Status Code Mapping

| Domain Error | HTTP Status | Error Code |
|-------------|-------------|------------|
| `NotFoundError` | 404 | `NOT_FOUND` |
| `PolicyViolation` | 422 | `POLICY_VIOLATION` |
| `ValidationError` | 422 | `VALIDATION_ERROR` |
| `RateLimitError` | 429 | `RATE_LIMIT_EXCEEDED` |
| `BlockchainSimulationError` | 502 | `BLOCKCHAIN_DRY_RUN_FAILED` |
| `AuthenticationError` | 401 | `UNAUTHORIZED` |
| `AuthorizationError` | 403 | `FORBIDDEN` |
| `UnexpectedError` | 500 | `INTERNAL_ERROR` |

### 4.3 Endpoint Catalogue

#### Authentication & Identity

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/v1/auth/register` | None | Register enterprise + admin user |
| `POST` | `/v1/auth/login` | None | Returns JWT access + refresh tokens |
| `POST` | `/v1/auth/refresh` | Refresh JWT | Rotate access token |
| `POST` | `/v1/auth/api-keys` | JWT | Create API key for M2M access |
| `DELETE` | `/v1/auth/api-keys/{key_id}` | JWT | Revoke API key |
| `GET` | `/v1/enterprises/{id}` | JWT | Get enterprise profile |
| `PATCH` | `/v1/enterprises/{id}/kyc` | JWT | Submit KYC documents |
| `PUT` | `/v1/enterprises/{id}/agent-config` | JWT | Update agent personalization config |

#### Marketplace

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/v1/marketplace/rfq` | JWT | Upload RFQ document (triggers NLP + matching) |
| `GET` | `/v1/marketplace/rfq/{id}` | JWT | Get RFQ with parsed fields + match list |
| `GET` | `/v1/marketplace/rfq/{id}/matches` | JWT | Get ranked match list |
| `POST` | `/v1/marketplace/rfq/{id}/confirm` | JWT | Confirm RFQ, select match, initiate negotiation |
| `PUT` | `/v1/marketplace/capability-profile` | JWT | Update seller capability profile |
| `POST` | `/v1/marketplace/capability-profile/embeddings` | JWT | Recompute embeddings via LLM |

#### Negotiation Sessions

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/v1/sessions` | JWT | Create session from confirmed match |
| `GET` | `/v1/sessions/{id}` | JWT | Get session state + offer history |
| `GET` | `/v1/sessions/{id}/stream` | JWT | SSE stream — live agent turn events |
| `POST` | `/v1/sessions/{id}/override` | JWT | Human override: inject offer mid-session |
| `POST` | `/v1/sessions/{id}/terminate` | JWT | Admin-terminate session |

#### Escrow

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/v1/escrow/{session_id}` | JWT | Get escrow state + Algorand app info |
| `POST` | `/v1/escrow/{id}/fund` | JWT | Fund escrow (atomic PaymentTxn + AppCall) |
| `POST` | `/v1/escrow/{id}/release` | JWT | Release funds to seller with Merkle root |
| `POST` | `/v1/escrow/{id}/refund` | JWT | Refund buyer (dispute resolution) |
| `POST` | `/v1/escrow/{id}/freeze` | JWT | Freeze escrow during dispute |

#### Audit, Compliance & Treasury

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/v1/audit/log` | JWT (AUDITOR) | Paginated audit log for enterprise |
| `GET` | `/v1/audit/proof/{session_id}` | JWT | Merkle proof for session audit trail |
| `GET` | `/v1/compliance/fema/{session_id}` | JWT | FEMA record download (PDF/CSV) |
| `GET` | `/v1/compliance/gst/{session_id}` | JWT | GST reconciliation record download |
| `POST` | `/v1/compliance/export` | JWT | Bulk compliance export (date range) |
| `GET` | `/v1/treasury/dashboard` | JWT (TREASURY_MANAGER) | Pool balances + FX rate |
| `GET` | `/v1/treasury/fx-exposure` | JWT | Open FX position summary |
| `GET` | `/v1/treasury/liquidity-forecast` | JWT | 30-day liquidity runway |
| `GET` | `/metrics` | Internal only | Prometheus metrics endpoint |
| `GET` | `/health` | None | DB + Redis + Algorand health check |

### 4.4 Key Request / Response Examples

**RFQ Upload:**
```json
POST /v1/marketplace/rfq
{
  "raw_text": "We require 500 MT of HR Coil (HSN 7208), budget ₹45,000–₹50,000/MT, delivery by April 30 to Mumbai.",
  "document_type": "free_text"
}
```

**RFQ Response (after NLP parsing):**
```json
{
  "success": true,
  "data": {
    "rfq_id": "uuid",
    "parsed_fields": {
      "product": "HR Coil",
      "hsn_code": "7208",
      "quantity": "500 MT",
      "budget_min": 45000,
      "budget_max": 50000,
      "delivery_window": "2026-04-30",
      "geography": "Mumbai"
    },
    "matches": [
      { "match_id": "uuid", "seller_name": "IndiaSteel Ltd", "score": 0.94, "rank": 1 }
    ],
    "status": "MATCHED"
  }
}
```

**SSE Stream events:**
```
data: {"event": "offer",  "round": 3, "proposer": "BUYER",  "price": 47500, "confidence": 0.82}
data: {"event": "offer",  "round": 4, "proposer": "SELLER", "price": 48200, "confidence": 0.76}
data: {"event": "agreed", "final_price": 47800, "session_id": "uuid"}
data: {"event": "stalled","round": 10, "session_id": "uuid"}
```

---

## 5. Data Requirements

### 5.1 Database Schema

```sql
-- ─── IDENTITY ─────────────────────────────────────────────────────────────────

CREATE TABLE enterprises (
    enterprise_id     UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_name        VARCHAR(255) NOT NULL,
    pan               VARCHAR(10)  UNIQUE NOT NULL,   -- pattern: AAAAA9999A
    gstin             VARCHAR(15)  UNIQUE NOT NULL,   -- 15-char alphanumeric
    kyc_status        VARCHAR(20)  NOT NULL DEFAULT 'PENDING',
                                  -- PENDING | KYC_SUBMITTED | VERIFIED | ACTIVE
    trade_role        VARCHAR(10)  NOT NULL DEFAULT 'BUYER',
                                  -- BUYER | SELLER | BOTH
    algorand_wallet   VARCHAR(64),
    industry_vertical VARCHAR(100),
    geography         VARCHAR(100) DEFAULT 'IN',
    min_order_value   NUMERIC(18,2),
    max_order_value   NUMERIC(18,2),
    commodities       TEXT[],
    listing_active    BOOLEAN      DEFAULT TRUE,
    created_at        TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE users (
    user_id       UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    enterprise_id UUID         NOT NULL REFERENCES enterprises(enterprise_id),
    email         VARCHAR(255) UNIQUE NOT NULL,
    full_name     VARCHAR(255),
    role          VARCHAR(30)  NOT NULL,
                               -- ADMIN | TREASURY_MANAGER | COMPLIANCE_OFFICER | AUDITOR
    password_hash VARCHAR(255) NOT NULL,
    is_active     BOOLEAN      DEFAULT TRUE,
    created_at    TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE api_keys (
    key_id        UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    enterprise_id UUID         NOT NULL REFERENCES enterprises(enterprise_id),
    key_hash      VARCHAR(128) UNIQUE NOT NULL,  -- HMAC-SHA256; never plaintext
    is_active     BOOLEAN      DEFAULT TRUE,
    expires_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ  DEFAULT NOW()
);

-- ─── MARKETPLACE ──────────────────────────────────────────────────────────────

CREATE TABLE rfqs (
    rfq_id          UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    enterprise_id   UUID          NOT NULL REFERENCES enterprises(enterprise_id),
    raw_text        TEXT          NOT NULL,
    status          VARCHAR(20)   NOT NULL DEFAULT 'DRAFT',
                                  -- DRAFT | PARSED | MATCHED | CONFIRMED | SETTLED
    product         VARCHAR(255),
    hsn_code        VARCHAR(10),
    quantity        NUMERIC(18,4),
    unit            VARCHAR(50),
    budget_min      NUMERIC(18,2),
    budget_max      NUMERIC(18,2),
    delivery_window DATE,
    geography       VARCHAR(100),
    embedding       vector(1536), -- HNSW index
    created_at      TIMESTAMPTZ   DEFAULT NOW()
);

CREATE TABLE capability_profiles (
    profile_id    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    enterprise_id UUID         UNIQUE NOT NULL REFERENCES enterprises(enterprise_id),
    commodities   TEXT[],
    embedding     vector(1536), -- IVFFlat index (cosine)
    updated_at    TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE matches (
    match_id             UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    rfq_id               UUID    NOT NULL REFERENCES rfqs(rfq_id),
    seller_enterprise_id UUID    NOT NULL REFERENCES enterprises(enterprise_id),
    score                FLOAT   NOT NULL,
    rank                 INTEGER NOT NULL,
    created_at           TIMESTAMPTZ DEFAULT NOW()
);

-- ─── NEGOTIATION ──────────────────────────────────────────────────────────────

CREATE TABLE negotiation_sessions (
    session_id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    rfq_id               UUID         NOT NULL REFERENCES rfqs(rfq_id),
    match_id             UUID         NOT NULL REFERENCES matches(match_id),
    buyer_enterprise_id  UUID         NOT NULL REFERENCES enterprises(enterprise_id),
    seller_enterprise_id UUID         NOT NULL REFERENCES enterprises(enterprise_id),
    status               VARCHAR(20)  NOT NULL DEFAULT 'ACTIVE',
                                      -- ACTIVE | AGREED | FAILED | EXPIRED | HUMAN_REVIEW
    agreed_price         NUMERIC(18,2),
    agreed_terms         JSONB,
    round_count          INTEGER      DEFAULT 0,
    created_at           TIMESTAMPTZ  DEFAULT NOW(),
    completed_at         TIMESTAMPTZ
);

CREATE TABLE offers (
    offer_id          UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id        UUID          NOT NULL REFERENCES negotiation_sessions(session_id),
    round_number      INTEGER       NOT NULL,
    proposer_role     VARCHAR(10)   NOT NULL,   -- BUYER | SELLER
    price             NUMERIC(18,2) NOT NULL,
    terms             JSONB,
    confidence        FLOAT,
    agent_reasoning   TEXT,          -- LLM rationale stored for audit
    is_human_override BOOLEAN       DEFAULT FALSE,
    created_at        TIMESTAMPTZ   DEFAULT NOW()
);

CREATE TABLE agent_profiles (
    profile_id       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    enterprise_id    UUID        UNIQUE NOT NULL REFERENCES enterprises(enterprise_id),
    risk_profile     JSONB       NOT NULL,
    -- { "risk_appetite": "low|medium|high", "budget_ceiling": float, "margin_floor": float }
    automation_level VARCHAR(20) DEFAULT 'FULL',
    strategy_weights JSONB,
    -- { "avg_deviation": float, "avg_rounds": int, "win_rate": float, "stall_threshold": int }
    playbook_config  JSONB,
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

-- ─── SETTLEMENT ───────────────────────────────────────────────────────────────

CREATE TABLE escrow_contracts (
    escrow_id        UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id       UUID         UNIQUE NOT NULL REFERENCES negotiation_sessions(session_id),
    algo_app_id      BIGINT       UNIQUE,
    algo_app_address VARCHAR(64),
    amount_microalgo BIGINT       NOT NULL,
    status           VARCHAR(20)  NOT NULL DEFAULT 'DEPLOYED',
                                  -- DEPLOYED | FUNDED | RELEASED | REFUNDED | FROZEN
    deploy_tx_id     VARCHAR(128),
    fund_tx_id       VARCHAR(128),
    release_tx_id    VARCHAR(128),
    merkle_root      VARCHAR(128), -- anchored on-chain at release
    frozen           BOOLEAN      DEFAULT FALSE,
    created_at       TIMESTAMPTZ  DEFAULT NOW(),
    settled_at       TIMESTAMPTZ
);

CREATE TABLE settlements (
    settlement_id       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    escrow_id           UUID        NOT NULL REFERENCES escrow_contracts(escrow_id),
    milestone_index     INTEGER     NOT NULL,
    amount_microalgo    BIGINT      NOT NULL,
    tx_id               VARCHAR(128) NOT NULL,
    oracle_confirmation JSONB,
    settled_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ─── COMPLIANCE ───────────────────────────────────────────────────────────────

CREATE TABLE audit_log (
    log_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    enterprise_id UUID        NOT NULL REFERENCES enterprises(enterprise_id),
    session_id    UUID,
    event_type    VARCHAR(50) NOT NULL,
    event_data    JSONB       NOT NULL,
    prev_hash     VARCHAR(128),                -- SHA-256 of prior entry
    entry_hash    VARCHAR(128) NOT NULL,       -- SHA-256(event_data + prev_hash)
    created_at    TIMESTAMPTZ DEFAULT NOW()
    -- Retention: 7 years minimum (RLS + archival job)
    -- Append-only: no UPDATE or DELETE permitted
);
CREATE INDEX audit_log_enterprise_idx ON audit_log(enterprise_id, created_at DESC);

CREATE TABLE compliance_records (
    record_id     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    enterprise_id UUID        NOT NULL REFERENCES enterprises(enterprise_id),
    session_id    UUID        NOT NULL REFERENCES negotiation_sessions(session_id),
    record_type   VARCHAR(20) NOT NULL,  -- FEMA | GST
    record_data   JSONB       NOT NULL,
    generated_at  TIMESTAMPTZ DEFAULT NOW()
);
```

### 5.2 pgvector Index Definitions

```sql
-- IVFFlat for capability profile matching (primary use case)
CREATE INDEX ON capability_profiles
  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- HNSW for RFQ reverse-matching
CREATE INDEX ON rfqs
  USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
```

Embeddings are 1536-dimensional `float32` vectors (OpenAI `text-embedding-3-small` compatible; swappable via `IMatchmakingEngine` port).

### 5.3 Data Retention Policy

| Table | Minimum Retention | Enforcement |
|-------|-------------------|-------------|
| `audit_log` | 7 years | PostgreSQL RLS + S3 Glacier archival job |
| `compliance_records` | 7 years | Same as `audit_log` |
| `offers` | 3 years | Soft-delete with `archived_at` timestamp |
| `negotiation_sessions` | 3 years | Soft-delete with `completed_at` timestamp |
| `escrow_contracts` | Permanent | Never deleted; on-chain Merkle root provides independent proof |

### 5.4 Table Summary

| Table | Domain | Primary Key | Key Indexes |
|-------|--------|-------------|-------------|
| `enterprises` | identity | `enterprise_id` (UUID) | `pan` unique, `gstin` unique |
| `users` | identity | `user_id` (UUID) | `email` unique |
| `api_keys` | identity | `key_id` (UUID) | `key_hash` unique |
| `rfqs` | marketplace | `rfq_id` (UUID) | HNSW on `embedding` |
| `capability_profiles` | marketplace | `profile_id` (UUID) | IVFFlat on `embedding` |
| `matches` | marketplace | `match_id` (UUID) | `rfq_id` index |
| `negotiation_sessions` | negotiation | `session_id` (UUID) | `rfq_id`, `status` indexes |
| `offers` | negotiation | `offer_id` (UUID) | `(session_id, round_number)` index |
| `agent_profiles` | negotiation | `profile_id` (UUID) | `enterprise_id` unique |
| `escrow_contracts` | settlement | `escrow_id` (UUID) | `session_id` unique, `algo_app_id` unique |
| `settlements` | settlement | `settlement_id` (UUID) | `escrow_id` index |
| `audit_log` | compliance | `log_id` (UUID) | `(enterprise_id, created_at DESC)` |
| `compliance_records` | compliance | `record_id` (UUID) | `(enterprise_id, record_type)` |

---

## 6. Smart Contract Specification

### 6.1 Contract Overview

| Field | Value |
|-------|-------|
| Contract name | `CadenciaEscrow` |
| Language | Algorand Python (Puya / PuyaPy) |
| ABI standard | ARC-4 + ARC-56 |
| Source file | `contracts/escrow_contract.py` |
| Compiled output | `artifacts/CadenciaEscrow.approval.teal`, `.clear.teal`, `.arc56.json`, `CadenciaEscrowClient.py` |
| Compilation | `algokit compile py contracts/escrow_contract.py --out-dir artifacts/` — offline only, never at runtime |

### 6.2 Global State Schema

| Variable | Type | Description |
|----------|------|-------------|
| `buyer` | `Account` (bytes[32]) | Algorand address of the buyer enterprise |
| `seller` | `Account` (bytes[32]) | Algorand address of the seller enterprise |
| `amount` | `UInt64` | Escrow amount in microALGO (must match payment transaction) |
| `session_id` | `Bytes` | Cadencia negotiation session UUID (UTF-8 encoded) |
| `status` | `UInt64` | `0`=DEPLOYED, `1`=FUNDED, `2`=RELEASED, `3`=REFUNDED |
| `frozen` | `UInt64` | `0`=normal operation, `1`=frozen (no state transitions permitted) |

### 6.3 ABI Methods

| Method | Parameters | Access Control | Pre-condition | Post-condition |
|--------|-----------|---------------|---------------|----------------|
| `initialize(buyer, seller, amount, session_id) → void` | ARC-4 typed args | Creator only (create=require) | None — CREATE call | `status=0`, `frozen=0` |
| `fund(payment: PaymentTransaction) → void` | GroupTransaction | Any caller (buyer) | `status==0`, `frozen==0`; `payment.amount==self.amount`; `payment.receiver==app_address` | `status=1` |
| `release(merkle_root: String) → void` | Merkle root hash | Creator only | `status==1`, `frozen==0` | `status=2`; inner payment → seller |
| `refund(reason: String) → void` | Reason string | Creator only | `status==1` | `status=3`; inner payment → buyer |
| `freeze() → void` | None | buyer OR seller OR creator | Any status | `frozen=1` |
| `unfreeze() → void` | None | Creator only | `frozen==1` | `frozen=0` |

### 6.4 Puya Source

```python
# contracts/escrow_contract.py
from algopy import (
    ARC4Contract, arc4, Bytes, UInt64, Account,
    GlobalState, Txn, Global, itxn,
)

class CadenciaEscrow(ARC4Contract):
    buyer:      Account
    seller:     Account
    amount:     UInt64
    session_id: Bytes
    status:     UInt64   # 0=DEPLOYED, 1=FUNDED, 2=RELEASED, 3=REFUNDED
    frozen:     UInt64   # 0=normal, 1=frozen

    @arc4.abimethod(allow_actions=["NoOp"], create="require")
    def initialize(self, buyer, seller, amount, session_id) -> None:
        self.buyer      = buyer.native
        self.seller     = seller.native
        self.amount     = amount.native
        self.session_id = session_id.bytes
        self.status     = UInt64(0)
        self.frozen     = UInt64(0)

    @arc4.abimethod
    def fund(self, payment: arc4.PaymentTransaction) -> None:
        assert self.status == UInt64(0), "Not in DEPLOYED state"
        assert self.frozen == UInt64(0), "Escrow is frozen"
        assert payment.native.receiver == Global.current_application_address
        assert payment.native.amount == self.amount
        self.status = UInt64(1)

    @arc4.abimethod
    def release(self, merkle_root: arc4.String) -> None:
        assert Txn.sender == Global.creator_address, "Only creator can release"
        assert self.status == UInt64(1), "Not funded"
        assert self.frozen == UInt64(0), "Escrow is frozen"
        itxn.Payment(
            receiver=self.seller,
            amount=self.amount,
            fee=Global.min_txn_fee,
        ).submit()
        self.status = UInt64(2)

    @arc4.abimethod
    def refund(self, reason: arc4.String) -> None:
        assert Txn.sender == Global.creator_address, "Only creator can refund"
        assert self.status == UInt64(1), "Not funded"
        itxn.Payment(
            receiver=self.buyer,
            amount=self.amount,
            fee=Global.min_txn_fee,
        ).submit()
        self.status = UInt64(3)

    @arc4.abimethod
    def freeze(self) -> None:
        assert Txn.sender in (self.buyer, self.seller, Global.creator_address)
        self.frozen = UInt64(1)

    @arc4.abimethod
    def unfreeze(self) -> None:
        assert Txn.sender == Global.creator_address
        self.frozen = UInt64(0)
```

### 6.5 Contract Safety Requirements

| ID | Safety Requirement |
|----|-------------------|
| SRS-SC-001 | All contract method calls SHALL be preceded by `algod.dryrun()` simulation (`ESCROW_DRY_RUN_ENABLED=true`). Dry-run failure SHALL prevent broadcast and raise `BlockchainSimulationError`. |
| SRS-SC-002 | The `fund()` method SHALL verify `payment.amount == self.amount` atomically. Underfunding or overfunding SHALL cause the transaction group to fail. |
| SRS-SC-003 | `release()` and `refund()` SHALL be inaccessible when `frozen==1`. The smart contract SHALL assert `frozen==0` before executing payment. |
| SRS-SC-004 | Only the contract creator (AlgorandGateway signing key) MAY call `release()`, `refund()`, or `unfreeze()`. Unauthorized callers SHALL cause the contract to reject the transaction. |
| SRS-SC-005 | Inner payment transactions (`release`, `refund`) SHALL use `Global.min_txn_fee`. Insufficient fee SHALL cause transaction failure on-chain. |
| SRS-SC-006 | Transaction submission SHALL use algosdk transaction ID deduplication. Duplicate `tx_id` detection SHALL prevent double-spend. |

---

## 7. Security Requirements

### 7.1 Authentication & Authorisation

| ID | Requirement | Priority |
|----|-------------|----------|
| SRS-SEC-001 | All JWT access tokens SHALL be signed with RS256 asymmetric algorithm. HS256 is prohibited. | MUST |
| SRS-SEC-002 | JWT access tokens SHALL expire in exactly 15 minutes. The `exp` claim SHALL be validated on every request. | MUST |
| SRS-SEC-003 | Refresh tokens SHALL be delivered exclusively via `httpOnly`, `Secure`, `SameSite=Strict` cookies. | MUST |
| SRS-SEC-004 | API keys SHALL be stored as HMAC-SHA256 hashes in the database. Plaintext API keys SHALL never be persisted or logged. | MUST |
| SRS-SEC-005 | Every protected route SHALL call `require_role()` before executing business logic. | MUST |
| SRS-SEC-006 | CORS SHALL be locked to the `CORS_ALLOWED_ORIGINS` environment variable. Wildcard (`*`) origins are prohibited in production. | MUST |

### 7.2 Input Validation & LLM Security

| ID | Requirement | Priority |
|----|-------------|----------|
| SRS-SEC-010 | All RFQ raw text and capability profile text inputs SHALL be scanned for prompt injection patterns before LLM submission. Detected patterns SHALL raise HTTP 422. | MUST |
| SRS-SEC-011 | LLM inputs SHALL be hard-truncated at 8,000 characters. | MUST |
| SRS-SEC-012 | LLM agent outputs SHALL be validated against a strict JSON schema: `action ∈ {OFFER, ACCEPT, REJECT, COUNTER}`, `price` must be numeric. Non-conforming outputs SHALL raise `ValidationError` and the negotiation turn SHALL not advance. | MUST |
| SRS-SEC-013 | Pydantic v2 models SHALL enforce: string length limits, numeric range constraints, UUID format validation on all API input DTOs. | MUST |

### 7.3 Blockchain Security

| ID | Requirement | Priority |
|----|-------------|----------|
| SRS-SEC-020 | The Algorand escrow creator mnemonic (25-word key) SHALL be stored exclusively as an environment variable. It SHALL never appear in VCS, logs, or error messages. | MUST |
| SRS-SEC-021 | All contract calls SHALL undergo dry-run simulation before broadcast. No contract call SHALL be broadcast without a successful dry-run. | MUST |
| SRS-SEC-022 | `X402_SIMULATION_MODE` SHALL be `false` in production. The system SHALL reject `SIM-` prefix payment tokens in all code paths. | MUST |
| SRS-SEC-023 | Outbound settlement webhook events SHALL be signed with HMAC-SHA256. Receivers can verify authenticity via `X-Cadencia-Signature` header. | MUST |

### 7.4 Data Security

| ID | Requirement | Priority |
|----|-------------|----------|
| SRS-SEC-030 | All secrets SHALL reside in environment variables. Zero secrets SHALL be present in VCS. | MUST |
| SRS-SEC-031 | Structured JSON logs (structlog) SHALL include a `request_id` on every log line. Sensitive fields (passwords, mnemonics, API keys) SHALL be masked before logging. | MUST |
| SRS-SEC-032 | The production database SHALL enforce TLS in transit. `DATABASE_URL` SHALL use `ssl=require`. | MUST |
| SRS-SEC-033 | The Caddyfile SHALL configure: TLS (Let's Encrypt), HSTS (`max-age=63072000`), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`. | MUST |
| SRS-SEC-034 | Data residency SHALL be enforced in AWS `ap-south-1` (Mumbai). No Cadencia production data SHALL be stored outside `ap-south-1`. | MUST |

---

## 8. Non-Functional Requirements

### 8.1 Performance

| ID | Requirement | Metric | Target |
|----|-------------|--------|--------|
| SRS-PF-001 | API response latency | p95 (non-blockchain endpoints) | < 500ms |
| SRS-PF-002 | Agent negotiation turn latency | p95 (LLM + policy + DB write) | < 3,000ms |
| SRS-PF-003 | pgvector matching latency | p95 (Top-5 across 10K profiles) | < 2,000ms |
| SRS-PF-004 | Algorand finality detection | Block event detection lag | < 5,000ms |
| SRS-PF-005 | Concurrent sessions (prototype) | Simultaneous active sessions | 100 |
| SRS-PF-006 | Concurrent sessions (Phase 2) | Simultaneous active sessions | 1,000 |
| SRS-PF-007 | LLM throughput cap | Simultaneous LLM API requests | 50 req/min |

### 8.2 Reliability

| ID | Requirement | Target |
|----|-------------|--------|
| SRS-RL-001 | Escrow deployment success rate | ≥ 99.5% on testnet; ≥ 99.9% on mainnet |
| SRS-RL-002 | Audit trail hash-chain integrity | 100% — no hash breaks tolerated |
| SRS-RL-003 | Data retention compliance | 7 years minimum — no row deletion from `audit_log` or `compliance_records` |
| SRS-RL-004 | Transaction idempotency | Algorand submissions safe to retry — zero double-spend incidents |
| SRS-RL-005 | Unit of Work atomicity | 100% — partial commits not permitted within a single request |

### 8.3 Scalability

| ID | Requirement | Target |
|----|-------------|--------|
| SRS-SC-001 | Horizontal scaling | Stateless FastAPI workers — minimum 4 Gunicorn workers in production (expandable) |
| SRS-SC-002 | Database connection pooling | `pool_size=20`, `max_overflow=10` (configurable via env vars) |
| SRS-SC-003 | Redis session caching | All negotiation session state cached in Redis to reduce DB reads under load |
| SRS-SC-004 | pgvector index scalability | IVFFlat `lists=100` initially; re-tune at 100K profiles |

### 8.4 Maintainability

| ID | Requirement |
|----|-------------|
| SRS-MT-001 | Mypy strict mode SHALL pass with zero type errors on every CI build. |
| SRS-MT-002 | Ruff linting (E, F, I, TID252 rules) SHALL pass with zero violations on every CI build. |
| SRS-MT-003 | Domain unit tests (pure Python, zero I/O) SHALL achieve ≥ 90% line coverage on all `domain/` directories. |
| SRS-MT-004 | All new `IAgentDriver`, `IBlockchainGateway`, and `IEscrowRepository` implementations SHALL be verified substitutable via Mypy Protocol conformance check. |
| SRS-MT-005 | Alembic migrations SHALL be idempotent; `scripts/migrate.py` SHALL be safe to run on container start in all environments. |
| SRS-MT-006 | All environment-specific configuration SHALL reside in environment variables. Zero hardcoded configuration SHALL exist in application code. |

---

## 9. Testing Requirements

### 9.1 Test Pyramid

```
         ▲  E2E Tests (Algorand localnet)
        ▲▲▲  Integration Tests (Docker: DB + Redis)
      ▲▲▲▲▲▲▲  Unit Tests (Pure Python, zero I/O)
```

### 9.2 Test Layers

| Layer | Framework | Scope | I/O | Coverage Target |
|-------|-----------|-------|-----|----------------|
| Domain unit tests | `pytest` | Entity state machines, policy guards, value objects, domain events | None — pure Python | ≥ 90% on `domain/` |
| Application unit tests | `pytest` + mock adapters | Service use cases, command/query handlers | None — ports mocked via Protocol | ≥ 80% on `application/` |
| Infrastructure integration | `pytest` + `testcontainers` | Repository queries, Redis cache, DB migrations, pgvector index | Docker (PostgreSQL + Redis) | All critical query paths |
| E2E trade loop | `pytest` + Algorand localnet | Full RFQ → match → negotiate → escrow → release → compliance | Localnet + pgvector + Redis | Full happy path + 3 failure scenarios |

### 9.3 Critical Test Cases

| ID | Test | Description | Pass Condition |
|----|------|-------------|----------------|
| TC-001 | `test_budget_guard_rejects_over_ceiling` | Offer with price > `budget_ceiling` | `PolicyViolation` raised; session does not advance |
| TC-002 | `test_stall_detection_triggers_human_review` | Session with `round_count ≥ stall_threshold` | Session transitions to `HUMAN_REVIEW` |
| TC-003 | `test_convergence_detection_agrees_session` | Price gap ≤ 2% | `AGREED`; `SessionAgreed` event emitted |
| TC-004 | `test_dry_run_failure_prevents_broadcast` | Dry-run rejection | `BlockchainSimulationError` raised; algosdk broadcast not called |
| TC-005 | `test_escrow_fund_partial_amount_rejected` | `payment.amount ≠ escrow.amount` | Transaction group fails |
| TC-006 | `test_frozen_escrow_rejects_release` | `release()` on frozen escrow | `ContractAssertionError`; status unchanged |
| TC-007 | `test_audit_log_hash_chain_integrity` | SHA-256 chain verification | `SHA-256(prev_hash + event_data) == entry_hash` for all entries |
| TC-008 | `test_prompt_injection_rejected_before_llm` | Injection pattern in RFQ text | `ValidationError` raised; LLM adapter not called |
| TC-009 | `test_agent_output_non_json_raises_error` | Agent returns non-JSON string | `ValidationError` raised; turn not persisted |
| TC-010 | `test_complete_trade_loop_e2e` | Full end-to-end trade | All assertions pass on localnet — see scaffold below |

**E2E Test Scaffold:**

```python
# tests/e2e/test_full_trade_loop.py
async def test_complete_trade_loop(localnet_client, seeded_db):
    rfq = await upload_rfq(buyer_token, sample_rfq_text)
    assert rfq["status"] == "MATCHED"

    session = await confirm_match(buyer_token, rfq["matches"][0]["match_id"])
    events = await collect_sse_events(session["session_id"], timeout=30)
    assert any(e["event"] == "agreed" for e in events)

    escrow = await get_escrow(buyer_token, session["session_id"])
    assert escrow["status"] == "DEPLOYED"

    await fund_escrow(buyer_token, escrow["escrow_id"])
    await release_escrow(admin_token, escrow["escrow_id"])

    compliance = await get_compliance_record(buyer_token, session["session_id"])
    assert compliance["record_type"] in ("FEMA", "GST")
```

**Domain Unit Test Example:**

```python
# tests/unit/negotiation/test_policy.py
def test_budget_guard_rejects_over_ceiling():
    profile = AgentProfile(risk_profile={"budget_ceiling": 50000})
    offer = Offer(price=55000, proposer_role="BUYER")
    with pytest.raises(PolicyViolation):
        NegotiationPolicy.check_budget_guard(offer, profile)
```

---

## 10. Deployment & Infrastructure Requirements

### 10.1 Runtime Environment

| Component | Specification |
|-----------|--------------|
| Python | 3.12+ (async-native; Pydantic v2) |
| FastAPI | 0.115+ with Uvicorn ASGI server |
| Gunicorn | 4 workers (`--worker-class uvicorn.workers.UvicornWorker`) |
| PostgreSQL | 16+ with pgvector extension 0.7+ |
| Redis | 7.0+ |
| Algorand SDK | algosdk 2.x + algokit-utils 3.x |
| AWS Region | `ap-south-1` (Mumbai) — mandatory for data residency |
| Reverse Proxy | Caddy 2.x (TLS, HSTS, security headers) |

### 10.2 Docker Compose Configurations

| Config | Purpose | Key Services |
|--------|---------|-------------|
| `docker-compose.yml` | Local development | PostgreSQL 16 + pgvector, Redis 7, Algorand localnet, FastAPI hot reload |
| `docker-compose.prod.yml` | Production | Gunicorn (4 workers), Caddy HTTPS, health checks, no localnet |

### 10.3 CI/CD Requirements

- Ruff linting (E, F, I, TID252) — every pull request
- Mypy strict — every pull request
- Domain unit tests (`pytest`, zero I/O) — every pull request
- Puya contract compilation (`algokit compile py`) — every `contracts/` change; `artifacts/` committed to VCS
- Integration tests (`pytest` + `testcontainers`) — every merge to main
- Alembic migration dry-run — every `alembic/versions/` change
- Docker image build + tag with git SHA — every merge to main

### 10.4 Health Check Specification

`GET /health` SHALL return HTTP 200 when all dependencies are healthy:

```json
{
  "status": "healthy",
  "db": "connected",
  "redis": "connected",
  "algorand": "connected",
  "version": "3.0.0"
}
```

Any unhealthy dependency SHALL return HTTP 503 with the failing component identified in the response body.

### 10.5 Prometheus Metrics

`GET /metrics` SHALL expose the following counters and gauges (internal access only):

| Metric | Type | Description |
|--------|------|-------------|
| `cadencia_active_sessions` | Gauge | Number of currently ACTIVE negotiation sessions |
| `cadencia_escrow_state_total` | Counter (by state) | Escrow state transition events |
| `cadencia_llm_latency_seconds` | Histogram | LLM call latency per provider |
| `cadencia_api_request_duration_seconds` | Histogram | API endpoint latency by route |
| `cadencia_rate_limit_hits_total` | Counter | Rate limit rejection events |

---

## 11. Bounded Context & Interface Reference

### 11.1 Context Map

| Context | Responsibility | Key Aggregates | Key Ports |
|---------|---------------|----------------|-----------|
| `identity` | Auth, KYC, Enterprise management | Enterprise, User | `IEnterpriseRepository`, `IUserRepository` |
| `marketplace` | RFQ lifecycle, Matching | RFQ, Match, CapabilityProfile | `IRFQRepository`, `IMatchmakingEngine` |
| `negotiation` | Agent sessions, Offers, Playbooks | NegotiationSession, Offer, AgentProfile | `ISessionRepository`, `INeutralEngine`, `IAgentDriver` |
| `settlement` | Escrow, Blockchain | Escrow, Settlement | `IEscrowRepository`, `IBlockchainGateway`, `IMerkleService` |
| `compliance` | Audit log, FEMA/GST | AuditLog, FEMARecord, GSTRecord | `IAuditRepository`, `IComplianceExporter` |
| `treasury` | Liquidity, FX | LiquidityPool, FXPosition | `ILiquidityRepository`, `IFXProvider` |

### 11.2 Port Interface Catalogue

| Interface | Context | Concrete Adapter | Method Signatures |
|-----------|---------|-----------------|-------------------|
| `IEnterpriseRepository` | identity | `PostgresEnterpriseRepository` | `get(id)`, `save(enterprise)`, `find_by_pan(pan)`, `find_by_gstin(gstin)` |
| `IUserRepository` | identity | `PostgresUserRepository` | `get(id)`, `get_by_email(email)`, `save(user)` |
| `IRFQRepository` | marketplace | `PostgresRFQRepository` | `get(id)`, `save(rfq)`, `list_for_enterprise(eid)` |
| `IMatchmakingEngine` | marketplace | `pgvector_matchmaker` | `find_top_n_matches(rfq_embedding, n) → List[Match]` |
| `IDocumentParser` | marketplace | `LLMDocumentParser` | `parse(raw_text) → ParsedRFQFields` |
| `ISessionRepository` | negotiation | `PostgresSessionRepository` | `get(id)`, `save(session)`, `list_active()` |
| `INeutralEngine` | negotiation | `NeutralEngine` | `run_round(session, buyer_agent, seller_agent) → RoundResult` |
| `IAgentDriver` | negotiation | `LLMAgentDriver` | `generate_offer(role, session_ctx, profile) → AgentAction` |
| `IEscrowRepository` | settlement | `PostgresEscrowRepository` | `get(id)`, `get_by_session(session_id)`, `save(escrow)` |
| `IBlockchainGateway` | settlement | `AlgorandGateway` | `deploy_escrow(...)`, `fund_escrow(...)`, `release_escrow(...)`, `refund_escrow(...)`, `freeze_escrow(...)`, `unfreeze_escrow(...)` |
| `IMerkleService` | settlement | `MerkleService` | `compute_root(entries) → MerkleRoot`, `generate_proof(entry, entries) → MerkleProof` |
| `IPaymentProvider` | settlement | `OnRampAdapter` | `convert_inr_to_usdc(amount)`, `convert_usdc_to_inr(amount)` |
| `IAuditRepository` | compliance | `PostgresAuditRepository` | `append(event)`, `get_log(enterprise_id)`, `get_chain(session_id)` |
| `IComplianceExporter` | compliance | `FEMAGSTExporter` | `export_fema(session_id) → bytes`, `export_gst(session_id) → bytes` |
| `IFXProvider` | treasury | `FrankfurterFXAdapter` | `get_rate(base, target) → FXRate` |

### 11.3 Domain Event Reference

| Event | Publisher | Subscriber | Payload | Effect |
|-------|-----------|------------|---------|--------|
| `RFQConfirmed` | marketplace | negotiation | `rfq_id, match_id, buyer_id, seller_id` | `CreateSession` command dispatched |
| `SessionAgreed` | negotiation | settlement | `session_id, agreed_price, buyer_addr, seller_addr` | `DeployEscrow` command dispatched |
| `EscrowDeployed` | settlement | compliance | `escrow_id, session_id, algo_app_id` | `AppendAuditEvent(ESCROW_DEPLOYED)` |
| `EscrowFunded` | settlement | compliance | `escrow_id, session_id, fund_tx_id` | `AppendAuditEvent(ESCROW_FUNDED)` |
| `EscrowReleased` | settlement | compliance | `escrow_id, session_id, release_tx_id, merkle_root` | `GenerateComplianceRecord` (FEMA + GST) |
| `EscrowRefunded` | settlement | compliance | `escrow_id, session_id, refund_tx_id, reason` | `AppendAuditEvent(ESCROW_REFUNDED)` |
| `HumanOverride` | negotiation | negotiation | `session_id, offer_id, original_price, override_price` | Update `AgentProfile` `strategy_weights` |

### 11.4 Ruff Import Boundary Configuration

```toml
# pyproject.toml
[tool.ruff.lint]
select = ["E", "F", "I", "TID252"]

[tool.ruff.lint.flake8-tidy-imports.banned-module-imports]
"src.settlement" = { message = "Use domain events or shared ports — no direct settlement imports from other domains" }
"src.negotiation" = { message = "Use domain events — no direct negotiation imports from other domains" }
```

---

*Cadencia SRS v1.0 · April 2026 · IEEE 830-Compatible*
