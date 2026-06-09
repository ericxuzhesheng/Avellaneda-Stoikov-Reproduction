# Track B — Hummingbot 上的 Avellaneda–Stoikov 做市

本轨道把 A–S 做市策略表达为 **Hummingbot 的编程模型**，并诚实标注其局限。

## 两个交付物

1. **`as_market_making.py`** — 可直接放入真实 Hummingbot 运行时的 v2 脚本
   （`ScriptStrategyBase` + `OrderCandidate`）。它显式实现 A–S 的保留价（式 3.17）
   与最优价差（式 3.18），并暴露 `gamma / kappa / horizon / inventory_skew` 参数，
   把"论文 ↔ Hummingbot"的映射写在明处。把 `inventory_skew=False` 即得论文的
   "symmetric" 基准。Hummingbot 内置的 `avellaneda_market_making` 策略用的是同一套
   A–S 公式，本脚本只是把参数摊开以便对照。

2. **`run_hummingbot_sim.py`** — **离线复现**。无需安装 Hummingbot 重型运行时
   （conda/Docker/连接器），即可看到论文效应。它复用本项目唯一的 A–S 数学实现
   （`src/simulate.py`），但按 Hummingbot 的 `order_refresh_time` **粗刷新节奏**运行：
   行情仍在论文的精细时钟（dt=0.005）上成交，而报价每 `REQUOTE_EVERY` 个 tick 才刷新一次，
   其间报价"陈旧"。这正是真实 Hummingbot 部署区别于论文理想高频仿真之处。

## 在真实 Hummingbot 中运行

```bash
# 在 Hummingbot 安装目录中
cp as_market_making.py <hummingbot>/scripts/
# 进入 Hummingbot CLI（已配置 binance_paper_trade）
start --script as_market_making.py
```

## 离线复现

```bash
python track_b_hummingbot/run_hummingbot_sim.py             # 默认 gamma=0.1, requote_every=5
python track_b_hummingbot/run_hummingbot_sim.py --requote-every 20   # 观察刷新越慢、盈亏越受陈旧报价侵蚀
```

## 诚实局限（写入报告）

- Hummingbot 面向真实/模拟交易所、按**秒级**而非 tick 级运行，缺乏 tick 级队列位置模型；
  只能复现 A–S 报价逻辑与"库存控制"的定性效果，**定量偏离论文最大**。
- 报价刷新越慢（`REQUOTE_EVERY` 越大），库存控制越滞后、陈旧报价的逆向成交越侵蚀盈亏——
  这是 Hummingbot 这类秒级做市机器人相对论文理想高频仿真的真实代价。
- `gamma` 不能取太大：当库存偏斜系数 `gamma*sigma^2*(T-t)` 超过半价差时，陈旧报价会被迫在
  远离中价处保证成交而巨亏（本项目实测 gamma=0.5 时如此），故取 gamma=0.1 使偏斜小于半价差。
- 完整 Hummingbot 运行时在本机（Python 3.13 / Windows）安装受阻，故离线轨道是 **API 级对齐 +
  同一 A–S 数学**，而非完整运行时回测。
