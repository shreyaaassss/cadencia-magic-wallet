#!/bin/bash
set -e

echo "=== Fix 1: Ensure Postgres cadencia user has correct password ==="
docker exec cadencia-db psql -U postgres -c "ALTER USER cadencia WITH PASSWORD 'cadencia_dev';" 2>&1 || \
  docker exec cadencia-db psql -U cadencia -d cadencia -c "SELECT 1;" 2>&1

echo "=== Fix 2: Remove Redis password from .env (Redis has no auth) ==="
sed -i 's|REDIS_URL=redis://:cadencia_dev@localhost|REDIS_URL=redis://localhost|g' /home/ec2-user/cadencia/backend/.env
grep REDIS_URL /home/ec2-user/cadencia/backend/.env

echo "=== Restart backend ==="
pm2 restart cadencia-backend
sleep 6

echo "=== Final health check ==="
curl -s http://localhost:8000/health | python3.12 -m json.tool
