"""YAME — drone multirotor électrique (vol stationnaire)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..composants import helice as yared_helice
from ..composants import moteur_electrique as yared_electrique
from ..socle.atmosphere import G, Air, air
from ..socle.erreurs import BesoinInfaisable, ErreurEtude
from ..socle.format import nb
from ..socle.modele import Article, Chiffre, Etape, Etude, Question, Section, Tableau, nettoyer
from ..socle.modules import Module, enregistrer
from ..socle.reponses import Reponses


@dataclass
class Parametres:
    m_charge_utile: float
    p_charge_utile: float
    endurance_min: float
    air: Air
    rotors: int = 4
    charge_disque: float = 60.0  # N/m2 : faible, pour l'endurance
    figure_de_merite: float = 0.68
    rendement_chaine_electrique: float = 0.85
    marge_vol: float = 1.10  # manœuvres et vent
    marge_poussee: float = 2.0  # poussée maxi / poids
    energie_batterie: float = 200.0  # Wh/kg, pack lithium-ion
    puissance_batterie: float = 600.0  # W/kg
    profondeur_decharge: float = 0.85
    puissance_moteur_electrique: float = 5000.0  # W/kg en pointe
    p_avionique: float = 15.0
    m_avionique: float = 0.45
    k_chassis: float = 0.20
    m_chassis_fixe: float = 0.30
    pen_structure: float = 1.0
    pen_moteurs_electriques: float = 1.0
    masse_moteur_electrique: float | None = None  # kg par moteur ; None = estimation par la puissance


REALISATION = 0.93  # part du rendement calculé qu'une pièce d'atelier atteint réellement
RENDEMENT_CONTROLEUR = 0.95


def dimensionner(p: Parametres) -> dict:
    masse = 3.0 * p.m_charge_utile + 1.0
    for _ in range(500):
        poids = masse * G
        surface = poids / p.charge_disque
        diametre = math.sqrt(4.0 * surface / (p.rotors * math.pi))
        p_ideale = poids**1.5 / math.sqrt(2.0 * p.air.densite * surface)
        p_vol = p_ideale / p.figure_de_merite / p.rendement_chaine_electrique * p.marge_vol + p.p_avionique + p.p_charge_utile
        energie = p_vol * p.endurance_min / 60.0 / p.profondeur_decharge
        m_batterie = max(energie / p.energie_batterie, 1.5 * p_vol / p.puissance_batterie)
        p_moteur_maxi = p_ideale / p.figure_de_merite / p.rotors * p.marge_poussee**1.5
        if p.masse_moteur_electrique is not None:
            m_moteurs = p.rotors * p.masse_moteur_electrique
        else:
            m_moteurs = p.pen_moteurs_electriques * p.rotors * p_moteur_maxi / p.puissance_moteur_electrique
        m_controleurs = p.rotors * (0.02 + p_moteur_maxi / 25000.0)
        m_helices = p.rotors * 0.25 * diametre**2
        m_chassis = p.pen_structure * (p.k_chassis * masse + p.m_chassis_fixe)
        masses = {
            "Charge utile": p.m_charge_utile, "Batterie": m_batterie, "Châssis et train": m_chassis,
            "Moteurs électriques": m_moteurs, "Contrôleurs": m_controleurs, "Hélices": m_helices, "Avionique": p.m_avionique,
        }
        nouvelle = sum(masses.values())
        if nouvelle > 150.0 or not math.isfinite(nouvelle):
            raise BesoinInfaisable(
                "Aucun multirotor électrique ne tient cette endurance avec cette charge. "
                "Pistes : réduire l'endurance ou la charge, ou passer à un drone à voilure fixe."
            )
        if abs(nouvelle - masse) < 1e-6:
            masse = nouvelle
            break
        masse = 0.6 * masse + 0.4 * nouvelle
    else:
        raise BesoinInfaisable("Le calcul ne converge pas : réduire l'endurance ou la charge utile.")
    return {
        "masse_totale": masse, "masses": masses, "diametre_helice": diametre, "p_vol": p_vol,
        "energie_batterie_wh": energie, "p_moteur_maxi": p_moteur_maxi, "poussee_stationnaire_n": masse * G / p.rotors,
        "encombrement": 1.1 * diametre / math.sin(math.pi / p.rotors) + diametre,
        "regime_decharge": p_vol / (m_batterie * p.energie_batterie),
    }


LIMITES = [
    "Vol stationnaire seulement : le vol d'avancement, souvent un peu plus économe, n'est pas calculé.",
    "Châssis : masse estimée par une loi empirique, sans calcul de résistance ni de vibrations.",
    "Les rendements d'hélice et de moteur viennent des modèles simplifiés de YARED, minorés d'un coefficient forfaitaire.",
    "Non traité : commandes de vol, contrôleurs, pannes d'un moteur.",
]


class DroneMultirotor(Module):
    identifiant = "drone-multirotor"
    nom = "Drone multirotor"
    genre = "famille"
    description = "Multirotor électrique pour le vol stationnaire : observation à courte portée, inspection, relais radio."
    accepte_expert = True
    questions = [
        Question("charge_utile_kg", "Quelle masse doit-il emporter ?", unite="kg", obligatoire=True),
        Question("endurance_min", "Combien de minutes doit-il tenir en l'air ?", unite="min", obligatoire=True),
        Question("rotors", "Nombre de rotors", "choix", choix=[["4", "4 rotors"], ["6", "6 rotors"], ["8", "8 rotors"]]),
        Question("charge_utile_w", "Consommation électrique de la charge utile", unite="W", avance=True),
        Question("altitude_m", "Altitude du terrain", unite="m", avance=True),
        Question("temperature_c", "Température maximale", unite="°C", avance=True),
        Question("fabrication_locale", "Les composants seront-ils fabriqués en atelier local ?", "oui_non", avance=True),
    ]
    exemple = {"nom": "Multirotor d'observation", "charge_utile_kg": 1.0, "endurance_min": 30}

    def etudier(self, brutes: dict) -> Etude:
        r = Reponses(self.questions, brutes)
        charge = r.obligatoire("charge_utile_kg")
        endurance = r.obligatoire("endurance_min")
        rotors = int(r.combler("rotors", "4", "Quatre rotors : le moins de pièces à fabriquer."))
        puissance_cu = r.combler("charge_utile_w", round(20.0 * charge), "Environ 20 W par kg de charge utile.")
        altitude = r.combler("altitude_m", 400.0, "Valeur prudente pour le Togo.")
        temperature = r.combler("temperature_c", 40.0, "Journée chaude : air moins dense, donc plus de puissance pour porter.")
        locale = r.combler("fabrication_locale", True, "Les masses du châssis et des moteurs sont majorées pour des procédés d'atelier.")
        p = Parametres(charge, puissance_cu, endurance, air(altitude, temperature, altitude), rotors,
                       pen_structure=1.15 if locale else 1.0, pen_moteurs_electriques=1.25 if locale else 1.0)
        r.appliquer_expert(p)
        # Couplage YAME <-> YARED : les performances de l'hélice et du moteur conçus
        # remplacent les valeurs types, jusqu'à stabilité.
        figes = frozenset(r.expert)
        depart = {"figure_de_merite": p.figure_de_merite, "rendement_chaine_electrique": p.rendement_chaine_electrique}
        annexes, alertes, tours = {}, [], 0
        for tours in range(1, 13):
            d = dimensionner(p)
            try:
                sustentation = yared_helice.concevoir_sustentation(d["masse_totale"] * G / p.rotors, d["diametre_helice"],
                                                                   p.air.densite, marge_poussee=p.marge_poussee)
                point, maxi = sustentation["point"], sustentation["maxi"]
                tension = 44.4 if d["p_vol"] > 1500 else 22.2
                moteur = yared_electrique.concevoir(point["couple_nm"], point["regime_tr_min"], maxi["couple_nm"],
                                                    maxi["regime_tr_min"], tension, majoration_masse=p.pen_moteurs_electriques)
            except ErreurEtude as erreur:
                alertes.append(f"Composants : {erreur}")
                break
            annexes = {"helice": sustentation, "moteur": moteur}
            actuels = {"figure_de_merite": p.figure_de_merite, "rendement_chaine_electrique": p.rendement_chaine_electrique,
                       "masse_moteur_electrique": d["masses"]["Moteurs électriques"] / p.rotors}
            cibles = {"figure_de_merite": REALISATION * point["figure_de_merite"],
                      "rendement_chaine_electrique": RENDEMENT_CONTROLEUR * moteur["rendement"],
                      "masse_moteur_electrique": moteur["masse_kg"]}
            cibles = {k: v for k, v in cibles.items() if k not in figes}
            if not cibles or max(abs(v - actuels[k]) / abs(actuels[k]) for k, v in cibles.items()) < 0.01:
                break
            for cle, valeur in cibles.items():
                setattr(p, cle, valeur)
        masse, total = d["masse_totale"], d["masse_totale"]
        titre = r.titre or "Drone multirotor"

        sections = [Section("Système retenu", [f"Multirotor électrique à {p.rotors} rotors."], [
            Tableau(["Grandeur", "Valeur"], [
                ["Hélices", f"{p.rotors} hélices de {nb(d['diametre_helice'] * 100, 0)} cm"],
                ["Encombrement hors tout", f"{nb(d['encombrement'], 2)} m"],
                ["Puissance électrique en vol", f"{nb(d['p_vol'], 0)} W"],
                ["Batterie", f"{nb(d['energie_batterie_wh'], 0)} Wh, {nb(d['masses']['Batterie'], 2)} kg"],
                ["Poussée par rotor en vol stationnaire", f"{nb(d['poussee_stationnaire_n'] / G, 2)} kg"],
                ["Poussée maximale par rotor", f"{nb(p.marge_poussee * d['poussee_stationnaire_n'] / G, 2)} kg"],
            ], "Géométrie et performances"),
            Tableau(["Poste", "Masse", "Part"], [
                [nom, f"{nb(m, 2)} kg", f"{nb(100 * m / total, 0)} %"] for nom, m in sorted(d["masses"].items(), key=lambda x: -x[1])
            ] + [["Total au décollage", f"{nb(total, 2)} kg", "100 %"]], "Bilan de masse"),
        ], alertes)]
        if "helice" in annexes:
            sections.append(yared_helice.section_helice(annexes["helice"], "Hélice"))
            sections.append(yared_electrique.section_moteur_electrique(annexes["moteur"], "Moteur électrique"))
            m = annexes["moteur"]
            sections.append(Section("Valeurs calculées par YARED et réinjectées dans le dimensionnement", [
                f"YAME part de valeurs types. YARED conçoit l'hélice et le moteur, et leurs résultats remplacent ces valeurs ; "
                f"le calcul est repris jusqu'à stabilité ({tours} tours ici).",
                f"La figure de mérite calculée est multipliée par {nb(REALISATION, 2)} pour les imperfections de fabrication, "
                f"et le rendement du moteur par {nb(RENDEMENT_CONTROLEUR, 2)} pour son contrôleur.",
            ], [Tableau(["Grandeur", "Valeur de départ", "Valeur retenue"], [
                ["Figure de mérite des hélices", nb(depart["figure_de_merite"], 2), nb(p.figure_de_merite, 2)],
                ["Rendement de la chaîne électrique", f"{nb(depart['rendement_chaine_electrique'] * 100, 0)} %", f"{nb(p.rendement_chaine_electrique * 100, 0)} %"],
                ["Masse d'un moteur", "estimée par la puissance", f"{nb(d['masses']['Moteurs électriques'] / p.rotors, 2)} kg"],
            ])]))

        etapes = [
            Etape("Revue du dossier", "Valider les hypothèses avant d'engager des dépenses.",
                  ["Relire le tableau des hypothèses : confirmer ou corriger chaque valeur marquée « comblé ».",
                   "Si une valeur change, relancer l'étude."],
                  ["Ce rapport"], "Toutes les hypothèses sont confirmées par écrit.", ["Hypothèses modifiées"]),
            Etape("Composants : conception détaillée et validation au banc", "Disposer d'un groupe moteur-hélice mesuré.",
                  ["Ouvrir les études YARED de l'hélice et du moteur électrique depuis ce dossier.",
                   "Suivre leur plan de prototypage jusqu'à la dernière étape.",
                   "Mesurer la poussée et la puissance d'un groupe complet sur le banc."],
                  ["Études YARED jointes", "Banc de poussée"],
                  f"Un groupe fournit {nb(p.marge_poussee * d['poussee_stationnaire_n'] / G, 2)} kg de poussée maximale, et "
                  f"{nb(d['poussee_stationnaire_n'] / G, 2)} kg avec moins de {nb(1.15 * d['p_vol'] / p.rotors, 0)} W électriques.",
                  ["Poussée maximale (kg)", "Puissance électrique en stationnaire, par groupe (W)", "Masse d'un moteur (kg)"],
                  "Hélice derrière un écran pendant les essais."),
            Etape("Batterie", "Assembler un pack sûr.",
                  [f"Assembler le pack : {nb(d['energie_batterie_wh'], 0)} Wh, avec carte de protection et d'équilibrage.",
                   f"Faire un cycle complet au courant de vol ({nb(d['p_vol'], 0)} W) sur charge résistive."],
                  ["Cellules lithium", "Soudeuse par points", "Carte de protection", "Charge résistive"],
                  f"Énergie restituée ≥ {nb(0.85 * d['energie_batterie_wh'], 0)} Wh. Température du pack < 55 °C. Masse ≤ {nb(1.10 * d['masses']['Batterie'], 2)} kg.",
                  ["Énergie restituée (Wh)", "Température maximale (°C)", "Masse du pack (kg)"],
                  "Assemblage et essais sur une surface incombustible, avec un seau de sable à portée de main."),
            Etape("Châssis et pesée", "Tenir le bilan de masse.",
                  [f"Fabriquer le châssis : {p.rotors} bras, encombrement {nb(d['encombrement'], 2)} m.",
                   "Vérifier la rigidité : aucun bras ne doit vriller à la main.", "Peser."],
                  ["Tubes ou plaques composites", "Balance"],
                  f"Châssis ≤ {nb(1.10 * d['masses']['Châssis et train'], 2)} kg.", ["Masse du châssis (kg)"]),
            Etape("Intégration et essais au sol", "Vérifier le fonctionnement avant de quitter le sol.",
                  ["Monter moteurs, contrôleurs, autopilote et batterie ; peser l'ensemble.",
                   "Hélices démontées : vérifier le sens de rotation de chaque moteur et les sécurités (perte radio, batterie faible)."],
                  ["Station sol", "Balance"],
                  f"Masse au décollage ≤ {nb(1.05 * masse, 2)} kg. Sens de rotation et sécurités conformes.",
                  ["Masse au décollage (kg)"], "Hélices démontées pour tout essai à l'intérieur."),
            Etape("Autorisations et zone d'essai", "Voler dans un cadre légal et sûr.",
                  ["Obtenir l'autorisation de vol auprès de l'autorité compétente.", "Choisir une zone dégagée, sans public."],
                  ["Dossier de conception"], "Autorisation écrite obtenue, zone reconnue.", ["Référence de l'autorisation"]),
            Etape("Vol captif puis vol libre", "Valider le pilotage.",
                  ["Vol retenu par des longes de 1 m : 30 secondes.", "Vol libre à 3 m : 2 minutes de stationnaire.",
                   "Relever la puissance et les températures."],
                  ["Longes", "Station sol"],
                  f"Stationnaire stable. Puissance à moins de 20 % de {nb(d['p_vol'], 0)} W. Moteurs sous 80 °C.",
                  ["Puissance en stationnaire (W)", "Température des moteurs (°C)"], "Personne à moins de 15 m."),
            Etape("Montée en endurance", "Atteindre la durée demandée par paliers.",
                  [f"Vols de 5 minutes, puis de la moitié de l'endurance, puis de {nb(p.endurance_min, 0)} minutes.",
                   "Atterrir avec au moins 15 % de batterie."],
                  ["Station sol"], f"Vol de {nb(p.endurance_min, 0)} minutes réalisé avec 15 % de batterie restante.",
                  ["Durée du plus long vol (min)", "Batterie restante (%)"]),
            Etape("Recalage et décision", "Rendre le modèle fidèle au drone réel.",
                  ["Reporter masses et puissance mesurées dans une nouvelle étude.", "Décider : geler, ou lancer un deuxième prototype."],
                  ["La plateforme"], "Écart inférieur à 10 % sur la masse et la puissance.", ["Écart sur la puissance (%)", "Décision"]),
        ]
        fab, base, yared = "À fabriquer", "Élément de base à approvisionner", "À concevoir avec YARED"
        nomenclature = [
            Article("Châssis", 1, fab, f"{p.rotors} bras, cible {nb(d['masses']['Châssis et train'], 2)} kg"),
            Article("Moteur électrique", p.rotors, yared, f"{nb(p.marge_poussee * d['poussee_stationnaire_n'] / G, 2)} kg de poussée maximale"),
            Article("Hélice", p.rotors, yared, f"{nb(d['diametre_helice'] * 100, 0)} cm"),
            Article("Contrôleur de moteur", p.rotors, yared, "Module non encore disponible"),
            Article("Pack batterie", 1, fab, f"{nb(d['energie_batterie_wh'], 0)} Wh, assemblé à partir de cellules"),
            Article("Cellules lithium-ion", 1, base, f"Lot pour {nb(d['energie_batterie_wh'], 0)} Wh"),
            Article("Autopilote, GPS, radio", 1, yared, "Module non encore disponible"),
            Article("Charge utile", 1, "Fournie par l'utilisateur", f"{nb(charge, 1)} kg"),
        ]
        composants = []
        if "helice" in annexes:
            m = annexes["moteur"]
            composants = [
                {"module": "helice", "libelle": "Hélice", "reponses": {
                    "nom": f"{titre} — hélice", "usage": "sustentation", "poussee_kg": round(masse / p.rotors, 3),
                    "diametre_m": round(d["diametre_helice"], 3), "altitude_m": altitude, "temperature_c": temperature}},
                {"module": "moteur-electrique", "libelle": "Moteur électrique", "reponses": {
                    "nom": f"{titre} — moteur", "couple_nm": round(m["couple_nm"], 3), "regime_tr_min": round(m["regime_tr_min"]),
                    "tension_v": m["tension_v"], "marge_pointe": round(m["couple_pointe_nm"] / m["couple_nm"], 2), "fabrication_locale": locale}},
            ]
        return Etude(
            module=self.identifiant, genre=self.genre, titre=titre,
            chiffres=[
                Chiffre(f"{nb(masse, 2)} kg", "masse au décollage"),
                Chiffre(f"{p.rotors} × {nb(d['diametre_helice'] * 100, 0)} cm", "hélices"),
                Chiffre(f"{nb(d['energie_batterie_wh'], 0)} Wh", "batterie"),
                Chiffre(f"{nb(d['p_vol'], 0)} W", "puissance en vol"),
            ],
            hypotheses=r.registre.en_dicts(), sections=sections, etapes=etapes, nomenclature=nomenclature, limites=LIMITES,
            donnees=nettoyer({"dimensionnement": d, "annexes": annexes, "composants": composants}),
        )


enregistrer(DroneMultirotor())
