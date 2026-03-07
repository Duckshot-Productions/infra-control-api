#!/bin/bash
set -e

echo "🚀 Setting up Infra Control API..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
  echo "Please run as root (sudo)"
  exit 1
fi

# Install system dependencies
echo "📦 Installing system dependencies..."
apt update
apt install -y python3-pip python3-venv redis-server postgresql postgresql-contrib curl jq

# Setup PostgreSQL
echo "🗄️ Setting up PostgreSQL..."
sudo -u postgres psql -c "CREATE DATABASE infradb;" || echo "Database already exists"
sudo -u postgres psql -c "CREATE USER infrauser WITH PASSWORD 'changeme123';" || echo "User already exists"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE infradb TO infrauser;"

# Clone or update repo
REPO_PATH="/opt/infra-control-api"
if [ -d "$REPO_PATH" ]; then
  echo "📥 Updating repo..."
  cd $REPO_PATH
  git pull
else
  echo "📥 Cloning repo..."
  git clone https://github.com/DuckshotPro/infra-control-api.git $REPO_PATH
  cd $REPO_PATH
fi

# Setup Python venv
echo "🐍 Setting up Python venv..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Setup database schema
echo "📋 Creating database tables..."
PGPASSWORD=changeme123 psql -U infrauser -d infradb -h localhost < schema.sql

# Setup environment file
if [ ! -f ".env" ]; then
  echo "⚙️ Creating .env file..."
  cp .env.example .env
  
  # Generate secure token
  TOKEN=$(openssl rand -hex 32)
  sed -i "s/your-secret-token-here/$TOKEN/g" .env
  
  # Get Tailscale IP
  TS_IP=$(tailscale ip -4 2>/dev/null || echo "100.0.0.1")
  sed -i "s/100.x.x.x/$TS_IP/g" .env
  
  echo "🔑 Generated CONTROL_TOKEN: $TOKEN"
  echo "📍 Tailscale IP: $TS_IP"
  echo ""
  echo "⚠️  IMPORTANT: Save this token! Add it to your GitHub secrets as CONTROL_API_TOKEN"
  echo ""
else
  echo "⚠️  .env file already exists, skipping creation"
fi

# Install systemd services
echo "🔧 Installing systemd services..."
cp infra-control-api.service /etc/systemd/system/
cp workers/scraper_worker.service /etc/systemd/system/
systemctl daemon-reload

# Start services
echo "🚀 Starting services..."
systemctl enable infra-control-api
systemctl start infra-control-api

systemctl enable scraper_worker
systemctl start scraper_worker

# Check status
sleep 3
echo ""
echo "📊 Service Status:"
systemctl status infra-control-api --no-pager -l | head -15
echo ""
systemctl status scraper_worker --no-pager -l | head -15

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Add GitHub secrets (see README.md)"
echo "2. Update .env with your API keys"
echo "3. Add scraper scripts to /opt/scrapers/"
echo "4. Test with: curl -H 'Authorization: Bearer YOUR_TOKEN' http://$(tailscale ip -4):5000/health"
