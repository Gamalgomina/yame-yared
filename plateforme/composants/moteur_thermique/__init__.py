"""YARED — moteur thermique monocylindre à allumage commandé, 2 ou 4 temps."""

from __future__ import annotations

from ...socle.atmosphere import air
from ...socle.format import nb
from ...socle.modele import Article, Chiffre, Etape, Etude, Question, Section, Tableau, nettoyer
from ...socle.modules import Module, enregistrer
from ...socle.reponses import Reponses
from . import cao
from .conception import VARIANTES, concevoir, retenir
from .pieces import predimensionner

LIMITES = [
    "Cycle : gaz du cylindre traité comme une seule zone ; remplissage décrit par des coefficients ; "
    "pertes thermiques multipliées par un coefficient provisoire. À recaler sur le banc d'essai.",
    "Pièces : cotes de départ issues de règles de construction mécanique, avec des contraintes admissibles "
    "prudentes. Pas de calcul par éléments finis, pas de calcul de fatigue détaillé.",
    "Non traité : écoulements dans les conduits, vibrations de torsion, graissage, allumage, alimentation "
    "en carburant, tenue des roulements.",
    "Fichiers CAO : formes simplifiées à compléter dans un logiciel de dessin, pas des plans de fabrication.",
]


def etudier_moteur(cdc: dict, types: list) -> dict:
    """Conçoit chaque variante, retient la meilleure, pré-dimensionne ses pièces."""
    candidats = [concevoir(cdc, t) for t in types]
    # Critère : masse du moteur plus carburant brûlé sur la durée demandée.
    indice = retenir(candidats, lambda c: c["masse_kg"] + c["carburant_par_vol_kg"])
    retenu = candidats[indice]
    pieces = predimensionner(retenu, cdc["regime_max_tr_min"], cdc["temperature_air_k"])
    return {"candidats": candidats, "retenu": retenu, "pieces": pieces, "cahier_des_charges": cdc}


def section_demande(cdc: dict) -> Section:
    return Section(
        "Cahier des charges du moteur",
        tableaux=[Tableau(["Demande", "Valeur"], [
            ["Puissance maximale à l'arbre, dans l'air du lieu d'emploi", f"{nb(cdc['puissance_max_w'], 0)} W"],
            ["Puissance en régime de croisière", f"{nb(cdc['puissance_croisiere_w'], 0)} W"],
            ["Régime maximal", f"{nb(cdc['regime_max_tr_min'], 0)} tr/min"],
            ["Régime de croisière", f"{nb(cdc['regime_croisiere_tr_min'], 0)} tr/min"],
            ["Durée de fonctionnement d'affilée", f"{nb(cdc['duree_vol_h'], 1)} h"],
            ["Air : pression et température", f"{nb(cdc['pression_air_pa'] / 100, 0)} hPa, {nb(cdc['temperature_air_k'] - 273.15, 0)} °C"],
        ])],
    )


def section_comparaison(resultat: dict) -> Section:
    lignes = []
    for c in resultat["candidats"]:
        nom = c["libelle"] + (" — retenu" if c is resultat["retenu"] else "")
        lignes.append([
            nom, f"{nb(c['cylindree_cm3'], 0)} cm³", f"{nb(c['masse_kg'], 1)} kg",
            f"{nb(c['conso_croisiere'] * 1000, 0)} g/kWh", f"{nb(c['carburant_par_vol_kg'], 1)} kg", c["difficulte"],
        ])
    return Section(
        "Comparaison des variantes",
        ["À masse comparable (moins de 10 % d'écart sur la somme moteur + carburant, soit moins que "
         "l'incertitude du modèle), la plateforme retient le moteur le plus simple à fabriquer."],
        [Tableau(["Variante", "Cylindrée", "Masse", "Consommation en croisière", "Carburant sur la durée", "Fabrication"], lignes)],
    )


def section_moteur(m: dict) -> Section:
    pg, cr = m["plein_gaz"], m["croisiere"]
    return Section(
        "Moteur : première conception",
        ["Simulation du cycle thermodynamique, degré par degré de vilebrequin."],
        [
            Tableau(["Caractéristique", "Valeur"], [
                ["Architecture", f"Monocylindre refroidi par air, {m['libelle']}"],
                ["Cylindrée", f"{nb(m['cylindree_cm3'], 1)} cm³"],
                ["Alésage × course", f"{nb(m['alesage_mm'], 1)} × {nb(m['course_mm'], 1)} mm"],
                ["Taux de compression", nb(m["taux_compression"], 1)],
                ["Masse estimée", f"{nb(m['masse_kg'], 2)} kg"],
                ["Pièces mobiles", m["pieces_mobiles"]],
            ]),
            Tableau(["Point de fonctionnement", "Plein gaz", "Croisière"], [
                ["Régime", f"{nb(pg['regime_tr_min'], 0)} tr/min", f"{nb(cr['regime_tr_min'], 0)} tr/min"],
                ["Ouverture des gaz", "100 %", f"{nb(cr['charge'] * 100, 0)} %"],
                ["Puissance à l'arbre", f"{nb(pg['puissance_w'], 0)} W", f"{nb(cr['puissance_w'], 0)} W"],
                ["Pression moyenne effective", f"{nb(pg['pme_bar'], 2)} bar", f"{nb(cr['pme_bar'], 2)} bar"],
                ["Pression maximale dans le cylindre", f"{nb(pg['pression_max_bar'], 0)} bar", f"{nb(cr['pression_max_bar'], 0)} bar"],
                ["Vitesse moyenne du piston", f"{nb(pg['vitesse_piston_m_s'], 1)} m/s", f"{nb(cr['vitesse_piston_m_s'], 1)} m/s"],
                ["Consommation spécifique", f"{nb(pg['conso_specifique'] * 1000, 0)} g/kWh", f"{nb(cr['conso_specifique'] * 1000, 0)} g/kWh"],
                ["Débit de carburant", f"{nb(pg['debit_carburant_g_h'], 0)} g/h", f"{nb(cr['debit_carburant_g_h'], 0)} g/h"],
                ["Rendement global", f"{nb(pg['rendement_global'] * 100, 0)} %", f"{nb(cr['rendement_global'] * 100, 0)} %"],
                ["Chaleur à évacuer par les ailettes", f"{nb(pg['chaleur_parois_w'], 0)} W", f"{nb(cr['chaleur_parois_w'], 0)} W"],
            ]),
        ],
        list(m["alertes"]),
    )


def section_pieces(pieces: dict) -> Section:
    c, g = pieces["cotes"], pieces["grandeurs"]
    lignes = [
        ["Piston", "Diamètre × hauteur", f"{nb(c['alesage'], 1)} × {nb(c['hauteur_piston'], 1)} mm", "Proportion usuelle"],
        ["Piston", "Épaisseur de la calotte", f"{nb(c['calotte'], 1)} mm", "Plaque en flexion sous la pression maximale"],
        ["Piston", "Épaisseur de la jupe", f"{nb(c['jupe'], 1)} mm", "Minimum de fonderie"],
        ["Piston", "Jeu dans le cylindre, à froid", f"{nb(g['jeu_piston_mm'][0], 2)} à {nb(g['jeu_piston_mm'][1], 2)} mm", "Dilatation de l'aluminium dans la fonte"],
        ["Axe de piston", "Diamètre extérieur / intérieur", f"{nb(c['d_axe'], 1)} / {nb(c['d_axe_int'], 1)} mm", "Pression de contact dans le pied de bielle"],
        ["Axe de piston", "Contrainte de flexion", f"{nb(g['sigma_axe_mpa'], 0)} MPa", "À garder sous 250 MPa (acier cémenté)"],
        ["Segments", "Nombre", f"{c['nb_segments']}", "Étanchéité" + ("" if pieces["deux_temps"] else " et raclage de l'huile")],
        ["Segments", "Hauteur × épaisseur radiale", f"{nb(c['segment_hauteur'], 1)} × {nb(c['segment_radial'], 1)} mm", "Proportion usuelle"],
        ["Segments", "Jeu à la coupe", f"{nb(g['jeu_coupe_mm'], 2)} mm", "Dilatation"],
        ["Bielle", "Entraxe", f"{nb(c['longueur_bielle'], 1)} mm", "Rapport bielle / course"],
        ["Bielle", "Section du corps", f"{nb(c['bielle_largeur'], 1)} × {nb(c['bielle_epaisseur'], 1)} mm", "Compression, traction par inertie, flambement"],
        ["Vilebrequin", "Diamètre du maneton", f"{nb(c['d_maneton'], 1)} mm", "Flexion entre deux paliers"],
        ["Vilebrequin", "Diamètre des tourillons", f"{nb(c['d_tourillon'], 1)} mm", "Flexion et torsion"],
        ["Vilebrequin", "Entraxe des paliers", f"{nb(c['portee_paliers'], 1)} mm", "Proportion usuelle"],
        ["Vilebrequin", "Épaisseur des bras", f"{nb(c['bras_epaisseur'], 1)} mm", "Proportion usuelle"],
        ["Cylindre", "Épaisseur de la chemise", f"{nb(c['chemise'], 1)} mm", "Pression maximale, plus rigidité"],
        ["Cylindre et culasse", "Ailettes", f"{nb(g['surface_ailettes_cm2'], 0)} cm², soit environ {c['nb_ailettes']} ailettes de {nb(c['ailette_d_ext'], 0)} mm de diamètre", "Chaleur à évacuer plein gaz, dans le souffle de l'hélice"],
        ["Culasse", "Volume de la chambre de combustion", f"{nb(g['volume_chambre_cm3'], 1)} cm³", "Taux de compression"],
        ["Culasse", "Fixation", f"4 goujons M{g['filetage_goujon']}", "Effort des gaz majoré de 50 %"],
    ]
    if pieces["deux_temps"]:
        lignes += [
            ["Lumières", "Hauteur de la lumière d'échappement", f"{nb(g['lumiere_echappement_mm'], 1)} mm", "Ouverture 100° après le point mort haut"],
            ["Lumières", "Largeur maximale", f"{nb(g['lumiere_largeur_max_mm'], 1)} mm", "Tenue des segments"],
        ]
    else:
        lignes += [
            ["Distribution", "Soupape d'admission / d'échappement", f"{nb(g['soupape_admission_mm'], 1)} / {nb(g['soupape_echappement_mm'], 1)} mm", "Part de l'alésage"],
            ["Distribution", "Levée", f"{nb(g['levee_soupape_mm'], 1)} mm", "Un quart du diamètre"],
            ["Distribution", "Indice de remplissage au régime maximal", nb(g["indice_mach_admission"], 2), "À garder sous 0,5"],
        ]
    efforts = Tableau(["Grandeur", "Valeur"], [
        ["Effort maximal des gaz sur le piston", f"{nb(g['effort_gaz_n'], 0)} N"],
        ["Effort d'inertie à 110 % du régime maximal", f"{nb(g['effort_inertie_n'], 0)} N"],
        ["Masse en mouvement alternatif", f"{nb(g['masse_alternative_g'], 0)} g (piston {nb(g['masse_piston_g'], 0)} g, axe {nb(g['masse_axe_g'], 0)} g)"],
        ["Masse de la bielle", f"{nb(g['masse_bielle_g'], 0)} g"],
        ["Contrepoids à placer sur le vilebrequin", f"{nb(g['contrepoids_g_mm'], 0)} g·mm"],
        ["Effort vibratoire résiduel au régime maximal", f"{nb(g['effort_residuel_n'], 0)} N, à reprendre par les fixations"],
    ], "Efforts et équilibrage")
    alertes = []
    if g["sigma_axe_mpa"] > 250:
        alertes.append("L'axe de piston est trop chargé en flexion : augmenter son diamètre.")
    if not pieces["deux_temps"] and g["indice_mach_admission"] > 0.5:
        alertes.append("La soupape d'admission est trop petite pour le régime maximal : le remplissage chutera.")
    return Section(
        "Cotes de départ des pièces",
        ["Cotes pour dessiner et fabriquer un premier prototype de banc d'essai. Les contraintes admissibles "
         "sont prudentes, pour des matières et des procédés d'atelier."],
        [Tableau(["Pièce", "Cote", "Valeur", "Base du calcul"], lignes), efforts],
        alertes,
    )


def etapes_moteur(resultat: dict) -> list:
    m, cdc, p = resultat["retenu"], resultat["cahier_des_charges"], resultat["pieces"]
    c, g = p["cotes"], p["grandeurs"]
    cr = m["croisiere"]
    masse_mobile = g["masse_piston_g"] + g["masse_axe_g"]
    distribution = (
        Etape(
            "Lumières du cylindre",
            "Obtenir le balayage prévu par le calcul.",
            [f"Usiner la lumière d'échappement : hauteur {nb(g['lumiere_echappement_mm'], 1)} mm depuis le point mort bas, "
             f"largeur {nb(g['lumiere_largeur_max_mm'], 1)} mm au plus.",
             "Usiner les lumières de transfert, ouverture 20° de vilebrequin après l'échappement.",
             "Casser les arêtes des lumières (chanfrein de 0,3 mm) pour ne pas accrocher les segments."],
            ["Fraiseuse ou meule sur flexible", "Disque gradué sur le vilebrequin"],
            "Ouverture de l'échappement mesurée à 100° ± 2° après le point mort haut.",
            ["Angle d'ouverture de l'échappement (°)", "Angle d'ouverture des transferts (°)"],
        )
        if p["deux_temps"]
        else Etape(
            "Distribution",
            "Ouvrir et fermer les soupapes aux angles prévus.",
            [f"Fabriquer les soupapes : admission {nb(g['soupape_admission_mm'], 1)} mm, échappement {nb(g['soupape_echappement_mm'], 1)} mm, "
             f"levée {nb(g['levee_soupape_mm'], 1)} mm.",
             "Roder chaque soupape sur son siège à la pâte abrasive, puis contrôler l'étanchéité à l'essence.",
             "Fabriquer l'arbre à cames et l'entraîner à la moitié du régime du vilebrequin.",
             "Caler : fermeture de l'admission 45° après le point mort bas, ouverture de l'échappement 55° avant le point mort bas."],
            ["Tour", "Disque gradué sur le vilebrequin", "Comparateur"],
            "Calage mesuré à ± 3° ; aucune fuite d'essence aux sièges en 1 minute.",
            ["Fermeture de l'admission (° après le point mort bas)", "Ouverture de l'échappement (° avant le point mort bas)"],
        )
    )
    return [
        Etape(
            "Revue de conception et choix des matières",
            "Figer les cotes de départ et vérifier que chaque pièce est faisable avec les machines disponibles.",
            ["Relire le tableau « Cotes de départ des pièces » avec le mécanicien et le fondeur ; noter toute cote infaisable.",
             "Choisir la matière de chaque pièce : alliage d'aluminium au silicium pour le piston et le carter, fonte pour la chemise, "
             "acier mi-dur pour la bielle et le vilebrequin.",
             "Ouvrir les fichiers CAO du dossier dans FreeCAD et compléter le dessin : congés, graissage, fixations.",
             "Commander les éléments de base : roulements, bougie, visserie."],
            ["FreeCAD (gratuit)", "Inventaire des machines et des matières"],
            "Chaque cote du tableau est confirmée ou remplacée, et les éléments de base sont commandés.",
            ["Cotes modifiées et raison", "Matière retenue pour chaque pièce"],
        ),
        Etape(
            "Banc d'essai moteur",
            "Disposer d'un moyen de mesure fiable avant de fabriquer le moteur.",
            [f"Construire un bâti rigide ancré au sol, tenant au moins {nb(5 * g['effort_residuel_n'], 0)} N.",
             "Monter le moteur sur un berceau pivotant avec un bras de réaction posé sur une balance, pour mesurer le couple.",
             "Installer un compte-tours, une balance à 1 g près pour peser le carburant consommé, et des sondes de température "
             "sur la culasse et l'échappement.",
             "Installer un coupe-circuit commandé à distance et un écran de protection dans le plan de l'hélice.",
             "Étalonner : suspendre une masse connue au bout du bras et comparer au couple affiché."],
            ["Profilés d'acier soudés", "Balance", "Compte-tours", "Thermocouples", "Extincteur"],
            "Le banc restitue un couple connu à ± 3 %, et le coupe-circuit arrête le moteur à distance.",
            ["Écart de mesure du couple (%)"],
            "Personne dans le plan de rotation de l'hélice. Carburant stocké à plus de 5 m. Essais en plein air.",
        ),
        Etape(
            "Cylindre, chemise et culasse",
            "Obtenir un fût rond et droit, et le bon taux de compression.",
            [f"Couler puis usiner le cylindre et la culasse : {nb(g['surface_ailettes_cm2'], 0)} cm² d'ailettes au total, "
             f"soit environ {c['nb_ailettes']} ailettes de {nb(c['ailette_d_ext'], 0)} mm de diamètre réparties entre les deux.",
             f"Emmancher la chemise en fonte (épaisseur {nb(c['chemise'], 1)} mm) et l'aléser à {nb(c['alesage'], 2)} mm, puis pierrer.",
             f"Usiner la chambre de combustion pour un volume de {nb(g['volume_chambre_cm3'], 1)} cm³, bougie montée.",
             f"Percer et tarauder les 4 goujons M{g['filetage_goujon']}."],
            ["Fonderie d'aluminium", "Tour, alésoir ou barre d'alésage", "Pierre à roder", "Alésomètre", "Burette graduée"],
            f"Alésage {nb(c['alesage'], 2)} mm ± 0,01 mm, défaut de rondeur et de cylindricité ≤ 0,01 mm. "
            f"Volume de chambre {nb(g['volume_chambre_cm3'], 1)} cm³ ± 3 %, mesuré au liquide.",
            ["Alésage en haut, au milieu, en bas, dans deux directions (mm)", "Volume de la chambre (cm³)"],
        ),
        Etape(
            "Piston, axe et segments",
            "Obtenir l'étanchéité sans serrage à chaud.",
            [f"Couler puis usiner le piston : hauteur {nb(c['hauteur_piston'], 1)} mm, calotte {nb(c['calotte'], 1)} mm, jupe {nb(c['jupe'], 1)} mm.",
             f"Ajuster son diamètre pour un jeu à froid de {nb(g['jeu_piston_mm'][0], 2)} à {nb(g['jeu_piston_mm'][1], 2)} mm dans le cylindre mesuré à l'étape précédente.",
             f"Usiner l'axe : {nb(c['d_axe'], 1)} mm extérieur, {nb(c['d_axe_int'], 1)} mm intérieur, puis le cémenter et le rectifier.",
             f"Usiner {c['nb_segments']} segments en fonte de {nb(c['segment_hauteur'], 1)} × {nb(c['segment_radial'], 1)} mm, "
             f"jeu à la coupe {nb(g['jeu_coupe_mm'], 2)} mm."],
            ["Tour", "Micromètre", "Jeu de cales", "Four de cémentation ou sous-traitance", "Balance à 0,1 g"],
            f"Jeu piston-cylindre dans la plage indiquée. Masse piston + axe ≤ {nb(1.10 * masse_mobile, 0)} g.",
            ["Jeu piston-cylindre (mm)", "Jeu à la coupe de chaque segment (mm)", "Masse du piston équipé (g)"],
        ),
        Etape(
            "Bielle et vilebrequin",
            "Transmettre l'effort des gaz sans casse ni vibration excessive.",
            [f"Usiner la bielle : entraxe {nb(c['longueur_bielle'], 1)} mm, corps de {nb(c['bielle_largeur'], 1)} × {nb(c['bielle_epaisseur'], 1)} mm, "
             "sans angle vif.",
             f"Usiner le vilebrequin : maneton {nb(c['d_maneton'], 1)} mm, tourillons {nb(c['d_tourillon'], 1)} mm, "
             f"rayon de manivelle {nb(c['course'] / 2, 2)} mm, congés de 1,5 mm au moins.",
             "Traiter thermiquement, puis rectifier maneton et tourillons.",
             f"Équilibrer : ajuster les contrepoids pour un balourd de {nb(g['contrepoids_g_mm'], 0)} g·mm opposé au maneton."],
            ["Tour, fraiseuse", "Four de traitement thermique", "Rectifieuse ou sous-traitance", "Vés et comparateur", "Balance"],
            f"Faux-rond des tourillons ≤ 0,02 mm. Entraxe de bielle à ± 0,05 mm. Balourd à ± 5 %. "
            f"Masse de la bielle ≤ {nb(1.10 * g['masse_bielle_g'], 0)} g.",
            ["Faux-rond (mm)", "Entraxe de la bielle (mm)", "Masse de la bielle (g)", "Balourd mesuré (g·mm)"],
        ),
        distribution,
        Etape(
            "Montage à blanc et compression",
            "Vérifier que tout tourne librement et que le cylindre est étanche avant de mettre du carburant.",
            ["Monter le moteur complet, lubrifié, sans allumage ni carburant.",
             "Le faire tourner à la main sur dix tours : aucun point dur.",
             "L'entraîner à la perceuse et mesurer la compression au compressiomètre."],
            ["Compressiomètre", "Perceuse ou démarreur"],
            f"Rotation libre sur dix tours. Compression d'au moins {'6' if p['deux_temps'] else '7'} bar.",
            ["Compression mesurée (bar)"],
        ),
        Etape(
            "Premier démarrage",
            "Obtenir un ralenti stable.",
            ["Monter l'allumage et l'alimentation en carburant, hélice de banc montée et serrée au couple.",
             "Régler l'avance à l'allumage à 20° avant le point mort haut pour commencer.",
             "Démarrer, laisser tourner deux minutes au ralenti, puis arrêter et chercher fuites et desserrages."],
            ["Banc d'essai", "Lampe stroboscopique ou disque gradué"],
            "Démarrage en moins de dix essais. Ralenti stable pendant deux minutes. Aucune fuite.",
            ["Nombre d'essais avant démarrage", "Régime de ralenti (tr/min)", "Avance retenue (°)"],
            "Port de lunettes et de protections auditives. Une seule personne aux commandes, une au coupe-circuit.",
        ),
        Etape(
            "Rodage",
            "Mettre les surfaces en place sans serrage.",
            ["Faire tourner deux heures par paliers de dix minutes, à moins de 50 % des gaz, en variant le régime.",
             "Relever la température de culasse à chaque palier.",
             "Vidanger (4 temps) ou contrôler la bougie (2 temps) à la fin."],
            ["Banc d'essai"],
            "Température de culasse stabilisée sous 200 °C. Aucun serrage, aucune baisse de régime inexpliquée.",
            ["Température de culasse maximale (°C)", "Durée totale de rodage (h)"],
        ),
        Etape(
            "Courbe de puissance plein gaz",
            "Vérifier que le moteur atteint la puissance demandée.",
            [f"Mesurer couple et régime à cinq régimes entre {nb(0.5 * cdc['regime_max_tr_min'], 0)} et {nb(cdc['regime_max_tr_min'], 0)} tr/min, plein gaz.",
             "Maintenir chaque point 30 secondes ; relever couple, régime, températures et consommation.",
             "Noter la pression atmosphérique et la température de l'air du jour."],
            ["Banc d'essai", "Baromètre, thermomètre"],
            f"Puissance d'au moins {nb(cdc['puissance_max_w'], 0)} W à {nb(cdc['regime_max_tr_min'], 0)} tr/min. Température de culasse ≤ 220 °C.",
            ["Puissance à chaque régime (W)", "Température de culasse (°C)", "Pression (hPa) et température (°C) de l'air"],
        ),
        Etape(
            "Point de croisière",
            "Vérifier la consommation au point où le moteur passera l'essentiel de sa vie.",
            [f"Régler la charge pour {nb(cdc['puissance_croisiere_w'], 0)} W à {nb(cdc['regime_croisiere_tr_min'], 0)} tr/min.",
             "Peser le carburant consommé sur 20 minutes.",
             "Ajuster la richesse et l'avance pour la consommation la plus basse sans raté."],
            ["Banc d'essai", "Balance"],
            f"Consommation ≤ {nb(1.15 * cr['debit_carburant_g_h'], 0)} g/h (valeur calculée : {nb(cr['debit_carburant_g_h'], 0)} g/h, plus 15 %).",
            ["Consommation (g/h)", "Ouverture des gaz (%)", "Température de culasse (°C)"],
        ),
        Etape(
            "Endurance",
            "Prouver que le moteur tient la durée demandée.",
            [f"Au point de croisière : faire tourner 1 h, puis 4 h, puis {nb(cdc['duree_vol_h'], 1)} h d'affilée.",
             "Relever régime, températures et consommation toutes les 15 minutes.",
             "Après le dernier essai, démonter et mesurer l'alésage, le piston et les segments."],
            ["Banc d'essai", "Alésomètre, micromètre"],
            f"Aucun arrêt sur {nb(cdc['duree_vol_h'], 1)} h. Perte de puissance < 5 %. Usure de l'alésage < 0,01 mm.",
            ["Durée atteinte sans arrêt (h)", "Perte de puissance (%)", "Usure de l'alésage (mm)"],
        ),
        Etape(
            "Recalage du modèle",
            "Rendre la simulation fidèle à votre moteur, pour concevoir la version suivante.",
            ["Reporter les mesures des étapes précédentes dans une nouvelle étude, par les réglages experts.",
             "Comparer puissance et consommation calculées et mesurées.",
             "Décider : geler cette conception, ou lancer un deuxième prototype corrigé."],
            ["La plateforme"],
            "Après recalage, écart entre calcul et mesure inférieur à 10 % sur la puissance et la consommation.",
            ["Écart sur la puissance (%)", "Écart sur la consommation (%)", "Décision"],
        ),
    ]


def nomenclature_moteur(resultat: dict) -> list:
    m, p = resultat["retenu"], resultat["pieces"]
    c, g = p["cotes"], p["grandeurs"]
    fab, base, yared = "À fabriquer", "Élément de base à approvisionner", "À concevoir avec YARED"
    articles = [
        Article("Piston", 1, fab, f"Aluminium moulé, {nb(c['alesage'], 1)} × {nb(c['hauteur_piston'], 1)} mm"),
        Article("Axe de piston", 1, fab, f"Acier cémenté, {nb(c['d_axe'], 1)} mm"),
        Article("Segment", c["nb_segments"], fab, f"Fonte, {nb(c['segment_hauteur'], 1)} × {nb(c['segment_radial'], 1)} mm"),
        Article("Bielle", 1, fab, f"Acier, entraxe {nb(c['longueur_bielle'], 1)} mm"),
        Article("Vilebrequin", 1, fab, f"Acier traité, maneton {nb(c['d_maneton'], 1)} mm"),
        Article("Cylindre à ailettes", 1, fab, f"Aluminium moulé, {nb(g['surface_ailettes_cm2'], 0)} cm² d'ailettes avec la culasse"),
        Article("Chemise", 1, fab, f"Fonte, alésage {nb(c['alesage'], 1)} mm"),
        Article("Culasse", 1, fab, f"Aluminium moulé, chambre de {nb(g['volume_chambre_cm3'], 1)} cm³"),
        Article("Demi-carter", 2, fab, "Aluminium moulé"),
        Article("Roulement de vilebrequin", 2, base, f"Alésage {nb(c['d_tourillon'], 0)} mm environ"),
        Article("Cage à aiguilles de tête de bielle", 1, base, f"Pour maneton de {nb(c['d_maneton'], 0)} mm environ"),
        Article("Bougie", 1, base, "Petit culot"),
        Article("Goujon de culasse", 4, base, f"M{g['filetage_goujon']}, classe 8.8"),
        Article("Joints et visserie", 1, base, "Lot"),
        Article("Allumage électronique", 1, yared, "Module non encore disponible dans la plateforme"),
    ]
    if p["deux_temps"]:
        articles.append(Article("Carburateur ou injection", 1, yared, "Module non encore disponible dans la plateforme"))
    else:
        articles += [
            Article("Soupape", 2, fab, f"Acier réfractaire, {nb(g['soupape_admission_mm'], 1)} et {nb(g['soupape_echappement_mm'], 1)} mm"),
            Article("Ressort de soupape", 2, base, ""),
            Article("Arbre à cames, poussoirs, culbuteurs", 1, fab, "Acier traité"),
            Article("Injection et calculateur", 1, yared, "Module non encore disponible dans la plateforme"),
        ]
    return articles


class MoteurThermique(Module):
    identifiant = "moteur-thermique"
    nom = "Moteur thermique"
    genre = "composant"
    description = "Monocylindre à essence refroidi par air, 2 ou 4 temps : cylindrée, consommation, cotes des pièces, fichiers CAO."
    questions = [
        Question("puissance_max_w", "Quelle puissance maximale le moteur doit-il fournir à l'arbre ?", unite="W", obligatoire=True),
        Question("puissance_croisiere_w", "Quelle puissance fournit-il la plupart du temps ?", unite="W"),
        Question("duree_h", "Combien d'heures doit-il tourner d'affilée ?", unite="h"),
        Question("type", "Quel type de moteur ?", "choix",
                 choix=[["auto", "Laisser la plateforme comparer"]] + [[k, v["libelle"]] for k, v in VARIANTES.items()]),
        Question("regime_max_tr_min", "Régime maximal", unite="tr/min", avance=True),
        Question("regime_croisiere_tr_min", "Régime de croisière", unite="tr/min", avance=True),
        Question("altitude_m", "Altitude d'emploi", unite="m", avance=True),
        Question("temperature_c", "Température de l'air la plus chaude", unite="°C", avance=True),
        Question("fabrication_locale", "Le moteur sera-t-il fabriqué en atelier local ?", "oui_non", avance=True),
    ]
    exemple = {"nom": "Moteur de drone 1,7 kW", "puissance_max_w": 1750, "puissance_croisiere_w": 720, "duree_h": 8.5}

    def etudier(self, brutes: dict) -> Etude:
        r = Reponses(self.questions, brutes)
        p_max = r.obligatoire("puissance_max_w")
        p_croisiere = r.combler("puissance_croisiere_w", round(0.45 * p_max),
                                "45 % de la puissance maximale : rapport courant entre croisière et pointe.")
        duree = r.combler("duree_h", 8.0, "Durée d'une mission longue.")
        choix = r.combler("type", "auto", "La plateforme compare les variantes ; à masse comparable, elle retient la plus simple à fabriquer.")
        regime_max = r.combler("regime_max_tr_min", 7000.0, "Régime modéré, favorable à la durée de vie.")
        regime_croisiere = r.combler("regime_croisiere_tr_min", round(regime_max * (p_croisiere / p_max) ** (1 / 3)),
                                     "Charge de type hélice : la puissance varie comme le cube du régime.")
        altitude = r.combler("altitude_m", 400.0, "Valeur prudente pour le Togo.")
        temperature = r.combler("temperature_c", 40.0, "Journée chaude : l'air chaud réduit la puissance.")
        locale = r.combler("fabrication_locale", True, "La masse est majorée de 25 % pour des procédés d'atelier.")
        a = air(altitude, temperature, altitude)
        cdc = {
            "type": choix, "puissance_max_w": p_max, "puissance_croisiere_w": p_croisiere,
            "regime_max_tr_min": regime_max, "regime_croisiere_tr_min": regime_croisiere,
            "pression_air_pa": a.pression, "temperature_air_k": a.temperature,
            "duree_vol_h": duree, "majoration_masse": 1.25 if locale else 1.0,
        }
        resultat = etudier_moteur(cdc, list(VARIANTES) if choix == "auto" else [choix])
        m = resultat["retenu"]
        sections = [section_demande(cdc)]
        if len(resultat["candidats"]) > 1:
            sections.append(section_comparaison(resultat))
        sections += [section_moteur(m), section_pieces(resultat["pieces"])]
        return Etude(
            module=self.identifiant, genre=self.genre, titre=r.titre or "Moteur thermique",
            chiffres=[
                Chiffre(f"{nb(m['cylindree_cm3'], 0)} cm³", f"cylindrée, {m['type']}"),
                Chiffre(f"{nb(m['alesage_mm'], 1)} × {nb(m['course_mm'], 1)} mm", "alésage × course"),
                Chiffre(f"{nb(m['masse_kg'], 1)} kg", "masse estimée"),
                Chiffre(f"{nb(m['croisiere']['debit_carburant_g_h'], 0)} g/h", "consommation en croisière"),
            ],
            hypotheses=r.registre.en_dicts(), sections=sections, etapes=etapes_moteur(resultat),
            nomenclature=nomenclature_moteur(resultat), limites=LIMITES, donnees=nettoyer(resultat),
        )

    def fichiers(self, etude: Etude) -> dict:
        return cao.pieces_step(etude.donnees["pieces"]["cotes"])


enregistrer(MoteurThermique())
