"""Registre des modules.

Pour ajouter un matériel ou un composant : écrire une classe qui hérite de
Module, déclarer ses questions, écrire `etudier`, puis l'enregistrer avec
`enregistrer`. Elle apparaît alors dans l'interface web, l'API et la ligne de
commande sans autre modification.
"""

from __future__ import annotations

from .modele import Etude

QUESTION_NOM = "nom"


class Module:
    identifiant: str = ""
    nom: str = ""
    genre: str = "famille"  # "famille" (YAME) ou "composant" (YARED)
    description: str = ""
    questions: list = []
    exemple: dict = {}  # réponses d'exemple, pour les tests et la démonstration
    accepte_expert: bool = False

    def etudier(self, brutes: dict) -> Etude:
        raise NotImplementedError

    def fichiers(self, etude: Etude) -> dict:
        """Fichiers supplémentaires à joindre au dossier (nom -> octets)."""
        return {}


_REGISTRE: dict = {}


def enregistrer(module: Module) -> Module:
    if not module.identifiant:
        raise ValueError("Un module doit avoir un identifiant.")
    _REGISTRE[module.identifiant] = module
    return module


def _charger() -> None:
    if _REGISTRE:
        return
    from .. import composants, familles  # noqa: F401  (l'import enregistre les modules)


def tous() -> list:
    _charger()
    return list(_REGISTRE.values())


def obtenir(identifiant: str) -> Module:
    _charger()
    if identifiant not in _REGISTRE:
        raise KeyError(f"Module inconnu : {identifiant}")
    return _REGISTRE[identifiant]
