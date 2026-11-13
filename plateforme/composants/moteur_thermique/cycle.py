"""Simulation du cycle d'un moteur monocylindre (modèle « zéro dimension »).

Le gaz du cylindre est traité comme une seule zone homogène. On suit sa
température degré par degré de vilebrequin, de la fermeture à l'ouverture
du cylindre, avec :
- la combustion décrite par une loi de Wiebe ;
- les pertes de chaleur aux parois (corrélation de Hohenberg) ;
- les frottements (loi de type Chen-Flynn) ;
- le remplissage décrit par un rendement volumétrique (4 temps) ou par un
  modèle de balayage à mélange parfait (2 temps).

Ce modèle prédit des tendances et des ordres de grandeur. Il n'est pas
recalé : ses coefficients devront être ajustés sur les mesures du banc.

Variantes :
- "4T"    : 4 temps, mélange préparé à l'admission ;
- "2T"    : 2 temps à balayage par le carter, mélange préparé (une partie du
            carburant s'échappe pendant le balayage) ;
- "2T-ID" : 2 temps à injection directe (le carburant est injecté après la
            fermeture de l'échappement, donc rien ne s'échappe).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

R_GAZ = 287.0  # J/(kg.K)
PCI_ESSENCE = 43.5e6  # J/kg
RICHESSE_STOECHIO = 14.7  # kg d'air par kg d'essence


@dataclass
class Moteur:
    type: str  # "4T", "2T" ou "2T-ID"
    alesage: float  # m
    course: float  # m
    taux_compression: float  # géométrique
    rapport_bielle: float = 1.9  # longueur de bielle / course

    # Remplissage
    rendement_volumetrique: float = 0.82  # 4 temps, pleine charge
    taux_balayage_max: float = 0.80  # 2 temps, pleine charge
    angle_fermeture_admission: float = -135.0  # 4T, degrés (0 = point mort haut)
    angle_ouverture_echappement: float = 125.0  # 4T
    angle_lumiere_echappement: float = 100.0  # 2T : ouverture, et fermeture symétrique

    # Combustion
    rendement_combustion: float = 0.95
    duree_combustion: float = 45.0  # degrés, sans gaz résiduels
    temperature_paroi: float = 460.0  # K, moteur refroidi par air
    # Petits moteurs : les pertes aux parois dépassent ce que donne la
    # corrélation, établie sur de gros moteurs. Coefficient à recaler au banc.
    facteur_pertes_paroi: float = 1.8
    # Dégradation de la combustion quand les gaz brûlés résiduels sont nombreux
    # (faible charge, surtout en 2 temps).
    sensibilite_residuels: float = 0.6

    @property
    def deux_temps(self) -> bool:
        return self.type.startswith("2T")

    @property
    def cylindree(self) -> float:
        return math.pi / 4.0 * self.alesage**2 * self.course

    @property
    def volume_mort(self) -> float:
        return self.cylindree / (self.taux_compression - 1.0)

    def volume(self, angle_deg: float) -> float:
        a = self.course / 2.0
        bielle = self.rapport_bielle * self.course
        t = math.radians(angle_deg)
        deplacement = bielle + a - a * math.cos(t) - math.sqrt(bielle**2 - (a * math.sin(t)) ** 2)
        return self.volume_mort + math.pi / 4.0 * self.alesage**2 * deplacement


def _wiebe(angle: float, debut: float, duree: float) -> float:
    if angle <= debut:
        return 0.0
    x = (angle - debut) / duree
    return 1.0 - math.exp(-5.0 * x**3)


def simuler(
    moteur: Moteur,
    regime_tr_min: float,
    charge: float,
    pression_air: float,
    temperature_air: float,
    richesse_lambda: float = 1.0,
    pas_deg: float = 0.5,
) -> dict:
    """Simule un point de fonctionnement. `charge` va de 0 (ralenti) à 1 (plein gaz)."""
    charge = min(max(charge, 0.05), 1.0)
    vd = moteur.cylindree
    vitesse_piston = 2.0 * moteur.course * regime_tr_min / 60.0
    pression_echappement = 1.05 * pression_air
    air_par_carburant = richesse_lambda * RICHESSE_STOECHIO

    if moteur.deux_temps:
        angle_debut = -moteur.angle_lumiere_echappement
        angle_fin = moteur.angle_lumiere_echappement
        v_debut = moteur.volume(angle_debut)
        masse_reference = pression_air / (R_GAZ * temperature_air) * vd
        taux_balayage = moteur.taux_balayage_max * charge
        temperature_frais = temperature_air + 50.0  # réchauffage dans le carter
        temperature_residuels = 900.0
        # Balayage à mélange parfait : part de la charge fraîche qui reste.
        masse_fraiche = (1.0 - math.exp(-taux_balayage)) * masse_reference
        masse_fraiche = min(masse_fraiche, pression_echappement * v_debut / (R_GAZ * temperature_frais))
        masse_residuels = max(
            0.0,
            (pression_echappement * v_debut / R_GAZ - masse_fraiche * temperature_frais) / temperature_residuels,
        )
        masse = masse_fraiche + masse_residuels
        temperature = pression_echappement * v_debut / (masse * R_GAZ)
        fraction_residuels = masse_residuels / masse
        masse_delivree = taux_balayage * masse_reference
        if moteur.type == "2T-ID":
            carburant_brule = masse_fraiche / air_par_carburant
            carburant_fourni = carburant_brule
        else:
            carburant_brule = masse_fraiche / (1.0 + air_par_carburant)
            carburant_fourni = masse_delivree / (1.0 + air_par_carburant)
        rendement_retenue = masse_fraiche / masse_delivree
        pression_admission = pression_air
    else:
        angle_debut = moteur.angle_fermeture_admission
        angle_fin = moteur.angle_ouverture_echappement
        v_debut = moteur.volume(angle_debut)
        pression_admission = pression_air * (0.25 + 0.72 * charge)
        temperature_admission = temperature_air + 25.0
        masse_fraiche = (
            moteur.rendement_volumetrique * pression_admission / (R_GAZ * temperature_admission) * vd
        )
        fraction_residuels = min(0.30, 0.07 * pression_echappement / pression_admission)
        masse = masse_fraiche / (1.0 - fraction_residuels)
        temperature = (1.0 - fraction_residuels) * temperature_admission + fraction_residuels * 900.0
        carburant_brule = masse_fraiche / (1.0 + air_par_carburant)
        carburant_fourni = carburant_brule
        rendement_retenue = 1.0

    qualite = 1.0 - moteur.sensibilite_residuels * max(0.0, fraction_residuels - 0.10)
    chaleur = carburant_brule * PCI_ESSENCE * moteur.rendement_combustion * qualite * min(1.0, richesse_lambda)
    duree = min(90.0, moteur.duree_combustion + 60.0 * fraction_residuels)
    # Calage : moitié de la combustion atteinte 8° après le point mort haut.
    debut_combustion = 8.0 - 0.5175 * duree

    dt = pas_deg / (6.0 * regime_tr_min)  # secondes par pas
    surface_fixe = math.pi / 2.0 * moteur.alesage**2
    section = math.pi / 4.0 * moteur.alesage**2

    def chaleur_paroi(volume: float, pression: float, temp: float) -> float:
        h = 130.0 * volume**-0.06 * (pression / 1e5) ** 0.8 * temp**-0.4 * (vitesse_piston + 1.4) ** 0.8
        surface = surface_fixe + math.pi * moteur.alesage * (volume / section)
        return moteur.facteur_pertes_paroi * h * surface * (temp - moteur.temperature_paroi) * dt

    def cv(temp: float) -> float:
        gamma = max(1.20, 1.38 - 8.0e-5 * (temp - 300.0))
        return R_GAZ / (gamma - 1.0)

    travail = 0.0
    pertes_paroi = 0.0
    pression_max = 0.0
    angle = angle_debut
    volume = v_debut
    while angle < angle_fin - 1e-9:
        volume_suivant = moteur.volume(angle + pas_deg)
        d_volume = volume_suivant - volume
        pression = masse * R_GAZ * temperature / volume
        d_combustion = chaleur * (_wiebe(angle + pas_deg, debut_combustion, duree) - _wiebe(angle, debut_combustion, duree))
        d_paroi = chaleur_paroi(volume, pression, temperature)
        # Prédicteur
        t_pred = temperature + (d_combustion - d_paroi - pression * d_volume) / (masse * cv(temperature))
        p_pred = masse * R_GAZ * t_pred / volume_suivant
        # Correcteur (moyenne des deux bouts du pas)
        p_moy = 0.5 * (pression + p_pred)
        d_paroi = 0.5 * (d_paroi + chaleur_paroi(volume_suivant, p_pred, t_pred))
        cv_moy = cv(0.5 * (temperature + t_pred))
        temperature += (d_combustion - d_paroi - p_moy * d_volume) / (masse * cv_moy)
        travail += p_moy * d_volume
        pertes_paroi += d_paroi
        pression_max = max(pression_max, pression, p_pred)
        angle += pas_deg
        volume = volume_suivant
    pression_fin = masse * R_GAZ * temperature / volume

    if moteur.deux_temps:
        pmi = travail / vd
        pmf = 0.15e5 + 0.004 * pression_max + 0.09e5 * vitesse_piston + 0.35e5 * taux_balayage
        cycles_par_tour = 1.0
    else:
        v_bas = moteur.volume(180.0)
        travail += pression_admission * (v_debut - v_bas)  # début de compression
        travail += 0.5 * (pression_fin + pression_echappement) * (v_bas - volume)  # détente finale
        pmi = travail / vd - (pression_echappement - pression_admission)  # pompage
        pmf = 0.25e5 + 0.005 * pression_max + 0.12e5 * vitesse_piston
        cycles_par_tour = 0.5

    pme = pmi - pmf
    cycles_par_s = regime_tr_min / 60.0 * cycles_par_tour
    puissance = max(pme, 0.0) * vd * cycles_par_s
    debit_carburant = carburant_fourni * cycles_par_s  # kg/s
    conso = debit_carburant / puissance * 3.6e6 if puissance > 0 else float("inf")  # kg/kWh
    return {
        "puissance_w": puissance,
        "pme_bar": pme / 1e5,
        "pmi_bar": pmi / 1e5,
        "pmf_bar": pmf / 1e5,
        "pression_max_bar": pression_max / 1e5,
        "temperature_echappement_k": temperature,
        "conso_specifique": conso,
        "rendement_global": puissance / (debit_carburant * PCI_ESSENCE) if debit_carburant > 0 else 0.0,
        "debit_carburant_g_h": debit_carburant * 3.6e6,
        "chaleur_parois_w": pertes_paroi * cycles_par_s,
        "fraction_residuels": fraction_residuels,
        "rendement_retenue": rendement_retenue,
        "vitesse_piston_m_s": vitesse_piston,
        "effort_gaz_max_n": pression_max * section,
        "charge": charge,
        "regime_tr_min": regime_tr_min,
    }
