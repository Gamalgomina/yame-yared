"""Logiciels embarqués sans recette intégrée.

Ces logiciels sont installés sur le serveur et vérifiés par un essai réel,
mais la plateforme n'a pas encore de calcul tout fait qui s'en sert. Ils sont
à la disposition de l'agent IA, qui les pilote depuis `executer_python`
(avec `subprocess`), comme le ferait un ingénieur en ligne de commande.

`executer()` lance l'essai de fonctionnement et rend le mode d'emploi.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import ErreurOutil, Outil, Resultat, enregistrer

DOSSIER_OPENFOAM = "/usr/share/openfoam"


def _lancer(commande: list, dossier: str | None = None, duree: int = 120, env: dict | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(commande, cwd=dossier, capture_output=True, text=True, timeout=duree,
                              env={**os.environ, **(env or {})}, errors="replace")
    except subprocess.TimeoutExpired:
        raise ErreurOutil(f"{commande[0]} n'a pas répondu en {duree} s.") from None
    except OSError as erreur:
        raise ErreurOutil(f"{commande[0]} n'a pas pu être lancé : {erreur}") from None


class OutilLibre(Outil):
    schema = {"type": "object", "properties": {}}
    commande = ""  # exécutable recherché
    mode_d_emploi = ""

    def chemin(self) -> str | None:
        return shutil.which(self.commande)

    def disponible(self) -> bool:
        return self.chemin() is not None

    def essai(self) -> dict:
        raise NotImplementedError

    def executer(self) -> Resultat:
        self.exiger()
        return Resultat({"essai_de_fonctionnement": self.essai(), "mode_d_emploi": self.mode_d_emploi})


# --- OpenFOAM : mécanique des fluides -------------------------------------------

_ENTETE = "FoamFile { version 2.0; format ascii; class %s; object %s; }\n"
_CAS_ESSAI = {
    "system/blockMeshDict": ("dictionary", """convertToMeters 0.1;
vertices ((0 0 0) (1 0 0) (1 1 0) (0 1 0) (0 0 0.1) (1 0 0.1) (1 1 0.1) (0 1 0.1));
blocks (hex (0 1 2 3 4 5 6 7) (20 20 1) simpleGrading (1 1 1));
edges ();
boundary
(
    movingWall { type wall; faces ((3 7 6 2)); }
    fixedWalls { type wall; faces ((0 4 7 3) (2 6 5 1) (1 5 4 0)); }
    frontAndBack { type empty; faces ((0 3 2 1) (4 5 6 7)); }
);
"""),
    "system/controlDict": ("dictionary", """application icoFoam; startFrom startTime; startTime 0; stopAt endTime;
endTime 0.1; deltaT 0.005; writeControl timeStep; writeInterval 20; purgeWrite 0; writeFormat ascii;
writePrecision 6; writeCompression off; timeFormat general; timePrecision 6; runTimeModifiable true;
"""),
    "system/fvSchemes": ("dictionary", """ddtSchemes { default Euler; }
gradSchemes { default Gauss linear; }
divSchemes { default none; div(phi,U) Gauss linear; }
laplacianSchemes { default Gauss linear orthogonal; }
interpolationSchemes { default linear; }
snGradSchemes { default orthogonal; }
"""),
    "system/fvSolution": ("dictionary", """solvers
{
    p { solver PCG; preconditioner DIC; tolerance 1e-06; relTol 0.05; }
    pFinal { $p; relTol 0; }
    U { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-05; relTol 0; }
}
PISO { nCorrectors 2; nNonOrthogonalCorrectors 0; pRefCell 0; pRefValue 0; }
"""),
    "constant/transportProperties": ("dictionary", "nu [0 2 -1 0 0 0 0] 0.01;\n"),
    "0/U": ("volVectorField", """dimensions [0 1 -1 0 0 0 0];
internalField uniform (0 0 0);
boundaryField { movingWall { type fixedValue; value uniform (1 0 0); } fixedWalls { type noSlip; } frontAndBack { type empty; } }
"""),
    "0/p": ("volScalarField", """dimensions [0 2 -2 0 0 0 0];
internalField uniform 0;
boundaryField { movingWall { type zeroGradient; } fixedWalls { type zeroGradient; } frontAndBack { type empty; } }
"""),
}


class OpenFoam(OutilLibre):
    identifiant = "openfoam"
    nom = "Mécanique des fluides"
    logiciel = "OpenFOAM"
    role = ("Calcule un écoulement en trois dimensions (conduits d'un moteur, refroidissement, traînée d'une forme). "
            "Sans recette intégrée : à piloter par l'agent IA.")
    commande = "icoFoam"
    mode_d_emploi = (
        "Depuis executer_python : écrire un dossier de cas (system/, constant/, 0/), puis lancer avec subprocess "
        "blockMesh ou gmshToFoam pour le maillage, puis un solveur (icoFoam, simpleFoam, rhoSimpleFoam...). "
        f"La variable WM_PROJECT_DIR={DOSSIER_OPENFOAM} est déjà posée. Lire les résultats dans les dossiers de temps "
        "ou avec postProcess. Garder des maillages modestes : 2 cœurs, 120 s par exécution."
    )

    def etat(self) -> str:
        return "OpenFOAM installé" if self.disponible() else "non installé"

    def essai(self) -> dict:
        with tempfile.TemporaryDirectory(prefix="yame-foam-") as dossier:
            for nom, (classe, corps) in _CAS_ESSAI.items():
                chemin = Path(dossier) / nom
                chemin.parent.mkdir(parents=True, exist_ok=True)
                chemin.write_text(_ENTETE % (classe, chemin.name) + corps)
            env = {"WM_PROJECT_DIR": os.environ.get("WM_PROJECT_DIR", DOSSIER_OPENFOAM)}
            maillage = _lancer(["blockMesh"], dossier, 60, env)
            if maillage.returncode != 0:
                raise ErreurOutil("OpenFOAM : le maillage d'essai a échoué.\n" + maillage.stdout[-600:])
            calcul = _lancer(["icoFoam"], dossier, 100, env)
            pas = calcul.stdout.count("\nTime = ")
            if calcul.returncode != 0 or pas == 0:
                raise ErreurOutil("OpenFOAM : le calcul d'essai a échoué.\n" + calcul.stdout[-600:])
            return {"cas": "cavité entraînée, 400 mailles", "pas_de_temps_calcules": pas, "reussi": True}


# --- GetDP : électromagnétisme ----------------------------------------------------

class GetDP(OutilLibre):
    identifiant = "getdp"
    nom = "Électromagnétisme"
    logiciel = "GetDP (avec gmsh)"
    role = ("Calcule le champ magnétique dans un moteur électrique ou une génératrice (couple, saturation). "
            "Sans recette intégrée : à piloter par l'agent IA.")
    commande = "getdp"
    mode_d_emploi = (
        "Depuis executer_python : écrire la géométrie en .geo, mailler avec gmsh (gmsh fichier.geo -2), écrire le "
        "problème en .pro (magnétostatique en potentiel vecteur), puis lancer « getdp fichier.pro -msh fichier.msh "
        "-solve <résolution> -pos <post-traitement> » avec subprocess."
    )

    def etat(self) -> str:
        if not self.disponible():
            return "non installé"
        sortie = _lancer(["getdp", "--version"], duree=20)
        return "GetDP " + ((sortie.stdout + sortie.stderr).strip() or "installé")

    def essai(self) -> dict:
        sortie = _lancer(["getdp", "--version"], duree=20)
        version = (sortie.stdout + sortie.stderr).strip()
        if sortie.returncode != 0 or not version:
            raise ErreurOutil("GetDP ne répond pas.")
        return {"version": version, "reussi": True, "portee": "démarrage du logiciel seulement"}


# --- KiCad : cartes électroniques --------------------------------------------------

class KiCad(OutilLibre):
    identifiant = "kicad"
    nom = "Cartes électroniques"
    logiciel = "KiCad (avec SKiDL)"
    role = ("Décrit un schéma électronique, puis exporte les fichiers de fabrication d'une carte. "
            "Sans recette intégrée : à piloter par l'agent IA.")
    commande = "kicad-cli"
    mode_d_emploi = (
        "Depuis executer_python : décrire le schéma avec la bibliothèque Python skidl (liste de connexions), ou "
        "manipuler une carte avec le module pcbnew ; exporter avec « kicad-cli pcb export gerbers|drill|step » ou "
        "« kicad-cli sch export pdf|netlist ». Le placement et le routage d'une carte restent un travail de dessin : "
        "la plateforme ne route pas une carte toute seule."
    )

    def etat(self) -> str:
        if not self.disponible():
            return "non installé"
        return "KiCad " + (_lancer(["kicad-cli", "version"], duree=30).stdout.strip() or "installé")

    def essai(self) -> dict:
        sortie = _lancer(["kicad-cli", "version"], duree=30)
        if sortie.returncode != 0 or not sortie.stdout.strip():
            raise ErreurOutil("KiCad ne répond pas.")
        return {"version": sortie.stdout.strip(), "reussi": True, "portee": "démarrage du logiciel seulement"}


enregistrer(OpenFoam())
enregistrer(GetDP())
enregistrer(KiCad())
