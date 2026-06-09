"""Cross-track figures combining Track 0 (paper MC), Track A (hftbacktest),
and Track B (Hummingbot cadence). Run after the three track scripts.

    python make_figures.py
Produces figures/fig5_hft_inventory_path.{pdf,png} and
        figures/fig6_cross_track_inventory_std.{pdf,png}.
"""

import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import sys
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from src import plotstyle
plotstyle.apply()

RESULTS = os.path.join(ROOT, "results")
FIG = os.path.join(ROOT, "figures")


def _save(fig, name):
    os.makedirs(FIG, exist_ok=True)
    fig.savefig(os.path.join(FIG, name + ".pdf"))
    fig.savefig(os.path.join(FIG, name + ".png"), dpi=140)
    plt.close(fig)


def fig_hft_inventory_path():
    """Track A: inventory time series, inventory vs symmetric, in the real LOB engine."""
    ts = np.load(os.path.join(RESULTS, "track_a_timeseries.npz"))
    inv_t = (ts["inv_ts"] - ts["inv_ts"][0]) / 1e9
    sym_t = (ts["sym_ts"] - ts["sym_ts"][0]) / 1e9
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.plot(sym_t, ts["sym_pos"], color=plotstyle.COLOR_SYMMETRIC, lw=1.0, label="对称基准（库存漂移）")
    ax.plot(inv_t, ts["inv_pos"], color=plotstyle.COLOR_INVENTORY, lw=1.1, label="库存策略（受控）")
    ax.axhline(0, color="black", lw=0.5, alpha=0.5)
    ax.set_xlabel("时间 (秒)")
    ax.set_ylabel("库存 (手)")
    ax.set_title("Track A（hftbacktest 真实撮合引擎）：A–S 报价下的库存路径")
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    _save(fig, "fig5_hft_inventory_path")


def _load(name):
    path = os.path.join(RESULTS, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fig_cross_track_inventory_std():
    """Inventory std (risk) across every available track, inventory vs symmetric.

    Real-data tracks are added automatically when their summaries exist, so the
    figure grows from the offline-only baseline to the full comparison without
    code changes (graceful fallback)."""
    t0 = _load("summary.json")
    # (label, summary-dict, inv-key, sym-key) -- only included if the file exists
    specs = []
    if t0:
        specs.append(("Track 0\n论文蒙特卡洛", {"inventory": t0["0.1"]["inventory"],
                      "symmetric": t0["0.1"]["symmetric"]}, "final_q_std"))
    for fname, label in [
        ("track_a_summary.json", "Track A\nhftbacktest(合成)"),
        ("track_a_real_summary.json", "Track A\nhftbacktest(真实)"),
        ("track_b_summary.json", "Track B\nHummingbot(离线)"),
        ("track_b_real_summary.json", "Track B\nHummingbot(真实)"),
    ]:
        d = _load(fname)
        if d:
            specs.append((label, d, "position_std"))

    labels = [s[0] for s in specs]
    inv_std = [s[1]["inventory"][s[2]] for s in specs]
    sym_std = [s[1]["symmetric"][s[2]] for s in specs]

    x = np.arange(len(labels))
    w = 0.38
    fig, ax = plt.subplots(figsize=(max(8, 1.7 * len(labels)), 4.6))
    b1 = ax.bar(x - w / 2, inv_std, w, color=plotstyle.COLOR_INVENTORY, label="库存策略")
    b2 = ax.bar(x + w / 2, sym_std, w, color=plotstyle.COLOR_SYMMETRIC, label="对称基准")
    ax.bar_label(b1, fmt="%.1f", fontsize=9)
    ax.bar_label(b2, fmt="%.1f", fontsize=9)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("终端库存标准差")
    ax.set_title("各轨道库存风险对照：A–S 库存控制 vs 对称基准")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    _save(fig, "fig6_cross_track_inventory_std")


def fig_track_a_real_pnl():
    """Track A real data: P&L mean +/- std ACROSS windows -- the risk story.

    The symmetric benchmark's huge P&L dispersion is the directional risk it
    takes; the inventory strategy's P&L is far more stable. Skipped if the real
    summary is absent."""
    d = _load("track_a_real_summary.json")
    if not d or "pnl_std" not in d.get("inventory", {}):
        return
    names = ["库存策略", "对称基准"]
    means = [d["inventory"]["pnl_mean"], d["symmetric"]["pnl_mean"]]
    stds = [d["inventory"]["pnl_std"], d["symmetric"]["pnl_std"]]
    colors = [plotstyle.COLOR_INVENTORY, plotstyle.COLOR_SYMMETRIC]
    nwin = d["inventory"].get("n_windows", "?")

    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    bars = ax.bar(names, means, yerr=stds, capsize=8, color=colors, alpha=0.9,
                  error_kw={"elinewidth": 1.6, "ecolor": "#222"})
    ax.axhline(0, color="black", lw=0.6)
    for b, m, s in zip(bars, means, stds):
        ax.text(b.get_x() + b.get_width() / 2, m, f"  {m:.1f}±{s:.1f}",
                ha="center", va="bottom" if m >= 0 else "top", fontsize=10)
    ax.set_ylabel("终端盈亏（跨窗口）")
    ax.set_title(f"Track A 真实 Binance 数据：盈亏均值 ± 跨窗口标准差（{nwin} 个窗口）")
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    _save(fig, "fig7_track_a_real_pnl")


def main():
    fig_hft_inventory_path()
    fig_cross_track_inventory_std()
    fig_track_a_real_pnl()
    print("wrote fig5/fig6/fig7 to", FIG)


if __name__ == "__main__":
    main()
