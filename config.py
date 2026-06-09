"""Single source of truth for the Avellaneda-Stoikov (2008) reproduction.

All parameters are taken verbatim from Section 3.3 of:
    Marco Avellaneda & Sasha Stoikov,
    "High-frequency trading in a limit order book", Quantitative Finance (2008).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ASParams:
    """Parameters of the Avellaneda-Stoikov numerical experiment (paper Sec. 3.3)."""

    s0: float = 100.0     # initial mid-price
    T: float = 1.0        # terminal time (one trading "session")
    sigma: float = 2.0    # mid-price volatility (arithmetic BM, dS = sigma dW)
    dt: float = 0.005     # simulation time step -> N = T/dt = 200 steps
    q0: int = 0           # initial inventory
    gamma: float = 0.1    # risk aversion (varied: 0.1, 0.01, 0.5 -> Tables 1, 2, 3)
    k: float = 1.5        # order-book decay parameter in lambda(d) = A*exp(-k*d)
    A: float = 140.0      # base order arrival intensity

    @property
    def n_steps(self) -> int:
        return int(round(self.T / self.dt))


# The three risk-aversion settings reproduced in the paper (Tables 1-3).
GAMMA_TABLE = {
    "table1_gamma_0.1": 0.1,
    "table2_gamma_0.01": 0.01,
    "table3_gamma_0.5": 0.5,
}

# Number of Monte-Carlo paths per setting (paper: "1000 simulations").
N_SIMS = 1000

# Fixed seed for reproducibility of our run (paper does not publish its seed).
SEED = 20260608

# Paper's published results, for side-by-side validation in the report.
# Columns: (Profit, std(Profit), Final q, std(Final q))
PAPER_RESULTS = {
    0.1: {
        "inventory": (62.94, 5.89, 0.10, 2.80),
        "symmetric": (67.21, 13.43, -0.018, 8.66),
    },
    0.01: {
        "inventory": (66.78, 8.76, -0.02, 4.70),
        "symmetric": (67.36, 13.40, -0.31, 8.65),
    },
    0.5: {
        "inventory": (33.92, 4.72, -0.02, 1.88),
        "symmetric": (66.20, 14.53, 0.25, 9.06),
    },
}
