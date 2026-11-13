"""Rendu HTML des études (page web et rapport autonome) et plan en Markdown."""

from __future__ import annotations

import csv
import datetime
import io

from jinja2 import Environment, PackageLoader, select_autoescape

from .. import __version__
from .format import texte
from .modele import Etude

ORIGINES = {"utilisateur": ("donné", "utilisateur"), "déduit": ("déduit", "deduit"), "défaut": ("comblé", "defaut")}

environnement = Environment(
    loader=PackageLoader("plateforme.web", "templates"),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
environnement.filters["texte"] = texte
environnement.globals["version"] = __version__
environnement.globals["ORIGINES"] = ORIGINES


def page(gabarit: str, **contexte) -> str:
    return environnement.get_template(gabarit).render(**contexte)


def rapport_autonome(etude: Etude, nom_module: str, avancement: dict | None = None) -> str:
    """Rapport complet en un seul fichier HTML, lisible hors ligne."""
    return page(
        "rapport_autonome.html", etude=etude, nom_module=nom_module, avancement=avancement or {},
        date=datetime.date.today().strftime("%d/%m/%Y"),
    )


def plan_markdown(etude: Etude, avancement: dict | None = None) -> str:
    """Plan de prototypage sous forme de liste à cocher."""
    avancement = avancement or {}
    lignes = [f"# Plan de prototypage — {etude.titre}", "",
              "Les étapes se suivent strictement : ne commencez une étape que lorsque la précédente est validée.", ""]
    for numero, etape in enumerate(etude.etapes, 1):
        fait = avancement.get(numero)
        lignes += [f"## Étape {numero} — {etape.titre}" + (f" (validée le {fait['valide_le']})" if fait else ""), "",
                   f"**Objectif.** {etape.objectif}", "", "**À faire**", ""]
        lignes += [f"- [{'x' if fait else ' '}] {action}" for action in etape.actions]
        if etape.moyens:
            lignes += ["", "**Moyens.** " + " ; ".join(etape.moyens)]
        if etape.securite:
            lignes += ["", f"**Sécurité.** {etape.securite}"]
        lignes += ["", f"**Critère de réussite.** {etape.critere}", ""]
        if etape.mesures:
            lignes += ["**Mesures à relever**", ""]
            for mesure in etape.mesures:
                valeur = fait["releves"].get(mesure, "") if fait else ""
                lignes.append(f"- {mesure} : {valeur or '__________'}")
            lignes.append("")
    return "\n".join(lignes)


def nomenclature_csv(etude: Etude) -> str:
    sortie = io.StringIO()
    ecrivain = csv.writer(sortie, delimiter=";")
    ecrivain.writerow(["Désignation", "Quantité", "Nature", "Spécification"])
    for article in etude.nomenclature:
        ecrivain.writerow([article.designation, texte(article.quantite), article.nature, article.specification])
    return sortie.getvalue()
