"""Track A (real data) -- run the A-S quoting rule over SEVERAL real Binance
windows and aggregate, mirroring the paper's "many paths" Monte Carlo.

For each window we run the inventory and symmetric variants through hftbacktest's
real matching/latency/queue engine, then report:
  * P&L mean and std ACROSS windows   (symmetric's directional bets -> high std)
  * average terminal-inventory std     (inventory control -> small and stable)

A single window can flatter the symmetric benchmark (a directional inventory bet
that happens to pay off); aggregating across windows exposes its true risk, which
is the paper's core point.

Run (feeds must already be downloaded via download_data.py):
    python track_a_hftbacktest/run_real_windows.py \
        --feeds track_a_hftbacktest/SOLUSDT-2024-03-05_h0-1.npz \
                track_a_hftbacktest/SOLUSDT-2024-05-02_h0-1.npz \
                track_a_hftbacktest/SOLUSDT-2024-07-03_h0-1.npz
"""

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from run_hft import run_variant, summarize, RESULTS  # reuse the engine wiring


def _tick_from_meta(feed, default=0.001):
    meta = feed.replace(".npz", ".meta.json")
    if os.path.exists(meta):
        with open(meta, encoding="utf-8") as f:
            return float(json.load(f).get("tick_size") or default)
    return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feeds", nargs="+", required=True)
    ap.add_argument("--half-spread-ticks", type=float, default=15.0)
    ap.add_argument("--skew-coef", type=float, default=2.0)
    ap.add_argument("--max-pos", type=float, default=60.0)
    ap.add_argument("--requote-ms", type=float, default=150.0)
    ap.add_argument("--lot-size", type=float, default=1.0)
    args = ap.parse_args()

    requote_ns = int(args.requote_ms * 1e6)
    capacity = 2_000_000
    per_window = {"inventory": [], "symmetric": []}
    rep_ts = None  # representative timeseries (first window) for plotting

    for feed in args.feeds:
        if not os.path.exists(feed):
            sys.exit(f"feed not found: {feed} (run download_data.py first)")
        tick = _tick_from_meta(feed)
        print(f"window {os.path.basename(feed)}  tick={tick}")
        inv = run_variant(feed, args.half_spread_ticks, args.skew_coef, args.max_pos,
                          requote_ns, capacity, tick, args.lot_size)
        sym = run_variant(feed, args.half_spread_ticks, 0.0, args.max_pos,
                          requote_ns, capacity, tick, args.lot_size)
        per_window["inventory"].append(summarize("inventory", inv))
        per_window["symmetric"].append(summarize("symmetric", sym))
        if rep_ts is None:
            rep_ts = (inv, sym)

    def agg(rows):
        pnl = np.array([r["final_pnl"] for r in rows])
        pos = np.array([r["position_std"] for r in rows])
        eqs = np.array([r["equity_std"] for r in rows])
        return {
            "n_windows": len(rows),
            "pnl_mean": float(np.mean(pnl)),
            "pnl_std": float(np.std(pnl)),       # dispersion of P&L across windows
            "position_std": float(np.mean(pos)), # avg terminal-inventory std
            "equity_std": float(np.mean(eqs)),
            "windows": rows,
        }

    summary = {"inventory": agg(per_window["inventory"]),
               "symmetric": agg(per_window["symmetric"])}

    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "track_a_real_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    inv, sym = rep_ts
    def ds(a, n=3000):
        step = max(1, len(a) // n)
        return a[::step]
    np.savez(
        os.path.join(RESULTS, "track_a_real_timeseries.npz"),
        inv_ts=ds(inv["timestamp"]), inv_pos=ds(inv["position"]), inv_eq=ds(inv["equity"]),
        sym_ts=ds(sym["timestamp"]), sym_pos=ds(sym["position"]), sym_eq=ds(sym["equity"]),
    )

    print("\n=== Track A (real Binance, aggregated over windows) ===")
    for k in ("inventory", "symmetric"):
        s = summary[k]
        print(f"  {k:10s} pnl={s['pnl_mean']:8.2f} +/- {s['pnl_std']:6.2f} (across {s['n_windows']} win)  "
              f"avg_pos_std={s['position_std']:6.2f}  avg_eq_std={s['equity_std']:6.2f}")
    print(f"\nWrote {RESULTS}/track_a_real_summary.json and track_a_real_timeseries.npz")


if __name__ == "__main__":
    main()
