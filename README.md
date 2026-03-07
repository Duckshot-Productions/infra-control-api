# Infra Control API

**Org-level API for controlling your VPS scraper fleet, MCP tool orchestration, and dual LLM routing (Qwen local/cloud + Gemini) via GitHub Actions.**

## Architecture

```
GitHub Actions (Tailscale) → VPS Control Plane → ┬→ Scraper Workers
                                                   ├→ Qwen (local/cloud)
                                                   ├→ Gemini API
                                                   └→ MCP Tools
```

## Features

- **Scraper Fleet Control**: Trigger, monitor, and queue scraping jobs
- **Dual LLM Routing**: Auto-route to Qwen local (if available) or fallback to cloud/Gemini
- **MCP Tool Execution**: Execute any MCP tool via LLM with cost tracking
- **GitHub Actions Integration**: Org-level workflows for deployment and orchestration
- **Tailscale Security**: Zero-trust networking, only accessible via tailnet
- **Event Logging**: Real-time event stream to Redis + persistent DB storage

## Setup

### 1. VPS Setup

```bash
# Install dependencies
sudo apt update && sudo apt install -y python3-pip python3-venv redis-server postgresql

# Clone repo
git clone https://github.com/DuckshotPro/infra-control-api.git /opt/infra-control-api
cd /opt/infra-control-api

# Create venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Setup database
sudo -u postgres psql
CREATE DATABASE infradb;
CREATE USER infrauser WITH PASSWORD 'yourpassword';
GRANT ALL PRIVILEGES ON DATABASE infradb TO infrauser;
\q

# Create tables
psql -U infrauser -d infradb < schema.sql

# Configure
cp .env.example .env
nano .env  # Fill in your values

# Get Tailscale IP
tailscale ip -4

# Install systemd service
sudo cp infra-control-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable infra-control-api
sudo systemctl start infra-control-api
```

### 2. GitHub Secrets

Add these secrets to your **org** or repository:

- `TS_OAUTH_CLIENT_ID`: Tailscale OAuth client ID
- `TS_OAUTH_SECRET`: Tailscale OAuth secret
- `VPS_TAILSCALE_IP`: Your VPS Tailscale IP (e.g., `100.x.x.x`)
- `VPS_SSH_KEY`: SSH private key for VPS access
- `VPS_USER`: SSH user (e.g., `ubuntu`)
- `CONTROL_API_TOKEN`: Bearer token for API auth

### 3. Deploy

Push to `main` branch or manually trigger:

```bash
gh workflow run deploy-listener.yml
```

## Usage

### Trigger Scraper via GitHub Actions

```bash
gh workflow run deploy-listener.yml \
  -f action=run-scraper \
  -f target=site_a
```

### Execute MCP Tool

```bash
gh workflow run mcp-orchestrator.yml \
  -f tool=github_search_code \
  -f arguments='{"query": "MCP server", "limit": 10}' \
  -f llm_preference=qwen-local
```

### Query System State

```bash
curl -H "Authorization: Bearer $TOKEN" \
  https://your-vps.ts.net:5000/query-state
```

## LLM Routing Logic

- **Auto**: Route to local Qwen if load < 70%, else cloud
- **qwen-local**: Force local Qwen (fails if unavailable)
- **qwen-cloud**: Use Qwen cloud API (costs $$$)
- **gemini**: Use Gemini 2.0 Flash

Cost tracking is built-in for all cloud LLM calls.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/run-scraper` | POST | Queue scraper job |
| `/scraper-status/<target>` | GET | Get scraper status |
| `/query-state` | POST | Get system state |
| `/execute-mcp` | POST | Execute MCP tool |
| `/admin/restart` | POST | Restart service |

## Next Steps

1. **Add scraper worker logic**: Implement actual scraper execution in background workers
2. **Connect MCP registry**: Wire `/execute-mcp` to your actual MCP server/tools
3. **Setup alerting**: Add webhooks to Discord/Slack on scraper failures
4. **Cost dashboard**: Build Grafana dashboard for LLM usage/costs

---

**Let Qwen or Gemini finish the implementation** 🚀
