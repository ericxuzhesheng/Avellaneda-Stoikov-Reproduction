"""Fetch REAL Binance USD-M futures data and convert it to an hftbacktest feed.

This is the "real-data" path for Track A (the default experiment uses the fully
synthetic feed from make_feed.py). hftbacktest's matching engine consumes its own
64-byte event format; Binance's public daily archives are not in that format, so
they are converted here.

The public archive (https://data.binance.vision) exposes:
  * bookTicker -> best bid/ask updates  -> DEPTH_BBO_EVENT  (top-of-book only)
  * aggTrades  -> trades                -> TRADE_EVENT

A BBO + trades feed drives the engine fine for top-of-book market making; because
there is no in-book depth, the queue model is then approximate (documented in the
report). Parsing is vectorised with pandas, and a UTC-hour window keeps the output
small (one full day of a liquid symbol is ~200 MB).

Usage:
    python track_a_hftbacktest/download_data.py \
        --symbol SOLUSDT --date 2024-01-02 --start-hour 0 --end-hour 2
Then point run_hft.py at the produced .npz:
    python track_a_hftbacktest/run_hft.py \
        --feed track_a_hftbacktest/SOLUSDT-2024-01-02_h0-2.npz --tick-size 0.01
"""

import argparse
import datetime as dt
import io
import json
import os
import zipfile

import numpy as np
import pandas as pd

from hftbacktest import (
    DEPTH_EVENT, TRADE_EVENT, EXCH_EVENT, LOCAL_EVENT, BUY_EVENT, SELL_EVENT,
    event_dtype,
)

BASE = "https://data.binance.vision/data/futures/um/daily"

# Fallback tick sizes (Binance exchangeInfo) if inference is inconclusive.
KNOWN_TICK = {"BTCUSDT": 0.10, "ETHUSDT": 0.01, "SOLUSDT": 0.001, "BNBUSDT": 0.01}


def _infer_tick(prices: np.ndarray, fallback: float | None) -> float:
    """Infer the instrument tick size from the smallest positive price gap.

    Real Binance prices live on the exchange's tick grid; the minimum gap between
    distinct best bid/ask quotes recovers it (e.g. SOLUSDT -> 0.001). Falls back
    to the known value if the data is degenerate.
    """
    uniq = np.unique(prices[prices > 0])
    if uniq.size < 2:
        return fallback or 0.01
    gap = float(np.min(np.diff(uniq)))
    # snap to a clean power-of-ten / 1-2-5 grid to avoid float noise
    if gap <= 0:
        return fallback or 0.01
    import math
    exp = math.floor(math.log10(gap))
    base = 10.0 ** exp
    for mult in (1, 2, 5, 10):
        if gap <= mult * base * 1.5:
            return round(mult * base, 10)
    return round(base, 10)

_BUY_TRADE = TRADE_EVENT | EXCH_EVENT | LOCAL_EVENT | BUY_EVENT
_SELL_TRADE = TRADE_EVENT | EXCH_EVENT | LOCAL_EVENT | SELL_EVENT


def _managed_depth(px, qty, exch_ns, local_ns, side_flag):
    """Convert a best-bid (or best-ask) stream into a single-level DEPTH_EVENT feed.

    bookTicker only gives the *current* best; to keep a clean book we emit a
    "set" at the new best and a "clear" (qty 0) at the previous best whenever the
    price changes. This maintains exactly one resting level per side that tracks
    the BBO -- which the HashMapMarketDepth book populates correctly (unlike the
    DEPTH_BBO_EVENT path in this build). Unchanged rows are de-duplicated.
    """
    ev_flag = DEPTH_EVENT | EXCH_EVENT | LOCAL_EVENT | side_flag
    n = len(px)
    changed_px = np.ones(n, dtype=bool)
    changed_px[1:] = px[1:] != px[:-1]
    changed = changed_px.copy()
    changed[1:] |= qty[1:] != qty[:-1]

    si = np.flatnonzero(changed)                       # rows that set a level
    sets = np.zeros(len(si), dtype=event_dtype)
    sets["ev"] = ev_flag
    sets["exch_ts"] = exch_ns[si]
    sets["local_ts"] = local_ns[si]
    sets["px"] = px[si]
    sets["qty"] = qty[si]

    idx = np.arange(n)
    ci = np.flatnonzero(changed_px & (idx > 0))        # rows whose price moved
    clears = np.zeros(len(ci), dtype=event_dtype)
    clears["ev"] = ev_flag
    clears["exch_ts"] = exch_ns[ci] - 1                # 1 ns before the set
    clears["local_ts"] = local_ns[ci] - 1
    clears["px"] = px[ci - 1]                           # remove the previous best
    clears["qty"] = 0.0
    return np.concatenate([clears, sets])


def _download_zip_bytes(url: str) -> bytes:
    import urllib.request
    print(f"  downloading {url}")
    with urllib.request.urlopen(url, timeout=300) as resp:
        raw = resp.read()
    zf = zipfile.ZipFile(io.BytesIO(raw))
    return zf.read(zf.namelist()[0])


def _read_csv(raw: bytes, n_cols: int) -> pd.DataFrame:
    """Read a Binance archive CSV, sniffing whether row 0 is a header.

    Futures aggTrades archives often have no header while bookTicker does; we
    detect it by testing whether the second field of row 0 parses as a float.
    """
    first_line = raw.split(b"\n", 1)[0].decode("utf-8", "ignore")
    fields = first_line.split(",")
    has_header = True
    if len(fields) >= 2:
        try:
            float(fields[1])
            has_header = False  # numeric -> row 0 is data, not a header
        except ValueError:
            has_header = True
    df = pd.read_csv(io.BytesIO(raw), header=0 if has_header else None,
                     usecols=range(n_cols))
    df.columns = range(n_cols)  # index by position, ignore archive column names
    return df


def _utc_window_ms(date: str, start_hour: float, end_hour: float):
    """Return [lo, hi) transaction-time bounds in ms for the requested UTC window."""
    day = dt.datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    day_ms = int(day.timestamp() * 1000)
    return day_ms + int(start_hour * 3_600_000), day_ms + int(end_hour * 3_600_000)


def build_feed(symbol, date, start_hour, end_hour, out):
    lo_ms, hi_ms = _utc_window_ms(date, start_hour, end_hour)

    # --- book ticker (best bid/ask) ---------------------------------------
    bt_url = f"{BASE}/bookTicker/{symbol}/{symbol}-bookTicker-{date}.zip"
    bt = _read_csv(_download_zip_bytes(bt_url), 7)
    # cols: 0 update_id, 1 bid_px, 2 bid_qty, 3 ask_px, 4 ask_qty, 5 txn_time, 6 event_time
    txn = bt[5].to_numpy(np.int64)
    keep = (txn >= lo_ms) & (txn < hi_ms)
    bt = bt[keep]
    txn = txn[keep]
    evt = bt[6].to_numpy(np.int64)
    exch_ns = txn * 1_000_000
    local_ns = np.maximum(evt, txn) * 1_000_000  # local feed time >= exch time

    n = len(bt)
    bid_px = bt[1].to_numpy(np.float64)
    bid_qty = bt[2].to_numpy(np.float64)
    ask_px = bt[3].to_numpy(np.float64)
    ask_qty = bt[4].to_numpy(np.float64)
    bid = _managed_depth(bid_px, bid_qty, exch_ns, local_ns, BUY_EVENT)
    ask = _managed_depth(ask_px, ask_qty, exch_ns, local_ns, SELL_EVENT)

    # --- aggregated trades -------------------------------------------------
    tr_url = f"{BASE}/aggTrades/{symbol}/{symbol}-aggTrades-{date}.zip"
    tr = _read_csv(_download_zip_bytes(tr_url), 7)
    # cols: 0 agg_id, 1 price, 2 qty, 3 first_id, 4 last_id, 5 transact_time, 6 is_buyer_maker
    t_txn = tr[5].to_numpy(np.int64)
    keep_t = (t_txn >= lo_ms) & (t_txn < hi_ms)
    tr = tr[keep_t]
    t_txn = t_txn[keep_t]
    t_exch = t_txn * 1_000_000
    is_buyer_maker = tr[6].astype(str).str.strip().str.lower().eq("true").to_numpy()
    # aggressor side: buyer-maker means the aggressor SOLD into the bid
    side = np.where(is_buyer_maker, _SELL_TRADE, _BUY_TRADE)

    trd = np.zeros(len(tr), dtype=event_dtype)
    trd["ev"] = side
    trd["exch_ts"] = t_exch
    trd["local_ts"] = t_exch + 1_000_000  # 1 ms feed latency for trades
    trd["px"] = tr[1].to_numpy(np.float64)
    trd["qty"] = tr[2].to_numpy(np.float64)

    # --- merge + stable sort by local feed time ---------------------------
    arr = np.concatenate([bid, ask, trd])
    arr = arr[np.argsort(arr["local_ts"], kind="stable")]

    # Rebase timestamps to start at 0. hftbacktest's clock begins at t=0 and the
    # market-making loop elapses in small steps; absolute epoch-ns timestamps
    # (~1.7e18) would otherwise be unreachable. Relative spacing is preserved.
    t0 = int(arr["exch_ts"].min())
    arr["exch_ts"] -= t0
    arr["local_ts"] -= t0

    tick_size = _infer_tick(np.concatenate([bid_px, ask_px]), KNOWN_TICK.get(symbol))

    np.savez(out, data=arr)
    meta = {
        "symbol": symbol, "date": date,
        "start_hour": start_hour, "end_hour": end_hour,
        "n_events": int(len(arr)),
        "n_bbo_rows": int(n), "n_depth_events": int(len(bid) + len(ask)),
        "n_trades": int(len(tr)),
        "tick_size": tick_size,
        "price_min": float(arr["px"][arr["px"] > 0].min()),
        "price_max": float(arr["px"].max()),
        "source": "binance USD-M public archive (bookTicker + aggTrades, BBO-only)",
    }
    with open(out.replace(".npz", ".meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print(f"  wrote {len(arr):,} events to {out}")
    print(f"  window {date} {start_hour}-{end_hour}h UTC | "
          f"price {meta['price_min']:.4f}..{meta['price_max']:.4f} | "
          f"tick={meta['tick_size']}")
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="SOLUSDT")
    ap.add_argument("--date", default="2024-01-02")
    ap.add_argument("--start-hour", type=float, default=0.0)
    ap.add_argument("--end-hour", type=float, default=2.0)
    args = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    tag = f"{args.symbol}-{args.date}_h{int(args.start_hour)}-{int(args.end_hour)}"
    out = os.path.join(here, f"{tag}.npz")
    build_feed(args.symbol, args.date, args.start_hour, args.end_hour, out)


if __name__ == "__main__":
    main()
