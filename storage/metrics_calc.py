"""
AUREUS-SMC Quantitative Performance Metrics Calculator
Institutional risk and performance metrics: Win Rate, Profit Factor, Sharpe Ratio, and Drawdowns.
"""

from __future__ import annotations
import math
from typing import List, Dict, Any
import numpy as np
from core.models import TradeRecord


def compute_metrics(trades: List[TradeRecord], initial_balance: float = 100_000.0) -> Dict[str, Any]:
    """
    Computes institutional quantitative statistics over a collection of closed trades.
    """
    total_trades = len(trades)
    if total_trades == 0:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "breakevens": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "net_profit": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "max_drawdown_percent": 0.0,
            "sharpe_ratio": 0.0,
            "avg_trade_pnl": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "expectancy": 0.0,
        }

    wins: List[float] = []
    losses: List[float] = []
    breakevens: int = 0
    returns: List[float] = []

    running_equity = initial_balance
    peak_equity = initial_balance
    max_dd_dollars = 0.0
    max_dd_pct = 0.0

    for t in reversed(trades):  # Process chronologically
        pnl = t.net_pnl
        if pnl > 0.01:
            wins.append(pnl)
        elif pnl < -0.01:
            losses.append(abs(pnl))
        else:
            breakevens += 1

        returns.append(pnl / running_equity if running_equity > 0 else 0.0)
        running_equity += pnl

        if running_equity > peak_equity:
            peak_equity = running_equity
        dd = peak_equity - running_equity
        if dd > max_dd_dollars:
            max_dd_dollars = dd
            max_dd_pct = (dd / peak_equity) * 100.0 if peak_equity > 0 else 0.0

    win_count = len(wins)
    loss_count = len(losses)
    win_rate = round((win_count / total_trades) * 100.0, 2)

    gross_profit = round(sum(wins), 2)
    gross_loss = round(sum(losses), 2)
    net_profit = round(gross_profit - gross_loss, 2)

    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

    avg_win = round(float(np.mean(wins)), 2) if wins else 0.0
    avg_loss = round(float(np.mean(losses)), 2) if losses else 0.0

    # Mathematical Expectancy = (Win% * AvgWin) - (Loss% * AvgLoss)
    p_win = win_count / total_trades
    p_loss = loss_count / total_trades
    expectancy = round((p_win * avg_win) - (p_loss * avg_loss), 2)

    # Annualized Sharpe Ratio estimation (assuming ~252 trading days)
    sharpe = 0.0
    if len(returns) > 1:
        mean_ret = float(np.mean(returns))
        std_ret = float(np.std(returns, ddof=1))
        if std_ret > 1e-7:
            # Assuming ~2 trades per day -> sqrt(252 * 2) = ~22.45
            sharpe = round((mean_ret / std_ret) * math.sqrt(504), 2)

    return {
        "total_trades": total_trades,
        "wins": win_count,
        "losses": loss_count,
        "breakevens": breakevens,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "net_profit": net_profit,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "max_drawdown_percent": round(max_dd_pct, 2),
        "sharpe_ratio": sharpe,
        "avg_trade_pnl": round(net_profit / total_trades, 2),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "expectancy": expectancy
    }
