"""Track A -- Avellaneda-Stoikov market-making through hftbacktest's engine.

We run the A-S quoting rule inside hftbacktest's real order/latency/queue/
matching engine on an L2 feed (synthetic A-S feed by default; swap in real
Binance L2 via download_data.py). Two variants are compared, mirroring the paper:

  * "inventory" : quotes centred on the inventory-skewed reservation price
                  r = mid - skew_coef * position   (A-S: q*gamma*sigma^2*(T-t))
  * "symmetric" : same half-spread, centred on the mid-price (skew_coef = 0)

The reproduction target is the paper's core finding: the inventory strategy
attains far smaller inventory (and P&L) variance than the symmetric benchmark.

Run:  python track_a_hftbacktest/run_hft.py
"""

import argparse
import json
import os
import sys

import numpy as np
from numba import njit

from hftbacktest import (
    BacktestAsset, HashMapMarketDepthBacktest, Recorder, GTX, LIMIT, BUY, SELL,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
FEED = os.path.join(HERE, "feed_synth.npz")
RESULTS = os.path.join(ROOT, "results")

ASK_ID_OFFSET = 1_000_000_000  # keep ask order-ids disjoint from bid order-ids


@njit
def market_making(hbt, recorder, half_spread_ticks, skew_coef, max_pos, requote_ns):
    asset_no = 0
    while hbt.elapse(requote_ns) == 0:
        hbt.clear_inactive_orders(asset_no)
        depth = hbt.depth(asset_no)
        bbt = depth.best_bid_tick
        bat = depth.best_ask_tick
        # skip if the book is one-sided / empty
        if bbt <= 0 or bat <= 0 or bat - bbt > 1_000_000:
            recorder.record(hbt)
            continue

        mid_tick = 0.5 * (bbt + bat)
        pos = hbt.position(asset_no)

        # A-S reservation price (in ticks): skew proportional to inventory.
        reservation_tick = mid_tick - skew_coef * pos

        desired_bid_tick = int(round(reservation_tick - half_spread_ticks))
        desired_ask_tick = int(round(reservation_tick + half_spread_ticks))
        # post-only safety: never cross the opposite touch
        if desired_bid_tick >= bat:
            desired_bid_tick = bat - 1
        if desired_ask_tick <= bbt:
            desired_ask_tick = bbt + 1

        # inventory limits: stop adding to a side once at the cap
        bid_ok = pos < max_pos
        ask_ok = pos > -max_pos

        # reconcile resting orders with desired quotes
        bid_exists = False
        ask_exists = False
        values = hbt.orders(asset_no).values()
        while values.has_next():
            o = values.get()
            if o.side == BUY:
                if (not bid_ok) or o.price_tick != desired_bid_tick:
                    if o.cancellable:
                        hbt.cancel(asset_no, o.order_id, False)
                else:
                    bid_exists = True
            else:  # SELL
                if (not ask_ok) or o.price_tick != desired_ask_tick:
                    if o.cancellable:
                        hbt.cancel(asset_no, o.order_id, False)
                else:
                    ask_exists = True

        tick_size = depth.tick_size
        if bid_ok and not bid_exists:
            hbt.submit_buy_order(
                asset_no, desired_bid_tick, desired_bid_tick * tick_size,
                1.0, GTX, LIMIT, False)
        if ask_ok and not ask_exists:
            hbt.submit_sell_order(
                asset_no, desired_ask_tick + ASK_ID_OFFSET, desired_ask_tick * tick_size,
                1.0, GTX, LIMIT, False)

        recorder.record(hbt)
    return True


def build_backtest(feed, tick_size, lot_size):
    asset = (
        BacktestAsset()
        .data([feed])
        .linear_asset(1.0)
        .constant_order_latency(10_000_000, 10_000_000)  # 10 ms entry / response
        .risk_adverse_queue_model()
        .no_partial_fill_exchange()
        .trading_value_fee_model(-0.00002, 0.0007)        # maker rebate / taker fee
        .tick_size(tick_size)
        .lot_size(lot_size)
    )
    return HashMapMarketDepthBacktest([asset])


def run_variant(feed, half_spread_ticks, skew_coef, max_pos, requote_ns, capacity,
                tick_size, lot_size):
    hbt = build_backtest(feed, tick_size, lot_size)
    recorder = Recorder(1, capacity)
    market_making(hbt, recorder.recorder, half_spread_ticks, skew_coef, max_pos, requote_ns)
    hbt.close()
    rec = recorder.get(0)
    rec = rec[rec["timestamp"] > 0]
    # drop snapshots taken before the book is two-sided (mid price not yet valid)
    valid = np.isfinite(rec["price"]) & (rec["price"] > 0)
    rec = rec[valid]
    equity = rec["balance"] + rec["position"] * rec["price"] - rec["fee"]
    return {
        "timestamp": rec["timestamp"],
        "position": rec["position"],
        "equity": equity,
        "num_trades": rec["num_trades"],
    }


def summarize(name, r):
    return {
        "variant": name,
        "final_pnl": float(r["equity"][-1]),
        "equity_std": float(np.std(r["equity"])),
        "position_std": float(np.std(r["position"])),
        "position_absmax": float(np.max(np.abs(r["position"]))),
        "n_trades": int(r["num_trades"][-1]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", default=FEED)
    ap.add_argument("--half-spread-ticks", type=float, default=3.0,
                    help="quote distance from reservation price; >=2 keeps the MM resting in the book")
    ap.add_argument("--skew-coef", type=float, default=0.50,
                    help="inventory skew (ticks per unit of inventory); A-S q*gamma*sigma^2*(T-t)")
    ap.add_argument("--max-pos", type=float, default=50.0)
    ap.add_argument("--requote-ms", type=float, default=50.0)
    ap.add_argument("--tick-size", type=float, default=0.01,
                    help="instrument tick size; for real feeds read it from the .meta.json sidecar")
    ap.add_argument("--lot-size", type=float, default=1.0)
    ap.add_argument("--real", action="store_true",
                    help="tag outputs as the real-data run (track_a_real_*) instead of synthetic")
    args = ap.parse_args()

    if not os.path.exists(args.feed):
        sys.exit(f"feed not found: {args.feed}\nRun: python track_a_hftbacktest/make_feed.py")

    # If a real-feed sidecar exists, prefer its tick size and auto-enable --real.
    tick_size = args.tick_size
    meta_path = args.feed.replace(".npz", ".meta.json")
    is_real = args.real
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        if meta.get("tick_size"):
            tick_size = float(meta["tick_size"])
        is_real = True
        print(f"real feed: {meta.get('symbol')} {meta.get('date')} "
              f"{meta.get('start_hour')}-{meta.get('end_hour')}h  tick={tick_size}")

    requote_ns = int(args.requote_ms * 1e6)
    capacity = 2_000_000

    print("Running hftbacktest A-S market making (inventory)...")
    inv = run_variant(args.feed, args.half_spread_ticks, args.skew_coef, args.max_pos,
                      requote_ns, capacity, tick_size, args.lot_size)
    print("Running hftbacktest A-S market making (symmetric)...")
    sym = run_variant(args.feed, args.half_spread_ticks, 0.0, args.max_pos,
                      requote_ns, capacity, tick_size, args.lot_size)

    summary = {"inventory": summarize("inventory", inv), "symmetric": summarize("symmetric", sym)}

    prefix = "track_a_real" if is_real else "track_a"
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, f"{prefix}_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    # time series for plotting (downsample to keep files small)
    def ds(a, n=3000):
        step = max(1, len(a) // n)
        return a[::step]
    np.savez(
        os.path.join(RESULTS, f"{prefix}_timeseries.npz"),
        inv_ts=ds(inv["timestamp"]), inv_pos=ds(inv["position"]), inv_eq=ds(inv["equity"]),
        sym_ts=ds(sym["timestamp"]), sym_pos=ds(sym["position"]), sym_eq=ds(sym["equity"]),
    )

    print(f"\n=== Track A: hftbacktest A-S market making ({'real' if is_real else 'synthetic'}) ===")
    for k in ("inventory", "symmetric"):
        s = summary[k]
        print(f"  {k:10s} final_pnl={s['final_pnl']:9.3f}  equity_std={s['equity_std']:8.3f}  "
              f"pos_std={s['position_std']:7.2f}  pos_absmax={s['position_absmax']:6.0f}  trades={s['n_trades']}")
    print(f"\nWrote {RESULTS}/{prefix}_summary.json and {prefix}_timeseries.npz")


if __name__ == "__main__":
    main()
