"""Simulateur ArduPilot (SITL) : le vrai logiciel de vol, exécuté sur le serveur.

Ce que fait cet outil aujourd'hui : il démarre ArduPlane en simulation, lui
envoie un fichier de réglages et vérifie, réglage par réglage, que le logiciel
de vol le connaît et l'accepte tel quel. Un fichier de réglages produit par la
plateforme est donc contrôlé contre le vrai ArduPilot avant d'aller sur un
autopilote réel.

Ce qu'il ne fait pas encore : faire voler une mission complète en simulation.
L'agent IA peut le tenter depuis `executer_python` (binaire dans YAME_SITL,
dialogue avec pymavlink).

Installation : compiler ArduPilot (`./waf configure --board sitl && ./waf plane`)
et indiquer le binaire dans la variable YAME_SITL. L'image Docker complète le fait.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from . import ErreurOutil, Outil, Resultat, enregistrer

EMPLACEMENTS = ("/opt/ardupilot/build/sitl/bin/arduplane",)


def binaire() -> str | None:
    candidats = [os.environ.get("YAME_SITL", ""), *EMPLACEMENTS, shutil.which("arduplane") or ""]
    return next((c for c in candidats if c and os.path.isfile(c) and os.access(c, os.X_OK)), None)


def _reglages_par_defaut(chemin_binaire: str, decollage_vertical: bool) -> str | None:
    """Fichier de réglages de base livré avec ArduPilot pour le modèle simulé."""
    dossiers = [os.environ.get("YAME_SITL_DEFAUTS", "")]
    try:
        dossiers.append(str(Path(chemin_binaire).resolve().parents[3] / "Tools" / "autotest" / "default_params"))
    except IndexError:
        pass
    nom = "quadplane.parm" if decollage_vertical else "plane.parm"
    for dossier in dossiers:
        if dossier and (Path(dossier) / nom).is_file():
            return str(Path(dossier) / nom)
    return None


def lire_reglages(texte: str) -> list:
    """Lit un fichier .param : lignes « NOM,valeur » ou « NOM valeur », commentaires en #."""
    reglages = []
    for ligne in texte.splitlines():
        ligne = ligne.split("#", 1)[0].strip()
        if not ligne:
            continue
        morceaux = ligne.replace(",", " ").split()
        if len(morceaux) < 2:
            raise ErreurOutil(f"Ligne de réglage illisible : {ligne}")
        try:
            reglages.append((morceaux[0].upper(), float(morceaux[1])))
        except ValueError:
            raise ErreurOutil(f"Valeur illisible pour {morceaux[0]} : {morceaux[1]}") from None
    return reglages


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class OutilSimulateur(Outil):
    identifiant = "simulateur"
    nom = "Simulateur de vol"
    logiciel = "ArduPilot SITL (ArduPlane) et pymavlink"
    role = ("Démarre le vrai logiciel de vol en simulation et vérifie qu'il accepte un fichier de réglages, "
            "réglage par réglage.")
    schema = {
        "type": "object",
        "properties": {
            "reglages": {"type": "string", "description": "Contenu d'un fichier .param (une ligne « NOM,valeur » par réglage)."},
            "decollage_vertical": {"type": "boolean", "description": "Vrai : avion à décollage vertical (QuadPlane)."},
        },
        "required": ["reglages"],
    }

    def disponible(self) -> bool:
        if binaire() is None:
            return False
        try:
            import pymavlink  # noqa: F401
        except Exception:
            return False
        return True

    def etat(self) -> str:
        if binaire() is None:
            return "non installé (ArduPilot n'est pas compilé sur ce serveur)"
        return "ArduPlane en simulation" if self.disponible() else "pymavlink manquant"

    def executer(self, reglages: str, decollage_vertical: bool = True, duree_max: int = 90) -> Resultat:
        self.exiger()
        from pymavlink import mavutil

        liste = lire_reglages(reglages)
        if not liste:
            raise ErreurOutil("Le fichier de réglages est vide.")
        chemin = binaire()
        port = _port_libre()
        commande = [chemin, "--model", "quadplane" if decollage_vertical else "plane", "--speedup", "5", "-w",
                    "--serial0", f"tcp:{port}", "--home", "6.17,1.25,60,0"]
        defauts = _reglages_par_defaut(chemin, decollage_vertical)
        if defauts:
            commande += ["--defaults", defauts]
        with tempfile.TemporaryDirectory(prefix="yame-sitl-") as dossier:
            journal = open(Path(dossier) / "sitl.log", "w")
            processus = subprocess.Popen(commande, cwd=dossier, stdout=journal, stderr=subprocess.STDOUT)
            liaison = None
            try:
                fin = time.time() + duree_max
                while liaison is None:
                    if processus.poll() is not None:
                        raise ErreurOutil("Le simulateur s'est arrêté au démarrage.\n" + Path(dossier, "sitl.log").read_text()[-800:])
                    if time.time() > fin:
                        raise ErreurOutil("Le simulateur n'a pas démarré à temps.")
                    try:
                        liaison = mavutil.mavlink_connection(f"tcp:127.0.0.1:{port}", autoreconnect=False)
                    except OSError:
                        time.sleep(0.5)
                if liaison.wait_heartbeat(timeout=max(5, fin - time.time())) is None:
                    raise ErreurOutil("Le simulateur ne répond pas.")

                acceptes, modifies, inconnus = [], [], []
                for nom, valeur in liste:
                    if time.time() > fin:
                        raise ErreurOutil("Durée maximale dépassée pendant l'envoi des réglages.")
                    recu = None
                    for _ in range(3):
                        liaison.mav.param_set_send(liaison.target_system, liaison.target_component, nom.encode("ascii"),
                                                   valeur, mavutil.mavlink.MAV_PARAM_TYPE_REAL32)
                        limite = time.time() + 2.0
                        while time.time() < limite:
                            message = liaison.recv_match(type="PARAM_VALUE", blocking=True, timeout=0.5)
                            if message is not None and message.param_id.rstrip("\x00").upper() == nom:
                                recu = float(message.param_value)
                                break
                        if recu is not None:
                            break
                    if recu is None:
                        inconnus.append(nom)
                    elif abs(recu - valeur) > 1e-3 * max(1.0, abs(valeur)):
                        modifies.append({"nom": nom, "demande": valeur, "retenu": recu})
                    else:
                        acceptes.append(nom)
                return Resultat({
                    "modele_simule": "QuadPlane" if decollage_vertical else "avion",
                    "reglages_envoyes": len(liste),
                    "acceptes": len(acceptes),
                    "modifies_par_le_logiciel_de_vol": modifies,
                    "inconnus_du_logiciel_de_vol": inconnus,
                    "conforme": not inconnus and not modifies,
                    "portee": "Vérifie que les réglages existent et sont acceptés. Ne vérifie pas qu'ils font bien voler l'avion.",
                })
            finally:
                if liaison is not None:
                    try:
                        liaison.close()
                    except Exception:
                        pass
                processus.terminate()
                try:
                    processus.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    processus.kill()
                journal.close()


enregistrer(OutilSimulateur())
