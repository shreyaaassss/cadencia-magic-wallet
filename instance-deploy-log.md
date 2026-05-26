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

## CI/CD Pipeline

**Workflow:** `.github/workflows/deploy.yml`
**Trigger:** Push to `main` or manual `workflow_dispatch`
**Average deploy time:** ~2.5 minutes

### Pipeline Steps

```
Push to main
  → GitHub Actions runner (ubuntu-latest, 7GB RAM)
  → Install frontend deps (npm ci)
  → Build Next.js standalone (with env vars from GitHub Secrets)
  → Package frontend (.next/standalone + .next/static + public) into tarball
  → Package backend source into tarball
  → SCP both tarballs to EC2 instance
  → Extract frontend → pm2 restart cadencia-frontend
  → Extract backend → pm2 restart cadencia-backend
  → Health check (frontend HTTP 200 + backend /health = healthy)
```

### GitHub Secrets

| Secret | Purpose |
|--------|---------|
| `EC2_HOST` | `13.204.194.47` (Cadencia-Magic-Wallet instance) |
| `EC2_USER` | `ec2-user` |
| `EC2_SSH_KEY` | PEM private key for SSH access |
| `NEXT_PUBLIC_MAGIC_PUBLISHABLE_KEY` | Magic.link publishable key (baked into frontend build) |
| `MAGIC_SECRET_KEY` | Magic.link secret key (set in backend `.env` on instance) |

### Why build in CI (not on instance)?

The instance is a `t4g.small` (2GB RAM) — `npm install` + `next build` requires ~4GB and causes OOM kills.
GitHub Actions runners have 7GB RAM, so the build runs reliably there. Only the pre-built output is uploaded to the instance.

## Deployment Method (manual fallback)

If CI/CD is unavailable, deploy manually:

```bash
# Build locally
cd frontend && npx next build --webpack

# Package
tar czf /tmp/frontend-deploy.tar.gz .next/standalone .next/static public

# Upload
scp -i <pem-key> /tmp/frontend-deploy.tar.gz ec2-user@13.204.194.47:/tmp/

# Deploy
ssh -i <pem-key> ec2-user@13.204.194.47 "
  cd ~/cadencia/frontend && rm -rf .next &&
  tar xzf /tmp/frontend-deploy.tar.gz &&
  cp -r .next/static .next/standalone/.next/static &&
  cp -r public .next/standalone/public &&
  pm2 restart cadencia-frontend
"
```

## Keys & Secrets (on instance)

| Key | Where it's set |
|-----|----------------|
| `NEXT_PUBLIC_MAGIC_PUBLISHABLE_KEY` | Baked at build time via GitHub Secrets |
| `MAGIC_SECRET_KEY` | Backend `~/cadencia/backend/.env` on instance |
| Backend `.env` | `~/cadencia/backend/.env` on instance |

## Other Instances (not in use)

| Instance ID | Name | IP | Status | Notes |
|-------------|------|----|--------|-------|
| `i-0d107e1399d17af09` | Cadencia-New | 13.232.223.160 | **stopped** | Docker Compose setup, not in use |
| `i-0710c784e9ed08a29` | cadencia-demo | 3.111.135.76 | **stopped** | Legacy demo |
