"""Smoke-test: does our A-S strategy load inside the real Hummingbot runtime?

Run inside the hummingbot container (entrypoint overridden to python):
    docker compose run --rm --entrypoint python hummingbot data/check_env.py
"""
import importlib.util
import sys

print("python", sys.version.split()[0])

# 1) the real Hummingbot v2 strategy base must import
from hummingbot.strategy.strategy_v2_base import StrategyV2Base  # noqa: E402
from hummingbot.core.data_type.order_candidate import OrderCandidate     # noqa: E402
from hummingbot.core.data_type.common import OrderType, PriceType, TradeType  # noqa: E402
print("hummingbot v2 core imports OK")

# 2) our strategy file must import and expose the strategy + config classes
spec = importlib.util.spec_from_file_location(
    "as_mm", "/home/hummingbot/scripts/as_market_making.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
cls = m.AvellanedaStoikovMM
cfg = m.ASConfig
assert issubclass(cls, StrategyV2Base), "strategy is not a StrategyV2Base"
print("strategy loaded:", cls.__name__)
c = cfg()  # instantiate the pydantic config with defaults
print("  exchange      :", c.exchange)
print("  trading_pair  :", c.trading_pair)
print("  gamma/kappa   :", c.gamma, "/", c.kappa)
print("  inventory_skew:", c.inventory_skew)
print("ALL CHECKS PASSED")
