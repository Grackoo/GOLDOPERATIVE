# AUREUS-SMC Institutional Gold (XAU/USD) Algorithmic Engine

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
![Architecture](https://img.shields.io/badge/architecture-Event--Driven-gold.svg)
![Database](https://img.shields.io/badge/sqlite-WAL%20Mode-green.svg)
![Frontend](https://img.shields.io/badge/dashboard-FastAPI%20%7C%20TradingView%20v4-cyan.svg)
![Latency](https://img.shields.io/badge/latency-%3C5ms%20Equinix%20NY4-red.svg)

**AUREUS-SMC** is an institutional-grade, event-driven quantitative trading system engineered in Python 3.11+ specifically for **Gold (XAU/USD)**. It automates the **London Session Liquidity Sweep and New York Open Displacement** Smart Money Concepts (SMC) strategy during the institutional window (08:00 AM – 10:30 AM EST/EDT) with dynamic Daylight Saving Time (DST) synchronization.

---

## 🏛️ Modular System Architecture

The architecture enforces strict decoupling via the **Observer Pattern / Asynchronous Event Bus**:

```
AUREUS-SMC/
├── core/
│   ├── models.py            # Strongly-typed dataclasses & Pydantic domain models
│   ├── events.py            # Strongly-typed event contracts
│   ├── event_bus.py         # Sub-millisecond asynchronous Event Bus (AsyncEventBus)
│   ├── state_machine.py     # Institutional State Machine with strict transition validation
│   └── time_manager.py      # ZoneInfo Timezone Manager (America/New_York) with dynamic DST
├── data/
│   ├── ring_buffer.py       # High-performance circular buffers (O(1) lookbacks)
│   ├── bar_aggregator.py    # Tick-to-candle aggregator (real-time M1 & M5 generation)
│   └── feed_manager.py      # Asset normalization & DXY/US10Y macro correlation buffers
├── strategy/
│   ├── london_range.py      # London Session (03:00 - 08:00 EST) High/Low liquidity tracking
│   ├── liquidity_sweep.py   # Wick penetration beyond London range with close inside (Turtle Soup)
│   ├── displacement.py      # Market Structure Shift (MSS/CHOCH) qualified by ATR (>1.5x ATR)
│   ├── fvg_detector.py      # 3-candle imbalance (FVG) & Consequent Encroachment (50% CE)
│   └── smc_engine.py        # Central SMC strategy coordinator synthesizing setups
├── risk/
│   ├── position_sizer.py    # Dynamic lot sizing: Lots = (Balance * %Risk) / (SL * Contract_Size)
│   ├── spread_filter.py     # Microstructure gate (max $0.30 spread tolerance)
│   ├── circuit_breaker.py   # Kill Switches: Max 2 trades/session, 2% Daily Drawdown hard stop
│   └── order_manager.py     # Active Order Management: 1:1.5 RRR BE shift, 1:2.0 RRR 50% partial
├── execution/
│   ├── base_broker.py       # Abstract BaseBrokerClient interface
│   ├── paper_broker.py      # Institutional Paper Simulator (10-35ms latency, stochastic slippage)
│   ├── mt5_broker.py        # MetaTrader 5 institutional adapter
│   └── oanda_broker.py      # OANDA v20 REST & Streaming API adapter
├── storage/
│   ├── db.py                # Asynchronous aiosqlite engine configured with PRAGMA journal_mode=WAL
│   ├── repository.py        # SQLite persistence and state rehydration on reboot
│   └── metrics_calc.py      # Win Rate, Profit Factor, Sharpe Ratio, Max Drawdown
├── macro/
│   ├── news_calendar.py     # Economic calendar parser (ForexFactory / Investing JSON feed)
│   └── news_filter.py       # Blackout window gate: [-15 min, +15 min] for High Impact USD releases
├── web/
│   ├── server.py            # FastAPI REST & WebSocket streaming server
│   └── static/              # Dark institutional TradingView Lightweight Charts v4 dashboard
├── scripts/
│   ├── run_sandbox.py       # Comprehensive verification runner with complete SMC replay
│   └── run_live.py          # Production launcher with signal handlers
├── deployment/
│   ├── Dockerfile           # Multi-stage production container
│   ├── docker-compose.yml   # Container orchestration
│   ├── aureus-trading.service # systemd unit file for Linux VPS
│   └── NY4_DEPLOYMENT_GUIDE.md # Equinix NY4 VPS tuning for <5ms latency
├── config.py                # Pydantic Settings singleton with .env support
└── requirements.txt         # Frozen dependencies
```

---

## ⚡ Core Strategy Specification (SMC XAU/USD)

1. **London Session Liquidity Accumulation (03:00 AM – 08:00 AM EST):**
   - Automatically computes and locks the London High (Buy-Side Liquidity - BSL) and London Low (Sell-Side Liquidity - SSL) at 08:00 AM EST.
2. **NY Open Liquidity Sweep (08:00 AM – 10:30 AM EST):**
   - Price penetrates beyond the London High or Low with a wick, but closes back *inside* the London range (confirming institutional trap liquidity).
3. **Displacement & Market Structure Shift (MSS / CHOCH):**
   - Price reverses impulsively, breaking local structure. The displacement candle's body size must strictly exceed **1.5 × ATR(14)** to eliminate retail noise.
4. **Fair Value Gap (FVG) & Consequent Encroachment:**
   - Detects 3-candle imbalance. Limit/market entry triggered upon mitigation of the **50% Consequent Encroachment (CE)** level.
5. **Macro News Blackout Filter:**
   - Automatically pauses all order entries **15 minutes before and 15 minutes after** high-impact USD events (NFP, CPI, FOMC).

---

## 📐 Mathematical Risk Engine

### 1. Position Sizing
$$\text{Lots} = \frac{\text{Balance} \times \text{Risk}\%}{\text{SL\_Distance}_{\$} \times \text{Contract Size}}$$
- Standard XAU/USD CFD contract size = **100 Troy Ounces per Lot**.
- Tick size = **$0.01**.
- Example: $100,000 balance with 1.0% risk ($1,000) and $7.60 SL distance:
  $$\text{Lots} = \frac{1000}{7.60 \times 100} = 1.31 \text{ lots}$$

### 2. Strict Risk-Reward Ratio (1:3 Minimum)
- Take Profit is configured at **1:3.0 RRR** minimum relative to initial risk.

### 3. Dynamic Order Progression
- **1:1.5 RRR:** Stop Loss moves to **Break-Even + $0.10** buffer (covering spread and commissions).
- **1:2.0 RRR:** Executes **50% partial close** of position volume. Residual volume runs to full 1:3 TP.

### 4. Circuit Breakers & Kill Switches
- **Hard Stop Daily Drawdown:** System automatically halts if daily loss reaches **2.0%**.
- **Max Trades Per Session:** Hard cap of **2 trades per morning session**.

---

## 🚀 Quickstart & Verification

### 1. Setup Virtual Environment
```bash
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows
.venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Run Sandbox Replay & Verification
Execute the complete institutional simulation demonstrating all 7 phases:
```bash
python scripts/run_sandbox.py
```

### 3. Launch Live Production Engine & Web Dashboard
```bash
python scripts/run_live.py
```
Open your browser at:
```
http://localhost:8000
```

---

## 📊 High-Speed WebSocket Dashboard

The dashboard provides:
- **TradingView Lightweight Charts v4+** with dynamic multi-layer canvas rendering.
- **Live Overlays:** London High/Low (BSL/SSL), Liquidity Sweeps, MSS/CHOCH, Fair Value Gaps, Stop Loss, Take Profit, and Break-Even lines.
- **Real-Time KPIs:** Win Rate %, Profit Factor, Annualized Sharpe Ratio, Max Drawdown %, and Live Floating PnL.
- **SQLite Trade Audit Trail:** Instant display of closed trades with R-multiples and execution breakdown.

---

## 🛡️ License
Proprietary Institutional Quantitative Software. All rights reserved.
