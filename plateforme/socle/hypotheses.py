"""Registre d'hypothèses.

Chaque valeur utilisée par la plateforme est enregistrée avec son origine :
- "utilisateur" : donnée par la personne qui décrit le besoin ;
- "déduit"      : tirée d'une réponse de l'utilisateur ;
- "défaut"      : comblée par la plateforme, avec la raison du choix.

Le rapport affiche ce registre pour que rien ne soit décidé en silence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Hypothese:
    cle: str
    libelle: str
    valeur: Any
    unite: str
    origine: str
    raison: str


@dataclass
class Registre:
    hypotheses: dict = field(default_factory=dict)

    def fixer(self, cle: str, libelle: str, valeur: Any, unite: str, origine: str, raison: str = "") -> Any:
        self.hypotheses[cle] = Hypothese(cle, libelle, valeur, unite, origine, raison)
        return valeur

    def valeur(self, cle: str) -> Any:
        return self.hypotheses[cle].valeur

    def liste(self) -> list:
        return list(self.hypotheses.values())

    def en_dicts(self) -> list:
        return [asdict(h) for h in self.liste()]
