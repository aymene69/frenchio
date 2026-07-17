"""
Frenchio - Stremio Addon
=========================

A powerful Stremio addon for searching and streaming content from multiple
French private/semi-private trackers with AllDebrid integration and qBittorrent
fallback for non-cached torrents.

Features:
    - Multi-tracker search (UNIT3D, YGGTorrent, ABNormal, C411, Torr9)
    - AllDebrid instant caching detection
    - qBittorrent sequential streaming for non-cached torrents
    - Intelligent episode selection in season packs
    - Parallel API requests for maximum speed
    - Automatic magnet cleanup

Author: Frenchio Contributors
License: MIT
Repository: https://github.com/aymene69/frenchio
"""

import base64
import json
import os
import logging
import aiohttp
from aiohttp import web
import aiofiles
import asyncio
from urllib.parse import urlencode, urlsplit, urlparse, quote as urlquote, unquote as urlunquote
from services.tmdb import TMDBService
from services.unit3d import Unit3DService
from services.alldebrid import AllDebridService
from services.torbox import TorBoxService
from services.debridlink import DebridLinkService
from services.realdebrid import RealDebridService
from services.ygg import YggService
from services.abn import ABNService
from services.c411 import C411Service
from services.torr9 import Torr9Service
from services.qbittorrent import QBittorrentService
from services.tr4ker import Tr4kerService
from services.nyaa import NyaaService
from services.nekobt import NekoBTService
from utils import format_size, parse_torrent_name, check_season_episode, check_title_match, is_video_file

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,  # INFO pour un usage normal
    format='%(levelname)s:%(name)s:%(message)s'
)

# Configuration du proxy (HTTP_PROXY, HTTPS_PROXY)
HTTP_PROXY = os.getenv('HTTP_PROXY') or os.getenv('http_proxy')
HTTPS_PROXY = os.getenv('HTTPS_PROXY') or os.getenv('https_proxy')

if HTTP_PROXY or HTTPS_PROXY:
    logging.info(f"Proxy configuration detected:")
    if HTTP_PROXY:
        logging.info(f"  HTTP_PROXY: {HTTP_PROXY}")
    if HTTPS_PROXY:
        logging.info(f"  HTTPS_PROXY: {HTTPS_PROXY}")

# Version de l'application
APP_VERSION = "1.5.2"

# Stremio Addons Config (signature)
STREMIO_ADDONS_CONFIG = {
    "issuer": "https://stremio-addons.net",
    "signature": "eyJhbGciOiJkaXIiLCJlbmMiOiJBMTI4Q0JDLUhTMjU2In0..9l2RL_spVPK81eoy5BUkDg.efNcrE-IQ2DOoYtul30Y1bf3YuCxW8imVaKluLvX2ThwHlgi14rEajndgvRKjVDv57fazbZncm3uySZvqyi_OpQCb5tTHZJcxwD1uhdO5hXDwgSV25T-eOV8tnhnFhNd.0o5__kzn1_ygVSGX7whq3A"
}

# Configuration des fonctionnalités
QBITTORRENT_ENABLE = os.getenv('QBITTORRENT_ENABLE', 'true').lower() in ('true', '1', 'yes')
MANIFEST_TITLE_SUFFIX = os.getenv('MANIFEST_TITLE_SUFFIX', '')
MANIFEST_BLURB = os.getenv('MANIFEST_BLURB', '')

# Proxy de streaming qBittorrent : répertoire local où les fichiers sont montés.
# Quand défini, Frenchio sert les fichiers directement en attendant les pièces (évite les zéros).
QBIT_PROXY_DIR = os.getenv('QBIT_PROXY_DIR', '')

logging.info(f"qBittorrent enabled: {QBITTORRENT_ENABLE}")
if MANIFEST_TITLE_SUFFIX:
    logging.info(f"Manifest title suffix: {MANIFEST_TITLE_SUFFIX}")
if MANIFEST_BLURB:
    logging.info(f"Manifest blurb configured")

# ============================================================================
# Middleware
# ============================================================================

@web.middleware
async def cors_middleware(request, handler):
    """
    CORS middleware to allow cross-origin requests from Stremio.
    
    Stremio Web requires CORS headers to communicate with external addons.
    This middleware adds the necessary headers to all responses.
    """
    response = await handler(request)
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response

# ============================================================================
# Configuration Handlers
# ============================================================================

async def handle_configure(request):
    """
    Serve the configuration page with optional pre-filled values.
    
    The configuration page allows users to input their API keys and tracker
    credentials. If a config string is provided in the URL, it will be decoded
    and used to pre-fill the form fields.
    
    Args:
        request: aiohttp request object containing optional config parameter
        
    Returns:
        web.Response: HTML configuration page
    """
    config_str = request.match_info.get('config', '')
    prefill_data = "{}"
    
    if config_str:
        try:
            # On tente de décoder si une config est passée dans l'URL
            decoded = decode_config(config_str)
            if decoded:
                prefill_data = json.dumps(decoded)
        except:
            pass

    try:
        async with aiofiles.open('templates/configure.html', mode='r', encoding='utf-8') as f:
            content = await f.read()
        
        # Injection de la config pré-remplie dans le JS
        # On cherche une balise script ou on l'ajoute
        # Le plus simple : remplacer une variable placeholder
        content = content.replace('const prefillConfig = {};', f'const prefillConfig = {prefill_data};')
        
        # Injection de la variable QBITTORRENT_ENABLE
        qbit_enabled_js = 'true' if QBITTORRENT_ENABLE else 'false'
        content = content.replace('const qbittorrentEnabled = true;', f'const qbittorrentEnabled = {qbit_enabled_js};')
        
        # Injection du blurb personnalisé (échappé pour JavaScript)
        blurb_escaped = json.dumps(MANIFEST_BLURB) if MANIFEST_BLURB else '""'
        content = content.replace('const manifestBlurb = "";', f'const manifestBlurb = {blurb_escaped};')
        
        # Injection de la version de l'application
        content = content.replace('const appVersion = "1.1.0";', f'const appVersion = "{APP_VERSION}";')
        
        return web.Response(text=content, content_type='text/html')
    except Exception as e:
        return web.Response(text=str(e), status=500)

def decode_config(config_str):
    try:
        decoded = base64.b64decode(config_str).decode('utf-8')
        return json.loads(decoded)
    except Exception as e:
        logging.error(f"Config Decode Error: {e}")
        return None


def build_mediaflow_proxy_url(stream_url, mediaflow_config, filename=None):
    """
    Construit une URL MediaFlow Proxy à partir d'une URL de stream finale.

    MediaFlow est utilisé ici comme proxy optionnel en sortie, après résolution
    par le provider de débridage ou qBittorrent.
    """
    if not stream_url or not mediaflow_config:
        return stream_url

    base_url = (mediaflow_config.get('proxy_url') or '').strip().rstrip('/')
    if not base_url:
        return stream_url

    stream_path = urlsplit(stream_url).path.lower()
    is_hls = stream_path.endswith('.m3u8') or '.m3u8' in stream_path
    endpoint = '/proxy/hls/manifest.m3u8' if is_hls else '/proxy/stream'

    params = {'d': stream_url}
    api_password = (mediaflow_config.get('api_password') or '').strip()
    if api_password:
        params['api_password'] = api_password

    if endpoint == '/proxy/stream' and filename:
        params['filename'] = filename

    proxied_url = f"{base_url}{endpoint}?{urlencode(params)}"
    logging.info(f"MediaFlow proxy enabled for endpoint {endpoint}")
    return proxied_url


def finalize_stream_url(stream_url, config, filename=None):
    """Applique les post-traitements optionnels au lien final de lecture."""
    mediaflow_config = config.get('mediaflow')
    return build_mediaflow_proxy_url(stream_url, mediaflow_config, filename=filename)

async def handle_manifest(request):
    """Retourne le manifest de l'addon"""
    config_str = request.match_info.get('config', '')
    config = decode_config(config_str)
    
    if not config:
        return web.Response(status=400, text="Invalid Config")

    # Construction du nom de l'addon avec suffixe optionnel
    addon_name = "Frenchio"
    if MANIFEST_TITLE_SUFFIX:
        addon_name += f" {MANIFEST_TITLE_SUFFIX}"
    
    # Description de base (le blurb s'affiche dans la page de config)
    description = "Stream from French Trackers (UNIT3D, YGG, ABN, C411, Torr9) via AllDebrid, TorBox, DebridLink ou qBittorrent"

    manifest = {
        "id": "community.aymene69.frenchio",
        "version": APP_VERSION,
        "name": addon_name,
        "description": description,
        "icon": "https://i.imgur.com/MgdGxnR.png", # Icône générique ou à changer
        "stremioAddonsConfig": STREMIO_ADDONS_CONFIG,
        "types": ["movie", "series"],
        "catalogs": [],
        "resources": ["stream"],
        "idPrefixes": ["tt"],
        "behaviorHints": {
            "configurable": True,
        },
        "beyiond_support": True
    }
    return web.json_response(manifest)

async def handle_manifest_no_config(request):
    """
    Manifest sans configuration (route /manifest.json).
    Utile quand quelqu'un tente d'installer l'addon sans passer par /configure.
    """
    addon_name = "Frenchio"
    if MANIFEST_TITLE_SUFFIX:
        addon_name += f" {MANIFEST_TITLE_SUFFIX}"

    description = "Addon non configuré : allez sur /configure pour générer votre lien d'installation."

    manifest = {
        "id": "community.aymene69.frenchio",
        "version": APP_VERSION,
        "name": addon_name,
        "description": description,
        "icon": "https://i.imgur.com/MgdGxnR.png",
        "stremioAddonsConfig": STREMIO_ADDONS_CONFIG,
        "types": ["movie", "series"],
        "catalogs": [],
        # On garde stream pour que Stremio le reconnaisse, mais sans config ça ne renverra rien.
        "resources": ["stream"],
        "behaviorHints": {
            "configurable": True,
            "configurationRequired": True
        },
        "beyiond_support": True
    }
    return web.json_response(manifest)

async def handle_stream_no_config(request):
    """
    Stream endpoint sans configuration (route /stream/...).
    On renvoie un stream "informatif" qui pointe vers la page /configure.
    """
    host_url = f"{request.scheme}://{request.host}"
    config_url = f"{host_url}/configure"

    return web.json_response({
        "streams": [{
            "name": "Configure l'addon",
            "title": "⚙️ Configure Frenchio (ouvre la page de configuration)",
            # Stremio ouvre un navigateur externe au lieu d'essayer de lire une vidéo
            "externalUrl": config_url
        }]
    })

async def handle_stream(request):
    """Gère la recherche de streams"""
    config_str = request.match_info.get('config', '')
    config = decode_config(config_str)
    if not config:
        return web.json_response({"streams": []})

    stream_type = request.match_info.get('type')
    stream_id = request.match_info.get('id')

    # Parsing ID (tt1234567 ou tt1234567:1:2)
    imdb_id = stream_id
    season = None
    episode = None
    
    if ":" in stream_id:
        parts = stream_id.split(":")
        imdb_id = parts[0]
        season = int(parts[1])
        episode = int(parts[2])

    logging.info(f"Searching for {stream_type} {imdb_id} S{season}E{episode}")

    # Initialisation des services
    tmdb_service = TMDBService(config['tmdb_key'])
    
    # Services de débridage (optionnels)
    alldebrid_service = None
    torbox_service = None
    debridlink_service = None
    realdebrid_service = None
    
    if config.get('alldebrid_key') and config['alldebrid_key'].strip():
        alldebrid_service = AllDebridService(config['alldebrid_key'])
        logging.info("AllDebrid service initialized")
    
    if config.get('torbox_key') and config['torbox_key'].strip():
        torbox_service = TorBoxService(config['torbox_key'])
        logging.info("TorBox service initialized")
    
    if config.get('debridlink_key') and config['debridlink_key'].strip():
        debridlink_service = DebridLinkService(config['debridlink_key'])
        logging.info("DebridLink service initialized")
    
    if config.get('realdebrid_key') and config['realdebrid_key'].strip():
        realdebrid_service = RealDebridService(config['realdebrid_key'])
        logging.info("Real-Debrid service initialized")
    
    if not alldebrid_service and not torbox_service and not debridlink_service and not realdebrid_service:
        logging.info("No debrid service configured, using qBittorrent fallback")
    
    # qBittorrent optionnel
    qbit_service = None
    if QBITTORRENT_ENABLE and config.get('qbittorrent'):
        qbit_config = config['qbittorrent']
        if qbit_config.get('host') and qbit_config.get('public_url'):
            qbit_service = QBittorrentService(
                host=qbit_config['host'],
                username=qbit_config.get('username', ''),
                password=qbit_config.get('password', ''),
                public_url_base=qbit_config['public_url']
            )
            logging.info("qBittorrent service initialized")
            
            # Test de connexion (synchrone avec la nouvelle librairie)
            try:
                qbit_service.test_connection()
            except Exception as e:
                logging.error(f"qBittorrent test failed: {e}")
        else:
            logging.warning("qBittorrent config incomplete, skipping")
    elif not QBITTORRENT_ENABLE:
        logging.info("qBittorrent disabled by QBITTORRENT_ENABLE environment variable")
    
    # Vérifier qu'au moins un service est configuré
    if not alldebrid_service and not torbox_service and not debridlink_service and not realdebrid_service and not qbit_service:
        logging.error("No debrid or torrent client configured!")
        return web.json_response({"streams": []})
    
    unit3d_results = []
    # 1. Info Média et Conversion ID (pour UNIT3D)
    
    # Étape 1 : Find by IMDB ID
    tmdb_id = await tmdb_service.get_tmdb_id(imdb_id, stream_type)
    
    # Étape 1.5 : Récupérer Titre/Année pour les trackers qui en ont besoin
    # YGG est maintenant toujours actif (avec ou sans passkey), donc on a toujours besoin de media_info
    media_info = None
    needs_media_info = True  # Toujours true car YGG est toujours actif
    
    if needs_media_info:
        # On a besoin des détails pour le titre
        if tmdb_id:
             async with aiohttp.ClientSession(trust_env=True) as session:
                url = f"https://api.themoviedb.org/3/{'movie' if stream_type == 'movie' else 'tv'}/{tmdb_id}"
                params = {"api_key": config['tmdb_key'], "language": "fr-FR"} 
                # Trackers FR, donc on force le titre FR
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        media_info = await resp.json()

    # 2. Recherche Parallèle
    tasks = []

    # Tâche UNIT3D
    if config.get('trackers'):
        logging.info(f"Starting UNIT3D search on {len(config['trackers'])} trackers")
        unit3d_service = Unit3DService(config['trackers'])
        tasks.append(unit3d_service.search_all(
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
            type=stream_type,
            season=season,
            episode=episode
        ))
    else:
        logging.info("UNIT3D search skipped (no trackers configured)")
        async def empty(): return []
        tasks.append(empty())

    # Tâche YGG (toujours active, passkey plus nécessaire)
    ygg_service = YggService()
    
    target_title = (media_info.get('title') or media_info.get('name')) if media_info else ""
    original_title = (media_info.get('original_title') or media_info.get('original_name')) if media_info else ""
    year = ""
    is_anime = False
    if media_info:
        date = media_info.get('release_date') or media_info.get('first_air_date')
        year = date.split('-')[0] if date else ""
        
        orig_lang = media_info.get('original_language', '')
        origin_country = media_info.get('origin_country', [])
        genres = media_info.get('genres', [])
        genre_ids = [g.get('id') for g in genres] if genres else media_info.get('genre_ids', [])
        
        if orig_lang in ['ja', 'ko', 'zh'] or 'JP' in origin_country:
            if 16 in genre_ids or orig_lang == 'ja':
                is_anime = True
                
        # Fallback pour les animes très spécifiques qui pourraient manquer d'infos complètes
        if 'anime' in (media_info.get('overview') or '').lower() and 16 in genre_ids:
            is_anime = True

    if stream_type == 'movie':
        tasks.append(ygg_service.search_movie(target_title, year, original_title=original_title, imdb_id=imdb_id, tmdb_id=tmdb_id))
    elif stream_type == 'series':
        tasks.append(ygg_service.search_series(target_title, season, episode, original_title=original_title, imdb_id=imdb_id, tmdb_id=tmdb_id))

    # Tâche ABN
    abn_service = None
    if config.get('abn_username') and config.get('abn_password'):
        logging.info("Starting ABN search")
        abn_service = ABNService(
            username=config.get('abn_username'),
            password=config.get('abn_password')
        )
        
        title = media_info.get('title') or media_info.get('name') if media_info else ""
        original_title = media_info.get('original_title') or media_info.get('original_name') if media_info else ""
        year = ""
        if media_info:
            date = media_info.get('release_date') or media_info.get('first_air_date')
            year = date.split('-')[0] if date else ""

        if stream_type == 'movie':
            tasks.append(abn_service.search_movie(title, year, original_title=original_title))
        elif stream_type == 'series':
            tasks.append(abn_service.search_series(title, season, episode, original_title=original_title))
    else:
        async def empty(): return []
        tasks.append(empty())

    # Tâche C411
    if config.get('c411_apikey'):
        logging.info("Starting C411 search")
        c411_service = C411Service(config.get('c411_apikey'))
        
        if stream_type == 'movie':
            tasks.append(c411_service.search_movie(target_title, year, imdb_id=imdb_id, tmdb_id=tmdb_id))
        elif stream_type == 'series':
            tasks.append(c411_service.search_series(target_title, season, episode, imdb_id=imdb_id, tmdb_id=tmdb_id))
    else:
        async def empty(): return []
        tasks.append(empty())

    # Tâche Torr9
    if config.get('torr9_passkey'):
        logging.info("Starting Torr9 search")
        torr9_service = Torr9Service(config.get('torr9_passkey'))

        if stream_type == 'movie':
            tasks.append(torr9_service.search_movie(target_title, year, imdb_id=imdb_id, tmdb_id=tmdb_id))
        elif stream_type == 'series':
            tasks.append(torr9_service.search_series(target_title, season, episode, imdb_id=imdb_id, tmdb_id=tmdb_id))
    else:
        async def empty(): return []
        tasks.append(empty())

    # Tâche Tr4ker
    if config.get('tr4ker_apikey'):
        logging.info("Starting Tr4ker search")
        tr4ker_service = Tr4kerService(config.get('tr4ker_apikey'))

        if stream_type == 'movie':
            tasks.append(tr4ker_service.search_movie(target_title, year, imdb_id=imdb_id, tmdb_id=tmdb_id))
        elif stream_type == 'series':
            tasks.append(tr4ker_service.search_series(target_title, season, episode, imdb_id=imdb_id, tmdb_id=tmdb_id))
    else:
        async def empty(): return []
        tasks.append(empty())

    # Tâche NekoBT
    if config.get('neko_apikey') and is_anime:
        logging.info("Starting NekoBT search")
        nekobt_service = NekoBTService(config.get('neko_apikey'))

        if stream_type == 'movie':
            tasks.append(nekobt_service.search_movie(target_title, year, imdb_id=imdb_id, tmdb_id=tmdb_id))
        elif stream_type == 'series':
            tasks.append(nekobt_service.search_series(target_title, season, episode, imdb_id=imdb_id, tmdb_id=tmdb_id))
    else:
        if config.get('neko_apikey') and not is_anime:
            logging.info("NekoBT search skipped (Not an anime)")
        async def empty(): return []
        tasks.append(empty())

    # Tâche Nyaa
    if config.get('nyaa_enabled') and is_anime:
        logging.info("Starting Nyaa search")
        nyaa_service = NyaaService()

        if stream_type == 'movie':
            tasks.append(nyaa_service.search_movie(target_title, year, imdb_id=imdb_id, tmdb_id=tmdb_id))
        elif stream_type == 'series':
            tasks.append(nyaa_service.search_series(target_title, season, episode, imdb_id=imdb_id, tmdb_id=tmdb_id))
    else:
        if config.get('nyaa_enabled') and not is_anime:
            logging.info("Nyaa search skipped (Not an anime)")
        async def empty(): return []
        tasks.append(empty())

    # Exécution
    try:
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        unit3d_results = results_list[0] if not isinstance(results_list[0], Exception) else []
        for t in unit3d_results:
            t['source'] = 'unit3d'
            
        def safe(idx):
            r = results_list[idx] if len(results_list) > idx else []
            if isinstance(r, Exception):
                logging.error(f"Task {idx} failed: {r}")
                return []
            return r

        ygg_results = safe(1)
        abn_results = safe(2)
        c411_results = safe(3)
        torr9_results = safe(4)
        tr4ker_results = safe(5)
        nekobt_results = safe(6)
        nyaa_results = safe(7)
    finally:
        # Fermer la session ABN proprement
        if abn_service:
            await abn_service.close()

    logging.info(f"Results breakdown: UNIT3D={len(unit3d_results)}, YGG={len(ygg_results)}, ABN={len(abn_results)}, C411={len(c411_results)}, Torr9={len(torr9_results)}, Tr4ker={len(tr4ker_results)}, NekoBT={len(nekobt_results)}, Nyaa={len(nyaa_results)}")

    # Fusion et Déduplication
    all_torrents = unit3d_results + ygg_results + abn_results + c411_results + torr9_results + tr4ker_results + nekobt_results + nyaa_results
    
    # Tri préalable selon providers_order pour que le tracker favori soit gardé lors de la déduplication
    providers_order = config.get('providers_order', [])
    if providers_order:
        def get_prov_sort_key(t):
            source = t.get('source', '')
            try:
                return providers_order.index(source)
            except ValueError:
                return len(providers_order)
        all_torrents.sort(key=get_prov_sort_key)
    
    # Filtrage par taille si configuré
    max_size_gb = config.get('max_size', 0)
    if max_size_gb > 0:
        max_size_bytes = max_size_gb * 1024 * 1024 * 1024  # Conversion Go -> bytes
        before_filter = len(all_torrents)
        all_torrents = [t for t in all_torrents if t.get('size', 0) <= max_size_bytes]
        filtered_count = before_filter - len(all_torrents)
        if filtered_count > 0:
            logging.info(f"Filtered {filtered_count} torrents exceeding {max_size_gb} Go")
    
    
    # Filtrage par type de fichier (Vidéos uniquement)
    before_filter = len(all_torrents)
    all_torrents = [t for t in all_torrents if is_video_file(t.get('name', ''))]
    filtered_count = before_filter - len(all_torrents)
    if filtered_count > 0:
        logging.info(f"Filtered {filtered_count} non-video files")

    unique_torrents = {}
    
    for t in all_torrents:
        # Filtrage Strict pour UNIT3D (Anti-bruit ID)
        if t.get('source') == 'unit3d': # ou le nom interne utilisé dans le service
            # UNIT3D est cherché par ID, donc le résultat DOIT avoir l'ID correspondant
            # ou au moins ne pas avoir un ID contradictoire (0 ou différent)
            
            res_tmdb = t.get('tmdb_id') or t.get('tmdb')
            res_imdb = t.get('imdb_id') or t.get('imdb')
            
            # Si TMDB ID présent et non nul, il doit matcher
            if res_tmdb and str(res_tmdb) != "0" and tmdb_id and str(res_tmdb) != str(tmdb_id):
                # logging.info(f"Filtered UNIT3D (Wrong TMDB): {t.get('name')} {res_tmdb}!={tmdb_id}")
                continue
                
            # Si IMDB ID présent et non nul, il doit matcher (en ignorant 'tt')
            if res_imdb and str(res_imdb) != "0" and imdb_id:
                clean_res = str(res_imdb).replace('tt', '')
                clean_req = str(imdb_id).replace('tt', '')
                if clean_res != clean_req:
                    # logging.info(f"Filtered UNIT3D (Wrong IMDB): {t.get('name')} {res_imdb}!={imdb_id}")
                    continue
                
            # Si UNIT3D renvoie un résultat sans ID, on l'accepte quand même
            # (la vérification par titre pourrait être ajoutée ici si nécessaire)
            # if (not res_tmdb or str(res_tmdb) == "0") and (not res_imdb or str(res_imdb) == "0"):
            #      # Filtrage par titre si nécessaire
            #      pass

        # Filtrage par titre et année (Vérification systématique pour éviter les erreurs de mapping des trackers)
        if stream_type in ('movie', 'series'):
            # Pour l'animation (Nyaa/NekoBT), le nommage est trop complexe (ex: sous-titres anglais) pour le filtre strict
            if t.get('source') not in ('nyaa', 'nekobt'):
                if not check_title_match(t.get('name', ''), target_title, original_title, year=year, is_movie=(stream_type == 'movie')):
                    # logging.info(f"Filtered out (Title mismatch): {t.get('name')} for target {target_title}")
                    continue

        # Filtrage Série (SxxExx)
        # Si c'est une série, on vérifie que le titre correspond à la saison/épisode demandé
        # pour éviter d'afficher E03 quand on veut E07 (souvent le cas avec recherche floue)
        if stream_type == 'series' and season is not None:
            exclude_packs = config.get('exclude_season_packs', False)
            if not check_season_episode(t.get('name', ''), season, episode, exclude_packs=exclude_packs):
                # logging.info(f"Filtered out: {t.get('name')} (Wrong Season/Episode)")
                continue

        # Info Hash est la clé unique (minuscule pour éviter les doublons de casse)
        ih = t.get('info_hash')
        if ih:
            ih = ih.lower()
            if ih not in unique_torrents:
                unique_torrents[ih] = t
            # Optionnel : Si on voulait fusionner les sources, on pourrait le faire ici
            # else:
            #     unique_torrents[ih]['tracker_name'] += f" / {t.get('tracker_name')}"
            
    # Liste finale des torrents uniques
    torrents = list(unique_torrents.values())
    
    if not torrents:
        return web.json_response({"streams": []})

    logging.info(f"Total unique torrents (UNIT3D + YGG + ABN + C411 + Torr9 + Tr4ker + NekoBT + Nyaa): {len(torrents)}")

    streams = []
    host_url = f"{request.scheme}://{request.host}"
    
    # 3. Check disponibilité sur les services de débridage
    availability = {}
    debrid_provider = None
    
    if alldebrid_service:
        hashes = [t['info_hash'] for t in torrents if t.get('info_hash')]
        availability = await alldebrid_service.check_availability(hashes)
        debrid_provider = "alldebrid"
        logging.info(f"AllDebrid: {len([v for v in availability.values() if v])} cached torrents")
    
    elif torbox_service:
        # TorBox check (en parallèle pour la vitesse)
        hashes = [t['info_hash'] for t in torrents if t.get('info_hash')]
        # Effectuer toutes les vérifications en parallèle
        results = await asyncio.gather(
            *[torbox_service.check_availability(h) for h in hashes],
            return_exceptions=True
        )
        # Construire le dictionnaire de disponibilité
        for h, result in zip(hashes, results):
            if not isinstance(result, Exception) and result:
                availability[h] = result
        debrid_provider = "torbox"
        logging.info(f"TorBox: {len([v for v in availability.values() if v])} cached torrents")
    
    elif debridlink_service:
        # DebridLink check (en parallèle)
        hashes = [t['info_hash'] for t in torrents if t.get('info_hash')]
        availability = await debridlink_service.check_availability(hashes)
        debrid_provider = "debridlink"
        logging.info(f"DebridLink: {len([v for v in availability.values() if v])} cached torrents")
    
    elif realdebrid_service:
        # Real-Debrid check
        hashes = [t['info_hash'] for t in torrents if t.get('info_hash')]
        availability = await realdebrid_service.check_availability(hashes)
        debrid_provider = "realdebrid"
        logging.info(f"Real-Debrid: {len([v for v in availability.values() if v])} cached torrents")

    # 4. Générer les streams
    cached_torrents = []
    uncached_torrents = []
    
    for torrent in torrents:
        info_hash = torrent.get('info_hash')
        if not info_hash:
            continue
            
        # Nettoyer le hash
        if alldebrid_service:
            clean_hash = alldebrid_service._clean_hash(info_hash)
            is_cached = availability.get(clean_hash, False)
        elif torbox_service:
            clean_hash = info_hash.lower().strip()
            is_cached = availability.get(clean_hash, False)
        elif debridlink_service:
            clean_hash = info_hash.lower().strip()
            is_cached = availability.get(clean_hash, False)
        elif realdebrid_service:
            clean_hash = info_hash.lower().strip()
            is_cached = availability.get(clean_hash, False)
        else:
            clean_hash = info_hash.lower().strip()
            is_cached = False
        
        if is_cached:
            cached_torrents.append((torrent, clean_hash))
        else:
            uncached_torrents.append((torrent, clean_hash))

    # Application du Tri
    sort_by = config.get('sort_by', 'tracker_priority')
    
    if sort_by == 'size_asc':
        def get_sort_size(item):
            torrent, _ = item
            return torrent.get('size', 0)
        
        cached_torrents.sort(key=get_sort_size)
        uncached_torrents.sort(key=get_sort_size)
        
    elif sort_by == 'size_desc':
        def get_sort_size(item):
            torrent, _ = item
            return torrent.get('size', 0)
        
        cached_torrents.sort(key=get_sort_size, reverse=True)
        uncached_torrents.sort(key=get_sort_size, reverse=True)
        
    else:
        # Tri personnalisé selon providers_order de la config (par défaut)
        providers_order = config.get('providers_order', [])
        if providers_order:
            def get_sort_key(item):
                torrent, _ = item
                source = torrent.get('source', '')
                try:
                    return providers_order.index(source)
                except ValueError:
                    return len(providers_order)

            # Utilisation de sort() qui est stable en Python
            cached_torrents.sort(key=get_sort_key)
            uncached_torrents.sort(key=get_sort_key)

    logging.info(f"Cached: {len(cached_torrents)}, Uncached: {len(uncached_torrents)}")
    
    # 4a. Streams débridés (cachés)
    for torrent, clean_hash in cached_torrents:
        # Extraire un nom propre pour les trackers UNIT3D (tracker_name = URL)
        raw_tracker = torrent.get('tracker_name', 'UNIT3D')
        if raw_tracker.startswith('http'):
            # https://theoldschool.cc -> TheOldSchool
            domain = urlparse(raw_tracker).hostname or raw_tracker
            clean_name = domain.split('.')[0].capitalize()
        else:
            clean_name = raw_tracker

        source_prefix = "\n🐝 YGG" if torrent.get('source') == 'ygg' else \
                       "\n🎬 ABN" if torrent.get('source') == 'abn' else \
                       "\n📡 C411" if torrent.get('source') == 'c411' else \
                       "\n🔥 Torr9" if torrent.get('source') == 'torr9' else \
                       "\n🎯 Tr4ker" if torrent.get('source') == 'tr4ker' else \
                       f"\n🌐 {clean_name}"
        
        size_str = format_size(torrent.get('size', 0))
        meta = parse_torrent_name(torrent.get('name', ''))
        
        provider_emoji = "⚡"  # Éclair pour tous les services de débridage
        title = f"{provider_emoji} {meta['name']}\n{torrent.get('name')}\n💾 {size_str}"
        
        # URL de résolution (utilise le provider configuré)
        resolve_url = f"{host_url}/{config_str}/resolve/{debrid_provider}/{clean_hash}"
        
        if season is not None and episode is not None:
            resolve_url += f"?season={season}&episode={episode}"
        elif stream_type == 'movie':
            resolve_url += "?type=movie"

        streams.append({
            "name": f"Frenchio{source_prefix}",
            "title": title,
            "url": resolve_url,
            "filename": torrent.get('name', ''),
            "size": torrent.get('size', 0),
            "quality": meta.get('quality', ''),
            "codec": meta.get('codec', ''),
            "release_type": meta.get('release_type', ''),
            "language": meta.get('language', '')
        })

    # 4b. Streams qBittorrent (non cachés, si configuré)
    # Si on a des torrents cachés, on n'affiche pas les non-cachés
    if qbit_service and uncached_torrents:
        # Filtrer les torrents YGG sans passkey (ne peuvent pas être téléchargés)
        has_ygg_passkey = config.get('ygg_passkey') and config.get('ygg_passkey').strip()
        if not has_ygg_passkey:
            before_filter = len(uncached_torrents)
            uncached_torrents = [(t, h) for t, h in uncached_torrents if t.get('source') != 'ygg']
            filtered = before_filter - len(uncached_torrents)
            if filtered > 0:
                logging.info(f"qBittorrent: Filtered {filtered} YGG torrents (no passkey for download)")
        
        if cached_torrents:
            logging.info(f"qBittorrent: Skipping {len(uncached_torrents)} uncached torrents (cached results available)")
        else:
            limit = 10 if (alldebrid_service or torbox_service or debridlink_service or realdebrid_service) else 25  # Plus de résultats si pas de debrid
            logging.info(f"qBittorrent: Processing {min(len(uncached_torrents), limit)} torrents (out of {len(uncached_torrents)} available)")
            
            qbit_added = 0
            for torrent, clean_hash in uncached_torrents[:limit]:
                download_link = torrent.get('link') or torrent.get('download_link')
                if not download_link:
                    logging.debug(f"Skipping torrent without download link: {torrent.get('name')}")
                    continue
                
                # Extraire un nom propre pour les trackers UNIT3D
                raw_tracker = torrent.get('tracker_name', 'UNIT3D')
                if raw_tracker.startswith('http'):
                    domain = urlparse(raw_tracker).hostname or raw_tracker
                    clean_name = domain.split('.')[0].capitalize()
                else:
                    clean_name = raw_tracker

                source_prefix = "🐝 YGG" if torrent.get('source') == 'ygg' else \
                               "🎬 ABN" if torrent.get('source') == 'abn' else \
                               "📡 C411" if torrent.get('source') == 'c411' else \
                               "🔥 Torr9" if torrent.get('source') == 'torr9' else \
                               "🎯 Tr4ker" if torrent.get('source') == 'tr4ker' else \
                               f"🌐 {clean_name}"

                size_str = format_size(torrent.get('size', 0))
                meta = parse_torrent_name(torrent.get('name', ''))

                title = f"📥 {meta['name']}\n{torrent.get('name')}\n💾 {size_str} [qBittorrent]"

                encoded_link = urlquote(download_link, safe='')
                
                # On passe la config encodée pour avoir accès aux credentials qBittorrent
                resolve_url = f"{host_url}/{config_str}/resolve/qbit/{clean_hash}?link={encoded_link}"
                
                if season is not None and episode is not None:
                    resolve_url += f"&season={season}&episode={episode}"
                elif stream_type == 'movie':
                    resolve_url += "&type=movie"

                streams.append({
                    "name": f"Frenchio {source_prefix}",
                    "title": title,
                    "url": resolve_url,
                    "filename": torrent.get('name', ''),
                    "size": torrent.get('size', 0),
                    "quality": meta.get('quality', ''),
                    "codec": meta.get('codec', ''),
                    "release_type": meta.get('release_type', ''),
                    "language": meta.get('language', '')
                })
                qbit_added += 1
            
            logging.info(f"qBittorrent: Added {qbit_added} streams")

    logging.info(f"Returning {len(streams)} streams to Stremio")
    return web.json_response({"streams": streams})

async def handle_resolve(request):
    """Résout le lien Debrid ou qBittorrent au moment de la lecture"""
    # Récupérer la config depuis l'URL (/{config}/resolve/...)
    config_str = request.match_info.get('config', '')
    config = decode_config(config_str)
    
    if not config:
        return web.Response(status=400, text="Invalid config")
    
    service_name = request.match_info.get('service', 'alldebrid')
    info_hash = request.match_info.get('hash')
    
    # Récupération des paramètres optionnels
    season = request.query.get('season')
    episode = request.query.get('episode')
    media_type = request.query.get('type')
    
    # === MODE qBittorrent ===
    if service_name == 'qbit':
        download_link = request.query.get('link')
        if not download_link:
            return web.Response(status=400, text="Missing download link")
        
        download_link = urlunquote(download_link)
        
        # Récupérer la config qBittorrent
        qbit_config = config.get('qbittorrent')
        if not qbit_config:
            return web.Response(status=400, text="qBittorrent not configured")
        
        qbit_service = QBittorrentService(
            host=qbit_config['host'],
            username=qbit_config.get('username', ''),
            password=qbit_config.get('password', ''),
            public_url_base=qbit_config['public_url']
        )
        
        # Fast-path: si le torrent est déjà actif, on retourne l'URL sans rien télécharger.
        # Critique pour les seek libmpv (Range requests) qui repassent par /resolve.
        fast_url = qbit_service.try_fast_path(
            info_hash,
            season=int(season) if season else None,
            episode=int(episode) if episode else None
        )
        if fast_url:
            logging.info(f"⚡ Fast-path hit, skipping torrent download")
            fast_url = _qbit_proxy_url(request, config_str, info_hash, fast_url)
            raise web.HTTPMovedPermanently(finalize_stream_url(fast_url, config))

        # Magnet links passés directement à qBittorrent sans download HTTP
        if download_link.startswith('magnet:'):
            logging.info("Magnet link detected, passing directly to qBittorrent")
            stream_url = qbit_service.manage_stream(
                download_link,
                info_hash,
                is_file=False,
                season=int(season) if season else None,
                episode=int(episode) if episode else None
            )
            if stream_url:
                stream_url = _qbit_proxy_url(request, config_str, info_hash, stream_url)
                logging.info(f"qBittorrent stream ready: {stream_url}")
                raise web.HTTPMovedPermanently(finalize_stream_url(stream_url, config))
            else:
                return web.Response(status=404, text="Could not start qBittorrent stream")

        # Télécharger le .torrent
        logging.info(f"Downloading torrent from: {download_link[:100]}...")

        # Vérifier si c'est un lien ABN qui nécessite une authentification
        if 'abn.lol' in download_link or 'abnormal.ws' in download_link:
            if config.get('abn_username') and config.get('abn_password'):
                abn_service = ABNService(
                    username=config.get('abn_username'),
                    password=config.get('abn_password')
                )
                try:
                    torrent_data = await abn_service.download_torrent(download_link)
                    if not torrent_data:
                        logging.error("Failed to download .torrent from ABN")
                        return web.Response(status=502, text="Failed to download torrent file from ABN")
                finally:
                    await abn_service.close()
            else:
                logging.error("ABN credentials not configured")
                return web.Response(status=400, text="ABN credentials required")
        else:
            # Téléchargement standard
            async with aiohttp.ClientSession(trust_env=True) as session:
                async with session.get(download_link) as resp:
                    if resp.status != 200:
                        logging.error(f"Failed to download .torrent: {resp.status}")
                        return web.Response(status=502, text="Failed to download torrent file")
                    torrent_data = await resp.read()
        
        logging.info(f"Downloaded {len(torrent_data)} bytes, adding to qBittorrent...")
        
        # Ajouter et configurer dans qBittorrent (synchrone avec la librairie officielle)
        stream_url = qbit_service.manage_stream(
            torrent_data, 
            info_hash, 
            is_file=True,
            season=int(season) if season else None,
            episode=int(episode) if episode else None
        )
        
        if stream_url:
            stream_url = _qbit_proxy_url(request, config_str, info_hash, stream_url)
            logging.info(f"qBittorrent stream ready: {stream_url}")
            raise web.HTTPMovedPermanently(finalize_stream_url(stream_url, config))
        else:
            return web.Response(status=404, text="Could not start qBittorrent stream")

    # === MODE AllDebrid ===
    elif service_name == 'alldebrid':
        alldebrid_key = config.get('alldebrid_key')
        if not alldebrid_key:
            return web.Response(status=400, text="AllDebrid not configured")
        
        debrid_service = AllDebridService(alldebrid_key)
        
        stream_url = await debrid_service.unlock_magnet(
            info_hash, 
            season=int(season) if season else None, 
            episode=int(episode) if episode else None,
            media_type=media_type
        )
        
        if stream_url:
            raise web.HTTPMovedPermanently(finalize_stream_url(stream_url, config))
        else:
            return web.Response(status=404, text="Could not resolve stream or file not found in torrent")
    
    # === MODE TorBox ===
    elif service_name == 'torbox':
        logging.info(f"TorBox resolve: Starting with hash={info_hash}, season={season}, episode={episode}")
        
        torbox_key = config.get('torbox_key')
        if not torbox_key:
            return web.Response(status=400, text="TorBox not configured")
        
        debrid_service = TorBoxService(torbox_key)
        
        # Construire le magnet à partir du hash
        magnet_link = f"magnet:?xt=urn:btih:{info_hash}"
        
        # Déterminer le type de stream
        if season and episode:
            stream_type = "series"
        else:
            stream_type = "movie"
        
        stream_url = await debrid_service.get_stream_link(
            magnet_link,
            stream_type,
            season=int(season) if season else None,
            episode=int(episode) if episode else None
        )
        
        if stream_url:
            logging.info(f"TorBox resolve: Redirecting to: {stream_url}")
            raise web.HTTPMovedPermanently(finalize_stream_url(stream_url, config))
        else:
            logging.error(f"TorBox resolve: Failed to get stream URL for hash {info_hash}")
            return web.Response(status=404, text="Could not resolve TorBox stream")
    
    # === MODE DebridLink ===
    elif service_name == 'debridlink':
        logging.info(f"DebridLink resolve: Starting with hash={info_hash}, season={season}, episode={episode}")
        
        debridlink_key = config.get('debridlink_key')
        if not debridlink_key:
            return web.Response(status=400, text="DebridLink not configured")
        
        debrid_service = DebridLinkService(debridlink_key)
        
        stream_url = await debrid_service.unlock_magnet(
            info_hash,
            season=int(season) if season else None,
            episode=int(episode) if episode else None,
            media_type=media_type
        )
        
        if stream_url:
            logging.info(f"DebridLink resolve: Redirecting to: {stream_url}")
            raise web.HTTPMovedPermanently(finalize_stream_url(stream_url, config))
        else:
            logging.error(f"DebridLink resolve: Failed to get stream URL for hash {info_hash}")
            return web.Response(status=404, text="Could not resolve DebridLink stream")
    
    # === MODE Real-Debrid ===
    elif service_name == 'realdebrid':
        logging.info(f"Real-Debrid resolve: Starting with hash={info_hash}, season={season}, episode={episode}")
        
        realdebrid_key = config.get('realdebrid_key')
        if not realdebrid_key:
            return web.Response(status=400, text="Real-Debrid not configured")
        
        debrid_service = RealDebridService(realdebrid_key)
        
        stream_url = await debrid_service.unlock_magnet(
            info_hash,
            season=int(season) if season else None,
            episode=int(episode) if episode else None,
            media_type=media_type
        )
        
        if stream_url:
            logging.info(f"Real-Debrid resolve: Redirecting to: {stream_url}")
            raise web.HTTPMovedPermanently(finalize_stream_url(stream_url, config))
        else:
            logging.error(f"Real-Debrid resolve: Failed to get stream URL for hash {info_hash}")
            return web.Response(status=404, text="Could not resolve Real-Debrid stream")
    
    else:
        return web.Response(status=400, text=f"Unknown service: {service_name}")

async def handle_qbit_stream(request):
    """
    Proxy de streaming pièce-conscient pour qBittorrent.
    Pour chaque Range request, attend que les pièces correspondantes soient téléchargées
    avant de servir — évite de servir des zéros (fichier pré-alloué non encore rempli).
    """
    import re as _re
    import mimetypes

    config_str = request.match_info.get('config', '')
    config = decode_config(config_str)
    if not config:
        return web.Response(status=400, text="Invalid config")

    info_hash = request.match_info.get('hash', '').lower()
    rel_path = urlunquote(request.match_info.get('path', ''))
    local_path = os.path.join(QBIT_PROXY_DIR, rel_path)

    if not os.path.exists(local_path):
        logging.warning(f"qfile: not found: {local_path}")
        return web.Response(status=404, text="File not found")

    file_size = os.path.getsize(local_path)

    # Parse du Range header
    range_header = request.headers.get('Range', '')
    start, end, is_range = 0, file_size - 1, False
    if range_header:
        m = _re.match(r'bytes=(\d*)-(\d*)', range_header)
        if m:
            is_range = True
            s, e = m.group(1), m.group(2)
            start = int(s) if s else 0
            end = int(e) if e else file_size - 1
    end = min(end, file_size - 1)
    length = end - start + 1

    # Récupérer piece_size une fois pour le streaming pièce-par-pièce
    loop = asyncio.get_event_loop()
    qbit_service = None
    piece_size = None
    qbit_config = config.get('qbittorrent')
    if qbit_config and info_hash:
        try:
            qbit_service = QBittorrentService(
                host=qbit_config['host'],
                username=qbit_config.get('username', ''),
                password=qbit_config.get('password', ''),
                public_url_base=qbit_config.get('public_url', '')
            )
            piece_size = await loop.run_in_executor(None, qbit_service.get_piece_size, info_hash)
        except Exception as e:
            logging.warning(f"qfile init error: {e}")

    content_type, _ = mimetypes.guess_type(local_path)
    content_type = content_type or 'application/octet-stream'

    headers = {
        'Accept-Ranges': 'bytes',
        'Content-Length': str(length),
        'Content-Type': content_type,
    }
    if is_range:
        headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'

    if request.method == 'HEAD':
        return web.Response(status=206 if is_range else 200, headers=headers)

    response = web.StreamResponse(status=206 if is_range else 200, headers=headers)
    await response.prepare(request)

    try:
        async with aiofiles.open(local_path, 'rb') as f:
            await f.seek(start)
            pos = start
            remaining = length
            while remaining > 0:
                # Attendre que la pièce courante soit téléchargée avant de la servir.
                # On attend pièce par pièce pour envoyer les données au fur et à mesure
                # du téléchargement, sans jamais servir de zéros (preallocated).
                if piece_size and qbit_service and qbit_service.client:
                    current_piece = pos // piece_size
                    deadline = loop.time() + 30

                    def _piece_ready(p=current_piece):
                        try:
                            states = qbit_service.client.torrents_piece_states(torrent_hash=info_hash)
                            return bool(states and len(states) > p and states[p] == 2)
                        except Exception:
                            return True
                    while loop.time() < deadline:
                        ready = await loop.run_in_executor(None, _piece_ready)
                        if ready:
                            break
                        await asyncio.sleep(0.1)

                # Lire jusqu'à la fin de la pièce courante (ou fin du range)
                if piece_size:
                    current_piece = pos // piece_size
                    piece_end = (current_piece + 1) * piece_size
                    to_read = min(remaining, piece_end - pos, 65536)
                else:
                    to_read = min(remaining, 65536)

                chunk = await f.read(to_read)
                if not chunk:
                    break
                await response.write(chunk)
                pos += len(chunk)
                remaining -= len(chunk)
        await response.write_eof()
    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
        pass  # Normal: le player a fermé la connexion (seek ou fin de buffer)
    return response


def _qbit_proxy_url(request, config_str, info_hash, stream_url):
    """
    Si QBIT_PROXY_DIR est défini, remplace l'URL du fileserver par le proxy Frenchio.
    Sinon, retourne l'URL directe inchangée.
    """
    if not QBIT_PROXY_DIR or not stream_url:
        return stream_url
    parsed = urlparse(stream_url)
    file_path = parsed.path.lstrip('/')
    host_url = f"{request.scheme}://{request.host}"
    return f"{host_url}/{config_str}/qfile/{info_hash}/{file_path}"


async def get_app():
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get('/', handle_configure)
    app.router.add_get('/configure', handle_configure)
    app.router.add_get('/manifest.json', handle_manifest_no_config)
    app.router.add_get('/stream/{type}/{id}.json', handle_stream_no_config)
    app.router.add_get('/{config}/', handle_configure) # Nouvelle route pour config pré-remplie
    app.router.add_get('/{config}/configure', handle_configure) # Nouvelle route pour config pré-remplie
    app.router.add_get('/{config}/manifest.json', handle_manifest)
    app.router.add_get('/{config}/stream/{type}/{id}.json', handle_stream)
    
    # Routes de résolution (avec config)
    app.router.add_get('/{config}/resolve/{service}/{hash}', handle_resolve)

    # Proxy de streaming qBittorrent (pièce-conscient)
    app.router.add_get('/{config}/qfile/{hash}/{path:.*}', handle_qbit_stream)
    app.router.add_route('HEAD', '/{config}/qfile/{hash}/{path:.*}', handle_qbit_stream)
    
    # Anciennes routes (compatibilité)
    app.router.add_get('/resolve/{service}/{api_key}/{hash}', handle_resolve)
    app.router.add_get('/resolve/{api_key}/{hash}', handle_resolve)
    
    return app

if __name__ == '__main__':
    web.run_app(
        get_app(),
        host='0.0.0.0',
        port=7777
    )
