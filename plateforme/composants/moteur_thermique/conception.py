"""Conception préliminaire du moteur à partir du cahier des charges de YAME.

Étapes :
1. chercher la cylindrée qui donne la puissance maximale demandée, plein gaz,
   au régime maximal, dans l'air chaud de l'altitude de vol ;
2. chercher l'ouverture des gaz qui donne la puissance de croisière ;
3. en tirer la consommation en croisière, la masse estimée et les grandeurs
   utiles à la suite (efforts, chaleur à évacuer).
"""

from __future__ import annotations

import math

from .cycle import Moteur, simuler

# Choix de conception par variante. Ce sont des hypothèses de départ.
VARIANTES = {
    "4T": {
        "libelle": "4 temps, injection à l'admission",
        "alesage_sur_course": 1.10,
        "taux_compression": 8.5,
        "rapport_bielle": 1.9,
        "richesse_lambda": 1.0,
        "moteur": {"rendement_volumetrique": 0.78, "rendement_combustion": 0.92, "duree_combustion": 45.0},
        "masse_par_cm3": 0.035,
        "masse_fixe": 0.40,
        "pieces_mobiles": "piston, bielle, vilebrequin, arbre à cames, 2 soupapes, culbuteurs",
        "difficulte": "moyenne : distribution par soupapes à usiner et à régler",
    },
    "2T": {
        "libelle": "2 temps, mélange préparé",
        "alesage_sur_course": 1.15,
        "taux_compression": 9.5,
        "rapport_bielle": 2.0,
        "richesse_lambda": 0.90,
        "moteur": {"taux_balayage_max": 0.75, "rendement_combustion": 0.90, "duree_combustion": 50.0},
        "masse_par_cm3": 0.022,
        "masse_fixe": 0.35,
        "pieces_mobiles": "piston, bielle, vilebrequin",
        "difficulte": "faible : trois pièces mobiles, lumières dans le cylindre",
    },
    "2T-ID": {
        "libelle": "2 temps, injection directe",
        "alesage_sur_course": 1.15,
        "taux_compression": 9.5,
        "rapport_bielle": 2.0,
        "richesse_lambda": 1.0,
        "moteur": {"taux_balayage_max": 0.75, "rendement_combustion": 0.90, "duree_combustion": 50.0},
        "masse_par_cm3": 0.024,
        "masse_fixe": 0.55,
        "pieces_mobiles": "piston, bielle, vilebrequin, plus injecteur et pompe haute pression",
        "difficulte": "élevée : injecteur dans la culasse, pompe, calculateur à mettre au point",
    },
}


def _moteur(type_moteur: str, cylindree: float) -> Moteur:
    v = VARIANTES[type_moteur]
    ratio = v["alesage_sur_course"]
    course = (4.0 * cylindree / (math.pi * ratio**2)) ** (1.0 / 3.0)
    return Moteur(
        type=type_moteur,
        alesage=ratio * course,
        course=course,
        taux_compression=v["taux_compression"],
        rapport_bielle=v["rapport_bielle"],
        **v["moteur"],
    )


def _dichotomie(fonction, bas: float, haut: float, cible: float, iterations: int = 50) -> float:
    """Cherche x tel que fonction(x) = cible, pour une fonction croissante."""
    for _ in range(iterations):
        milieu = 0.5 * (bas + haut)
        if fonction(milieu) < cible:
            bas = milieu
        else:
            haut = milieu
    return 0.5 * (bas + haut)


def concevoir(cdc: dict, type_moteur: str | None = None) -> dict:
    """Conçoit un moteur répondant au cahier des charges `cdc`."""
    type_moteur = type_moteur or cdc["type"]
    v = VARIANTES[type_moteur]
    pression, temperature = cdc["pression_air_pa"], cdc["temperature_air_k"]
    lam = v["richesse_lambda"]

    def plein_gaz(cylindree: float) -> float:
        return simuler(_moteur(type_moteur, cylindree), cdc["regime_max_tr_min"], 1.0, pression, temperature, lam)["puissance_w"]

    cylindree = _dichotomie(plein_gaz, 5e-6, 500e-6, cdc["puissance_max_w"])
    moteur = _moteur(type_moteur, cylindree)
    maxi = simuler(moteur, cdc["regime_max_tr_min"], 1.0, pression, temperature, lam)

    def a_charge(charge: float) -> float:
        return simuler(moteur, cdc["regime_croisiere_tr_min"], charge, pression, temperature, lam)["puissance_w"]

    charge = _dichotomie(a_charge, 0.05, 1.0, cdc["puissance_croisiere_w"])
    croisiere = simuler(moteur, cdc["regime_croisiere_tr_min"], charge, pression, temperature, lam)

    cm3 = cylindree * 1e6
    masse = cdc.get("majoration_masse", 1.0) * (v["masse_par_cm3"] * cm3 + v["masse_fixe"])
    alertes = []
    if maxi["vitesse_piston_m_s"] > 12.0:
        alertes.append("Vitesse de piston élevée au régime maximal : usure à surveiller.")
    if croisiere["fraction_residuels"] > 0.30:
        alertes.append("Beaucoup de gaz brûlés résiduels en croisière : combustion irrégulière probable.")
    if abs(croisiere["puissance_w"] - cdc["puissance_croisiere_w"]) > 0.02 * cdc["puissance_croisiere_w"]:
        alertes.append("La puissance de croisière demandée est hors de la plage du modèle.")

    return {
        "type": type_moteur,
        "libelle": v["libelle"],
        "cylindree_cm3": cm3,
        "alesage_mm": moteur.alesage * 1000.0,
        "course_mm": moteur.course * 1000.0,
        "taux_compression": moteur.taux_compression,
        "masse_kg": masse,
        "plein_gaz": maxi,
        "croisiere": croisiere,
        "conso_croisiere": croisiere["conso_specifique"],
        "carburant_par_vol_kg": croisiere["debit_carburant_g_h"] / 1000.0 * cdc["duree_vol_h"],
        "pieces_mobiles": v["pieces_mobiles"],
        "difficulte": v["difficulte"],
        "alertes": alertes,
    }


# Du plus simple au plus difficile à fabriquer.
RANG_FABRICATION = {"2T": 1, "4T": 2, "2T-ID": 3}
TOLERANCE = 0.10


def retenir(candidats: list, critere, type_de=lambda c: c["type"]) -> int:
    """Indice du candidat retenu.

    Règle : parmi les candidats dont le critère (une masse, en général) est à
    moins de 10 % du meilleur — moins que l'incertitude du modèle —, on prend
    le moteur le plus simple à fabriquer.
    """
    meilleur = min(critere(c) for c in candidats)
    comparables = [i for i, c in enumerate(candidats) if critere(c) <= (1.0 + TOLERANCE) * meilleur]
    return min(comparables, key=lambda i: (RANG_FABRICATION[type_de(candidats[i])], critere(candidats[i])))
