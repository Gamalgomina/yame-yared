"""Travaux de l'agent IA, exécutés en arrière-plan.

Un travail peut durer plusieurs minutes : il tourne dans un fil séparé et
écrit son journal dans la base au fur et à mesure. Un seul travail tourne à
la fois ; les suivants attendent leur tour.
"""

from __future__ import annotations

import io
import threading
import zipfile
from pathlib import Path

from .agent import Agent
from .client import ErreurIA, IANonConfiguree, client_par_defaut, configuration

MODES = {"pilote": "Piloter une conception", "atelier": "Atelier de R&D"}
_verrou = threading.Lock()
_fils: dict = {}


def dossier_travail(stockage, numero: int) -> Path:
    return Path(stockage.dossier) / "travaux" / str(numero)


def _executer(stockage, numero: int, mode: str, demande: str, fabrique_client) -> None:
    with _verrou:
        stockage.etat_travail(numero, "en cours")
        agent = None
        try:
            client = (fabrique_client or client_par_defaut)()
            agent = Agent(client, stockage, journal=lambda genre, texte: stockage.journaliser(numero, genre, texte),
                          tours_max=configuration()["tours_max"], travail_id=numero)
            compte_rendu = agent.travailler(mode, demande)
            etat = "terminé"
        except (ErreurIA, IANonConfiguree) as erreur:
            compte_rendu, etat = str(erreur), "échec"
        except Exception as erreur:  # ne jamais laisser un travail « en cours » pour toujours
            compte_rendu, etat = f"Le travail s'est arrêté sur une erreur inattendue ({type(erreur).__name__}).", "échec"
            stockage.journaliser(numero, "erreur", f"{type(erreur).__name__} : {erreur}")
        if agent is not None:
            for etude in agent.etudes:
                stockage.journaliser(numero, "etude", str(etude))
            if agent.espace:
                dossier = dossier_travail(stockage, numero)
                dossier.mkdir(parents=True, exist_ok=True)
                for nom, contenu in agent.espace.items():
                    (dossier / Path(nom).name).write_bytes(contenu)
            stockage.etat_travail(numero, etat, compte_rendu, agent.jetons_entree, agent.jetons_sortie)
        else:
            stockage.etat_travail(numero, etat, compte_rendu)


def lancer(stockage, mode: str, demande: str, fabrique_client=None) -> int:
    """Crée un travail et le démarre en arrière-plan. Renvoie son numéro."""
    if mode not in MODES:
        raise ValueError("Mode inconnu.")
    numero = stockage.creer_travail(mode, demande)
    fil = threading.Thread(target=_executer, args=(stockage, numero, mode, demande, fabrique_client), daemon=True)
    _fils[numero] = fil
    fil.start()
    return numero


def attendre(numero: int, duree: float | None = None) -> None:
    """Attend la fin d'un travail (utile aux tests et à la ligne de commande)."""
    fil = _fils.get(numero)
    if fil is not None:
        fil.join(duree)


def archive_fichiers(stockage, numero: int) -> bytes | None:
    dossier = dossier_travail(stockage, numero)
    if not dossier.is_dir() or not any(dossier.iterdir()):
        return None
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as archive:
        for chemin in sorted(dossier.iterdir()):
            if chemin.is_file():
                archive.write(chemin, chemin.name)
    return tampon.getvalue()
