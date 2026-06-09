# Avellaneda–Stoikov (2008) Reproduction

### High-frequency trading in a limit order book

<p align="center">
  <a href="#中文"><img src="https://img.shields.io/badge/语言-中文-E84D3D?style=for-the-badge&labelColor=3B3F47" alt="中文"></a>
  &nbsp;
  <a href="#english"><img src="https://img.shields.io/badge/Language-English-2F73C9?style=for-the-badge&labelColor=3B3F47" alt="English"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/hftbacktest-2.4.4-FF6B35?style=for-the-badge" alt="hftbacktest">
  <img src="https://img.shields.io/badge/Hummingbot-Docker-00BCD4?style=for-the-badge&logo=docker&logoColor=white" alt="Hummingbot">
  <img src="https://img.shields.io/badge/三条轨道-蒙卡·hft·实盘-4CAF50?style=for-the-badge" alt="三轨道">
  <img src="https://img.shields.io/badge/License-MIT-9B51E0?style=for-the-badge" alt="MIT License">
</p>

---

## 中文

### 项目简介

本仓库完整复现经典做市论文：

> **Marco Avellaneda & Sasha Stoikov, "High-frequency trading in a limit order book"**, *Quantitative Finance*, 8(3), 2008.

核心结论：**库存偏斜策略**（以库存保留价为报价中心）相比"对称挂中价"基准，以轻微让利为代价，将终端库存标准差与盈亏方差压低约 **3–4 倍**。这一结论在三条独立轨道上均成立。

---

### 三条复现轨道

| 轨道 | 引擎 | 数据 | 库存 std（库存策略 vs 对称） |
|------|------|------|------------------------------|
| **Track 0** | 纯 numpy/numba 蒙特卡洛 | 论文参数（自洽） | **2.93 vs 8.61**（γ=0.1，1000 路径） |
| **Track A** | hftbacktest 真实撮合引擎 | 真实 Binance SOLUSDT L2（4 窗口） | **1.88 vs 17.52** |
| **Track B** | Docker Hummingbot 纸面交易 | ETH-USDT 实时行情（虚拟账户） | **0.59 vs 2.27 手** |

三轨道一致验证：库存策略的库存波动约为对称基准的 **1/4 ∼ 1/9**。

---

### 模型核心公式

```
保留价    r(s,q,t) = s − q·γ·σ²·(T−t)                   [式 3.17]
最优价差  δᵃ+δᵇ   = (2/γ)·ln(1+γ/k) + γ·σ²·(T−t)       [式 3.18]
成交强度  λ(δ)    = A·exp(−k·δ)                           [式 2.11]
```

报价挂在保留价 `r` 两侧；`symmetric` 基准改用中价 `s`，其余相同。

---

### 目录结构

```
├── config.py                       # 论文全部参数（单一可信源）
├── src/
│   ├── as_model.py                 # 保留价/最优价差/成交强度 闭式公式
│   ├── simulate.py                 # numba 蒙特卡洛（@njit，秒级完成）
│   ├── metrics.py                  # 指标聚合 + LaTeX 表格生成
│   └── plotstyle.py                # 中文绘图风格统一（Microsoft YaHei）
├── track0_paper/
│   └── run_paper.py                # 复现论文表 1–3、图 1–4
├── track_a_hftbacktest/
│   ├── download_data.py            # 下载真实 Binance L2 → hftbacktest npz
│   ├── run_hft.py                  # A-S 做市策略（numba hbt 主循环）
│   └── run_real_windows.py         # 多窗口真实数据聚合
├── track_b_hummingbot/
│   ├── as_market_making.py         # Hummingbot v2 StrategyV2Base 实现
│   ├── parse_hummingbot_logs.py    # sqlite/CSV 成交日志 → 指标 JSON
│   ├── docker-compose.yml          # 一键启动 Hummingbot 容器
│   └── RUNBOOK.md                  # 交钥匙运行手册（headless + 交互两路径）
├── make_figures.py                 # 图 5–7（跨轨道对照）
├── results/                        # CSV / JSON 结果
├── figures/                        # PDF + PNG 图
└── report/
    ├── report.tex                  # 中文 XeLaTeX 报告（ctex，11 页）
    └── report.pdf                  # 编译好的 PDF
```

---

### 快速开始

#### 环境安装

```bash
pip install -r requirements.txt
```

> **依赖**：numpy, pandas, matplotlib, numba, scipy, hftbacktest≥2.4  
> **Hummingbot**：独立 Docker 运行时，见 `track_b_hummingbot/RUNBOOK.md`

#### Track 0 — 复现论文表 1–3 + 图 1–4（约 30 秒）

```bash
python track0_paper/run_paper.py
```

产出 `results/table_gamma_*.csv`、`figures/fig1–4_*.png`、`report/tables.tex`。

#### Track A — hftbacktest 真实 Binance 数据

```bash
# 下载 1 小时真实行情（约 37 MB）
python track_a_hftbacktest/download_data.py \
    --symbol SOLUSDT --date 2024-03-05 --start-hour 0 --end-hour 1

# 运行 A-S 做市回测
python track_a_hftbacktest/run_real_windows.py \
    --feeds track_a_hftbacktest/SOLUSDT-2024-03-05_h0-1.npz
```

#### Track B — Hummingbot Docker 纸面交易

```bash
cd track_b_hummingbot

# 1) 初始化密码（仅一次）
docker compose run --rm --no-TTY --entrypoint bash hummingbot -lc \
  "cd /home/hummingbot && PYTHONPATH=/home/hummingbot \
   /opt/conda/envs/hummingbot/bin/python data/init_password.py aspass123"

# 2) 跑库存策略（~9 分钟）
docker compose run --rm --no-TTY --entrypoint bash hummingbot -lc \
  "cd /home/hummingbot && timeout 540 env CONFIG_PASSWORD=aspass123 \
   PYTHONPATH=/home/hummingbot \
   /opt/conda/envs/hummingbot/bin/python bin/hummingbot_quickstart.py \
   -p aspass123 --v2 as_conf.yml --headless"

# 3) 解析成交日志 → 指标
cd ..
python track_b_hummingbot/parse_hummingbot_logs.py \
    --inventory track_b_hummingbot/hb-files/data/as_conf.sqlite \
    --symmetric track_b_hummingbot/hb-files/data/as_conf_sym.sqlite
```

完整步骤见 [`track_b_hummingbot/RUNBOOK.md`](track_b_hummingbot/RUNBOOK.md)。

#### 跨轨道对照图 + 报告

```bash
python make_figures.py
cd report && latexmk -xelatex report.tex
```

---

### 复现结果对照

#### Track 0 — 论文表 1（γ = 0.1，1000 路径）

| 策略 | 盈亏均值 | 盈亏 std | 终端库存均值 | 库存 std |
|------|:--------:|:--------:|:------------:|:--------:|
| **库存策略** | 64.28 | **5.97** | −0.10 | **2.93** |
| 对称基准 | 68.91 | 13.55 | −0.23 | 8.61 |
| 论文原值（库存） | 62.94 | 5.89 | 0.10 | 2.80 |
| 论文原值（对称） | 67.21 | 13.43 | −0.02 | 8.66 |

#### Track A — 真实 Binance SOLUSDT（4 窗口聚合）

| 策略 | 跨窗口盈亏均值 | 盈亏 std | 库存 std |
|------|:-------------:|:--------:|:--------:|
| **库存策略** | −31.7 | ±12.8 | **1.88** |
| 对称基准 | −12.1 | ±55.8 | 17.52 |

#### Track B — Hummingbot 真实纸面交易（ETH-USDT，各约 9 分钟）

| 策略 | 库存 std（手） | 库存峰值（手） | 成交笔数 |
|------|:--------------:|:--------------:|:--------:|
| **库存策略** | **0.59** | 1 | 18 |
| 对称基准 | 2.27 | 5 | 15 |

---

### 诚实局限

- **Track 0** 与原文高度一致（γ=0.5 最高风险厌恶时盈亏被偏斜压低，属预期行为）。
- **Track A/B** 定量以 Track 0 为准；框架轨道的价值在于验证"库存控制"这一**相对结论**在真实撮合引擎与实际部署节奏下依然成立。
- 真实行情含漂移与自相关（A-S 假设无漂移）；Hummingbot 按秒级刷新而非 tick 级。
- **Binance 公共归档仅提供 BBO**（盘口最优一档），无完整深度队列——Track A 的队列模型为近似。

---

### 参考文献

```bibtex
@article{avellaneda2008high,
  title   = {High-frequency trading in a limit order book},
  author  = {Avellaneda, Marco and Stoikov, Sasha},
  journal = {Quantitative Finance},
  volume  = {8},
  number  = {3},
  pages   = {217--224},
  year    = {2008}
}
```

---

## English

### Overview

A three-track reproduction of the classical market-making paper by Avellaneda & Stoikov (2008), using **pure Monte Carlo**, **hftbacktest** (real exchange microstructure), and **Hummingbot** (live Docker paper-trade). All three tracks confirm the paper's core finding: inventory-skewed quotes cut inventory variance by **3–4×** versus a symmetric benchmark.

---

### Three Tracks

| Track | Engine | Data | Inventory std (inventory vs symmetric) |
|-------|--------|------|----------------------------------------|
| **Track 0** | numpy/numba Monte Carlo | Paper parameters | **2.93 vs 8.61** (γ=0.1, 1 000 paths) |
| **Track A** | hftbacktest real matching | Real Binance SOLUSDT L2 (4 windows) | **1.88 vs 17.52** |
| **Track B** | Docker Hummingbot paper-trade | ETH-USDT live quotes (virtual account) | **0.59 vs 2.27 lots** |

---

### Core Equations

```
Reservation price  r(s,q,t) = s − q·γ·σ²·(T−t)              [Eq. 3.17]
Optimal spread     δᵃ+δᵇ   = (2/γ)·ln(1+γ/k) + γ·σ²·(T−t)  [Eq. 3.18]
Fill intensity     λ(δ)    = A·exp(−k·δ)                      [Eq. 2.11]
```

---

### Quick Start

```bash
pip install -r requirements.txt

# Track 0 — reproduce Tables 1–3, Figures 1–4
python track0_paper/run_paper.py

# Track A — real Binance data
python track_a_hftbacktest/download_data.py --symbol SOLUSDT --date 2024-03-05 --start-hour 0 --end-hour 1
python track_a_hftbacktest/run_real_windows.py --feeds track_a_hftbacktest/SOLUSDT-2024-03-05_h0-1.npz

# Track B — see track_b_hummingbot/RUNBOOK.md for the full Docker walkthrough

# Cross-track figures + LaTeX report
python make_figures.py
cd report && latexmk -xelatex report.tex
```

---

### Honest Limitations

- Track A uses BBO-only Binance public archive (no full depth); queue model is approximate.
- Track B runs at second-level refresh, not tick-level. Quantitative comparisons should be anchored to Track 0.
- Real quotes contain drift and autocorrelation that A-S's arithmetic-Brownian assumption ignores.

---

### License

This project is licensed under the **MIT License** — see [`LICENSE`](LICENSE) for details.
