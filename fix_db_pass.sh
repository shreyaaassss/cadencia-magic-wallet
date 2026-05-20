#!/bin/bash
set -e

echo "=== Fix: update .env to use cadencia_prod (matches Docker container) ==="
sed -i 's|cadencia:cadencia_dev@localhost:5432|cadencia:cadencia_prod@localhost:5432|g' /home/ec2-user/cadencia/backend/.env
sed -i 's|POSTGRES_PASSWORD=cadencia_dev|POSTGRES_PASSWORD=cadencia_prod|g' /home/ec2-user/cadencia/backend/.env

echo "=== Updated DATABASE_URL ==="
grep -E "DATABASE_URL|POSTGRES_PASSWORD" /home/ec2-user/cadencia/backend/.env | grep -v "^#"

echo "=== Restarting backend ==="
pm2 restart cadencia-backend
sleep 6

echo "=== Final health check ==="
curl -s http://localhost:8000/health | python3.12 -m json.tool
