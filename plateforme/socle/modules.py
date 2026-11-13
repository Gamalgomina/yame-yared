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


# --- Modules ajoutés après coup (proposés par l'agent IA, validés par un humain) ---

MODULES_INTEGRES: set = set()
_ERREURS_AJOUTES: dict = {}


def integres() -> set:
    """Identifiants des modules livrés avec la plateforme."""
    _charger()
    if not MODULES_INTEGRES:
        MODULES_INTEGRES.update(_REGISTRE)
    return MODULES_INTEGRES


def charger_fichier(chemin) -> Module:
    """Charge un module depuis un fichier Python. Renvoie le module enregistré."""
    import importlib.util
    from pathlib import Path

    chemin = Path(chemin)
    avant = set(integres()) | set(_REGISTRE)
    specification = importlib.util.spec_from_file_location(f"yame_module_ajoute_{chemin.stem.replace('-', '_')}", chemin)
    code = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(code)
    nouveaux = [i for i in _REGISTRE if i not in avant]
    if len(nouveaux) != 1:
        for i in nouveaux:
            _REGISTRE.pop(i, None)
        raise ValueError(f"{chemin.name} doit enregistrer exactement un nouveau module (trouvé : {len(nouveaux)}).")
    return _REGISTRE[nouveaux[0]]


def charger_ajoutes(dossier) -> dict:
    """Charge tous les modules validés du dossier. Renvoie {fichier: erreur} pour ceux qui échouent."""
    from pathlib import Path

    integres()
    _ERREURS_AJOUTES.clear()
    dossier = Path(dossier)
    if dossier.is_dir():
        for chemin in sorted(dossier.glob("*.py")):
            if chemin.stem in _REGISTRE:
                continue
            try:
                charger_fichier(chemin)
            except Exception as erreur:  # un module défectueux ne doit pas empêcher le démarrage
                _ERREURS_AJOUTES[chemin.name] = f"{type(erreur).__name__} : {erreur}"
    return dict(_ERREURS_AJOUTES)


def retirer(identifiant: str) -> None:
    if identifiant in integres():
        raise ValueError("Un module livré avec la plateforme ne peut pas être retiré.")
    _REGISTRE.pop(identifiant, None)
