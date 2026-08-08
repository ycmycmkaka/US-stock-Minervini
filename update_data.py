import json
import math
import time
from pathlib import Path

import pandas as pd
import requests
from yahooquery import Ticker


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
RESULTS_PATH = BASE_DIR / "results.json"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_us_symbols():
    """Return listed US common-stock symbols from Nasdaq Trader files.

    ETFs and test issues are excluded so the scanner is focused on operating companies.
    """
    headers = {"User-Agent": "Mozilla/5.0"}

    url1 = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
    r1 = requests.get(url1, headers=headers, timeout=30)
    r1.raise_for_status()
    df1 = pd.read_csv(pd.io.common.StringIO(r1.text), sep="|")
    df1 = df1[df1["Symbol"] != "File Creation Time"].copy()
    if "ETF" in df1.columns:
        df1 = df1[df1["ETF"].fillna("N") == "N"]
    if "Test Issue" in df1.columns:
        df1 = df1[df1["Test Issue"].fillna("N") == "N"]
    df1 = df1[["Symbol"]].copy()
    df1["listing_exchange"] = "NASDAQ"

    url2 = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
    r2 = requests.get(url2, headers=headers, timeout=30)
    r2.raise_for_status()
    df2 = pd.read_csv(pd.io.common.StringIO(r2.text), sep="|")
    df2 = df2[df2["ACT Symbol"] != "File Creation Time"].copy()
    if "ETF" in df2.columns:
        df2 = df2[df2["ETF"].fillna("N") == "N"]
    if "Test Issue" in df2.columns:
        df2 = df2[df2["Test Issue"].fillna("N") == "N"]
    df2 = df2.rename(columns={"ACT Symbol": "Symbol", "Exchange": "listing_exchange"})
    df2 = df2[["Symbol", "listing_exchange"]].copy()

    exchange_map = {
        "N": "NYSE",
        "A": "NYSE American",
        "P": "NYSE Arca",
        "Z": "Cboe BZX",
        "V": "IEX",
    }
    df2["listing_exchange"] = (
        df2["listing_exchange"].map(exchange_map).fillna(df2["listing_exchange"])
    )

    df = pd.concat([df1, df2], ignore_index=True)
    df = df.dropna(subset=["Symbol"])
    df["Symbol"] = df["Symbol"].astype(str).str.strip()

    # Exclude preferreds, warrants and symbols Yahoo commonly cannot resolve cleanly.
    df = df[~df["Symbol"].str.contains(r"[\^\$]", regex=True)]
    df = df[~df["Symbol"].str.contains(r"\.", regex=True)]
    df = df.drop_duplicates(subset=["Symbol"]).reset_index(drop=True)
    return df


def normalize_number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def fetch_quote_metadata(symbols, config):
    """Fetch market cap/name/exchange first, then keep only large caps.

    This two-stage process avoids downloading 15 months of history for thousands of
    tiny stocks that would later be rejected by the market-cap filter.
    """
    batch_size = int(config.get("batch_size_quotes", 100))
    min_cap = float(config["market_cap_min"])
    metadata = {}

    for start in range(0, len(symbols), batch_size):
        batch = symbols[start : start + batch_size]
        try:
            q = Ticker(batch, asynchronous=True, max_workers=8)
            price_data = q.price
        except Exception as exc:
            print(f"Quote batch failed {start}-{start + len(batch)}: {exc}")
            time.sleep(1)
            continue

        if not isinstance(price_data, dict):
            continue

        for symbol in batch:
            info = price_data.get(symbol, {})
            if not isinstance(info, dict):
                continue

            market_cap = normalize_number(info.get("marketCap"))
            if market_cap is None or market_cap < min_cap:
                continue

            metadata[symbol] = {
                "market_cap": market_cap,
                "company": info.get("shortName") or info.get("longName") or symbol,
                "exchange": info.get("exchangeName") or info.get("fullExchangeName") or "",
            }

        time.sleep(0.1)

    return metadata


def normalize_history(history):
    if history is None or not hasattr(history, "reset_index"):
        return pd.DataFrame()

    df = history.reset_index()
    if df.empty or "symbol" not in df.columns or "date" not in df.columns:
        return pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce").dt.tz_convert(None)
    df = df.dropna(subset=["date"])
    return df.sort_values(["symbol", "date"])


def fetch_histories(symbols, config):
    period = config.get("history_period", "15mo")
    batch_size = int(config.get("batch_size_history", 60))
    frames = []

    for start in range(0, len(symbols), batch_size):
        batch = symbols[start : start + batch_size]
        try:
            t = Ticker(batch, asynchronous=True, max_workers=8)
            hist = t.history(period=period, interval="1d")
            df = normalize_history(hist)
            if not df.empty:
                frames.append(df)
        except Exception as exc:
            print(f"History batch failed {start}-{start + len(batch)}: {exc}")
            time.sleep(1)
            continue

        time.sleep(0.1)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def pct_return_from_bars(closes: pd.Series, bars_back: int):
    if len(closes) <= bars_back:
        return None
    current = float(closes.iloc[-1])
    past = float(closes.iloc[-1 - bars_back])
    if past <= 0:
        return None
    return (current / past - 1.0) * 100.0


def percentile_rank(series: pd.Series):
    return series.rank(method="average", pct=True) * 100.0


def calculate_stock_metrics(symbol, stock_hist, meta, benchmark_returns, min_rows):
    stock_hist = stock_hist.dropna(subset=["close"]).sort_values("date").copy()
    closes = stock_hist["close"].astype(float).reset_index(drop=True)

    if len(closes) < min_rows:
        return None

    recent_close = float(closes.iloc[-1])

    ma50 = float(closes.rolling(50).mean().iloc[-1])
    ma150 = float(closes.rolling(150).mean().iloc[-1])
    ma200_series = closes.rolling(200).mean()
    ma200 = float(ma200_series.iloc[-1])
    ma200_21d_ago = float(ma200_series.iloc[-22]) if len(ma200_series) >= 222 else None

    trailing_52w = closes.iloc[-252:]
    high_52w = float(trailing_52w.max())
    low_52w = float(trailing_52w.min())

    ret_5d = pct_return_from_bars(closes, 5)
    ret_20d = pct_return_from_bars(closes, 20)
    ret_60d = pct_return_from_bars(closes, 60)
    ret_63d = pct_return_from_bars(closes, 63)
    ret_126d = pct_return_from_bars(closes, 126)
    ret_189d = pct_return_from_bars(closes, 189)
    ret_252d = pct_return_from_bars(closes, 252)

    needed = [ret_5d, ret_20d, ret_60d, ret_63d, ret_126d, ret_189d, ret_252d]
    if any(v is None for v in needed):
        return None

    # Custom momentum score. This is intentionally called "custom" RS rather than
    # IBD RS Rating: 40% weight on the latest quarter, then 20% on 6/9/12-month
    # cumulative performance. The percentile conversion is performed later across
    # the market-cap-eligible universe.
    rs_raw = (
        0.40 * ret_63d
        + 0.20 * ret_126d
        + 0.20 * ret_189d
        + 0.20 * ret_252d
    )

    rs_5d_vs_spy = ret_5d - benchmark_returns["ret_5d"]
    rs_20d_vs_spy = ret_20d - benchmark_returns["ret_20d"]
    rs_60d_vs_spy = ret_60d - benchmark_returns["ret_60d"]

    dist_from_high = (recent_close / high_52w - 1.0) * 100.0
    pct_above_low = (recent_close / low_52w - 1.0) * 100.0

    # Seven structural criteria. RS is added as criterion 8 after percentile ranking.
    structural_conditions = {
        "price_above_150_200": recent_close > ma150 and recent_close > ma200,
        "ma150_above_200": ma150 > ma200,
        "ma200_rising": ma200_21d_ago is not None and ma200 > ma200_21d_ago,
        "ma50_above_150_200": ma50 > ma150 and ma50 > ma200,
        "price_above_50": recent_close > ma50,
        "price_30pct_above_52w_low": recent_close >= low_52w * 1.30,
        "price_within_25pct_52w_high": recent_close >= high_52w * 0.75,
    }

    return {
        "symbol": symbol,
        "company": meta["company"],
        "exchange": meta["exchange"],
        "market_cap": meta["market_cap"],
        "recent_close": recent_close,
        "ma50": ma50,
        "ma150": ma150,
        "ma200": ma200,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "dist_from_52w_high_pct": dist_from_high,
        "pct_above_52w_low": pct_above_low,
        "five_day_return_pct": ret_5d,
        "twenty_day_return_pct": ret_20d,
        "sixty_day_return_pct": ret_60d,
        "rs_5d_vs_spy_pct": rs_5d_vs_spy,
        "rs_20d_vs_spy_pct": rs_20d_vs_spy,
        "rs_60d_vs_spy_pct": rs_60d_vs_spy,
        "custom_rs_raw": rs_raw,
        "structural_conditions": structural_conditions,
    }


def benchmark_metrics(history_df, benchmark_symbol):
    bh = history_df[history_df["symbol"] == benchmark_symbol].copy()
    if bh.empty:
        raise RuntimeError(f"No benchmark history returned for {benchmark_symbol}")
    closes = bh.dropna(subset=["close"]).sort_values("date")["close"].astype(float).reset_index(drop=True)

    values = {
        "ret_5d": pct_return_from_bars(closes, 5),
        "ret_20d": pct_return_from_bars(closes, 20),
        "ret_60d": pct_return_from_bars(closes, 60),
    }
    if any(v is None for v in values.values()):
        raise RuntimeError(f"Not enough benchmark history for {benchmark_symbol}")
    return values


def round_or_none(value, digits=1):
    n = normalize_number(value)
    return None if n is None else round(n, digits)


def build_results():
    config = load_config()
    benchmark_symbol = str(config.get("benchmark_symbol", "SPY")).upper()

    symbols_df = fetch_us_symbols()
    all_symbols = symbols_df["Symbol"].tolist()
    print(f"Listed non-ETF symbols: {len(all_symbols)}")

    metadata = fetch_quote_metadata(all_symbols, config)
    large_cap_symbols = sorted(metadata.keys())
    print(f"Market-cap eligible: {len(large_cap_symbols)}")

    # Include benchmark in the same history download so all returns are aligned to
    # the same trading calendar/data source.
    history_symbols = sorted(set(large_cap_symbols + [benchmark_symbol]))
    history_df = fetch_histories(history_symbols, config)
    if history_df.empty:
        raise RuntimeError("No history data returned; keeping previous results.json")

    benchmark = benchmark_metrics(history_df, benchmark_symbol)

    min_rows = int(config.get("min_history_rows", 260))
    metrics = []
    for symbol in large_cap_symbols:
        stock_hist = history_df[history_df["symbol"] == symbol]
        if stock_hist.empty:
            continue
        try:
            row = calculate_stock_metrics(
                symbol,
                stock_hist,
                metadata[symbol],
                benchmark,
                min_rows,
            )
            if row:
                metrics.append(row)
        except Exception as exc:
            print(f"Metric error {symbol}: {exc}")

    minimum_ok = int(config.get("minimum_data_eligible_stocks", 100))
    if len(metrics) < minimum_ok:
        raise RuntimeError(
            f"Only {len(metrics)} stocks had usable history (< {minimum_ok}); "
            "refusing to overwrite results.json because the data source may be incomplete."
        )

    df = pd.DataFrame(metrics)
    df["rs_rating"] = percentile_rank(df["custom_rs_raw"]).round(0)

    # Add RS as the eighth Minervini-style trend-template criterion.
    min_template_rs = 70.0
    template_passes = []
    template_scores = []
    for idx, row in df.iterrows():
        conditions = dict(row["structural_conditions"])
        conditions["rs_rating_70_plus"] = float(row["rs_rating"]) >= min_template_rs
        score = sum(bool(v) for v in conditions.values())
        template_scores.append(score)
        template_passes.append(score == 8)
        df.at[idx, "structural_conditions"] = conditions

    df["trend_template_score"] = template_scores
    df["trend_template_pass"] = template_passes

    # Practical final screen: full template + stronger RS + positive medium-term
    # relative performance + not too extended from the 52-week high.
    min_rs = float(config.get("min_rs_rating", 80))
    min_rel20 = float(config.get("min_rs_20d_vs_spy_pct", 0))
    min_rel60 = float(config.get("min_rs_60d_vs_spy_pct", 0))
    max_from_high = float(config.get("max_dist_from_52w_high_pct", 15))

    final_mask = (
        (df["trend_template_pass"])
        & (df["rs_rating"] >= min_rs)
        & (df["rs_20d_vs_spy_pct"] >= min_rel20)
        & (df["rs_60d_vs_spy_pct"] >= min_rel60)
        & (df["dist_from_52w_high_pct"] >= -max_from_high)
    )

    final_df = df[final_mask].copy()

    # Practical ranking: highest custom RS first, then stronger 60D/20D SPY-relative
    # performance, then proximity to the 52-week high.
    final_df = final_df.sort_values(
        ["rs_rating", "rs_60d_vs_spy_pct", "rs_20d_vs_spy_pct", "dist_from_52w_high_pct"],
        ascending=[False, False, False, False],
    )

    rows = []
    for _, row in final_df.iterrows():
        conditions = row["structural_conditions"]
        rows.append(
            {
                "symbol": row["symbol"],
                "company": row["company"],
                "exchange": row["exchange"],
                "market_cap": int(row["market_cap"]),
                "recent_close": round_or_none(row["recent_close"], 2),
                "trend_template_score": int(row["trend_template_score"]),
                "trend_template_pass": bool(row["trend_template_pass"]),
                "rs_rating": int(row["rs_rating"]),
                "five_day_return_pct": round_or_none(row["five_day_return_pct"], 1),
                "twenty_day_return_pct": round_or_none(row["twenty_day_return_pct"], 1),
                "sixty_day_return_pct": round_or_none(row["sixty_day_return_pct"], 1),
                "rs_5d_vs_spy_pct": round_or_none(row["rs_5d_vs_spy_pct"], 1),
                "rs_20d_vs_spy_pct": round_or_none(row["rs_20d_vs_spy_pct"], 1),
                "rs_60d_vs_spy_pct": round_or_none(row["rs_60d_vs_spy_pct"], 1),
                "high_52w": round_or_none(row["high_52w"], 2),
                "low_52w": round_or_none(row["low_52w"], 2),
                "dist_from_52w_high_pct": round_or_none(row["dist_from_52w_high_pct"], 1),
                "pct_above_52w_low": round_or_none(row["pct_above_52w_low"], 1),
                "ma50": round_or_none(row["ma50"], 2),
                "ma150": round_or_none(row["ma150"], 2),
                "ma200": round_or_none(row["ma200"], 2),
                "template_conditions": conditions,
            }
        )

    output = {
        "generated_at": pd.Timestamp.now("UTC").strftime("%Y-%m-%d %H:%M UTC"),
        "method": "Minervini-style trend template + custom RS percentile + SPY relative strength",
        "rules": {
            "market_cap_min": config["market_cap_min"],
            "benchmark_symbol": benchmark_symbol,
            "trend_template_required_score": 8,
            "template_rs_rating_min": 70,
            "min_rs_rating": min_rs,
            "min_rs_20d_vs_spy_pct": min_rel20,
            "min_rs_60d_vs_spy_pct": min_rel60,
            "max_dist_from_52w_high_pct": max_from_high,
            "spy_five_day_return_pct": round_or_none(benchmark["ret_5d"], 1),
            "spy_twenty_day_return_pct": round_or_none(benchmark["ret_20d"], 1),
            "spy_sixty_day_return_pct": round_or_none(benchmark["ret_60d"], 1),
            "rs_definition": "Custom percentile rank across market-cap-eligible stocks using 40% 3M + 20% 6M + 20% 9M + 20% 12M cumulative returns; not the proprietary IBD RS Rating.",
        },
        "scan_stats": {
            "listed_non_etf_symbols": len(all_symbols),
            "market_cap_eligible": len(large_cap_symbols),
            "data_eligible": len(metrics),
            "trend_template_8_of_8": int(df["trend_template_pass"].sum()),
            "final_matches": len(rows),
        },
        "results": rows,
    }

    tmp_path = RESULTS_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    tmp_path.replace(RESULTS_PATH)

    print(
        f"Done. Data eligible={len(metrics)}, template 8/8={int(df['trend_template_pass'].sum())}, "
        f"final matches={len(rows)}"
    )


if __name__ == "__main__":
    build_results()
