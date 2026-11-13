"""Pages et API de l'agent IA, des modules proposés et des logiciels embarqués."""

from __future__ import annotations

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from .. import outils
from ..ia import propositions, travaux
from ..ia.client import configuration, configuree
from ..socle import modules
from ..socle.rendu import page

DEMANDE_MAX = 6000


def brancher(application: FastAPI, base, formulaire, fabrique_client=None) -> None:
    def ia_active() -> bool:
        return fabrique_client is not None or configuree()

    def travail_ou_404(numero: int) -> dict:
        travail = base.lire_travail(numero)
        if travail is None:
            raise HTTPException(404, "Travail inconnu.")
        return travail

    def proposition_ou_404(numero: int) -> dict:
        proposition = base.lire_proposition(numero)
        if proposition is None:
            raise HTTPException(404, "Proposition inconnue.")
        return proposition

    def page_ia(erreur: str = "", demande: str = "", mode: str = "pilote", statut: int = 200) -> HTMLResponse:
        c = configuration()
        return HTMLResponse(page(
            "ia.html", active=ia_active(), modele=c["modele"], recherche_web=bool(c["recherche_web"]),
            travaux=base.lister_travaux()[:30], propositions=base.lister_propositions()[:30], modes=travaux.MODES,
            erreur=erreur, demande=demande, mode=mode,
        ), statut)

    def page_proposition(numero: int, erreur: str = "", statut: int = 200) -> HTMLResponse:
        proposition = proposition_ou_404(numero)
        return HTMLResponse(page("proposition.html", p=proposition, erreur=erreur,
                                 actif=proposition["identifiant"] in {m.identifiant for m in modules.tous()}), statut)

    # --- Agent IA -------------------------------------------------------------
    @application.get("/ia", response_class=HTMLResponse, include_in_schema=False)
    def assistant():
        return page_ia()

    @application.post("/ia", include_in_schema=False)
    async def demander_travail(request: Request):
        saisie = await formulaire(request)
        mode = saisie.get("mode", "pilote")
        demande = saisie.get("demande", "").strip()
        if mode not in travaux.MODES:
            return page_ia("Choix inconnu.", demande, "pilote", 422)
        if not demande:
            return page_ia("Décrivez ce que vous voulez.", demande, mode, 422)
        if len(demande) > DEMANDE_MAX:
            return page_ia(f"La demande est trop longue ({DEMANDE_MAX} caractères au plus).", demande, mode, 422)
        if not ia_active():
            return page_ia("L'agent IA n'est pas configuré : il manque la clé d'API.", demande, mode, 409)
        numero = travaux.lancer(base, mode, demande, fabrique_client)
        return RedirectResponse(f"/ia/{numero}", status_code=303)

    @application.get("/ia/{numero}", response_class=HTMLResponse, include_in_schema=False)
    def voir_travail(numero: int):
        travail = travail_ou_404(numero)
        etudes_creees = []
        for ligne in travail["journal"]:
            if ligne["genre"] == "etude":
                etude = base.lire(int(ligne["texte"]))
                if etude:
                    etudes_creees.append({"id": etude["id"], "titre": etude["titre"]})
        return page(
            "travail.html", t=travail, mode=travaux.MODES.get(travail["mode"], travail["mode"]),
            journal=[l for l in travail["journal"] if l["genre"] != "etude"], etudes_creees=etudes_creees,
            propositions=base.lister_propositions(numero),
            fichiers=travaux.dossier_travail(base, numero).is_dir(),
            en_cours=travail["etat"] in ("en attente", "en cours"),
        )

    @application.get("/ia/{numero}/fichiers.zip", include_in_schema=False)
    def fichiers_travail(numero: int):
        travail_ou_404(numero)
        archive = travaux.archive_fichiers(base, numero)
        if archive is None:
            raise HTTPException(404, "Ce travail n'a produit aucun fichier.")
        return Response(archive, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="travail-{numero}-fichiers.zip"'})

    # --- Modules proposés -------------------------------------------------------
    @application.get("/propositions/{numero}", response_class=HTMLResponse, include_in_schema=False)
    def voir_proposition(numero: int):
        return page_proposition(numero)

    @application.post("/propositions/{numero}/valider", include_in_schema=False)
    async def valider_proposition(numero: int, request: Request):
        proposition = proposition_ou_404(numero)
        saisie = await formulaire(request)
        if saisie.get("relu") != "oui":
            return page_proposition(numero, "Cochez la case pour confirmer que vous avez relu le code.", 422)
        try:
            module = await run_in_threadpool(propositions.activer, base.dossier, proposition["identifiant"], proposition["code"])
        except Exception as erreur:
            return page_proposition(numero, f"Activation impossible : {erreur}", 422)
        base.etat_proposition(numero, "validée")
        return RedirectResponse(f"/modules/{module.identifiant}", status_code=303)

    @application.post("/propositions/{numero}/rejeter", include_in_schema=False)
    def rejeter_proposition(numero: int):
        proposition = proposition_ou_404(numero)
        if proposition["etat"] == "validée":
            propositions.desactiver(base.dossier, proposition["identifiant"])
        base.etat_proposition(numero, "rejetée")
        return RedirectResponse(f"/propositions/{numero}", status_code=303)

    # --- Logiciels embarqués ------------------------------------------------------
    @application.get("/outils", response_class=HTMLResponse, include_in_schema=False)
    def page_outils():
        return page("outils.html", outils=[
            {"nom": o.nom, "logiciel": o.logiciel, "role": o.role, "disponible": o.disponible(), "etat": o.etat()}
            for o in outils.tous()
        ], erreurs_modules=modules._ERREURS_AJOUTES)

    # --- API ------------------------------------------------------------------------
    @application.get("/api/outils", summary="Logiciels embarqués et leur état")
    def api_outils():
        return [{"identifiant": o.identifiant, "nom": o.nom, "logiciel": o.logiciel, "role": o.role,
                 "disponible": o.disponible(), "etat": o.etat()} for o in outils.tous()]

    @application.post("/api/ia/travaux", summary="Confier un travail à l'agent IA", status_code=202)
    def api_lancer_travail(corps: dict = Body(..., examples=[{"mode": "pilote", "demande": "Un drone qui porte 2 kg pendant 8 h, sans piste."}])):
        mode, demande = corps.get("mode", "pilote"), str(corps.get("demande", "")).strip()
        if mode not in travaux.MODES or not demande or len(demande) > DEMANDE_MAX:
            return JSONResponse({"erreur": "mode (pilote ou atelier) et demande sont obligatoires."}, status_code=422)
        if not ia_active():
            return JSONResponse({"erreur": "L'agent IA n'est pas configuré : il manque la clé d'API."}, status_code=409)
        return {"id": travaux.lancer(base, mode, demande, fabrique_client)}

    @application.get("/api/ia/travaux/{numero}", summary="État, journal et compte rendu d'un travail")
    def api_travail(numero: int):
        travail = travail_ou_404(numero)
        travail["propositions"] = base.lister_propositions(numero)
        return travail
