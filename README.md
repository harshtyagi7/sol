# Sol - AI Trading Orchestrator for Indian Stock Market

Sol is a multi-agent AI trading system for NSE/BSE. It coordinates multiple AI sub-agents (Claude, GPT-4, Gemini) that independently analyze the market and propose trades. Sol reviews everything and confirms with you before a single order is placed.

## Architecture

```
You (Harsh)
    ↕  (approve/reject/chat)
Sol (Claude Opus — Orchestrator)
    ↕  (collects proposals, enforces risk)
┌─────────────────────────────────┐
│  Agent Alpha   Agent Beta   Agent Gamma  │
│  (Claude)      (GPT-4)      (Gemini)     │
└─────────────────────────────────┘
    ↕  (market data, order execution)
Zerodha Kite Connect (NSE/BSE)
```

## Key Features

- **Multi-agent**: Each LLM independently proposes trades. Consensus = stronger signal.
- **Sol orchestrates**: Collects proposals, validates risk, presents to you for confirmation.
- **No trade without you**: Every single order requires your explicit approval.
- **Risk firewall**: Configurable max risk per trade, daily loss limits, position limits — never exceeded.
- **Paper trading default**: Safe mode by default. PAPER_TRADING_MODE=False to go live.
- **Real-time dashboard**: Live positions, P&L, risk meter, agent performance comparison.
- **Chat with Sol**: Natural language interface to ask about portfolio, positions, strategy.

## Quick Start

```bash
# 1. Clone and setup
bash scripts/setup.sh

# 2. Configure API keys in .env
KITE_API_KEY=...
KITE_API_SECRET=...
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...      # optional
GOOGLE_API_KEY=...      # optional

# 3. Start backend
poetry run uvicorn sol.main:app --reload

# 4. Start frontend (separate terminal)
cd frontend && npm install && npm run dev

# 5. Open http://localhost:3000
```

## Zerodha Login (Required Daily)

Kite access tokens expire daily at 6 AM IST. Each morning:

1. Visit http://localhost:3000
2. Go to the login prompt or visit http://localhost:8000/api/auth/login
3. Complete Zerodha 2FA — you'll be redirected back automatically

## Risk Configuration

Configure via the Risk tab in the dashboard:

| Setting | Default | Description |
|---------|---------|-------------|
| Max Risk Per Trade | 2% | Max % of capital at risk per trade |
| Daily Loss Limit | 5% | If daily loss hits this %, trading stops |
| Max Open Positions | 5 | Maximum simultaneous positions |
| Max Position Size | 10% | Max % of capital in one stock |

## Agent Management

Add/remove agents from the Agents tab. Each agent:
- Runs independently with its configured LLM and strategy prompt
- Maintains a virtual portfolio to track its own performance
- Reports proposals to Sol every 15 minutes during market hours

## Trading Flow

```
9:15 AM IST → Scheduler triggers analysis
→ All agents analyze market data concurrently
→ Proposals collected and risk-validated by Sol
→ Dashboard notification: "X proposals need review"
→ You review each proposal (rationale, risk:reward)
→ Approve / Reject / Modify
→ Approved orders execute via Zerodha
→ Positions monitored (SL auto-exit, TP alert)
→ 3:35 PM → EOD report from Sol
```

## Project Structure

```
sol/
├── core/           # Orchestrator, risk engine, scheduler
├── agents/         # Claude, GPT-4, Gemini sub-agents
├── broker/         # Zerodha Kite Connect + paper broker
├── models/         # SQLAlchemy ORM models
├── schemas/        # Pydantic schemas
├── api/            # FastAPI routes
└── services/       # Business logic
frontend/           # React dashboard
tests/              # Unit + integration tests
```

## Safety Notes

- **PAPER_TRADING_MODE=True by default** — no real orders until you set it to False
- Risk limits are validated TWICE: at proposal time AND at execution time
- Stop-loss is required on every trade by default
- Daily loss limit halts ALL new trades for the day when hit
