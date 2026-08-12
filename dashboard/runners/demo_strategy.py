"""Sample Q-learning agent for the Modernise-TradeMaster dashboard.

This is a minimal RL pipeline: a discrete Q-table agent is trained on a
price series, then backtested. It produces metrics, an equity curve, and a
trade log so the dashboard can render a complete experiment result.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ACTIONS = [0, 1, 2]  # hold, long, short


def encode_state(diff: np.ndarray, n: int = 3) -> int:
    """Encode the last *n* signed returns as a base-3 integer."""
    state = 0
    for i, d in enumerate(diff[-n:]):
        digit = 1 if d > 0 else (2 if d < 0 else 0)
        state += digit * (3**i)
    return state


def train_q_table(returns: np.ndarray, episodes: int, lr: float, eps: float, gamma: float = 0.9, n: int = 3):
    q_table = np.zeros((3**n, len(ACTIONS)))
    for ep in range(episodes):
        for t in range(n, len(returns) - 1):
            state = encode_state(returns[t - n : t], n)
            if np.random.random() < eps:
                action = int(np.random.choice(ACTIONS))
            else:
                action = int(np.argmax(q_table[state]))

            next_state = encode_state(returns[t - n + 1 : t + 1], n)
            market_return = returns[t + 1]
            position = 0 if action == 0 else (1 if action == 1 else -1)
            reward = market_return * position

            q_table[state, action] += lr * (
                reward + gamma * np.max(q_table[next_state]) - q_table[state, action]
            )
    return q_table


def backtest(close: np.ndarray, returns: np.ndarray, q_table: np.ndarray, n: int = 3):
    equity = [1.0]
    trades = []
    position = 0
    for t in range(n, len(returns) - 1):
        state = encode_state(returns[t - n : t], n)
        action = int(np.argmax(q_table[state]))

        if action == 1 and position != 1:
            position = 1
            trades.append({"step": int(t), "action": "BUY", "price": float(close[t])})
        elif action == 2 and position != -1:
            position = -1
            trades.append({"step": int(t), "action": "SELL", "price": float(close[t])})

        ret = returns[t + 1] * position
        equity.append(equity[-1] * (1.0 + ret))

    return np.array(equity), trades


def compute_metrics(equity: np.ndarray) -> dict:
    total_return = float(equity[-1] - 1.0)
    daily_rets = np.diff(equity) / equity[:-1]
    sharpe = float(
        np.mean(daily_rets) / (np.std(daily_rets) + 1e-9) * np.sqrt(252)
    )
    running_max = np.maximum.accumulate(equity)
    drawdowns = (running_max - equity) / running_max
    max_drawdown = float(np.max(drawdowns))
    return {
        "total_return_pct": round(total_return * 100, 4),
        "sharpe": round(sharpe, 4),
        "max_drawdown_pct": round(max_drawdown * 100, 4),
        "final_equity": round(float(equity[-1]), 4),
    }


def main():
    parser = argparse.ArgumentParser(description="Run a Q-learning trading demo")
    parser.add_argument("--data", required=True, help="Path to CSV with a 'close' column")
    parser.add_argument("--output", required=True, help="Directory to write results")
    parser.add_argument("--episodes", type=int, default=200, help="Training episodes")
    parser.add_argument("--lr", type=float, default=0.1, help="Q-learning learning rate")
    parser.add_argument("--eps", type=float, default=0.1, help="Epsilon-greedy exploration")
    parser.add_argument("--gamma", type=float, default=0.9, help="Discount factor")
    parser.add_argument("--n", type=int, default=3, help="Number of return lags in state")
    args = parser.parse_args()

    df = pd.read_csv(args.data)
    if "close" not in df.columns:
        raise ValueError("Input CSV must contain a 'close' column")
    close = df["close"].dropna().astype(float).values
    if len(close) < args.n + 10:
        raise ValueError("Not enough close prices to run the demo")

    returns = np.diff(close) / close[:-1]
    print(f"Training Q-learning agent on {len(returns)} steps, {args.episodes} episodes...")

    q_table = train_q_table(returns, args.episodes, args.lr, args.eps, args.gamma, args.n)
    equity, trades = backtest(close, returns, q_table, args.n)
    metrics = compute_metrics(equity)
    metrics["num_trades"] = len(trades)
    metrics["data_points"] = len(close)

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    pd.DataFrame({"step": range(len(equity)), "equity": equity}).to_csv(
        out / "equity.csv", index=False
    )
    if trades:
        pd.DataFrame(trades).to_csv(out / "trades.csv", index=False)
    else:
        (out / "trades.csv").write_text("step,action,price\n")

    params = {
        "agent": "QTable",
        "episodes": args.episodes,
        "learning_rate": args.lr,
        "epsilon": args.eps,
        "gamma": args.gamma,
        "state_lags": args.n,
    }
    (out / "params.json").write_text(json.dumps(params, indent=2))
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))

    print("METRICS", json.dumps(metrics))
    print(f"Results written to {out}")


if __name__ == "__main__":
    main()
