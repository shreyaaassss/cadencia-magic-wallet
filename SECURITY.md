# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Cadencia, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, email: **security@cadencia.app**

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We will acknowledge receipt within 48 hours and provide a timeline for resolution.

## Supported Versions

| Version | Supported |
|---------|-----------|
| main branch | Yes |
| Tagged releases | Yes |

## Security Measures

- RS256 JWT authentication (HS256 prohibited)
- CORS locked to explicit origins in production
- OWASP security headers on all responses
- Request body size limit (1 MB)
- SQL injection prevention via SQLAlchemy ORM
- X402 simulation mode blocked in production
- Algorand escrow smart contracts are immutable once deployed
- Hash-chained audit log for compliance (tamper-evident)

## Dependency Updates

Dependencies are monitored via GitHub Dependabot. Critical security patches are applied within 48 hours.
