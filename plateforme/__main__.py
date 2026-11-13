"""Ligne de commande.

    python -m plateforme modules
    python -m plateforme etudier missions/drone_voilure_fixe.toml --sortie resultats
    python -m plateforme serveur --port 8000
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from .socle import dossier, modules
from .socle.erreurs import ErreurEtude


def _modules(_arguments) -> int:
    for m in modules.tous():
        marque = "YAME " if m.genre == "famille" else "YARED"
        print(f"{marque}  {m.identifiant:22s} {m.nom} — {m.description}")
    return 0


def _etudier(arguments) -> int:
    with open(arguments.fichier, "rb") as fichier:
        reponses = tomllib.load(fichier)
    identifiant = arguments.module or reponses.pop("module", None)
    if not identifiant:
        print("Indiquez le module : ligne « module = \"...\" » dans le fichier, ou option --module.", file=sys.stderr)
        return 2
    try:
        etude = modules.obtenir(identifiant).etudier(reponses)
    except KeyError as erreur:
        print(erreur.args[0], file=sys.stderr)
        return 2
    except ErreurEtude as erreur:
        print(f"Étude impossible : {erreur}", file=sys.stderr)
        return 1
    sortie = Path(arguments.sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    archive = sortie / f"dossier-{dossier.nom_de_fichier(etude.titre)}.zip"
    archive.write_bytes(dossier.construire(etude))
    print(etude.titre)
    for chiffre in etude.chiffres:
        print(f"  {chiffre.valeur:>18s}  {chiffre.libelle}")
    print(f"Plan de prototypage : {len(etude.etapes)} étapes")
    print(f"Dossier de conception : {archive}")
    return 0


def _serveur(arguments) -> int:
    import uvicorn

    uvicorn.run("plateforme.web.app:creer_application", factory=True, host=arguments.hote, port=arguments.port)
    return 0


def principal() -> int:
    analyse = argparse.ArgumentParser(prog="plateforme", description="YAME / YARED : conception de matériels par simulation.")
    commandes = analyse.add_subparsers(dest="commande", required=True)
    commandes.add_parser("modules", help="liste les modules disponibles").set_defaults(fonction=_modules)
    etudier = commandes.add_parser("etudier", help="lance une étude depuis un fichier .toml")
    etudier.add_argument("fichier")
    etudier.add_argument("--module", help="identifiant du module, s'il n'est pas dans le fichier")
    etudier.add_argument("--sortie", default="resultats", help="dossier où écrire le dossier de conception")
    etudier.set_defaults(fonction=_etudier)
    serveur = commandes.add_parser("serveur", help="démarre l'application web")
    serveur.add_argument("--hote", default="127.0.0.1")
    serveur.add_argument("--port", type=int, default=8000)
    serveur.set_defaults(fonction=_serveur)
    arguments = analyse.parse_args()
    return arguments.fonction(arguments)


if __name__ == "__main__":
    sys.exit(principal())
