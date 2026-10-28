"""Crossover between quantum search time and classical time (V2 16.1). All [ESTIMATED].
T_q = Q * G * t_T / sqrt(Pq) with Q = c_q*sqrt(N/M);   T_c = kappa * N^alpha * t_c / P.
N* solves T_q = T_c:  N^(alpha-1/2) = c_q*G*t_T*P / (kappa*t_c*sqrt(Pq)*sqrt(M)).  alpha <= 1/2 -> no asymptotic crossover (inf)."""
from __future__ import annotations
from math import comb, inf, log, sqrt

def quantum_time(N: float, G: float, t_T: float, c_q: float, M: float = 1, Pq: float = 1) -> float:
    return c_q * sqrt(N / M) * G * t_T / sqrt(Pq)

def classical_time(N: float, t_c: float, P: float = 1, kappa: float = 1.0, alpha: float = 1.0) -> float:
    return kappa * N ** alpha * t_c / P

def crossover_N(G: float, t_T: float, t_c: float, P: float, c_q: float, Pq: float = 1, kappa: float = 1.0, alpha: float = 1.0, M: float = 1) -> float:
    if alpha <= 0.5: return inf
    rhs = c_q * G * t_T * P / (kappa * t_c * sqrt(Pq) * sqrt(M))
    return rhs ** (1.0 / (alpha - 0.5))

def crossover_numeric(G, t_T, t_c, P, c_q, Pq=1, kappa=1.0, alpha=1.0, M=1, lo=1.0, hi=1e300) -> float:
    """Independent check: bisection on log N of T_q(N) = T_c(N) (T_q/T_c is monotone decreasing in N for alpha > 1/2)."""
    if alpha <= 0.5: return inf
    f = lambda lg: log(quantum_time(2.718281828459045 ** lg, G, t_T, c_q, M, Pq)) - log(classical_time(2.718281828459045 ** lg, t_c, P, kappa, alpha))
    a, b = log(lo), log(hi) if hi < 1e300 else 690.0
    if f(a) < 0: return lo
    for _ in range(300):
        mid = 0.5 * (a + b)
        if f(mid) > 0: a = mid
        else: b = mid
    return 2.718281828459045 ** (0.5 * (a + b))

def k_bracket(L: int, N: float):
    """(k_low, k_high) with C(L,k_low) <= N < C(L,k_high); k_low=0 if N < C(L,1)."""
    k = 0
    while k < L and comb(L, k + 1) <= N and comb(L, k + 1) >= comb(L, k): k += 1
    return k, (k + 1 if k < L else None)
