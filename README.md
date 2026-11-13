# YAME / YARED — version 0.2

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
pip install -e ".[dev,cao]"
python -m pytest -q                      # contrôles automatiques
python -m plateforme serveur             # application web sur http://127.0.0.1:8000
```

`cao` est facultatif : sans lui, tout fonctionne sauf les fichiers STEP.

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

## Organisation du code

```
plateforme/
  socle/          modèle commun : questions, hypothèses, étude, plan, nomenclature,
                  dossier de conception, rendu, stockage
  familles/       YAME : un module par famille de matériels
  composants/     YARED : un module par composant
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
- Stabilité et commandes de vol ; simulation de vol.
- Modules YARED pour la génératrice, les contrôleurs de moteur, l'autopilote, la radio, les batteries.
- Recalage automatique à partir des mesures saisies : il se fait à la main, par les réglages experts.
- Comptes utilisateurs multiples : un seul identifiant protège toute l'application.

## Droits

Code privé. Tous droits réservés.
