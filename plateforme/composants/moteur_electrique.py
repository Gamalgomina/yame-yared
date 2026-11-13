"""YARED — moteur électrique sans balais à rotor extérieur.

Dimensionnement analytique : le couple fixe le volume d'entrefer par une
pression tangentielle admissible ; on en tire le stator, le bobinage, les
pertes et la masse. Ce n'est pas un calcul de champ magnétique : l'étape
suivante est une vérification par éléments finis (FEMM, Pyleecan).
"""

from __future__ import annotations

import math

from ..socle.erreurs import BesoinIncomplet
from ..socle.format import nb
from ..socle.modele import Article, Chiffre, Etape, Etude, Question, Section, Tableau, nettoyer
from ..socle.modules import Module, enregistrer
from ..socle.reponses import Reponses

PRESSION_CONTINUE = 12e3  # Pa, moteur refroidi par le souffle de l'hélice
PRESSION_POINTE = 30e3  # Pa, quelques dizaines de secondes
INDUCTION_ENTREFER = 0.85  # T, aimants néodyme en surface
COEFFICIENT_BOBINAGE = 0.93
RESISTIVITE_CUIVRE_CHAUD = 2.2e-8  # ohm.m à 100 °C
REMPLISSAGE_ENCOCHE = 0.40
DENSITE_COURANT_MAX = 15.0  # A/mm2 en continu, moteur dans le souffle de son hélice


def concevoir(couple: float, regime: float, couple_pointe: float, regime_pointe: float, tension: float,
              toles_fines: bool = False, majoration_masse: float = 1.0) -> dict:
    """Moteur fournissant `couple` (N.m) en continu à `regime` (tr/min).

    Le stator est agrandi par pas de 10 % tant que la densité de courant dans
    le cuivre dépasse la limite admise pour un refroidissement par air.
    """
    volume = max(couple / (2.0 * PRESSION_CONTINUE), couple_pointe / (2.0 * PRESSION_POINTE))
    for _ in range(40):
        m = _concevoir(volume, couple, regime, couple_pointe, regime_pointe, tension, toles_fines, majoration_masse)
        if m["densite_courant_a_mm2"] <= DENSITE_COURANT_MAX:
            break
        volume *= 1.10
    return m


def _concevoir(volume: float, couple: float, regime: float, couple_pointe: float, regime_pointe: float, tension: float,
               toles_fines: bool, majoration_masse: float) -> dict:
    diametre = (4.0 * volume / (math.pi * 0.25)) ** (1.0 / 3.0)  # longueur = 0,25 x diamètre
    longueur = 0.25 * diametre
    pression = couple / (2.0 * volume)

    encoches, poles = (12, 14) if diametre < 0.045 else (24, 28) if diametre < 0.10 else (36, 42)
    constante_vitesse = 1.2 * regime_pointe / (0.95 * tension)  # tr/min par volt
    constante_couple = 60.0 / (2.0 * math.pi * constante_vitesse)  # N.m/A
    courant_vide = 0.03 * couple / constante_couple + 0.3
    courant = couple / constante_couple + courant_vide
    courant_pointe = couple_pointe / constante_couple + courant_vide

    # Bobinage
    flux_pole = INDUCTION_ENTREFER * 2.0 / math.pi * (math.pi * diametre / poles) * longueur
    spires_phase = constante_couple / (math.sqrt(3.0) * COEFFICIENT_BOBINAGE * (poles / 2.0) * flux_pole)
    bobines_phase = encoches // 3
    spires_dent = max(1, round(spires_phase / bobines_phase))
    profondeur = 0.18 * diametre
    cuivre = math.pi * (diametre - profondeur) * profondeur * 0.5 * REMPLISSAGE_ENCOCHE  # m2
    section_fil = cuivre / (6.0 * spires_dent * bobines_phase)  # m2 par conducteur
    demi_spire = longueur + 0.9 * math.pi * diametre / encoches
    resistance_phase = RESISTIVITE_CUIVRE_CHAUD * spires_dent * bobines_phase * 2.0 * demi_spire / section_fil
    # Pertes : cuivre (deux phases conduisent), fer, frottements
    pertes_cuivre = 2.0 * resistance_phase * courant**2
    pertes_cuivre_pointe = 2.0 * resistance_phase * courant_pointe**2
    masse_fer = 7650.0 * 0.55 * math.pi / 4.0 * (diametre**2 - (diametre - 2.6 * profondeur) ** 2) * longueur
    frequence = regime * poles / 120.0
    pertes_fer = (12.0 if toles_fines else 25.0) * (frequence / 400.0) ** 1.5 * 1.3**2 * masse_fer
    puissance = couple * regime * 2.0 * math.pi / 60.0
    pertes_meca = 0.01 * puissance
    pertes = pertes_cuivre + pertes_fer + pertes_meca
    densite_courant = courant / section_fil / 1e6  # A/mm2

    diametre_ext = 1.12 * diametre
    masse = majoration_masse * 1.45 * 4500.0 * math.pi / 4.0 * diametre_ext**2 * longueur
    alertes = []
    if densite_courant > DENSITE_COURANT_MAX:
        alertes.append("Densité de courant élevée dans le cuivre : échauffement à surveiller, prévoir un stator plus grand.")
    if frequence > 1500.0:
        alertes.append("Fréquence électrique élevée : pertes dans les tôles importantes, tôles fines conseillées.")
    return {
        "diametre_stator_mm": diametre * 1000, "longueur_stator_mm": longueur * 1000,
        "diametre_exterieur_mm": diametre_ext * 1000, "encoches": encoches, "poles": poles,
        "constante_vitesse": constante_vitesse, "constante_couple": constante_couple,
        "spires_par_dent": spires_dent, "section_fil_mm2": section_fil * 1e6, "resistance_phase_mohm": resistance_phase * 1e3,
        "courant_a": courant, "courant_pointe_a": courant_pointe, "courant_vide_a": courant_vide,
        "densite_courant_a_mm2": densite_courant, "pression_tangentielle_kpa": pression / 1e3,
        "puissance_w": puissance, "pertes_cuivre_w": pertes_cuivre, "pertes_fer_w": pertes_fer,
        "pertes_cuivre_pointe_w": pertes_cuivre_pointe,
        "rendement": puissance / (puissance + pertes), "puissance_electrique_w": puissance + pertes,
        "masse_kg": masse, "frequence_hz": frequence, "tension_v": tension,
        "couple_nm": couple, "regime_tr_min": regime, "couple_pointe_nm": couple_pointe, "regime_pointe_tr_min": regime_pointe,
        "alertes": alertes,
    }


def section_moteur_electrique(m: dict, titre: str = "Moteur électrique : première conception") -> Section:
    return Section(titre, ["Dimensionnement analytique d'un moteur sans balais à rotor extérieur, aimants néodyme."], [
        Tableau(["Caractéristique", "Valeur"], [
            ["Stator : diamètre × longueur", f"{nb(m['diametre_stator_mm'], 0)} × {nb(m['longueur_stator_mm'], 0)} mm"],
            ["Diamètre extérieur du rotor", f"{nb(m['diametre_exterieur_mm'], 0)} mm"],
            ["Encoches / pôles", f"{m['encoches']} encoches, {m['poles']} aimants"],
            ["Bobinage", f"{m['spires_par_dent']} spires par dent, {nb(m['section_fil_mm2'], 2)} mm² de cuivre par spire"],
            ["Constante de vitesse", f"{nb(m['constante_vitesse'], 0)} tr/min par volt"],
            ["Résistance d'une phase, à chaud", f"{nb(m['resistance_phase_mohm'], 0)} mΩ"],
            ["Masse estimée", f"{nb(m['masse_kg'], 2)} kg"],
        ]),
        Tableau(["Point de fonctionnement", "Continu", "Pointe"], [
            ["Couple", f"{nb(m['couple_nm'], 2)} N·m", f"{nb(m['couple_pointe_nm'], 2)} N·m"],
            ["Régime", f"{nb(m['regime_tr_min'], 0)} tr/min", f"{nb(m['regime_pointe_tr_min'], 0)} tr/min"],
            ["Courant", f"{nb(m['courant_a'], 0)} A", f"{nb(m['courant_pointe_a'], 0)} A"],
            ["Pertes dans le cuivre", f"{nb(m['pertes_cuivre_w'], 0)} W", f"{nb(m['pertes_cuivre_pointe_w'], 0)} W"],
            ["Pertes dans les tôles", f"{nb(m['pertes_fer_w'], 0)} W", "—"],
            ["Rendement", f"{nb(m['rendement'] * 100, 0)} %", "—"],
        ]),
    ], list(m["alertes"]))


def etapes_moteur_electrique(m: dict) -> list:
    return [
        Etape("Vérification magnétique", "Confirmer le couple par un calcul de champ avant d'acheter aimants et tôles.",
              [f"Dessiner la coupe du moteur : stator de {nb(m['diametre_stator_mm'], 0)} mm, {m['encoches']} encoches, {m['poles']} aimants.",
               "Calculer le couple dans FEMM (gratuit) au courant continu prévu.",
               "Ajuster l'épaisseur des aimants et la largeur des dents si le couple manque."],
              ["FEMM ou Pyleecan"],
              f"Couple calculé d'au moins {nb(m['couple_nm'], 2)} N·m à {nb(m['courant_a'], 0)} A.",
              ["Couple calculé par éléments finis (N·m)", "Épaisseur d'aimant retenue (mm)"]),
        Etape("Stator", "Empiler des tôles isolées, sans court-circuit entre elles.",
              ["Faire découper les tôles magnétiques au laser ou par électro-érosion.",
               f"Empiler sur {nb(m['longueur_stator_mm'], 0)} mm, coller ou riveter, puis isoler les encoches.",
               "Ébavurer : aucune arête ne doit blesser l'émail du fil."],
              ["Tôles magnétiques de 0,2 à 0,35 mm", "Isolant d'encoche"],
              f"Hauteur du paquet {nb(m['longueur_stator_mm'], 0)} mm ± 0,3 mm. Aucun contact électrique entre le paquet et un fil d'essai glissé dans les encoches.",
              ["Hauteur du paquet (mm)", "Masse du stator nu (g)"]),
        Etape("Bobinage", "Obtenir trois phases identiques.",
              [f"Bobiner {m['spires_par_dent']} spires par dent, en fils parallèles totalisant {nb(m['section_fil_mm2'], 2)} mm².",
               "Suivre le schéma de bobinage du couple encoches/pôles retenu, puis coupler en étoile.",
               "Imprégner au vernis et cuire."],
              ["Fil de cuivre émaillé classe 200 °C", "Vernis d'imprégnation", "Ohmmètre de précision", "Mégohmmètre"],
              f"Résistance de chaque phase égale à ± 3 %, proche de {nb(m['resistance_phase_mohm'] / 1.3, 0)} mΩ à froid. Isolement à la masse > 10 MΩ.",
              ["Résistance des trois phases (mΩ)", "Isolement (MΩ)"]),
        Etape("Rotor", "Tenir les aimants à pleine vitesse.",
              [f"Usiner la cloche en acier doux, diamètre extérieur {nb(m['diametre_exterieur_mm'], 0)} mm.",
               f"Coller les {m['poles']} aimants en alternant les polarités, avec un gabarit d'espacement.",
               "Équilibrer la cloche."],
              ["Tour", "Colle époxy structurale", "Gabarit"],
              "Polarités alternées vérifiées à la boussole. Faux-rond de la cloche ≤ 0,05 mm.",
              ["Faux-rond (mm)", "Masse du rotor (g)"],
              "Les aimants néodyme pincent fort et se brisent en éclats : gants et lunettes."),
        Etape("Essai à vide", "Vérifier la constante de vitesse et les pertes à vide.",
              ["Monter les roulements, assembler, faire tourner à vide avec un contrôleur.",
               f"Mesurer le régime et le courant à vide sous {nb(m['tension_v'], 0)} V."],
              ["Contrôleur de moteur", "Alimentation", "Compte-tours", "Ampèremètre"],
              f"Constante de vitesse à ± 8 % de {nb(m['constante_vitesse'], 0)} tr/min par volt. Courant à vide ≤ {nb(2 * m['courant_vide_a'], 1)} A.",
              ["Régime à vide (tr/min)", "Tension (V)", "Courant à vide (A)"]),
        Etape("Essai en charge et échauffement", "Vérifier le couple et la tenue thermique.",
              [f"Charger le moteur (hélice ou frein) jusqu'à {nb(m['couple_nm'], 2)} N·m à {nb(m['regime_tr_min'], 0)} tr/min.",
               "Maintenir 10 minutes en relevant la température du bobinage chaque minute.",
               f"Faire une pointe de 30 secondes à {nb(m['couple_pointe_nm'], 2)} N·m."],
              ["Banc avec mesure de couple ou de poussée", "Sonde de température collée sur le bobinage"],
              f"Température du bobinage stabilisée sous 120 °C. Courant ≤ {nb(1.15 * m['courant_a'], 0)} A au point continu.",
              ["Courant au point continu (A)", "Température stabilisée (°C)", "Température après la pointe (°C)"]),
        Etape("Recalage", "Corriger le modèle avec les mesures.",
              ["Reporter constante de vitesse, courant et températures dans une nouvelle étude.",
               "Décider : geler, ou refaire un bobinage corrigé."],
              ["La plateforme"], "Écart inférieur à 10 % sur le courant au point continu.", ["Écart sur le courant (%)", "Décision"]),
    ]


LIMITES = [
    "Dimensionnement par pression tangentielle : pas de calcul de champ magnétique ni de saturation.",
    "Thermique : pas de calcul d'échauffement, seulement des densités de courant usuelles.",
    "Pertes dans les tôles estimées par une loi empirique, très sensible à la qualité des tôles.",
]


class ModuleMoteurElectrique(Module):
    identifiant = "moteur-electrique"
    nom = "Moteur électrique"
    genre = "composant"
    description = "Moteur sans balais à rotor extérieur : taille du stator, bobinage, courant, rendement, masse."
    questions = [
        Question("couple_nm", "Quel couple doit-il fournir en continu ?", unite="N·m"),
        Question("puissance_w", "Ou bien : quelle puissance mécanique en continu ?", unite="W"),
        Question("regime_tr_min", "À quel régime ?", unite="tr/min", obligatoire=True),
        Question("tension_v", "Quelle est la tension de la batterie ?", unite="V"),
        Question("marge_pointe", "Rapport entre le couple de pointe et le couple continu", avance=True),
        Question("toles_fines", "Disposez-vous de tôles magnétiques fines (0,2 mm) ?", "oui_non", avance=True),
        Question("fabrication_locale", "Le moteur sera-t-il fabriqué en atelier local ?", "oui_non", avance=True),
    ]
    exemple = {"nom": "Moteur de sustentation", "couple_nm": 1.35, "regime_tr_min": 5000, "tension_v": 44.4}

    def etudier(self, brutes: dict) -> Etude:
        r = Reponses(self.questions, brutes)
        regime = r.obligatoire("regime_tr_min")
        if r.donne("couple_nm"):
            couple = r.obligatoire("couple_nm")
        elif r.donne("puissance_w"):
            couple = r.deduire("couple_calcule", "Couple continu", round(r.obligatoire("puissance_w") / (regime * 2 * math.pi / 60), 3),
                               "N·m", "Puissance divisée par la vitesse de rotation.")
        else:
            raise BesoinIncomplet("Il manque une information : le couple ou la puissance à fournir en continu.")
        tension = r.combler("tension_v", 44.4, "Batterie de 12 éléments lithium en série, courante à cette taille.")
        marge = r.combler("marge_pointe", 1.8, "Réserve de couple pour les manœuvres et les rafales.")
        fines = r.combler("toles_fines", False, "Tôles de 0,35 mm supposées, plus faciles à trouver ; les pertes sont plus fortes.")
        locale = r.combler("fabrication_locale", True, "La masse est majorée de 25 % pour des procédés d'atelier.")
        m = concevoir(couple, regime, marge * couple, regime * math.sqrt(marge), tension, fines, 1.25 if locale else 1.0)
        return Etude(
            module=self.identifiant, genre=self.genre, titre=r.titre or "Moteur électrique",
            chiffres=[
                Chiffre(f"{nb(m['diametre_stator_mm'], 0)} × {nb(m['longueur_stator_mm'], 0)} mm", "stator, diamètre × longueur"),
                Chiffre(f"{nb(m['constante_vitesse'], 0)} tr/min/V", "constante de vitesse"),
                Chiffre(f"{nb(m['rendement'] * 100, 0)} %", "rendement au point continu"),
                Chiffre(f"{nb(m['masse_kg'], 2)} kg", "masse estimée"),
            ],
            hypotheses=r.registre.en_dicts(), sections=[section_moteur_electrique(m)], etapes=etapes_moteur_electrique(m),
            nomenclature=[
                Article("Paquet de tôles du stator", 1, "À fabriquer", f"{nb(m['diametre_stator_mm'], 0)} × {nb(m['longueur_stator_mm'], 0)} mm, {m['encoches']} encoches"),
                Article("Bobinage", 1, "À fabriquer", f"{m['spires_par_dent']} spires par dent, {nb(m['section_fil_mm2'], 2)} mm²"),
                Article("Cloche du rotor", 1, "À fabriquer", f"Acier doux, {nb(m['diametre_exterieur_mm'], 0)} mm"),
                Article("Flasque et arbre", 1, "À fabriquer", "Aluminium et acier"),
                Article("Aimant néodyme", m["poles"], "Élément de base à approvisionner", "Tenue à 120 °C au moins"),
                Article("Tôle magnétique", 1, "Élément de base à approvisionner", "Lot, 0,2 à 0,35 mm"),
                Article("Fil de cuivre émaillé", 1, "Élément de base à approvisionner", "Classe 200 °C"),
                Article("Roulement", 2, "Élément de base à approvisionner", ""),
                Article("Contrôleur du moteur", 1, "À concevoir avec YARED", "Module non encore disponible dans la plateforme"),
            ],
            limites=LIMITES, donnees=nettoyer(m),
        )


enregistrer(ModuleMoteurElectrique())
