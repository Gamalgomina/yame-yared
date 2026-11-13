"""Modèle de données commun à tous les modules.

Un module (famille YAME ou composant YARED) déclare ses questions, puis rend
une Etude. L'interface web, le rapport et le dossier de conception ne
connaissent que ces structures : ajouter un module ne demande donc de
toucher ni à l'interface ni au rapport.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class Question:
    cle: str
    libelle: str  # la question, posée en langage simple
    type: str = "nombre"  # "nombre", "oui_non", "choix" ou "texte"
    unite: str = ""
    obligatoire: bool = False
    choix: list = field(default_factory=list)  # [(valeur, libellé), ...]
    aide: str = ""
    avance: bool = False  # rangée sous « Précisions facultatives »


@dataclass
class Chiffre:
    valeur: str
    libelle: str


@dataclass
class Tableau:
    entetes: list
    lignes: list
    titre: str = ""


@dataclass
class Section:
    titre: str
    paragraphes: list = field(default_factory=list)
    tableaux: list = field(default_factory=list)
    alertes: list = field(default_factory=list)


@dataclass
class Etape:
    """Une étape du plan de prototypage. Les étapes se suivent strictement."""

    titre: str
    objectif: str
    actions: list
    moyens: list = field(default_factory=list)
    critere: str = ""  # condition à remplir pour passer à l'étape suivante
    mesures: list = field(default_factory=list)  # à relever et à noter
    securite: str = ""


@dataclass
class Article:
    """Une ligne de nomenclature."""

    designation: str
    quantite: float
    nature: str  # « à fabriquer », « élément de base à approvisionner »...
    specification: str = ""


@dataclass
class Etude:
    module: str
    genre: str  # "famille" ou "composant"
    titre: str
    chiffres: list = field(default_factory=list)
    hypotheses: list = field(default_factory=list)
    sections: list = field(default_factory=list)
    etapes: list = field(default_factory=list)
    nomenclature: list = field(default_factory=list)
    limites: list = field(default_factory=list)
    donnees: dict = field(default_factory=dict)

    def en_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def depuis_dict(cls, d: dict) -> "Etude":
        return cls(
            module=d["module"],
            genre=d["genre"],
            titre=d["titre"],
            chiffres=[Chiffre(**c) for c in d.get("chiffres", [])],
            hypotheses=list(d.get("hypotheses", [])),
            sections=[
                Section(
                    titre=s["titre"],
                    paragraphes=list(s.get("paragraphes", [])),
                    tableaux=[Tableau(**t) for t in s.get("tableaux", [])],
                    alertes=list(s.get("alertes", [])),
                )
                for s in d.get("sections", [])
            ],
            etapes=[Etape(**e) for e in d.get("etapes", [])],
            nomenclature=[Article(**a) for a in d.get("nomenclature", [])],
            limites=list(d.get("limites", [])),
            donnees=dict(d.get("donnees", {})),
        )


def nettoyer(objet: Any) -> Any:
    """Rend un résultat de calcul sérialisable en JSON (dataclasses, nombres numpy)."""
    import dataclasses

    if dataclasses.is_dataclass(objet) and not isinstance(objet, type):
        return nettoyer(dataclasses.asdict(objet))
    if isinstance(objet, dict):
        return {str(k): nettoyer(v) for k, v in objet.items()}
    if isinstance(objet, (list, tuple)):
        return [nettoyer(v) for v in objet]
    if isinstance(objet, (str, bool)) or objet is None:
        return objet
    if isinstance(objet, int):
        return int(objet)
    try:
        valeur = float(objet)
    except (TypeError, ValueError):
        return str(objet)
    return valeur if valeur == valeur and abs(valeur) != float("inf") else None


Optionnel = Optional
