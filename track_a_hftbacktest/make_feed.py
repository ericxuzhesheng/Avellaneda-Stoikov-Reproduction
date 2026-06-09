"""Generate a synthetic limit-order-book feed in hftbacktest's native event
format, replicating the Avellaneda-Stoikov data-generating process:

    * a Brownian mid-price (random +/- 1-tick walk), and
    * Poisson market-order arrivals that consume the resting book.

This lets us drive hftbacktest's *real* matching / latency / queue engine with
the same statistical environment as the paper, fully offline and reproducible.
To use real Binance L2 data instead, see download_data.py and point run_hft.py
at the converted .npz.

Event layout (64-byte struct, see hftbacktest.event_dtype):
    ev, exch_ts, local_ts, px, qty, order_id, ival, fval
"""

import argparse
import os

import numpy as np
from hftbacktest import (
    DEPTH_EVENT, TRADE_EVENT, EXCH_EVENT, LOCAL_EVENT, BUY_EVENT, SELL_EVENT,
    event_dtype,
)

# --- instrument / feed configuration -------------------------------------
TICK = 0.01            # tick size
MID0_TICK = 10_000     # initial mid in ticks -> price 100.00
N_LEVELS = 20          # resting levels per side
DEPTH_QTY = 12.0       # resting quantity per level (small enough for fills)
STEP_NS = 1_000_000    # 1 ms between steps
FEED_LATENCY_NS = 1_000_000   # 1 ms feed latency (local_ts = exch_ts + this)
P_MOVE = 0.30          # prob. the mid moves one tick on a step
P_TRADE = 0.55         # prob. a market order arrives on a step
MAX_TRADE_LOTS = 4     # market-order size ~ U{1..MAX_TRADE_LOTS}

_BID_DEPTH = DEPTH_EVENT | EXCH_EVENT | LOCAL_EVENT | BUY_EVENT
_ASK_DEPTH = DEPTH_EVENT | EXCH_EVENT | LOCAL_EVENT | SELL_EVENT
_BUY_TRADE = TRADE_EVENT | EXCH_EVENT | LOCAL_EVENT | BUY_EVENT
_SELL_TRADE = TRADE_EVENT | EXCH_EVENT | LOCAL_EVENT | SELL_EVENT


def generate(duration_s=60.0, seed=20260608):
    rng = np.random.default_rng(seed)
    n_steps = int(duration_s * 1e9 / STEP_NS)

    evs, ts, pxs, qtys = [], [], [], []

    def emit(ev, exch_ts, px, qty):
        evs.append(ev)
        ts.append(exch_ts)
        pxs.append(px)
        qtys.append(qty)

    mid = MID0_TICK
    exch_ts = 0

    # initial book: build N_LEVELS each side from empty via DEPTH events
    for lvl in range(1, N_LEVELS + 1):
        emit(_BID_DEPTH, exch_ts, (mid - lvl) * TICK, DEPTH_QTY)
        emit(_ASK_DEPTH, exch_ts, (mid + lvl) * TICK, DEPTH_QTY)

    for _ in range(n_steps):
        exch_ts += STEP_NS

        # mid-price random walk (+/- 1 tick) -> shift the book by one level
        if rng.random() < P_MOVE:
            if rng.random() < 0.5:  # mid up one tick
                emit(_BID_DEPTH, exch_ts, mid * TICK, DEPTH_QTY)               # new near bid
                emit(_BID_DEPTH, exch_ts, (mid - N_LEVELS) * TICK, 0.0)        # drop far bid
                emit(_ASK_DEPTH, exch_ts, (mid + 1) * TICK, 0.0)              # vacate new mid
                emit(_ASK_DEPTH, exch_ts, (mid + N_LEVELS + 1) * TICK, DEPTH_QTY)
                mid += 1
            else:                    # mid down one tick
                emit(_ASK_DEPTH, exch_ts, mid * TICK, DEPTH_QTY)
                emit(_ASK_DEPTH, exch_ts, (mid + N_LEVELS) * TICK, 0.0)
                emit(_BID_DEPTH, exch_ts, (mid - 1) * TICK, 0.0)
                emit(_BID_DEPTH, exch_ts, (mid - N_LEVELS - 1) * TICK, DEPTH_QTY)
                mid -= 1

        # Poisson market order consuming the touch (drives fills via queue model)
        if rng.random() < P_TRADE:
            lots = float(rng.integers(1, MAX_TRADE_LOTS + 1))
            if rng.random() < 0.5:   # aggressive buy -> trades at best ask
                emit(_BUY_TRADE, exch_ts, (mid + 1) * TICK, lots)
            else:                    # aggressive sell -> trades at best bid
                emit(_SELL_TRADE, exch_ts, (mid - 1) * TICK, lots)

    arr = np.zeros(len(evs), dtype=event_dtype)
    arr["ev"] = np.asarray(evs, dtype=np.uint64)
    exch = np.asarray(ts, dtype=np.int64)
    arr["exch_ts"] = exch
    arr["local_ts"] = exch + FEED_LATENCY_NS
    arr["px"] = np.asarray(pxs, dtype=np.float64)
    arr["qty"] = np.asarray(qtys, dtype=np.float64)
    # stable sort by local_ts (already time-ordered with constant latency)
    arr = arr[np.argsort(arr["local_ts"], kind="stable")]
    return arr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=60.0, help="feed length in seconds")
    ap.add_argument("--seed", type=int, default=20260608)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    out = args.out or os.path.join(here, "feed_synth.npz")
    arr = generate(args.duration, args.seed)
    np.savez(out, data=arr)
    print(f"wrote {len(arr):,} events to {out}")
    print(f"  exch_ts span: {arr['exch_ts'][0]} .. {arr['exch_ts'][-1]} ns")
    print(f"  price range : {arr['px'][arr['px']>0].min():.2f} .. {arr['px'].max():.2f}")


if __name__ == "__main__":
    main()
