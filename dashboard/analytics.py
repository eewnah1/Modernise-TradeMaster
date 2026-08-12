"""Performance and risk analytics for dashboard results.

All functions accept pandas/numpy inputs and return JSON-serialisable dicts.
"""

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def _to_series(equity: List[Dict[str, Any]]) -> pd.Series:
    """Convert equity records to a pandas Series indexed by step."""
    if not equity:
        return pd.Series(dtype=float)
    df = pd.DataFrame(equity)
    if "step" in df.columns:
        return pd.Series(df["equity"].values, index=df["step"].values)
    return pd.Series(df["equity"].values)


def compute_drawdown(equity: np.ndarray) -> Tuple[np.ndarray, float]:
    """Return drawdown series (negative) and maximum drawdown (positive)."""
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    max_dd = float(np.min(dd))  # most negative
    return dd, abs(max_dd)


def compute_equity_metrics(equity: List[Dict[str, Any]], risk_free: float = 0.0) -> Dict[str, Any]:
    """Classic risk-adjusted metrics from an equity curve."""
    s = _to_series(equity)
    if s.empty or len(s) < 2:
        return {}

    values = s.values.astype(float)
    rets = np.diff(values) / values[:-1]

    if len(rets) == 0 or not np.isfinite(rets).any():
        return {}

    total_return = float(values[-1] / values[0] - 1.0)
    annual_factor = 252.0
    periods = len(rets)

    # Assume each equity point is one trading period; CAGR if period count known.
    cagr = (1.0 + total_return) ** (annual_factor / max(periods, 1)) - 1.0

    mean_ret = float(np.mean(rets))
    std_ret = float(np.std(rets, ddof=1)) if periods > 1 else 0.0
    volatility = std_ret * np.sqrt(annual_factor) if std_ret > 0 else 0.0

    excess = rets - risk_free / annual_factor
    sharpe = float(np.mean(excess) / (np.std(excess, ddof=1) + 1e-12) * np.sqrt(annual_factor))

    downside = rets[rets < 0]
    sortino = float(
        np.mean(excess) / (np.std(downside, ddof=1) + 1e-12) * np.sqrt(annual_factor)
        if downside.size and np.std(downside, ddof=1) > 0
        else 0.0
    )

    _, max_dd = compute_drawdown(values)

    calmar = cagr / max_dd if max_dd > 0 else 0.0

    positive = rets[rets > 0]
    negative = rets[rets < 0]
    win_rate_periods = float(positive.size / rets.size) if rets.size else 0.0

    return {
        "total_return_pct": round(total_return * 100, 4),
        "cagr_pct": round(cagr * 100, 4),
        "volatility_pct": round(volatility * 100, 4),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "max_drawdown_pct": round(max_dd * 100, 4),
        "calmar": round(calmar, 4),
        "win_rate_periods": round(win_rate_periods * 100, 4),
        "num_periods": periods,
        "final_equity": round(float(values[-1]), 4),
    }


def compute_rolling_metrics(equity: List[Dict[str, Any]], window: int = 20) -> Dict[str, List[float]]:
    """Rolling Sharpe and drawdown over the equity curve."""
    s = _to_series(equity)
    if s.empty or len(s) < window + 1:
        return {"sharpe": [], "drawdown": []}

    values = pd.Series(s.values.astype(float))
    rets = values.pct_change().dropna()
    if rets.empty:
        return {"sharpe": [], "drawdown": []}

    rolling_mean = rets.rolling(window=window, min_periods=window).mean()
    rolling_std = rets.rolling(window=window, min_periods=window).std()
    rolling_sharpe = (rolling_mean / (rolling_std + 1e-12) * np.sqrt(252)).fillna(0)

    rolling_peak = values.expanding(min_periods=1).max()
    rolling_dd = ((values - rolling_peak) / rolling_peak).fillna(0).tolist()

    return {
        "sharpe": [round(float(v), 4) if np.isfinite(v) else 0.0 for v in rolling_sharpe.tolist()],
        "drawdown": [round(float(v) * 100, 4) for v in rolling_dd],
    }


def reconstruct_trades(trades: List[Dict[str, Any]], close: Optional[np.ndarray] = None) -> List[Dict[str, Any]]:
    """Build a richer trade history with PnL and holding period.

    The dashboard backtest records each directional change (BUY/SELL) as a
    single action row. We treat a trade as a completed round-turn when the
    position flips sign or goes back to flat.
    """
    if not trades:
        return []

    closed: List[Dict[str, Any]] = []
    position = 0
    entry: Optional[Dict[str, Any]] = None

    for i, t in enumerate(trades):
        action = str(t.get("action", "")).upper()
        price = float(t.get("price", 0) or 0)
        step = int(t.get("step", i))

        if action == "BUY":
            new_position = 1
        elif action == "SELL":
            new_position = -1
        else:
            new_position = 0

        if position == 0:
            entry = {"side": action, "entry_step": step, "entry_price": price}
        elif position != new_position:
            # Close the prior position at this price
            if entry:
                side = entry["side"]
                direction = 1 if side == "BUY" else -1
                pnl_pct = direction * (price - entry["entry_price"]) / max(entry["entry_price"], 1e-9) * 100
                closed.append(
                    {
                        "side": side,
                        "entry_step": entry["entry_step"],
                        "exit_step": step,
                        "entry_price": round(entry["entry_price"], 4),
                        "exit_price": round(price, 4),
                        "pnl_pct": round(pnl_pct, 4),
                        "holding_periods": int(step - entry["entry_step"]),
                    }
                )
            if new_position != 0:
                entry = {"side": action, "entry_step": step, "entry_price": price}
            else:
                entry = None

        position = new_position

    # Open trade
    if position != 0 and entry:
        last_price = entry["entry_price"]
        if close is not None and len(close):
            last_price = float(close[-1])
        side = entry["side"]
        direction = 1 if side == "BUY" else -1
        pnl_pct = direction * (last_price - entry["entry_price"]) / max(entry["entry_price"], 1e-9) * 100
        closed.append(
            {
                "side": side,
                "entry_step": entry["entry_step"],
                "exit_step": None,
                "entry_price": round(entry["entry_price"], 4),
                "exit_price": round(last_price, 4),
                "pnl_pct": round(pnl_pct, 4),
                "holding_periods": None,
                "open": True,
            }
        )

    return closed


def trade_statistics(trades: List[Dict[str, Any]], close: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """Summary statistics for round-turn trades."""
    closed_trades = reconstruct_trades(trades, close)
    finished = [t for t in closed_trades if not t.get("open")]
    if not finished:
        return {"total_trades": len(closed_trades), "closed_trades": 0}

    pnls = np.array([t["pnl_pct"] for t in finished])
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]

    gross_profit = float(np.sum(wins)) if wins.size else 0.0
    gross_loss = float(abs(np.sum(losses))) if losses.size else 0.0

    return {
        "total_trades": len(closed_trades),
        "closed_trades": len(finished),
        "win_rate": round(float((wins.size / pnls.size) * 100), 4) if pnls.size else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss > 0 else ("inf" if gross_profit > 0 else 0.0),
        "avg_trade_pct": round(float(np.mean(pnls)), 4),
        "avg_win_pct": round(float(np.mean(wins)), 4) if wins.size else 0.0,
        "avg_loss_pct": round(float(np.mean(losses)), 4) if losses.size else 0.0,
        "best_trade_pct": round(float(np.max(pnls)), 4),
        "worst_trade_pct": round(float(np.min(pnls)), 4),
        "total_pnl_pct": round(float(np.sum(pnls)), 4),
        "trades": closed_trades,
    }


def benchmark_metrics(close: np.ndarray, initial_equity: float = 1.0) -> Dict[str, Any]:
    """Buy-and-hold benchmark metrics for the same price window."""
    if close is None or len(close) < 2:
        return {}
    close = np.asarray(close, dtype=float)
    equity = initial_equity * (close / close[0])
    total_return = float(close[-1] / close[0] - 1.0)
    rets = np.diff(close) / close[:-1]
    sharpe = float(np.mean(rets) / (np.std(rets, ddof=1) + 1e-12) * np.sqrt(252))
    _, max_dd = compute_drawdown(equity)
    return {
        "total_return_pct": round(total_return * 100, 4),
        "sharpe": round(sharpe, 4),
        "max_drawdown_pct": round(max_dd * 100, 4),
        "equity": [round(float(v), 4) for v in equity.tolist()],
    }


def compute_result_analytics(
    equity: List[Dict[str, Any]],
    trades: List[Dict[str, Any]],
    close: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Full analytics bundle for the dashboard Results tab."""
    metrics = compute_equity_metrics(equity)
    rolling = compute_rolling_metrics(equity)
    tstats = trade_statistics(trades, close)
    bench = benchmark_metrics(close, initial_equity=equity[0]["equity"] if equity else 1.0) if close is not None else {}

    alpha_vs_benchmark = None
    if bench and metrics:
        alpha_vs_benchmark = round(metrics["total_return_pct"] - bench["total_return_pct"], 4)

    return {
        "metrics": metrics,
        "rolling": rolling,
        "trades": tstats,
        "benchmark": bench,
        "alpha_vs_benchmark_pct": alpha_vs_benchmark,
    }
