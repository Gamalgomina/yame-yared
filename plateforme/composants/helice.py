"""YARED — hélice à pas fixe.

Calcul par éléments de pale couplé à la théorie de la quantité de mouvement :
la pale est découpée en tranches ; pour chacune, on cherche les vitesses
induites qui équilibrent les efforts aérodynamiques du profil et l'air
accéléré par le disque. Profil de type Clark Y, polaire simplifiée.

Deux usages : croisière (absorber une puissance à une vitesse d'avance) et
sustentation (fournir une poussée à l'arrêt).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..socle.atmosphere import air
from ..socle.erreurs import BesoinInfaisable, BesoinIncomplet
from ..socle.format import nb
from ..socle.modele import Article, Chiffre, Etape, Etude, Question, Section, Tableau, nettoyer
from ..socle.modules import Module, enregistrer
from ..socle.reponses import Reponses

STATIONS = [0.20 + i * (0.97 - 0.20) / 23 for i in range(24)]
DECROCHAGE = 0.158  # rad


def _polaire(alpha: float) -> tuple:
    """Portance et traînée d'un profil mince cambré, petit nombre de Reynolds."""
    if alpha <= DECROCHAGE:
        cl = max(0.35 + 5.7 * alpha, -0.6)
        cd = 0.016 + 0.012 * (cl - 0.5) ** 2
    else:
        exces = alpha - DECROCHAGE
        cl = max(1.25 - 1.6 * exces, 0.7)
        cd = 0.022 + 1.4 * exces
    return cl, cd


@dataclass
class Helice:
    diametre: float  # m
    pas_relatif: float  # pas géométrique / diamètre
    pales: int = 2
    largeur: float = 0.13  # règle la corde maximale (0,13 -> 15 % du rayon)

    @property
    def rayon(self) -> float:
        return self.diametre / 2.0

    def corde(self, x: float) -> float:
        return self.largeur * 4.0 * x * (1.08 - x) * self.rayon

    def calage(self, x: float) -> float:
        """Angle de la corde par rapport au plan de rotation (pas constant)."""
        return math.atan(self.pas_relatif / (math.pi * x))


def analyser(h: Helice, vitesse: float, regime_tr_min: float, densite: float) -> dict:
    """Poussée, couple, puissance et rendement à un point de fonctionnement."""
    omega = regime_tr_min * 2.0 * math.pi / 60.0
    rayon = h.rayon
    pas_radial = (STATIONS[1] - STATIONS[0]) * rayon
    poussee = couple = 0.0
    for x in STATIONS:
        r = x * rayon
        corde, calage = h.corde(x), h.calage(x)
        vi, vt = max(0.05 * omega * rayon, 0.5), 0.0
        d_poussee = d_couple = 0.0
        for _ in range(300):
            v_axiale = max(vitesse + vi, 0.1 * vitesse + 0.05)
            v_tangente = max(omega * r - vt, 0.1 * omega * r)
            phi = math.atan2(v_axiale, v_tangente)
            cl, cd = _polaire(calage - phi)
            pression = 0.5 * densite * (v_axiale**2 + v_tangente**2) * h.pales * corde
            d_poussee = pression * (cl * math.cos(phi) - cd * math.sin(phi))
            d_couple = pression * r * (cl * math.sin(phi) + cd * math.cos(phi))
            # Pertes en bout de pale (Prandtl)
            f = h.pales / 2.0 * (rayon - r) / (r * max(math.sin(phi), 1e-3))
            perte = max(2.0 / math.pi * math.acos(min(1.0, math.exp(-f))), 0.05)
            base = 4.0 * math.pi * r * densite * v_axiale * perte
            vi_cible = d_poussee / base
            vt_cible = d_couple / (base * r)
            if vitesse < 0.1:
                vi_cible = max(vi_cible, 0.0)
            ecart = abs(vi_cible - vi) + abs(vt_cible - vt)
            vi += 0.2 * (vi_cible - vi)
            vt += 0.2 * (vt_cible - vt)
            if ecart < 1e-4:
                break
        poussee += d_poussee * pas_radial
        couple += d_couple * pas_radial
    puissance = couple * omega
    surface = math.pi * rayon**2
    ideale = abs(poussee) ** 1.5 / math.sqrt(2.0 * densite * surface)
    return {
        "poussee_n": poussee, "couple_nm": couple, "puissance_w": puissance,
        "rendement": poussee * vitesse / puissance if puissance > 0 else 0.0,
        "figure_de_merite": ideale / puissance if puissance > 0 and poussee > 0 else 0.0,
        "regime_tr_min": regime_tr_min, "vitesse_m_s": vitesse,
        "mach_bout_pale": math.hypot(omega * rayon, vitesse) / 340.0,
    }


def _dichotomie(fonction, bas, haut, cible, tours=22):
    for _ in range(tours):
        milieu = 0.5 * (bas + haut)
        if fonction(milieu) < cible:
            bas = milieu
        else:
            haut = milieu
    return 0.5 * (bas + haut)


def concevoir_croisiere(puissance: float, vitesse: float, regime: float, densite: float,
                        diametre_max: float, pales: int = 2) -> dict:
    """Hélice qui absorbe `puissance` au régime et à la vitesse donnés, rendement maximal."""
    meilleur = None
    omega = regime * 2.0 * math.pi / 60.0
    diametre = 0.20
    while diametre <= diametre_max + 1e-9:
        if omega * diametre / 2.0 <= 0.62 * 340.0:
            h = Helice(diametre, 0.3, pales)
            absorbee = lambda pas: analyser(Helice(diametre, pas, pales), vitesse, regime, densite)["puissance_w"]  # noqa: E731
            pas_mini = 1.05 * vitesse / (regime / 60.0 * diametre)  # en dessous, la pale ne tire pas
            if pas_mini < 1.5 and absorbee(max(pas_mini, 0.2)) < puissance < absorbee(1.6):
                pas = _dichotomie(absorbee, max(pas_mini, 0.2), 1.6, puissance)
                h = Helice(diametre, pas, pales)
                point = analyser(h, vitesse, regime, densite)
                if meilleur is None or point["rendement"] > meilleur["point"]["rendement"]:
                    meilleur = {"helice": h, "point": point}
        diametre += 0.03
    if meilleur is None:
        raise BesoinInfaisable(
            "Aucune hélice ne convient à ce régime et à cette puissance. "
            "Pistes : autoriser un diamètre plus grand, ou changer le régime."
        )
    return meilleur


def concevoir_sustentation(poussee: float, diametre: float, densite: float, pales: int = 2,
                           marge_poussee: float = 1.8) -> dict:
    """Hélice de sustentation : régime et puissance pour la poussée demandée à l'arrêt."""
    h = Helice(diametre, 0.33, pales, largeur=0.16)
    tire = lambda regime: analyser(h, 0.0, regime, densite)["poussee_n"]  # noqa: E731
    regime_limite = 0.62 * 340.0 / (math.pi * diametre) * 60.0
    if tire(regime_limite) < marge_poussee * poussee:
        raise BesoinInfaisable(
            "Cette hélice n'atteint pas la poussée maximale demandée sans dépasser la vitesse limite en bout de pale. "
            "Piste : augmenter le diamètre."
        )
    regime = _dichotomie(tire, 200.0, regime_limite, poussee)
    regime_maxi = _dichotomie(tire, 200.0, regime_limite, marge_poussee * poussee)
    return {"helice": h, "point": analyser(h, 0.0, regime, densite), "maxi": analyser(h, 0.0, regime_maxi, densite)}


def geometrie(h: Helice) -> list:
    """Stations de la pale : rayon, corde, calage, épaisseur."""
    lignes = []
    for x in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.97):
        corde = h.corde(x)
        epaisseur = (0.18 - 0.08 * x) * corde  # profil épais au pied, fin en bout
        lignes.append({"x": x, "rayon_mm": x * h.rayon * 1000, "corde_mm": corde * 1000,
                       "calage_deg": math.degrees(h.calage(x)), "epaisseur_mm": epaisseur * 1000})
    return lignes


def section_helice(resultat: dict, titre: str = "Hélice : première conception") -> Section:
    h, p = resultat["helice"], resultat["point"]
    lignes = [
        ["Diamètre", f"{nb(h.diametre * 100, 0)} cm ({nb(h.diametre / 0.0254, 1)} pouces)"],
        ["Pas", f"{nb(h.pas_relatif * h.diametre * 100, 0)} cm ({nb(h.pas_relatif * h.diametre / 0.0254, 1)} pouces)"],
        ["Nombre de pales", str(h.pales)],
        ["Régime", f"{nb(p['regime_tr_min'], 0)} tr/min"],
        ["Poussée", f"{nb(p['poussee_n'], 1)} N ({nb(p['poussee_n'] / 9.80665, 2)} kg)"],
        ["Puissance absorbée", f"{nb(p['puissance_w'], 0)} W"],
        ["Couple", f"{nb(p['couple_nm'], 2)} N·m"],
        ["Vitesse en bout de pale", f"Mach {nb(p['mach_bout_pale'], 2)}"],
    ]
    if p["vitesse_m_s"] > 0.1:
        lignes.append(["Rendement", f"{nb(p['rendement'] * 100, 0)} %"])
    else:
        lignes.append(["Figure de mérite", nb(p["figure_de_merite"], 2)])
    if "maxi" in resultat:
        m = resultat["maxi"]
        lignes.append(["Poussée maximale", f"{nb(m['poussee_n'] / 9.80665, 2)} kg à {nb(m['regime_tr_min'], 0)} tr/min, {nb(m['puissance_w'], 0)} W"])
    stations = [[f"{nb(s['rayon_mm'], 0)} mm", f"{nb(s['corde_mm'], 1)} mm", f"{nb(s['calage_deg'], 1)}°", f"{nb(s['epaisseur_mm'], 1)} mm"]
                for s in geometrie(h)]
    return Section(titre, ["Calcul par éléments de pale, profil de type Clark Y."], [
        Tableau(["Caractéristique", "Valeur"], lignes),
        Tableau(["Rayon", "Corde", "Calage", "Épaisseur maximale"], stations, "Forme de la pale, du pied vers le bout"),
    ])


def etapes_helice(resultat: dict) -> list:
    h, p = resultat["helice"], resultat["point"]
    regime_max = resultat.get("maxi", p)["regime_tr_min"]
    return [
        Etape("Gabarits de la pale", "Reproduire fidèlement la forme calculée.",
              ["Tracer le profil Clark Y à chaque rayon du tableau « Forme de la pale », à la corde et au calage indiqués.",
               "Découper un gabarit par rayon (tôle ou contreplaqué fin).",
               "Fabriquer le moule ou le bloc à sculpter : bois dur lamellé-collé, ou moule pour stratifié."],
              ["Coordonnées du profil Clark Y", "Scie, limes"],
              "Chaque gabarit respecte la corde à ± 0,5 mm et le calage à ± 0,5°.",
              ["Écart maximal de corde (mm)", "Écart maximal de calage (°)"]),
        Etape("Fabrication de l'hélice", "Obtenir deux pales identiques.",
              ["Mettre en forme les pales en contrôlant avec les gabarits tous les 10 % du rayon.",
               "Percer le moyeu parfaitement au centre.",
               "Poncer, puis vernir ou gelcoater."],
              ["Gabarits", "Perceuse à colonne"],
              f"Diamètre {nb(h.diametre * 1000, 0)} mm ± 1 mm ; les deux pales ont la même longueur à 0,5 mm près.",
              ["Diamètre (mm)", "Masse de l'hélice (g)"]),
        Etape("Équilibrage", "Supprimer les vibrations.",
              ["Poser l'hélice sur un équilibreur à pointes ou sur deux lames horizontales.",
               "Alléger la pale lourde par ponçage du dessus, jamais du bord d'attaque.",
               "Vérifier ensuite l'équilibre du moyeu, hélice verticale."],
              ["Équilibreur"],
              "L'hélice reste immobile dans toutes les positions.",
              ["Masse retirée (g)"]),
        Etape("Essai de survitesse", "Vérifier la tenue mécanique avant tout essai avec du personnel à proximité.",
              [f"Monter l'hélice sur le banc, derrière un écran solide, et la faire tourner 2 minutes à {nb(1.2 * regime_max, 0)} tr/min.",
               "Arrêter, puis inspecter le pied des pales et le moyeu à la loupe."],
              ["Banc d'essai", "Écran de protection", "Compte-tours"],
              f"Aucune fissure ni décollement après 2 minutes à {nb(1.2 * regime_max, 0)} tr/min.",
              ["Régime atteint (tr/min)", "Observations"],
              "Personne dans le plan de rotation. Commande à distance."),
        Etape("Mesure des performances", "Comparer l'hélice réelle au calcul.",
              [f"Mesurer poussée et puissance absorbée à {nb(p['regime_tr_min'], 0)} tr/min"
               + (f", dans un flux d'air de {nb(p['vitesse_m_s'], 0)} m/s si possible (véhicule ou soufflerie), sinon à l'arrêt." if p["vitesse_m_s"] > 0.1 else ", à l'arrêt."),
               "Relever trois régimes autour du point visé."],
              ["Banc d'essai avec mesure de poussée et de couple"],
              f"Poussée et puissance à moins de 15 % des valeurs calculées ({nb(p['poussee_n'], 1)} N, {nb(p['puissance_w'], 0)} W).",
              ["Poussée (N)", "Puissance absorbée (W)", "Régime (tr/min)"]),
        Etape("Recalage", "Corriger le pas si nécessaire.",
              ["Si la puissance absorbée est trop forte, réduire le pas ; trop faible, l'augmenter.",
               "Reporter les mesures dans une nouvelle étude et refaire une hélice si l'écart dépasse 15 %."],
              ["La plateforme"], "Écart final inférieur à 10 %.", ["Écart final sur la poussée (%)", "Décision"]),
    ]


LIMITES = [
    "Polaire de profil simplifiée, sans effet du nombre de Reynolds ni de la compressibilité.",
    "Forme en plan et loi de pas imposées : l'hélice n'est pas optimisée tranche par tranche.",
    "Aucun calcul de résistance de la pale : la tenue est vérifiée par l'essai de survitesse.",
]


class ModuleHelice(Module):
    identifiant = "helice"
    nom = "Hélice"
    genre = "composant"
    description = "Hélice à pas fixe, pour la croisière ou la sustentation : diamètre, pas, rendement, forme de la pale."
    questions = [
        Question("usage", "À quoi sert l'hélice ?", "choix", obligatoire=True,
                 choix=[["croisiere", "Propulser un avion en croisière"], ["sustentation", "Porter un appareil à l'arrêt"]]),
        Question("puissance_w", "Croisière : quelle puissance le moteur lui fournit-il ?", unite="W"),
        Question("vitesse_m_s", "Croisière : à quelle vitesse l'appareil avance-t-il ?", unite="m/s"),
        Question("regime_tr_min", "Croisière : à quel régime tourne le moteur ?", unite="tr/min"),
        Question("poussee_kg", "Sustentation : quelle poussée doit-elle fournir en vol stationnaire ?", unite="kg"),
        Question("diametre_m", "Diamètre (sustentation) ou diamètre maximal (croisière)", unite="m"),
        Question("pales", "Nombre de pales", avance=True),
        Question("altitude_m", "Altitude d'emploi", unite="m", avance=True),
        Question("temperature_c", "Température de l'air la plus chaude", unite="°C", avance=True),
    ]
    exemple = {"nom": "Hélice de croisière", "usage": "croisiere", "puissance_w": 590, "vitesse_m_s": 20.6, "regime_tr_min": 5200}

    def etudier(self, brutes: dict) -> Etude:
        r = Reponses(self.questions, brutes)
        usage = r.obligatoire("usage")
        altitude = r.combler("altitude_m", 400.0, "Valeur prudente pour le Togo.")
        temperature = r.combler("temperature_c", 40.0, "Journée chaude : air moins dense.")
        pales = int(r.combler("pales", 2, "Deux pales : le plus simple à fabriquer et à équilibrer."))
        densite = air(altitude, temperature, altitude).densite
        if usage == "croisiere":
            for cle in ("puissance_w", "vitesse_m_s", "regime_tr_min"):
                if not r.donne(cle):
                    raise BesoinIncomplet(f"Il manque une information : {r.questions[cle].libelle}")
            puissance, vitesse, regime = (r.obligatoire(c) for c in ("puissance_w", "vitesse_m_s", "regime_tr_min"))
            d_max = r.combler("diametre_m", 0.70, "Limite de garde au sol et de vitesse en bout de pale.")
            resultat = concevoir_croisiere(puissance, vitesse, regime, densite, d_max, pales)
        else:
            if not r.donne("poussee_kg"):
                raise BesoinIncomplet(f"Il manque une information : {r.questions['poussee_kg'].libelle}")
            poussee = r.obligatoire("poussee_kg") * 9.80665
            diametre = r.combler("diametre_m", round(math.sqrt(poussee / 200.0 / math.pi) * 2, 2),
                                 "Diamètre donnant une charge de 200 N par m² de disque, bon compromis entre taille et puissance.")
            resultat = concevoir_sustentation(poussee, diametre, densite, pales)
        h, p = resultat["helice"], resultat["point"]
        chiffres = [
            Chiffre(f"{nb(h.diametre / 0.0254, 1)} × {nb(h.pas_relatif * h.diametre / 0.0254, 1)}", "diamètre × pas, en pouces"),
            Chiffre(f"{nb(p['poussee_n'] / 9.80665, 2)} kg", "poussée"),
            Chiffre(f"{nb(p['puissance_w'], 0)} W", "puissance absorbée"),
            Chiffre(f"{nb(p['rendement'] * 100, 0)} %", "rendement") if usage == "croisiere"
            else Chiffre(nb(p["figure_de_merite"], 2), "figure de mérite"),
        ]
        return Etude(
            module=self.identifiant, genre=self.genre, titre=r.titre or "Hélice", chiffres=chiffres,
            hypotheses=r.registre.en_dicts(), sections=[section_helice(resultat)], etapes=etapes_helice(resultat),
            nomenclature=[
                Article("Hélice", 1, "À fabriquer", f"{nb(h.diametre * 100, 0)} cm, pas {nb(h.pas_relatif * h.diametre * 100, 0)} cm, bois lamellé ou stratifié"),
                Article("Gabarits de profil", 9, "À fabriquer", "Un par rayon du tableau"),
                Article("Résine, fibre ou bois dur", 1, "Élément de base à approvisionner", "Lot"),
            ],
            limites=LIMITES, donnees=nettoyer({**resultat, "stations": geometrie(h)}),
        )


enregistrer(ModuleHelice())
