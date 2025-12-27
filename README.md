# 🎬 Frenchio - Addon Stremio pour Trackers Français

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![GHCR](https://img.shields.io/badge/ghcr-latest-blue?logo=docker)](https://github.com/aymene69/frenchio/pkgs/container/frenchio)
[![Build](https://img.shields.io/github/actions/workflow/status/aymene69/frenchio/docker-publish.yml?branch=main)](https://github.com/aymene69/frenchio/actions)

**Frenchio** est un addon Stremio puissant qui permet de rechercher et streamer du contenu depuis plusieurs trackers privés/semi-privés français avec support de débridage AllDebrid et streaming direct via qBittorrent.

Suite à la fermeture de YGG aux services de debrid, cet addon permet de continuer à profiter de contenu français de qualité en connectant vos trackers privés préférés directement à Stremio.

## ✨ Fonctionnalités

- 🔍 **Recherche multi-trackers** : UNIT3D, Sharewood, YGGTorrent
- ⚡ **AllDebrid Integration** : Streaming instantané des torrents cachés
- 📥 **qBittorrent Support** : Streaming direct pour les torrents non-cachés
- 🎯 **Sélection intelligente** : Détection automatique des épisodes dans les packs de saisons
- 🌐 **Recherche parallèle** : Requêtes simultanées pour des résultats ultra-rapides
- 🧹 **Auto-cleanup** : Nettoyage automatique des magnets AllDebrid
- 🎨 **Interface moderne** : Page de configuration intuitive
- 🐳 **Docker Ready** : Déploiement en un clic

## 📋 Prérequis

### Services requis

- [TMDB API Key](https://www.themoviedb.org/settings/api) (gratuit)
- **Au moins un tracker parmi** :
  - Trackers **UNIT3D** (avec API Token)
  - [Sharewood](https://www.sharewood.tv/) (Passkey)
  - [YGGTorrent](https://www.ygg.re/) (Passkey via YGGAPI)

### Options de streaming

**Choisissez au moins une option** :

1. **AllDebrid** (recommandé) : [Clé API](https://alldebrid.com/apikeys/) - Streaming instantané des torrents cachés
2. **qBittorrent** : Instance avec WebUI activée - Streaming de tous les torrents

## 🚀 Installation

### Option 1 : Docker (Recommandé)

```bash
# Lancement avec Docker Compose
docker-compose up -d

# Vérifier les logs
docker logs frenchio-addon -f
```

> **Note** : Les images sont disponibles pour **amd64** et **arm64** (Raspberry Pi, Apple Silicon)

L'addon sera accessible sur `http://localhost:7777`

> ⚠️ **IMPORTANT** : Si vous hébergez l'addon sur un serveur distant (pas en localhost), vous **DEVEZ** utiliser **HTTPS**. Stremio refuse les addons HTTP non-localhost pour des raisons de sécurité. Utilisez un reverse proxy (Nginx, Caddy) avec un certificat SSL (Let's Encrypt).

### Option 2 : Installation manuelle

```bash
# Clone le repository
git clone https://github.com/aymene69/frenchio.git
cd frenchio

# Crée un environnement virtuel
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Installe les dépendances
pip install -r requirements.txt

# Lance l'addon
python main.py
```

## ⚙️ Configuration

### 1. Accéder à la page de configuration

Ouvrez votre navigateur sur : `http://localhost:7777/configure`

> ⚠️ Si vous hébergez sur un serveur distant, utilisez `https://votre-domaine.com/configure` (HTTPS obligatoire)

### 2. Remplir vos identifiants

#### TMDB (Obligatoire)
- **TMDB API Key** : Votre clé API v3 de TheMovieDB

#### AllDebrid (Optionnel - Recommandé)
- **AllDebrid API Key** : Votre clé API pour le débridage instantané

#### Trackers UNIT3D (Optionnel)
Ajoutez un ou plusieurs trackers compatibles UNIT3D :
- **URL** : `https://votre-tracker.com` (sans slash final)
- **API Token** : Token d'API personnel depuis les paramètres du tracker

> **Note** : UNIT3D est une plateforme de tracker BitTorrent. De nombreux trackers français utilisent ce logiciel. L'addon est compatible avec tous les trackers basés sur UNIT3D.

#### Sharewood (Optionnel)
- **Passkey** : Votre passkey Sharewood (32 caractères)

#### YGGTorrent (Optionnel)
- **Passkey** : Votre passkey YGG (32 caractères)

> **Note** : Même si YGG a fermé l'accès aux services de debrid, vous pouvez toujours utiliser YGG avec qBittorrent pour le streaming direct.

#### qBittorrent (Optionnel)
Configuration pour le streaming direct :
- **Host** : `http://votre-ip:8080` (WebUI qBittorrent)
- **Username** : Login WebUI
- **Password** : Mot de passe WebUI
- **Public URL** : `http://votre-ip:8000` (pour servir les fichiers)

### 3. Générer et installer

1. Cliquez sur **"Générer le lien d'installation Stremio"**
2. Copiez le lien généré
3. Ouvrez-le dans votre navigateur
4. Stremio détectera automatiquement l'addon

## 🎯 Utilisation

### Recherche de contenu

1. Ouvrez Stremio
2. Recherchez un film ou une série
3. Cliquez sur "Play"
4. Sélectionnez une source **Frenchio**

### Comment ça marche ?

```
Stremio
   ↓
Frenchio (recherche parallèle)
   ├─→ Trackers UNIT3D
   ├─→ Sharewood
   └─→ YGGTorrent
   ↓
Résultats filtrés
   ↓
   ├─→ AllDebrid (si caché) → Stream instantané ⚡
   └─→ qBittorrent (sinon) → Stream pendant le DL 📥
```

**Processus détaillé** :

1. **Conversion IMDB → TMDB** : Récupération des métadonnées
2. **Recherche parallèle** : Tous les trackers interrogés simultanément
3. **Filtrage intelligent** :
   - Vérification de la pertinence (TMDB/IMDB ID)
   - Pour les séries : détection du S##E## dans le nom
   - Pour les packs : exploration des fichiers pour trouver le bon épisode
4. **Débridage/Streaming** :
   - **AllDebrid** : Si le torrent est caché → streaming instantané
   - **qBittorrent** : Sinon → ajout avec téléchargement séquentiel
5. **Nettoyage** : Suppression automatique des magnets temporaires sur AllDebrid

## 🌐 Hébergement distant (HTTPS requis)

Si vous hébergez Frenchio sur un serveur distant (VPS, NAS, etc.), vous **devez** utiliser HTTPS.

### Déploiement avec Traefik

Un exemple `docker-compose.traefik.example.yml` est fourni :

```bash
# 1. Copiez et personnalisez
cp docker-compose.traefik.example.yml docker-compose.yml
# Éditez et remplacez "frenchio.aymene.tech" par votre domaine

# 2. Lancez
docker-compose up -d
```

> **Note** : Nécessite un réseau `traefik_network` existant et Traefik déjà configuré avec Let's Encrypt.

### Déploiement avec Caddy (Alternative)

Un fichier `docker-compose.https.yml` est fourni pour un déploiement HTTPS facile :

```bash
# 1. Copiez et configurez le Caddyfile
cp Caddyfile.example Caddyfile
# Éditez Caddyfile et remplacez "frenchio.votredomaine.com" par votre domaine

# 2. Lancez avec Caddy (gère automatiquement le SSL)
docker-compose -f docker-compose.https.yml up -d
```

Caddy va automatiquement :
- ✅ Obtenir un certificat SSL gratuit (Let's Encrypt)
- ✅ Le renouveler automatiquement
- ✅ Gérer le reverse proxy

### Configuration manuelle avec Nginx

```nginx
server {
    listen 443 ssl http2;
    server_name frenchio.votredomaine.com;

    ssl_certificate /etc/letsencrypt/live/votredomaine.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/votredomaine.com/privkey.pem;

    location / {
        proxy_pass http://localhost:7777;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Avec Caddy (le plus simple)

```
frenchio.votredomaine.com {
    reverse_proxy localhost:7777
}
```

Caddy gère automatiquement les certificats SSL avec Let's Encrypt !

### Obtenir un certificat SSL gratuit

```bash
# Avec Certbot (pour Nginx/Apache)
sudo certbot --nginx -d frenchio.votredomaine.com

# Avec Caddy
# Automatique, rien à faire !
```

## 🌐 Configuration Proxy (HTTP/HTTPS)

Si votre réseau utilise un proxy, Frenchio le supporte nativement :

### Avec Docker

```bash
# Définir les variables d'environnement proxy
docker run -d \
  --name frenchio \
  -p 7777:7777 \
  -e HTTP_PROXY=http://proxy.example.com:8080 \
  -e HTTPS_PROXY=http://proxy.example.com:8080 \
  -e NO_PROXY=localhost,127.0.0.1 \
  ghcr.io/aymene69/frenchio:latest
```

### Avec Docker Compose

Décommentez les lignes proxy dans `docker-compose.yml` :

```yaml
environment:
  - PORT=7777
  - HTTP_PROXY=http://proxy.example.com:8080
  - HTTPS_PROXY=http://proxy.example.com:8080
  - NO_PROXY=localhost,127.0.0.1
```

### Installation manuelle

```bash
# Définir les variables avant de lancer
export HTTP_PROXY=http://proxy.example.com:8080
export HTTPS_PROXY=http://proxy.example.com:8080
export NO_PROXY=localhost,127.0.0.1

python main.py
```

> **Note** : Frenchio utilise les variables standard `HTTP_PROXY`, `HTTPS_PROXY` et `NO_PROXY` (majuscules ou minuscules).

## 🔧 Configuration qBittorrent

Pour un streaming optimal avec qBittorrent :

### 1. Activer le WebUI

Options → Web UI → Cocher "Enable Web UI"
- Port : 8080 (ou autre)
- Username : admin
- Password : votre-mot-de-passe

### 2. Serveur de fichiers

Le dossier de téléchargement doit être accessible via HTTP pour le streaming.

**Option A : Nginx**
```nginx
server {
    listen 8000;
    root /chemin/vers/downloads;
    autoindex on;
}
```

**Option B : Python (test uniquement)**
```bash
cd /chemin/vers/downloads
python3 -m http.server 8000
```

### 3. Configuration dans Frenchio

- Host : `http://ip-qbittorrent:8080`
- Public URL : `http://ip-qbittorrent:8000`

> **Note** : La librairie `qbittorrent-api` gère automatiquement l'authentification et le CSRF, aucune configuration spéciale nécessaire.

## 📊 Architecture

```
frenchio/
├── main.py                 # Point d'entrée, routes Stremio
├── services/
│   ├── tmdb.py            # Service TMDB (IMDB → TMDB)
│   ├── unit3d.py          # Client UNIT3D multi-tracker
│   ├── sharewood.py       # Client Sharewood API
│   ├── ygg.py             # Client YGGAPI
│   ├── alldebrid.py       # Service AllDebrid (debrid)
│   └── qbittorrent.py     # Service qBittorrent (streaming)
├── templates/
│   └── configure.html     # Page de configuration
├── utils.py               # Utilitaires
├── requirements.txt       # Dépendances Python
├── Dockerfile             # Image Docker
└── docker-compose.yml     # Stack Docker
```

### Schéma de déploiement

```
┌─────────────────────────────────────────────┐
│  Stremio (Client)                           │
│  ✅ Accepte: https:// ou http://localhost   │
│  ❌ Refuse: http://distant                  │
└─────────────────┬───────────────────────────┘
                  │
    ┌─────────────┴──────────────┐
    │                            │
    ▼ localhost                  ▼ distant
┌──────────────┐          ┌──────────────┐
│  Frenchio    │          │ Reverse Proxy│
│ :7777 (HTTP) │          │ (HTTPS + SSL)│
└──────────────┘          └──────┬───────┘
                                 │
                          ┌──────▼───────┐
                          │  Frenchio    │
                          │ :7777 (HTTP) │
                          └──────────────┘
```

## 🐛 Dépannage

### L'addon n'apparaît pas dans Stremio / Erreur de connexion

**Cause** : Stremio refuse les addons HTTP non-localhost

**Solution** :
- ✅ Si hébergé localement : Utilisez `http://localhost:7777` ou `http://127.0.0.1:7777`
- ✅ Si hébergé à distance : **HTTPS obligatoire** avec un reverse proxy (voir section [Hébergement distant](#-hébergement-distant-https-requis))

### Aucun résultat affiché

- Vérifiez que vos clés API sont valides
- Consultez les logs : `docker logs frenchio-addon` ou terminal
- Testez manuellement les API des trackers

### qBittorrent : Connexion impossible

- Vérifiez que le WebUI est bien activé
- Testez : `curl http://votre-ip:8080/api/v2/app/version`
- Vérifiez les identifiants (username/password)

### AllDebrid : Erreurs

- Vérifiez que votre clé API est valide
- Consultez les logs pour les détails

## 🤝 Contribution

Les contributions sont les bienvenues ! N'hésitez pas à :

1. Fork le projet
2. Créer une branche (`git checkout -b feature/nouvelle-fonctionnalite`)
3. Commit vos changements (`git commit -m 'Ajout nouvelle fonctionnalité'`)
4. Push vers la branche (`git push origin feature/nouvelle-fonctionnalite`)
5. Ouvrir une Pull Request

## 📜 Licence

Ce projet est sous licence MIT. Voir le fichier [LICENSE](LICENSE) pour plus de détails.

## ⚠️ Avertissement

Cet addon est conçu pour un usage personnel avec vos propres comptes et trackers. Assurez-vous de respecter les conditions d'utilisation de chaque service et les lois en vigueur dans votre pays.

## 🙏 Remerciements

- [Stremio](https://www.stremio.com/) pour leur plateforme extensible
- [UNIT3D](https://github.com/HDInnovations/UNIT3D) pour leur API tracker
- [AllDebrid](https://alldebrid.com/) pour leur service de débridage
- [TMDB](https://www.themoviedb.org/) pour leurs métadonnées
- La communauté des trackers français

## 📧 Support

Pour toute question ou problème :
- Ouvrez une [issue](https://github.com/aymene69/frenchio/issues)
- Consultez la [documentation Stremio](https://github.com/Stremio/stremio-addon-sdk)

---

**Fait avec ❤️ pour la communauté Stremio francophone**
