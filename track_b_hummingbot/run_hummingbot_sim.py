"""Track B -- offline reproduction of the Hummingbot A-S strategy.

A full Hummingbot runtime (conda/Docker, exchange connectors) is not required to
see the paper's effect. This harness runs the *same* Avellaneda-Stoikov quoting
rule used by as_market_making.py, but at Hummingbot's coarse, second-level
requote cadence (order_refresh_time) rather than the paper's fine dt. It reuses
the single A-S math source (src/simulate.py), so the only difference from Track 0
is the cadence -- which is exactly what distinguishes a Hummingbot deployment
from the paper's idealised high-frequency simulation.

Run:  python track_b_hummingbot/run_hummingbot_sim.py
"""

import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config
from src.simulate import simulate_stale

RESULTS = os.path.join(ROOT, "results")

# Hummingbot-style configuration (mirrors as_market_making.py).
# gamma=0.1 keeps the inventory skew (gamma*sigma^2*(T-t)=0.4 per unit) below the
# half-spread (0.645), so quoting stays well-behaved under stale (coarse) requoting.
GAMMA = 0.1
# The market trades on the paper's fine clock (dt=0.005), but Hummingbot only
# refreshes its quotes every order_refresh_time. We hold quotes stale for
# REQUOTE_EVERY fine steps between refreshes.
REQUOTE_EVERY = 5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=config.N_SIMS)
    ap.add_argument("--seed", type=int, default=config.SEED + 7)
    ap.add_argument("--requote-every", type=int, default=REQUOTE_EVERY)
    args = ap.parse_args()

    params = config.ASParams(gamma=GAMMA)  # fine clock dt=0.005
    inv = simulate_stale(params, GAMMA, "inventory", args.sims, args.requote_every, args.seed)
    sym = simulate_stale(params, GAMMA, "symmetric", args.sims, args.requote_every, args.seed + 1)

    summary = {
        "config": {"gamma": GAMMA, "dt": params.dt, "requote_every": args.requote_every,
                   "cadence": "stale quotes refreshed every %d ticks (Hummingbot order_refresh_time)" % args.requote_every},
        "inventory": {
            "final_pnl": inv["profit_mean"], "pnl_std": inv["profit_std"],
            "position_std": inv["final_q_std"], "position_mean": inv["final_q_mean"],
        },
        "symmetric": {
            "final_pnl": sym["profit_mean"], "pnl_std": sym["profit_std"],
            "position_std": sym["final_q_std"], "position_mean": sym["final_q_mean"],
        },
    }

    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "track_b_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\n=== Track B: Hummingbot-cadence A-S market making (gamma={GAMMA}) ===")
    for k in ("inventory", "symmetric"):
        s = summary[k]
        print(f"  {k:10s} final_pnl={s['final_pnl']:8.3f}  pnl_std={s['pnl_std']:7.3f}  "
              f"final_q_std={s['position_std']:6.2f}")
    print(f"\nWrote {RESULTS}/track_b_summary.json")


if __name__ == "__main__":
    main()
