"""Aggregation of Monte-Carlo results into the paper's Tables 1-3 and LaTeX."""

import csv
import os


TABLE_COLUMNS = ["Strategy", "Profit", "std(Profit)", "Final q", "std(Final q)"]


def result_row(strategy_name, res):
    """One table row: strategy name + the four reported statistics."""
    return [
        strategy_name,
        res["profit_mean"],
        res["profit_std"],
        res["final_q_mean"],
        res["final_q_std"],
    ]


def write_csv(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(TABLE_COLUMNS)
        for row in rows:
            w.writerow([row[0]] + [f"{v:.4f}" for v in row[1:]])


def latex_table(gamma, our_rows, paper_results):
    """Build a booktabs LaTeX table comparing our reproduction with the paper."""
    tag = str(gamma).replace(".", "p")
    lines = []
    lines.append(r"\begin{table}[htbp]")
    lines.append(r"\centering")
    lines.append(
        r"\caption{$\gamma=%g$ 时本文复现值与原论文值对照（1000 次蒙特卡洛模拟）}" % gamma
    )
    lines.append(r"\label{tab:gamma_%s}" % tag)
    lines.append(r"\begin{tabular}{l rrrr}")
    lines.append(r"\toprule")
    lines.append(r"策略 & 盈亏均值 & 盈亏标准差 & 终端库存 $q$ & 库存标准差 \\")
    lines.append(r"\midrule")
    for name, key in [("库存策略（本文）", "inventory"), ("对称基准（本文）", "symmetric")]:
        row = next(r for r in our_rows if r[0] == key)
        lines.append(
            r"%s & %.2f & %.2f & %.3f & %.2f \\" % (name, row[1], row[2], row[3], row[4])
        )
    lines.append(r"\midrule")
    for label, key in [("库存策略（原文）", "inventory"), ("对称基准（原文）", "symmetric")]:
        p, sp, fq, sfq = paper_results[gamma][key]
        lines.append(r"%s & %.2f & %.2f & %.3f & %.2f \\" % (label, p, sp, fq, sfq))
    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}")
    lines.append(r"\end{table}")
    return "\n".join(lines)
