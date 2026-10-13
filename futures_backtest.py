import requests, json, math

CONFIG = {
    "initial_capital": 10000,
    "risk_per_trade_pct": 1.0,
    "max_drawdown_pct": 20.0,
    "atr_period": 14,
    "atr_multiplier": 2.0,
    "ema_trend": 200,
    "ema_trail": 21,
    "breakout_period": 10,
    "target_1_r": 2.0,
    "target_2_r": 3.0,
    "commission_pct": 0.055,
    "slippage_pct": 0.05,
    "leverage": 1,
    "symbols": [
        "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
        "ADAUSDT","DOGEUSDT","AVAXUSDT","DOTUSDT","LINKUSDT",
        "MATICUSDT","UNIUSDT","ATOMUSDT","LTCUSDT","NEARUSDT",
        "AAVEUSDT","FILUSDT","SANDUSDT","MANAUSDT","ALGOUSDT",
        "APTUSDT","ARBUSDT","OPUSDT","INJUSDT","SUIUSDT",
        "SEIUSDT","TIAUSDT","WLDUSDT","PYTHUSDT","STXUSDT","FETUSDT","RENDERUSDT","JUPUSDT","WIFUSDT","BONKUSDT","PENDLEUSDT","EIGENUSDT","ENAUSDT","NOTUSDT","ZROUSDT","IOUSDT","MEWUSDT","ZKUSDT","REZUSDT","LISTAUSDT"
    ],
    "interval": "60",
    "limit": 1500,
}

def std(vals):
    if len(vals) < 2: return 1.0
    m = sum(vals) / len(vals)
    return math.sqrt(sum((x - m) ** 2 for x in vals) / len(vals))

def fetch_klines(symbol, interval="60", limit=1000, start_ms=None, end_ms=None):
    url = "https://api.bybit.com/v5/market/kline"
    result = []
    current_end = end_ms
    while len(result) < limit:
        batch_size = min(1000, limit - len(result))
        params = {"category":"linear","symbol":symbol,"interval":interval,"limit":batch_size}
        if current_end: params["end"] = current_end
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if data["retCode"] != 0: raise RuntimeError(data["retMsg"])
        rows = data["result"]["list"]
        if not rows: break
        batch = [{"ts":int(row[0]),"open":float(row[1]),"high":float(row[2]),
                  "low":float(row[3]),"close":float(row[4]),"volume":float(row[5])} for row in rows]
        result.extend(batch)
        if len(batch) < batch_size: break
        current_end = min(b["ts"] for b in batch) - 1
        if start_ms and current_end < start_ms: break
    seen = set(); dedup = []
    for r in sorted(result, key=lambda x: x["ts"]):
        if r["ts"] not in seen:
            seen.add(r["ts"]); dedup.append(r)
    if start_ms: dedup = [r for r in dedup if r["ts"] >= start_ms]
    if end_ms:   dedup = [r for r in dedup if r["ts"] <= end_ms]
    return dedup

def calc_atr(candles, period=14):
    atrs = [None] * len(candles)
    trs = []
    for i in range(1, len(candles)):
        trs.append(max(
            candles[i]["high"] - candles[i]["low"],
            abs(candles[i]["high"] - candles[i-1]["close"]),
            abs(candles[i]["low"]  - candles[i-1]["close"])
        ))
    if len(trs) >= period:
        atrs[period] = sum(trs[:period]) / period
        k = 2 / (period + 1)
        for i in range(period, len(trs)):
            atrs[i+1] = trs[i] * k + atrs[i] * (1 - k)
    return atrs

def calc_ema(candles, period):
    emas   = [None] * len(candles)
    closes = [c["close"] for c in candles]
    if len(closes) < period: return emas
    emas[period-1] = sum(closes[:period]) / period
    k = 2 / (period + 1)
    for i in range(period, len(closes)):
        emas[i] = closes[i] * k + emas[i-1] * (1 - k)
    return emas

def cost(price, qty, cfg):
    return price * qty * ((cfg["commission_pct"] + cfg["slippage_pct"]) / 100)

def get_btc_daily_ema200():
    r = requests.get("https://api.bybit.com/v5/market/kline",
        params={"category":"linear","symbol":"BTCUSDT","interval":"D","limit":250}, timeout=15)
    data = r.json()
    if data["retCode"] != 0: return {}
    candles = []
    for row in sorted(data["result"]["list"], key=lambda x: int(x[0])):
        candles.append({"ts":int(row[0]),"close":float(row[4])})
    emas = [None]*len(candles)
    closes = [c["close"] for c in candles]
    if len(closes) >= 200:
        emas[199] = sum(closes[:200])/200
        k = 2/201
        for i in range(200, len(closes)):
            emas[i] = closes[i]*k + emas[i-1]*(1-k)
    btc_trend = {}
    for i, c in enumerate(candles):
        if emas[i] is not None:
            day_ts = (c["ts"] // 86400000) * 86400000
            btc_trend[day_ts] = c["close"] > emas[i]
    return btc_trend


if __name__ == "__main__":
    BTC_TREND = get_btc_daily_ema200()
    print("  BTC тренд загружен: " + str(len(BTC_TREND)) + " дней")
    
    def run_backtest(symbol, cfg, start_capital):
        try:
            candles = fetch_klines(symbol, cfg["interval"], cfg["limit"], cfg.get("start_ms"), cfg.get("end_ms"))
        except Exception as e:
            return [], start_capital, start_capital
        n         = len(candles)
        atrs      = calc_atr(candles, cfg["atr_period"])
        ema_trend = calc_ema(candles, cfg["ema_trend"])
        ema_trail = calc_ema(candles, cfg["ema_trail"])
        bp        = cfg["breakout_period"]
        capital   = float(start_capital)
        peak_cap  = capital
        trades    = []
        pos       = None
    
        for i in range(max(cfg["ema_trend"], bp) + 1, n):
            c     = candles[i]
            atr   = atrs[i]
            et    = ema_trend[i]
            etr   = ema_trail[i]
            if atr is None or et is None or etr is None: continue
    
    
            if pos:
                entry = pos["entry"]
                pr    = pos["price_risk"]
                side  = pos.get("side","long")
    
                if side == "long":
                    # Цель 1
                    if not pos["t1_done"] and c["high"] >= entry + cfg["target_1_r"] * pr:
                        ep = entry + cfg["target_1_r"] * pr
                        qc = pos["qty"] * 0.50
                        pnl = qc * (ep - entry) - cost(ep, qc, cfg)
                        capital += pnl; pos["qty"] -= qc
                        pos["t1_done"] = True; pos["pnl"] += pnl
                    # Цель 2
                    if pos["t1_done"] and not pos["t2_done"] and c["high"] >= entry + cfg["target_2_r"] * pr:
                        ep = entry + cfg["target_2_r"] * pr
                        qc = pos["qty"] * 0.60
                        pnl = qc * (ep - entry) - cost(ep, qc, cfg)
                        capital += pnl; pos["qty"] -= qc
                        pos["t2_done"] = True; pos["pnl"] += pnl
                    # Трейлинг
                    if pos["t1_done"] and etr > pos["trail_stop"]:
                        pos["trail_stop"] = etr
                    eff_stop = max(pos["stop"], pos["trail_stop"]) if pos["t1_done"] else pos["stop"]
                    if c["low"] <= eff_stop:
                        ep = eff_stop
                        pnl = pos["qty"] * (ep - entry) - cost(ep, pos["qty"], cfg)
                        capital += pnl; pos["pnl"] += pnl
                        r_mult = round(pos["pnl"] / pos["risk_usd"], 2) if pos["risk_usd"] else 0
                        trades.append({"symbol":symbol,"side":"long","entry":round(entry,4),"exit":round(ep,4),
                                       "pnl":round(pos["pnl"],2),"r":r_mult,"capital":round(capital,2)})
                        if capital > peak_cap: peak_cap = capital
                        pos = None
    
                else:  # SHORT
                    # Цель 1
                    if not pos["t1_done"] and c["low"] <= entry - cfg["target_1_r"] * pr:
                        ep = entry - cfg["target_1_r"] * pr
                        qc = pos["qty"] * 0.50
                        pnl = qc * (entry - ep) - cost(ep, qc, cfg)
                        capital += pnl; pos["qty"] -= qc
                        pos["t1_done"] = True; pos["pnl"] += pnl
                    # Цель 2
                    if pos["t1_done"] and not pos["t2_done"] and c["low"] <= entry - cfg["target_2_r"] * pr:
                        ep = entry - cfg["target_2_r"] * pr
                        qc = pos["qty"] * 0.60
                        pnl = qc * (entry - ep) - cost(ep, qc, cfg)
                        capital += pnl; pos["qty"] -= qc
                        pos["t2_done"] = True; pos["pnl"] += pnl
                    # Трейлинг шорт
                    if pos["t1_done"] and etr < pos["trail_stop"]:
                        pos["trail_stop"] = etr
                    eff_stop = min(pos["stop"], pos["trail_stop"]) if pos["t1_done"] else pos["stop"]
                    if c["high"] >= eff_stop:
                        ep = eff_stop
                        pnl = pos["qty"] * (entry - ep) - cost(ep, pos["qty"], cfg)
                        capital += pnl; pos["pnl"] += pnl
                        r_mult = round(pos["pnl"] / pos["risk_usd"], 2) if pos["risk_usd"] else 0
                        trades.append({"symbol":symbol,"side":"short","entry":round(entry,4),"exit":round(ep,4),
                                       "pnl":round(pos["pnl"],2),"r":r_mult,"capital":round(capital,2)})
                        if capital > peak_cap: peak_cap = capital
                        pos = None
    
            elif pos is None:
                prev = candles[i-1]
                dd = (peak_cap - capital) / peak_cap * 100
                if dd >= cfg["max_drawdown_pct"]: continue
    
                # LONG — пробой вверх, цена выше EMA200
                rh = [candles[j]["high"] for j in range(i - bp - 1, i - 1)]
                rl = [candles[j]["low"]  for j in range(i - bp - 1, i - 1)]
    
                day_key = (c["ts"] // 86400000) * 86400000
                btc_bull = BTC_TREND.get(day_key, True)
                if btc_bull and prev["close"] > et and prev["high"] > max(rh):
                    ep = c["open"]
                    sp = ep - cfg["atr_multiplier"] * atr
                    ru = capital * (cfg["risk_per_trade_pct"] / 100)
                    pr = abs(ep - sp)
                    if pr > 0:
                        qty = ru / pr
                        capital -= cost(ep, qty, cfg)
                        pos = {"side":"long","entry":ep,"stop":sp,"trail_stop":sp,"qty":qty,
                               "risk_usd":ru,"price_risk":pr,"pnl":0.0,"t1_done":False,"t2_done":False}
    
    
    
    
    
            if capital > peak_cap: peak_cap = capital
    
        return trades, capital, peak_cap
    
    all_trades = []
    capital    = float(CONFIG["initial_capital"])
    peak_cap   = capital
    S = "=" * 58
    D = "-" * 58
    
    print("")
    print(S)
    print("  Van Tharp FUTURES Backtest  |  Linear  |  1x (без плеч)")
    print("  Комиссия: 0.055% + Проскальзывание: 0.05%")
    print("  30 пар  |  Вход: open следующей свечи")
    print(S)
    
    for sym in CONFIG["symbols"]:
        print("  Загружаю " + sym + "...")
        try:
            trades, capital, peak_cap = run_backtest(sym, CONFIG, capital)
            all_trades.extend(trades)
            print("  " + sym + " OK | сделок: " + str(len(trades)) + " | капитал: $" + str(round(capital, 2)))
        except Exception as e:
            print("  ОШИБКА " + sym + ": " + str(e))
    
    print("")
    
    if not all_trades:
        print("  Сделок нет.")
    else:
        rs        = [t["r"] for t in all_trades]
        winners   = [r for r in rs if r > 0]
        losers    = [r for r in rs if r <= 0]
        n         = len(rs)
        wr        = len(winners) / n
        aw        = sum(winners) / len(winners) if winners else 0
        al        = abs(sum(losers) / len(losers)) if losers else 0
        er        = wr * aw - (1 - wr) * al
        sq        = (er / std(rs)) * math.sqrt(n)
        ic        = CONFIG["initial_capital"]
        rp        = (capital - ic) / ic * 100
        tp        = sum(t["pnl"] for t in all_trades)
        gw        = sum(t["pnl"] for t in all_trades if t["pnl"] > 0)
        gl        = abs(sum(t["pnl"] for t in all_trades if t["pnl"] < 0))
        pf        = round(gw / gl, 2) if gl > 0 else 999
        caps      = [ic] + [t["capital"] for t in all_trades]
        pk = ic; md = 0.0
        for c in caps:
            if c > pk: pk = c
            dd = (pk - c) / pk * 100
            if dd > md: md = dd
        sg = ("Плохая" if sq < 1 else "Нейтральная" if sq < 2 else
              "Хорошая" if sq < 3 else "Отличная" if sq < 5 else "Превосходная")
    
        print(S)
        print("  ИТОГОВЫЙ ОТЧЕТ (Futures Linear 1x)")
        print(S)
        print("  Начальный капитал : $" + "{:,.2f}".format(ic))
        print("  Итоговый капитал  : $" + "{:,.2f}".format(capital))
        print("  Доходность        : " + "{:+.2f}".format(rp) + "%")
        print("  Общий PnL         : $" + "{:+,.2f}".format(tp))
        print(D)
        print("  Всего сделок      : " + str(n))
        print("  Win Rate          : " + str(round(wr * 100, 1)) + "%")
        print("  Profit Factor     : " + str(pf))
        print("  Avg Win           : " + str(round(aw, 2)) + "R")
        print("  Avg Loss          : " + str(round(al, 2)) + "R")
        print(D)
        print("  Expectancy        : " + str(round(er, 3)) + "R / сделку")
        print("  SQN               : " + str(round(sq, 2)) + "  ->  " + sg)
        print("  Макс просадка     : -" + str(round(md, 2)) + "%")
        print(S)
    
        top = sorted(all_trades, key=lambda x: x["pnl"], reverse=True)[:5]
        print("  ТОП-5 лучших:")
        for t in top:
            print("    " + t["symbol"] + "  " + str(t["r"]) + "R  $" + "{:+,.2f}".format(t["pnl"]))
        print("")
        bot = sorted(all_trades, key=lambda x: x["pnl"])[:5]
        print("  ТОП-5 худших:")
        for t in bot:
            print("    " + t["symbol"] + "  " + str(t["r"]) + "R  $" + "{:+,.2f}".format(t["pnl"]))
        print(S)
    
        with open("futures_results.json", "w") as f:
            json.dump({"metrics":{"initial_capital":ic,"final_capital":round(capital,2),
                "return_pct":round(rp,2),"total_pnl_usd":round(tp,2),"total_trades":n,
                "win_rate_pct":round(wr*100,1),"profit_factor":pf,"avg_win_R":round(aw,2),
                "avg_loss_R":round(al,2),"expectancy_R":round(er,3),"sqn":round(sq,2),
                "sqn_grade":sg,"max_drawdown_pct":round(md,2)},
                "trades":all_trades}, f, indent=2, ensure_ascii=False)
        print("  Сохранено -> futures_results.json")
        print(S)
    