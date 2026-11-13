"""Modules : contrat commun, cohérence interne et plausibilité physique."""

import math

import pytest

from plateforme.composants import helice, moteur_electrique
from plateforme.composants.moteur_thermique import cao
from plateforme.composants.moteur_thermique.conception import concevoir
from plateforme.composants.moteur_thermique.cycle import PCI_ESSENCE, Moteur, simuler
from plateforme.composants.moteur_thermique.pieces import predimensionner
from plateforme.familles import drone_multirotor, vehicule_terrestre
from plateforme.familles.drone_voilure_fixe import DroneVoilureFixe, _boucler
from plateforme.familles.drone_voilure_fixe.dimensionnement import cahier_des_charges_moteur, dimensionner
from plateforme.socle import modules
from plateforme.socle.atmosphere import G, air
from plateforme.socle.erreurs import BesoinIncomplet, BesoinInfaisable
from plateforme.socle.reponses import Reponses

IDENTIFIANTS = [m.identifiant for m in modules.tous()]


def _parametres_drone(**reponses):
    module = DroneVoilureFixe()
    base = {"endurance_h": 8, "charge_utile_kg": 2.0, "piste_disponible": "non", "moteur": "4T"}
    return module.parametres(Reponses(module.questions, {**base, **reponses}))[0]


# --- Contrat commun à tous les modules ------------------------------------------

def test_les_six_modules_sont_enregistres():
    assert set(IDENTIFIANTS) == {"drone-voilure-fixe", "drone-multirotor", "vehicule-terrestre",
                                 "moteur-thermique", "helice", "moteur-electrique"}


@pytest.fixture(scope="module")
def etudes():
    return {m.identifiant: m.etudier(m.exemple) for m in modules.tous()}


@pytest.mark.parametrize("identifiant", IDENTIFIANTS)
def test_contrat_d_un_module(identifiant, etudes):
    module, etude = modules.obtenir(identifiant), etudes[identifiant]
    assert etude.module == identifiant and etude.genre == module.genre and etude.titre
    assert len(etude.chiffres) >= 3 and etude.sections and etude.limites and etude.nomenclature
    # Rien n'est décidé en silence : toute valeur comblée ou déduite est expliquée.
    assert all(h["raison"] for h in etude.hypotheses if h["origine"] != "utilisateur")
    # Plan de prototypage : chaque étape a des actions, un critère chiffrable et des mesures à relever.
    assert len(etude.etapes) >= 6
    for etape in etude.etapes:
        assert etape.titre and etape.objectif and etape.actions and etape.critere and etape.mesures
    # Les clés obligatoires sont bien exigées.
    obligatoires = [q.cle for q in module.questions if q.obligatoire]
    if obligatoires:
        with pytest.raises(BesoinIncomplet):
            module.etudier({k: v for k, v in module.exemple.items() if k != obligatoires[0]})


@pytest.mark.parametrize("identifiant", ["drone-voilure-fixe", "drone-multirotor", "vehicule-terrestre"])
def test_les_composants_d_une_famille_s_etudient(identifiant, etudes):
    composants = etudes[identifiant].donnees["composants"]
    assert composants
    for composant in composants:
        sous_etude = modules.obtenir(composant["module"]).etudier(composant["reponses"])
        assert sous_etude.genre == "composant" and sous_etude.etapes


# --- Drone à voilure fixe --------------------------------------------------------

def test_drone_la_masse_boucle():
    p = _parametres_drone()
    drone = dimensionner(p)
    assert sum(drone["masses"].values()) == pytest.approx(drone["masse_totale"], abs=1e-3)
    assert math.sqrt(drone["allongement"] * drone["surface"]) <= p.envergure_max + 1e-9
    assert drone["croisiere"]["v_decrochage"] <= p.vs_max_vtol


def test_drone_croisiere_recalculee_a_la_main():
    p = _parametres_drone()
    d = dimensionner(p)
    rho, s, m, v = p.air_vol.densite, d["surface"], d["masse_totale"], d["croisiere"]["vitesse"]
    cl = m * G / (0.5 * rho * v**2 * s)
    f = p.f_fuselage + p.f_nacelle_camera + p.f_refroidissement + p.f_bras_vtol + p.f_helices_vtol
    cd = p.cd_profil * (1 + p.rapport_empennage) + f / s + cl**2 / (math.pi * p.oswald * d["allongement"])
    arbre = (m * G * cd / cl) * v / p.rendement_helice + p.p_electrique / p.rendement_generatrice
    assert arbre == pytest.approx(d["p_croisiere_arbre"], rel=1e-6)
    attendu = p.conso * arbre / 1000 * (p.endurance_h + p.reserve_min / 60) * (1 + p.carburant_inutilisable)
    assert d["carburant_kg"] == pytest.approx(attendu, rel=0.10) and d["carburant_kg"] <= attendu


def test_drone_tendances():
    m8 = dimensionner(_parametres_drone())["masse_totale"]
    assert dimensionner(_parametres_drone(endurance_h=4))["masse_totale"] < m8
    assert dimensionner(_parametres_drone(piste_disponible="oui"))["masse_totale"] < m8
    assert dimensionner(_parametres_drone(charge_utile_kg=4.0))["masse_totale"] > m8
    assert dimensionner(_parametres_drone(fabrication_locale="non"))["masse_totale"] < m8


def test_drone_infaisable_explique():
    with pytest.raises(BesoinInfaisable):
        dimensionner(_parametres_drone(endurance_h=60, charge_utile_kg=20))


def test_drone_couplage_coherent_et_reglage_expert_respecte():
    v = _boucler(_parametres_drone())
    assert v["tours"] < 14
    assert v["moteur"]["masse_kg"] == pytest.approx(v["drone"]["masses"]["Moteur thermique"], rel=0.02)
    assert v["moteur"]["conso_croisiere"] == pytest.approx(v["drone"]["conso_specifique"], rel=0.02)
    assert v["parametres"].rendement_helice == pytest.approx(0.93 * v["annexes"]["helice_croisiere"]["point"]["rendement"], rel=0.02)
    fige = _boucler(_parametres_drone(expert={"rendement_helice": 0.60}), frozenset({"rendement_helice"}))
    assert fige["parametres"].rendement_helice == 0.60
    assert fige["drone"]["masse_totale"] > v["drone"]["masse_totale"]


def test_drone_etude_complete(etudes):
    donnees = etudes["drone-voilure-fixe"].donnees
    assert len(donnees["variantes"]) == 3
    retenue = next(v for v in donnees["variantes"] if v["type"] == donnees["retenue"])
    assert donnees["alternative_sans_vtol"]["drone"]["masse_totale"] < retenue["drone"]["masse_totale"]
    # L'étude du moteur ouverte depuis le drone redonne le même moteur.
    composant = donnees["composants"][0]
    sous_etude = modules.obtenir("moteur-thermique").etudier(composant["reponses"])
    assert sous_etude.donnees["retenu"]["cylindree_cm3"] == pytest.approx(retenue["moteur"]["cylindree_cm3"], rel=0.02)


# --- Moteur thermique ------------------------------------------------------------

@pytest.mark.parametrize("type_moteur", ["4T", "2T", "2T-ID"])
def test_cycle_plausible(type_moteur):
    moteur = Moteur(type_moteur, 0.040, 0.036, 9.0)
    r = simuler(moteur, 6000, 1.0, 101325.0, 288.15)
    assert 2.5 < r["pme_bar"] < 9.0 and 0.10 < r["rendement_global"] < 0.33 and 20 < r["pression_max_bar"] < 60
    energie_carburant = r["debit_carburant_g_h"] / 3.6e6 * PCI_ESSENCE
    assert r["puissance_w"] + r["chaleur_parois_w"] < energie_carburant
    assert simuler(moteur, 6000, 0.5, 101325.0, 288.15)["puissance_w"] < r["puissance_w"]
    assert simuler(moteur, 6000, 1.0, 80000.0, 310.0)["puissance_w"] < r["puissance_w"]  # air chaud en altitude


def test_ordre_des_consommations():
    conso = {t: simuler(Moteur(t, 0.040, 0.036, 9.0), 5000, 0.7, 101325.0, 288.15)["conso_specifique"] for t in ("4T", "2T", "2T-ID")}
    assert conso["4T"] < conso["2T"] and conso["2T-ID"] < conso["2T"]


@pytest.mark.parametrize("type_moteur", ["4T", "2T", "2T-ID"])
def test_le_moteur_tient_le_cahier_des_charges(type_moteur):
    p = _parametres_drone(moteur=type_moteur)
    cdc = cahier_des_charges_moteur(p, dimensionner(p))
    moteur = concevoir(cdc)
    assert moteur["plein_gaz"]["puissance_w"] == pytest.approx(cdc["puissance_max_w"], rel=0.01)
    assert moteur["croisiere"]["puissance_w"] == pytest.approx(cdc["puissance_croisiere_w"], rel=0.02)
    assert 10 < moteur["cylindree_cm3"] < 200
    pieces = predimensionner(moteur, cdc["regime_max_tr_min"], cdc["temperature_air_k"])
    c, g = pieces["cotes"], pieces["grandeurs"]
    assert 0.2 * c["alesage"] < c["d_axe"] < 0.4 * c["alesage"]
    assert 0.25 * c["alesage"] < c["d_maneton"] < 0.6 * c["alesage"]
    assert g["sigma_axe_mpa"] < 250 and g["effort_gaz_n"] > g["effort_inertie_n"] > 0
    assert 20 < g["masse_piston_g"] < 200 and c["nb_ailettes"] < 60


@pytest.mark.skipif(not cao.disponible(), reason="cadquery n'est pas installé")
def test_fichiers_cao(etudes):
    fichiers = modules.obtenir("moteur-thermique").fichiers(etudes["moteur-thermique"])
    assert set(fichiers) == {"cao/piston.step", "cao/bielle.step", "cao/vilebrequin.step", "cao/cylindre.step"}
    assert all(contenu.startswith(b"ISO-10303-21") for contenu in fichiers.values())


# --- Hélice ----------------------------------------------------------------------

def test_helice_bornes_physiques():
    h = helice.Helice(0.50, 0.5)
    lent, rapide = helice.analyser(h, 0.0, 3000, 1.225), helice.analyser(h, 0.0, 6000, 1.225)
    assert 0 < lent["poussee_n"] < rapide["poussee_n"]
    assert rapide["poussee_n"] == pytest.approx(4 * lent["poussee_n"], rel=0.05)  # poussée ~ régime au carré
    assert 0.3 < rapide["figure_de_merite"] < 0.85
    vol = helice.analyser(h, 20.0, 6000, 1.225)
    assert 0.4 < vol["rendement"] < 0.9 and vol["poussee_n"] < rapide["poussee_n"]


def test_helice_de_croisiere_absorbe_la_puissance():
    r = helice.concevoir_croisiere(600.0, 20.0, 5200.0, 1.05, 0.70)
    assert r["point"]["puissance_w"] == pytest.approx(600.0, rel=0.01)
    assert 0.5 < r["point"]["rendement"] < 0.85 and r["point"]["mach_bout_pale"] < 0.62
    with pytest.raises(BesoinInfaisable):
        helice.concevoir_croisiere(50000.0, 20.0, 5200.0, 1.05, 0.30)


def test_helice_de_sustentation_tient_la_poussee():
    r = helice.concevoir_sustentation(50.0, 0.56, 1.08)
    assert r["point"]["poussee_n"] == pytest.approx(50.0, rel=0.01)
    assert r["maxi"]["poussee_n"] == pytest.approx(90.0, rel=0.01)
    assert r["maxi"]["puissance_w"] > r["point"]["puissance_w"]
    with pytest.raises(BesoinInfaisable):
        helice.concevoir_sustentation(500.0, 0.20, 1.08)


# --- Moteur électrique -------------------------------------------------------------

def test_moteur_electrique_bilan_et_tendances():
    m = moteur_electrique.concevoir(1.35, 5000, 2.4, 6700, 44.4)
    assert m["puissance_w"] == pytest.approx(1.35 * 5000 * 2 * math.pi / 60, rel=1e-6)
    assert 0.75 < m["rendement"] < 0.97 and m["puissance_electrique_w"] > m["puissance_w"]
    assert m["densite_courant_a_mm2"] <= moteur_electrique.DENSITE_COURANT_MAX + 1e-9
    assert m["courant_pointe_a"] > m["courant_a"] and 0.1 < m["masse_kg"] < 2.0
    assert moteur_electrique.concevoir(2.7, 5000, 4.8, 6700, 44.4)["masse_kg"] > m["masse_kg"]
    assert moteur_electrique.concevoir(1.35, 5000, 2.4, 6700, 44.4, toles_fines=True)["rendement"] > m["rendement"]


# --- Multirotor et véhicule ----------------------------------------------------------

def test_multirotor_masse_et_tendances():
    p = drone_multirotor.Parametres(1.0, 20.0, 30.0, air(400, 40, 400))
    d = drone_multirotor.dimensionner(p)
    assert sum(d["masses"].values()) == pytest.approx(d["masse_totale"], abs=1e-4)
    plus_long = drone_multirotor.dimensionner(drone_multirotor.Parametres(1.0, 20.0, 40.0, air(400, 40, 400)))
    assert plus_long["masse_totale"] > d["masse_totale"]
    with pytest.raises(BesoinInfaisable):
        drone_multirotor.dimensionner(drone_multirotor.Parametres(5.0, 100.0, 300.0, air(400, 40, 400)))


def test_vehicule_masse_et_tendances():
    a = air(400, 40, 400)
    p = vehicule_terrestre.Parametres(150.0, 80.0, 40 / 3.6, 0.20, 0.035, a)
    d = vehicule_terrestre.dimensionner(p)
    assert sum(d["masses"].values()) == pytest.approx(d["masse_totale"], abs=1e-3)
    # Effort dans la pente recalculé à la main (traînée de l'air négligeable à 15 km/h).
    angle = math.atan(0.20)
    attendu = d["masse_totale"] * G * (0.035 * math.cos(angle) + math.sin(angle))
    assert d["effort_pente_n"] == pytest.approx(attendu, rel=0.02)
    sable = vehicule_terrestre.dimensionner(vehicule_terrestre.Parametres(150.0, 80.0, 40 / 3.6, 0.20, 0.12, a))
    assert sable["energie_km"] > d["energie_km"] and sable["masse_totale"] > d["masse_totale"]
