"""Dossier de conception : tout ce qu'il faut pour préparer le prototypage.

Une archive zip contenant le rapport, le plan de prototypage pas à pas, la
nomenclature, les chiffres bruts, les fichiers CAO disponibles, et un
sous-dossier complet par composant à concevoir.
"""

from __future__ import annotations

import io
import json
import re
import unicodedata
import zipfile

from . import modules
from .erreurs import ErreurEtude
from .modele import Etude
from .rendu import nomenclature_csv, plan_markdown, rapport_autonome

LISEZ_MOI = """DOSSIER DE CONCEPTION — {titre}

Contenu
  rapport.html              Le rapport complet. À ouvrir dans un navigateur.
  plan_de_prototypage.md    Les étapes à suivre, dans l'ordre, avec critères et mesures.
  nomenclature.csv          La liste des pièces. S'ouvre dans un tableur (séparateur : point-virgule).
  resultats.json            Tous les chiffres, pour d'autres outils.
  cao/                      Fichiers STEP des pièces, s'il y en a. À ouvrir dans FreeCAD.
  composants/               Un dossier complet par composant à concevoir.

Mode d'emploi
  1. Lisez le rapport, en particulier le tableau des hypothèses et la partie « Limites ».
  2. Suivez le plan de prototypage étape par étape. Ne sautez aucune étape.
  3. À chaque étape, notez les mesures demandées : elles servent à recaler les calculs.

Avertissement
  Avant-projet non validé. Les calculs viennent de modèles simplifiés qui n'ont pas été
  recalés sur des essais. Aucune pièce ne doit être mise en service sur cette seule base.
"""


def nom_de_fichier(texte: str) -> str:
    """Nom sans accent ni espace, sûr pour tous les systèmes."""
    ascii_ = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", ascii_).strip("-").lower() or "etude"


def _ecrire(archive: zipfile.ZipFile, prefixe: str, etude: Etude, avancement: dict | None = None) -> None:
    module = modules.obtenir(etude.module)
    archive.writestr(prefixe + "rapport.html", rapport_autonome(etude, module.nom, avancement))
    archive.writestr(prefixe + "plan_de_prototypage.md", plan_markdown(etude, avancement))
    archive.writestr(prefixe + "nomenclature.csv", "﻿" + nomenclature_csv(etude))
    archive.writestr(prefixe + "resultats.json", json.dumps(etude.en_dict(), indent=2, ensure_ascii=False))
    try:
        for nom, contenu in module.fichiers(etude).items():
            archive.writestr(prefixe + nom, contenu)
    except Exception as erreur:  # la CAO est facultative : son échec ne doit pas bloquer le dossier
        archive.writestr(prefixe + "cao/ERREUR.txt", f"Les fichiers CAO n'ont pas pu être produits : {erreur}\n")


def construire(etude: Etude, avancement: dict | None = None) -> bytes:
    """Construit l'archive zip du dossier de conception."""
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("LISEZ-MOI.txt", LISEZ_MOI.format(titre=etude.titre))
        _ecrire(archive, "", etude, avancement)
        for numero, composant in enumerate(etude.donnees.get("composants", []), 1):
            prefixe = f"composants/{numero}-{nom_de_fichier(composant['libelle'])}/"
            try:
                sous_etude = modules.obtenir(composant["module"]).etudier(composant["reponses"])
            except (ErreurEtude, KeyError) as erreur:
                archive.writestr(prefixe + "ERREUR.txt", f"Ce composant n'a pas pu être étudié : {erreur}\n")
                continue
            _ecrire(archive, prefixe, sous_etude)
    return tampon.getvalue()
