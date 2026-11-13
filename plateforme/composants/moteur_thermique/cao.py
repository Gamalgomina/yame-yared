"""Export des pièces du moteur en CAO (fichiers STEP).

Formes simplifiées, cotées par le pré-dimensionnement : elles servent de base
de dessin dans FreeCAD ou tout autre logiciel, pas de plans de fabrication.
Nécessite la bibliothèque `cadquery` (facultative). Sans elle, la fonction
renvoie un dictionnaire vide et le reste de la plateforme fonctionne.
"""

from __future__ import annotations

import os
import tempfile


def disponible() -> bool:
    try:
        import cadquery  # noqa: F401
    except Exception:
        return False
    return True


def _step(objet) -> bytes:
    import cadquery as cq

    with tempfile.TemporaryDirectory() as dossier:
        chemin = os.path.join(dossier, "piece.step")
        cq.exporters.export(objet, chemin)
        with open(chemin, "rb") as fichier:
            return fichier.read()


def pieces_step(cotes: dict) -> dict:
    """Renvoie {nom de fichier: contenu STEP} pour les pièces principales."""
    if not disponible():
        return {}
    import cadquery as cq

    c = cotes
    b, h = c["alesage"], c["hauteur_piston"]

    # Piston : cylindre creux par le dessous, perçage d'axe, gorges de segments.
    piston = cq.Workplane("XY").circle(b / 2).extrude(h)
    piston = piston.cut(cq.Workplane("XY").circle(b / 2 - c["jupe"]).extrude(h - c["calotte"]))
    hauteur_axe = h * 0.45
    bossages = (
        cq.Workplane("YZ").workplane(offset=-(b / 2 - c["jupe"])).center(0, hauteur_axe)
        .circle(c["d_axe"] * 0.9).extrude(b - 2 * c["jupe"])
    )
    degagement = cq.Workplane("XY").box(c["portee_pied"] + 2.0, b, h, centered=(True, True, False))
    piston = piston.union(bossages.cut(degagement).intersect(cq.Workplane("XY").circle(b / 2).extrude(h)))
    piston = piston.cut(
        cq.Workplane("YZ").workplane(offset=-b / 2 - 1).center(0, hauteur_axe).circle(c["d_axe"] / 2).extrude(b + 2)
    )
    for i in range(int(c["nb_segments"])):
        z = h - c["calotte"] * 0.6 - c["segment_hauteur"] - i * 2.2 * c["segment_hauteur"]
        gorge = (
            cq.Workplane("XY").workplane(offset=z).circle(b / 2 + 1).circle(b / 2 - c["segment_radial"])
            .extrude(c["segment_hauteur"])
        )
        piston = piston.cut(gorge)

    # Bielle : pied, tête et corps rectangulaire.
    ep = c["bielle_epaisseur"]
    entraxe = c["longueur_bielle"]
    r_pied, r_tete = c["d_axe"] / 2 + 3.0, c["d_maneton"] / 2 + 5.0
    bielle = (
        cq.Workplane("XY").rect(c["bielle_largeur"], entraxe, centered=(True, False)).extrude(ep)
        .union(cq.Workplane("XY").circle(r_tete).extrude(ep))
        .union(cq.Workplane("XY").center(0, entraxe).circle(r_pied).extrude(ep))
        .cut(cq.Workplane("XY").circle(c["d_maneton"] / 2 + 2.0).extrude(ep))
        .cut(cq.Workplane("XY").center(0, entraxe).circle(c["d_axe"] / 2 + 1.0).extrude(ep))
    )

    # Vilebrequin : deux tourillons, deux bras à contrepoids, un maneton.
    rayon = c["course"] / 2
    bras = c["bras_epaisseur"]
    entre_bras = ep + 1.0
    r_bras = rayon + c["d_maneton"] / 2 + 3.0

    def un_bras(z: float):
        disque = cq.Workplane("XY").workplane(offset=z).circle(r_bras).extrude(bras)
        # Allègement côté maneton : le côté opposé reste plein et sert de contrepoids.
        coupe = (
            cq.Workplane("XY").workplane(offset=z).center(rayon + r_bras, 0)
            .rect(2 * r_bras - c["d_maneton"], 2.5 * r_bras).extrude(bras)
        )
        return disque.cut(coupe)

    longueur_tourillon = 1.2 * c["d_tourillon"]
    vilebrequin = (
        cq.Workplane("XY").circle(c["d_tourillon"] / 2).extrude(longueur_tourillon)
        .union(un_bras(longueur_tourillon))
        .union(
            cq.Workplane("XY").workplane(offset=longueur_tourillon + bras).center(rayon, 0)
            .circle(c["d_maneton"] / 2).extrude(entre_bras)
        )
        .union(un_bras(longueur_tourillon + bras + entre_bras))
        .union(
            cq.Workplane("XY").workplane(offset=longueur_tourillon + 2 * bras + entre_bras)
            .circle(c["d_tourillon"] / 2).extrude(longueur_tourillon * 2.0)
        )
    )

    # Cylindre : fût et ailettes annulaires.
    hauteur_cylindre = c["course"] + h + 4.0
    cylindre = cq.Workplane("XY").circle(c["ailette_d_int"] / 2).circle(b / 2).extrude(hauteur_cylindre)
    pas = max(4.0, (hauteur_cylindre - 6.0) / max(int(c["nb_ailettes"]), 1))
    nombre = min(int(c["nb_ailettes"]), int((hauteur_cylindre - 6.0) // pas))
    for i in range(nombre):
        ailette = (
            cq.Workplane("XY").workplane(offset=hauteur_cylindre - 2.0 - (i + 1) * pas)
            .circle(c["ailette_d_ext"] / 2).circle(c["ailette_d_int"] / 2 - 0.2).extrude(1.5)
        )
        cylindre = cylindre.union(ailette)

    return {
        "cao/piston.step": _step(piston),
        "cao/bielle.step": _step(bielle),
        "cao/vilebrequin.step": _step(vilebrequin),
        "cao/cylindre.step": _step(cylindre),
    }
