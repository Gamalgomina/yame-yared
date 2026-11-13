# Mettre la plateforme en ligne

La plateforme se déploie avec Docker sur n'importe quel serveur Linux (serveur loué, machine du
bureau, etc.). Comptez 1 Go de mémoire et 3 Go de disque.

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

## Si la construction de l'image échoue

La bibliothèque de CAO (fichiers STEP) est la partie la plus lourde. Pour s'en passer, remplacer
dans `docker-compose.yml` la ligne `build: .` par :

```yaml
    build:
      context: .
      args:
        AVEC_CAO: "0"
```

La plateforme fonctionne alors normalement, sans les fichiers STEP dans les dossiers.

## Sans Docker

```
pip install ".[cao]"
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
