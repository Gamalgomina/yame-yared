"""Contrôle et activation des modules proposés par l'agent IA.

Parcours d'un module proposé :
1. l'agent écrit le code et le soumet ;
2. le code est contrôlé dans le bac à sable : il doit se charger, enregistrer
   un module, réussir l'étude de son propre exemple, fournir un plan de
   prototypage et des limites, et produire un dossier ;
3. la proposition attend la relecture d'une personne ;
4. si elle est validée, le fichier est copié dans le dossier des modules
   ajoutés et chargé. Il tourne alors avec les droits de la plateforme :
   la validation est une décision de confiance.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..outils import bac_a_sable
from ..socle import modules

MOTIF_IDENTIFIANT = re.compile(r"^[a-z][a-z0-9-]{2,40}$")

CONTROLE = r'''
import importlib.util, json, sys
from plateforme.socle import modules
from plateforme.socle.modele import Etude, Question
from plateforme.socle.erreurs import ErreurEtude
from plateforme.socle import dossier

ATTENDU = __ATTENDU__
avant = {m.identifiant for m in modules.tous()}
spec = importlib.util.spec_from_file_location("module_propose", "module_propose.py")
code = importlib.util.module_from_spec(spec)
spec.loader.exec_module(code)
nouveaux = [m for m in modules.tous() if m.identifiant not in avant]
problemes = []
if len(nouveaux) != 1:
    print("::YAME::" + json.dumps({"problemes": [f"Le fichier doit enregistrer exactement un module avec enregistrer(...). Trouvé : {len(nouveaux)}."]}))
    sys.exit(0)
m = nouveaux[0]
if m.identifiant != ATTENDU:
    problemes.append(f"L'identifiant du module est « {m.identifiant} » au lieu de « {ATTENDU} ».")
if m.genre not in ("famille", "composant"):
    problemes.append("genre doit valoir « famille » ou « composant ».")
if not m.nom or not m.description:
    problemes.append("nom et description sont obligatoires.")
if not m.questions or not all(isinstance(q, Question) for q in m.questions):
    problemes.append("questions doit être une liste non vide d'objets Question.")
if not m.exemple:
    problemes.append("exemple (réponses d'exemple) est obligatoire.")
resume = {}
if not problemes:
    etude = m.etudier(dict(m.exemple))
    if not isinstance(etude, Etude):
        problemes.append("etudier doit renvoyer une Etude.")
    else:
        if not etude.chiffres: problemes.append("L'étude doit donner des chiffres clés.")
        if not etude.sections: problemes.append("L'étude doit contenir au moins une section de résultats.")
        if not etude.hypotheses: problemes.append("L'étude doit rendre ses hypothèses (r.registre.en_dicts()).")
        if len(etude.etapes) < 4: problemes.append("Le plan de prototypage doit compter au moins 4 étapes.")
        if any(not e.critere or not e.actions for e in etude.etapes):
            problemes.append("Chaque étape doit avoir des actions et un critère de réussite.")
        if not etude.limites: problemes.append("L'étude doit énoncer ses limites.")
        json.dumps(etude.en_dict())
        archive = dossier.construire(etude)
        resume = {
            "titre": etude.titre,
            "chiffres": [[c.valeur, c.libelle] for c in etude.chiffres],
            "etapes": [e.titre for e in etude.etapes],
            "limites": etude.limites,
            "taille_dossier": len(archive),
        }
    if any(q.obligatoire for q in m.questions):
        try:
            m.etudier({})
            problemes.append("Sans les réponses obligatoires, etudier doit lever BesoinIncomplet.")
        except ErreurEtude:
            pass
print("::YAME::" + json.dumps({"problemes": problemes, "resume": resume, "nom": m.nom, "genre": m.genre}))
'''


def controler(identifiant: str, code: str) -> dict:
    """Contrôle un module proposé. Renvoie {"valide": bool, "rapport": texte, "resume": dict}."""
    if not MOTIF_IDENTIFIANT.match(identifiant or ""):
        return {"valide": False, "resume": {},
                "rapport": "Identifiant invalide : minuscules, chiffres et tirets, de 3 à 41 caractères, commençant par une lettre."}
    if identifiant in modules.integres():
        return {"valide": False, "resume": {}, "rapport": f"« {identifiant} » est déjà un module de la plateforme."}
    try:
        compile(code, "module_propose.py", "exec")
    except SyntaxError as erreur:
        return {"valide": False, "resume": {}, "rapport": f"Erreur de syntaxe ligne {erreur.lineno} : {erreur.msg}"}
    sortie = bac_a_sable.executer(
        CONTROLE.replace("__ATTENDU__", json.dumps(identifiant)), duree_max=180,
        fichiers={"module_propose.py": code.encode("utf-8")},
    )
    ligne = next((l for l in sortie.sortie.splitlines() if l.startswith("::YAME::")), None)
    if ligne is None:
        return {"valide": False, "resume": {}, "rapport": "Le module a échoué pendant le contrôle.\n" + sortie.resume(4000)}
    resultat = json.loads(ligne[len("::YAME::"):])
    if resultat["problemes"]:
        return {"valide": False, "resume": resultat.get("resume", {}),
                "rapport": "Problèmes à corriger :\n- " + "\n- ".join(resultat["problemes"])}
    resume = resultat["resume"]
    rapport = (
        f"Contrôle réussi. Étude de l'exemple : « {resume['titre']} ».\n"
        + "Chiffres clés : " + " ; ".join(f"{v} ({l})" for v, l in resume["chiffres"]) + "\n"
        + f"Plan de prototypage : {len(resume['etapes'])} étapes.\n"
        + f"Limites énoncées : {len(resume['limites'])}."
    )
    return {"valide": True, "resume": resume, "rapport": rapport}


def dossier_des_ajouts(dossier_donnees) -> Path:
    return Path(dossier_donnees) / "modules_ajoutes"


def activer(dossier_donnees, identifiant: str, code: str):
    """Installe un module validé et le charge. Renvoie le module."""
    verification = controler(identifiant, code)
    if not verification["valide"]:
        raise ValueError(verification["rapport"])
    dossier = dossier_des_ajouts(dossier_donnees)
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"{identifiant}.py"
    modules.retirer(identifiant) if identifiant not in modules.integres() else None
    chemin.write_text(code, encoding="utf-8")
    try:
        return modules.charger_fichier(chemin)
    except Exception:
        chemin.unlink(missing_ok=True)
        raise


def desactiver(dossier_donnees, identifiant: str) -> None:
    modules.retirer(identifiant)
    (dossier_des_ajouts(dossier_donnees) / f"{identifiant}.py").unlink(missing_ok=True)
