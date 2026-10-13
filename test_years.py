import requests, json, sys

exec(open('futures_backtest.py').read().split('print("="*58)')[0])

periods = {
    "2023": (1672531200000, 1704067199000),
    "2024": (1704067200000, 1735689599000),
    "2025": (1735689600000, 1767225599000),
}

for year, (start_ms, end_ms) in periods.items():
    cfg = dict(CONFIG)
    cfg["start_ms"] = start_ms
    cfg["end_ms"]   = end_ms
    cfg["limit"]    = 9999
    all_trades = []
    for sym in cfg["symbols"]:
        try:
            t = run_backtest(sym, cfg, cfg["initial_capital"])
            all_trades.extend(t)
        except Exception as e:
            pass
    if not all_trades:
        print(f"{year}: нет данных")
        continue
    total_pnl = sum(t["pnl"] for t in all_trades)
    wins = [t for t in all_trades if t["pnl"] > 0]
    rs = [t["r"] for t in all_trades]
    avg_r = sum(rs)/len(rs)
    std_r = (sum((r-avg_r)**2 for r in rs)/len(rs))**0.5
    sqn = (avg_r/std_r)*(len(rs)**0.5) if std_r else 0
    wr = 100*len(wins)/len(all_trades)
    print(f"{year}: PnL=${total_pnl:+.0f}  сделок={len(all_trades)}  SQN={sqn:.2f}  WR={wr:.1f}%")
