"""Accès au modèle d'IA.

Réglages (variables d'environnement) :
- YAME_IA_CLE            clé d'API Anthropic. Sans elle, l'agent est désactivé.
- YAME_IA_MODELE         modèle utilisé (défaut : claude-sonnet-5-5).
- YAME_IA_RECHERCHE_WEB  type de l'outil de recherche web côté Anthropic, par
                         exemple « web_search_20250305 ». Vide (défaut) : pas
                         de recherche web. Voir les risques dans DEPLOIEMENT.md.
- YAME_IA_TOURS_MAX      nombre maximal d'allers-retours par travail (défaut : 40).

La clé n'est jamais écrite dans la base, les journaux ou les pages.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

MODELE_PAR_DEFAUT = "claude-sonnet-5-5"


class IANonConfiguree(RuntimeError):
    """Aucune clé d'API : l'agent ne peut pas travailler."""


class ErreurIA(RuntimeError):
    """Le service d'IA a refusé ou échoué ; le message est affichable."""


@dataclass
class Appel:
    identifiant: str
    nom: str
    arguments: dict


@dataclass
class Reponse:
    contenu: list  # blocs bruts, à renvoyer tels quels dans la conversation
    textes: list = field(default_factory=list)
    appels: list = field(default_factory=list)
    arret: str = "end_turn"
    jetons_entree: int = 0
    jetons_sortie: int = 0


def configuration() -> dict:
    return {
        "cle": os.environ.get("YAME_IA_CLE", "").strip(),
        "modele": os.environ.get("YAME_IA_MODELE", "").strip() or MODELE_PAR_DEFAUT,
        "recherche_web": os.environ.get("YAME_IA_RECHERCHE_WEB", "").strip(),
        "tours_max": int(os.environ.get("YAME_IA_TOURS_MAX", "40") or 40),
    }


def configuree() -> bool:
    return bool(configuration()["cle"])


class ClientAnthropic:
    """Client de l'API Messages d'Anthropic."""

    def __init__(self, cle: str, modele: str, recherche_web: str = "", jetons_max: int = 8000):
        if not cle:
            raise IANonConfiguree("Aucune clé d'API : définissez YAME_IA_CLE.")
        import anthropic

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=cle, max_retries=3, timeout=600.0)
        self.modele = modele
        self.recherche_web = recherche_web
        self.jetons_max = jetons_max

    def repondre(self, systeme: str, messages: list, outils: list) -> Reponse:
        tous = list(outils)
        if self.recherche_web:
            tous.append({"type": self.recherche_web, "name": "web_search", "max_uses": 8})
        try:
            message = self._client.messages.create(
                model=self.modele, max_tokens=self.jetons_max, system=systeme, messages=messages, tools=tous,
            )
        except self._anthropic.AuthenticationError:
            raise ErreurIA("La clé d'API est refusée. Vérifiez YAME_IA_CLE.") from None
        except self._anthropic.BadRequestError as erreur:
            if self.recherche_web:
                # Le type d'outil de recherche n'est peut-être pas accepté par ce modèle : on s'en passe.
                self.recherche_web = ""
                return self.repondre(systeme, messages, outils)
            raise ErreurIA(f"Demande refusée par le service d'IA : {erreur.message}") from None
        except self._anthropic.APIStatusError as erreur:
            raise ErreurIA(f"Le service d'IA a répondu par une erreur {erreur.status_code}.") from None
        except self._anthropic.APIConnectionError:
            raise ErreurIA("Impossible de joindre le service d'IA. Vérifiez la connexion Internet du serveur.") from None

        reponse = Reponse(contenu=message.content, arret=message.stop_reason or "end_turn")
        for bloc in message.content:
            if bloc.type == "text":
                reponse.textes.append(bloc.text)
            elif bloc.type == "tool_use":
                reponse.appels.append(Appel(bloc.id, bloc.name, dict(bloc.input or {})))
        if message.usage:
            reponse.jetons_entree = message.usage.input_tokens or 0
            reponse.jetons_sortie = message.usage.output_tokens or 0
        return reponse


def client_par_defaut() -> ClientAnthropic:
    c = configuration()
    return ClientAnthropic(c["cle"], c["modele"], c["recherche_web"])
