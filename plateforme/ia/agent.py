"""Boucle de travail de l'agent IA.

L'agent reçoit une demande, puis alterne réflexion et appels d'outils jusqu'à
rendre un compte rendu. Ses outils sont ceux de la plateforme : modules,
logiciels embarqués, calcul Python en bac à sable, et, dans l'atelier de R&D,
la soumission d'un nouveau module.

Chaque travail a un espace de fichiers en mémoire (pièces CAO, résultats de
calcul) que les outils se partagent.
"""

from __future__ import annotations

import inspect
import json
import sys

from .. import outils
from ..outils import ErreurOutil, OutilIndisponible, bac_a_sable
from ..socle import modules
from ..socle.erreurs import ErreurEtude
from ..socle.modele import Etude
from . import propositions
from .guide import consignes

LONGUEUR_MAX = 8000


def _court(texte: str, longueur: int = LONGUEUR_MAX) -> str:
    return bac_a_sable._tronquer(texte, longueur)


def _json(objet, longueur: int = 3500) -> str:
    return _court(json.dumps(objet, ensure_ascii=False, default=str), longueur)


def decrire_modules() -> str:
    lignes = []
    for m in modules.tous():
        lignes.append(f"- {m.identifiant} [{'YAME' if m.genre == 'famille' else 'YARED'}] {m.nom} : {m.description}")
    return "\n".join(lignes)


def decrire_outils() -> str:
    return "\n".join(
        f"- outil_{o.identifiant} : {o.nom} ({o.logiciel}). {o.role} "
        f"{'Disponible.' if o.disponible() else 'NON INSTALLÉ sur ce serveur.'}"
        for o in outils.tous()
    )


def resumer_etude(numero: int | None, etude: Etude) -> str:
    comblees = [f"{h['libelle']} = {h['valeur']} {h['unite']} ({h['raison']})"
                for h in etude.hypotheses if h.get("origine") == "défaut"]
    alertes = [a for s in etude.sections for a in s.alertes]
    morceaux = [
        (f"Étude n° {numero} : " if numero else "Étude : ") + etude.titre,
        "Chiffres clés : " + " ; ".join(f"{c.valeur} ({c.libelle})" for c in etude.chiffres),
        "Sections : " + " | ".join(s.titre for s in etude.sections),
    ]
    if comblees:
        morceaux.append("Valeurs comblées par le module :\n- " + "\n- ".join(comblees))
    if alertes:
        morceaux.append("Alertes :\n- " + "\n- ".join(alertes))
    morceaux.append(f"Plan de prototypage : {len(etude.etapes)} étapes. Nomenclature : {len(etude.nomenclature)} lignes.")
    morceaux.append("Limites :\n- " + "\n- ".join(etude.limites[:6]))
    morceaux.append("Résultats bruts : " + _json(etude.donnees))
    return "\n".join(morceaux)


class Agent:
    def __init__(self, client, stockage, journal=None, tours_max: int = 40, travail_id: int | None = None):
        self.client = client
        self.stockage = stockage
        self.journal = journal or (lambda genre, texte: None)
        self.tours_max = tours_max
        self.travail_id = travail_id
        self.espace: dict = {}  # nom de fichier -> octets
        self.etudes: list = []
        self.propositions: list = []
        self.jetons_entree = 0
        self.jetons_sortie = 0

    # --- Définition des outils ---------------------------------------------
    def definitions(self, mode: str) -> list:
        liste = [
            {"name": "lister_modules",
             "description": "Liste les modules avec leurs questions (clé, type, unité, caractère obligatoire, choix).",
             "input_schema": {"type": "object", "properties": {
                 "module": {"type": "string", "description": "Facultatif : ne détailler que ce module."}}}},
            {"name": "lancer_etude",
             "description": "Lance l'étude d'un module et l'enregistre. Ne fournir que les réponses réellement données "
                            "par la personne : le module comble le reste. Rend les chiffres clés et les valeurs comblées.",
             "input_schema": {"type": "object", "properties": {
                 "module": {"type": "string"},
                 "nom": {"type": "string", "description": "Titre de l'étude."},
                 "reponses": {"type": "object", "description": "Clé de question -> valeur. Les familles YAME acceptent "
                              "aussi « expert » : dictionnaire de paramètres techniques à imposer."}},
                 "required": ["module", "reponses"]}},
            {"name": "lire_etude",
             "description": "Relit une étude enregistrée, avec les mesures relevées pendant le prototypage.",
             "input_schema": {"type": "object", "properties": {"numero": {"type": "integer"}}, "required": ["numero"]}},
            {"name": "executer_python",
             "description": "Exécute un script Python dans un bac à sable (numpy, aerosandbox et cadquery sont installés ; "
                            "le paquet plateforme est importable). Afficher les résultats avec print. Les fichiers de "
                            "l'espace de travail sont dans le dossier courant ; les fichiers créés y sont ajoutés. "
                            "Durée maximale : 120 s.",
             "input_schema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}},
            {"name": "lire_code_module",
             "description": "Rend le code source d'un module existant, pour en respecter les conventions.",
             "input_schema": {"type": "object", "properties": {"identifiant": {"type": "string"}}, "required": ["identifiant"]}},
        ]
        for o in outils.tous():
            schema = json.loads(json.dumps(o.schema))
            if o.identifiant == "cao":
                schema["properties"]["nom"] = {"type": "string", "description": "Nom de la pièce : les fichiers "
                                               "<nom>.step et <nom>.stl sont rangés dans l'espace de travail."}
                schema["required"] = ["script", "nom"]
            if o.identifiant == "structure":
                del schema["properties"]["step"]
                schema["properties"]["fichier"] = {"type": "string", "description": "Fichier STEP de l'espace de travail, "
                                                   "par exemple bielle.step (produit par outil_cao)."}
                schema["required"] = ["fichier", "axe", "force_n"]
            liste.append({"name": f"outil_{o.identifiant}", "description": f"{o.nom} ({o.logiciel}). {o.role}",
                          "input_schema": schema})
        if mode == "atelier":
            liste.append({
                "name": "proposer_module",
                "description": "Soumet un nouveau module. Il est contrôlé automatiquement ; s'il passe, il est enregistré "
                               "comme proposition en attente de validation par une personne. S'il échoue, le rapport dit quoi corriger.",
                "input_schema": {"type": "object", "properties": {
                    "identifiant": {"type": "string", "description": "Minuscules, chiffres, tirets. Identique à celui du code."},
                    "nom": {"type": "string"},
                    "description": {"type": "string", "description": "Ce que fait le module, son modèle, ses sources, ses limites."},
                    "code": {"type": "string", "description": "Le fichier Python complet du module."}},
                    "required": ["identifiant", "nom", "description", "code"]},
            })
        return liste

    # --- Exécution des outils ------------------------------------------------
    def _lister_modules(self, module: str | None = None) -> str:
        retenus = [m for m in modules.tous() if module in (None, "", m.identifiant)]
        if not retenus:
            return f"Module inconnu : {module}."
        lignes = []
        for m in retenus:
            lignes.append(f"## {m.identifiant} [{'YAME' if m.genre == 'famille' else 'YARED'}] {m.nom}\n{m.description}")
            for q in m.questions:
                detail = [q.type] + ([q.unite] if q.unite else []) + (["obligatoire"] if q.obligatoire else [])
                if q.choix:
                    detail.append("choix : " + ", ".join(str(c[0]) for c in q.choix))
                lignes.append(f"- {q.cle} ({' ; '.join(detail)}) : {q.libelle}")
            if m.accepte_expert:
                lignes.append("- expert (dictionnaire) : paramètres techniques à imposer")
            lignes.append(f"Exemple de réponses : {json.dumps(m.exemple, ensure_ascii=False)}")
        return "\n".join(lignes)

    def _lancer_etude(self, module: str, reponses: dict, nom: str = "") -> str:
        m = modules.obtenir(module)
        brutes = dict(reponses or {})
        if nom:
            brutes["nom"] = nom
        etude = m.etudier(brutes)
        numero = self.stockage.creer(m.identifiant, etude.titre, brutes, etude.en_dict())
        self.etudes.append(numero)
        return resumer_etude(numero, etude)

    def _lire_etude(self, numero: int) -> str:
        ligne = self.stockage.lire(int(numero))
        if ligne is None:
            return f"Aucune étude n° {numero}."
        texte = resumer_etude(ligne["id"], Etude.depuis_dict(ligne["etude"]))
        texte += "\nRéponses données : " + _json(ligne["reponses"], 1500)
        avancement = self.stockage.avancement(ligne["id"])
        if avancement:
            texte += "\nMesures relevées pendant le prototypage : " + _json(avancement, 3000)
        else:
            texte += "\nPrototypage : aucune étape validée pour l'instant."
        return texte

    def _executer_python(self, code: str) -> str:
        sortie = bac_a_sable.executer(code, duree_max=120, fichiers=self.espace)
        self.espace.update(sortie.fichiers)
        return sortie.resume()

    def _lire_code_module(self, identifiant: str) -> str:
        m = modules.obtenir(identifiant)
        return _court(inspect.getsource(sys.modules[type(m).__module__]), 30000)

    def _outil(self, identifiant: str, arguments: dict) -> str:
        outil = outils.obtenir(identifiant)
        arguments = dict(arguments)
        nom = ""
        if identifiant == "cao":
            nom = "".join(c for c in str(arguments.pop("nom", "piece")) if c.isalnum() or c in "-_") or "piece"
        if identifiant == "structure":
            fichier = str(arguments.pop("fichier", ""))
            if fichier not in self.espace:
                return f"Fichier absent de l'espace de travail : {fichier}. Fichiers présents : {', '.join(self.espace) or 'aucun'}."
            arguments["step"] = self.espace[fichier]
        resultat = outil.executer(**arguments)
        donnees = resultat.donnees
        if identifiant == "aerodynamique":
            donnees = {**donnees, "polaire": donnees["polaire"][::2]}
        for nom_fichier, contenu in resultat.fichiers.items():
            if identifiant == "cao":
                nom_fichier = nom + "." + nom_fichier.rsplit(".", 1)[-1]
            self.espace[nom_fichier] = contenu
        texte = _json(donnees, 6000)
        if resultat.fichiers:
            texte += "\nFichiers rangés dans l'espace de travail : " + ", ".join(
                (nom + "." + n.rsplit(".", 1)[-1]) if identifiant == "cao" else n for n in resultat.fichiers)
        return texte

    def _proposer_module(self, identifiant: str, nom: str, description: str, code: str) -> str:
        controle = propositions.controler(identifiant, code)
        if not controle["valide"]:
            return "Module refusé.\n" + controle["rapport"]
        numero = self.stockage.creer_proposition(self.travail_id, identifiant, nom, description, code, controle["rapport"])
        self.propositions.append(numero)
        return (f"Proposition n° {numero} enregistrée. {controle['rapport']}\n"
                "Le module n'est pas actif : une personne doit le relire et le valider.")

    def executer_outil(self, nom: str, arguments: dict) -> tuple:
        """Renvoie (texte, erreur)."""
        try:
            if nom == "lister_modules":
                return self._lister_modules(**arguments), False
            if nom == "lancer_etude":
                return self._lancer_etude(**arguments), False
            if nom == "lire_etude":
                return self._lire_etude(**arguments), False
            if nom == "executer_python":
                return self._executer_python(**arguments), False
            if nom == "lire_code_module":
                return self._lire_code_module(**arguments), False
            if nom == "proposer_module":
                return self._proposer_module(**arguments), False
            if nom.startswith("outil_"):
                return self._outil(nom[len("outil_"):], arguments), False
            return f"Outil inconnu : {nom}.", True
        except (ErreurEtude, ErreurOutil, OutilIndisponible) as erreur:
            return str(erreur), True
        except KeyError as erreur:
            return f"Introuvable : {erreur}.", True
        except TypeError as erreur:
            return f"Arguments incorrects pour {nom} : {erreur}", True
        except Exception as erreur:  # un outil défaillant ne doit pas arrêter le travail
            return f"Échec de {nom} : {type(erreur).__name__} : {erreur}", True

    # --- Boucle ----------------------------------------------------------------
    def travailler(self, mode: str, demande: str) -> str:
        systeme = consignes(mode, decrire_modules(), decrire_outils(), bool(getattr(self.client, "recherche_web", "")))
        definitions = self.definitions(mode)
        messages = [{"role": "user", "content": demande}]
        derniers_textes: list = []
        for _ in range(self.tours_max):
            reponse = self.client.repondre(systeme, messages, definitions)
            self.jetons_entree += reponse.jetons_entree
            self.jetons_sortie += reponse.jetons_sortie
            messages.append({"role": "assistant", "content": reponse.contenu})
            texte = "\n".join(t for t in reponse.textes if t.strip()).strip()
            if texte:
                derniers_textes = [texte]

            if reponse.appels:
                if texte:
                    self.journal("message", texte)
                resultats = []
                for appel in reponse.appels:
                    if reponse.arret == "max_tokens":
                        contenu, erreur = "Appel coupé avant la fin : recommence avec un contenu plus court.", True
                    else:
                        self.journal("outil", f"{appel.nom} " + _json(
                            {k: (v if len(str(v)) < 200 else str(v)[:200] + "…") for k, v in appel.arguments.items()}, 600))
                        contenu, erreur = self.executer_outil(appel.nom, appel.arguments)
                        self.journal("erreur" if erreur else "resultat", _court(contenu, 1500))
                    bloc = {"type": "tool_result", "tool_use_id": appel.identifiant, "content": _court(contenu)}
                    if erreur:
                        bloc["is_error"] = True
                    resultats.append(bloc)
                messages.append({"role": "user", "content": resultats})
                continue
            if reponse.arret == "pause_turn":
                continue
            if reponse.arret == "max_tokens":
                messages.append({"role": "user", "content": "Ta réponse a été coupée. Termine par un compte rendu plus court."})
                continue
            if reponse.arret == "refusal":
                return "Le modèle d'IA a refusé de traiter cette demande."
            return texte or "Travail terminé sans compte rendu."
        return ("Nombre maximal d'allers-retours atteint avant la fin du travail.\n\n" + "\n".join(derniers_textes)).strip()
