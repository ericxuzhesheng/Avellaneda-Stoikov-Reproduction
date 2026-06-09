"""Monte-Carlo simulation of the Avellaneda-Stoikov market-making experiment.

Faithfully follows the simulation procedure of paper Section 3.3:

  * at time t the agent computes its bid/ask quote distances d_b, d_a;
  * at t+dt the state is updated:
      - with prob lambda_a(d_a)*dt an ask fill occurs: q -= 1, cash += s + d_a
      - with prob lambda_b(d_b)*dt a bid fill occurs:  q += 1, cash -= s - d_b
      - the mid-price moves by a random increment +/- sigma*sqrt(dt);
  * terminal P&L = cash + q * S_T.

The "inventory" strategy centres quotes on the reservation price r(s,q,t);
the "symmetric" benchmark centres the same spread on the mid-price s.
"""

import math

import numpy as np
from numba import njit


# Strategy codes for the jitted kernel.
INVENTORY = 0
SYMMETRIC = 1


@njit(cache=True)
def _simulate_batch(n_sims, n_steps, s0, T, sigma, dt, q0, gamma, k, A, strategy, seed):
    """Run n_sims independent paths; return (profit[], final_q[])."""
    np.random.seed(seed)
    profit = np.empty(n_sims, dtype=np.float64)
    final_q = np.empty(n_sims, dtype=np.float64)

    sqrt_dt = math.sqrt(dt)
    # The paper quotes the constant (stationary) spread (2/gamma)*ln(1+gamma/k):
    # this is exactly the single "Spread" value reported in Tables 1-3
    # (1.29 / 1.33 / 1.15) and it makes the symmetric benchmark's profit
    # gamma-invariant, as observed in the paper. The time-varying term
    # gamma*sigma^2*(T-t) enters only through the reservation-price skew.
    half_spread = 0.5 * (2.0 / gamma) * math.log(1.0 + gamma / k)

    for sim in range(n_sims):
        s = s0
        q = q0
        cash = 0.0
        for i in range(n_steps):
            t_rem = T - i * dt
            inv_term = q * gamma * sigma * sigma * t_rem  # q*gamma*sigma^2*(T-t)

            if strategy == INVENTORY:
                # quotes centred on reservation price r = s - inv_term
                delta_a = -inv_term + half_spread
                delta_b = inv_term + half_spread
            else:  # SYMMETRIC: quotes centred on the mid-price
                delta_a = half_spread
                delta_b = half_spread

            # Poisson fill probabilities over the step (clamped to [0,1]).
            lam_a_dt = A * math.exp(-k * delta_a) * dt
            lam_b_dt = A * math.exp(-k * delta_b) * dt
            if lam_a_dt > 1.0:
                lam_a_dt = 1.0
            if lam_b_dt > 1.0:
                lam_b_dt = 1.0

            if np.random.random() < lam_a_dt:   # ask lifted -> we sell at s + delta_a
                q -= 1
                cash += s + delta_a
            if np.random.random() < lam_b_dt:   # bid hit -> we buy at s - delta_b
                q += 1
                cash -= s - delta_b

            # mid-price random walk: +/- sigma*sqrt(dt) with equal probability
            if np.random.random() < 0.5:
                s += sigma * sqrt_dt
            else:
                s -= sigma * sqrt_dt

        profit[sim] = cash + q * s
        final_q[sim] = q

    return profit, final_q


def simulate(params, gamma, strategy, n_sims, seed):
    """Convenience wrapper around the jitted kernel.

    Returns a dict with profit/final_q arrays and their summary statistics.
    """
    strat_code = INVENTORY if strategy == "inventory" else SYMMETRIC
    profit, final_q = _simulate_batch(
        n_sims, params.n_steps, params.s0, params.T, params.sigma, params.dt,
        params.q0, gamma, params.k, params.A, strat_code, seed,
    )
    return {
        "profit": profit,
        "final_q": final_q,
        "profit_mean": float(np.mean(profit)),
        "profit_std": float(np.std(profit)),
        "final_q_mean": float(np.mean(final_q)),
        "final_q_std": float(np.std(final_q)),
    }


@njit(cache=True)
def _simulate_trace(n_steps, s0, T, sigma, dt, q0, gamma, k, A, seed):
    """Single inventory-strategy path; record mid/reservation/bid/ask/inventory."""
    np.random.seed(seed)
    mid = np.empty(n_steps + 1)
    reservation = np.empty(n_steps + 1)
    bid = np.empty(n_steps + 1)
    ask = np.empty(n_steps + 1)
    inv = np.empty(n_steps + 1)

    sqrt_dt = math.sqrt(dt)
    half_spread = 0.5 * (2.0 / gamma) * math.log(1.0 + gamma / k)

    s = s0
    q = q0
    cash = 0.0
    for i in range(n_steps):
        t_rem = T - i * dt
        inv_term = q * gamma * sigma * sigma * t_rem
        r = s - inv_term
        delta_a = -inv_term + half_spread
        delta_b = inv_term + half_spread

        mid[i] = s
        reservation[i] = r
        ask[i] = s + delta_a
        bid[i] = s - delta_b
        inv[i] = q

        lam_a_dt = min(A * math.exp(-k * delta_a) * dt, 1.0)
        lam_b_dt = min(A * math.exp(-k * delta_b) * dt, 1.0)
        if np.random.random() < lam_a_dt:
            q -= 1
            cash += s + delta_a
        if np.random.random() < lam_b_dt:
            q += 1
            cash -= s - delta_b
        if np.random.random() < 0.5:
            s += sigma * sqrt_dt
        else:
            s -= sigma * sqrt_dt

    # final point
    mid[n_steps] = s
    reservation[n_steps] = s - q * gamma * sigma * sigma * 0.0
    ask[n_steps] = s
    bid[n_steps] = s
    inv[n_steps] = q
    return mid, reservation, bid, ask, inv


@njit(cache=True)
def _simulate_stale(n_sims, n_steps, s0, T, sigma, dt, q0, gamma, k, A,
                    strategy, requote_every, seed):
    """Like _simulate_batch but quotes are refreshed only every `requote_every`
    fine steps (held stale in between), modelling Hummingbot's order_refresh_time
    while the market keeps trading on the fine clock."""
    np.random.seed(seed)
    profit = np.empty(n_sims, dtype=np.float64)
    final_q = np.empty(n_sims, dtype=np.float64)

    sqrt_dt = math.sqrt(dt)
    half_spread = 0.5 * (2.0 / gamma) * math.log(1.0 + gamma / k)

    for sim in range(n_sims):
        s = s0
        q = q0
        cash = 0.0
        p_a = s0 + half_spread   # current resting ask price
        p_b = s0 - half_spread   # current resting bid price
        for i in range(n_steps):
            if i % requote_every == 0:  # refresh quotes (prices fixed until next refresh)
                t_rem = T - i * dt
                inv_term = q * gamma * sigma * sigma * t_rem
                reservation = s - inv_term if strategy == INVENTORY else s
                p_a = reservation + half_spread
                p_b = reservation - half_spread

            delta_a = p_a - s   # distance of (stale) quotes to the moving mid
            delta_b = s - p_b
            lam_a_dt = min(A * math.exp(-k * delta_a) * dt, 1.0)
            lam_b_dt = min(A * math.exp(-k * delta_b) * dt, 1.0)
            if np.random.random() < lam_a_dt:
                q -= 1
                cash += p_a
            if np.random.random() < lam_b_dt:
                q += 1
                cash -= p_b
            if np.random.random() < 0.5:
                s += sigma * sqrt_dt
            else:
                s -= sigma * sqrt_dt

        profit[sim] = cash + q * s
        final_q[sim] = q
    return profit, final_q


def simulate_stale(params, gamma, strategy, n_sims, requote_every, seed):
    """Hummingbot-cadence wrapper: refresh quotes every `requote_every` steps."""
    strat_code = INVENTORY if strategy == "inventory" else SYMMETRIC
    profit, final_q = _simulate_stale(
        n_sims, params.n_steps, params.s0, params.T, params.sigma, params.dt,
        params.q0, gamma, params.k, params.A, strat_code, requote_every, seed,
    )
    return {
        "profit": profit,
        "final_q": final_q,
        "profit_mean": float(np.mean(profit)),
        "profit_std": float(np.std(profit)),
        "final_q_mean": float(np.mean(final_q)),
        "final_q_std": float(np.std(final_q)),
    }


def simulate_trace(params, gamma, seed):
    """Return a single representative inventory-strategy path for Figure 1."""
    mid, reservation, bid, ask, inv = _simulate_trace(
        params.n_steps, params.s0, params.T, params.sigma, params.dt,
        params.q0, gamma, params.k, params.A, seed,
    )
    t = np.linspace(0.0, params.T, params.n_steps + 1)
    return {"t": t, "mid": mid, "reservation": reservation, "bid": bid, "ask": ask, "inv": inv}
