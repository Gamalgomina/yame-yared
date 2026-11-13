"""Stockage des études et de l'avancement du prototypage (SQLite)."""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS etudes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cree_le TEXT NOT NULL,
    module TEXT NOT NULL,
    titre TEXT NOT NULL,
    reponses TEXT NOT NULL,
    etude TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS avancement (
    etude_id INTEGER NOT NULL REFERENCES etudes(id) ON DELETE CASCADE,
    etape INTEGER NOT NULL,
    valide_le TEXT NOT NULL,
    releves TEXT NOT NULL,
    PRIMARY KEY (etude_id, etape)
);
CREATE TABLE IF NOT EXISTS travaux (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cree_le TEXT NOT NULL,
    mode TEXT NOT NULL,
    demande TEXT NOT NULL,
    etat TEXT NOT NULL,
    journal TEXT NOT NULL DEFAULT '[]',
    compte_rendu TEXT NOT NULL DEFAULT '',
    jetons_entree INTEGER NOT NULL DEFAULT 0,
    jetons_sortie INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS propositions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cree_le TEXT NOT NULL,
    travail_id INTEGER,
    identifiant TEXT NOT NULL,
    nom TEXT NOT NULL,
    description TEXT NOT NULL,
    code TEXT NOT NULL,
    controle TEXT NOT NULL,
    etat TEXT NOT NULL
);
"""


class EtapeVerrouillee(ValueError):
    """Tentative de valider une étape hors de l'ordre."""


def chemin_par_defaut() -> Path:
    return Path(os.environ.get("YAME_DONNEES", "donnees")) / "yame.db"


class Stockage:
    def __init__(self, chemin: str | Path | None = None):
        self.chemin = Path(chemin) if chemin else chemin_par_defaut()
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        with self._connexion() as c:
            c.executescript(SCHEMA)

    def _connexion(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.chemin)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        return c

    @staticmethod
    def _maintenant() -> str:
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # --- Études ---------------------------------------------------------
    def creer(self, module: str, titre: str, reponses: dict, etude: dict) -> int:
        with self._connexion() as c:
            curseur = c.execute(
                "INSERT INTO etudes (cree_le, module, titre, reponses, etude) VALUES (?, ?, ?, ?, ?)",
                (self._maintenant(), module, titre, json.dumps(reponses, ensure_ascii=False),
                 json.dumps(etude, ensure_ascii=False)),
            )
            return int(curseur.lastrowid)

    def lister(self) -> list:
        with self._connexion() as c:
            lignes = c.execute(
                "SELECT e.id, e.cree_le, e.module, e.titre, "
                "(SELECT COUNT(*) FROM avancement a WHERE a.etude_id = e.id) AS etapes_validees "
                "FROM etudes e ORDER BY e.id DESC"
            ).fetchall()
        return [dict(ligne) for ligne in lignes]

    def lire(self, identifiant: int) -> dict | None:
        with self._connexion() as c:
            ligne = c.execute("SELECT * FROM etudes WHERE id = ?", (identifiant,)).fetchone()
        if ligne is None:
            return None
        d = dict(ligne)
        d["reponses"] = json.loads(d["reponses"])
        d["etude"] = json.loads(d["etude"])
        return d

    def supprimer(self, identifiant: int) -> None:
        with self._connexion() as c:
            c.execute("DELETE FROM etudes WHERE id = ?", (identifiant,))

    # --- Avancement du prototypage -----------------------------------------
    def avancement(self, identifiant: int) -> dict:
        """Étapes validées : numéro -> {valide_le, releves}."""
        with self._connexion() as c:
            lignes = c.execute(
                "SELECT etape, valide_le, releves FROM avancement WHERE etude_id = ? ORDER BY etape", (identifiant,)
            ).fetchall()
        return {l["etape"]: {"valide_le": l["valide_le"], "releves": json.loads(l["releves"])} for l in lignes}

    def valider_etape(self, identifiant: int, etape: int, releves: dict) -> None:
        """Valide l'étape `etape` (numérotée à partir de 1). Ordre strict."""
        faites = self.avancement(identifiant)
        attendue = len(faites) + 1
        if etape != attendue:
            raise EtapeVerrouillee(f"L'étape à valider est la n° {attendue}, pas la n° {etape}.")
        with self._connexion() as c:
            c.execute(
                "INSERT INTO avancement (etude_id, etape, valide_le, releves) VALUES (?, ?, ?, ?)",
                (identifiant, etape, self._maintenant(), json.dumps(releves, ensure_ascii=False)),
            )

    def annuler_derniere_etape(self, identifiant: int) -> None:
        faites = self.avancement(identifiant)
        if faites:
            with self._connexion() as c:
                c.execute("DELETE FROM avancement WHERE etude_id = ? AND etape = ?", (identifiant, max(faites)))

    # --- Travaux de l'agent IA ----------------------------------------------
    def creer_travail(self, mode: str, demande: str) -> int:
        with self._connexion() as c:
            curseur = c.execute(
                "INSERT INTO travaux (cree_le, mode, demande, etat) VALUES (?, ?, ?, 'en attente')",
                (self._maintenant(), mode, demande),
            )
            return int(curseur.lastrowid)

    def journaliser(self, identifiant: int, genre: str, texte: str) -> None:
        """Ajoute une ligne au journal d'un travail."""
        with self._connexion() as c:
            ligne = c.execute("SELECT journal FROM travaux WHERE id = ?", (identifiant,)).fetchone()
            if ligne is None:
                return
            journal = json.loads(ligne["journal"])
            journal.append({"heure": datetime.datetime.now().strftime("%H:%M:%S"), "genre": genre, "texte": texte})
            c.execute("UPDATE travaux SET journal = ? WHERE id = ?", (json.dumps(journal, ensure_ascii=False), identifiant))

    def etat_travail(self, identifiant: int, etat: str, compte_rendu: str | None = None,
                     jetons_entree: int | None = None, jetons_sortie: int | None = None) -> None:
        with self._connexion() as c:
            c.execute("UPDATE travaux SET etat = ? WHERE id = ?", (etat, identifiant))
            if compte_rendu is not None:
                c.execute("UPDATE travaux SET compte_rendu = ? WHERE id = ?", (compte_rendu, identifiant))
            if jetons_entree is not None:
                c.execute("UPDATE travaux SET jetons_entree = ?, jetons_sortie = ? WHERE id = ?",
                          (jetons_entree, jetons_sortie or 0, identifiant))

    def lire_travail(self, identifiant: int) -> dict | None:
        with self._connexion() as c:
            ligne = c.execute("SELECT * FROM travaux WHERE id = ?", (identifiant,)).fetchone()
        if ligne is None:
            return None
        d = dict(ligne)
        d["journal"] = json.loads(d["journal"])
        return d

    def lister_travaux(self) -> list:
        with self._connexion() as c:
            lignes = c.execute("SELECT id, cree_le, mode, demande, etat FROM travaux ORDER BY id DESC").fetchall()
        return [dict(ligne) for ligne in lignes]

    def interrompre_travaux_en_cours(self) -> None:
        """Au démarrage : un travail resté « en cours » a été coupé par un arrêt du serveur."""
        with self._connexion() as c:
            c.execute("UPDATE travaux SET etat = 'interrompu' WHERE etat IN ('en cours', 'en attente')")

    # --- Modules proposés par l'agent IA --------------------------------------
    def creer_proposition(self, travail_id: int | None, identifiant: str, nom: str, description: str,
                          code: str, controle: str) -> int:
        with self._connexion() as c:
            curseur = c.execute(
                "INSERT INTO propositions (cree_le, travail_id, identifiant, nom, description, code, controle, etat) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'à valider')",
                (self._maintenant(), travail_id, identifiant, nom, description, code, controle),
            )
            return int(curseur.lastrowid)

    def lire_proposition(self, identifiant: int) -> dict | None:
        with self._connexion() as c:
            ligne = c.execute("SELECT * FROM propositions WHERE id = ?", (identifiant,)).fetchone()
        return dict(ligne) if ligne else None

    def lister_propositions(self, travail_id: int | None = None) -> list:
        requete = "SELECT id, cree_le, travail_id, identifiant, nom, description, etat FROM propositions"
        with self._connexion() as c:
            if travail_id is None:
                lignes = c.execute(requete + " ORDER BY id DESC").fetchall()
            else:
                lignes = c.execute(requete + " WHERE travail_id = ? ORDER BY id", (travail_id,)).fetchall()
        return [dict(ligne) for ligne in lignes]

    def etat_proposition(self, identifiant: int, etat: str) -> None:
        with self._connexion() as c:
            c.execute("UPDATE propositions SET etat = ? WHERE id = ?", (etat, identifiant))

    def etudes_depuis(self, identifiant_mini: int) -> list:
        with self._connexion() as c:
            lignes = c.execute("SELECT id, titre, module FROM etudes WHERE id >= ? ORDER BY id", (identifiant_mini,)).fetchall()
        return [dict(ligne) for ligne in lignes]

    @property
    def dossier(self) -> Path:
        return self.chemin.parent
