"""Closed-form Avellaneda-Stoikov quoting formulas (paper Sec. 2-3).

These pure functions implement the approximate (linearised) solution that the
paper itself uses for its simulations:

    reservation price        r(s,q,t) = s - q*gamma*sigma^2*(T-t)          (Eq. 3.17)
    optimal total spread     d_a + d_b = gamma*sigma^2*(T-t)
                                          + (2/gamma)*ln(1 + gamma/k)      (Eq. 3.18)
    fill intensity           lambda(d) = A*exp(-k*d)                       (Eq. 2.11)

The "inventory" strategy centres the quotes on r; the "symmetric" benchmark
centres the same spread on the mid-price s.
"""

import math


def reservation_price(s: float, q: int, gamma: float, sigma: float, t_remaining: float) -> float:
    """Indifference / reservation price r(s, q, t)  (Eq. 3.17)."""
    return s - q * gamma * sigma * sigma * t_remaining


def optimal_total_spread(gamma: float, sigma: float, k: float, t_remaining: float) -> float:
    """Optimal bid-ask spread d_a + d_b  (Eq. 3.18)."""
    return gamma * sigma * sigma * t_remaining + (2.0 / gamma) * math.log(1.0 + gamma / k)


def fill_intensity(delta: float, A: float, k: float) -> float:
    """Poisson arrival intensity lambda(delta) = A*exp(-k*delta)  (Eq. 2.11)."""
    return A * math.exp(-k * delta)
