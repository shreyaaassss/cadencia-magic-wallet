#!/bin/bash
sed -i 's/\r//' /home/ec2-user/cadencia/backend/.env
echo "CRLF stripped"
grep DATABASE_URL /home/ec2-user/cadencia/backend/.env | cat -A | head -2
pm2 restart cadencia-backend
sleep 6
curl -s http://localhost:8000/health | python3.12 -m json.tool
