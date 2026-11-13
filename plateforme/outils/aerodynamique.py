"""Aérodynamique d'un avion : polaire et point d'équilibre.

Embarque AeroSandbox (méthode AeroBuildup) et NeuralFoil pour les profils.
Tient le rôle prévu pour OpenVSP dans le pipeline : calculer portance et
traînée sur la forme réelle (aile, empennage, fuselage) au lieu d'une somme de
coefficients. Ce que la méthode ne voit pas (bras, hélices arrêtées, nacelle,
refroidissement) s'ajoute par une surface de traînée équivalente.
"""

from __future__ import annotations

import math

from . import ErreurOutil, Outil, Resultat, enregistrer

G = 9.80665


def _nombre(x) -> float:
    import numpy

    return float(numpy.ravel(x)[0])


class OutilAerodynamique(Outil):
    identifiant = "aerodynamique"
    nom = "Aérodynamique de l'avion"
    logiciel = "AeroSandbox et NeuralFoil"
    role = "Calcule portance, traînée et finesse sur la forme de l'avion, et le point de vol en palier."
    schema = {
        "type": "object",
        "properties": {
            "envergure_m": {"type": "number"},
            "surface_m2": {"type": "number", "description": "Surface de l'aile."},
            "masse_kg": {"type": "number"},
            "vitesse_m_s": {"type": "number", "description": "Vitesse de vol étudiée."},
            "densite_kg_m3": {"type": "number", "description": "Densité de l'air (1,225 au niveau de la mer)."},
            "profil": {"type": "string", "description": "Profil de l'aile, par exemple naca4412."},
            "effilement": {"type": "number", "description": "Corde en bout / corde à l'emplanture (1 = aile rectangulaire)."},
            "rapport_empennage": {"type": "number", "description": "Surface d'empennage / surface d'aile."},
            "longueur_fuselage_m": {"type": "number"},
            "diametre_fuselage_m": {"type": "number"},
            "trainee_supplementaire_m2": {
                "type": "number",
                "description": "Surface de traînée équivalente de ce qui n'est pas modélisé (bras, hélices arrêtées, nacelle).",
            },
        },
        "required": ["envergure_m", "surface_m2", "masse_kg", "vitesse_m_s"],
    }

    def disponible(self) -> bool:
        try:
            import aerosandbox  # noqa: F401
        except Exception:
            return False
        return True

    def etat(self) -> str:
        if not self.disponible():
            return "non installé (pip install aerosandbox)"
        import aerosandbox

        return f"AeroSandbox {aerosandbox.__version__}"

    def executer(self, envergure_m: float, surface_m2: float, masse_kg: float, vitesse_m_s: float,
                 densite_kg_m3: float = 1.225, profil: str = "naca4412", effilement: float = 1.0,
                 rapport_empennage: float = 0.22, longueur_fuselage_m: float | None = None,
                 diametre_fuselage_m: float | None = None, trainee_supplementaire_m2: float = 0.0) -> Resultat:
        self.exiger()
        import aerosandbox as asb

        if min(envergure_m, surface_m2, masse_kg, vitesse_m_s, densite_kg_m3) <= 0:
            raise ErreurOutil("Envergure, surface, masse, vitesse et densité doivent être supérieures à zéro.")
        try:
            profil_aile = asb.Airfoil(profil)
            if profil_aile.coordinates is None:
                raise ValueError
        except Exception:
            raise ErreurOutil(f"Profil inconnu : {profil}. Exemple de nom valide : naca4412.") from None

        corde_moyenne = surface_m2 / envergure_m
        emplanture = 2.0 * corde_moyenne / (1.0 + effilement)
        bout = emplanture * effilement
        longueur = longueur_fuselage_m or 0.45 * envergure_m
        diametre = diametre_fuselage_m or 0.07 * envergure_m
        bras_de_levier = 0.55 * longueur  # du quart de corde de l'aile à l'empennage

        aile = asb.Wing(name="aile", symmetric=True, xsecs=[
            asb.WingXSec(xyz_le=[0.0, 0.0, 0.0], chord=emplanture, airfoil=profil_aile),
            asb.WingXSec(xyz_le=[0.25 * (emplanture - bout), envergure_m / 2.0, 0.0], chord=bout, airfoil=profil_aile),
        ])
        surfaces = [aile]
        if rapport_empennage > 0:
            symetrique = asb.Airfoil("naca0010")
            s_h = 0.65 * rapport_empennage * surface_m2  # plan horizontal
            s_v = 0.35 * rapport_empennage * surface_m2  # dérive
            b_h = math.sqrt(4.0 * s_h)
            h_v = math.sqrt(1.5 * s_v)
            surfaces.append(asb.Wing(name="plan horizontal", symmetric=True, xsecs=[
                asb.WingXSec(xyz_le=[bras_de_levier, 0.0, 0.0], chord=s_h / b_h, airfoil=symetrique),
                asb.WingXSec(xyz_le=[bras_de_levier, b_h / 2.0, 0.0], chord=s_h / b_h, airfoil=symetrique),
            ]))
            surfaces.append(asb.Wing(name="dérive", symmetric=False, xsecs=[
                asb.WingXSec(xyz_le=[bras_de_levier, 0.0, 0.0], chord=s_v / h_v, airfoil=symetrique),
                asb.WingXSec(xyz_le=[bras_de_levier, 0.0, h_v], chord=s_v / h_v, airfoil=symetrique),
            ]))
        nez = -0.35 * longueur
        fuselage = asb.Fuselage(name="fuselage", xsecs=[
            asb.FuselageXSec(xyz_c=[nez + x * longueur, 0.0, 0.0], radius=max(r * diametre / 2.0, 1e-3))
            for x, r in ((0.0, 0.1), (0.12, 0.85), (0.3, 1.0), (0.6, 1.0), (0.85, 0.5), (1.0, 0.15))
        ])
        avion = asb.Airplane(name="avion", wings=surfaces, fuselages=[fuselage], xyz_ref=[0.25 * emplanture, 0.0, 0.0])

        atmosphere = asb.Atmosphere(altitude=0.0)
        viscosite = atmosphere.dynamic_viscosity()
        # AeroSandbox raisonne en altitude : on impose la densité voulue en volant, au niveau de la
        # mer, à la vitesse qui donne la même pression dynamique. Le nombre de Reynolds du calcul
        # est alors surestimé de quelques pour cent, sans effet sensible sur le résultat.
        pression_dynamique = 0.5 * densite_kg_m3 * vitesse_m_s**2
        vitesse_equivalente = math.sqrt(2.0 * pression_dynamique / 1.225)
        reynolds = densite_kg_m3 * vitesse_m_s * corde_moyenne / _nombre(viscosite)

        polaire = []
        for alpha in range(-4, 19):
            point = asb.OperatingPoint(velocity=vitesse_equivalente, alpha=float(alpha), atmosphere=atmosphere)
            r = asb.AeroBuildup(airplane=avion, op_point=point).run()
            cl = _nombre(r["CL"])
            cd = _nombre(r["CD"]) + trainee_supplementaire_m2 / surface_m2
            polaire.append({"incidence_deg": float(alpha), "cl": cl, "cd": cd, "finesse": cl / cd, "cm": _nombre(r["Cm"])})

        cl_max = max(p["cl"] for p in polaire)
        cl_palier = masse_kg * G / (pression_dynamique * surface_m2)
        croissante = polaire[: max(range(len(polaire)), key=lambda i: polaire[i]["cl"]) + 1]
        equilibre = None
        for a, b in zip(croissante, croissante[1:]):
            if a["cl"] <= cl_palier <= b["cl"]:
                t = (cl_palier - a["cl"]) / (b["cl"] - a["cl"]) if b["cl"] > a["cl"] else 0.0
                equilibre = {k: a[k] + t * (b[k] - a[k]) for k in a}
                break
        donnees = {
            "polaire": polaire,
            "cl_max": cl_max,
            "vitesse_decrochage_m_s": math.sqrt(2.0 * masse_kg * G / (densite_kg_m3 * surface_m2 * cl_max)),
            "finesse_max": max(p["finesse"] for p in polaire),
            "reynolds_aile": reynolds,
            "cl_palier": cl_palier,
            "allongement": envergure_m**2 / surface_m2,
        }
        if equilibre is None:
            donnees["palier"] = None
            donnees["remarque"] = "L'aile ne porte pas cette masse à cette vitesse : elle décroche avant."
        else:
            trainee = pression_dynamique * surface_m2 * equilibre["cd"]
            cd0 = equilibre["cd"] - equilibre["cl"] ** 2 / (math.pi * 0.8 * donnees["allongement"])
            donnees["palier"] = {
                **equilibre,
                "trainee_n": trainee,
                "puissance_de_vol_w": trainee * vitesse_m_s,
                "cd0_equivalent": cd0,
            }
        return Resultat(donnees)


enregistrer(OutilAerodynamique())
