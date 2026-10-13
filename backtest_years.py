import pandas as pd
import numpy as np

CONFIG = {
    "initial_capital": 10000,
    "risk_per_trade_pct": 1.0,
    "atr_period": 14,
    "atr_multiplier": 2.0,
    "ema_trend": 200,
    "breakout_period": 20,
    "target_1_r": 2.0,
    "target_2_r": 3.0,
    "commission_pct": 0.1,
    "slippage_pct": 0.05,
}

df = pd.read_csv("data/BTCUSDT_1h_2022_2025.csv")
df["open_time"] = pd.to_datetime(df["open_time"])
df = df.sort_values("open_time").reset_index(drop=True)

df["ema200"] = df["close"].ewm(span=CONFIG["ema_trend"], adjust=False).mean()
df["atr"] = np.maximum(
    df["high"] - df["low"],
    np.maximum(
        abs(df["high"] - df["close"].shift()),
        abs(df["low"] - df["close"].shift())
    )
).rolling(CONFIG["atr_period"]).mean()

df["highest"] = df["high"].rolling(CONFIG["breakout_period"]).max().shift(1)

trades = []
position = None

for i in range(1, len(df)):
    row = df.iloc[i]
    prev = df.iloc[i - 1]

    if position is None:
        if (
            prev["close"] > prev["highest"]
            and prev["close"] > prev["ema200"]
        ):
            entry = row["open"] * (1 + CONFIG["slippage_pct"] / 100)
            atr = prev["atr"]
            stop = entry - CONFIG["atr_multiplier"] * atr
            risk = entry - stop
            size = (CONFIG["initial_capital"] * CONFIG["risk_per_trade_pct"] / 100) / risk
            position = {
                "entry_time": row["open_time"],
                "entry": entry,
                "stop": stop,
                "risk": risk,
                "size": size,
                "year": row["open_time"].year,
            }
    else:
        low = row["low"]
        high = row["high"]

        exit_price = None
        result = None

        if low <= position["stop"]:
            exit_price = position["stop"]
            result = "loss"
        elif high >= position["entry"] + CONFIG["target_2_r"] * position["risk"]:
            exit_price = position["entry"] + CONFIG["target_2_r"] * position["risk"]
            result = "win"
        elif high >= position["entry"] + CONFIG["target_1_r"] * position["risk"]:
            position["stop"] = position["entry"]
            result = "breakeven_move"

        if exit_price is not None:
            gross = (exit_price - position["entry"]) * position["size"]
            fees = (position["entry"] + exit_price) * position["size"] * CONFIG["commission_pct"] / 100
            net = gross - fees
            r = net / (position["risk"] * position["size"])

            trades.append({
                "year": position["year"],
                "entry_time": position["entry_time"],
                "exit_time": row["open_time"],
                "r": r,
                "pnl": net,
                "result": result,
            })
            position = None

trades = pd.DataFrame(trades)

print("\n=== РЕЗУЛЬТАТЫ ПО ГОДАМ ===")
for year, g in trades.groupby("year"):
    wins = g[g["r"] > 0]
    losses = g[g["r"] <= 0]
    pf = wins["r"].sum() / abs(losses["r"].sum()) if len(losses) and losses["r"].sum() != 0 else float("inf")
    expectancy = g["r"].mean()
    print(f"\n{year}")
    print(f"Сделок: {len(g)}")
    print(f"Win rate: {len(wins) / len(g) * 100:.1f}%")
    print(f"Profit factor: {pf:.2f}")
    print(f"Expectancy: {expectancy:.2f}R")
    print(f"PnL: ${g['pnl'].sum():,.2f}")

print("\n=== ОБЩИЙ РЕЗУЛЬТАТ ===")
wins = trades[trades["r"] > 0]
losses = trades[trades["r"] <= 0]
pf = wins["r"].sum() / abs(losses["r"].sum()) if len(losses) and losses["r"].sum() != 0 else float("inf")
print(f"Всего сделок: {len(trades)}")
print(f"Win rate: {len(wins) / len(trades) * 100:.1f}%")
print(f"Profit factor: {pf:.2f}")
print(f"Expectancy: {trades['r'].mean():.2f}R")
print(f"Общий PnL: ${trades['pnl'].sum():,.2f}")
