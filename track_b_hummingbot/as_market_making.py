"""Avellaneda-Stoikov market making as a Hummingbot **v2** script.

Targets the current Hummingbot scripts API (``StrategyV2Base`` + a pydantic
``StrategyV2ConfigBase``), which is what recent Hummingbot images ship. (The older
``ScriptStrategyBase`` API was removed; this file was validated to load inside the
official ``hummingbot/hummingbot:latest`` container.)

Copy into your Hummingbot install under ``scripts/`` and start it with
``start --script as_market_making.py``. It implements the same quoting rule
reproduced elsewhere in this project:

    reservation price   r = mid - q * gamma * sigma^2 * (T - t)        (Eq. 3.17)
    optimal spread      d = gamma * sigma^2 * (T - t)
                            + (2/gamma) * ln(1 + gamma/kappa)          (Eq. 3.18)

The bid/ask are placed at ``r -/+ d/2``. Set ``inventory_skew=False`` for the
paper's "symmetric" benchmark (quotes centred on the mid). The inventory ``q`` is
the net filled position measured in units of ``order_amount`` (tracked from fills),
matching the paper's integer-inventory semantics.

The offline, self-contained reproduction of the same logic lives in
run_hummingbot_sim.py; the real fill logs are parsed by parse_hummingbot_logs.py.
"""

import logging
import math
import os
from collections import deque
from decimal import Decimal
from typing import Dict, List

from pydantic import Field

from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.data_type.common import MarketDict, OrderType, PriceType, TradeType
from hummingbot.core.data_type.order_candidate import OrderCandidate
from hummingbot.core.event.events import OrderFilledEvent
from hummingbot.strategy.strategy_v2_base import StrategyV2Base, StrategyV2ConfigBase


class ASConfig(StrategyV2ConfigBase):
    script_file_name: str = os.path.basename(__file__)
    controllers_config: List[str] = []
    exchange: str = Field("binance_paper_trade")
    trading_pair: str = Field("ETH-USDT")
    order_amount: Decimal = Field(Decimal("0.02"))
    order_refresh_time: int = Field(5)          # seconds between requotes
    gamma: float = Field(0.1)                   # risk aversion (skew < half-spread)
    kappa: float = Field(1.5)                   # order-book liquidity (k)
    horizon: float = Field(1.0)                 # A-S (T - t), held constant
    vol_window: int = Field(60)                 # samples used to estimate sigma
    inventory_skew: bool = Field(True)          # False -> symmetric benchmark

    def update_markets(self, markets: MarketDict) -> MarketDict:
        markets[self.exchange] = markets.get(self.exchange, set()) | {self.trading_pair}
        return markets


class AvellanedaStoikovMM(StrategyV2Base):
    create_timestamp = 0

    def __init__(self, connectors: Dict[str, ConnectorBase], config: ASConfig):
        super().__init__(connectors, config)
        self.config = config
        self._mids = deque(maxlen=config.vol_window)
        self._inventory = 0.0   # net filled position, in units of order_amount

    # --- main loop ----------------------------------------------------------
    def on_tick(self):
        mid = self.connectors[self.config.exchange].get_price_by_type(
            self.config.trading_pair, PriceType.MidPrice)
        if mid is not None:
            self._mids.append(float(mid))
        if self.create_timestamp > self.current_timestamp:
            return
        sigma = self._estimate_sigma()
        if sigma is None or mid is None:
            return
        self.cancel_all_orders()
        proposal = self._create_proposal(float(mid), sigma)
        proposal = self.adjust_proposal_to_budget(proposal)
        self.place_orders(proposal)
        self.create_timestamp = self.config.order_refresh_time + self.current_timestamp

    # --- A-S quoting --------------------------------------------------------
    def _estimate_sigma(self):
        if len(self._mids) < self.config.vol_window:
            return None
        p = list(self._mids)
        diffs = [p[i + 1] - p[i] for i in range(len(p) - 1)]
        mean = sum(diffs) / len(diffs)
        var = sum((d - mean) ** 2 for d in diffs) / max(1, len(diffs) - 1)
        return math.sqrt(var)

    def _create_proposal(self, mid: float, sigma: float) -> List[OrderCandidate]:
        g, k, T = self.config.gamma, self.config.kappa, self.config.horizon
        q = self._inventory if self.config.inventory_skew else 0.0
        skew = q * g * sigma * sigma * T                                   # Eq. 3.17
        spread = g * sigma * sigma * T + (2.0 / g) * math.log(1.0 + g / k)  # Eq. 3.18
        reservation = mid - skew
        bid = Decimal(str(reservation - spread / 2.0))
        ask = Decimal(str(reservation + spread / 2.0))
        amt = Decimal(self.config.order_amount)
        buy = OrderCandidate(trading_pair=self.config.trading_pair, is_maker=True,
                             order_type=OrderType.LIMIT, order_side=TradeType.BUY,
                             amount=amt, price=bid)
        sell = OrderCandidate(trading_pair=self.config.trading_pair, is_maker=True,
                              order_type=OrderType.LIMIT, order_side=TradeType.SELL,
                              amount=amt, price=ask)
        return [buy, sell]

    # --- order plumbing (mirrors the shipped simple_pmm example) -----------
    def adjust_proposal_to_budget(self, proposal: List[OrderCandidate]) -> List[OrderCandidate]:
        return self.connectors[self.config.exchange].budget_checker.adjust_candidates(
            proposal, all_or_none=False)

    def place_orders(self, proposal: List[OrderCandidate]) -> None:
        for order in proposal:
            self.place_order(self.config.exchange, order)

    def place_order(self, connector_name: str, order: OrderCandidate):
        if order.amount <= Decimal("0"):
            return
        if order.order_side == TradeType.SELL:
            self.sell(connector_name=connector_name, trading_pair=order.trading_pair,
                      amount=order.amount, order_type=order.order_type, price=order.price)
        else:
            self.buy(connector_name=connector_name, trading_pair=order.trading_pair,
                     amount=order.amount, order_type=order.order_type, price=order.price)

    def cancel_all_orders(self):
        for order in self.get_active_orders(connector_name=self.config.exchange):
            self.cancel(self.config.exchange, order.trading_pair, order.client_order_id)

    def did_fill_order(self, event: OrderFilledEvent):
        # net inventory in units of order_amount (the paper's integer inventory)
        unit = float(self.config.order_amount)
        delta = (float(event.amount) / unit) if unit else 0.0
        self._inventory += delta if event.trade_type == TradeType.BUY else -delta
        self.log_with_clock(
            logging.INFO,
            f"{event.trade_type.name} {float(event.amount)} {event.trading_pair} "
            f"@ {float(event.price)} | inv={self._inventory:.2f}")
