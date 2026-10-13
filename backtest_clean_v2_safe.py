
import requests
import json
import math
import time
import random
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

CONFIG = {
    "initial_capital": 10_000.0,
    "risk_per_trade_pct": 1.0,
    "max_drawdown_pct": 20.0,

    "atr_period": 14,
    "stop_atr": 2.0,
    "take_profit_r": 3.0,

    "ema_trend": 200,
    "ema_slope_period": 20,

    "breakout_period": 20,

    "volume_filter": True,
    "volume_period": 20,
    "volume_multiplier": 1.5,

    "commission_pct": 0.055,
    "slippage_pct": 0.05,
    "funding_enabled": True,

    "interval": "60",
    "limit": 1500,

    "request_delay": 0.35,
    "symbol_delay": 2.0,

    "symbols": [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
        "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
        "LTCUSDT", "ATOMUSDT", "NEARUSDT", "AAVEUSDT", "FILUSDT",
        "UNIUSDT", "ARBUSDT", "OPUSDT", "INJUSDT", "SUIUSDT",
    ],
}

SESSION = requests.Session()

retry_strategy = Retry(
    total=5,
    connect=5,
    read=5,
    status=5,
    backoff_factor=2,
    status_forcelist=[408, 425, 429, 500, 502, 503, 504],
    allowed_methods=["GET"],
    respect_retry_after_header=True,
)

adapter = HTTPAdapter(
    pool_connections=10,
    pool_maxsize=10,
    max_retries=retry_strategy,
)

SESSION.mount("https://", adapter)
SESSION.mount("http://", adapter)


def safe_sleep(seconds):
    time.sleep(seconds + random.uniform(0, 0.25))


def http_get(url, params):
    for attempt in range(4):
        try:
            response = SESSION.get(
                url,
                params=params,
                timeout=(10, 30),
            )

            if response.status_code == 429:
                wait_time = 15 * (attempt + 1)
                print(f"    Rate limit. Жду {wait_time} сек...")
                safe_sleep(wait_time)
                continue

            response.raise_for_status()
            data = response.json()

            if data.get("retCode") != 0:
                message = data.get("retMsg", "Unknown Bybit error")

                if data.get("retCode") == 10006:
                    wait_time = 20 * (attempt + 1)
                    print(f"    Bybit rate limit. Жду {wait_time} сек...")
                    safe_sleep(wait_time)
                    continue

                raise RuntimeError(message)

            return data

        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ) as error:
            wait_time = 5 * (attempt + 1)
            print(f"    Сеть/API: {error}. Жду {wait_time} сек...")
            safe_sleep(wait_time)

        except json.JSONDecodeError as error:
            wait_time = 5 * (attempt + 1)
            print(f"    Некорректный ответ API. Жду {wait_time} сек...")
            safe_sleep(wait_time)

    raise RuntimeError("API недоступен после нескольких попыток")


def fetch_klines(symbol, interval, limit):
    url = "https://api.bybit.com/v5/market/kline"
    candles = []
    end_time = None

    while len(candles) < limit:
        batch_size = min(1000, limit - len(candles))
        params = {
            "category": "linear",
            "symbol": symbol,
            "interval": interval,
            "limit": batch_size,
        }

        if end_time is not None:
            params["end"] = end_time

        data = http_get(url, params)
        rows = data["result"]["list"]

        if not rows:
            break

        for row in rows:
            candles.append({
                "ts": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            })

        oldest_ts = min(item["ts"] for item in candles)

        if end_time is not None and oldest_ts >= end_time:
            break

        end_time = oldest_ts - 1

        if len(rows) < batch_size:
            break

        safe_sleep(CONFIG["request_delay"])

    unique = {}
    for candle in candles:
        unique[candle["ts"]] = candle

    candles = sorted(unique.values(), key=lambda item: item["ts"])
    return candles[-limit:]


def fetch_funding(symbol, start_ts, end_ts):
    if not CONFIG["funding_enabled"]:
        return []

    url = "https://api.bybit.com/v5/market/funding/history"
    funding = []
    cursor = None

    while True:
        params = {
            "category": "linear",
            "symbol": symbol,
            "startTime": start_ts,
            "endTime": end_ts,
            "limit": 200,
        }

        if cursor:
            params["cursor"] = cursor

        data = http_get(url, params)
        result = data["result"]
        rows = result.get("list", [])

        for row in rows:
            funding.append({
                "ts": int(row["fundingRateTimestamp"]),
                "rate": float(row["fundingRate"]),
            })

        cursor = result.get("nextPageCursor")

        if not cursor or not rows:
            break

        safe_sleep(CONFIG["request_delay"])

    return sorted(funding, key=lambda item: item["ts"])


def calc_atr(candles, period):
    atr = [None] * len(candles)
    true_ranges = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i - 1]

        true_range = max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"]),
        )

        true_ranges.append(true_range)

    if len(true_ranges) < period:
        return atr

    atr[period] = sum(true_ranges[:period]) / period
    smoothing = 2.0 / (period + 1)

    for i in range(period, len(true_ranges)):
        atr[i + 1] = (
            true_ranges[i] * smoothing
            + atr[i] * (1.0 - smoothing)
        )

    return atr


def calc_ema(values, period):
    ema = [None] * len(values)

    if len(values) < period:
        return ema

    ema[period - 1] = sum(values[:period]) / period
    smoothing = 2.0 / (period + 1)

    for i in range(period, len(values)):
        ema[i] = values[i] * smoothing + ema[i - 1] * (1.0 - smoothing)

    return ema


def get_btc_daily_trend():
    url = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "linear",
        "symbol": "BTCUSDT",
        "interval": "D",
        "limit": 400,
    }

    data = http_get(url, params)
    rows = data["result"]["list"]

    candles = []
    for row in rows:
        candles.append({
            "ts": int(row[0]),
            "close": float(row[4]),
        })

    candles.sort(key=lambda item: item["ts"])

    closes = [item["close"] for item in candles]
    ema200 = calc_ema(closes, 200)

    trend = {}

    for i, candle in enumerate(candles):
        if ema200[i] is not None:
            day = candle["ts"] // 86_400_000
            trend[day] = candle["close"] > ema200[i]

    return trend


def trade_cost(entry_price, exit_price, quantity):
    commission = CONFIG["commission_pct"] / 100.0
    slippage = CONFIG["slippage_pct"] / 100.0

    return (
        entry_price * quantity * commission
        + exit_price * quantity * commission
        + entry_price * quantity * slippage
        + exit_price * quantity * slippage
    )


def funding_cost(entry_ts, exit_ts, quantity, entry_price, funding_rates):
    if not CONFIG["funding_enabled"]:
        return 0.0

    cost = 0.0

    for item in funding_rates:
        if entry_ts < item["ts"] <= exit_ts:
            cost += item["rate"] * quantity * entry_price

    return cost


def run_backtest(symbol, config, start_capital):
    candles = fetch_klines(
        symbol,
        config["interval"],
        config["limit"],
    )

    minimum_bars = max(
        config["ema_trend"],
        config["breakout_period"],
        config["atr_period"],
        config["volume_period"],
        config["ema_slope_period"],
    ) + 5

    if len(candles) < minimum_bars:
        return [], start_capital

    closes = [item["close"] for item in candles]

    atr_values = calc_atr(candles, config["atr_period"])
    ema_trend_values = calc_ema(closes, config["ema_trend"])

    ema_trend_old_values = [None] * len(candles)

    for i in range(len(candles)):
        old_index = i - config["ema_slope_period"]

        if old_index >= 0:
            ema_trend_old_values[i] = ema_trend_values[old_index]

    volume_average = [None] * len(candles)

    if config["volume_filter"]:
        for i in range(config["volume_period"], len(candles)):
            volume_average[i] = sum(
                item["volume"]
                for item in candles[i - config["volume_period"]:i]
            ) / config["volume_period"]

    funding_rates = fetch_funding(
        symbol,
        candles[0]["ts"],
        candles[-1]["ts"],
    )

    capital = float(start_capital)
    peak_capital = capital
    trades = []
    position = None

    for i in range(minimum_bars, len(candles)):
        candle = candles[i]
        previous = candles[i - 1]

        atr = atr_values[i - 1]
        ema_trend = ema_trend_values[i - 1]
        ema_trend_old = ema_trend_old_values[i - 1]

        if atr is None or ema_trend is None or ema_trend_old is None:
            continue

        if position is not None:
            entry_price = position["entry"]
            price_risk = position["price_risk"]

            stop_price = position["stop"]
            take_profit_price = (
                entry_price
                + config["take_profit_r"] * price_risk
            )

            exit_price = None

            if candle["low"] <= stop_price:
                exit_price = stop_price
            elif candle["high"] >= take_profit_price:
                exit_price = take_profit_price

            if exit_price is not None:
                quantity = position["quantity"]

                gross_pnl = quantity * (exit_price - entry_price)
                fees = trade_cost(entry_price, exit_price, quantity)

                funding = funding_cost(
                    position["entry_ts"],
                    candle["ts"],
                    quantity,
                    entry_price,
                    funding_rates,
                )

                pnl = gross_pnl - fees - funding
                capital += pnl

                trades.append({
                    "symbol": symbol,
                    "side": "long",
                    "entry_time": position["entry_ts"],
                    "exit_time": candle["ts"],
                    "entry": entry_price,
                    "exit": exit_price,
                    "pnl": pnl,
                    "r": pnl / position["risk_usd"],
                })

                position = None

        if position is None:
            drawdown = (
                (peak_capital - capital) / peak_capital * 100.0
                if peak_capital > 0 else 0.0
            )

            if drawdown >= config["max_drawdown_pct"]:
                continue

            breakout_high = max(
                item["high"]
                for item in candles[
                    i - config["breakout_period"] - 1:i - 1
                ]
            )

            btc_day = candle["ts"] // 86_400_000
            btc_bull = BTC_TREND.get(btc_day, False)

            volume_ok = True

            if config["volume_filter"]:
                average_volume = volume_average[i - 1]
                volume_ok = (
                    average_volume is not None
                    and previous["volume"]
                    >= config["volume_multiplier"] * average_volume
                )

            ema_slope_ok = ema_trend > ema_trend_old

            long_signal = (
                btc_bull
                and previous["close"] > ema_trend
                and previous["close"] > breakout_high
                and volume_ok
                and ema_slope_ok
            )

            if long_signal:
                entry_price = candle["open"] * (
                    1.0 + config["slippage_pct"] / 100.0
                )

                stop_price = entry_price - config["stop_atr"] * atr
                price_risk = entry_price - stop_price

                if price_risk <= 0:
                    continue

                risk_usd = (
                    capital
                    * config["risk_per_trade_pct"]
                    / 100.0
                )

                quantity = risk_usd / price_risk

                if quantity <= 0:
                    continue

                entry_fees = trade_cost(
                    entry_price,
                    entry_price,
                    quantity,
                )

                capital -= entry_fees

                position = {
                    "symbol": symbol,
                    "side": "long",
                    "entry_ts": candle["ts"],
                    "entry": entry_price,
                    "stop": stop_price,
                    "quantity": quantity,
                    "risk_usd": risk_usd,
                    "price_risk": price_risk,
                }

        if capital > peak_capital:
            peak_capital = capital

    return trades, capital


def calculate_metrics(trades, initial_capital, final_capital):
    if not trades:
        return None

    r_values = [trade["r"] for trade in trades]
    winners = [value for value in r_values if value > 0]
    losers = [value for value in r_values if value <= 0]

    win_rate = len(winners) / len(r_values)
    average_win = sum(winners) / len(winners) if winners else 0.0
    average_loss = abs(sum(losers) / len(losers)) if losers else 0.0

    expectancy = (
        win_rate * average_win
        - (1.0 - win_rate) * average_loss
    )

    gross_profit = sum(
        trade["pnl"] for trade in trades if trade["pnl"] > 0
    )

    gross_loss = abs(sum(
        trade["pnl"] for trade in trades if trade["pnl"] < 0
    ))

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0 else float("inf")
    )

    variance = sum(
        (value - expectancy) ** 2 for value in r_values
    ) / len(r_values)

    standard_deviation = math.sqrt(variance) if variance > 0 else 1.0

    sqn = (
        expectancy / standard_deviation * math.sqrt(len(r_values))
        if standard_deviation > 0 else 0.0
    )

    return {
        "trades": len(trades),
        "win_rate_pct": win_rate * 100.0,
        "profit_factor": profit_factor,
        "expectancy_r": expectancy,
        "sqn": sqn,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "final_capital": final_capital,
        "return_pct": (
            (final_capital - initial_capital)
            / initial_capital * 100.0
        ),
    }


def print_report(metrics):
    line = "=" * 68
    dash = "-" * 68

    print()
    print(line)
    print("  CLEAN V2 SAFE | Bybit Linear | 1x | 1h")
    print("  Long only | BTC trend | Close breakout | Volume | EMA slope")
    print(line)

    if metrics is None:
        print("  Сделок нет.")
        print(line)
        return

    print(f"  Начальный капитал : ${CONFIG['initial_capital']:,.2f}")
    print(f"  Итоговый капитал  : ${metrics['final_capital']:,.2f}")
    print(f"  Доходность        : {metrics['return_pct']:+.2f}%")
    print(dash)
    print(f"  Всего сделок      : {metrics['trades']}")
    print(f"  Win Rate          : {metrics['win_rate_pct']:.1f}%")
    print(f"  Profit Factor     : {metrics['profit_factor']:.2f}")
    print(f"  Expectancy        : {metrics['expectancy_r']:+.3f}R")
    print(f"  SQN               : {metrics['sqn']:.2f}")
    print(line)


BTC_TREND = get_btc_daily_trend()
print(f"BTC дневной тренд загружен: {len(BTC_TREND)} дней")

capital = CONFIG["initial_capital"]
all_trades = []
failed_symbols = []

print()
print("Начинаю безопасный clean v2 бэктест...")

for symbol in CONFIG["symbols"]:
    print(f"Загружаю {symbol}...")

    try:
        trades, final_capital = run_backtest(
            symbol,
            CONFIG,
            capital,
        )

        all_trades.extend(trades)
        capital = final_capital

        print(
            f"{symbol} OK | сделок: {len(trades)} | "
            f"капитал: ${capital:,.2f}"
        )

    except Exception as error:
        failed_symbols.append(symbol)
        print(f"{symbol} ПРОПУЩЕН: {error}")

    safe_sleep(CONFIG["symbol_delay"])

metrics = calculate_metrics(
    all_trades,
    CONFIG["initial_capital"],
    capital,
)

print_report(metrics)

if failed_symbols:
    print("Пропущенные пары:")
    for symbol in failed_symbols:
        print(f"  - {symbol}")

with open("clean_v2_safe_results.json", "w", encoding="utf-8") as file:
    json.dump({
        "config": CONFIG,
        "metrics": metrics,
        "trades": all_trades,
        "failed_symbols": failed_symbols,
    }, file, indent=2, ensure_ascii=False, default=str)

print("Сохранено -> clean_v2_safe_results.json")
