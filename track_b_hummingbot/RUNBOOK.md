# Track B 交钥匙运行手册 —— 在真实 Hummingbot 中跑 Avellaneda–Stoikov 做市

本手册让你在本地用**真实的 Hummingbot 运行时**（Docker）跑本仓库的 A–S 策略
（`as_market_making.py`），用 **Binance 纸面交易（paper trade，不需真钱、不需 API Key）**
采集成交日志，再用 `parse_hummingbot_logs.py` 把日志转成与其它轨道一致的指标，自动并入报告与图。

本仓库提供两条路径：**方式一（headless 自动运行，本文已实测跑通，推荐复现）** 与
**方式二（交互式 TUI，适合手动操作）**。

---

## 方式一：headless 自动运行（本文已实测）

当前官方镜像已切到 **v2 脚本 API**（`StrategyV2Base`），`as_market_making.py` 已据此移植；
配置走 `conf/scripts/*.yml`（`as_conf.yml` = 库存策略，`as_conf_sym.yml` = 对称基准，二者仅
`inventory_skew` 不同）。`docker` 路径下文均假设已加入 PATH（Docker Desktop 的
`resources\bin`）。

```bash
cd track_b_hummingbot
mkdir -p hb-files/conf/scripts hb-files/logs hb-files/data
# 1) 初始化密码校验文件（headless 登录所需，仅一次）
docker compose run --rm --no-TTY --entrypoint bash hummingbot -lc \
  "cd /home/hummingbot && PYTHONPATH=/home/hummingbot /opt/conda/envs/hummingbot/bin/python data/init_password.py aspass123"

# 2) 跑库存策略约 9 分钟（写 data/as_conf.sqlite）
docker compose run --rm --no-TTY --entrypoint bash hummingbot -lc \
  "cd /home/hummingbot && rm -f data/as_conf.sqlite && timeout 540 env PYTHONPATH=/home/hummingbot CONFIG_PASSWORD=aspass123 \
   /opt/conda/envs/hummingbot/bin/python bin/hummingbot_quickstart.py -p aspass123 --v2 as_conf.yml --headless"

# 3) 跑对称基准约 9 分钟（写 data/as_conf_sym.sqlite）
docker compose run --rm --no-TTY --entrypoint bash hummingbot -lc \
  "cd /home/hummingbot && rm -f data/as_conf_sym.sqlite && timeout 540 env PYTHONPATH=/home/hummingbot CONFIG_PASSWORD=aspass123 \
   /opt/conda/envs/hummingbot/bin/python bin/hummingbot_quickstart.py -p aspass123 --v2 as_conf_sym.yml --headless"

# 4) 解析两个真实数据库 -> results/track_b_real_summary.json
cd ..
python track_b_hummingbot/parse_hummingbot_logs.py \
    --inventory track_b_hummingbot/hb-files/data/as_conf.sqlite \
    --symmetric track_b_hummingbot/hb-files/data/as_conf_sym.sqlite
python make_figures.py
cd report && latexmk -xelatex report.tex
```

运行越久（加大 `timeout`）成交越多、统计越平滑。`data/init_password.py` 与
`data/check_env.py`（在真实运行时校验策略可加载）随仓提供。

---

## 方式二：交互式 TUI（手动操作）

> Hummingbot 也可作为**交互式 TUI** 手动操作；下列为该路径。

---

## 0. 前置条件

- 安装 **Docker Desktop**（Windows/Mac）或 Docker Engine（Linux），并启动。
- 本目录（`track_b_hummingbot/`）即工作目录，已包含：
  - `docker-compose.yml` —— 启动 Hummingbot 容器，并把 `as_market_making.py` 挂进 `scripts/`
  - `as_market_making.py` —— A–S 策略（Hummingbot v2 `StrategyV2Base`，含库存偏斜开关）
  - `parse_hummingbot_logs.py` —— 成交日志 → 指标解析器

## 1. 准备持久化目录

```bash
cd track_b_hummingbot
mkdir -p hb-files/conf/connectors hb-files/conf/strategies hb-files/logs hb-files/data hb-files/certs
```

## 2. 首次启动并设置密码

```bash
docker compose run --rm hummingbot
```

首次进入会要求**设置一个配置密码**（自定义，记住即可）。进入 Hummingbot 终端后看到 `>>>` 提示符。

## 3. 连接 Binance 纸面交易（无需 API Key）

在 Hummingbot 提示符内：

```
>>>  connect binance_paper_trade
```

纸面交易使用 Binance 的实时行情但**虚拟撮合、虚拟余额**，无需真实密钥与资金。
可选：用 `balance paper` 查看/设置纸面账户的初始余额。

## 4. 第一次运行：库存策略（inventory）

`as_market_making.py` 顶部参数 `inventory_skew = True` 即库存偏斜（A–S 主策略）。直接启动：

```
>>>  start --script as_market_making.py
```

让其运行一段时间（建议 **≥ 2 小时**以累积足够成交；越久越稳）。期间可用 `status` 查看持仓与挂单。
结束后：

```
>>>  stop
```

导出该段成交日志（二选一）：
- 直接使用容器写入的数据库：`hb-files/data/*.sqlite`（表 `TradeFill`）；或
- 在 Hummingbot 内执行 `export trades`，得到 `hb-files/data/trades_*.csv`。

把这份日志**改名**以区分变体，例如：
```bash
cp hb-files/data/trades_*.csv hb-files/data/trades_inventory.csv
```

## 5. 第二次运行：对称基准（symmetric）

编辑 `as_market_making.py`，把 `inventory_skew = False`（仅关闭库存偏斜，价差不变），保存。
重复第 4 步（同样 ≥ 2 小时），结束后导出并改名：
```bash
cp hb-files/data/trades_*.csv hb-files/data/trades_symmetric.csv
```

> 提示：两段运行尽量等长、时间相邻，使两者面对的行情可比。

## 6. 解析日志 → 生成指标（回到项目根目录）

```bash
cd ..
python track_b_hummingbot/parse_hummingbot_logs.py \
    --inventory track_b_hummingbot/hb-files/data/trades_inventory.csv \
    --symmetric track_b_hummingbot/hb-files/data/trades_symmetric.csv
```

也支持直接读 sqlite：`--inventory .../xxx.sqlite`（自动读 `TradeFill` 表）。

这会写出 `results/track_b_real_summary.json` 与 `results/track_b_real_timeseries.npz`
（schema 与其它轨道一致）。

## 7. 重新出图与编译报告

```bash
python make_figures.py                 # fig6 会自动多出 "Track B(真实)" 柱
cd report && latexmk -xelatex report.tex
```

报告中的"Track B 真实 paper-trade"小节会自动反映你的真实运行结果。

---

## 验证解析器（无需 Hummingbot）

在跑真实运行之前，可先用内置样本验证整条管道是否通畅：

```bash
python track_b_hummingbot/parse_hummingbot_logs.py --make-sample
```

这会生成 `sample_trades_{inventory,symmetric}.csv` 并解析为
`results/track_b_sample_summary.json`（样本仅用于验证管道，**不会**写入真实结果槽
`track_b_real_summary.json`）。样本即可观察到库存策略库存标准差远小于对称基准的预期形态。

---

## 常见问题（Gotchas）

- **看不到成交**：纸面盘口价差若长期窄于策略半价差，则不会成交；适当调小
  `as_market_making.py` 的 `gamma` 或缩短刷新 `order_refresh_time`，并保证运行足够久。
- **`gamma` 不要过大**：当库存偏斜量 `gamma*sigma^2*(T-t)` 超过半价差时，陈旧报价会被迫在
  远离中价处保证成交而巨亏。默认 `gamma=0.1` 已使偏斜小于半价差。
- **时间戳单位**：Hummingbot 成交时间戳为毫秒；解析器会自动归一化为相对秒。
- **两段运行长度不一致**：会影响可比性；尽量等长、相邻。
- **容器内找不到脚本**：确认 `docker-compose.yml` 的挂载路径与本文件同级，且
  `as_market_making.py` 存在。
