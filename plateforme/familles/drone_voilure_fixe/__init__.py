"""YAME — drone à voilure fixe à moteur thermique, avec ou sans décollage vertical."""

from __future__ import annotations

import dataclasses
import math

from ...composants import helice as yared_helice
from ...composants import moteur_electrique as yared_electrique
from ...composants import moteur_thermique as yared_moteur
from ...composants.moteur_thermique.conception import VARIANTES, concevoir, retenir
from ...composants.moteur_thermique.pieces import predimensionner
from ...socle.atmosphere import G, air
from ...socle.erreurs import ErreurEtude
from ...socle.format import nb
from ...socle.modele import Article, Chiffre, Etape, Etude, Question, Section, Tableau, nettoyer
from ...socle.modules import Module, enregistrer
from ...socle.reponses import Reponses
from .dimensionnement import Parametres, cahier_des_charges_moteur, dimensionner

FACTEUR_DE_CHARGE = 3.0  # facteur de charge limite retenu pour l'essai statique

LIMITES = [
    "Aérodynamique : traînée estimée par addition de surfaces équivalentes, sans calcul sur la forme réelle.",
    "Structure : masses estimées par des lois empiriques, sans calcul de résistance. Les plans de la cellule ne sont pas encore produits.",
    "Stabilité et commandes de vol : non traitées. Une vérification indépendante est imposée dans le plan de prototypage.",
    "Les rendements d'hélice et de moteur électrique viennent des modèles simplifiés de YARED, minorés d'un coefficient forfaitaire.",
    "Fabrication locale : majorations de masse forfaitaires, à remplacer par vos pesées.",
    "Non traité : génératrice, contrôleurs, autopilote, liaison radio, pannes.",
]


REALISATION = 0.93  # part du rendement calculé qu'une pièce d'atelier atteint réellement
RENDEMENT_CONTROLEUR = 0.95
LIBELLES_REINJECTES = {
    "rendement_helice": "Rendement de l'hélice de croisière",
    "figure_de_merite": "Figure de mérite des hélices de sustentation",
    "rendement_chaine_electrique": "Rendement de la chaîne électrique de sustentation",
}


def _boucler(p: Parametres, figes: frozenset = frozenset(), iterations: int = 14) -> dict:
    """Couplage YAME <-> YARED pour un type de moteur donné.

    À chaque tour, YAME dimensionne le drone, YARED conçoit le moteur
    thermique, les hélices et le moteur électrique, et leurs performances
    remplacent les hypothèses de départ. On s'arrête quand plus rien ne bouge
    de plus de 1 %. Les réglages imposés par l'utilisateur (`figes`) ne sont
    jamais remplacés.
    """
    q = dataclasses.replace(p)
    for tour in range(1, iterations + 1):
        drone = dimensionner(q)
        cdc = cahier_des_charges_moteur(q, drone)
        moteur = concevoir(cdc)
        annexes = _composants_annexes(q, {"drone": drone, "cahier_des_charges": cdc})
        actuels = {"conso_specifique": q.conso, "masse_moteur": drone["masses"]["Moteur thermique"]}
        cibles = {"conso_specifique": moteur["conso_croisiere"], "masse_moteur": moteur["masse_kg"]}
        if "helice_croisiere" in annexes:
            actuels["rendement_helice"] = q.rendement_helice
            cibles["rendement_helice"] = REALISATION * annexes["helice_croisiere"]["point"]["rendement"]
        if "helice_sustentation" in annexes:
            actuels["figure_de_merite"] = q.figure_de_merite
            cibles["figure_de_merite"] = REALISATION * annexes["helice_sustentation"]["point"]["figure_de_merite"]
        if "moteur_sustentation" in annexes:
            actuels["rendement_chaine_electrique"] = q.rendement_chaine_electrique
            cibles["rendement_chaine_electrique"] = RENDEMENT_CONTROLEUR * annexes["moteur_sustentation"]["rendement"]
            actuels["masse_moteur_electrique"] = drone["vertical"]["m_moteurs"] / 4.0
            cibles["masse_moteur_electrique"] = annexes["moteur_sustentation"]["masse_kg"]
        cibles = {k: v for k, v in cibles.items() if k not in figes}
        if max(abs(v - actuels[k]) / abs(actuels[k]) for k, v in cibles.items()) < 0.01:
            break
        for cle, valeur in cibles.items():
            setattr(q, cle, valeur)
        if "rendement_helice" in cibles:
            q.rendement_helice_montee = 0.88 * q.rendement_helice
    return {"type": q.type_moteur, "drone": drone, "cahier_des_charges": cdc, "moteur": moteur, "tours": tour,
            "annexes": annexes, "parametres": q}


def _composants_annexes(p: Parametres, variante: dict) -> dict:
    """Hélices et moteur électrique conçus par YARED pour le drone retenu."""
    drone, cdc = variante["drone"], variante["cahier_des_charges"]
    annexes = {"alertes": []}
    puissance_helice = drone["p_croisiere_arbre"] - p.p_electrique / p.rendement_generatrice
    try:
        annexes["helice_croisiere"] = yared_helice.concevoir_croisiere(
            puissance_helice, drone["croisiere"]["vitesse"], cdc["regime_croisiere_tr_min"], p.air_vol.densite, 0.70)
    except ErreurEtude as erreur:
        annexes["alertes"].append(f"Hélice de croisière : {erreur}")
    if p.vtol:
        try:
            v = drone["vertical"]
            sustentation = yared_helice.concevoir_sustentation(
                drone["masse_totale"] * G / 4.0, v["diametre_helice"], p.air_sol.densite, marge_poussee=p.marge_poussee)
            annexes["helice_sustentation"] = sustentation
            point, maxi = sustentation["point"], sustentation["maxi"]
            tension = 44.4 if v["p_stationnaire"] > 1500 else 22.2
            annexes["moteur_sustentation"] = yared_electrique.concevoir(
                point["couple_nm"], point["regime_tr_min"], maxi["couple_nm"], maxi["regime_tr_min"], tension,
                majoration_masse=p.pen_moteurs_electriques)
        except ErreurEtude as erreur:
            annexes["alertes"].append(f"Sustentation : {erreur}")
    return annexes


def _section_systeme(p: Parametres, variante: dict) -> Section:
    drone, cdc = variante["drone"], variante["cahier_des_charges"]
    c = drone["croisiere"]
    total = drone["masse_totale"]
    geometrie = Tableau(["Grandeur", "Valeur"], [
        ["Envergure", f"{nb(drone['envergure'], 2)} m"],
        ["Surface de l'aile", f"{nb(drone['surface'], 2)} m²"],
        ["Corde moyenne", f"{nb(drone['corde'] * 100, 0)} cm"],
        ["Allongement", nb(drone["allongement"], 1)],
        ["Vitesse de croisière", f"{nb(c['vitesse'], 1)} m/s ({nb(c['vitesse'] * 3.6, 0)} km/h)"],
        ["Vitesse de décrochage", f"{nb(c['v_decrochage'], 1)} m/s ({nb(c['v_decrochage'] * 3.6, 0)} km/h)"],
        ["Finesse en croisière", nb(c["finesse"], 1)],
        ["Puissance moteur en croisière", f"{nb(drone['p_croisiere_arbre'], 0)} W"],
        ["Puissance moteur en montée", f"{nb(drone['p_montee_arbre'], 0)} W"],
        ["Carburant embarqué", f"{nb(drone['carburant_kg'], 2)} kg ({nb(drone['carburant_l'], 1)} L)"],
        ["Consommation moyenne", f"{nb(drone['conso_moyenne_g_h'], 0)} g/h"],
    ], "Géométrie et performances")
    masses = Tableau(["Poste", "Masse", "Part"], [
        [nom, f"{nb(m, 2)} kg", f"{nb(100 * m / total, 0)} %"] for nom, m in sorted(drone["masses"].items(), key=lambda x: -x[1])
    ] + [["Total au décollage", f"{nb(total, 2)} kg", "100 %"]], "Bilan de masse")
    structure = Tableau(["Élément de structure", "Masse cible"], [
        [nom, f"{nb(m, 2)} kg"] for nom, m in drone["detail_structure"].items() if m > 0
    ], "Détail de la structure")
    tableaux = [geometrie, masses, structure]
    v = drone["vertical"]
    if "diametre_helice" in v:
        tableaux.append(Tableau(["Décollage vertical", "Valeur"], [
            ["Hélices de sustentation", f"4 hélices de {nb(v['diametre_helice'] * 100, 0)} cm"],
            ["Puissance électrique en vol stationnaire", f"{nb(v['p_stationnaire'] / 1000, 1)} kW"],
            ["Poussée maximale par moteur", f"{nb(v['poussee_maxi_par_moteur'] / G, 1)} kg"],
            ["Batterie", f"{nb(v['energie_batterie_wh'], 0)} Wh, {nb(v['m_batterie'], 2)} kg"],
            ["Moteurs électriques (les 4)", f"{nb(v['m_moteurs'], 2)} kg"],
            ["Contrôleurs et hélices", f"{nb(v['m_controleurs'] + v['m_helices'], 2)} kg"],
        ], "Décollage vertical"))
    texte = "Avion à aile fixe" + (", avec quatre rotors électriques pour le décollage et l'atterrissage verticaux" if p.vtol else "")
    return Section("Système retenu", [
        texte + ", propulsé en croisière par un moteur thermique à hélice, qui entraîne aussi une génératrice pour l'électronique de bord."
    ], tableaux)


def _section_variantes(variantes: list, retenue: dict) -> Section:
    lignes = []
    for v in variantes:
        d, m = v["drone"], v["moteur"]
        lignes.append([
            m["libelle"] + (" — retenu" if v is retenue else ""), f"{nb(d['masse_totale'], 1)} kg", f"{nb(d['envergure'], 2)} m",
            f"{nb(d['carburant_kg'], 1)} kg", f"{nb(m['cylindree_cm3'], 0)} cm³", f"{nb(m['masse_kg'], 1)} kg",
            f"{nb(m['conso_croisiere'] * 1000, 0)} g/kWh", m["difficulte"],
        ])
    plus_leger = min(variantes, key=lambda v: v["drone"]["masse_totale"])
    if len(variantes) == 1:
        choix = "Le type de moteur a été imposé."
    elif plus_leger is retenue:
        choix = "Le moteur retenu donne le drone le plus léger."
    else:
        choix = (f"Le drone le plus léger serait obtenu avec le moteur « {plus_leger['moteur']['libelle']} », mais l'écart de masse "
                 "est inférieur à 10 %, donc à l'incertitude du modèle. À masse comparable, la plateforme retient le moteur le plus simple à fabriquer.")
    return Section("Comparaison des moteurs", [
        "Pour chaque type de moteur, YAME a dimensionné le drone et YARED a conçu le moteur correspondant, en boucle, "
        "jusqu'à ce que masse et consommation soient cohérentes.", choix,
    ], [Tableau(["Moteur", "Masse du drone", "Envergure", "Carburant", "Cylindrée", "Masse moteur", "Consommation", "Fabrication"], lignes)])


def _section_alternative(retenue: dict, alternative: dict) -> Section:
    d, da = retenue["drone"], alternative["drone"]
    gain = 100.0 * (1.0 - da["masse_totale"] / d["masse_totale"])
    return Section("Autre architecture : sans décollage vertical", [
        f"Avec le même type de moteur et un lancement par catapulte ou depuis une piste courte, le drone pèserait "
        f"{nb(da['masse_totale'], 1)} kg au lieu de {nb(d['masse_totale'], 1)} kg, soit {nb(gain, 0)} % de moins, avec "
        f"{nb(da['carburant_kg'], 1)} kg de carburant et un moteur de {nb(alternative['moteur']['cylindree_cm3'], 0)} cm³.",
        "Le décollage vertical ajoute des moteurs, une batterie et de la traînée, qu'il faut porter pendant tout le vol. "
        "En échange, il supprime la catapulte, la piste et l'atterrissage sur le ventre ou sous parachute.",
    ])


def _section_reinjection(variante: dict) -> Section | None:
    q, annexes, drone = variante["parametres"], variante["annexes"], variante["drone"]
    defauts = {c.name: c.default for c in dataclasses.fields(Parametres)}
    lignes = []
    for cle, libelle in LIBELLES_REINJECTES.items():
        if getattr(q, cle) != defauts[cle]:
            lignes.append([libelle, f"{nb(defauts[cle] * 100, 0)} %" if cle != "figure_de_merite" else nb(defauts[cle], 2),
                           f"{nb(getattr(q, cle) * 100, 0)} %" if cle != "figure_de_merite" else nb(getattr(q, cle), 2)])
    if q.masse_moteur_electrique is not None:
        lignes.append(["Masse d'un moteur électrique de sustentation", "estimée par la puissance", f"{nb(q.masse_moteur_electrique, 2)} kg"])
    lignes.append(["Masse du moteur thermique", "estimée par la puissance", f"{nb(drone['masses']['Moteur thermique'], 2)} kg"])
    lignes.append(["Consommation du moteur thermique en croisière", "valeur type", f"{nb(q.conso * 1000, 0)} g/kWh"])
    return Section("Valeurs calculées par YARED et réinjectées dans le dimensionnement", [
        f"YAME part de valeurs types. YARED conçoit ensuite chaque composant, et ses résultats remplacent ces valeurs ; "
        f"le calcul est repris jusqu'à stabilité ({variante['tours']} tours ici).",
        f"Les rendements d'hélice calculés sont multipliés par {nb(REALISATION, 2)} pour tenir compte des imperfections de fabrication, "
        f"et le rendement du moteur électrique par {nb(RENDEMENT_CONTROLEUR, 2)} pour son contrôleur. Un réglage expert imposé par vous n'est jamais remplacé.",
    ], [Tableau(["Grandeur", "Valeur de départ", "Valeur retenue"], lignes)], annexes["alertes"])


def _etapes(p: Parametres, variante: dict, annexes: dict) -> list:
    drone, cdc, moteur = variante["drone"], variante["cahier_des_charges"], variante["moteur"]
    masse = drone["masse_totale"]
    c = drone["croisiere"]
    v = drone["vertical"]
    limite, extreme = FACTEUR_DE_CHARGE * masse, 1.5 * FACTEUR_DE_CHARGE * masse
    liste_composants = "moteur thermique, hélice de croisière" + (", hélices de sustentation, moteurs électriques" if p.vtol else "")
    etapes = [
        Etape(
            "Revue du dossier et décisions",
            "Valider les hypothèses avant d'engager des dépenses.",
            ["Relire le tableau des hypothèses : confirmer ou corriger chaque valeur marquée « comblé ».",
             ("Décider entre décollage vertical et catapulte, à partir de la comparaison chiffrée du rapport."
              if p.vtol else "Confirmer le mode de lancement et d'atterrissage (piste, catapulte, parachute)."),
             "Confirmer le type de moteur retenu au vu des machines disponibles.",
             "Si une valeur change, relancer l'étude et repartir de la nouvelle version."],
            ["Ce rapport", "Inventaire de l'atelier"],
            "Toutes les hypothèses sont confirmées par écrit, et l'architecture est figée.",
            ["Hypothèses modifiées", "Architecture retenue"],
        ),
        Etape(
            "Composants : conception détaillée et validation au banc",
            "Disposer de composants mesurés avant de construire la cellule autour d'eux.",
            [f"Ouvrir l'étude YARED de chaque composant ({liste_composants}) depuis ce dossier.",
             "Suivre le plan de prototypage de chaque composant jusqu'à sa dernière étape.",
             "Peser chaque composant terminé."],
            ["Études YARED jointes au dossier", "Banc d'essai moteur", "Banc de poussée"],
            f"Moteur thermique : au moins {nb(cdc['puissance_max_w'], 0)} W et {nb(cdc['duree_vol_h'], 1)} h d'endurance au banc. "
            + (f"Chaque groupe de sustentation : au moins {nb(v['poussee_maxi_par_moteur'] / G, 1)} kg de poussée. " if p.vtol else "")
            + f"Masse du moteur thermique ≤ {nb(1.10 * moteur['masse_kg'], 2)} kg.",
            ["Puissance maximale du moteur (W)", "Consommation en croisière (g/h)", "Masse du moteur (kg)"]
            + (["Poussée maximale d'un groupe de sustentation (kg)", "Masse d'un moteur électrique (kg)"] if p.vtol else []),
            "Voir les consignes de chaque plan de composant.",
        ),
        Etape(
            "Dessin de la cellule",
            "Transformer les dimensions du rapport en plans fabricables.",
            [f"Dessiner l'aile : envergure {nb(drone['envergure'], 2)} m, surface {nb(drone['surface'], 2)} m², corde moyenne {nb(drone['corde'] * 100, 0)} cm, "
             "en deux ou trois tronçons, avec un longeron continu.",
             f"Dessiner l'empennage (surface {nb(p.rapport_empennage * drone['surface'], 2)} m²), le fuselage"
             + (" et les deux bras portant les moteurs de sustentation." if p.vtol else "."),
             "Placer moteur, réservoir, batterie et charge utile ; le réservoir au plus près du centre de gravité pour que le centrage ne bouge pas en vol.",
             "Faire calculer la stabilité, le centrage et la résistance du longeron par une personne compétente : la plateforme ne le fait pas encore."],
            ["FreeCAD ou OpenVSP (gratuits)", "Dimensions et masses cibles du rapport"],
            "Plans complets, avec la plage de centrage et la section du longeron justifiées par un calcul signé.",
            ["Plage de centrage retenue (% de la corde)", "Section du longeron", "Nom du vérificateur"],
        ),
        Etape(
            "Essai statique de l'aile",
            "Prouver que l'aile tient les efforts de vol avant de construire le reste.",
            ["Fabriquer une aile complète d'essai, identique à celle de vol.",
             "La poser à l'envers sur ses attaches de fuselage et la charger de sacs de sable répartis du centre vers les bouts.",
             f"Charger jusqu'à {nb(limite, 0)} kg (facteur de charge {nb(FACTEUR_DE_CHARGE, 1)}), mesurer la flèche, décharger et vérifier le retour.",
             f"Recharger jusqu'à {nb(extreme, 0)} kg et tenir 3 secondes."],
            ["Sacs de sable pesés", "Règle ou fil à plomb pour la flèche", "Tréteaux"],
            f"À {nb(limite, 0)} kg : aucune déformation permanente, flèche en bout inférieure à {nb(0.10 * drone['envergure'] / 2 * 100, 0)} cm. "
            f"À {nb(extreme, 0)} kg : aucune rupture pendant 3 secondes.",
            ["Flèche en bout d'aile à la charge limite (cm)", "Charge maximale tenue (kg)", "Masse de l'aile (kg)"],
            "Personne sous l'aile pendant le chargement.",
        ),
        Etape(
            "Fabrication de la cellule et pesée",
            "Tenir le bilan de masse.",
            ["Fabriquer aile, empennage, fuselage" + (", bras" if p.vtol else "") + " et atterrisseur.",
             "Peser chaque élément et comparer au tableau « Détail de la structure ».",
             "Si un élément dépasse sa masse cible de plus de 10 %, en chercher la cause avant de continuer."],
            ["Moules", "Tissus et résine", "Pompe à vide", "Balance à 10 g"],
            f"Structure complète ≤ {nb(1.10 * drone['masses']['Structure'], 2)} kg (cible {nb(drone['masses']['Structure'], 2)} kg).",
            ["Masse de chaque élément (kg)", "Masse totale de la structure (kg)"],
        ),
        Etape(
            "Intégration et essais au sol",
            "Vérifier que tout fonctionne ensemble, moteurs tournants, avant de quitter le sol.",
            ["Monter propulsion, réservoir, électronique et charge utile ; câbler.",
             f"Peser le drone complet, plein fait, et mesurer la position du centre de gravité.",
             "Essai de portée radio à 1 km, moteurs arrêtés puis moteurs tournants.",
             "Vérifier les sécurités : perte de liaison radio, batterie faible, arrêt moteur.",
             "Faire tourner le moteur thermique 30 minutes au sol, drone attaché, et relever les vibrations enregistrées par l'autopilote."],
            ["Balance", "Station sol", "Sangles d'arrimage"],
            f"Masse au décollage ≤ {nb(1.05 * masse, 1)} kg. Centre de gravité dans la plage fixée à l'étape 3. "
            "Liaison radio stable à 1 km moteurs tournants. Chaque sécurité déclenche le comportement prévu.",
            ["Masse au décollage (kg)", "Position du centre de gravité (% de la corde)", "Portée radio vérifiée (m)", "Niveau de vibrations"],
            "Drone arrimé pour tout essai moteur tournant. Hélices démontées pour les essais de sécurités.",
        ),
        Etape(
            "Autorisations et zone d'essai",
            "Voler dans un cadre légal et sûr.",
            ["Obtenir l'autorisation de vol auprès de l'autorité compétente pour la zone et les dates d'essai.",
             "Choisir une zone dégagée, sans habitation ni route sous les trajectoires.",
             "Rédiger la fiche d'essai : objectif de chaque vol, critères d'arrêt, rôle de chacun."],
            ["Dossier de conception", "Fiche d'essai"],
            "Autorisation écrite obtenue. Zone reconnue. Fiche d'essai signée par le responsable des essais.",
            ["Référence de l'autorisation", "Lieu et dates d'essai"],
        ),
    ]
    if p.vtol:
        etapes += [
            Etape(
                "Vol stationnaire",
                "Valider la sustentation et le pilotage en vertical.",
                ["Premier essai drone retenu par des longes de 1 m : décollage, tenue 30 secondes, atterrissage.",
                 "Puis vol libre à 3 m : stationnaire de 2 minutes, petits déplacements.",
                 "Relever la puissance électrique et la température des moteurs et de la batterie."],
                ["Longes", "Station sol", "Thermomètre infrarouge"],
                f"Stationnaire stable sans oscillation. Puissance électrique à moins de 20 % de {nb(v['p_stationnaire'] / 1000, 1)} kW. "
                "Moteurs sous 80 °C et batterie sous 55 °C après 2 minutes.",
                ["Puissance en stationnaire (kW)", "Température des moteurs (°C)", "Température de la batterie (°C)"],
                "Zone dégagée sur 30 m. Personne à moins de 15 m.",
            ),
            Etape(
                "Transition et premier vol en croisière",
                "Passer du vol vertical au vol d'avion, et revenir.",
                [f"Monter à 40 m, accélérer jusqu'à {nb(1.2 * c['v_decrochage'], 0)} m/s, couper la sustentation.",
                 f"Voler 15 minutes en palier à {nb(c['vitesse'], 0)} m/s ; relever régime moteur et consommation.",
                 "Revenir en vol vertical et atterrir."],
                ["Station sol", "Balance pour peser le carburant avant et après"],
                f"Transition sans perte d'altitude de plus de 10 m. Palier tenu à {nb(c['vitesse'], 0)} m/s. "
                f"Consommation ≤ {nb(1.2 * drone['conso_moyenne_g_h'], 0)} g/h.",
                ["Perte d'altitude en transition (m)", "Vitesse de croisière (m/s)", "Consommation (g/h)", "Régime moteur en palier (tr/min)"],
            ),
        ]
    else:
        etapes.append(Etape(
            "Premier vol",
            "Valider le lancement, le vol en palier et l'atterrissage.",
            ["Lancer avec peu de carburant (1 h), monter à 100 m.",
             f"Voler 15 minutes en palier à {nb(c['vitesse'], 0)} m/s ; explorer les basses vitesses jusqu'à {nb(1.15 * c['v_decrochage'], 0)} m/s.",
             "Atterrir ; relever la consommation."],
            ["Catapulte ou piste", "Station sol", "Balance"],
            f"Lancement et atterrissage sans dommage. Palier tenu. Consommation ≤ {nb(1.2 * drone['conso_moyenne_g_h'], 0)} g/h.",
            ["Vitesse de croisière (m/s)", "Consommation (g/h)", "Vitesse minimale tenue (m/s)"],
        ))
    etapes += [
        Etape(
            "Montée en endurance",
            "Atteindre la durée demandée par paliers.",
            [f"Enchaîner des vols de 30 minutes, 2 h, 4 h, puis {nb(p.endurance_h, 0)} h.",
             "Après chaque vol : peser le carburant restant, inspecter cellule, moteur et fixations.",
             "Ne passer au palier suivant que si le précédent est sans anomalie."],
            ["Station sol", "Balance", "Liste d'inspection"],
            f"Vol de {nb(p.endurance_h, 0)} h réalisé, avec au moins {nb(p.reserve_min, 0)} minutes de carburant restant à l'atterrissage.",
            ["Durée du plus long vol (h)", "Carburant consommé (kg)", "Carburant restant (kg)", "Anomalies"],
        ),
        Etape(
            "Recalage et décision",
            "Rendre le modèle fidèle au drone réel, pour la version suivante.",
            ["Reporter masses, puissance et consommation mesurées dans une nouvelle étude, par les réglages experts.",
             "Comparer l'endurance calculée à l'endurance mesurée.",
             "Décider : geler la définition, ou lancer un deuxième prototype."],
            ["La plateforme"],
            "Après recalage, écart inférieur à 10 % sur la masse et la consommation.",
            ["Écart sur la masse (%)", "Écart sur la consommation (%)", "Décision"],
        ),
    ]
    return etapes


def _nomenclature(p: Parametres, variante: dict) -> list:
    drone, moteur = variante["drone"], variante["moteur"]
    ds, v = drone["detail_structure"], drone["vertical"]
    fab, base, yared = "À fabriquer", "Élément de base à approvisionner", "À concevoir avec YARED"
    articles = [
        Article("Aile", 1, fab, f"Composite, {nb(drone['envergure'], 2)} m, {nb(drone['surface'], 2)} m², cible {nb(ds['Aile'], 2)} kg"),
        Article("Empennage", 1, fab, f"Composite, cible {nb(ds['Empennage'], 2)} kg"),
        Article("Fuselage", 1, fab, f"Composite, cible {nb(ds['Fuselage'], 2)} kg"),
        Article("Atterrisseur", 1, fab, f"Cible {nb(ds['Atterrisseur'], 2)} kg"),
        Article("Réservoir", 1, fab, f"{nb(drone['carburant_l'] * 1.05, 1)} L"),
        Article("Moteur thermique", 1, yared, f"{moteur['libelle']}, {nb(moteur['cylindree_cm3'], 0)} cm³"),
        Article("Hélice de croisière", 1, yared, f"Environ {nb(variante['cahier_des_charges']['diametre_helice_m'] * 100, 0)} cm"),
        Article("Génératrice et redresseur", 1, yared, f"{nb(p.p_electrique, 0)} W ; module non encore disponible"),
        Article("Autopilote, GPS, capteur de vitesse", 1, yared, "Cartes à concevoir ; module non encore disponible"),
        Article("Liaison radio et station sol", 1, yared, "Module non encore disponible"),
        Article("Servomoteur", 6, yared, "Module non encore disponible"),
        Article("Charge utile", 1, "Fournie par l'utilisateur", f"{nb(p.m_charge_utile, 1)} kg, {nb(p.p_charge_utile, 0)} W"),
        Article("Tissus de verre et de carbone, résine époxy", 1, base, "Lot"),
        Article("Câbles, connecteurs, visserie", 1, base, "Lot"),
    ]
    if p.vtol:
        articles[3:3] = [Article("Bras de sustentation", 2, fab, f"Tube ou caisson composite, cible {nb(ds['Bras de sustentation'], 2)} kg les deux")]
        articles += [
            Article("Moteur électrique de sustentation", 4, yared, f"{nb(v['poussee_maxi_par_moteur'] / G, 1)} kg de poussée maximale"),
            Article("Hélice de sustentation", 4, yared, f"{nb(v['diametre_helice'] * 100, 0)} cm"),
            Article("Contrôleur de moteur", 4, yared, f"{nb(v['p_moteur_maxi'] / 1000, 1)} kW ; module non encore disponible"),
            Article("Pack batterie", 1, fab, f"{nb(v['energie_batterie_wh'], 0)} Wh, assemblé à partir de cellules"),
            Article("Cellules lithium", 1, base, f"Lot pour {nb(v['energie_batterie_wh'], 0)} Wh, forte décharge"),
        ]
    return articles


def _etudes_composants(p: Parametres, variante: dict, annexes: dict, titre: str) -> list:
    """Réponses prêtes à l'emploi pour ouvrir l'étude YARED de chaque composant."""
    drone, cdc = variante["drone"], variante["cahier_des_charges"]
    altitude_vol = drone["altitude_vol_m"]
    locale = p.pen_moteur > 1.0
    composants = [{
        "module": "moteur-thermique", "libelle": "Moteur thermique",
        "reponses": {
            "nom": f"{titre} — moteur thermique", "puissance_max_w": round(cdc["puissance_max_w"]),
            "puissance_croisiere_w": round(cdc["puissance_croisiere_w"]), "duree_h": cdc["duree_vol_h"], "type": variante["type"],
            "regime_max_tr_min": round(cdc["regime_max_tr_min"]), "regime_croisiere_tr_min": round(cdc["regime_croisiere_tr_min"]),
            "altitude_m": altitude_vol, "temperature_c": round(p.air_vol.temperature - 273.15, 1), "fabrication_locale": locale,
        },
    }]
    if "helice_croisiere" in annexes:
        composants.append({
            "module": "helice", "libelle": "Hélice de croisière",
            "reponses": {
                "nom": f"{titre} — hélice de croisière", "usage": "croisiere",
                "puissance_w": round(drone["p_croisiere_arbre"] - p.p_electrique / p.rendement_generatrice),
                "vitesse_m_s": round(drone["croisiere"]["vitesse"], 1), "regime_tr_min": round(cdc["regime_croisiere_tr_min"]),
                "altitude_m": altitude_vol, "temperature_c": round(p.air_vol.temperature - 273.15, 1),
            },
        })
    if "helice_sustentation" in annexes:
        v = drone["vertical"]
        composants.append({
            "module": "helice", "libelle": "Hélice de sustentation",
            "reponses": {
                "nom": f"{titre} — hélice de sustentation", "usage": "sustentation",
                "poussee_kg": round(drone["masse_totale"] / 4.0, 2), "diametre_m": round(v["diametre_helice"], 3),
                "altitude_m": drone["altitude_sol_m"], "temperature_c": round(p.air_sol.temperature - 273.15, 1),
            },
        })
    if "moteur_sustentation" in annexes:
        m = annexes["moteur_sustentation"]
        composants.append({
            "module": "moteur-electrique", "libelle": "Moteur électrique de sustentation",
            "reponses": {
                "nom": f"{titre} — moteur de sustentation", "couple_nm": round(m["couple_nm"], 3),
                "regime_tr_min": round(m["regime_tr_min"]), "tension_v": m["tension_v"],
                "marge_pointe": round(m["couple_pointe_nm"] / m["couple_nm"], 2), "fabrication_locale": p.pen_moteurs_electriques > 1.0,
            },
        })
    return composants


class DroneVoilureFixe(Module):
    identifiant = "drone-voilure-fixe"
    nom = "Drone à voilure fixe"
    genre = "famille"
    description = "Avion sans pilote à moteur thermique, longue endurance, avec ou sans décollage vertical."
    accepte_expert = True
    questions = [
        Question("endurance_h", "Combien d'heures le drone doit-il rester en vol ?", unite="h", obligatoire=True),
        Question("charge_utile_kg", "Quelle masse doit-il emporter (caméra, calculateur, radio) ?", unite="kg", obligatoire=True),
        Question("piste_disponible", "Y a-t-il une piste dégagée d'au moins 100 m là où il décollera ?", "oui_non"),
        Question("charge_utile_w", "Consommation électrique de la charge utile", unite="W", avance=True),
        Question("altitude_terrain_m", "Altitude du terrain", unite="m", avance=True),
        Question("temperature_max_c", "Température maximale au sol", unite="°C", avance=True),
        Question("hauteur_de_vol_m", "Hauteur de vol au-dessus du sol", unite="m", avance=True),
        Question("vent_max_kmh", "Vent maximal à tenir", unite="km/h", avance=True),
        Question("envergure_max_m", "Envergure maximale", unite="m", avance=True),
        Question("reserve_min", "Réserve de carburant", unite="min", avance=True),
        Question("moteur", "Type de moteur", "choix", avance=True,
                 choix=[["auto", "Laisser la plateforme comparer"]] + [[k, v["libelle"]] for k, v in VARIANTES.items()]),
        Question("fabrication_locale", "Les composants seront-ils fabriqués en atelier local ?", "oui_non", avance=True),
    ]
    exemple = {"nom": "Surveillance jour et nuit", "endurance_h": 8, "charge_utile_kg": 2.0, "piste_disponible": "non"}

    def parametres(self, r: Reponses) -> tuple:
        endurance = r.obligatoire("endurance_h")
        charge = r.obligatoire("charge_utile_kg")
        puissance_cu = r.combler("charge_utile_w", round(30.0 * charge),
                                 "Environ 30 W par kg : ordre de grandeur d'une nacelle caméra avec calculateur embarqué.")
        piste = r.brut("piste_disponible")
        if piste is True:
            vtol = r.deduire("decollage_vertical", "Décollage vertical", False, "", "Une piste est disponible : l'avion classique est plus léger et plus simple.")
        elif piste is False:
            vtol = r.deduire("decollage_vertical", "Décollage vertical", True, "", "Pas de piste disponible : le décollage vertical est nécessaire.")
        else:
            vtol = r.registre.fixer("decollage_vertical", "Décollage vertical", True, "", "défaut",
                                    "Aucune information sur une piste : le décollage vertical fonctionne partout.")
        altitude_sol = r.combler("altitude_terrain_m", 400.0, "Valeur prudente pour le Togo : la plupart du territoire est plus bas.")
        temperature = r.combler("temperature_max_c", 40.0, "Journée chaude de saison sèche : l'air chaud porte moins et le moteur développe moins.")
        hauteur = r.combler("hauteur_de_vol_m", 600.0, "Compromis entre discrétion sonore et finesse de l'image.")
        vent = r.combler("vent_max_kmh", 35.0, "Vent soutenu courant ; le drone doit pouvoir avancer face à lui.")
        envergure = r.combler("envergure_max_m", 3.6, "Aile en deux ou trois tronçons transportable dans un pick-up, moules de taille raisonnable.")
        reserve = r.combler("reserve_min", 30.0, "Marge habituelle pour un retour contre le vent ou une attente à l'atterrissage.")
        moteur = r.combler("moteur", "auto", "La plateforme compare les variantes ; à masse comparable, elle retient la plus simple à fabriquer.")
        locale = r.combler("fabrication_locale", True,
                           "Objectif du projet : les masses du moteur, des moteurs électriques et de la structure sont majorées pour des procédés d'atelier.")
        vitesse_min = r.deduire("vitesse_min", "Vitesse minimale de vol", round(vent / 3.6 + 6.0, 1), "m/s",
                                "Vent maximal plus 6 m/s, pour toujours avancer face au vent.")
        p = Parametres(
            endurance_h=endurance, reserve_min=reserve, m_charge_utile=charge, p_charge_utile=puissance_cu, vtol=vtol,
            air_vol=air(altitude_sol + hauteur, temperature, altitude_sol), air_sol=air(altitude_sol, temperature, altitude_sol),
            v_min=vitesse_min, envergure_max=envergure, type_moteur=moteur if moteur != "auto" else "4T",
            pen_structure=1.15 if locale else 1.0, pen_moteur=1.25 if locale else 1.0, pen_moteurs_electriques=1.25 if locale else 1.0,
        )
        r.appliquer_expert(p)
        return p, moteur, altitude_sol, altitude_sol + hauteur

    def etudier(self, brutes: dict) -> Etude:
        r = Reponses(self.questions, brutes)
        p, choix, altitude_sol, altitude_vol = self.parametres(r)
        types = list(VARIANTES) if choix == "auto" else [choix]
        figes = frozenset(r.expert)
        variantes = [_boucler(dataclasses.replace(p, type_moteur=t), figes) for t in types]
        retenue = variantes[retenir(variantes, lambda v: v["drone"]["masse_totale"])]
        base = dataclasses.replace(p, type_moteur=retenue["type"])
        p = retenue["parametres"]
        retenue["drone"]["altitude_sol_m"], retenue["drone"]["altitude_vol_m"] = altitude_sol, altitude_vol
        alternative = None
        if p.vtol:
            try:
                alternative = _boucler(dataclasses.replace(base, vtol=False), figes)
            except ErreurEtude:
                alternative = None
        annexes = retenue["annexes"]
        drone, moteur, cdc = retenue["drone"], retenue["moteur"], retenue["cahier_des_charges"]
        resultat_moteur = {
            "candidats": [v["moteur"] for v in variantes], "retenu": moteur, "cahier_des_charges": cdc,
            "pieces": predimensionner(moteur, cdc["regime_max_tr_min"], cdc["temperature_air_k"]),
        }
        titre = r.titre or "Drone à voilure fixe"

        sections = [_section_systeme(p, retenue), _section_variantes(variantes, retenue)]
        if alternative:
            sections.append(_section_alternative(retenue, alternative))
        sections += [yared_moteur.section_demande(cdc), yared_moteur.section_moteur(moteur), yared_moteur.section_pieces(resultat_moteur["pieces"])]
        if "helice_croisiere" in annexes:
            sections.append(yared_helice.section_helice(annexes["helice_croisiere"], "Hélice de croisière"))
        if "helice_sustentation" in annexes:
            sections.append(yared_helice.section_helice(annexes["helice_sustentation"], "Hélice de sustentation"))
        if "moteur_sustentation" in annexes:
            sections.append(yared_electrique.section_moteur_electrique(annexes["moteur_sustentation"], "Moteur électrique de sustentation"))
        sections.append(_section_reinjection(retenue))

        return Etude(
            module=self.identifiant, genre=self.genre, titre=titre,
            chiffres=[
                Chiffre(f"{nb(drone['masse_totale'], 1)} kg", "masse au décollage"),
                Chiffre(f"{nb(drone['envergure'], 2)} m", "envergure"),
                Chiffre(f"{nb(drone['croisiere']['vitesse'] * 3.6, 0)} km/h", "vitesse de croisière"),
                Chiffre(f"{nb(drone['carburant_l'], 1)} L", f"carburant pour {nb(p.endurance_h, 0)} h + réserve"),
                Chiffre(f"{nb(moteur['cylindree_cm3'], 0)} cm³", f"moteur {moteur['type']}"),
            ],
            hypotheses=r.registre.en_dicts(), sections=sections, etapes=_etapes(p, retenue, annexes),
            nomenclature=_nomenclature(p, retenue), limites=LIMITES,
            donnees=nettoyer({
                "variantes": variantes, "retenue": retenue["type"], "alternative_sans_vtol": alternative,
                "moteur": resultat_moteur, "annexes": annexes,
                "composants": _etudes_composants(p, retenue, annexes, titre),
            }),
        )


enregistrer(DroneVoilureFixe())
