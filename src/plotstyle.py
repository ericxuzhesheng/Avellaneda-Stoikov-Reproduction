"""Shared matplotlib styling so every figure uses consistent Chinese labels.

Importing this module configures a CJK-capable sans-serif font and a clean
publication style. Call ``apply()`` once at the top of any plotting script.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# Preference order of CJK fonts that ship with Windows.
_CJK_FONTS = ["Microsoft YaHei", "SimHei", "DengXian", "SimSun"]


def apply() -> None:
    """Set a consistent, CJK-capable plotting style for the whole project."""
    plt.rcParams.update({
        "font.sans-serif": _CJK_FONTS + ["DejaVu Sans"],
        "axes.unicode_minus": False,          # render the minus sign correctly
        "font.size": 11,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.labelsize": 11,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "grid.linewidth": 0.6,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "legend.frameon": False,
        "figure.dpi": 120,
    })


# Project colour palette (consistent across all tracks).
COLOR_INVENTORY = "#c0392b"   # 库存策略 (red)
COLOR_SYMMETRIC = "#7f8c8d"   # 对称基准 (grey)
COLOR_MID = "#2c3e50"         # 中价 (dark)
COLOR_RESERVATION = "#27ae60" # 保留价 (green)
COLOR_ASK = "#e67e22"         # 卖价 (orange)
COLOR_BID = "#2980b9"         # 买价 (blue)
