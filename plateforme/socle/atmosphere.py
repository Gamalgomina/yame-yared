"""Atmosphère : pression, température et densité de l'air au point de vol."""

from __future__ import annotations

from dataclasses import dataclass

R_AIR = 287.05  # J/(kg.K)
G = 9.80665  # m/s2
DENSITE_NIVEAU_MER = 1.225  # kg/m3


@dataclass(frozen=True)
class Air:
    pression: float  # Pa
    temperature: float  # K
    densite: float  # kg/m3


def air(altitude_m: float, temperature_sol_c: float, altitude_sol_m: float = 0.0) -> Air:
    """Air à une altitude donnée, pour une température mesurée au sol.

    Pression : atmosphère standard. Température : celle du sol, moins 6,5 °C
    par 1000 m de hauteur. Un jour chaud donne donc un air moins dense que
    l'atmosphère standard, ce qui pénalise l'aile, l'hélice et le moteur.
    """
    pression = 101325.0 * (1.0 - 2.25577e-5 * altitude_m) ** 5.25588
    temperature = temperature_sol_c + 273.15 - 0.0065 * (altitude_m - altitude_sol_m)
    return Air(pression, temperature, pression / (R_AIR * temperature))
