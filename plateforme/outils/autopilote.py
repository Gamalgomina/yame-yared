"""Réglages de départ et mission pour l'autopilote ArduPilot (ArduPlane).

ArduPilot est le logiciel qui vole dans le drone : la plateforme ne le
remplace pas. Cet outil traduit le résultat du dimensionnement en :
- un fichier de réglages (.param) à charger dans Mission Planner ou
  QGroundControl ;
- un fichier de mission (.waypoints) : décollage, attente sur zone, retour.

Les noms de réglages ont été vérifiés dans le code source d'ArduPlane
(branche principale, novembre 2026). Les versions anciennes (avant 4.5)
utilisent d'autres noms pour les vitesses.

Ce sont des valeurs de départ. Elles ne remplacent ni le réglage en vol, ni
les essais au sol du plan de prototypage. Le vol simulé (SITL) n'est pas
encore embarqué.
"""

from __future__ import annotations

import math

from . import ErreurOutil, Outil, Resultat, enregistrer

G = 9.80665

# Réglages dont le nom a été vérifié dans le code source d'ArduPlane.
REGLAGES_VERIFIES = {
    "AIRSPEED_STALL", "AIRSPEED_MIN", "AIRSPEED_CRUISE", "AIRSPEED_MAX", "STALL_PREVENTION",
    "THR_MAX", "TRIM_THROTTLE", "ROLL_LIMIT_DEG", "PTCH_LIM_MAX_DEG", "PTCH_LIM_MIN_DEG",
    "WP_RADIUS", "WP_LOITER_RAD", "RTL_ALTITUDE", "RTL_RADIUS", "FS_SHORT_ACTN", "FS_LONG_ACTN",
    "FS_LONG_TIMEOUT", "TECS_CLMB_MAX", "TECS_SINK_MIN", "TECS_SINK_MAX",
    "BATT_MONITOR", "BATT_CAPACITY", "BATT_LOW_VOLT", "BATT_CRT_VOLT",
    "Q_ENABLE", "Q_FRAME_CLASS", "Q_FRAME_TYPE", "Q_ASSIST_SPEED", "Q_TRANSITION_MS", "Q_RTL_MODE", "Q_RTL_ALT",
}

# Commandes de mission (MAVLink)
POINT, ATTENTE_DUREE, RETOUR, DECOLLAGE, DECOLLAGE_VERTICAL = 16, 19, 20, 22, 84


def reglages(vitesse_decrochage_m_s: float, vitesse_croisiere_m_s: float, hauteur_de_vol_m: float,
             decollage_vertical: bool = True, taux_de_montee_m_s: float = 2.0, part_gaz_croisiere: float = 0.45,
             capacite_batterie_mah: float | None = None, elements_batterie: int | None = None,
             finesse: float = 10.0) -> list:
    """Liste de (nom, valeur, explication)."""
    vs, vc = vitesse_decrochage_m_s, vitesse_croisiere_m_s
    if not 0 < vs < vc:
        raise ErreurOutil("La vitesse de croisière doit être supérieure à la vitesse de décrochage.")
    v_min = math.ceil(1.15 * vs)
    v_max = math.ceil(max(1.6 * vs, 1.2 * vc))
    inclinaison = 35.0
    rayon_virage = vc**2 / (G * math.tan(math.radians(inclinaison)))
    rayon_attente = math.ceil(1.6 * rayon_virage / 10.0) * 10
    liste = [
        ("AIRSPEED_STALL", round(vs, 1), "vitesse de décrochage calculée, en m/s"),
        ("AIRSPEED_MIN", v_min, "1,15 fois le décrochage"),
        ("AIRSPEED_CRUISE", round(vc, 1), "vitesse de croisière du dimensionnement"),
        ("AIRSPEED_MAX", v_max, "limite haute, à confirmer en vol"),
        ("STALL_PREVENTION", 1, "limite l'inclinaison à basse vitesse"),
        ("THR_MAX", 100, "pleine puissance autorisée"),
        ("TRIM_THROTTLE", int(round(100 * min(max(part_gaz_croisiere, 0.2), 0.9))), "gaz de croisière estimés, en %"),
        ("ROLL_LIMIT_DEG", int(inclinaison), "inclinaison prudente pour un premier prototype"),
        ("PTCH_LIM_MAX_DEG", 20, "assiette maximale à cabrer"),
        ("PTCH_LIM_MIN_DEG", -20, "assiette maximale à piquer"),
        ("TECS_CLMB_MAX", round(taux_de_montee_m_s, 1), "taux de montée du dimensionnement, en m/s"),
        ("TECS_SINK_MIN", round(vc / max(finesse, 3.0), 1), "taux de chute moteur réduit, vitesse / finesse"),
        ("TECS_SINK_MAX", 5.0, "taux de descente maximal demandé"),
        ("WP_RADIUS", int(max(60, math.ceil(rayon_virage / 10.0) * 10)), "rayon de validation d'un point, en m"),
        ("WP_LOITER_RAD", int(rayon_attente), f"1,6 fois le rayon de virage à {int(inclinaison)}°, en m"),
        ("RTL_ALTITUDE", int(round(hauteur_de_vol_m)), "retour à la hauteur de vol, en m"),
        ("RTL_RADIUS", int(rayon_attente), "rayon d'attente au retour, en m"),
        ("FS_SHORT_ACTN", 0, "perte de liaison courte : attente en cercle"),
        ("FS_LONG_ACTN", 1, "perte de liaison longue : retour au point de départ"),
        ("FS_LONG_TIMEOUT", 20, "délai avant le retour, en s"),
    ]
    if capacite_batterie_mah:
        liste += [("BATT_MONITOR", 4, "mesure de tension et de courant"),
                  ("BATT_CAPACITY", int(round(capacite_batterie_mah)), "capacité de la batterie, en mAh")]
        if elements_batterie:
            liste += [("BATT_LOW_VOLT", round(3.6 * elements_batterie, 1), "alerte : 3,6 V par élément"),
                      ("BATT_CRT_VOLT", round(3.4 * elements_batterie, 1), "critique : 3,4 V par élément")]
    if decollage_vertical:
        liste += [
            ("Q_ENABLE", 1, "active le décollage vertical (redémarrer l'autopilote ensuite)"),
            ("Q_FRAME_CLASS", 1, "quatre rotors"),
            ("Q_FRAME_TYPE", 1, "disposition en X : à vérifier selon la position et le sens de vos moteurs"),
            ("Q_ASSIST_SPEED", v_min - 3, "les rotors aident en dessous de cette vitesse (3 m/s sous le minimum)"),
            ("Q_TRANSITION_MS", 5000, "durée de la transition, en ms"),
            ("Q_RTL_MODE", 1, "retour en avion puis atterrissage vertical"),
            ("Q_RTL_ALT", 20, "hauteur d'approche de l'atterrissage vertical, en m"),
        ]
    inconnus = [nom for nom, _, _ in liste if nom not in REGLAGES_VERIFIES]
    if inconnus:  # garde-fou de développement : jamais de nom non vérifié dans un fichier
        raise ErreurOutil(f"Réglages non vérifiés : {', '.join(inconnus)}")
    return liste


def fichier_reglages(liste: list, titre: str = "") -> str:
    lignes = [
        "# Réglages de départ ArduPlane générés par YAME" + (f" - {titre}" if titre else ""),
        "# Valeurs de départ issues d'un avant-projet non validé : à vérifier une par une.",
        "# Ne remplace ni le réglage en vol ni les essais au sol du plan de prototypage.",
        "# Noms valables pour ArduPlane 4.5 et suivants.",
    ]
    for nom, valeur, explication in liste:
        lignes.append(f"# {explication}")
        lignes.append(f"{nom},{valeur}")
    return "\n".join(lignes) + "\n"


def mission(latitude: float, longitude: float, hauteur_de_vol_m: float, duree_attente_min: float,
            distance_zone_m: float = 1500.0, cap_deg: float = 0.0, decollage_vertical: bool = True) -> str:
    """Mission simple au format « QGC WPL 110 » : décollage, attente sur zone, retour."""
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ErreurOutil("Latitude ou longitude invalide.")
    d_lat = distance_zone_m * math.cos(math.radians(cap_deg)) / 111320.0
    d_lon = distance_zone_m * math.sin(math.radians(cap_deg)) / (111320.0 * max(math.cos(math.radians(latitude)), 0.01))
    zone = (latitude + d_lat, longitude + d_lon)
    h = float(hauteur_de_vol_m)
    hauteur_decollage = 30.0 if decollage_vertical else min(h, 60.0)
    # (commande, p1, p2, p3, p4, latitude, longitude, hauteur)
    points = [
        (POINT, 0, 0, 0, 0, latitude, longitude, 0.0),  # point de départ
        # Décollage sur place : vertical, ou classique avec 12° d'assiette.
        (DECOLLAGE_VERTICAL if decollage_vertical else DECOLLAGE, 0 if decollage_vertical else 12,
         0, 0, 0, 0.0, 0.0, hauteur_decollage),
        (POINT, 0, 0, 0, 0, zone[0], zone[1], h),
        (ATTENTE_DUREE, round(duree_attente_min * 60.0), 0, 0, 0, zone[0], zone[1], h),
        # Retour au départ. Avec Q_RTL_MODE = 1, il se termine par un atterrissage vertical.
        # Sans décollage vertical, l'avion attend en cercle : l'atterrissage reste à programmer
        # selon le terrain, ou à faire en pilotage manuel.
        (RETOUR, 0, 0, 0, 0, 0.0, 0.0, 0.0),
    ]
    lignes = ["QGC WPL 110"]
    for i, (commande, p1, p2, p3, p4, lat, lon, alt) in enumerate(points):
        repere = 0 if i == 0 else 3  # 0 : altitude absolue (départ) ; 3 : hauteur au-dessus du départ
        lignes.append("\t".join(str(v) for v in (
            i, 1 if i == 0 else 0, repere, commande, p1, p2, p3, p4, f"{lat:.7f}", f"{lon:.7f}", f"{alt:.1f}", 1)))
    return "\n".join(lignes) + "\n"


class OutilAutopilote(Outil):
    identifiant = "autopilote"
    nom = "Réglages de l'autopilote"
    logiciel = "ArduPilot (ArduPlane)"
    role = "Produit le fichier de réglages de départ et une mission simple pour un avion, avec ou sans décollage vertical."
    schema = {
        "type": "object",
        "properties": {
            "vitesse_decrochage_m_s": {"type": "number"},
            "vitesse_croisiere_m_s": {"type": "number"},
            "hauteur_de_vol_m": {"type": "number"},
            "decollage_vertical": {"type": "boolean"},
            "taux_de_montee_m_s": {"type": "number"},
            "part_gaz_croisiere": {"type": "number", "description": "Puissance de croisière / puissance maximale."},
            "capacite_batterie_mah": {"type": "number"},
            "elements_batterie": {"type": "integer", "description": "Nombre d'éléments en série."},
            "finesse": {"type": "number"},
            "latitude": {"type": "number", "description": "Avec la longitude : produit aussi une mission."},
            "longitude": {"type": "number"},
            "duree_attente_min": {"type": "number", "description": "Durée de l'attente sur zone dans la mission."},
            "distance_zone_m": {"type": "number"},
            "cap_deg": {"type": "number", "description": "Direction de la zone depuis le départ (0 = nord)."},
        },
        "required": ["vitesse_decrochage_m_s", "vitesse_croisiere_m_s", "hauteur_de_vol_m"],
    }

    def etat(self) -> str:
        return "intégré : génération des fichiers de réglages et de mission"

    def executer(self, vitesse_decrochage_m_s: float, vitesse_croisiere_m_s: float, hauteur_de_vol_m: float,
                 decollage_vertical: bool = True, taux_de_montee_m_s: float = 2.0, part_gaz_croisiere: float = 0.45,
                 capacite_batterie_mah: float | None = None, elements_batterie: int | None = None,
                 finesse: float = 10.0, latitude: float | None = None, longitude: float | None = None,
                 duree_attente_min: float = 30.0, distance_zone_m: float = 1500.0, cap_deg: float = 0.0,
                 titre: str = "") -> Resultat:
        liste = reglages(vitesse_decrochage_m_s, vitesse_croisiere_m_s, hauteur_de_vol_m, decollage_vertical,
                         taux_de_montee_m_s, part_gaz_croisiere, capacite_batterie_mah, elements_batterie, finesse)
        fichiers = {"reglages_arduplane.param": fichier_reglages(liste, titre).encode("utf-8")}
        if latitude is not None and longitude is not None:
            fichiers["mission.waypoints"] = mission(
                latitude, longitude, hauteur_de_vol_m, duree_attente_min, distance_zone_m, cap_deg, decollage_vertical
            ).encode("utf-8")
        return Resultat({"reglages": [{"nom": n, "valeur": v, "explication": e} for n, v, e in liste]}, fichiers)


enregistrer(OutilAutopilote())
