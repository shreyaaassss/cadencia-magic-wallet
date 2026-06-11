# Cadencia — Architecture Documentation

## System Architecture

```mermaid
graph TD
    User[Browser / Mobile] --> Caddy[Caddy Reverse Proxy]
    Caddy --> FE[Next.js Frontend :3000]
    Caddy --> BE[FastAPI Backend :8000]
    BE --> PG[(PostgreSQL + pgvector)]
    BE --> Redis[(Redis 7 Cache)]
    BE --> Algo[Algorand Testnet]
    BE --> LLM[LLM Provider<br/>Groq / Gemini / OpenAI]
    BE --> Magic[Magic.link Auth]
    BE --> Prometheus[Prometheus :9090]
    Prometheus --> Grafana[Grafana :3001]
```

## Procurement Workflow

```mermaid
sequenceDiagram
    participant Buyer
    participant Frontend
    participant Backend
    participant Matchmaker
    participant NegotiationAgent
    participant EscrowService
    participant Algorand

    Buyer->>Frontend: Submit RFQ (natural language)
    Frontend->>Backend: POST /v1/marketplace/rfq
    Backend->>Matchmaker: Parse RFQ + embed via pgvector
    Matchmaker-->>Backend: Ranked seller matches
    Backend->>NegotiationAgent: Create session per match
    NegotiationAgent->>NegotiationAgent: Auto-negotiate (LLM rounds)
    NegotiationAgent-->>Backend: SessionAgreed event
    Backend->>Buyer: Show matched deals
    Buyer->>Backend: Select deal
    Backend->>EscrowService: Deploy CadenciaEscrow contract
    EscrowService->>Algorand: Create app transaction
    Algorand-->>EscrowService: App ID + address
    Buyer->>Algorand: Fund escrow (ALGO)
    Note over Buyer,Algorand: Seller dispatches goods
    Buyer->>Algorand: Confirm delivery + release funds
    Backend->>Backend: Generate compliance audit + PO PDF
```

## Negotiation Engine Architecture

```mermaid
graph LR
    RFQ[RFQ Text] --> Parser[NLP Parser<br/>LLM extracts HSN + qty]
    Parser --> Embed[Embedder<br/>text-embedding-004]
    Embed --> VDB[(pgvector)]
    VDB --> Matches[Top-K Sellers]
    Matches --> BuyerAgent[Buyer Agent<br/>IAgentDriver]
    Matches --> SellerAgent[Seller Agent<br/>IAgentDriver]
    BuyerAgent --> Session[NegotiationSession<br/>9-state FSM]
    SellerAgent --> Session
    Session --> Convergence{Price gap<br/>within 2%?}
    Convergence -->|Yes| Agreed[SessionAgreed Event]
    Convergence -->|No| NextRound[Next Round]
    NextRound --> BuyerAgent
```

### Negotiation Engine Layers

| Layer | Component | Purpose |
|-------|-----------|---------|
| 1 | Valuation Engine | Computes reservation price, target price, walkaway delta |
| 2 | Strategy Engine | Selects strategy per round (anchor, boulware, tit-for-tat, ultimatum) |
| 3 | Opponent Model | Bayesian belief updates (cooperative, strategic, stubborn, bluffing) |
| 4 | Guardrail Engine | Validates offers against budget ceiling, margin floor, confidence |

## Escrow Smart Contract Lifecycle

```mermaid
stateDiagram-v2
    [*] --> PENDING_APPROVAL: Buyer selects deal
    PENDING_APPROVAL --> APPROVED: Seller accepts
    APPROVED --> DEPLOYED: Contract created on Algorand
    DEPLOYED --> FUNDED: Buyer funds via Pera Wallet
    FUNDED --> DISPATCHED: Seller ships goods
    DISPATCHED --> RELEASED: Buyer confirms delivery
    FUNDED --> REFUNDED: Dispute resolution
    FUNDED --> FROZEN: Either party freezes
    FROZEN --> FUNDED: Creator unfreezes
    RELEASED --> [*]
    REFUNDED --> [*]
```

## Domain Architecture (Hexagonal / DDD)

Each backend domain follows:

```
<domain>/
├── api/              # FastAPI routers (inbound adapters)
├── application/      # Use case services + commands
├── domain/           # Pure models, value objects, events
└── infrastructure/   # ORM models, repositories, external adapters
```

**Domains:** admin, compliance, health, identity, marketplace, messaging, negotiation, procurement, settlement, shared, treasury, wallet

## Database Schema (Key Tables)

| Table | Purpose |
|-------|---------|
| `enterprises` | Buyer/seller company profiles |
| `users` | Enterprise user accounts (Magic.link auth) |
| `capability_profiles` | Seller embeddings for pgvector matching |
| `catalogue_items` | Seller product catalogue |
| `rfqs` | Buyer request for quotations |
| `matches` | RFQ-to-seller match records |
| `negotiation_sessions` | 9-state FSM negotiation lifecycle |
| `offers` | Individual negotiation round offers |
| `escrow_contracts` | Algorand escrow lifecycle |
| `audit_entries` | Hash-chained compliance audit log |
| `procurement_documents` | Purchase order records |
| `x402_payments` | Micropayment ledger |

## CI/CD Pipeline

```mermaid
graph LR
    Push[git push main] --> CI[CI: Lint + Tests + Docker Build]
    Push --> Deploy[Deploy: Build + SCP + PM2 restart + Health check + Smoke tests]
```

## External Dependencies

| Service | Purpose | Failover |
|---------|---------|----------|
| PostgreSQL + pgvector | Primary database | Docker local |
| Redis 7 | Cache + rate limiting | In-memory dev |
| Algorand testnet | Smart contract settlement | AlgoKit localnet |
| Groq API | LLM inference (primary) | Gemini / OpenAI fallback |
| Gemini text-embedding-004 | Vector embeddings | Required |
| Magic.link | Passwordless auth + wallet | RS256 JWT standalone |
