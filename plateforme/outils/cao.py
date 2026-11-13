"""CAO paramétrique : exécute un script CadQuery et rend la pièce.

CadQuery repose sur OpenCascade, le noyau géométrique de FreeCAD. Un script
décrit la pièce par ses cotes ; il doit ranger la forme finale dans une
variable nommée `resultat`. L'outil rend le volume, la masse, l'encombrement,
et les fichiers STEP (pour tout logiciel de CAO) et STL (impression 3D,
maillage).
"""

from __future__ import annotations

import json

from . import ErreurOutil, Outil, Resultat, enregistrer
from .bac_a_sable import executer

SUITE = r'''
import json as _json
import cadquery as _cq
_forme = resultat.val() if isinstance(resultat, _cq.Workplane) else resultat
if isinstance(resultat, _cq.Workplane) and len(resultat.vals()) > 1:
    _forme = resultat.combine().val()
_cq.exporters.export(_cq.Workplane(obj=_forme), "piece.step")
_cq.exporters.export(_cq.Workplane(obj=_forme), "piece.stl", tolerance=0.05, angularTolerance=0.2)
_b = _forme.BoundingBox()
print("::YAME::" + _json.dumps({
    "volume_mm3": _forme.Volume(),
    "surface_mm2": _forme.Area(),
    "dimensions_mm": [_b.xlen, _b.ylen, _b.zlen],
    "centre_de_masse_mm": list(_forme.Center().toTuple()),
}))
'''


class OutilCAO(Outil):
    identifiant = "cao"
    nom = "CAO paramétrique"
    logiciel = "CadQuery (noyau OpenCascade, celui de FreeCAD)"
    role = "Dessine une pièce à partir d'un script et de ses cotes ; rend STEP, STL, volume et masse."
    schema = {
        "type": "object",
        "properties": {
            "script": {
                "type": "string",
                "description": "Script Python CadQuery (import cadquery as cq). Cotes en millimètres. "
                               "La forme finale doit être rangée dans la variable `resultat`.",
            },
            "densite_kg_m3": {"type": "number", "description": "Masse volumique de la matière, pour la masse."},
        },
        "required": ["script"],
    }

    def disponible(self) -> bool:
        try:
            import cadquery  # noqa: F401
        except Exception:
            return False
        return True

    def etat(self) -> str:
        if not self.disponible():
            return "non installé (pip install cadquery)"
        import cadquery

        return f"CadQuery {cadquery.__version__}"

    def executer(self, script: str, densite_kg_m3: float | None = None, duree_max: int = 120) -> Resultat:
        self.exiger()
        sortie = executer(script + "\n" + SUITE, duree_max=duree_max)
        ligne = next((l for l in sortie.sortie.splitlines() if l.startswith("::YAME::")), None)
        if not sortie.reussi or ligne is None:
            raise ErreurOutil("Le script de CAO a échoué.\n" + sortie.resume(3000))
        donnees = json.loads(ligne[len("::YAME::"):])
        donnees["volume_cm3"] = donnees["volume_mm3"] / 1000.0
        if densite_kg_m3:
            donnees["masse_kg"] = donnees["volume_mm3"] * 1e-9 * densite_kg_m3
        fichiers = {n: c for n, c in sortie.fichiers.items() if n in ("piece.step", "piece.stl")}
        return Resultat(donnees, fichiers)


enregistrer(OutilCAO())
