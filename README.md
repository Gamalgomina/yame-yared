# YAME / YARED — version 0.3

Plateforme de conception de matériels par simulation. On décrit un besoin en quelques réponses ;
la plateforme comble les vides, calcule, et remet un **dossier de conception** avec un **plan de
prototypage pas à pas**.

- **YAME** part d'un besoin et dimensionne un système complet.
- **YARED** conçoit un composant par simulation.

Les deux partagent le même socle. Un composant conçu dans YARED sert à tous les systèmes de YAME :
le moteur thermique équipe aussi bien le drone que le véhicule terrestre.

> **Avant-projet non validé.** Les modèles sont simplifiés et n'ont pas été recalés sur des essais.
> Incertitude de l'ordre de 15 à 25 % sur les masses et les consommations. Aucune pièce ne doit être
> mise en service sur cette seule base : le plan de prototypage impose les essais.

## Modules disponibles

| Outil | Module | Ce qu'il fait |
|---|---|---|
| YAME | `drone-voilure-fixe` | Avion sans pilote à moteur thermique, longue endurance, avec ou sans décollage vertical |
| YAME | `drone-multirotor` | Multirotor électrique pour le vol stationnaire |
| YAME | `vehicule-terrestre` | Petit véhicule de transport, électrique ou thermique |
| YARED | `moteur-thermique` | Monocylindre à essence, 2 ou 4 temps : cycle, cylindrée, consommation, cotes des pièces, fichiers CAO |
| YARED | `helice` | Hélice à pas fixe, croisière ou sustentation : diamètre, pas, rendement, forme de la pale |
| YARED | `moteur-electrique` | Moteur sans balais à rotor extérieur : stator, bobinage, courant, rendement, masse |

Chaque module indique ses propres limites dans le rapport.

## Logiciels embarqués

La plateforme ne réécrit pas les logiciels de calcul : elle les embarque et les pilote. La page
« Logiciels » de l'application indique lesquels sont installés sur le serveur.

| Rôle | Logiciel | Ce que la plateforme en fait |
|---|---|---|
| CAO | CadQuery (noyau OpenCascade, celui de FreeCAD) | Dessine une pièce depuis un script : STEP, STL, volume, masse |
| Aérodynamique | AeroSandbox et NeuralFoil | Portance, traînée, finesse et point de vol sur la forme de l'avion |
| Structure | gmsh et CalculiX | Contraintes et déformation d'une pièce encastrée et chargée |
| Autopilote | ArduPilot | Génère le fichier de réglages de départ et une mission |
| Simulateur de vol | ArduPilot SITL et pymavlink | Démarre le vrai logiciel de vol et vérifie qu'il accepte chaque réglage |
| Mécanique des fluides | OpenFOAM | Installé et essayé ; sans calcul tout fait, piloté par l'agent IA |
| Électromagnétisme | GetDP | Installé ; sans calcul tout fait, piloté par l'agent IA |
| Cartes électroniques | KiCad et SKiDL | Installé ; sans calcul tout fait, piloté par l'agent IA |

Non embarqués : OpenVSP (pas de paquet installable ; AeroSandbox tient ce rôle), OpenWAM et FEMM
(GetDP tient le rôle de FEMM). Le simulateur vérifie les réglages mais ne fait pas encore voler une
mission complète.

## Agent IA et atelier de R&D

Avec une clé d'API (variable `YAME_IA_CLE`), un agent IA travaille dans la plateforme, page « Agent IA » :

- **Piloter une conception** : vous décrivez le besoin en langage libre ; l'agent choisit le module,
  le remplit sans rien inventer, lance l'étude, la vérifie avec les logiciels embarqués et rend compte.
- **Atelier de R&D** : vous demandez un composant ou un matériel que la plateforme ne sait pas faire ;
  l'agent étudie l'état de l'art, écrit un modèle, l'essaie, puis **propose un nouveau module**.

Un module proposé est contrôlé automatiquement (il doit se charger, réussir son propre exemple, fournir
un plan de prototypage et ses limites). Il n'entre dans la plateforme qu'après **relecture et validation
par une personne**. Il reste une hypothèse tant qu'il n'a pas été recalé sur des essais.

L'agent calcule dans un bac à sable : processus séparé, durée limitée, sans la clé d'IA ni le mot de
passe. Ce bac à sable n'isole ni le réseau ni le disque : voir les précautions dans DEPLOIEMENT.md.
L'agent refuse toute demande d'armement.

> L'agent a été vérifié avec un service d'IA simulé. Il n'a pas encore tourné avec une vraie clé :
> le premier travail réel est un essai.

## Ce que remet la plateforme

Pour chaque étude, un dossier de conception (archive zip) :

| Fichier | Contenu |
|---|---|
| `rapport.html` | Chiffres clés, hypothèses (données, déduites, comblées, avec la raison), résultats, limites |
| `plan_de_prototypage.md` | Les étapes à suivre dans l'ordre, avec moyens, consignes de sécurité, critère de réussite et mesures à relever |
| `nomenclature.csv` | La liste des pièces : à fabriquer, à concevoir avec YARED, élément de base à approvisionner |
| `resultats.json` | Tous les chiffres, pour d'autres outils |
| `cao/*.step` | Formes de départ des pièces du moteur, à ouvrir dans FreeCAD |
| `composants/` | Un dossier complet par composant du système |

Dans l'application web, le plan se suit **strictement dans l'ordre** : une étape ne se valide que si la
précédente l'est, en saisissant les mesures demandées et en confirmant le critère de réussite. Les
mesures sont conservées et reportées dans le dossier.

## Démarrer sur votre machine

Il faut Python 3.11 ou plus récent.

```
pip install -e ".[dev,cao,calcul]"
python -m pytest -q                      # contrôles automatiques
python -m plateforme serveur             # application web sur http://127.0.0.1:8000
```

`cao` et `calcul` sont facultatifs : sans eux, les logiciels correspondants sont signalés « non installés »
et le reste fonctionne. CalculiX, GetDP, OpenFOAM et KiCad s'installent avec le gestionnaire de paquets du
système (`apt install calculix-ccx getdp openfoam kicad` sous Ubuntu 24.04).

En ligne de commande :

```
python -m plateforme modules
python -m plateforme etudier missions/drone_voilure_fixe.toml --sortie resultats
```

Pour mettre la plateforme en ligne : voir [DEPLOIEMENT.md](DEPLOIEMENT.md).

## Décrire un besoin

Dans l'application web, un formulaire par module. En ligne de commande, un fichier `.toml`
(exemples dans `missions/`). Seules quelques réponses sont obligatoires ; le reste est comblé et
signalé dans le rapport.

Les familles YAME acceptent des **réglages experts** : n'importe quel paramètre technique du calcul,
par exemple une valeur mesurée sur un prototype. C'est ainsi que l'on recale les modèles :

```toml
[expert]
rendement_helice = 0.70
pen_structure = 1.08
```

## API

L'application expose une API JSON, documentée sur `/docs` :

| Méthode | Adresse | Rôle |
|---|---|---|
| GET | `/api/modules` | Modules et questions |
| POST | `/api/modules/{module}/etudes` | Lancer une étude |
| GET | `/api/etudes` | Liste des études |
| GET | `/api/etudes/{n}` | Une étude et l'avancement de son prototypage |
| GET | `/api/outils` | Logiciels embarqués et leur état |
| POST | `/api/ia/travaux` | Confier un travail à l'agent IA |
| GET | `/api/ia/travaux/{n}` | État, journal et compte rendu d'un travail |

## Organisation du code

```
plateforme/
  socle/          modèle commun : questions, hypothèses, étude, plan, nomenclature,
                  dossier de conception, rendu, stockage
  familles/       YAME : un module par famille de matériels
  composants/     YARED : un module par composant
  outils/         logiciels embarqués et bac à sable de calcul
  ia/             agent IA, atelier de R&D, contrôle des modules proposés
  web/            application web et API
missions/         besoins d'exemple
tests/            contrôles automatiques
```

## Ajouter un matériel ou un composant

1. Créer un fichier dans `plateforme/familles/` ou `plateforme/composants/`.
2. Y écrire une classe qui hérite de `Module` : identifiant, nom, questions, et une méthode `etudier`
   qui renvoie une `Etude` (chiffres, hypothèses, sections, étapes de prototypage, nomenclature, limites).
3. L'enregistrer avec `enregistrer(...)` et l'importer dans le `__init__.py` du dossier.

Le module apparaît alors dans l'application web, l'API et la ligne de commande, sans autre
modification. Un nouveau module n'est fiable qu'après recalage sur de vrais essais.

## Ce que la plateforme ne fait pas encore

- Forme 3D et plans de la cellule d'un drone ou du châssis d'un véhicule ; calcul de résistance.
- Stabilité et commandes de vol ; vol d'une mission complète en simulation.
- Modules YARED pour la génératrice, les contrôleurs de moteur, la radio, les batteries : à demander à
  l'atelier de R&D.
- Calculs tout faits avec OpenFOAM, GetDP et KiCad : ils ne servent qu'à travers l'agent IA.
- Recalage automatique à partir des mesures saisies : il se fait à la main, par les réglages experts.
- Comptes utilisateurs multiples : un seul identifiant protège toute l'application.

## Droits

Code privé. Tous droits réservés.
