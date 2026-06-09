"""Parse a REAL Hummingbot paper-trade run into Track B metrics.

After running the bundled `as_market_making.py` strategy inside a real Hummingbot
container (see RUNBOOK.md), Hummingbot records every fill in:
  * data/<strategy>.sqlite   -> table `TradeFill`, or
  * an exported `trades_*.csv`.

This script reconstructs the inventory and equity time series from those fills and
computes the same metrics as the other tracks, so the result drops straight into
the report and figures. Run it once per variant (inventory / symmetric):

    python track_b_hummingbot/parse_hummingbot_logs.py \
        --inventory data/trades_inventory.csv \
        --symmetric data/trades_symmetric.csv

Generate self-contained sample logs to validate the pipeline without Hummingbot:

    python track_b_hummingbot/parse_hummingbot_logs.py --make-sample
"""

import argparse
import json
import os
import sqlite3

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESULTS = os.path.join(ROOT, "results")

# Candidate column names in Hummingbot TradeFill / trades CSV (case-insensitive).
_TS = ("timestamp", "time", "trade_time")
_SIDE = ("trade_type", "side", "trade_side")
_PRICE = ("price",)
_AMOUNT = ("amount", "quantity", "qty")
_FEE = ("trade_fee_in_quote", "fee", "trade_fee")


def _pick(cols, candidates):
    low = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand in low:
            return low[cand]
    return None


def _load_fills(path: str) -> pd.DataFrame:
    """Load fills from a Hummingbot CSV or sqlite (TradeFill table)."""
    if path.endswith(".sqlite") or path.endswith(".db"):
        con = sqlite3.connect(path)
        try:
            df = pd.read_sql_query("SELECT * FROM TradeFill", con)
        finally:
            con.close()
    else:
        df = pd.read_csv(path)

    ts = _pick(df.columns, _TS)
    side = _pick(df.columns, _SIDE)
    price = _pick(df.columns, _PRICE)
    amount = _pick(df.columns, _AMOUNT)
    fee = _pick(df.columns, _FEE)
    if not all([ts, side, price, amount]):
        raise ValueError(f"{path}: could not find timestamp/side/price/amount columns "
                         f"in {list(df.columns)}")

    out = pd.DataFrame()
    t = pd.to_numeric(df[ts], errors="coerce")
    # Hummingbot timestamps are ms since epoch; normalise to seconds from start.
    out["t"] = (t - t.min()) / (1000.0 if t.max() > 1e12 else 1.0)
    out["side"] = df[side].astype(str).str.upper().str.contains("BUY").map({True: 1, False: -1})
    out["price"] = pd.to_numeric(df[price], errors="coerce")
    out["amount"] = pd.to_numeric(df[amount], errors="coerce").abs()
    out["fee"] = pd.to_numeric(df[fee], errors="coerce").fillna(0.0) if fee else 0.0
    out = out.dropna(subset=["t", "price", "amount"]).sort_values("t").reset_index(drop=True)

    # Hummingbot's sqlite TradeFill stores price/amount/fee as integers scaled by
    # 1e6 (e.g. ETH 1690.99 -> 1690992000); CSV exports use real decimals. Detect
    # the scaling from the price column (large + whole) and undo it consistently.
    px = out["price"].dropna()
    if len(px) and px.median() > 1e5 and bool((px == px.round()).all()):
        out["price"] = out["price"] / 1e6
        out["amount"] = out["amount"] / 1e6
        out["fee"] = out["fee"] / 1e6
    return out


def _reconstruct(fills: pd.DataFrame) -> dict:
    """Rebuild inventory / cash / equity time series from a fill log."""
    signed_qty = fills["side"] * fills["amount"]
    position_base = np.cumsum(signed_qty.to_numpy())   # inventory in base asset
    # report inventory in LOTS (units of the typical fill size) to match the
    # paper's integer-inventory semantics and stay comparable across tracks
    unit = float(fills["amount"].median()) or 1.0
    position = position_base / unit
    # cash decreases on buys, increases on sells; subtract fees throughout
    cash_delta = -(fills["side"] * fills["price"] * fills["amount"]).to_numpy() - fills["fee"].to_numpy()
    cash = np.cumsum(cash_delta)
    price = fills["price"].to_numpy()
    equity = cash + position_base * price   # mark-to-market at last trade price (real units)
    return {
        "t": fills["t"].to_numpy(),
        "position": position,
        "equity": equity,
        "n_trades": int(len(fills)),
    }


def _summarize(name: str, rec: dict) -> dict:
    eq = rec["equity"]
    return {
        "variant": name,
        "final_pnl": float(eq[-1]) if len(eq) else 0.0,
        "equity_std": float(np.std(eq)) if len(eq) else 0.0,
        "position_std": float(np.std(rec["position"])) if len(rec["position"]) else 0.0,
        "position_absmax": float(np.max(np.abs(rec["position"]))) if len(rec["position"]) else 0.0,
        "n_trades": rec["n_trades"],
        "source": "real hummingbot paper-trade fill log",
    }


def run(inventory_path, symmetric_path, tag="real"):
    """Parse fill logs and write results/track_b_<tag>_summary.json.

    tag="real" is reserved for the user's actual Hummingbot run (it is what the
    figures/report treat as the real result); tag="sample" is for validating the
    pipeline on the bundled synthetic logs without polluting the real slot.
    """
    os.makedirs(RESULTS, exist_ok=True)
    summary, ts_out = {}, {}
    for name, path in (("inventory", inventory_path), ("symmetric", symmetric_path)):
        if not path:
            continue
        rec = _reconstruct(_load_fills(path))
        summary[name] = _summarize(name, rec)
        ts_out[f"{name}_t"] = rec["t"]
        ts_out[f"{name}_pos"] = rec["position"]
        ts_out[f"{name}_eq"] = rec["equity"]

    if not summary:
        raise SystemExit("no logs provided; pass --inventory and/or --symmetric (or --make-sample)")

    with open(os.path.join(RESULTS, f"track_b_{tag}_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    if ts_out:
        np.savez(os.path.join(RESULTS, f"track_b_{tag}_timeseries.npz"), **ts_out)

    print(f"=== Track B ({'real Hummingbot paper-trade' if tag == 'real' else 'SAMPLE pipeline check'}) ===")
    for k, s in summary.items():
        print(f"  {k:10s} final_pnl={s['final_pnl']:9.3f}  equity_std={s['equity_std']:8.3f}  "
              f"pos_std={s['position_std']:7.2f}  pos_absmax={s['position_absmax']:6.0f}  trades={s['n_trades']}")
    print(f"\nWrote {RESULTS}/track_b_{tag}_summary.json")


def make_sample():
    """Write two self-contained sample fill logs (inventory vs symmetric) so the
    parser pipeline can be validated end-to-end without a Hummingbot runtime."""
    rng = np.random.default_rng(20260609)
    n = 240
    t0 = 1_717_200_000_000  # arbitrary epoch ms
    dt = 5_000             # 5 s between fills (order_refresh_time)
    amount = 1.0           # 1 lot per fill; position tracked in lots
    mid = 132.0
    rows_inv, rows_sym = [], []
    pos_inv = pos_sym = 0.0
    base_cols = ["timestamp", "trade_type", "price", "amount", "trade_fee_in_quote"]
    for i in range(n):
        mid += rng.normal(0, 0.05)
        ts = t0 + i * dt
        fee = round(amount * mid * 0.0002, 6)
        # inventory strategy: A-S skew makes fills mean-revert position toward 0
        p_buy_inv = float(np.clip(0.5 - 0.15 * pos_inv, 0.05, 0.95))
        side_inv = "BUY" if rng.random() < p_buy_inv else "SELL"
        pos_inv += amount if side_inv == "BUY" else -amount
        rows_inv.append([ts, side_inv, round(mid, 3), amount, fee])
        # symmetric benchmark: no skew -> inventory random-walks and drifts away
        side_sym = "BUY" if rng.random() < 0.5 else "SELL"
        pos_sym += amount if side_sym == "BUY" else -amount
        rows_sym.append([ts, side_sym, round(mid, 3), amount, fee])
    pd.DataFrame(rows_inv, columns=base_cols).to_csv(
        os.path.join(HERE, "sample_trades_inventory.csv"), index=False)
    pd.DataFrame(rows_sym, columns=base_cols).to_csv(
        os.path.join(HERE, "sample_trades_symmetric.csv"), index=False)
    print(f"wrote sample_trades_inventory.csv and sample_trades_symmetric.csv to {HERE}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", help="Hummingbot fill log (CSV or .sqlite) for the inventory variant")
    ap.add_argument("--symmetric", help="Hummingbot fill log (CSV or .sqlite) for the symmetric variant")
    ap.add_argument("--make-sample", action="store_true", help="write sample logs and parse them")
    args = ap.parse_args()

    if args.make_sample:
        make_sample()
        run(os.path.join(HERE, "sample_trades_inventory.csv"),
            os.path.join(HERE, "sample_trades_symmetric.csv"), tag="sample")
        return
    run(args.inventory, args.symmetric, tag="real")


if __name__ == "__main__":
    main()
