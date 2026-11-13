"""YAME — véhicule terrestre léger, électrique ou thermique.

Dimensionnement en ligne droite : résistance au roulement, traînée de l'air,
pente. Sert à fixer masse, puissance, couple aux roues et énergie embarquée.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..composants import moteur_electrique as yared_electrique
from ..composants import moteur_thermique as yared_moteur
from ..socle.atmosphere import G, Air, air
from ..socle.erreurs import BesoinInfaisable, ErreurEtude
from ..socle.format import nb
from ..socle.modele import Article, Chiffre, Etape, Etude, Question, Section, Tableau, nettoyer
from ..socle.modules import Module, enregistrer
from ..socle.reponses import Reponses

ROULEMENT = {"route": 0.015, "piste": 0.035, "sable": 0.12}
TERRAINS = {"route": "Route goudronnée", "piste": "Piste en terre", "sable": "Sable ou terrain meuble"}
PUISSANCE_MAX_MONOCYLINDRE = 9000.0  # W : au-delà, hors du domaine du module moteur


@dataclass
class Parametres:
    m_charge_utile: float
    autonomie_km: float
    v_max: float  # m/s
    pente: float  # 0,20 = 20 %
    roulement: float
    air: Air
    electrique: bool = True
    v_pente: float = 15.0 / 3.6  # vitesse tenue dans la pente maximale
    part_vitesse_croisiere: float = 0.70
    marge_puissance: float = 1.15
    rendement_electrique: float = 0.81  # moteur, contrôleur, transmission
    rendement_transmission: float = 0.85  # thermique : boîte ou variateur
    energie_batterie: float = 140.0  # Wh/kg, pack assemblé
    profondeur_decharge: float = 0.85
    kg_par_kw_electrique: float = 1.0  # moteur + contrôleur
    kg_par_kw_thermique: float = 2.2  # moteur + transmission
    conso_specifique: float = 0.36  # kg/kWh
    k_chassis: float = 0.32  # châssis, roues, suspension, carrosserie
    m_chassis_fixe: float = 15.0
    m_equipements: float = 8.0  # câblage, commandes, éclairage
    rayon_roue: float = 0.25
    pen_structure: float = 1.0
    pen_moteur: float = 1.0


def _effort(p: Parametres, masse: float, vitesse: float, pente: float) -> float:
    angle = math.atan(pente)
    scx = min(0.35 + 0.0015 * masse, 1.6)
    return masse * G * (p.roulement * math.cos(angle) + math.sin(angle)) + 0.5 * p.air.densite * scx * vitesse**2


def dimensionner(p: Parametres) -> dict:
    rendement = p.rendement_electrique if p.electrique else p.rendement_transmission
    masse = 2.5 * p.m_charge_utile + 60.0
    for _ in range(500):
        v_croisiere = p.part_vitesse_croisiere * p.v_max
        effort_pente = _effort(p, masse, p.v_pente, p.pente)
        p_vmax = _effort(p, masse, p.v_max, 0.0) * p.v_max / rendement
        p_pente = effort_pente * p.v_pente / rendement
        p_max = p.marge_puissance * max(p_vmax, p_pente)
        p_croisiere = _effort(p, masse, v_croisiere, 0.0) * v_croisiere / rendement
        energie_km = p_croisiere / v_croisiere / 3.6  # Wh/km à l'entrée de la chaîne
        if p.electrique:
            energie = energie_km * p.autonomie_km / p.profondeur_decharge
            m_energie = energie / p.energie_batterie
            m_motorisation = p.pen_moteur * p.kg_par_kw_electrique * p_max / 1000.0
            carburant = 0.0
        else:
            energie = energie_km * p.autonomie_km
            carburant = p.conso_specifique * energie / 1000.0 * 1.10
            m_energie = carburant * 1.10
            m_motorisation = p.pen_moteur * p.kg_par_kw_thermique * p_max / 1000.0
        m_chassis = p.pen_structure * (p.k_chassis * masse + p.m_chassis_fixe)
        masses = {
            "Charge utile": p.m_charge_utile, "Châssis, roues, suspension": m_chassis,
            "Batterie" if p.electrique else "Carburant et réservoir": m_energie,
            "Motorisation": m_motorisation, "Équipements": p.m_equipements,
        }
        nouvelle = sum(masses.values())
        if nouvelle > 5000.0 or not math.isfinite(nouvelle):
            raise BesoinInfaisable(
                "Aucun véhicule léger ne répond à ce besoin. Pistes : réduire l'autonomie, la charge ou la pente."
            )
        if abs(nouvelle - masse) < 1e-5:
            masse = nouvelle
            break
        masse = 0.5 * (masse + nouvelle)
    else:
        raise BesoinInfaisable("Le calcul ne converge pas : réduire l'autonomie ou la charge utile.")
    return {
        "electrique": p.electrique, "masse_totale": masse, "masses": masses, "p_max": p_max, "p_croisiere": p_croisiere,
        "v_croisiere": v_croisiere, "energie_km": energie_km, "energie_wh": energie, "carburant_kg": carburant,
        "effort_pente_n": effort_pente, "couple_roues_nm": effort_pente * p.rayon_roue,
        "duree_h": p.autonomie_km / (v_croisiere * 3.6),
    }


LIMITES = [
    "Calcul en ligne droite : pas de tenue de route, de freinage, de franchissement ni de direction.",
    "Châssis : masse estimée par une loi empirique, sans calcul de résistance.",
    "Motorisation : masses forfaitaires par kW ; les composants conçus par YARED sont affichés à côté.",
    "Le moteur électrique de YARED est pensé pour être refroidi par un flux d'air : à vérifier pour un véhicule lent.",
]


class VehiculeTerrestre(Module):
    identifiant = "vehicule-terrestre"
    nom = "Véhicule terrestre léger"
    genre = "famille"
    description = "Petit véhicule de transport, piloté ou télécommandé, électrique ou thermique."
    accepte_expert = True
    questions = [
        Question("charge_utile_kg", "Quelle charge doit-il transporter (personnes et matériel) ?", unite="kg", obligatoire=True),
        Question("autonomie_km", "Quelle distance doit-il parcourir sans ravitailler ?", unite="km", obligatoire=True),
        Question("terrain", "Sur quel terrain roule-t-il surtout ?", "choix", choix=[[k, v] for k, v in TERRAINS.items()]),
        Question("motorisation", "Quelle motorisation ?", "choix",
                 choix=[["auto", "Laisser la plateforme comparer"], ["electrique", "Électrique"], ["thermique", "Thermique"]]),
        Question("vitesse_max_kmh", "Vitesse maximale", unite="km/h", avance=True),
        Question("pente_max_pct", "Pente la plus raide à gravir", unite="%", avance=True),
        Question("altitude_m", "Altitude", unite="m", avance=True),
        Question("temperature_c", "Température maximale", unite="°C", avance=True),
        Question("fabrication_locale", "Les composants seront-ils fabriqués en atelier local ?", "oui_non", avance=True),
    ]
    exemple = {"nom": "Porteur tout-terrain", "charge_utile_kg": 150, "autonomie_km": 80, "terrain": "piste"}

    def etudier(self, brutes: dict) -> Etude:
        r = Reponses(self.questions, brutes)
        charge = r.obligatoire("charge_utile_kg")
        autonomie = r.obligatoire("autonomie_km")
        terrain = r.combler("terrain", "piste", "Piste en terre : le cas le plus courant hors des villes.")
        motorisation = r.combler("motorisation", "auto", "La plateforme compare les deux et retient le véhicule le plus léger.")
        v_max = r.combler("vitesse_max_kmh", 40.0, "Vitesse raisonnable sur piste pour un véhicule léger.")
        pente = r.combler("pente_max_pct", 20.0, "Pente raide mais courante hors route.")
        altitude = r.combler("altitude_m", 400.0, "Valeur prudente pour le Togo.")
        temperature = r.combler("temperature_c", 40.0, "Journée chaude.")
        locale = r.combler("fabrication_locale", True, "Les masses du châssis et de la motorisation sont majorées pour des procédés d'atelier.")
        a = air(altitude, temperature, altitude)
        base = Parametres(charge, autonomie, v_max / 3.6, pente / 100.0, ROULEMENT[terrain], a,
                          pen_structure=1.15 if locale else 1.0, pen_moteur=1.25 if locale else 1.0)
        r.appliquer_expert(base)
        import dataclasses
        variantes = []
        for electrique in ([True, False] if motorisation == "auto" else [motorisation == "electrique"]):
            try:
                variantes.append(dimensionner(dataclasses.replace(base, electrique=electrique)))
            except BesoinInfaisable:
                if motorisation != "auto":
                    raise
        if not variantes:
            raise BesoinInfaisable("Aucun véhicule léger ne répond à ce besoin. Pistes : réduire l'autonomie, la charge ou la pente.")
        d = min(variantes, key=lambda v: v["masse_totale"])
        p = dataclasses.replace(base, electrique=d["electrique"])
        masse, titre = d["masse_totale"], r.titre or "Véhicule terrestre léger"

        sections = [Section("Système retenu", [
            ("Véhicule électrique à batterie." if p.electrique else "Véhicule à moteur thermique.")
            + " Les efforts sont calculés en ligne droite, sur le terrain indiqué.",
        ], [
            Tableau(["Grandeur", "Valeur"], [
                ["Masse en charge", f"{nb(masse, 0)} kg"],
                ["Puissance maximale du moteur", f"{nb(d['p_max'] / 1000, 1)} kW"],
                ["Puissance en croisière", f"{nb(d['p_croisiere'] / 1000, 1)} kW à {nb(d['v_croisiere'] * 3.6, 0)} km/h"],
                ["Effort de traction dans la pente maximale", f"{nb(d['effort_pente_n'], 0)} N"],
                ["Couple aux roues dans la pente", f"{nb(d['couple_roues_nm'], 0)} N·m"],
                ["Énergie consommée", f"{nb(d['energie_km'], 0)} Wh/km"],
                ["Batterie", f"{nb(d['energie_wh'] / 1000, 1)} kWh"] if p.electrique
                else ["Carburant", f"{nb(d['carburant_kg'], 1)} kg ({nb(d['carburant_kg'] / 0.74, 1)} L)"],
            ], "Performances"),
            Tableau(["Poste", "Masse", "Part"], [
                [nom, f"{nb(m, 1)} kg", f"{nb(100 * m / masse, 0)} %"] for nom, m in sorted(d["masses"].items(), key=lambda x: -x[1])
            ] + [["Total en charge", f"{nb(masse, 1)} kg", "100 %"]], "Bilan de masse"),
        ])]
        if len(variantes) > 1:
            sections.append(Section("Comparaison des motorisations", ["La plateforme retient le véhicule le plus léger."], [
                Tableau(["Motorisation", "Masse en charge", "Puissance maximale", "Énergie embarquée"], [
                    ["Électrique" if v["electrique"] else "Thermique", f"{nb(v['masse_totale'], 0)} kg", f"{nb(v['p_max'] / 1000, 1)} kW",
                     f"{nb(v['energie_wh'] / 1000, 1)} kWh de batterie" if v["electrique"] else f"{nb(v['carburant_kg'], 1)} kg de carburant"]
                    for v in variantes
                ]),
            ]))

        composants, alertes, annexes = [], [], {}
        try:
            if p.electrique:
                regime = 3000.0
                couple = d["p_croisiere"] * p.rendement_electrique / (regime * 2 * math.pi / 60)
                marge = max(1.2, d["p_max"] / d["p_croisiere"])
                annexes["moteur_electrique"] = yared_electrique.concevoir(couple, regime, marge * couple, regime, 48.0,
                                                                          majoration_masse=p.pen_moteur)
                sections.append(yared_electrique.section_moteur_electrique(annexes["moteur_electrique"], "Moteur électrique de traction"))
                composants.append({"module": "moteur-electrique", "libelle": "Moteur électrique de traction", "reponses": {
                    "nom": f"{titre} — moteur de traction", "couple_nm": round(couple, 2), "regime_tr_min": regime, "tension_v": 48.0,
                    "marge_pointe": round(marge, 2), "fabrication_locale": locale}})
            elif d["p_max"] <= PUISSANCE_MAX_MONOCYLINDRE:
                cdc = {"type": "4T", "puissance_max_w": d["p_max"], "puissance_croisiere_w": d["p_croisiere"],
                       "regime_max_tr_min": 4500.0, "regime_croisiere_tr_min": 3200.0, "pression_air_pa": a.pression,
                       "temperature_air_k": a.temperature, "duree_vol_h": d["duree_h"], "majoration_masse": p.pen_moteur}
                annexes["moteur_thermique"] = yared_moteur.etudier_moteur(cdc, ["4T"])
                sections += [yared_moteur.section_demande(cdc), yared_moteur.section_moteur(annexes["moteur_thermique"]["retenu"])]
                composants.append({"module": "moteur-thermique", "libelle": "Moteur thermique", "reponses": {
                    "nom": f"{titre} — moteur", "puissance_max_w": round(d["p_max"]), "puissance_croisiere_w": round(d["p_croisiere"]),
                    "duree_h": round(d["duree_h"], 1), "type": "4T", "regime_max_tr_min": 4500, "regime_croisiere_tr_min": 3200,
                    "altitude_m": altitude, "temperature_c": temperature, "fabrication_locale": locale}})
            else:
                alertes.append("La puissance demandée dépasse le domaine du module moteur monocylindre de YARED : moteur à définir à part.")
        except ErreurEtude as erreur:
            alertes.append(f"Composants : {erreur}")
        sections[0].alertes += alertes

        charge_essai = 2.0 * charge
        etapes = [
            Etape("Revue du dossier", "Valider les hypothèses avant d'engager des dépenses.",
                  ["Relire le tableau des hypothèses : confirmer ou corriger chaque valeur marquée « comblé ».",
                   "Confirmer la motorisation.", "Si une valeur change, relancer l'étude."],
                  ["Ce rapport"], "Toutes les hypothèses sont confirmées par écrit.", ["Hypothèses modifiées", "Motorisation retenue"]),
            Etape("Motorisation : conception détaillée et validation au banc", "Disposer d'un moteur mesuré avant de construire autour.",
                  ["Ouvrir l'étude YARED du moteur depuis ce dossier et suivre son plan de prototypage.",
                   "Mesurer puissance et couple au banc."],
                  ["Étude YARED jointe", "Banc d'essai"],
                  f"Puissance d'au moins {nb(d['p_max'] / 1000, 1)} kW. Masse de la motorisation ≤ {nb(1.10 * d['masses']['Motorisation'], 1)} kg.",
                  ["Puissance maximale (kW)", "Masse de la motorisation (kg)"]),
            Etape("Dessin du châssis et de la transmission", "Transformer les chiffres en plans.",
                  [f"Dessiner le châssis pour {nb(masse, 0)} kg en charge, avec la suspension et la direction.",
                   f"Choisir le rapport de transmission pour {nb(d['couple_roues_nm'], 0)} N·m aux roues dans la pente et {nb(p.v_max * 3.6, 0)} km/h en pointe.",
                   "Dimensionner les freins pour arrêter le véhicule chargé dans la pente maximale.",
                   "Faire vérifier la résistance du châssis et le freinage par une personne compétente : la plateforme ne le fait pas encore."],
                  ["FreeCAD (gratuit)"], "Plans complets, avec le calcul du châssis et des freins signé.",
                  ["Rapport de transmission retenu", "Nom du vérificateur"]),
            Etape("Fabrication du châssis et essai de charge", "Prouver que le châssis tient.",
                  ["Souder et assembler le châssis ; monter roues et suspension.",
                   f"Charger le plateau à {nb(charge_essai, 0)} kg (deux fois la charge utile), 10 minutes.", "Décharger, contrôler les soudures."],
                  ["Poste à souder", "Charges pesées", "Balance"],
                  f"Aucune déformation permanente ni fissure sous {nb(charge_essai, 0)} kg. Châssis ≤ {nb(1.10 * d['masses']['Châssis, roues, suspension'], 0)} kg.",
                  ["Masse du châssis (kg)", "Observations après essai"], "Personne sous le véhicule pendant le chargement."),
            Etape("Intégration et essais à l'arrêt", "Vérifier commandes et sécurités roues levées.",
                  ["Monter motorisation, transmission, freins, " + ("batterie" if p.electrique else "réservoir") + " et commandes.",
                   "Roues levées : vérifier accélérateur, freins, arrêt d'urgence.", "Peser le véhicule."],
                  ["Chandelles", "Balance"],
                  f"Masse à vide ≤ {nb(1.05 * (masse - charge), 0)} kg. L'arrêt d'urgence coupe la traction.",
                  ["Masse à vide (kg)"]),
            Etape("Essais sur terrain fermé", "Mesurer les performances réelles.",
                  ["À vide puis en charge : freinage depuis 20 km/h, puis vitesse maximale.",
                   f"Gravir une pente de {nb(p.pente * 100, 0)} % en charge.",
                   "Parcourir 10 km à vitesse de croisière et mesurer l'énergie consommée."],
                  ["Terrain privé, sans public", "Compteur d'énergie ou pesée du carburant"],
                  f"Vitesse maximale ≥ {nb(p.v_max * 3.6, 0)} km/h. Pente de {nb(p.pente * 100, 0)} % gravie en charge. "
                  f"Consommation ≤ {nb(1.2 * d['energie_km'], 0)} Wh/km" + ("" if p.electrique else f" (soit {nb(1.2 * d['carburant_kg'] / p.autonomie_km * 1000 / 1.1, 0)} g/km)") + ".",
                  ["Vitesse maximale (km/h)", "Pente gravie (%)", "Consommation (Wh/km ou g/km)", "Distance de freinage depuis 20 km/h (m)"],
                  "Casque et ceinture pour le conducteur. Vitesse augmentée par paliers."),
            Etape("Autonomie", "Atteindre la distance demandée.",
                  [f"Parcourir {nb(autonomie / 4, 0)} km, puis {nb(autonomie / 2, 0)} km, puis {nb(autonomie, 0)} km en charge.",
                   "Inspecter châssis, transmission et freins après chaque parcours."],
                  ["Terrain d'essai"], f"{nb(autonomie, 0)} km parcourus en charge sans ravitailler.",
                  ["Distance atteinte (km)", "Énergie ou carburant restant"]),
            Etape("Recalage et décision", "Rendre le modèle fidèle au véhicule réel.",
                  ["Reporter masses et consommation mesurées dans une nouvelle étude.", "Décider : geler, ou lancer un deuxième prototype."],
                  ["La plateforme"], "Écart inférieur à 10 % sur la masse et la consommation.", ["Écart sur la consommation (%)", "Décision"]),
        ]
        fab, basique, yared = "À fabriquer", "Élément de base à approvisionner", "À concevoir avec YARED"
        nomenclature = [
            Article("Châssis soudé", 1, fab, f"Acier, pour {nb(masse, 0)} kg en charge"),
            Article("Suspension et direction", 1, fab, ""),
            Article("Transmission", 1, fab, f"{nb(d['couple_roues_nm'], 0)} N·m aux roues"),
            Article("Moteur", 1, yared, f"{nb(d['p_max'] / 1000, 1)} kW"),
            Article("Freins", 1, basique, "Jeu complet"),
            Article("Roues et pneus", 4, basique, f"Rayon {nb(p.rayon_roue * 100, 0)} cm"),
            Article("Roulements, visserie, câbles", 1, basique, "Lot"),
        ]
        if p.electrique:
            nomenclature += [
                Article("Pack batterie", 1, fab, f"{nb(d['energie_wh'] / 1000, 1)} kWh, assemblé à partir de cellules"),
                Article("Cellules lithium", 1, basique, f"Lot pour {nb(d['energie_wh'] / 1000, 1)} kWh"),
                Article("Contrôleur du moteur", 1, yared, "Module non encore disponible"),
            ]
        else:
            nomenclature.append(Article("Réservoir", 1, fab, f"{nb(d['carburant_kg'] / 0.74 * 1.05, 1)} L"))
        return Etude(
            module=self.identifiant, genre=self.genre, titre=titre,
            chiffres=[
                Chiffre(f"{nb(masse, 0)} kg", "masse en charge"),
                Chiffre(f"{nb(d['p_max'] / 1000, 1)} kW", "puissance maximale"),
                Chiffre(f"{nb(d['energie_wh'] / 1000, 1)} kWh", "batterie") if p.electrique else Chiffre(f"{nb(d['carburant_kg'] / 0.74, 1)} L", "carburant"),
                Chiffre("électrique" if p.electrique else "thermique", "motorisation retenue"),
            ],
            hypotheses=r.registre.en_dicts(), sections=sections, etapes=etapes, nomenclature=nomenclature, limites=LIMITES,
            donnees=nettoyer({"variantes": variantes, "retenu": d, "annexes": annexes, "composants": composants}),
        )


enregistrer(VehiculeTerrestre())
