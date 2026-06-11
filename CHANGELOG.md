# Changelog

All notable changes to the Cadencia platform are documented here.

## [0.9.0] - 2026-06-11

### Added
- 50-seller seed dataset across 10 Indian MSME industries
- Mandatory test suite: 97 tests across 4 layers (unit, integration, E2E, smoke)
- Negotiation engine E2E simulation (buyer-vs-seller agent)
- Post-deploy smoke tests in deploy workflow
- IST timezone for all date/time formatting
- PO generation moved to post-settlement (EscrowReleased event)
- DB reset and seed GitHub Actions workflow

### Changed
- Landing page: hero typography, feature cards (X402 + Escrow), settlement copy
- Sidebar: sticky scroll fix (h-screen + overflow-y-auto)
- Marketplace: removed Discover page, removed Market Overview section
- SectionHeader: primary button styling for New RFQ
- Seller CTA button: solid fill instead of outline

### Removed
- Discover page (`/marketplace/discover`)
- Market Overview stats section from marketplace

## [0.8.0] - 2026-06-10

### Added
- PO filtering by enterprise, transaction IDs in escrow
- SSE real-time negotiation room fixes
- RFQ submit flow improvements
- Bulk catalogue CSV upload for sellers

## [0.7.0] - 2026-06-05

### Added
- ALGO normalization for escrow amounts
- RFQ schema validation with AI preview
- PO auto-generation on SessionAgreed
- Catalogue bulk import feature

## [0.6.0] - 2026-05-31

### Added
- Magic.link passwordless authentication
- X402 micropayment protocol for negotiation turns
- Algorand escrow smart contract (Puya/ARC-56)
- Multi-round AI negotiation with Groq/Gemini LLM drivers
