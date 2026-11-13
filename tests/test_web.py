"""Application web : parcours complet, verrouillage des étapes, sécurité, API."""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from plateforme.socle.stockage import Stockage
from plateforme.web.app import creer_application

HELICE = {"nom": "Hélice d'essai", "usage": "sustentation", "poussee_kg": "5"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("YAME_MOT_DE_PASSE", raising=False)
    return TestClient(creer_application(Stockage(tmp_path / "essai.db")), follow_redirects=False)


def _creer(client, module="helice", donnees=HELICE) -> str:
    reponse = client.post(f"/modules/{module}", data=donnees)
    assert reponse.status_code == 303
    return reponse.headers["location"]


def test_pages_de_base(client):
    assert client.get("/sante").json()["etat"] == "ok"
    accueil = client.get("/")
    assert accueil.status_code == 200 and "Drone à voilure fixe" in accueil.text and "Moteur thermique" in accueil.text
    for module in ("drone-voilure-fixe", "drone-multirotor", "vehicule-terrestre", "moteur-thermique", "helice", "moteur-electrique"):
        assert client.get(f"/modules/{module}").status_code == 200
    assert client.get("/modules/inconnu").status_code == 404
    assert client.get("/etudes/99").status_code == 404


def test_parcours_d_une_etude(client):
    adresse = _creer(client)
    page = client.get(adresse)
    assert page.status_code == 200 and "Hélice d&#39;essai" in page.text and "Nomenclature" in page.text
    assert "comblé" in page.text  # les vides comblés sont affichés
    assert client.get(adresse + "/rapport.html").status_code == 200
    modifier = client.get(adresse + "/modifier")
    assert 'value="5"' in modifier.text
    assert "Hélice d&#39;essai" in client.get("/etudes").text
    assert client.post(adresse + "/supprimer").status_code == 303
    assert client.get(adresse).status_code == 404


def test_erreurs_expliquees(client):
    incomplet = client.post("/modules/helice", data={"usage": "sustentation"})
    assert incomplet.status_code == 422 and "Il manque une information" in incomplet.text
    infaisable = client.post("/modules/helice", data={"usage": "sustentation", "poussee_kg": "500", "diametre_m": "0,2"})
    assert infaisable.status_code == 422 and "augmenter le diamètre" in infaisable.text


def test_plan_de_prototypage_strict(client):
    adresse = _creer(client)
    plan = client.get(adresse + "/plan")
    assert plan.status_code == 200 and "à faire maintenant" in plan.text and "verrouillée" in plan.text
    # On ne saute pas d'étape.
    assert client.post(adresse + "/plan/2", data={"m0": "x", "m1": "y", "critere": "oui"}).status_code == 409
    # Les mesures et la confirmation du critère sont obligatoires.
    assert client.post(adresse + "/plan/1", data={"m0": "0,3", "m1": "", "critere": "oui"}).status_code == 422
    assert client.post(adresse + "/plan/1", data={"m0": "0,3", "m1": "0,2"}).status_code == 422
    valide = client.post(adresse + "/plan/1", data={"m0": "0,3", "m1": "0,2", "critere": "oui", "observations": "RAS"})
    assert valide.status_code == 303
    plan = client.get(adresse + "/plan")
    assert "validée le" in plan.text and "RAS" in plan.text and "(1/6)" in plan.text
    assert client.post(adresse + "/plan/1", data={"m0": "a", "m1": "b", "critere": "oui"}).status_code == 409
    assert client.post(adresse + "/plan/annuler").status_code == 303
    assert "(0/6)" in client.get(adresse + "/plan").text


def test_dossier_et_composants(client):
    adresse = _creer(client, "drone-multirotor", {"charge_utile_kg": "1", "endurance_min": "20"})
    page = client.get(adresse)
    assert "Composants à concevoir avec YARED" in page.text
    archive = client.get(adresse + "/dossier.zip")
    assert archive.status_code == 200 and archive.headers["content-type"] == "application/zip"
    noms = zipfile.ZipFile(io.BytesIO(archive.content)).namelist()
    assert "plan_de_prototypage.md" in noms and any(n.startswith("composants/1-") for n in noms)
    composant = client.post(adresse + "/composants/0")
    assert composant.status_code == 303 and "Hélice" in client.get(composant.headers["location"]).text
    assert client.post(adresse + "/composants/9").status_code == 404


def test_connexion_exigee_si_mot_de_passe(tmp_path, monkeypatch):
    monkeypatch.setenv("YAME_UTILISATEUR", "chef")
    monkeypatch.setenv("YAME_MOT_DE_PASSE", "secret-long")
    client = TestClient(creer_application(Stockage(tmp_path / "essai.db")))
    assert client.get("/sante").status_code == 200  # la sonde de santé reste ouverte
    assert client.get("/").status_code == 401
    assert client.get("/api/etudes").status_code == 401
    assert client.get("/", auth=("chef", "mauvais")).status_code == 401
    assert client.get("/", auth=("chef", "secret-long")).status_code == 200


def test_requete_d_un_autre_site_refusee(client):
    refuse = client.post("/modules/helice", data=HELICE, headers={"Origin": "https://ailleurs.example"})
    assert refuse.status_code == 403
    accepte = client.post("/modules/helice", data=HELICE, headers={"Origin": "http://testserver"})
    assert accepte.status_code == 303


def test_api(client):
    modules = client.get("/api/modules").json()
    assert len(modules) == 6 and all(m["questions"] for m in modules)
    cree = client.post("/api/modules/moteur-electrique/etudes", json={"couple_nm": 1.2, "regime_tr_min": 5000})
    assert cree.status_code == 201
    numero = cree.json()["id"]
    etude = client.get(f"/api/etudes/{numero}").json()
    assert etude["etude"]["module"] == "moteur-electrique" and etude["avancement"] == {}
    assert client.get("/api/etudes").json()[0]["id"] == numero
    erreur = client.post("/api/modules/moteur-electrique/etudes", json={"couple_nm": 1.2})
    assert erreur.status_code == 422 and "erreur" in erreur.json()


def test_refus_de_demarrer_sans_mot_de_passe_en_deploiement(tmp_path, monkeypatch):
    monkeypatch.setenv("YAME_EXIGER_MOT_DE_PASSE", "1")
    monkeypatch.delenv("YAME_MOT_DE_PASSE", raising=False)
    with pytest.raises(RuntimeError):
        creer_application(Stockage(tmp_path / "essai.db"))
    monkeypatch.setenv("YAME_MOT_DE_PASSE", "secret-long")
    assert creer_application(Stockage(tmp_path / "essai.db")) is not None
