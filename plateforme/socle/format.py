"""Mise en forme des nombres."""

from __future__ import annotations


def nb(valeur: float, decimales: int = 1) -> str:
    """Nombre au format français : virgule décimale, espace fine entre milliers."""
    return f"{valeur:,.{decimales}f}".replace(",", " ").replace(".", ",")


def texte(valeur) -> str:
    """Valeur d'hypothèse lisible."""
    if isinstance(valeur, bool):
        return "oui" if valeur else "non"
    if isinstance(valeur, (int, float)):
        return nb(valeur, 0 if float(valeur) == int(valeur) else 1)
    return str(valeur)
