"""Lecture des réponses de l'utilisateur et comblement des vides.

Les réponses arrivent d'un formulaire web (texte), d'un fichier TOML ou de
l'API (valeurs typées). Elles sont normalisées ici, puis chaque module
demande ses valeurs avec `obligatoire`, `combler` ou `deduire`. Tout passe
par le registre d'hypothèses.
"""

from __future__ import annotations

import dataclasses
import tomllib
from typing import Any

from .erreurs import BesoinIncomplet
from .hypotheses import Registre
from .modele import Question

OUI = ("oui", "o", "yes", "true", "vrai", "1")
NON = ("non", "n", "no", "false", "faux", "0")


def normaliser(question: Question, brut: Any) -> Any:
    """Convertit une réponse brute. Renvoie None si la réponse est vide."""
    if brut is None or (isinstance(brut, str) and not brut.strip()):
        return None
    if question.type == "nombre":
        if isinstance(brut, bool):
            raise BesoinIncomplet(f"« {question.libelle} » attend un nombre.")
        try:
            return float(str(brut).replace(",", ".").replace(" ", "").replace(" ", ""))
        except ValueError:
            raise BesoinIncomplet(f"« {question.libelle} » attend un nombre, pas « {brut} ».") from None
    if question.type == "oui_non":
        if isinstance(brut, bool):
            return brut
        t = str(brut).strip().lower()
        if t in OUI:
            return True
        if t in NON:
            return False
        return None
    if question.type == "choix":
        valeurs = [c[0] for c in question.choix]
        if str(brut) not in valeurs:
            raise BesoinIncomplet(f"« {question.libelle} » : choix possibles : {', '.join(valeurs)}.")
        return str(brut)
    return str(brut).strip()


class Reponses:
    def __init__(self, questions: list, brutes: dict):
        self.questions = {q.cle: q for q in questions}
        self.registre = Registre()
        self.valeurs: dict = {}
        for cle, question in self.questions.items():
            valeur = normaliser(question, brutes.get(cle))
            if valeur is None:
                continue
            self.valeurs[cle] = valeur
        expert = brutes.get("expert")
        if isinstance(expert, str):
            try:
                expert = tomllib.loads(expert) if expert.strip() else {}
            except tomllib.TOMLDecodeError as erreur:
                raise BesoinIncomplet(f"Réglages experts illisibles : {erreur}") from None
        self.expert = dict(expert or {})
        self.titre = str(brutes.get("nom") or "").strip()

    def donne(self, cle: str) -> bool:
        return cle in self.valeurs

    def brut(self, cle: str) -> Any:
        """Réponse de l'utilisateur, ou None s'il n'a rien dit. N'enregistre rien."""
        return self.valeurs.get(cle)

    def obligatoire(self, cle: str) -> Any:
        q = self.questions[cle]
        if cle not in self.valeurs:
            raise BesoinIncomplet(f"Il manque une information : {q.libelle}")
        return self.registre.fixer(cle, q.libelle, self.valeurs[cle], q.unite, "utilisateur")

    def combler(self, cle: str, defaut: Any, raison: str) -> Any:
        q = self.questions[cle]
        if cle in self.valeurs:
            return self.registre.fixer(cle, q.libelle, self.valeurs[cle], q.unite, "utilisateur")
        return self.registre.fixer(cle, q.libelle, defaut, q.unite, "défaut", raison)

    def deduire(self, cle: str, libelle: str, valeur: Any, unite: str, raison: str) -> Any:
        return self.registre.fixer(cle, libelle, valeur, unite, "déduit", raison)

    def appliquer_expert(self, parametres: Any) -> Any:
        """Force des paramètres techniques d'un dataclass depuis la table [expert]."""
        champs = {c.name for c in dataclasses.fields(parametres)}
        for cle, valeur in self.expert.items():
            if cle not in champs:
                raise BesoinIncomplet(
                    f"Réglage expert inconnu : {cle}. Réglages possibles : {', '.join(sorted(champs))}."
                )
            setattr(parametres, cle, valeur)
            self.registre.fixer(f"expert.{cle}", f"Réglage expert : {cle}", valeur, "", "utilisateur")
        return parametres
