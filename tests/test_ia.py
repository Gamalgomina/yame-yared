"""Agent IA, atelier de R&D, bac à sable et logiciels embarqués.

Le service d'IA est remplacé par un client scénarisé : ces tests vérifient la
mécanique de la plateforme, pas la qualité des réponses d'un modèle.
"""

import pytest
from fastapi.testclient import TestClient

from plateforme import outils
from plateforme.ia import propositions, travaux
from plateforme.ia.agent import Agent
from plateforme.ia.client import Appel, Reponse
from plateforme.outils import bac_a_sable
from plateforme.socle import modules
from plateforme.socle.stockage import Stockage
from plateforme.web.app import creer_application

MODULE_PROPOSE = '''
"""Résistance de charge : modèle d'essai."""
from __future__ import annotations
from plateforme.socle.format import nb
from plateforme.socle.modele import Article, Chiffre, Etape, Etude, Question, Section, Tableau, nettoyer
from plateforme.socle.modules import Module, enregistrer
from plateforme.socle.reponses import Reponses


class Resistance(Module):
    identifiant = "resistance-essai"
    nom = "Résistance de charge"
    genre = "composant"
    description = "Résistance qui dissipe une puissance donnée sous une tension donnée."
    questions = [
        Question("puissance_w", "Quelle puissance doit-elle dissiper ?", unite="W", obligatoire=True),
        Question("tension_v", "Sous quelle tension ?", unite="V", avance=True),
    ]
    exemple = {"nom": "Charge d'essai", "puissance_w": 150}

    def etudier(self, brutes: dict) -> Etude:
        r = Reponses(self.questions, brutes)
        puissance = r.obligatoire("puissance_w")
        tension = r.combler("tension_v", 24.0, "Tension courante des bancs d'essai.")
        ohms = tension ** 2 / puissance
        etapes = [
            Etape(f"Étape {i}", "Objectif.", ["Action."], ["Moyen"], "Critère mesurable.", ["Résistance (ohm)"])
            for i in range(1, 5)
        ]
        return Etude(
            module=self.identifiant, genre=self.genre, titre=r.titre or self.nom,
            chiffres=[Chiffre(f"{nb(ohms, 2)} ohm", "résistance")],
            hypotheses=r.registre.en_dicts(),
            sections=[Section("Résultat", ["Loi d'Ohm."], [Tableau(["Grandeur", "Valeur"], [["Résistance", nb(ohms, 2)]])])],
            etapes=etapes,
            nomenclature=[Article("Fil résistif", 1, "Élément de base à approvisionner", "")],
            limites=["Échauffement non calculé."],
            donnees=nettoyer({"ohms": ohms}),
        )


enregistrer(Resistance())
'''


class ClientScenarise:
    """Rejoue une suite de réponses, comme le ferait le service d'IA."""

    recherche_web = ""

    def __init__(self, scenario):
        self.scenario = list(scenario)
        self.vus = []

    def repondre(self, systeme, messages, definitions):
        self.vus.append({"systeme": systeme, "messages": list(messages), "outils": [d["name"] for d in definitions]})
        etape = self.scenario.pop(0)
        if isinstance(etape, str):
            return Reponse(contenu=[{"type": "text", "text": etape}], textes=[etape], jetons_entree=10, jetons_sortie=5)
        nom, arguments = etape
        identifiant = f"appel_{len(self.vus)}"
        return Reponse(contenu=[{"type": "tool_use", "id": identifiant, "name": nom, "input": arguments}],
                       appels=[Appel(identifiant, nom, arguments)], arret="tool_use", jetons_entree=10, jetons_sortie=5)


@pytest.fixture()
def base(tmp_path):
    return Stockage(tmp_path / "essai.db")


@pytest.fixture(autouse=True)
def _nettoyage():
    yield
    modules.retirer("resistance-essai") if "resistance-essai" not in modules.integres() else None


def test_agent_pilote_lance_une_etude(base):
    client = ClientScenarise([
        ("lister_modules", {}),
        ("lancer_etude", {"module": "helice", "nom": "Hélice demandée", "reponses": {"usage": "sustentation", "poussee_kg": 5}}),
        "Étude n° 1 créée.",
    ])
    journal = []
    agent = Agent(client, base, journal=lambda genre, texte: journal.append((genre, texte)))
    assert agent.travailler("pilote", "Une hélice qui porte 5 kg.") == "Étude n° 1 créée."
    assert agent.etudes == [1] and base.lire(1)["titre"] == "Hélice demandée"
    assert agent.jetons_entree == 30
    assert "proposer_module" not in client.vus[0]["outils"]  # réservé à l'atelier
    assert "non armé" in client.vus[0]["systeme"]
    resultat = client.vus[2]["messages"][-1]["content"][0]
    assert resultat["type"] == "tool_result" and "Chiffres clés" in resultat["content"]
    assert [genre for genre, _ in journal].count("outil") == 2


def test_agent_survit_aux_erreurs_d_outil(base):
    client = ClientScenarise([
        ("outil_inexistant", {}),
        ("lancer_etude", {"module": "helice", "reponses": {}}),  # il manque une réponse obligatoire
        ("lancer_etude", {"module": "inconnu", "reponses": {}}),
        "Je n'ai pas pu conclure.",
    ])
    agent = Agent(client, base)
    assert agent.travailler("pilote", "essai") == "Je n'ai pas pu conclure."
    erreurs = [m["content"][0] for m in client.vus[-1]["messages"] if m["role"] == "user" and isinstance(m["content"], list)]
    assert all(e.get("is_error") for e in erreurs) and len(erreurs) == 3
    assert agent.etudes == []


def test_agent_borne_le_nombre_de_tours(base):
    client = ClientScenarise([("lister_modules", {})] * 5)
    agent = Agent(client, base, tours_max=3)
    assert "maximal" in agent.travailler("pilote", "essai")
    assert len(client.vus) == 3


def test_atelier_proposition_puis_validation(base, tmp_path):
    client = ClientScenarise([
        ("proposer_module", {"identifiant": "resistance-essai", "nom": "Résistance", "description": "Loi d'Ohm.",
                             "code": "def cassé("}),
        ("proposer_module", {"identifiant": "resistance-essai", "nom": "Résistance de charge",
                             "description": "Loi d'Ohm.", "code": MODULE_PROPOSE}),
        "Module proposé n° 1, à valider.",
    ])
    agent = Agent(client, base, travail_id=None)
    agent.travailler("atelier", "Une résistance de charge de 150 W.")
    assert "proposer_module" in client.vus[0]["outils"]
    refus = client.vus[1]["messages"][-1]["content"][0]
    assert "syntaxe" in refus["content"]  # le premier envoi, cassé, est refusé avec la raison
    assert agent.propositions == [1]
    proposition = base.lire_proposition(1)
    assert proposition["etat"] == "à valider"
    # Tant qu'une personne n'a pas validé, le module n'existe pas dans la plateforme.
    assert "resistance-essai" not in {m.identifiant for m in modules.tous()}

    module = propositions.activer(base.dossier, "resistance-essai", proposition["code"])
    assert module.etudier({"puissance_w": 96}).chiffres[0].valeur.startswith("6,00")
    assert (propositions.dossier_des_ajouts(base.dossier) / "resistance-essai.py").is_file()
    propositions.desactiver(base.dossier, "resistance-essai")
    assert "resistance-essai" not in {m.identifiant for m in modules.tous()}


def test_controle_refuse_un_module_incomplet():
    sans_plan = MODULE_PROPOSE.replace("for i in range(1, 5)", "for i in range(1, 2)")
    rapport = propositions.controler("resistance-essai", sans_plan)
    assert not rapport["valide"] and "4 étapes" in rapport["rapport"]
    assert not propositions.controler("Mauvais Nom", MODULE_PROPOSE)["valide"]
    assert not propositions.controler("helice", MODULE_PROPOSE)["valide"]  # ne remplace pas un module livré


def test_bac_a_sable_ne_transmet_pas_les_secrets(monkeypatch):
    monkeypatch.setenv("YAME_IA_CLE", "cle-secrete")
    monkeypatch.setenv("YAME_MOT_DE_PASSE", "mot-secret")
    sortie = bac_a_sable.executer("import os\nprint(sorted(os.environ))\nopen('resultat.txt', 'w').write('ok')")
    assert sortie.reussi
    assert "YAME_IA_CLE" not in sortie.sortie and "YAME_MOT_DE_PASSE" not in sortie.sortie
    assert sortie.fichiers == {"resultat.txt": b"ok"}


def test_bac_a_sable_interrompt_un_calcul_trop_long():
    sortie = bac_a_sable.executer("while True:\n    pass", duree_max=2)
    assert sortie.depasse and not sortie.reussi


def test_parcours_web_de_l_agent(base, monkeypatch):
    monkeypatch.delenv("YAME_MOT_DE_PASSE", raising=False)
    monkeypatch.delenv("YAME_EXIGER_MOT_DE_PASSE", raising=False)
    monkeypatch.delenv("YAME_IA_CLE", raising=False)

    sans_cle = TestClient(creer_application(base), follow_redirects=False)
    assert "clé" in sans_cle.get("/ia").text
    assert sans_cle.post("/ia", data={"mode": "pilote", "demande": "Une hélice."}).status_code == 409
    assert sans_cle.get("/outils").status_code == 200 and len(sans_cle.get("/api/outils").json()) >= 4

    scenario = [("proposer_module", {"identifiant": "resistance-essai", "nom": "Résistance de charge",
                                     "description": "Loi d'Ohm.", "code": MODULE_PROPOSE}), "Proposition n° 1."]
    client = TestClient(creer_application(base, fabrique_client=lambda: ClientScenarise(scenario)), follow_redirects=False)
    assert client.post("/ia", data={"mode": "atelier", "demande": ""}).status_code == 422
    reponse = client.post("/ia", data={"mode": "atelier", "demande": "Une résistance de charge."})
    assert reponse.status_code == 303
    travaux.attendre(1, 120)
    page = client.get(reponse.headers["location"])
    assert page.status_code == 200 and "Proposition n° 1." in page.text
    assert client.get("/api/ia/travaux/1").json()["etat"] == "terminé"

    assert client.get("/modules/resistance-essai").status_code == 404
    assert client.post("/propositions/1/valider", data={}).status_code == 422  # relecture non confirmée
    assert client.post("/propositions/1/valider", data={"relu": "oui"}).status_code == 303
    assert client.get("/modules/resistance-essai").status_code == 200
    assert client.post("/propositions/1/rejeter").status_code == 303
    assert client.get("/modules/resistance-essai").status_code == 404


# --- Logiciels embarqués : essais réels, sautés là où le logiciel n'est pas installé ---

def _outil(identifiant):
    outil = outils.obtenir(identifiant)
    if not outil.disponible():
        pytest.skip(f"{outil.logiciel} n'est pas installé ici")
    return outil


def test_registre_des_outils():
    identifiants = {o.identifiant for o in outils.tous()}
    assert {"cao", "aerodynamique", "structure", "autopilote", "simulateur", "openfoam", "getdp", "kicad"} <= identifiants
    for outil in outils.tous():
        assert outil.nom and outil.logiciel and outil.role and isinstance(outil.etat(), str)


def test_autopilote_genere_reglages_et_mission():
    resultat = outils.obtenir("autopilote").executer(
        vitesse_decrochage_m_s=15.9, vitesse_croisiere_m_s=20.6, hauteur_de_vol_m=600, latitude=6.17, longitude=1.25)
    noms = {r["nom"] for r in resultat.donnees["reglages"]}
    assert {"AIRSPEED_CRUISE", "AIRSPEED_MIN", "Q_ENABLE"} <= noms
    assert resultat.fichiers["mission.waypoints"].startswith(b"QGC WPL 110")


def test_cao_puis_structure_sur_une_poutre():
    piece = _outil("cao").executer(script="import cadquery as cq\nresultat = cq.Workplane('XY').box(120, 12, 8)",
                                  densite_kg_m3=7850)
    assert piece.donnees["volume_cm3"] == pytest.approx(11.52, rel=1e-3)
    step = piece.fichiers["piece.step"]
    calcul = _outil("structure").executer(step=step.decode(), matiere="acier", axe="x", force_n=[0, 0, -100])
    # Poutre encastrée : flèche = F L^3 / (3 E I) = 0,536 mm ; contrainte = 6 F L / (b h^2) = 93,8 MPa.
    assert calcul.donnees["deplacement_max_mm"] == pytest.approx(0.536, rel=0.08)
    assert calcul.donnees["contrainte_max_mpa"] == pytest.approx(93.8, rel=0.30)


def test_aerodynamique_point_de_vol():
    resultat = _outil("aerodynamique").executer(envergure_m=2.84, surface_m2=1.15, masse_kg=20.4, vitesse_m_s=20.6,
                                                densite_kg_m3=1.013)
    palier = resultat.donnees["palier"]
    # Portance = poids : CL = m g / (1/2 rho V^2 S)
    assert palier["cl"] == pytest.approx(20.4 * 9.80665 / (0.5 * 1.013 * 20.6**2 * 1.15), rel=0.02)
    assert 5 < palier["finesse"] < 30


def test_mecanique_des_fluides_cas_d_essai():
    assert _outil("openfoam").executer().donnees["essai_de_fonctionnement"]["pas_de_temps_calcules"] == 20


def test_simulateur_accepte_les_reglages_generes():
    simulateur = _outil("simulateur")
    reglages = outils.obtenir("autopilote").executer(
        vitesse_decrochage_m_s=15.9, vitesse_croisiere_m_s=20.6, hauteur_de_vol_m=600,
        capacite_batterie_mah=13000, elements_batterie=12).fichiers["reglages_arduplane.param"].decode()
    bilan = simulateur.executer(reglages=reglages, decollage_vertical=True).donnees
    assert bilan["inconnus_du_logiciel_de_vol"] == []
    assert bilan["acceptes"] + len(bilan["modifies_par_le_logiciel_de_vol"]) == bilan["reglages_envoyes"]
