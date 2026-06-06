#!/bin/bash
# Production smoke test — verifies all deployed changes
set -u
API="http://localhost:8000"
PASS=0; FAIL=0; TOTAL=0

check() {
  TOTAL=$((TOTAL+1))
  if [ "$1" = "PASS" ]; then PASS=$((PASS+1)); echo "  PASS: $2"
  else FAIL=$((FAIL+1)); echo "  FAIL: $2 -- $3"; fi
}

echo "============================================"
echo "  CADENCIA PRODUCTION SMOKE TEST"
echo "============================================"

echo ""
echo "--- Module 1: Industry Taxonomies ---"
RESP=$(curl -s $API/v1/marketplace/industries)
COUNT=$(echo "$RESP" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('data',[])))" 2>/dev/null)
[ "$COUNT" -ge 10 ] 2>/dev/null && check PASS "Industries: $COUNT taxonomies" || check FAIL "Industries count" "$COUNT"

HAS_MT=$(echo "$RESP" | python3 -c "
import sys,json
d=json.load(sys.stdin)['data']
m=[r for r in d if r['industry_code']=='METALS']
print('True' if m and 'MT' in m[0]['default_units'] else 'False')
" 2>/dev/null)
[ "$HAS_MT" = "True" ] && check PASS "METALS has MT" || check FAIL "METALS MT" "$HAS_MT"

HAS_PIECE=$(echo "$RESP" | python3 -c "
import sys,json
d=json.load(sys.stdin)['data']
e=[r for r in d if r['industry_code']=='ELECTRONICS']
print('True' if e and 'PIECE' in e[0]['default_units'] else 'False')
" 2>/dev/null)
[ "$HAS_PIECE" = "True" ] && check PASS "ELECTRONICS has PIECE" || check FAIL "ELECTRONICS PIECE" "$HAS_PIECE"

echo ""
echo "--- Module 2: Embedding Tracking Columns ---"
for COL in embedding_status embedding_version last_embedded_at; do
  EXISTS=$(PGPASSWORD=cadencia_prod psql -h localhost -U cadencia -d cadencia -t -c \
    "SELECT count(*) FROM information_schema.columns WHERE table_name='capability_profiles' AND column_name='$COL';" 2>/dev/null | tr -d ' ')
  [ "$EXISTS" = "1" ] && check PASS "capability_profiles.$COL" || check FAIL "capability_profiles.$COL" "missing"
done

echo ""
echo "--- Module 3: Catalogue Commercial Fields ---"
for COL in floor_price_inr max_discount_pct negotiation_enabled version status validity_end_date payment_terms region_restrictions; do
  EXISTS=$(PGPASSWORD=cadencia_prod psql -h localhost -U cadencia -d cadencia -t -c \
    "SELECT count(*) FROM information_schema.columns WHERE table_name='catalogue_items' AND column_name='$COL';" 2>/dev/null | tr -d ' ')
  [ "$EXISTS" = "1" ] && check PASS "catalogue_items.$COL" || check FAIL "catalogue_items.$COL" "missing"
done

echo ""
echo "--- Module 4: Capacity Unit + Shift Nullable ---"
EXISTS=$(PGPASSWORD=cadencia_prod psql -h localhost -U cadencia -d cadencia -t -c \
  "SELECT count(*) FROM information_schema.columns WHERE table_name='seller_capacity_profiles' AND column_name='capacity_unit';" 2>/dev/null | tr -d ' ')
[ "$EXISTS" = "1" ] && check PASS "capacity_unit column" || check FAIL "capacity_unit" "missing"

NULLABLE=$(PGPASSWORD=cadencia_prod psql -h localhost -U cadencia -d cadencia -t -c \
  "SELECT is_nullable FROM information_schema.columns WHERE table_name='seller_capacity_profiles' AND column_name='shift_pattern';" 2>/dev/null | tr -d ' ')
[ "$NULLABLE" = "YES" ] && check PASS "shift_pattern nullable" || check FAIL "shift_pattern nullable" "$NULLABLE"

echo ""
echo "--- Module 5: Catalogue Versioning + Change Log ---"
CL=$(PGPASSWORD=cadencia_prod psql -h localhost -U cadencia -d cadencia -t -c \
  "SELECT count(*) FROM information_schema.tables WHERE table_name='catalogue_change_log';" 2>/dev/null | tr -d ' ')
[ "$CL" = "1" ] && check PASS "catalogue_change_log table" || check FAIL "change_log table" "$CL"

echo ""
echo "--- Module 6: FK Constraints + Audit Trigger ---"
for CONS in fk_negotiation_sessions_rfq_id fk_negotiation_sessions_match_id; do
  C=$(PGPASSWORD=cadencia_prod psql -h localhost -U cadencia -d cadencia -t -c \
    "SELECT count(*) FROM information_schema.table_constraints WHERE constraint_name='$CONS';" 2>/dev/null | tr -d ' ')
  [ "$C" = "1" ] && check PASS "FK $CONS" || check FAIL "FK $CONS" "missing"
done

TRG=$(PGPASSWORD=cadencia_prod psql -h localhost -U cadencia -d cadencia -t -c \
  "SELECT count(*) FROM pg_trigger WHERE tgname='trg_enforce_audit_hash_chain';" 2>/dev/null | tr -d ' ')
[ "$TRG" = "1" ] && check PASS "Audit hash chain trigger" || check FAIL "audit trigger" "$TRG"

echo ""
echo "--- Module 7: Full-Text Search Index ---"
FTS=$(PGPASSWORD=cadencia_prod psql -h localhost -U cadencia -d cadencia -t -c \
  "SELECT count(*) FROM pg_indexes WHERE indexname='ix_catalogue_items_fulltext';" 2>/dev/null | tr -d ' ')
[ "$FTS" = "1" ] && check PASS "GIN fulltext index" || check FAIL "fulltext index" "$FTS"

echo ""
echo "--- Module 8: API Endpoint Health ---"
BE=$(curl -s -o /dev/null -w '%{http_code}' $API/v1/marketplace/industries)
[ "$BE" = "200" ] && check PASS "Backend API (HTTP $BE)" || check FAIL "Backend" "HTTP $BE"

ES=$(curl -s -o /dev/null -w '%{http_code}' $API/v1/marketplace/task-status/embedding)
[ "$ES" = "401" ] || [ "$ES" = "200" ] && check PASS "Embedding status endpoint (HTTP $ES)" || check FAIL "Embedding status" "HTTP $ES"

BULK=$(curl -s -o /dev/null -w '%{http_code}' -X POST $API/v1/marketplace/catalogue/bulk -H 'Content-Type: application/json' -d '{}')
[ "$BULK" = "401" ] || [ "$BULK" = "422" ] && check PASS "Bulk catalogue endpoint (HTTP $BULK)" || check FAIL "Bulk catalogue" "HTTP $BULK"

FE=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:3000/)
[ "$FE" = "200" ] && check PASS "Frontend (HTTP $FE)" || check FAIL "Frontend" "HTTP $FE"

echo ""
echo "--- Module 9: Alembic Version ---"
cd ~/cadencia/backend && source venv/bin/activate 2>/dev/null
VER=$(alembic current 2>&1 | grep -oP '\d+' | tail -1)
[ "$VER" = "026" ] && check PASS "Alembic at 026 (head)" || check FAIL "Alembic version" "$VER"

echo ""
echo "============================================"
echo "  RESULTS: $PASS passed / $FAIL failed / $TOTAL total"
echo "============================================"
[ $FAIL -eq 0 ] && echo "  ALL TESTS PASSED" || echo "  $FAIL FAILURES"
