#!/bin/bash
# Sol VPS deployment script
# Run once on a fresh Ubuntu/Debian droplet:  bash scripts/deploy.sh

set -e

echo "==> Installing Docker..."
apt-get update -qq
apt-get install -y -qq docker.io docker-compose-plugin curl git

echo "==> Cloning repo..."
git clone https://github.com/harshtyagi7/sol.git /opt/sol
cd /opt/sol

echo "==> Creating .env from template..."
if [ ! -f .env ]; then
  cp .env.example .env
  # Generate secrets
  SECRET_KEY=$(openssl rand -hex 32)
  DB_PASSWORD=$(openssl rand -hex 16)
  REDIS_PASSWORD=$(openssl rand -hex 16)
  sed -i "s/change-me-in-production-minimum-32-chars/$SECRET_KEY/" .env
  echo "" >> .env
  echo "DB_PASSWORD=$DB_PASSWORD" >> .env
  echo "REDIS_PASSWORD=$REDIS_PASSWORD" >> .env
  echo ""
  echo ">>> .env created. Edit /opt/sol/.env and fill in your API keys before continuing."
  echo "    Required: KITE_API_KEY, KITE_API_SECRET, KITE_REDIRECT_URL, ANTHROPIC_API_KEY"
  echo "    Also update: ALLOWED_KITE_USER_ID, CORS_ORIGINS"
  echo ""
  echo "    Once done, run:  cd /opt/sol && docker compose -f docker-compose.prod.yml up -d"
  exit 0
fi

echo "==> Running migrations..."
docker compose -f docker-compose.prod.yml run --rm sol poetry run alembic upgrade head

echo "==> Starting services..."
docker compose -f docker-compose.prod.yml up -d --build

echo ""
echo "✅ Sol is running at http://$(curl -s ifconfig.me):8000"
echo "   Check logs: docker compose -f docker-compose.prod.yml logs -f sol"
