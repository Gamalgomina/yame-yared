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
