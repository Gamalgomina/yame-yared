# Mettre la plateforme en ligne

La plateforme se déploie avec Docker sur n'importe quel serveur Linux (serveur loué, machine du
bureau, etc.). Avec tous les logiciels embarqués, comptez 4 Go de mémoire, 15 Go de disque, et une
première construction de 30 à 60 minutes (elle compile ArduPilot).

> L'image Docker n'a pas pu être construite dans l'environnement où ce code a été écrit. Les fichiers
> suivent les pratiques courantes, mais le premier `docker compose up` est à considérer comme un essai.

## 1. Préparer le serveur

Installer Docker (https://docs.docker.com/engine/install/), puis récupérer le code :

```
git clone https://github.com/Gamalgomina/yame-yared.git
cd yame-yared
```

## 2. Choisir l'identifiant et le mot de passe

```
cp .env.example .env
```

Ouvrir `.env` et renseigner `YAME_MOT_DE_PASSE` avec un mot de passe long. L'application refuse de
démarrer s'il est vide. Ce fichier reste sur le serveur : il n'est jamais envoyé sur GitHub.

## 3. Démarrer

### Accès depuis le serveur lui-même ou un réseau privé

```
docker compose up -d --build
```

L'application répond sur `http://127.0.0.1:8000`, uniquement depuis le serveur.

### Accès depuis Internet, en HTTPS

Il faut un nom de domaine qui pointe vers le serveur, et les ports 80 et 443 ouverts.
Renseigner `YAME_DOMAINE` dans `.env` (par exemple `yame.exemple.tg`), puis :

```
docker compose --profile https up -d --build
```

Le certificat HTTPS est obtenu et renouvelé automatiquement.

**N'exposez jamais l'application sur Internet sans HTTPS** : le mot de passe circulerait en clair.

## 4. Vérifier

```
docker compose ps
curl http://127.0.0.1:8000/sante
```

La seconde commande doit répondre `{"etat":"ok",...}`.

## Mettre à jour

```
git pull
docker compose up -d --build
```

Les études sont conservées : elles sont dans un volume Docker séparé du code.

## Sauvegarder les études

Toutes les études et l'avancement des prototypages tiennent dans un seul fichier, `yame.db`.

```
docker compose cp yame:/donnees/yame.db sauvegarde-yame.db
```

Faites-le régulièrement et gardez une copie ailleurs que sur le serveur.

## Activer l'agent IA

1. Créer une clé d'API sur https://console.anthropic.com (compte payant, facturé à l'usage).
2. La mettre dans `.env`, ligne `YAME_IA_CLE=`. Elle reste sur le serveur.
3. Redémarrer : `docker compose up -d`.

Réglages facultatifs dans `.env` :

- `YAME_IA_MODELE` : modèle utilisé (défaut : `claude-sonnet-5-5`).
- `YAME_IA_TOURS_MAX` : nombre maximal d'allers-retours par travail (défaut : 40). C'est la borne de coût
  d'un travail. Fixez aussi un plafond de dépense mensuel dans la console Anthropic.
- `YAME_IA_RECHERCHE_WEB` : mettre `web_search_20250305` pour que l'agent puisse chercher sur le web
  (facturé en plus). Laisser vide pour le désactiver.

### Précautions

L'agent écrit et exécute du code sur le serveur. Trois règles :

- **Ne donnez l'accès à la plateforme qu'à des personnes de confiance.** Toute personne connectée peut
  faire exécuter du code par l'agent.
- **Gardez la plateforme dans son conteneur Docker**, sur un serveur qui ne contient rien d'autre de
  sensible. Le bac à sable de calcul n'isole ni le réseau ni le disque : c'est le conteneur qui protège
  le reste du serveur.
- **Relisez tout module proposé avant de le valider.** Un module validé tourne avec les droits de la
  plateforme. Si vous ne lisez pas le Python, faites-le relire.

Avec la recherche web, l'agent lit des pages que personne n'a contrôlées. Il a pour consigne de ne pas
obéir à ce qu'elles contiennent, mais ce risque ne peut pas être ramené à zéro : raison de plus pour
relire ses propositions.

Les demandes et les résultats envoyés à l'agent passent par le service d'IA d'Anthropic. N'y mettez pas
d'information que vous ne voulez pas voir sortir du serveur.

## Si la construction de l'image échoue ou est trop lourde

Deux options réduisent l'image. Remplacer dans `docker-compose.yml` la ligne `build: .` par :

```yaml
    build:
      context: .
      args:
        SIMULATEUR: "0"         # ne compile pas ArduPilot
        LOGICIELS_LOURDS: "0"   # n'installe ni OpenFOAM ni KiCad
```

La plateforme signale alors ces logiciels comme « non installés » et fonctionne sans eux.

## Sans Docker

```
pip install ".[cao,calcul]"
export YAME_MOT_DE_PASSE="un mot de passe long"
export YAME_EXIGER_MOT_DE_PASSE=1
export YAME_DONNEES=/chemin/vers/les/donnees
python -m plateforme serveur --hote 127.0.0.1 --port 8000
```

Placez un serveur HTTPS (Caddy, nginx) devant pour tout accès distant.

## Réglages

| Variable | Rôle | Défaut |
|---|---|---|
| `YAME_UTILISATEUR` | Identifiant de connexion | `yame` |
| `YAME_MOT_DE_PASSE` | Mot de passe | vide |
| `YAME_EXIGER_MOT_DE_PASSE` | `1` : refuse de démarrer sans mot de passe | `1` dans l'image Docker |
| `YAME_DONNEES` | Dossier de la base de données | `donnees` (`/donnees` dans l'image) |
| `YAME_DOMAINE` | Nom de domaine pour le HTTPS automatique | vide |
| `YAME_IA_CLE` | Clé d'API de l'agent IA | vide (agent désactivé) |
| `YAME_IA_MODELE` | Modèle d'IA | `claude-sonnet-5-5` |
| `YAME_IA_TOURS_MAX` | Allers-retours maximaux par travail | `40` |
| `YAME_IA_RECHERCHE_WEB` | Type d'outil de recherche web | vide (désactivée) |
| `YAME_SITL` | Chemin du simulateur ArduPlane | `/opt/sitl/arduplane` dans l'image |
