"""Pré-dimensionnement des pièces du moteur.

Règles classiques de construction mécanique (plaque en flexion, poutre,
flambement, pression de contact), appliquées aux efforts calculés par la
simulation du cycle. Les contraintes admissibles sont volontairement basses,
pour des matières et des procédés d'atelier non certifiés.

Ce sont des cotes de départ pour dessiner et fabriquer un premier prototype
de banc d'essai, pas des cotes validées pour le vol.
"""

from __future__ import annotations

import math

# Contraintes admissibles (Pa), coefficients de sécurité inclus.
SIGMA_PISTON = 35e6  # alliage d'aluminium moulé, à chaud
SIGMA_BIELLE = 100e6  # acier mi-dur usiné, en fatigue
SIGMA_VILEBREQUIN = 90e6  # acier traité, en fatigue, avec concentration de contraintes
SIGMA_AXE = 250e6  # acier cémenté
SIGMA_CHEMISE = 40e6  # fonte
SIGMA_GOUJON = 200e6  # visserie classe 8.8
PRESSION_CONTACT_AXE = 30e6  # bague bronze, mouvement oscillant
MODULE_ACIER = 210e9

RHO_ALU, RHO_ACIER, RHO_FONTE = 2700.0, 7850.0, 7200.0
FILETAGES = [(4, 8.78), (5, 14.2), (6, 20.1), (8, 36.6), (10, 58.0)]  # (M, section résistante mm2)


def predimensionner(conception: dict, regime_max: float, temperature_air_k: float) -> dict:
    deux_temps = conception["type"].startswith("2T")
    b = conception["alesage_mm"] / 1000.0
    s = conception["course_mm"] / 1000.0
    pmax = conception["plein_gaz"]["pression_max_bar"] * 1e5
    rapport_bielle = 2.0 if deux_temps else 1.9
    section = math.pi / 4.0 * b**2
    effort_gaz = pmax * section
    rayon = s / 2.0
    omega = 1.10 * regime_max * 2.0 * math.pi / 60.0  # survitesse de 10 %

    # --- Piston
    calotte = max(b * math.sqrt(3.0 * pmax / (16.0 * SIGMA_PISTON)), 0.06 * b)
    hauteur_piston = (1.0 if deux_temps else 0.9) * b
    jupe = max(0.04 * b, 0.0015)
    masse_piston = RHO_ALU * 1.3 * (section * calotte + math.pi * b * jupe * (hauteur_piston - calotte))

    # --- Axe de piston
    d_axe = 0.25 * b
    portee_pied = 0.32 * b
    while effort_gaz / (d_axe * portee_pied) > PRESSION_CONTACT_AXE:
        d_axe += 0.0005
    d_axe_int = 0.6 * d_axe
    longueur_axe = 0.82 * b
    moment_axe = effort_gaz * (0.6 * b) / 8.0
    sigma_axe = moment_axe / (math.pi * (d_axe**4 - d_axe_int**4) / (32.0 * d_axe))
    masse_axe = RHO_ACIER * math.pi / 4.0 * (d_axe**2 - d_axe_int**2) * longueur_axe

    # --- Segments
    nb_segments = 2 if deux_temps else 3
    segment_radial = b / 23.0
    segment_hauteur = max(0.0012, 0.03 * b)
    masse_segments = nb_segments * RHO_FONTE * math.pi * b * segment_radial * segment_hauteur

    # --- Bielle : traction par inertie, compression par les gaz, flambement
    longueur_bielle = rapport_bielle * s
    masse_bielle = 0.0
    aire_bielle = effort_gaz / SIGMA_BIELLE
    for _ in range(30):
        masse_alternative = masse_piston + masse_axe + masse_segments + masse_bielle / 3.0
        effort_inertie = masse_alternative * rayon * omega**2 * (1.0 + rayon / longueur_bielle)
        aire_bielle = max(effort_gaz, effort_inertie) / SIGMA_BIELLE
        epaisseur = math.sqrt(aire_bielle / 2.0)  # section rectangulaire h = 2 e
        while True:
            elancement = longueur_bielle / (epaisseur / math.sqrt(12.0))
            critique = math.pi**2 * MODULE_ACIER * (2.0 * epaisseur**2) / elancement**2
            if critique >= 5.0 * effort_gaz:
                break
            epaisseur += 0.00025
        aire_bielle = 2.0 * epaisseur**2
        nouvelle = RHO_ACIER * 1.9 * aire_bielle * longueur_bielle  # corps + pied + tête
        if abs(nouvelle - masse_bielle) < 1e-5:
            break
        masse_bielle = nouvelle
    masse_rotative = 2.0 * masse_bielle / 3.0

    # --- Vilebrequin : maneton en flexion entre deux paliers
    portee_paliers = 1.1 * b
    moment_maneton = effort_gaz * portee_paliers / 4.0
    d_maneton = (32.0 * moment_maneton / (math.pi * SIGMA_VILEBREQUIN)) ** (1.0 / 3.0)
    d_tourillon = 1.05 * d_maneton
    bras_epaisseur = 0.22 * b
    contrepoids = (masse_rotative + 0.5 * masse_alternative) * rayon  # kg.m
    omega_max = regime_max * 2.0 * math.pi / 60.0
    effort_residuel = 0.5 * masse_alternative * rayon * omega_max**2

    # --- Cylindre, culasse, refroidissement
    chemise = max(pmax * b / (2.0 * SIGMA_CHEMISE) + 0.0015, 0.0025)
    section_goujon = 1.5 * effort_gaz / 4.0 / SIGMA_GOUJON * 1e6  # mm2
    filetage = next((m for m, a in FILETAGES if a >= section_goujon), 10)
    chaleur = conception["plein_gaz"]["chaleur_parois_w"]
    # Ailettes dans le souffle de l'hélice : échange de 90 W/m2/K, rendement
    # d'ailette de 0,8, pied d'ailette à 200 °C. Valeurs à recaler au banc.
    ecart = max(473.0 - temperature_air_k, 60.0)
    surface_ailettes = chaleur / (90.0 * 0.8 * ecart)
    d_int = b + 2.0 * chemise + 0.004
    d_ext = d_int + 2.0 * 0.35 * b
    surface_par_ailette = 2.0 * math.pi / 4.0 * (d_ext**2 - d_int**2)
    nb_ailettes = math.ceil(surface_ailettes / surface_par_ailette)
    volume_chambre = conception["cylindree_cm3"] / (conception["taux_compression"] - 1.0)

    mm = lambda x: x * 1000.0  # noqa: E731
    cotes = {
        "alesage": mm(b), "course": mm(s), "calotte": mm(calotte), "hauteur_piston": mm(hauteur_piston),
        "jupe": mm(jupe), "d_axe": mm(d_axe), "d_axe_int": mm(d_axe_int), "longueur_axe": mm(longueur_axe),
        "longueur_bielle": mm(longueur_bielle), "bielle_epaisseur": mm(epaisseur), "bielle_largeur": mm(2 * epaisseur),
        "portee_pied": mm(portee_pied), "d_maneton": mm(d_maneton), "d_tourillon": mm(d_tourillon),
        "portee_paliers": mm(portee_paliers), "bras_epaisseur": mm(bras_epaisseur), "chemise": mm(chemise),
        "ailette_d_int": mm(d_int), "ailette_d_ext": mm(d_ext), "nb_ailettes": nb_ailettes,
        "segment_hauteur": mm(segment_hauteur), "segment_radial": mm(segment_radial), "nb_segments": nb_segments,
    }
    grandeurs = {
        "effort_gaz_n": effort_gaz, "effort_inertie_n": effort_inertie, "masse_alternative_g": masse_alternative * 1000,
        "masse_piston_g": masse_piston * 1000, "masse_axe_g": masse_axe * 1000, "masse_bielle_g": masse_bielle * 1000,
        "sigma_axe_mpa": sigma_axe / 1e6, "contrepoids_g_mm": contrepoids * 1e6,
        "effort_residuel_n": effort_residuel, "surface_ailettes_cm2": surface_ailettes * 1e4,
        "volume_chambre_cm3": volume_chambre, "filetage_goujon": filetage,
        "jeu_piston_mm": (1.2e-3 * mm(b), 1.8e-3 * mm(b)), "jeu_coupe_mm": 0.004 * mm(b),
    }

    if deux_temps:
        angle = math.radians(100.0)
        descente = rayon * (1 - math.cos(angle)) + longueur_bielle - math.sqrt(longueur_bielle**2 - (rayon * math.sin(angle)) ** 2)
        grandeurs["lumiere_echappement_mm"] = mm(s - descente)
        grandeurs["lumiere_largeur_max_mm"] = 0.6 * mm(b)
    else:
        d_soupape = 0.42 * b
        vitesse_piston = 2.0 * s * regime_max / 60.0
        vitesse_son = math.sqrt(1.4 * 287.0 * temperature_air_k)
        grandeurs["soupape_admission_mm"] = mm(d_soupape)
        grandeurs["soupape_echappement_mm"] = mm(0.36 * b)
        grandeurs["levee_soupape_mm"] = mm(0.25 * d_soupape)
        grandeurs["indice_mach_admission"] = (b / d_soupape) ** 2 * vitesse_piston / (0.35 * vitesse_son)

    return {"cotes": cotes, "grandeurs": grandeurs, "deux_temps": deux_temps}
