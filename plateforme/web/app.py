"""Application web (pages) et API (JSON).

L'interface est entièrement générée à partir des modules : formulaires depuis
leurs questions, rapports depuis leurs études.

Configuration par variables d'environnement :
- YAME_DONNEES       dossier de la base de données (défaut : ./donnees)
- YAME_UTILISATEUR   identifiant de connexion (défaut : yame)
- YAME_MOT_DE_PASSE  mot de passe. S'il est vide, aucune connexion n'est
                     demandée : à réserver à un usage sur votre propre machine.
- YAME_EXIGER_MOT_DE_PASSE  s'il vaut 1, l'application refuse de démarrer sans
                     mot de passe. L'image Docker le fixe à 1.
- YAME_IA_CLE et les autres réglages de l'agent IA : voir plateforme/ia/client.py.
"""

from __future__ import annotations

import base64
import os
import secrets
from urllib.parse import parse_qs, urlsplit

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from .. import __version__
from ..ia import propositions
from ..socle import dossier, modules
from ..socle.erreurs import ErreurEtude
from ..socle.modele import Etude
from ..socle.rendu import page, rapport_autonome
from ..socle.stockage import EtapeVerrouillee, Stockage
from .ia import brancher as brancher_ia


def creer_application(stockage: Stockage | None = None, fabrique_client=None) -> FastAPI:
    application = FastAPI(
        title="YAME / YARED", version=__version__,
        description="Conception de matériels par simulation : dimensionnement d'un système (YAME) et conception de composants (YARED).",
    )
    base = stockage or Stockage()
    utilisateur = os.environ.get("YAME_UTILISATEUR", "yame")
    mot_de_passe = os.environ.get("YAME_MOT_DE_PASSE", "")
    if os.environ.get("YAME_EXIGER_MOT_DE_PASSE") == "1" and not mot_de_passe:
        # Garde-fou des déploiements : jamais d'application exposée sans connexion.
        raise RuntimeError(
            "YAME_MOT_DE_PASSE est vide. Définissez un mot de passe avant de démarrer "
            "(fichier .env), ou retirez YAME_EXIGER_MOT_DE_PASSE pour un usage sur votre propre machine."
        )

    # Modules validés après coup, et travaux de l'agent coupés par un arrêt du serveur.
    modules.charger_ajoutes(propositions.dossier_des_ajouts(base.dossier))
    base.interrompre_travaux_en_cours()

    def noms() -> dict:
        return {m.identifiant: m.nom for m in modules.tous()}

    # --- Sécurité -----------------------------------------------------------
    @application.middleware("http")
    async def securite(request: Request, suite):
        if request.url.path != "/sante":
            if mot_de_passe:
                entete = request.headers.get("authorization", "")
                autorise = False
                if entete.lower().startswith("basic "):
                    try:
                        nom, _, secret = base64.b64decode(entete[6:]).decode("utf-8").partition(":")
                        autorise = secrets.compare_digest(nom, utilisateur) and secrets.compare_digest(secret, mot_de_passe)
                    except Exception:
                        autorise = False
                if not autorise:
                    return Response("Connexion requise.", status_code=401,
                                    headers={"WWW-Authenticate": 'Basic realm="YAME", charset="UTF-8"'})
            # Une page d'un autre site ne doit pas pouvoir déclencher une action ici.
            origine = request.headers.get("origin")
            if request.method not in ("GET", "HEAD", "OPTIONS") and origine:
                if urlsplit(origine).netloc != request.headers.get("host", ""):
                    return Response("Requête refusée : origine inattendue.", status_code=403)
        reponse = await suite(request)
        reponse.headers["X-Content-Type-Options"] = "nosniff"
        reponse.headers["X-Frame-Options"] = "DENY"
        reponse.headers["Referrer-Policy"] = "same-origin"
        return reponse

    # --- Outils -------------------------------------------------------------
    async def formulaire(request: Request) -> dict:
        corps = (await request.body()).decode("utf-8")
        return {cle: valeurs[-1] for cle, valeurs in parse_qs(corps, keep_blank_values=True).items()}

    def module_ou_404(identifiant: str):
        try:
            return modules.obtenir(identifiant)
        except KeyError:
            raise HTTPException(404, "Module inconnu.") from None

    def etude_ou_404(identifiant: int) -> dict:
        ligne = base.lire(identifiant)
        if ligne is None:
            raise HTTPException(404, "Étude inconnue.")
        ligne["objet"] = Etude.depuis_dict(ligne["etude"])
        return ligne

    def creer_etude(module, reponses: dict) -> int:
        etude = module.etudier(reponses)
        return base.creer(module.identifiant, etude.titre, reponses, etude.en_dict())

    def page_formulaire(module, valeurs: dict, erreur: str = "", statut: int = 200) -> HTMLResponse:
        avancees = {q.cle for q in module.questions if q.avance} | {"expert"}
        ouvrir = any(str(valeurs.get(cle, "")).strip() for cle in avancees)
        return HTMLResponse(page("formulaire.html", module=module, valeurs=valeurs, erreur=erreur, ouvrir_precisions=ouvrir), statut)

    # --- Pages --------------------------------------------------------------
    @application.get("/sante", include_in_schema=False)
    def sante():
        return {"etat": "ok", "version": __version__}

    @application.get("/", response_class=HTMLResponse, include_in_schema=False)
    def accueil():
        tous = modules.tous()
        return page("accueil.html", familles=[m for m in tous if m.genre == "famille"],
                    composants=[m for m in tous if m.genre == "composant"], etudes=base.lister()[:8], noms=noms())

    @application.get("/etudes", response_class=HTMLResponse, include_in_schema=False)
    def liste_etudes():
        return page("etudes.html", etudes=base.lister(), noms=noms())

    @application.get("/modules/{identifiant}", response_class=HTMLResponse, include_in_schema=False)
    def nouvelle_etude(identifiant: str):
        return page_formulaire(module_ou_404(identifiant), {})

    @application.post("/modules/{identifiant}", include_in_schema=False)
    async def lancer_etude(identifiant: str, request: Request):
        module = module_ou_404(identifiant)
        reponses = await formulaire(request)
        try:
            numero = await run_in_threadpool(creer_etude, module, reponses)
        except ErreurEtude as erreur:
            return page_formulaire(module, reponses, str(erreur), 422)
        return RedirectResponse(f"/etudes/{numero}", status_code=303)

    @application.get("/etudes/{identifiant}", response_class=HTMLResponse, include_in_schema=False)
    def voir_etude(identifiant: int):
        ligne = etude_ou_404(identifiant)
        etude = ligne["objet"]
        return page("etude.html", etude=etude, identifiant=identifiant, cree_le=ligne["cree_le"], noms=noms(),
                    nom_module=noms().get(etude.module, etude.module), composants=etude.donnees.get("composants", []),
                    nb_validees=len(base.avancement(identifiant)))

    @application.get("/etudes/{identifiant}/modifier", response_class=HTMLResponse, include_in_schema=False)
    def modifier_etude(identifiant: int):
        ligne = etude_ou_404(identifiant)
        valeurs = dict(ligne["reponses"])
        if isinstance(valeurs.get("expert"), dict):
            valeurs["expert"] = "\n".join(f"{cle} = {valeur!r}" for cle, valeur in valeurs["expert"].items())
        return page_formulaire(module_ou_404(ligne["module"]), valeurs)

    @application.post("/etudes/{identifiant}/supprimer", include_in_schema=False)
    def supprimer_etude(identifiant: int):
        base.supprimer(identifiant)
        return RedirectResponse("/etudes", status_code=303)

    @application.post("/etudes/{identifiant}/composants/{indice}", include_in_schema=False)
    async def ouvrir_composant(identifiant: int, indice: int):
        composants = etude_ou_404(identifiant)["objet"].donnees.get("composants", [])
        if not 0 <= indice < len(composants):
            raise HTTPException(404, "Composant inconnu.")
        composant = composants[indice]
        try:
            numero = await run_in_threadpool(creer_etude, module_ou_404(composant["module"]), composant["reponses"])
        except ErreurEtude as erreur:
            raise HTTPException(422, str(erreur)) from None
        return RedirectResponse(f"/etudes/{numero}", status_code=303)

    @application.get("/etudes/{identifiant}/rapport.html", response_class=HTMLResponse, include_in_schema=False)
    def rapport(identifiant: int):
        etude = etude_ou_404(identifiant)["objet"]
        return rapport_autonome(etude, noms().get(etude.module, etude.module), base.avancement(identifiant))

    @application.get("/etudes/{identifiant}/dossier.zip", include_in_schema=False)
    async def telecharger_dossier(identifiant: int):
        etude = etude_ou_404(identifiant)["objet"]
        contenu = await run_in_threadpool(dossier.construire, etude, base.avancement(identifiant))
        nom = f"dossier-{identifiant}-{dossier.nom_de_fichier(etude.titre)}.zip"
        return Response(contenu, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{nom}"'})

    # --- Plan de prototypage ------------------------------------------------
    def page_plan(identifiant: int, erreur: str = "", statut: int = 200) -> HTMLResponse:
        etude = etude_ou_404(identifiant)["objet"]
        return HTMLResponse(page("plan.html", etude=etude, identifiant=identifiant, avancement=base.avancement(identifiant),
                                 nom_module=noms().get(etude.module, etude.module), erreur=erreur), statut)

    @application.get("/etudes/{identifiant}/plan", response_class=HTMLResponse, include_in_schema=False)
    def plan(identifiant: int):
        return page_plan(identifiant)

    @application.post("/etudes/{identifiant}/plan/annuler", include_in_schema=False)
    def annuler_etape(identifiant: int):
        etude_ou_404(identifiant)
        base.annuler_derniere_etape(identifiant)
        return RedirectResponse(f"/etudes/{identifiant}/plan", status_code=303)

    @application.post("/etudes/{identifiant}/plan/{numero}", include_in_schema=False)
    async def valider_etape(identifiant: int, numero: int, request: Request):
        etude = etude_ou_404(identifiant)["objet"]
        if not 1 <= numero <= len(etude.etapes):
            raise HTTPException(404, "Étape inconnue.")
        attendue = len(base.avancement(identifiant)) + 1
        if numero != attendue:
            return page_plan(identifiant, f"L'étape à valider est la n° {attendue}, pas la n° {numero}.", 409)
        saisie = await formulaire(request)
        etape = etude.etapes[numero - 1]
        releves = {mesure: saisie.get(f"m{i}", "").strip() for i, mesure in enumerate(etape.mesures)}
        manquantes = [mesure for mesure, valeur in releves.items() if not valeur]
        if manquantes:
            return page_plan(identifiant, "Mesure manquante : " + " ; ".join(manquantes), 422)
        if saisie.get("critere") != "oui":
            return page_plan(identifiant, "Cochez la case pour confirmer que le critère de réussite est atteint.", 422)
        if saisie.get("observations", "").strip():
            releves["Observations"] = saisie["observations"].strip()
        try:
            base.valider_etape(identifiant, numero, releves)
        except EtapeVerrouillee as erreur:
            return page_plan(identifiant, str(erreur), 409)
        return RedirectResponse(f"/etudes/{identifiant}/plan#etape-{numero + 1}", status_code=303)

    # --- API ----------------------------------------------------------------
    @application.get("/api/modules", summary="Liste des modules et de leurs questions")
    def api_modules():
        return [{"identifiant": m.identifiant, "nom": m.nom, "genre": m.genre, "description": m.description,
                 "questions": [q.__dict__ for q in m.questions], "exemple": m.exemple} for m in modules.tous()]

    @application.post("/api/modules/{identifiant}/etudes", summary="Lancer une étude", status_code=201)
    async def api_lancer(identifiant: str, reponses: dict = Body(..., examples=[{"endurance_h": 8, "charge_utile_kg": 2}])):
        module = module_ou_404(identifiant)
        try:
            numero = await run_in_threadpool(creer_etude, module, reponses)
        except ErreurEtude as erreur:
            return JSONResponse({"erreur": str(erreur)}, status_code=422)
        return {"id": numero, "etude": base.lire(numero)["etude"]}

    @application.get("/api/etudes", summary="Liste des études")
    def api_etudes():
        return base.lister()

    @application.get("/api/etudes/{identifiant}", summary="Une étude, avec l'avancement de son prototypage")
    def api_etude(identifiant: int):
        ligne = etude_ou_404(identifiant)
        ligne.pop("objet")
        ligne["avancement"] = {str(k): v for k, v in base.avancement(identifiant).items()}
        return ligne

    brancher_ia(application, base, formulaire, fabrique_client)
    return application

