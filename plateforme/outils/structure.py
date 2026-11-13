"""Résistance d'une pièce par éléments finis.

Embarque gmsh (maillage) et CalculiX (solveur). La pièce arrive en STEP,
cotée en millimètres. Cas de charge traité : la pièce est encastrée à une
extrémité le long d'un axe et reçoit une force à l'autre extrémité. C'est le
cas d'un longeron d'aile, d'une bielle, d'un bras, d'un maneton.

Unités : mm, N, MPa.

Limites : calcul statique, élastique et linéaire ; matière homogène et
isotrope (donc pas les composites stratifiés) ; pas de flambement ni de
fatigue. Les contraintes relevées tout près de l'encastrement et du point
d'application de la force sont faussées par la façon simplifiée d'appliquer
les efforts : l'outil rend aussi la contrainte maximale hors de ces zones.
Les contraintes sont lues à l'intérieur des éléments : en surface, la valeur
réelle est supérieure de quelques pour cent.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import ErreurOutil, Outil, Resultat, enregistrer

AXES = {"x": 0, "y": 1, "z": 2}
MATIERES = {
    # nom : (module d'Young en MPa, coefficient de Poisson, limite élastique indicative en MPa)
    "acier": (210000.0, 0.30, 350.0),
    "aluminium": (70000.0, 0.33, 150.0),
    "fonte": (110000.0, 0.26, 150.0),
    "bois": (10000.0, 0.35, 40.0),
}


def _mailler(step: bytes, taille: float | None, dossier: Path):
    """Maille la pièce en tétraèdres à 10 nœuds. Rend (nœuds, éléments, dimensions)."""
    import gmsh

    chemin = dossier / "piece.step"
    chemin.write_bytes(step)
    gmsh.initialize(readConfigFiles=False, interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.occ.importShapes(str(chemin))
        gmsh.model.occ.synchronize()
        if not gmsh.model.getEntities(3):
            raise ErreurOutil("Le fichier STEP ne contient pas de volume plein.")
        xmin, ymin, zmin, xmax, ymax, zmax = gmsh.model.getBoundingBox(-1, -1)
        dimensions = (xmax - xmin, ymax - ymin, zmax - zmin)
        if taille is None:
            taille = max(max(dimensions) / 60.0, sorted(dimensions)[0] / 4.0)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", taille)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin", taille / 4.0)
        gmsh.option.setNumber("Mesh.ElementOrder", 2)
        gmsh.option.setNumber("Mesh.HighOrderOptimize", 1)
        gmsh.model.mesh.generate(3)
        etiquettes, coordonnees, _ = gmsh.model.mesh.getNodes()
        noeuds = {int(e): (float(coordonnees[3 * i]), float(coordonnees[3 * i + 1]), float(coordonnees[3 * i + 2]))
                  for i, e in enumerate(etiquettes)}
        _, connectivite = gmsh.model.mesh.getElementsByType(11)  # tétraèdre à 10 nœuds
        elements = [[int(n) for n in connectivite[i:i + 10]] for i in range(0, len(connectivite), 10)]
    finally:
        gmsh.finalize()
    if not elements:
        raise ErreurOutil("Le maillage de la pièce a échoué.")
    # gmsh et CalculiX numérotent différemment les deux derniers nœuds de milieu d'arête.
    for e in elements:
        e[8], e[9] = e[9], e[8]
    return noeuds, elements, (xmin, ymin, zmin, xmax, ymax, zmax), taille


def _von_mises(s) -> float:
    sxx, syy, szz, sxy, sxz, syz = s
    return math.sqrt(0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2) + 3.0 * (sxy**2 + sxz**2 + syz**2))


class OutilStructure(Outil):
    identifiant = "structure"
    nom = "Résistance d'une pièce"
    logiciel = "gmsh et CalculiX"
    role = "Calcule contraintes et déformation d'une pièce encastrée d'un côté et chargée de l'autre."
    schema = {
        "type": "object",
        "properties": {
            "step": {"type": "string", "description": "Contenu du fichier STEP de la pièce (texte), cotes en mm."},
            "matiere": {"type": "string", "enum": list(MATIERES), "description": "Matière homogène de la pièce."},
            "axe": {"type": "string", "enum": ["x", "y", "z"],
                    "description": "Axe le long duquel la pièce est tenue à un bout et chargée à l'autre."},
            "force_n": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                        "description": "Force totale appliquée à l'extrémité libre, en N : [Fx, Fy, Fz]."},
            "module_young_mpa": {"type": "number", "description": "Remplace la valeur de la matière."},
            "taille_maille_mm": {"type": "number"},
        },
        "required": ["step", "axe", "force_n"],
    }

    def _solveur(self) -> str | None:
        return shutil.which("ccx") or shutil.which("ccx_2.21") or shutil.which("ccx_2.20")

    def disponible(self) -> bool:
        try:
            import gmsh  # noqa: F401
        except Exception:
            return False
        return self._solveur() is not None

    def etat(self) -> str:
        try:
            import gmsh

            mailleur = f"gmsh {gmsh.__version__}"
        except Exception:
            return "gmsh non installé (pip install gmsh)"
        if self._solveur() is None:
            return f"{mailleur} ; CalculiX non installé (paquet calculix-ccx)"
        return f"{mailleur} et CalculiX"

    def executer(self, step, axe: str, force_n, matiere: str = "acier", module_young_mpa: float | None = None,
                 taille_maille_mm: float | None = None, duree_max: int = 300) -> Resultat:
        self.exiger()
        if axe not in AXES:
            raise ErreurOutil("L'axe doit être x, y ou z.")
        if matiere not in MATIERES:
            raise ErreurOutil(f"Matière inconnue : {matiere}. Choix : {', '.join(MATIERES)}.")
        force = [float(f) for f in force_n]
        if len(force) != 3 or not any(force):
            raise ErreurOutil("La force doit avoir trois composantes, dont au moins une non nulle.")
        young, poisson, limite = MATIERES[matiere]
        young = float(module_young_mpa or young)
        if isinstance(step, str):
            step = step.encode("utf-8")

        with tempfile.TemporaryDirectory(prefix="yame-ef-") as nom_dossier:
            dossier = Path(nom_dossier)
            noeuds, elements, boite, taille = _mailler(step, taille_maille_mm, dossier)
            i = AXES[axe]
            bas, haut = boite[i], boite[i + 3]
            longueur = haut - bas
            tolerance = max(1e-6 * longueur, 1e-4)
            fixes = [n for n, c in noeuds.items() if c[i] <= bas + tolerance]
            charges = [n for n, c in noeuds.items() if c[i] >= haut - tolerance]
            if not fixes or not charges:
                raise ErreurOutil("Impossible de trouver les deux extrémités de la pièce le long de cet axe.")

            lignes = ["*NODE, NSET=NTOUS"]
            lignes += [f"{n}, {c[0]:.6f}, {c[1]:.6f}, {c[2]:.6f}" for n, c in noeuds.items()]
            lignes.append("*ELEMENT, TYPE=C3D10, ELSET=ETOUS")
            lignes += [f"{k}, " + ", ".join(str(n) for n in e) for k, e in enumerate(elements, start=1)]

            def groupe(nom, membres):
                bloc = [f"*NSET, NSET={nom}"]
                bloc += [", ".join(str(n) for n in membres[k:k + 10]) for k in range(0, len(membres), 10)]
                return bloc

            lignes += groupe("NFIXE", fixes) + groupe("NCHARGE", charges)
            lignes += [
                "*MATERIAL, NAME=MATIERE", "*ELASTIC", f"{young}, {poisson}",
                "*SOLID SECTION, ELSET=ETOUS, MATERIAL=MATIERE",
                "*STEP", "*STATIC", "*BOUNDARY", "NFIXE, 1, 3", "*CLOAD",
            ]
            lignes += [f"NCHARGE, {d + 1}, {force[d] / len(charges):.9e}" for d in range(3) if force[d]]
            lignes += ["*NODE PRINT, NSET=NTOUS", "U", "*EL PRINT, ELSET=ETOUS", "S", "*END STEP"]
            (dossier / "calcul.inp").write_text("\n".join(lignes) + "\n")

            try:
                execution = subprocess.run([self._solveur(), "calcul"], cwd=dossier, capture_output=True,
                                           text=True, timeout=duree_max)
            except subprocess.TimeoutExpired:
                raise ErreurOutil("Le calcul a dépassé la durée maximale. Piste : augmenter la taille de maille.") from None
            resultats = dossier / "calcul.dat"
            if execution.returncode != 0 or not resultats.exists() or resultats.stat().st_size == 0:
                raise ErreurOutil("CalculiX a échoué :\n" + (execution.stdout + execution.stderr)[-1500:])

            deplacement_max, contraintes = 0.0, {}
            bloc = None
            for ligne in resultats.read_text().splitlines():
                if "displacements" in ligne:
                    bloc = "u"
                    continue
                if "stresses" in ligne:
                    bloc = "s"
                    continue
                champs = ligne.split()
                if bloc == "u" and len(champs) == 4:
                    deplacement_max = max(deplacement_max, math.sqrt(sum(float(v) ** 2 for v in champs[1:])))
                elif bloc == "s" and len(champs) == 8:
                    numero = int(champs[0])
                    contraintes[numero] = max(contraintes.get(numero, 0.0), _von_mises([float(v) for v in champs[2:]]))

        if not contraintes:
            raise ErreurOutil("Aucune contrainte lue dans les résultats de CalculiX.")
        marge = 0.10 * longueur
        hors_appuis = []
        for numero, valeur in contraintes.items():
            centre = sum(noeuds[n][i] for n in elements[numero - 1][:4]) / 4.0
            if bas + marge <= centre <= haut - marge:
                hors_appuis.append(valeur)
        contrainte = max(hors_appuis) if hors_appuis else max(contraintes.values())
        return Resultat({
            "contrainte_max_mpa": contrainte,
            "contrainte_max_aux_appuis_mpa": max(contraintes.values()),
            "deplacement_max_mm": deplacement_max,
            "limite_elastique_indicative_mpa": limite,
            "coefficient_de_securite": limite / contrainte if contrainte > 0 else float("inf"),
            "longueur_mm": longueur,
            "noeuds": len(noeuds),
            "elements": len(elements),
            "taille_maille_mm": taille,
            "matiere": matiere,
            "module_young_mpa": young,
        })


enregistrer(OutilStructure())
