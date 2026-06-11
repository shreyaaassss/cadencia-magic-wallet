# Cadencia — Product Requirements Document
**PRD · Version 1.0 · April 2026**

| Field | Value |
|-------|-------|
| Product | Cadencia |
| Version | 3.0 (Production Architecture) |
| Date | April 2026 |
| Status | Active Development |
| Audience | Product, Engineering, Stakeholders |

---

## Table of Contents

1. [Executive Overview](#1-executive-overview)
2. [Target Users & Personas](#2-target-users--personas)
3. [Product Goals & Success Metrics](#3-product-goals--success-metrics)
4. [Feature Requirements](#4-feature-requirements)
5. [User Stories](#5-user-stories)
6. [Domain Event Flow](#6-domain-event-flow)
7. [Non-Functional Requirements](#7-non-functional-requirements)
8. [Constraints & Assumptions](#8-constraints--assumptions)
9. [Product Roadmap](#9-product-roadmap)
10. [Appendix](#10-appendix)

---

## 1. Executive Overview

### 1.1 Product Vision

Cadencia is a closed-loop, AI-native agentic B2B trade marketplace purpose-built for Indian Micro, Small & Medium Enterprises (MSMEs). The platform transforms the friction-laden B2B procurement cycle — traditionally involving phone calls, WhatsApp negotiations, manual compliance filing, and slow bank settlements — into a single-upload autonomous workflow.

An enterprise uploads one Request for Quotation (RFQ) document. Cadencia then autonomously handles seller discovery, AI-driven negotiation, blockchain-secured escrow, settlement, and regulatory compliance export — end to end, with minimal human intervention.

### 1.2 Problem Statement

- Indian MSMEs spend 30–40% of procurement bandwidth on manual vendor discovery and email/phone negotiation cycles.
- Cross-border and domestic settlement latency (3–7 banking days) locks working capital.
- FEMA and GST compliance documentation is manual, error-prone, and audit-intensive.
- No existing marketplace offers discovery + negotiation + blockchain settlement + compliance in a single product.

### 1.3 Solution Summary

Cadencia is a seven-layer production backend integrating FastAPI, LLM-powered negotiation agents, Algorand blockchain escrow (Puya smart contracts), PostgreSQL with pgvector similarity search, and automated FEMA/GST compliance generation — packaged as a unified API-first platform.

### 1.4 Non-Negotiable Architectural Principles

| Principle | Rule | Enforcement |
|-----------|------|-------------|
| **Puya-First Contracts** | All Algorand smart contracts authored in Algorand Python (Puya), compiled offline to `.teal` + `.arc56.json` | CI compile step; no runtime compilation in production |
| **Hexagonal Architecture** | Domain layer (pure Python) never imports FastAPI, SQLAlchemy, or algosdk | Ruff import boundary linting (TID252) |
| **DDD Bounded Contexts** | Code organized by business domain, not file type; cross-domain calls via domain events only | Ruff banned-module-imports; Mypy strict |

---

## 2. Target Users & Personas

### Persona A — MSME Buyer (Procurement Manager)

| Field | Detail |
|-------|--------|
| Role | Procurement / Purchase Manager at an Indian MSME |
| Goal | Source materials quickly with guaranteed price and delivery |
| Pain | Spends days on WhatsApp/calls finding vendors; no structured negotiation; manual GST reconciliation |
| Value | Upload one RFQ; receive ranked matches; confirm; let agents negotiate; download compliance docs |

### Persona B — MSME Seller (Sales / BD Manager)

| Field | Detail |
|-------|--------|
| Role | Sales or Business Development Manager at an MSME supplier |
| Goal | Receive pre-qualified, intent-confirmed leads; negotiate efficiently; receive payment securely |
| Pain | Chases unverified inquiries; no structured deal flow; manual invoice + FEMA filing |
| Value | Respond to matched RFQs; agent negotiates on behalf; escrow guarantees payment on delivery |

### Persona C — Compliance Officer / Auditor

| Field | Detail |
|-------|--------|
| Role | Internal or external compliance professional |
| Goal | Produce FEMA Form A2, GST export records for every cross-border or domestic trade |
| Pain | Manual record assembly; reconciling bank references with accounting entries |
| Value | Every settled trade auto-generates downloadable PDF/CSV compliance record with 7-year retention |

### Persona D — Treasury Manager

| Field | Detail |
|-------|--------|
| Role | CFO / Treasury function at a larger MSME or trade finance provider |
| Goal | Monitor INR/USDC pool balances, FX exposure, and 30-day liquidity runway |
| Pain | No real-time view of stablecoin positions and cross-currency exposure |
| Value | Live treasury dashboard via `/v1/treasury` endpoints |

---

## 3. Product Goals & Success Metrics

### 3.1 Strategic Goals

- Reduce average B2B procurement cycle time from days to under 30 minutes for matched trades.
- Provide Indian MSMEs with a single platform for discovery, negotiation, settlement, and compliance.
- Achieve blockchain-verifiable, audit-ready trade records satisfying RBI FEMA and GST Authority requirements.
- Build an extensible agent architecture capable of supporting new LLM providers and blockchains without domain changes.

### 3.2 Key Performance Indicators

| KPI | Target | Measurement |
|-----|--------|-------------|
| Time-to-Match after RFQ upload | < 2 seconds (10K seller profiles) | pgvector p95 latency |
| Autonomous negotiation success rate | > 80% sessions reach AGREED without human override | Session status analytics |
| Escrow deployment success rate | > 99.5% on Algorand testnet / mainnet | AlgorandGateway success logs |
| Compliance record generation | 100% of released escrows generate FEMA + GST record | ComplianceService audit |
| API response time (non-blockchain) | < 500ms p95 | Prometheus `/metrics` |
| Concurrent negotiation sessions | 100 prototype / 1,000 Phase 2 | Load test results |
| Audit trail integrity | 100% Merkle-provable — zero hash breaks | AuditService verification |
| Data retention compliance | 7-year minimum | Compliance audit |

### 3.3 Phase Exit Criteria

| Phase | Week | Exit Criteria |
|-------|------|---------------|
| Phase 0 — Foundation | 1 | `docker compose up` boots; `/health` returns 200; Puya contract compiled to `artifacts/` |
| Phase 1 — Identity & Auth | 1–2 | JWT auth flow complete; rate limiting active; unit tests passing |
| Phase 2 — Algorand Escrow | 2–3 | Full escrow lifecycle on localnet; deploy → fund → release → refund verified |
| Phase 3 — Audit & x402 | 3 | Hash-chained audit log verifiable; Merkle proof endpoint working |
| Phase 4 — Negotiation | 3–4 | Autonomous negotiation completes; SSE stream emits all events; human override persisted |
| Phase 5 — Marketplace | 4–5 | RFQ → NLP parse → pgvector match → confirm → negotiation handoff working end-to-end |
| Phase 6 — Compliance | 5 | Every test trade generates downloadable FEMA + GST records |
| Phase 7 — Production Hardening | 6 | `docker compose -f docker-compose.prod.yml up` fully operational; all endpoints < 500ms p95 |

---

## 4. Feature Requirements

### F1 — Enterprise Registration & KYC

- Self-service enterprise registration with PAN, GSTIN, legal name, trade role (BUYER / SELLER / BOTH), commodity list, and order value range.
- KYC state machine: `PENDING → KYC_SUBMITTED → VERIFIED → ACTIVE`.
- Admin user creation with role assignment (ADMIN, TREASURY_MANAGER, COMPLIANCE_OFFICER, AUDITOR).
- Algorand wallet address linkage to enterprise profile.
- API key creation and revocation for M2M (machine-to-machine) access.

### F2 — JWT Authentication & Security

- RS256-signed JWT access tokens with 15-minute expiry.
- 30-day refresh tokens stored as httpOnly cookies.
- Redis-backed rate limiting: 100 requests / 60 seconds per enterprise.
- HMAC-SHA256 hashed API keys stored in database (never plaintext).
- Role-based access control enforced on every protected route via `require_role()` dependency.

### F3 — RFQ Upload & NLP Parsing

- Free-text RFQ upload — no structured form required.
- LLM NLP extraction of: product name, HSN code, quantity, unit, budget range (min/max), delivery window, geography.
- Parsed fields returned in structured JSON within the RFQ response.
- Prompt injection sanitization on all LLM inputs (hard truncation at 8,000 characters).
- RFQ state machine: `DRAFT → PARSED → MATCHED → CONFIRMED → SETTLED`.

### F4 — pgvector Seller Matching Engine

- Seller capability profiles stored as pgvector embeddings (1536-dimensional).
- IVFFlat cosine similarity search returning Top-N ranked matches in under 2 seconds across 10,000 profiles.
- Match score, seller name, and rank returned in RFQ response.
- Embedding recomputation endpoint for capability profile updates.
- Buyer confirms preferred match to initiate negotiation handoff.

### F5 — AI Agent Negotiation Engine

- Fully autonomous buyer and seller LLM agents personalized via AgentProfile (risk appetite, budget ceiling, margin floor, automation level, industry playbook).
- NeutralEngine manages round sequencing, convergence detection (price gap ≤ 2%), and stall detection (configurable round threshold).
- Agent outputs strictly validated: action must be `OFFER | ACCEPT | REJECT | COUNTER`; price must be numeric.
- Server-Sent Events (SSE) stream at `/v1/sessions/{id}/stream` for real-time turn-by-turn visibility.
- Human override: buyer or seller can inject manual offer mid-session; correction logged as audit event and used to update AgentProfile weights.
- Session states: `ACTIVE → AGREED | FAILED | EXPIRED | HUMAN_REVIEW`.
- On AGREED, `SessionAgreed` domain event triggers automatic escrow deployment.

### F6 — Algorand Escrow (Puya Smart Contracts)

- ARC-4 compliant `CadenciaEscrow` contract written in Algorand Python (Puya), compiled offline.
- Escrow state machine: `DEPLOYED(0) → FUNDED(1) → RELEASED(2) | REFUNDED(3)`, with FROZEN flag.
- Dry-run simulation required before every contract call; `BlockchainSimulationError` raised on failure without touching chain.
- Merkle root (SHA-256 hash chain of audit events) anchored on-chain in transaction Note field at release.
- Freeze/unfreeze capability for dispute resolution.
- Idempotent transaction submission — safe to retry without double-spend.

### F7 — Compliance Automation (FEMA + GST)

- Auto-generated FEMA record on `EscrowReleased` event: transaction date, amount, purpose code, counterparty country, RBI reference.
- Auto-generated GST record: GSTIN of both parties, HSN code, taxable value, IGST/CGST/SGST breakdown.
- PDF and CSV export endpoints for both record types.
- Bulk compliance export by date range.
- 7-year data retention enforced via PostgreSQL policy and archival job.
- Hash-chained audit log: every entry hashes the previous entry's hash (append-only, tamper-evident).
- Merkle proof endpoint for session audit trail verification.

### F8 — Treasury Dashboard

- Real-time INR and USDC stablecoin pool balances.
- Open FX position summary and 30-day liquidity runway forecast.
- Live Frankfurter FX feed integration for INR ↔ USDC rate.

---

## 5. User Stories

| ID | As a… | I want to… | So that… | Acceptance Criteria |
|----|-------|------------|----------|---------------------|
| US-01 | MSME Buyer | Upload a free-text RFQ | I receive ranked seller matches without filling forms | NLP parses product, HSN, budget, window in < 3s; matches returned with scores |
| US-02 | MSME Buyer | Confirm a seller match | AI agents begin negotiating on my behalf | Session created; SSE stream begins; first offer emitted within 5s |
| US-03 | MSME Buyer | Watch negotiation in real time | I can intervene if agents deviate from my strategy | SSE stream emits each round event; human override API available |
| US-04 | MSME Buyer | Override an agent offer mid-session | My preferred price replaces the agent offer | Override logged as HumanOverride event; agent continues from new price |
| US-05 | MSME Seller | Receive matched RFQ leads | I only respond to pre-qualified, intent-confirmed buyers | Seller capability profile matched via pgvector cosine similarity |
| US-06 | MSME Seller | Have escrow guarantee payment | I release goods only after funds are locked on-chain | Escrow DEPLOYED and FUNDED before negotiation AGREED confirmation |
| US-07 | Compliance Officer | Download FEMA record per trade | I satisfy RBI reporting requirements | FEMA PDF/CSV available at `/v1/compliance/fema/{session_id}` |
| US-08 | Compliance Officer | Verify audit trail integrity | I can prove no records were tampered | Merkle proof endpoint returns verifiable proof for any session |
| US-09 | Treasury Manager | View stablecoin pool balances | I manage FX exposure in real time | `/v1/treasury/dashboard` returns INR + USDC balances and FX rate |
| US-10 | Admin | Freeze escrow during a dispute | Neither party can release or refund until resolved | Escrow status becomes FROZEN; release and refund calls rejected |

---

## 6. Domain Event Flow

### 6.1 Event Bus Architecture

Cross-domain communication occurs exclusively via an in-process domain event bus (`publisher.py` → `handlers.py`). Direct imports between bounded contexts are prohibited by Ruff linting rules.

### 6.2 Event Catalogue

| Event | Publisher | Subscriber | Effect |
|-------|-----------|------------|--------|
| `RFQConfirmed` | marketplace | negotiation | Spin up NegotiationSession between buyer and seller |
| `SessionAgreed` | negotiation | settlement | Deploy CadenciaEscrow smart contract on Algorand |
| `EscrowFunded` | settlement | compliance | Append audit event to hash-chained AuditLog |
| `EscrowReleased` | settlement | compliance | Generate FEMA record + GST record; anchor Merkle root on-chain |
| `EscrowRefunded` | settlement | compliance | Append refund audit event; update escrow status to REFUNDED |
| `HumanOverride` | negotiation | negotiation | Log correction event; update AgentProfile strategy weights |

### 6.3 End-to-End Trade Flow

1. Buyer uploads RFQ free text → LLM NLP extraction → pgvector matching → Top-N sellers returned
2. Buyer confirms preferred match → `RFQConfirmed` event → `NegotiationSession` created
3. Buyer and Seller LLM agents exchange offers → convergence detected → `SessionAgreed` event
4. `SettlementService` receives `SessionAgreed` → deploys `CadenciaEscrow` on Algorand (dry-run first)
5. Buyer funds escrow (atomic PaymentTxn + AppCall) → `EscrowFunded` event → audit record
6. Delivery confirmed → Admin releases escrow → `EscrowReleased` event → FEMA + GST records generated
7. Compliance officer downloads FEMA PDF and GST CSV; Merkle proof verifiable on-chain

---

## 7. Non-Functional Requirements

### 7.1 Performance

| Requirement | Target | Scope |
|-------------|--------|-------|
| API response time | < 500ms p95 | All non-blockchain endpoints |
| Agent negotiation turn latency | < 3s p95 | LLM call + policy check + DB write |
| pgvector matching latency | < 2s p95 | Top-5 match across 10,000 profiles |
| Algorand block event detection | < 5 seconds | Finality monitoring |
| Concurrent negotiation sessions | 100 (prototype) / 1,000 (Phase 2) | Simultaneous active sessions |
| LLM throughput cap | 50 req/min | Redis-backed rate limiting |

### 7.2 Security

- JWT RS256 access tokens, 15-minute expiry; refresh tokens in httpOnly cookies.
- All API keys stored as HMAC-SHA256 hashes — never plaintext.
- Prompt injection detection on every LLM input (regex pattern matching + hard 8,000-character truncation).
- Agent output schema validation: `action` and `price` fields strictly typed; invalid JSON rejected.
- Dry-run simulation mandatory before every Algorand transaction submission.
- HMAC-signed outbound webhooks for settlement events.
- CORS locked to configured origins (`CORS_ALLOWED_ORIGINS` env var).
- Zero secrets in VCS; all credentials in environment variables.

### 7.3 Reliability & Data Integrity

- Idempotent Algorand transaction submission — safe to retry without double-spend risk.
- Append-only, hash-chained audit log — each entry hashes the previous entry.
- Merkle root of all session audit events anchored on-chain at escrow release.
- Unit of Work pattern ensures all DB writes within a request succeed or fail atomically.
- 7-year audit log retention enforced via PostgreSQL row-level policy and archival job.

### 7.4 Maintainability & Extensibility

- New LLM provider: implement `IAgentDriver` interface → zero domain changes.
- New blockchain: implement `IBlockchainGateway` interface → zero domain changes.
- Mypy strict mode enforced; Protocol-based ports verified for substitutability.
- Ruff import boundary enforcement prevents accidental cross-domain coupling.
- All domain logic covered by pure-Python unit tests (no I/O dependencies).

### 7.5 Compliance

- FEMA Form A2 fields captured for every cross-border settlement.
- GST IGST/CGST/SGST breakdown per trade with HSN code.
- Data residency: `ap-south-1` (AWS Mumbai) for all production data.
- Structured JSON logging via structlog with request IDs on all log lines.
- Prometheus metrics endpoint at `/metrics`: active sessions, escrow states, LLM latency.

---

## 8. Constraints & Assumptions

### 8.1 Technical Constraints

- All Algorand smart contracts must be authored in Algorand Python (Puya) — PyTeal is explicitly prohibited.
- Smart contracts are compiled offline (`algokit compile py`) and artifacts checked into VCS — never compiled at runtime.
- `X402_SIMULATION_MODE` must never be `true` in production; `SIM-` prefix tokens are rejected in all code paths.
- PostgreSQL 16 with pgvector extension is the only supported database for vector similarity search.
- Redis 7 is required for session caching, rate limiting, and event state.

### 8.2 Business Assumptions

- Initial deployment targets the Indian MSME market; FEMA and GST compliance is mandatory for all cross-border and domestic trade records.
- Prototype phase supports up to 100 concurrent negotiation sessions; Phase 2 scales to 1,000.
- Buyer and Seller Algorand wallets are pre-registered; on/off-ramp for INR ↔ USDC conversion is handled by an external provider.
- KYC provider integration is mocked for prototype; production requires a certified CKYC provider.

### 8.3 Out of Scope (v1.0)

- Mobile application (iOS/Android native clients)
- Multi-currency settlement beyond INR ↔ USDC/ALGO
- Dispute arbitration workflow beyond escrow freeze
- Supplier credit scoring or embedded lending

---

## 9. Product Roadmap

| Phase | Timeline | Deliverable | Key Features |
|-------|----------|-------------|--------------|
| Phase 0 — Foundation | Week 1 | Bootable platform | FastAPI app factory, DB migrations, Puya contract compiled, `/health` endpoint |
| Phase 1 — Identity & Auth | Weeks 1–2 | Auth system live | Enterprise registration, JWT, KYC state machine, API keys, rate limiting |
| Phase 2 — Algorand Escrow | Weeks 2–3 | Escrow lifecycle on localnet | Deploy/Fund/Release/Refund/Freeze; Merkle service; dry-run safety |
| Phase 3 — Audit & x402 | Week 3 | Immutable audit log | Hash-chained AuditLog, Merkle proof endpoint, webhook notifier |
| Phase 4 — Negotiation Engine | Weeks 3–4 | Autonomous negotiation | LLM agents, NeutralEngine, SSE stream, human override, AgentProfile |
| Phase 5 — Marketplace | Weeks 4–5 | Full RFQ-to-trade loop | RFQ upload, NLP parsing, pgvector matching, confirm → session handoff |
| Phase 6 — Compliance Generator | Week 5 | Compliance auto-generation | FEMA + GST records, PDF/CSV export, treasury dashboard |
| Phase 7 — Production Hardening | Week 6 | Production-ready platform | Gunicorn + Caddy, HSTS, Pydantic hardening, Prometheus, Alembic runbook |

---

## 10. Appendix

### 10.1 Bounded Context Summary

| Context | Responsibility | Key Aggregates | Key Ports |
|---------|---------------|----------------|-----------|
| `identity` | Auth, KYC, Enterprise mgmt | Enterprise, User | `IEnterpriseRepository`, `IUserRepository` |
| `marketplace` | RFQ lifecycle, Matching | RFQ, Match, CapabilityProfile | `IRFQRepository`, `IMatchmakingEngine` |
| `negotiation` | Agent sessions, Offers | NegotiationSession, Offer, AgentProfile | `ISessionRepository`, `INeutralEngine`, `IAgentDriver` |
| `settlement` | Escrow, Blockchain | Escrow, Settlement | `IEscrowRepository`, `IBlockchainGateway`, `IMerkleService` |
| `compliance` | Audit log, FEMA/GST | AuditLog, FEMARecord, GSTRecord | `IAuditRepository`, `IComplianceExporter` |
| `treasury` | Liquidity, FX | LiquidityPool, FXPosition | `ILiquidityRepository`, `IFXProvider` |

### 10.2 Environment Configuration Summary

| Variable | Purpose | Example |
|----------|---------|---------|
| `DATABASE_URL` | PostgreSQL async connection string | `postgresql+asyncpg://cadencia:pass@localhost/cadencia` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `JWT_SECRET_KEY` | RS256 signing key (never commit) | `openssl rand -hex 32` |
| `ALGORAND_NETWORK` | Target network | `testnet \| mainnet` |
| `ALGORAND_ESCROW_CREATOR_MNEMONIC` | 25-word Algorand mnemonic | NEVER commit to VCS |
| `LLM_PROVIDER` | LLM backend | `google \| anthropic \| openai` |
| `ESCROW_DRY_RUN_ENABLED` | Dry-run before all chain calls | `true` (always in non-production) |
| `CORS_ALLOWED_ORIGINS` | Allowed CORS origins | `https://cadencia.app` |
| `AUDIT_RETENTION_YEARS` | Minimum audit log retention | `7` |
| `DATA_RESIDENCY_REGION` | AWS data residency region | `ap-south-1` |

### 10.3 Glossary

| Term | Definition |
|------|------------|
| RFQ | Request for Quotation — the primary document a buyer uploads to initiate a trade |
| HSN Code | Harmonised System of Nomenclature code — mandatory for GST classification of goods |
| pgvector | PostgreSQL extension enabling vector similarity search for capability profile matching |
| Puya / PuyaPy | Algorand Foundation's official Python-based smart contract language (replaces PyTeal) |
| ARC-4 | Algorand smart contract ABI standard for typed method calls and typed clients |
| ARC-56 | Extended Algorand smart contract metadata standard for typed client generation |
| FEMA | Foreign Exchange Management Act — Indian regulation governing cross-border payments |
| GSTIN | Goods and Services Tax Identification Number — mandatory for all GST-registered Indian entities |
| SSE | Server-Sent Events — HTTP streaming for real-time agent negotiation turn events |
| Hexagonal | Architecture pattern (Ports and Adapters) isolating domain logic from infrastructure |
| DDD | Domain-Driven Design — organising code by business domain rather than file type |
| UoW | Unit of Work — pattern ensuring atomic DB commits across multiple repository operations |

---

*Cadencia PRD v1.0 · Confidential · April 2026*
