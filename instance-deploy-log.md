# Cadencia Deployment Log

## Active Instance

| Field | Value |
|-------|-------|
| **Instance ID** | `i-0c7f318a0e3d5a6b7` |
| **Instance Name** | `Cadencia-Magic-Wallet` |
| **Instance Type** | `t4g.small` (2GB RAM, ARM/Graviton) |
| **Public IP** | `13.204.194.47` |
| **Region** | `ap-south-1` (Mumbai) |
| **DNS** | `cadencia-magic-wallet.duckdns.org` |
| **TLS** | Let's Encrypt via Nginx (certbot) |

## Git Repository

| Field | Value |
|-------|-------|
| **Remote** | `https://github.com/shreyaaassss/cadencia-magic-wallet.git` |
| **Branch** | `main` |

## Stack (on instance)

| Service | How it runs | Port |
|---------|------------|------|
| **Frontend** | PM2 → Next.js 16 standalone | 3000 |
| **Backend** | PM2 → Uvicorn (FastAPI) | 8000 |
| **Reverse Proxy** | Nginx (systemd) | 80/443 |
| **Database** | Docker → pgvector/pgvector:pg15 | 5432 |
| **Redis** | System service | 6379 |

## Deployment Method

- Build frontend **locally** (the instance has only 2GB RAM, too low for `npm install` + `next build`)
- `tar czf` the `.next/standalone`, `.next/static`, and `public` directories
- `scp` the tarball to the instance
- Extract into `~/cadencia/frontend/`, copy static assets into standalone
- `pm2 restart cadencia-frontend`

## Keys & Secrets

| Key | Where it's set |
|-----|----------------|
| `NEXT_PUBLIC_MAGIC_PUBLISHABLE_KEY` | Baked at build time (build arg) |
| `MAGIC_SECRET_KEY` | Backend `.env` on instance |
| Backend `.env` | `~/cadencia/backend/.env` on instance |

## Other Instances (not in use)

| Instance ID | Name | IP | Status | Notes |
|-------------|------|----|--------|-------|
| `i-0d107e1399d17af09` | Cadencia-New | 13.232.223.160 | running | Docker Compose setup, DNS not pointing here |
| `i-0710c784e9ed08a29` | cadencia-demo | 3.111.135.76 | stopped | Legacy demo |
