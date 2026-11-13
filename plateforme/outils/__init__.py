"""Logiciels de calcul embarqués.

Chaque outil enveloppe un logiciel libre existant derrière la même interface :
`disponible()`, `etat()`, `executer(**arguments)`. Les modules de YAME et de
YARED les appellent directement ; l'agent IA les reçoit comme outils, décrits
par `schema`.

Un outil absent (logiciel non installé) ne bloque jamais la plateforme : les
modules qui s'en servent le signalent et continuent sans lui.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class OutilIndisponible(RuntimeError):
    """Le logiciel n'est pas installé sur cette machine."""


class ErreurOutil(RuntimeError):
    """Le calcul a échoué ; le message explique pourquoi."""


@dataclass
class Resultat:
    donnees: dict
    fichiers: dict = field(default_factory=dict)  # nom -> octets


class Outil:
    identifiant: str = ""
    nom: str = ""
    logiciel: str = ""  # logiciel libre embarqué
    role: str = ""  # ce qu'il apporte, en une phrase
    schema: dict = {}  # schéma JSON des arguments de `executer`

    def disponible(self) -> bool:
        return True

    def etat(self) -> str:
        """Version installée, ou raison de l'indisponibilité."""
        return "disponible" if self.disponible() else "non installé"

    def executer(self, **arguments) -> Resultat:
        raise NotImplementedError

    def exiger(self) -> None:
        if not self.disponible():
            raise OutilIndisponible(f"{self.nom} : {self.logiciel} n'est pas installé sur cette machine.")


_REGISTRE: dict = {}


def enregistrer(outil: Outil) -> Outil:
    _REGISTRE[outil.identifiant] = outil
    return outil


def _charger() -> None:
    if _REGISTRE:
        return
    from . import aerodynamique, autopilote, cao, libres, simulateur, structure  # noqa: F401  (l'import enregistre)


def tous() -> list:
    _charger()
    return list(_REGISTRE.values())


def obtenir(identifiant: str) -> Outil:
    _charger()
    if identifiant not in _REGISTRE:
        raise KeyError(f"Outil inconnu : {identifiant}")
    return _REGISTRE[identifiant]
