#!/usr/bin/env bash
set -e

echo "=== Sol Trading System Setup ==="

# Check Python
python3 --version || { echo "Python 3.11+ required"; exit 1; }

# Install Poetry if not present
if ! command -v poetry &>/dev/null; then
    echo "Installing Poetry..."
    pip install poetry
fi

echo "Installing Python dependencies..."
poetry install

# Copy .env if not exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from template. Please fill in your API keys."
fi

# Check if Docker is available
if command -v docker &>/dev/null; then
    echo "Starting PostgreSQL and Redis..."
    docker compose up -d postgres redis
    sleep 3
    echo "Database services started"
else
    echo "Docker not found. Please start PostgreSQL and Redis manually."
    echo "  PostgreSQL: localhost:5432, db=soldb, user=sol, pass=solpass"
    echo "  Redis: localhost:6379"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env and add your API keys"
echo "  2. Run: poetry run uvicorn sol.main:app --reload"
echo "  3. Open: http://localhost:8000 (API) or run frontend separately"
echo ""
echo "To start the frontend:"
echo "  cd frontend && npm install && npm run dev"
echo ""
echo "IMPORTANT: Trading is in PAPER MODE by default."
echo "Set PAPER_TRADING_MODE=False in .env only when ready for live trading."
