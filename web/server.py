"""
AUREUS-SMC High-Speed Web Server & WebSocket Streaming Engine
FastAPI application delivering real-time institutional metrics and TradingView chart data.
"""

from __future__ import annotations
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from core.models import SystemState, OrderSide, Order, OrderType, OrderStatus
from core.events import (
    TickEvent, BarClosedEvent, BarUpdateEvent, LondonRangeCalculatedEvent,
    LiquiditySweepEvent, DisplacementEvent, FVGDetectedEvent,
    SignalGeneratedEvent, OrderFilledEvent, PositionModifiedEvent,
    PositionClosedEvent, AccountUpdateEvent, SystemStateChangedEvent
)
from core.event_bus import event_bus
from core.state_machine import state_machine
from core.time_manager import time_manager
from storage.db import db_manager
from storage.repository import repository
from storage.metrics_calc import compute_metrics
from strategy.daily_decision_engine import daily_decision_engine
from config import settings

logger = logging.getLogger("WebServer")

app = FastAPI(title=settings.SYSTEM_NAME, version="2.0.0")

# Mount static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


class ConnectionManager:
    """Manages active browser WebSocket subscriptions for sub-millisecond broadcast."""

    def __init__(self) -> None:
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.debug(f"Client connected. Active WebSockets: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)
        logger.debug(f"Client disconnected. Active WebSockets: {len(self.active_connections)}")

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Broadcasts JSON payload concurrently to all connected frontends."""
        if not self.active_connections:
            return
        payload = json.dumps(message)
        dead = []
        for connection in self.active_connections:
            try:
                await connection.send_text(payload)
            except Exception:
                dead.append(connection)
        for d in dead:
            self.active_connections.discard(d)


ws_manager = ConnectionManager()


# --- Event Bus to WebSocket Bridge ---

async def _ws_on_tick(event: TickEvent) -> None:
    await ws_manager.broadcast({
        "type": "TICK",
        "data": {
            "symbol": event.tick.symbol,
            "bid": event.tick.bid,
            "ask": event.tick.ask,
            "mid": event.tick.mid,
            "spread": event.tick.spread,
            "timestamp": event.tick.timestamp.isoformat()
        }
    })

async def _ws_on_bar_update(event: BarUpdateEvent) -> None:
    bar = event.bar
    await ws_manager.broadcast({
        "type": "BAR_UPDATE",
        "data": {
            "timeframe": bar.timeframe,
            "time": int(bar.timestamp.timestamp()),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "is_closed": False
        }
    })

async def _ws_on_bar_closed(event: BarClosedEvent) -> None:
    bar = event.bar
    await ws_manager.broadcast({
        "type": "BAR_CLOSED",
        "data": {
            "timeframe": bar.timeframe,
            "time": int(bar.timestamp.timestamp()),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "is_closed": True
        }
    })

async def _ws_on_london_range(event: LondonRangeCalculatedEvent) -> None:
    lr = event.london_range
    await ws_manager.broadcast({
        "type": "LONDON_RANGE",
        "data": {
            "high": lr.high,
            "low": lr.low,
            "range_size": lr.range_size,
            "date": lr.date_str
        }
    })

async def _ws_on_sweep(event: LiquiditySweepEvent) -> None:
    sw = event.sweep
    await ws_manager.broadcast({
        "type": "LIQUIDITY_SWEEP",
        "data": {
            "direction": sw.direction.value,
            "level": sw.level_swept,
            "extreme": sw.wick_extreme,
            "pips": sw.penetration_pips,
            "time": sw.timestamp.isoformat()
        }
    })

async def _ws_on_displacement(event: DisplacementEvent) -> None:
    mss = event.mss
    await ws_manager.broadcast({
        "type": "DISPLACEMENT",
        "data": {
            "direction": mss.direction.value,
            "broken_level": mss.broken_swing_level,
            "ratio": mss.body_to_atr_ratio,
            "time": mss.timestamp.isoformat()
        }
    })

async def _ws_on_fvg(event: FVGDetectedEvent) -> None:
    fvg = event.fvg
    await ws_manager.broadcast({
        "type": "FVG",
        "data": {
            "direction": fvg.direction.value,
            "top": fvg.top,
            "bottom": fvg.bottom,
            "ce": fvg.consequent_encroachment,
            "time": fvg.timestamp.isoformat()
        }
    })

async def _ws_on_signal(event: SignalGeneratedEvent) -> None:
    await ws_manager.broadcast({
        "type": "SIGNAL",
        "data": {
            "id": event.signal_id,
            "direction": event.direction,
            "entry": event.entry_price,
            "sl": event.stop_loss,
            "tp": event.take_profit,
            "rrr": event.risk_reward_ratio,
            "reason": event.reason
        }
    })

async def _ws_on_state_change(event: SystemStateChangedEvent) -> None:
    await ws_manager.broadcast({
        "type": "STATE_CHANGE",
        "data": {
            "previous": event.previous_state.value,
            "current": event.new_state.value,
            "reason": event.reason,
            "time": event.timestamp.isoformat()
        }
    })

async def _ws_on_order_filled(event: OrderFilledEvent) -> None:
    await ws_manager.broadcast({
        "type": "ORDER_FILLED",
        "data": {
            "ticket": event.position.ticket,
            "position_id": event.position.position_id,
            "side": event.position.side.value if hasattr(event.position.side, "value") else str(event.position.side),
            "volume": event.position.volume,
            "entry_price": event.position.entry_price,
            "stop_loss": event.position.stop_loss,
            "take_profit": event.position.take_profit,
            "time": event.position.opened_at.isoformat()
        }
    })

async def _ws_on_position_closed(event: PositionClosedEvent) -> None:
    await ws_manager.broadcast({
        "type": "POSITION_CLOSED",
        "data": {
            "trade_id": event.trade_record.trade_id,
            "position_id": event.trade_record.position_id,
            "side": event.trade_record.side.value if hasattr(event.trade_record.side, "value") else str(event.trade_record.side),
            "volume": event.trade_record.volume,
            "entry_price": event.trade_record.entry_price,
            "exit_price": event.trade_record.exit_price,
            "net_pnl": event.trade_record.net_pnl,
            "r_multiple": event.trade_record.r_multiple_realized,
            "reason": event.trade_record.close_reason,
            "time": event.trade_record.close_time.isoformat()
        }
    })

async def _ws_on_position_modified(event: PositionModifiedEvent) -> None:
    await ws_manager.broadcast({
        "type": "POSITION_MODIFIED",
        "data": {
            "position_id": event.position.position_id,
            "modification_type": event.modification_type,
            "new_sl": event.new_sl,
            "new_tp": event.new_tp
        }
    })

# Register internal WebSocket subscriptions
event_bus.subscribe(TickEvent, _ws_on_tick)
event_bus.subscribe(BarUpdateEvent, _ws_on_bar_update)
event_bus.subscribe(BarClosedEvent, _ws_on_bar_closed)
event_bus.subscribe(LondonRangeCalculatedEvent, _ws_on_london_range)
event_bus.subscribe(LiquiditySweepEvent, _ws_on_sweep)
event_bus.subscribe(DisplacementEvent, _ws_on_displacement)
event_bus.subscribe(FVGDetectedEvent, _ws_on_fvg)
event_bus.subscribe(SignalGeneratedEvent, _ws_on_signal)
event_bus.subscribe(SystemStateChangedEvent, _ws_on_state_change)
event_bus.subscribe(OrderFilledEvent, _ws_on_order_filled)
event_bus.subscribe(PositionClosedEvent, _ws_on_position_closed)
event_bus.subscribe(PositionModifiedEvent, _ws_on_position_modified)


# --- REST API Endpoints ---

@app.get("/", response_class=FileResponse)
async def serve_index():
    """Serves the institutional trading desk frontend."""
    return FileResponse(str(static_dir / "index.html"))


@app.get("/api/status")
async def get_system_status():
    """Retrieves current engine state, New York time, and strategy status."""
    ny_now = time_manager.now()
    return {
        "system_name": settings.SYSTEM_NAME,
        "environment": settings.ENVIRONMENT,
        "broker_type": settings.BROKER_TYPE,
        "state": state_machine.state.value,
        "ny_time": ny_now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "is_london_session": time_manager.is_in_london_session(ny_now),
        "is_ny_window": time_manager.is_in_ny_execution_window(ny_now),
        "symbol": settings.SYMBOL,
        "contract_size": settings.CONTRACT_SIZE
    }


@app.get("/api/metrics")
async def get_performance_metrics():
    """Returns real-time quantitative metrics computed from SQLite history."""
    trades = await repository.get_all_trades()
    return compute_metrics(trades, settings.INITIAL_BALANCE)


@app.get("/api/trades")
async def get_trades_history(limit: int = Query(default=100, le=500)):
    """Returns closed trade audit records from SQLite."""
    trades = await repository.get_all_trades(limit=limit)
    return [
        {
            "trade_id": t.trade_id,
            "position_id": t.position_id,
            "side": t.side.value if hasattr(t.side, "value") else str(t.side),
            "volume": t.volume,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "stop_loss": t.stop_loss,
            "take_profit": t.take_profit,
            "r_multiple": t.r_multiple_realized,
            "net_pnl": t.net_pnl,
            "commission": t.commission,
            "open_time": t.open_time.isoformat(),
            "close_time": t.close_time.isoformat(),
            "close_reason": t.close_reason,
            "smc_setup": t.smc_setup_type
        }
        for t in trades
    ]


@app.get("/api/positions")
async def get_active_positions():
    """Returns live open positions with real-time mark-to-market prices and floating PnL."""
    if hasattr(app.state, "broker") and app.state.broker:
        positions = await app.state.broker.get_open_positions()
    else:
        positions = await repository.rehydrate_positions()
    return [
        {
            "position_id": p.position_id,
            "ticket": p.ticket,
            "side": p.side.value if hasattr(p.side, "value") else str(p.side),
            "volume": p.volume,
            "entry_price": p.entry_price,
            "current_price": p.current_price,
            "stop_loss": p.stop_loss,
            "take_profit": p.take_profit,
            "r_multiple": p.current_r_multiple(),
            "unrealized_pnl": p.unrealized_pnl,
            "break_even": p.break_even_set,
            "partial_closed": p.partial_closed,
            "opened_at": p.opened_at.isoformat()
        }
        for p in positions
    ]


@app.post("/api/orders")
async def place_order_endpoint(request: Request):
    """
    Direct institutional order entry from dashboard.
    Executes real orders into the trading engine with live matching and SL/TP sentinel.
    """
    try:
        data = await request.json()
    except Exception:
        return {"success": False, "error": "Invalid JSON payload"}

    side_str = data.get("side", "BUY").upper()
    volume = float(data.get("volume", 0.10))
    order_type_str = data.get("order_type", "MARKET").upper()
    entry_price = float(data.get("entry_price", 0.0)) if data.get("entry_price") else None
    stop_loss = float(data.get("stop_loss", 0.0)) if data.get("stop_loss") else None
    take_profit = float(data.get("take_profit", 0.0)) if data.get("take_profit") else None
    comment = str(data.get("comment", "Manual Order"))

    if volume <= 0:
        return {"success": False, "error": "El volumen debe ser mayor a 0"}

    side = OrderSide.BUY if side_str == "BUY" else OrderSide.SELL
    order_type = OrderType.MARKET if order_type_str == "MARKET" else OrderType.LIMIT

    # Obtain current real-time prices
    current_bid = 4055.20
    current_ask = 4055.21
    if hasattr(app.state, "feed_manager") and app.state.feed_manager and app.state.feed_manager.latest_tick:
        current_bid = app.state.feed_manager.latest_tick.bid
        current_ask = app.state.feed_manager.latest_tick.ask

    base_price = current_ask if side == OrderSide.BUY else current_bid
    if entry_price and order_type == OrderType.LIMIT:
        base_price = entry_price

    # Auto SL/TP if omitted (Default 1:3 RRR)
    if stop_loss is None or stop_loss <= 0:
        risk_dist = 14.0
        stop_loss = round(base_price - risk_dist if side == OrderSide.BUY else base_price + risk_dist, 2)

    if take_profit is None or take_profit <= 0:
        risk_dist = abs(base_price - stop_loss)
        take_profit = round(base_price + (risk_dist * 3.0) if side == OrderSide.BUY else base_price - (risk_dist * 3.0), 2)

    order = Order(
        order_id=f"ORD_{int(datetime.now(timezone.utc).timestamp())}_{uuid.uuid4().hex[:4]}",
        client_order_id=f"GUI_{uuid.uuid4().hex[:6]}",
        symbol=settings.SYMBOL,
        side=side,
        order_type=order_type,
        volume=volume,
        entry_price=base_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        status=OrderStatus.PENDING,
        created_at=datetime.now(timezone.utc),
        comment=comment
    )

    if not hasattr(app.state, "broker") or not app.state.broker:
        return {"success": False, "error": "El motor de ejecución no está conectado."}

    filled_order = await app.state.broker.place_order(order)
    return {
        "success": filled_order.status in [OrderStatus.FILLED, OrderStatus.PENDING],
        "order_id": filled_order.order_id,
        "status": filled_order.status.value,
        "entry_price": filled_order.filled_price or filled_order.entry_price,
        "volume": filled_order.volume,
        "stop_loss": filled_order.stop_loss,
        "take_profit": filled_order.take_profit,
        "side": filled_order.side.value
    }


@app.post("/api/positions/{position_id}/close")
async def close_position_endpoint(position_id: str):
    """Liquidates an open market position immediately at market price."""
    if not hasattr(app.state, "broker") or not app.state.broker:
        return {"success": False, "error": "Broker no disponible"}

    trade = await app.state.broker.close_position(position_id, reason="MANUAL_CLOSE")
    if trade:
        return {
            "success": True,
            "trade_id": trade.trade_id,
            "net_pnl": trade.net_pnl,
            "exit_price": trade.exit_price,
            "close_reason": trade.close_reason
        }
    return {"success": False, "error": "Posición no encontrada o ya liquidada"}


@app.post("/api/trades/reset")
async def reset_trades_endpoint():
    """Resets audit trail database and starts clean audit session."""
    async with db_manager.get_connection() as conn:
        await conn.execute("DELETE FROM trades")
        await conn.execute("DELETE FROM active_positions")
        await conn.commit()

    if hasattr(app.state, "broker") and hasattr(app.state.broker, "trade_history"):
        app.state.broker.trade_history.clear()
        app.state.broker.positions.clear()
        app.state.broker.balance = settings.INITIAL_BALANCE

    logger.info("Trade Audit Trail reset cleanly to 0.")
    return {"success": True, "message": "Auditoría reiniciada con éxito a 0 operaciones."}


@app.get("/api/bars")
async def get_bars(timeframe: str = "M1", count: int = 120):
    """Returns historical bars for initial chart population."""
    bars_data = []
    if hasattr(app.state, "bar_aggregator"):
        bars = app.state.bar_aggregator.get_latest_bars(timeframe, count=count)
        bars_data = [
            {
                "time": int(b.timestamp.timestamp()),
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume
            }
            for b in bars
        ]

    # If empty, generate baseline Gold structure
    if not bars_data:
        from datetime import timedelta, timezone
        now = datetime.now(timezone.utc)
        step_map = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800}
        step = step_map.get(timeframe.upper(), 60)
        base_price = 2735.0
        import random
        prices = []
        p = base_price
        for _ in range(count):
            p += random.uniform(-0.6, 0.6)
            prices.append(round(p, 2))

        for i, price in enumerate(prices):
            bar_time = now - timedelta(seconds=(count - i) * step)
            high = round(price + random.uniform(0.1, 0.8), 2)
            low = round(price - random.uniform(0.1, 0.8), 2)
            bars_data.append({
                "time": int(bar_time.timestamp()),
                "open": round(price + random.uniform(-0.3, 0.3), 2),
                "high": high,
                "low": low,
                "close": price,
                "volume": random.randint(50, 250)
            })

    return bars_data


@app.get("/api/daily-briefing")
async def get_daily_briefing():
    """Retrieves current session parameters, pivot levels, COT data, and 1:3 CALL & PUT setups."""
    current_price = 4055.20
    if hasattr(app.state, "feed_manager") and app.state.feed_manager and app.state.feed_manager.latest_tick:
        current_price = app.state.feed_manager.latest_tick.bid
    elif hasattr(app.state, "bar_aggregator") and app.state.bar_aggregator:
        bars_m1 = app.state.bar_aggregator.get_latest_bars("M1", count=5)
        if bars_m1:
            current_price = bars_m1[-1].close

    bars = []
    if hasattr(app.state, "bar_aggregator") and app.state.bar_aggregator:
        bars = app.state.bar_aggregator.get_latest_bars("M15", count=60)

    analysis = daily_decision_engine.calculate_session_parameters(current_price, bars)
    return analysis


@app.post("/api/daily-briefing/recalculate")
async def recalculate_daily_briefing(request: Request):
    """
    Recalculates setups and zones on demand.
    Accepts optional custom daily parameters or calculates from the real-time live market tick.
    """
    body: Dict[str, Any] = {}
    try:
        raw_body = await request.body()
        if raw_body:
            body = json.loads(raw_body)
    except Exception:
        body = {}

    # If explicit parameters provided, persist them
    if body and any(k in body for k in ["open_price", "current_price", "min_price", "max_price", "atr"]):
        daily_decision_engine.save_stored_parameters(body)
    elif body and body.get("mode") == "reset_live":
        # Delete custom parameters file to revert to pure live mode
        try:
            if daily_decision_engine.input_file.exists():
                daily_decision_engine.input_file.unlink()
        except Exception as e:
            logger.warning(f"Failed to unlink daily_input.json: {e}")

    # Determine real-time market price
    current_price = 4055.20
    if hasattr(app.state, "feed_manager") and app.state.feed_manager and app.state.feed_manager.latest_tick:
        current_price = app.state.feed_manager.latest_tick.bid
    elif hasattr(app.state, "bar_aggregator") and app.state.bar_aggregator:
        bars_m1 = app.state.bar_aggregator.get_latest_bars("M1", count=5)
        if bars_m1:
            current_price = bars_m1[-1].close

    bars = []
    if hasattr(app.state, "bar_aggregator") and app.state.bar_aggregator:
        bars = app.state.bar_aggregator.get_latest_bars("M15", count=60)

    analysis = daily_decision_engine.calculate_session_parameters(
        current_price=current_price,
        bars=bars,
        custom_params=body if body else None
    )

    # Write local storage copy of markdown report
    md_content = daily_decision_engine.generate_markdown_report(analysis)
    report_path = Path("storage/INFORME_OPERATIVO_DIARIO.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(md_content, encoding="utf-8")

    return analysis


@app.get("/api/daily-briefing/parameters")
async def get_daily_parameters():
    """Returns stored user parameters from storage/daily_input.json."""
    params = daily_decision_engine.load_stored_parameters()
    return params or {"mode": "live"}


@app.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket):
    """High-speed WebSocket stream broadcasting market ticks, bars, SMC levels, and fills."""
    await ws_manager.connect(websocket)
    try:
        # Initial greeting with state snapshot
        await websocket.send_text(json.dumps({
            "type": "INITIAL_HANDSHAKE",
            "data": {
                "system": settings.SYSTEM_NAME,
                "state": state_machine.state.value,
                "ny_time": time_manager.now().isoformat()
            }
        }))
        while True:
            # Keepalive listener
            data = await websocket.receive_text()
            if data == "PING":
                await websocket.send_text(json.dumps({"type": "PONG"}))
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket client error: {e}")
        ws_manager.disconnect(websocket)
