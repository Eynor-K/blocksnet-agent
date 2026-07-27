#!/usr/bin/env bash
# a2a/07: end-to-end smoke для docker-compose.
#
# Поднимает compose → ждёт healthcheck → проверяет Agent Card → проверяет
# MCP через python -c import → гасит. Код возврата 0 при успехе, !=0 при любой
# ошибке.
#
# Требует: docker, docker compose, curl.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== build ==="
docker compose build --quiet

echo
echo "=== up ==="
docker compose up -d

echo
echo "=== wait healthchecks ==="
TIMEOUT=120
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
    STATUS=$(docker compose ps --format json 2>/dev/null | python3 -c "
import sys, json
healthy = True
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        s = json.loads(line)
    except json.JSONDecodeError:
        continue
    if 'Health' in s and s['Health'] != 'healthy':
        healthy = False
print('healthy' if healthy else 'unhealthy')
" 2>/dev/null || echo "starting")
    if [ "$STATUS" = "healthy" ]; then
        echo "all services healthy after ${ELAPSED}s"
        break
    fi
    sleep 5
    ELAPSED=$((ELAPSED + 5))
done

if [ "$STATUS" != "healthy" ]; then
    echo "ERROR: services did not become healthy within ${TIMEOUT}s"
    docker compose logs --tail=50
    docker compose down -v
    exit 1
fi

echo
echo "=== Agent Card (HTTP GET) ==="
AGENT_RESPONSE=$(curl -fsS http://127.0.0.1:8080/.well-known/agent-card.json)
if echo "$AGENT_RESPONSE" | python3 -c "
import sys, json
card = json.load(sys.stdin)
assert card['name'] == 'blocksnet-mcp-a2a', f'unexpected name: {card.get(\"name\")}'
assert len(card['skills']) >= 2, f'expected ≥2 skills, got {len(card[\"skills\"])}'
print(f'  name={card[\"name\"]}, skills={len(card[\"skills\"])}')
" 2>&1; then
    echo "$AGENT_RESPONSE" | python3 -m json.tool | head -20
else
    echo "ERROR: Agent Card check failed"
    docker compose down -v
    exit 1
fi

echo
echo "=== MCP tools via python -c import ==="
docker compose exec -T mcp python -c "
import blocksnet_mcp.server as s
m = s.get_mcp()
import asyncio
tools = asyncio.run(m.list_tools())
assert len(tools) >= 32, f'expected ≥32 tools, got {len(tools)}'
print(f'  registered tools: {len(tools)}')
# submit_answer не должен экспонироваться
names = {t.name for t in tools}
assert 'submit_answer' not in names, 'submit_answer leaked to MCP'
print('  submit_answer absent (good)')
"

echo
echo "=== итог ==="
echo "  SMOKE OK"
docker compose down
exit 0