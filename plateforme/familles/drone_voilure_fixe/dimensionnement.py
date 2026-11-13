"""Dimensionnement d'un drone à voilure fixe, avec ou sans décollage vertical.

Principe : pour une surface d'aile et un allongement donnés, on cherche la
masse au décollage qui « boucle » (la somme des masses des éléments vaut la
masse totale), puis on balaie surfaces et allongements pour retenir le drone
le plus léger qui tient la mission.

Tous les coefficients sont des valeurs d'avant-projet. Ils devront être
recalés sur les pesées et les essais en vol du premier prototype.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from ...socle.atmosphere import DENSITE_NIVEAU_MER, G, Air
from ...socle.erreurs import BesoinInfaisable

DENSITE_ESSENCE = 0.74  # kg/L

# Consommation spécifique en croisière (kg de carburant par kWh à l'arbre),
# utilisée tant que YARED n'a pas fourni sa propre valeur.
CONSO_SPECIFIQUE_DEFAUT = {"2T": 0.60, "2T-ID": 0.42, "4T": 0.40}
# Masse du moteur thermique : (kg par kW nominal, masse fixe en kg),
# utilisée tant que YARED n'a pas fourni sa propre valeur.
MASSE_MOTEUR_DEFAUT = {"2T": (0.45, 0.3), "2T-ID": (0.50, 0.5), "4T": (0.80, 0.5)}



@dataclass
class Parametres:
    # --- Mission ---
    endurance_h: float
    air_vol: Air
    air_sol: Air
    reserve_min: float = 30.0
    m_charge_utile: float = 2.0  # kg
    p_charge_utile: float = 60.0  # W
    vtol: bool = True
    v_min: float = 16.0  # m/s
    envergure_max: float = 3.6  # m

    # --- Aérodynamique ---
    cl_max: float = 1.35  # portance maximale de l'aile, sans volets
    marge_decrochage: float = 1.30  # vitesse de vol / vitesse de décrochage
    vs_max_sans_vtol: float = 13.0  # m/s, décrochage maximal pour un avion à piste
    vs_max_vtol: float = 16.0  # m/s, pour une transition vertical -> horizontal courte et sûre
    cd_profil: float = 0.011  # traînée de profil de l'aile
    oswald: float = 0.80
    rapport_empennage: float = 0.22  # surface d'empennage / surface d'aile
    f_fuselage: float = 0.010  # surfaces de traînée équivalentes, m2
    f_nacelle_camera: float = 0.0045
    f_refroidissement: float = 0.004
    f_bras_vtol: float = 0.004
    f_helices_vtol: float = 0.008  # hélices de sustentation arrêtées en croisière
    allongement_max: float = 16.0
    corde_min: float = 0.15  # m

    # --- Propulsion de croisière ---
    type_moteur: str = "4T"
    conso_specifique: Optional[float] = None  # kg/kWh ; None = valeur par défaut du type
    masse_moteur: Optional[float] = None  # kg ; None = estimation par la puissance
    masse_moteur_electrique: Optional[float] = None  # kg par moteur de sustentation ; None = estimation
    rendement_helice: float = 0.68
    rendement_helice_montee: float = 0.60
    vz_montee: float = 2.0  # m/s
    taux_utilisation_montee: float = 0.85  # part de la puissance maxi utilisée en montée
    regime_max: float = 7000.0  # tr/min
    mach_bout_pale: float = 0.55

    # --- Électricité de bord ---
    p_avionique: float = 40.0  # W
    rendement_generatrice: float = 0.75
    m_generatrice: float = 0.55  # kg, redresseur compris
    m_avionique: float = 1.5  # kg : autopilote, GPS, radio, servos, câblage

    # --- Décollage vertical ---
    charge_disque: float = 200.0  # N/m2
    figure_de_merite: float = 0.65
    rendement_chaine_electrique: float = 0.85
    duree_stationnaire_min: float = 4.0  # décollage + atterrissage + marge
    marge_poussee: float = 1.8  # poussée maxi / poids
    energie_batterie: float = 160.0  # Wh/kg
    puissance_batterie: float = 3000.0  # W/kg (accus lithium-polymère forte décharge)
    profondeur_decharge: float = 0.80
    puissance_moteur_electrique: float = 5000.0  # W/kg en pointe
    secours_avionique_min: float = 10.0  # autonomie de l'électronique moteur arrêté

    # --- Structure ---
    k_aile: float = 1.8  # kg/m2 pour un allongement de 10
    k_empennage: float = 1.5  # kg/m2
    k_fuselage: float = 0.07  # part de la masse totale
    m_fuselage_fixe: float = 0.6  # kg
    k_bras_vtol: float = 0.035
    k_patins: float = 0.02
    k_train_roulant: float = 0.04

    # --- Carburant ---
    carburant_inutilisable: float = 0.05
    k_reservoir: float = 0.08  # masse du réservoir / masse de carburant
    m_circuit_carburant: float = 0.15  # kg

    # --- Majoration des masses pour une fabrication locale ---
    pen_structure: float = 1.0
    pen_moteur: float = 1.0
    pen_moteurs_electriques: float = 1.0

    @property
    def conso(self) -> float:
        if self.conso_specifique is not None:
            return self.conso_specifique
        return CONSO_SPECIFIQUE_DEFAUT[self.type_moteur]

    @property
    def p_electrique(self) -> float:
        return self.p_avionique + self.p_charge_utile


def _point_de_vol(p: Parametres, masse: float, surface: float, allongement: float) -> dict:
    """Vitesse la plus économique respectant les marges, et traînée associée."""
    rho = p.air_vol.densite
    poids = masse * G
    f = p.f_fuselage + p.f_nacelle_camera + p.f_refroidissement
    if p.vtol:
        f += p.f_bras_vtol + p.f_helices_vtol
    cd0 = p.cd_profil * (1.0 + p.rapport_empennage) + f / surface
    k = 1.0 / (math.pi * p.oswald * allongement)

    v_decrochage = math.sqrt(2.0 * poids / (rho * surface * p.cl_max))
    v_puissance_mini = math.sqrt(2.0 * poids / (rho * surface)) * (k / (3.0 * cd0)) ** 0.25
    vitesse = max(p.marge_decrochage * v_decrochage, v_puissance_mini, p.v_min)

    q = 0.5 * rho * vitesse**2
    cl = poids / (q * surface)
    cd = cd0 + k * cl**2
    trainee = q * surface * cd
    return {
        "vitesse": vitesse,
        "v_decrochage": v_decrochage,
        "cl": cl,
        "cd0": cd0,
        "finesse": cl / cd,
        "trainee": trainee,
        "puissance_vol": trainee * vitesse,
    }


def _puissance_arbre(p: Parametres, puissance_vol: float, rendement_helice: float) -> float:
    """Puissance demandée au moteur : hélice plus génératrice."""
    return puissance_vol / rendement_helice + p.p_electrique / p.rendement_generatrice


def evaluer(p: Parametres, surface: float, allongement: float) -> Optional[dict]:
    """Boucle la masse pour une aile donnée. Renvoie None si ça ne converge pas."""
    envergure = math.sqrt(allongement * surface)
    duree_s = (p.endurance_h + p.reserve_min / 60.0) * 3600.0
    pas = 24
    masse = 12.0

    for _ in range(300):
        # --- Carburant : vol découpé en tranches, la masse baisse au fil du vol
        m_courante = masse
        carburant_brule = 0.0
        for _ in range(pas):
            pv = _point_de_vol(p, m_courante, surface, allongement)
            p_arbre = _puissance_arbre(p, pv["puissance_vol"], p.rendement_helice)
            brule = p.conso * (p_arbre / 1000.0) * (duree_s / pas / 3600.0)
            carburant_brule += brule
            m_courante -= brule
            if m_courante <= 0.2 * masse:  # il faudrait plus de carburant que le drone ne pèse
                return None
        m_carburant = carburant_brule * (1.0 + p.carburant_inutilisable)
        m_reservoir = p.k_reservoir * m_carburant + p.m_circuit_carburant

        # --- Moteur : dimensionné par la montée à pleine masse
        croisiere = _point_de_vol(p, masse, surface, allongement)
        p_croisiere = _puissance_arbre(p, croisiere["puissance_vol"], p.rendement_helice)
        p_montee_vol = croisiere["puissance_vol"] + masse * G * p.vz_montee
        p_montee = _puissance_arbre(p, p_montee_vol, p.rendement_helice_montee)
        p_max_altitude = p_montee / p.taux_utilisation_montee
        p_nominale_sol = p_max_altitude * DENSITE_NIVEAU_MER / p.air_vol.densite
        if p.masse_moteur is not None:
            m_moteur = p.masse_moteur
        else:
            par_kw, fixe = MASSE_MOTEUR_DEFAUT[p.type_moteur]
            m_moteur = p.pen_moteur * (par_kw * p_nominale_sol / 1000.0 + fixe)

        # --- Décollage vertical
        vertical = {}
        m_vertical = 0.0
        if p.vtol:
            poids = masse * G
            surface_disques = poids / p.charge_disque
            diametre = math.sqrt(surface_disques / math.pi)  # 4 hélices
            p_ideale = poids**1.5 / math.sqrt(2.0 * p.air_sol.densite * surface_disques)
            p_stationnaire = p_ideale / p.figure_de_merite / p.rendement_chaine_electrique
            energie = (
                p_stationnaire * p.duree_stationnaire_min / 60.0
                + p.p_electrique * p.secours_avionique_min / 60.0
            ) / p.profondeur_decharge
            p_pointe = p_stationnaire * 1.5
            m_batterie = max(energie / p.energie_batterie, p_pointe / p.puissance_batterie)
            p_moteur_maxi = p_stationnaire / 4.0 * p.marge_poussee**1.5
            if p.masse_moteur_electrique is not None:
                m_moteurs = 4.0 * p.masse_moteur_electrique
            else:
                m_moteurs = p.pen_moteurs_electriques * 4.0 * p_moteur_maxi / p.puissance_moteur_electrique
            m_controleurs = 4.0 * (0.03 + p_moteur_maxi / 25000.0)
            m_helices = 4.0 * 0.25 * diametre**2
            m_vertical = m_batterie + m_moteurs + m_controleurs + m_helices
            vertical = {
                "diametre_helice": diametre,
                "p_stationnaire": p_stationnaire,
                "p_moteur_maxi": p_moteur_maxi,
                "poussee_maxi_par_moteur": p.marge_poussee * poids / 4.0,
                "energie_batterie_wh": energie,
                "m_batterie": m_batterie,
                "m_moteurs": m_moteurs,
                "m_controleurs": m_controleurs,
                "m_helices": m_helices,
            }
        else:
            # Sans décollage vertical : petite batterie tampon pour l'électronique
            energie = p.p_electrique * p.secours_avionique_min / 60.0 / p.profondeur_decharge
            m_vertical = energie / p.energie_batterie
            vertical = {"energie_batterie_wh": energie, "m_batterie": m_vertical}

        # --- Structure
        m_aile = p.k_aile * surface * (allongement / 10.0) ** 0.6
        m_empennage = p.k_empennage * p.rapport_empennage * surface
        m_fuselage = p.k_fuselage * masse + p.m_fuselage_fixe
        m_bras = p.k_bras_vtol * masse if p.vtol else 0.0
        m_train = (p.k_patins if p.vtol else p.k_train_roulant) * masse
        m_structure = p.pen_structure * (m_aile + m_empennage + m_fuselage + m_bras + m_train)

        masses = {
            "Charge utile": p.m_charge_utile,
            "Structure": m_structure,
            "Moteur thermique": m_moteur,
            "Génératrice": p.m_generatrice,
            "Carburant": m_carburant,
            "Réservoir et circuit": m_reservoir,
            "Décollage vertical" if p.vtol else "Batterie tampon": m_vertical,
            "Avionique": p.m_avionique,
        }
        nouvelle = sum(masses.values())
        if nouvelle > 150.0 or not math.isfinite(nouvelle):
            return None
        if abs(nouvelle - masse) < 1e-5:
            masse = nouvelle
            break
        masse = 0.5 * masse + 0.5 * nouvelle
    else:
        return None

    vs_max = p.vs_max_vtol if p.vtol else p.vs_max_sans_vtol
    if croisiere["v_decrochage"] > vs_max:
        return None

    return {
        "masse_totale": masse,
        "masses": masses,
        "detail_structure": {
            "Aile": p.pen_structure * m_aile,
            "Empennage": p.pen_structure * m_empennage,
            "Fuselage": p.pen_structure * m_fuselage,
            "Bras de sustentation": p.pen_structure * m_bras,
            "Atterrisseur": p.pen_structure * m_train,
        },
        "surface": surface,
        "allongement": allongement,
        "envergure": envergure,
        "corde": surface / envergure,
        "croisiere": croisiere,
        "p_croisiere_arbre": p_croisiere,
        "p_montee_arbre": p_montee,
        "p_max_altitude": p_max_altitude,
        "p_nominale_sol": p_nominale_sol,
        "carburant_kg": m_carburant,
        "carburant_l": m_carburant / DENSITE_ESSENCE,
        "conso_moyenne_g_h": carburant_brule / (duree_s / 3600.0) * 1000.0,
        "conso_specifique": p.conso,
        "vertical": vertical,
        "type_moteur": p.type_moteur,
    }


def dimensionner(p: Parametres) -> dict:
    """Cherche l'aile donnant le drone le plus léger : balayage large, puis affinage."""

    def balayer(surfaces, allongements, meilleur):
        for surface in surfaces:
            for allongement in allongements:
                if allongement < 7.0 or allongement > p.allongement_max or surface < 0.2:
                    continue
                envergure = math.sqrt(allongement * surface)
                if envergure > p.envergure_max or surface / envergure < p.corde_min:
                    continue
                resultat = evaluer(p, float(surface), float(allongement))
                if resultat and (meilleur is None or resultat["masse_totale"] < meilleur["masse_totale"]):
                    meilleur = resultat
        return meilleur

    meilleur = balayer(np.arange(0.40, 3.001, 0.20), np.arange(7.0, p.allongement_max + 0.001, 1.5), None)
    if meilleur is None:  # domaine étroit : balayage fin complet
        meilleur = balayer(np.arange(0.40, 3.001, 0.05), np.arange(7.0, p.allongement_max + 0.001, 0.5), None)
    if meilleur is None:
        raise BesoinInfaisable(
            "Aucun drone ne tient cette mission avec les hypothèses retenues. "
            "Pistes : réduire l'endurance ou la charge utile, autoriser une envergure plus grande."
        )
    s0, a0 = meilleur["surface"], meilleur["allongement"]
    return balayer(np.arange(s0 - 0.20, s0 + 0.201, 0.05), np.arange(a0 - 1.5, a0 + 1.501, 0.5), meilleur)


def cahier_des_charges_moteur(p: Parametres, resultat: dict) -> dict:
    """Ce que YAME demande à YARED pour le moteur thermique."""
    p_max = resultat["p_max_altitude"]
    p_croisiere = resultat["p_croisiere_arbre"]
    # Diamètre d'hélice : loi empirique sur les moteurs de cette classe.
    diametre = 0.362 * (resultat["p_nominale_sol"] / 1000.0) ** 0.25
    vitesse_son = math.sqrt(1.4 * 287.05 * p.air_vol.temperature)
    regime_bout_pale = p.mach_bout_pale * vitesse_son / (math.pi * diametre) * 60.0
    regime_max = min(p.regime_max, regime_bout_pale)
    # Hélice à pas fixe : la puissance absorbée varie comme le cube du régime.
    regime_croisiere = regime_max * (p_croisiere / p_max) ** (1.0 / 3.0)
    return {
        "type": p.type_moteur,
        "puissance_max_w": p_max,
        "puissance_croisiere_w": p_croisiere,
        "regime_max_tr_min": regime_max,
        "regime_croisiere_tr_min": regime_croisiere,
        "diametre_helice_m": diametre,
        "pression_air_pa": p.air_vol.pression,
        "temperature_air_k": p.air_vol.temperature,
        "duree_vol_h": p.endurance_h + p.reserve_min / 60.0,
        "majoration_masse": p.pen_moteur,
    }
