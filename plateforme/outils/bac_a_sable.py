"""Exécution de code Python dans un processus séparé.

Sert à l'outil de CAO (scripts CadQuery), à l'agent IA (calculs libres) et au
contrôle des modules proposés par l'agent avant leur validation.

Ce que ce bac à sable garantit :
- processus distinct, dans un dossier temporaire effacé à la fin ;
- durée et taille des fichiers limitées ;
- variables d'environnement de la plateforme retirées (clé d'IA, mot de passe).

Ce qu'il ne garantit PAS : l'isolation du réseau et du disque. Le code tourne
avec les droits de l'application. La barrière extérieure est le conteneur
Docker : ne donnez l'accès à l'agent IA qu'à des personnes de confiance.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

RACINE = str(Path(__file__).resolve().parents[2])  # dossier qui contient le paquet « plateforme »
TAILLE_MAX_FICHIERS = 30 * 1024 * 1024
ENTETE = f"import sys\nsys.path.insert(0, {RACINE!r})\n"


@dataclass
class Sortie:
    code_retour: int
    sortie: str
    erreurs: str
    fichiers: dict = field(default_factory=dict)  # nom -> octets
    depasse: bool = False  # durée maximale dépassée

    @property
    def reussi(self) -> bool:
        return self.code_retour == 0 and not self.depasse

    def resume(self, longueur: int = 6000) -> str:
        """Texte court pour un journal ou pour l'agent IA."""
        morceaux = []
        if self.depasse:
            morceaux.append("[durée maximale dépassée : calcul interrompu]")
        if self.sortie.strip():
            morceaux.append(_tronquer(self.sortie.strip(), longueur))
        if self.erreurs.strip():
            morceaux.append("[erreurs]\n" + _tronquer(self.erreurs.strip(), longueur // 2))
        if self.fichiers:
            morceaux.append("[fichiers produits] " + ", ".join(f"{n} ({len(c)} octets)" for n, c in self.fichiers.items()))
        return "\n".join(morceaux) or "[aucune sortie]"


def _tronquer(texte: str, longueur: int) -> str:
    if len(texte) <= longueur:
        return texte
    moitie = longueur // 2
    return texte[:moitie] + f"\n[... {len(texte) - longueur} caractères retirés ...]\n" + texte[-moitie:]


def _limites(duree_max: int):
    def poser():
        import resource

        os.setsid()
        resource.setrlimit(resource.RLIMIT_CPU, (duree_max + 5, duree_max + 10))
        resource.setrlimit(resource.RLIMIT_FSIZE, (200 * 1024 * 1024, 200 * 1024 * 1024))

    return poser


def executer(code: str, duree_max: int = 120, fichiers: dict | None = None) -> Sortie:
    """Exécute `code`. `fichiers` (nom -> octets) sont déposés dans le dossier de travail."""
    environnement = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "OMP_NUM_THREADS": "2",
    }
    # Réglages des logiciels embarqués (aucun secret) : OpenFOAM, simulateur de vol.
    for variable, defaut in (("WM_PROJECT_DIR", "/usr/share/openfoam"), ("YAME_SITL", "")):
        valeur = os.environ.get(variable, defaut)
        if valeur and (variable != "WM_PROJECT_DIR" or os.path.isdir(valeur)):
            environnement[variable] = valeur
    with tempfile.TemporaryDirectory(prefix="yame-bac-") as dossier:
        environnement["HOME"] = dossier
        for nom, contenu in (fichiers or {}).items():
            (Path(dossier) / Path(nom).name).write_bytes(contenu)
        script = Path(dossier) / "_script.py"
        script.write_text(ENTETE + code, encoding="utf-8")
        deposes = {p.name for p in Path(dossier).iterdir()}
        processus = subprocess.Popen(
            [sys.executable, "-I", str(script)],
            cwd=dossier, env=environnement, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            preexec_fn=_limites(duree_max) if os.name == "posix" else None,
        )
        depasse = False
        try:
            sortie, erreurs = processus.communicate(timeout=duree_max)
        except subprocess.TimeoutExpired:
            depasse = True
            try:
                os.killpg(processus.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, AttributeError):
                processus.kill()
            sortie, erreurs = processus.communicate()
        produits, total = {}, 0
        for chemin in sorted(Path(dossier).iterdir()):
            if chemin.is_file() and chemin.name not in deposes:
                taille = chemin.stat().st_size
                if total + taille > TAILLE_MAX_FICHIERS:
                    continue
                produits[chemin.name] = chemin.read_bytes()
                total += taille
        return Sortie(processus.returncode if not depasse else -9, sortie, erreurs, produits, depasse)
