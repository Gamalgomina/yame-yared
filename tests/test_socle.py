"""Socle : questions, hypothèses, stockage, dossier."""

import io
import json
import zipfile

import pytest

from plateforme.socle import dossier, modules
from plateforme.socle.atmosphere import air
from plateforme.socle.erreurs import BesoinIncomplet
from plateforme.socle.format import nb, texte
from plateforme.socle.modele import Etude, Question
from plateforme.socle.rendu import nomenclature_csv, plan_markdown, rapport_autonome
from plateforme.socle.reponses import Reponses, normaliser
from plateforme.socle.stockage import EtapeVerrouillee, Stockage


def test_atmosphere_standard():
    a = air(0.0, 15.0)
    assert a.densite == pytest.approx(1.225, rel=1e-3)
    assert air(1000.0, 40.0, 400.0).densite < a.densite


def test_format_francais():
    assert nb(1234.5, 1) == "1 234,5"
    assert texte(True) == "oui" and texte(8.0) == "8" and texte(2.5) == "2,5"


def test_normalisation_des_reponses():
    nombre = Question("x", "Combien ?")
    assert normaliser(nombre, "2,5") == 2.5
    assert normaliser(nombre, "") is None
    with pytest.raises(BesoinIncomplet):
        normaliser(nombre, "beaucoup")
    oui_non = Question("p", "Piste ?", "oui_non")
    assert normaliser(oui_non, "oui") is True and normaliser(oui_non, "Non") is False
    assert normaliser(oui_non, "je ne sais pas") is None
    choix = Question("c", "Lequel ?", "choix", choix=[["a", "A"], ["b", "B"]])
    assert normaliser(choix, "a") == "a"
    with pytest.raises(BesoinIncomplet):
        normaliser(choix, "z")


def test_comblement_et_tracabilite():
    questions = [Question("a", "Valeur A ?", unite="kg", obligatoire=True), Question("b", "Valeur B ?")]
    r = Reponses(questions, {"a": "3", "b": ""})
    assert r.obligatoire("a") == 3.0
    assert r.combler("b", 7.0, "Parce que.") == 7.0
    origines = {h.cle: h.origine for h in r.registre.liste()}
    assert origines == {"a": "utilisateur", "b": "défaut"}
    assert r.registre.hypotheses["b"].raison == "Parce que."
    with pytest.raises(BesoinIncomplet):
        Reponses(questions, {}).obligatoire("a")


def test_reglages_experts_en_texte():
    r = Reponses([], {"expert": "alpha = 2.5\nbeta = 3"})
    assert r.expert == {"alpha": 2.5, "beta": 3}
    with pytest.raises(BesoinIncomplet):
        Reponses([], {"expert": "ceci n'est pas du toml"})


def test_stockage_et_ordre_strict_des_etapes(tmp_path):
    base = Stockage(tmp_path / "essai.db")
    numero = base.creer("helice", "Essai", {"a": 1}, {"module": "helice"})
    assert base.lire(numero)["reponses"] == {"a": 1}
    assert base.lister()[0]["etapes_validees"] == 0
    with pytest.raises(EtapeVerrouillee):
        base.valider_etape(numero, 2, {})
    base.valider_etape(numero, 1, {"mesure": "12"})
    with pytest.raises(EtapeVerrouillee):
        base.valider_etape(numero, 1, {})
    base.valider_etape(numero, 2, {})
    assert list(base.avancement(numero)) == [1, 2]
    assert base.avancement(numero)[1]["releves"] == {"mesure": "12"}
    base.annuler_derniere_etape(numero)
    assert list(base.avancement(numero)) == [1]
    base.supprimer(numero)
    assert base.lire(numero) is None and base.avancement(numero) == {}


def test_etude_aller_retour_json():
    module = modules.obtenir("helice")
    etude = module.etudier(module.exemple)
    copie = Etude.depuis_dict(json.loads(json.dumps(etude.en_dict(), ensure_ascii=False)))
    assert copie.en_dict() == etude.en_dict()


def test_rendus():
    module = modules.obtenir("moteur-electrique")
    etude = module.etudier(module.exemple)
    html = rapport_autonome(etude, module.nom, {1: {"valide_le": "2026-01-01 10:00", "releves": {etude.etapes[0].mesures[0]: "1,4"}}})
    assert "Plan de prototypage" in html and "validée le 2026-01-01" in html and "<script" not in html
    plan = plan_markdown(etude)
    assert plan.count("## Étape") == len(etude.etapes) and "Critère de réussite" in plan
    assert nomenclature_csv(etude).splitlines()[0] == "Désignation;Quantité;Nature;Spécification"


def test_dossier_de_conception_complet():
    module = modules.obtenir("drone-multirotor")
    etude = module.etudier(module.exemple)
    archive = zipfile.ZipFile(io.BytesIO(dossier.construire(etude)))
    noms = set(archive.namelist())
    assert {"LISEZ-MOI.txt", "rapport.html", "plan_de_prototypage.md", "nomenclature.csv", "resultats.json"} <= noms
    # Un sous-dossier complet par composant à concevoir.
    for numero, composant in enumerate(etude.donnees["composants"], 1):
        prefixe = f"composants/{numero}-{dossier.nom_de_fichier(composant['libelle'])}/"
        assert prefixe + "plan_de_prototypage.md" in noms and prefixe + "rapport.html" in noms
    assert json.loads(archive.read("resultats.json"))["module"] == "drone-multirotor"


def test_nom_de_fichier():
    assert dossier.nom_de_fichier("Hélice de croisière n° 2") == "helice-de-croisiere-n-2"
    assert dossier.nom_de_fichier("???") == "etude"
