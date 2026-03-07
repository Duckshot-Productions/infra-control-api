#!/bin/bash
# Quick API test script

TOKEN="${CONTROL_API_TOKEN:-changeme}"
HOST="${API_HOST:-localhost:5000}"

echo "🧪 Testing Infra Control API at $HOST"
echo ""

# Health check
echo "1️⃣ Health Check:"
curl -s -H "Authorization: Bearer $TOKEN" http://$HOST/health | jq .
echo ""

# Queue scraper
echo "2️⃣ Queue Scraper Job:"
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target": "test_site", "priority": 5}' \
  http://$HOST/run-scraper | jq .
echo ""

# Query state
echo "3️⃣ Query System State:"
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  http://$HOST/query-state | jq .
echo ""

echo "✅ Tests complete"
