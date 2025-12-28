"""
Frenchio - Stremio Addon
=========================

A powerful Stremio addon for searching and streaming content from multiple
French private/semi-private trackers with AllDebrid integration and qBittorrent
fallback for non-cached torrents.

Features:
    - Multi-tracker search (UNIT3D, Sharewood, YGGTorrent)
    - AllDebrid instant caching detection
    - qBittorrent sequential streaming for non-cached torrents
    - Intelligent episode selection in season packs
    - Parallel API requests for maximum speed
    - Automatic magnet cleanup

Author: Frenchio Contributors
License: MIT
Repository: https://github.com/yourusername/frenchio
"""

import base64
import json
import os
import logging
import aiohttp
from aiohttp import web
import aiofiles
import asyncio
from services.tmdb import TMDBService
from services.unit3d import Unit3DService
from services.alldebrid import AllDebridService
from services.torbox import TorBoxService
from services.sharewood import SharewoodService
from services.ygg import YggService
from services.qbittorrent import QBittorrentService
from utils import format_size, parse_torrent_name, check_season_episode

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

# Configuration des fonctionnalités
QBITTORRENT_ENABLE = os.getenv('QBITTORRENT_ENABLE', 'true').lower() in ('true', '1', 'yes')
MANIFEST_TITLE_SUFFIX = os.getenv('MANIFEST_TITLE_SUFFIX', '')
MANIFEST_BLURB = os.getenv('MANIFEST_BLURB', '')

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
        async with aiofiles.open('templates/configure.html', mode='r') as f:
            content = await f.read()
        
        # Injection de la config pré-remplie dans le JS
        # On cherche une balise script ou on l'ajoute
        # Le plus simple : remplacer une variable placeholder
        content = content.replace('const prefillConfig = {};', f'const prefillConfig = {prefill_data};')
        
        # Injection de la variable QBITTORRENT_ENABLE
        qbit_enabled_js = 'true' if QBITTORRENT_ENABLE else 'false'
        content = content.replace('const qbittorrentEnabled = true;', f'const qbittorrentEnabled = {qbit_enabled_js};')
        
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
    
    # Construction de la description avec blurb optionnel
    description = "Stream from French Trackers (UNIT3D, Sharewood, YGG) via AllDebrid, TorBox ou qBittorrent"
    if MANIFEST_BLURB:
        description += f"\n\n{MANIFEST_BLURB}"

    manifest = {
        "id": "community.aymene69.frenchio",
        "version": "1.0.0",
        "name": addon_name,
        "description": description,
        "icon": "https://i.imgur.com/tVjqEJP.png", # Icône générique ou à changer
        "types": ["movie", "series"],
        "catalogs": [],
        "resources": ["stream"],
        # "idPrefixes": ["tt"], # Supprimé car inutile si catalogs vide
        "behaviorHints": {
            "configurable": True,
        }
    }
    return web.json_response(manifest)

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
    
    if config.get('alldebrid_key') and config['alldebrid_key'].strip():
        alldebrid_service = AllDebridService(config['alldebrid_key'])
        logging.info("AllDebrid service initialized")
    
    if config.get('torbox_key') and config['torbox_key'].strip():
        torbox_service = TorBoxService(config['torbox_key'])
        logging.info("TorBox service initialized")
    
    if not alldebrid_service and not torbox_service:
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
    if not alldebrid_service and not torbox_service and not qbit_service:
        logging.error("No debrid or torrent client configured!")
        return web.json_response({"streams": []})
    
    unit3d_results = []
    sharewood_results = []

    # 1. Info Média (pour Sharewood) et Conversion ID (pour UNIT3D)
    # On a besoin des infos textuelles pour Sharewood
    # On a besoin du TMDB ID pour UNIT3D
    
    # Étape 1 : Find by IMDB ID
    tmdb_id = await tmdb_service.get_tmdb_id(imdb_id, stream_type)
    
    # Étape 1.5 : Récupérer Titre/Année si Sharewood configuré
    media_info = None
    if config.get('sharewood_passkey'):
        # On a besoin des détails pour le titre
        if tmdb_id:
             async with aiohttp.ClientSession(trust_env=True) as session:
                url = f"https://api.themoviedb.org/3/{'movie' if stream_type == 'movie' else 'tv'}/{tmdb_id}"
                params = {"api_key": config['tmdb_key'], "language": "fr-FR"} 
                # Sharewood est FR, donc on force le titre FR
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        media_info = await resp.json()

    # 2. Recherche Parallèle (UNIT3D + Sharewood)
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

    # Tâche Sharewood
    if config.get('sharewood_passkey') and media_info:
        logging.info("Starting Sharewood search")
        sharewood_service = SharewoodService(config.get('sharewood_passkey'))
        
        title = media_info.get('title') or media_info.get('name')
        
        # Année
        date = media_info.get('release_date') or media_info.get('first_air_date')
        year = date.split('-')[0] if date else ""
        
        if stream_type == 'movie':
            tasks.append(sharewood_service.search_movie(title, year))
        elif stream_type == 'series':
            tasks.append(sharewood_service.search_series(title, season, episode))
    else:
        if not config.get('sharewood_passkey'):
            logging.info("Sharewood search skipped (no passkey configured)")
        elif not media_info:
            logging.info("Sharewood search skipped (media info not found for title)")
            
        async def empty(): return []
        tasks.append(empty())

    # Tâche YGG
    if config.get('ygg_passkey'):
        logging.info("Starting YGG search")
        # URL API par défaut, configurable si besoin via config['ygg_url']
        ygg_service = YggService(config.get('ygg_passkey'))
        
        title = media_info.get('title') if media_info else ""
        year = ""
        if media_info:
            date = media_info.get('release_date') or media_info.get('first_air_date')
            year = date.split('-')[0] if date else ""

        if stream_type == 'movie':
            tasks.append(ygg_service.search_movie(title, year, tmdb_id=tmdb_id))
        elif stream_type == 'series':
            tasks.append(ygg_service.search_series(title, season, episode, tmdb_id=tmdb_id))
    else:
        async def empty(): return []
        tasks.append(empty())

    # Exécution
    results_list = await asyncio.gather(*tasks)
    unit3d_results = results_list[0]
    sharewood_results = results_list[1] if len(results_list) > 1 else []
    ygg_results = results_list[2] if len(results_list) > 2 else []
    
    logging.info(f"Results breakdown: UNIT3D={len(unit3d_results)}, Sharewood={len(sharewood_results)}, YGG={len(ygg_results)}")
    
    # Fusion et Déduplication
    all_torrents = unit3d_results + sharewood_results + ygg_results
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
                
            # Si UNIT3D renvoie un résultat sans ID, on vérifie le titre au lieu de jeter
            if (not res_tmdb or str(res_tmdb) == "0") and (not res_imdb or str(res_imdb) == "0"):
                 if not is_relevant(t, None, None, ref_title):
                     # logging.info(f"Filtered UNIT3D (No IDs & Wrong Title): {t.get('name')}")
                     continue

        # Filtrage Série (SxxExx)
        # Si c'est une série, on vérifie que le titre correspond à la saison/épisode demandé
        # pour éviter d'afficher E03 quand on veut E07 (souvent le cas avec recherche floue)
        if stream_type == 'series' and season is not None:
            if not check_season_episode(t.get('name', ''), season, episode):
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

    logging.info(f"Total unique torrents (UNIT3D + Sharewood + YGG): {len(torrents)}")

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
        else:
            clean_hash = info_hash.lower().strip()
            is_cached = False
        
        if is_cached:
            cached_torrents.append((torrent, clean_hash))
        else:
            uncached_torrents.append((torrent, clean_hash))
    
    logging.info(f"Cached: {len(cached_torrents)}, Uncached: {len(uncached_torrents)}")
    
    # 4a. Streams débridés (cachés)
    for torrent, clean_hash in cached_torrents:
        source_prefix = "[Sharewood]" if torrent.get('source') == 'sharewood' else \
                       "[YGG]" if torrent.get('source') == 'ygg' else \
                       f"[{torrent.get('tracker_name', 'UNIT3D')}]"
        
        size_str = format_size(torrent.get('size', 0))
        extra_info = parse_torrent_name(torrent.get('name', ''))
        
        provider_emoji = "⚡"  # Éclair pour tous les services de débridage
        title = f"{provider_emoji} {extra_info}\n{torrent.get('name')}\n💾 {size_str} - {source_prefix}"
        
        # URL de résolution (utilise le provider configuré)
        resolve_url = f"{host_url}/{config_str}/resolve/{debrid_provider}/{clean_hash}"
        
        if season is not None and episode is not None:
            resolve_url += f"?season={season}&episode={episode}"
        elif stream_type == 'movie':
            resolve_url += "?type=movie"

        streams.append({
            "name": "Frenchio",
            "title": title,
            "url": resolve_url
        })
    
    # 4b. Streams qBittorrent (non cachés, si configuré)
    # Si on a des torrents cachés, on n'affiche pas les non-cachés
    if qbit_service and uncached_torrents:
        if cached_torrents:
            logging.info(f"qBittorrent: Skipping {len(uncached_torrents)} uncached torrents (cached results available)")
        else:
            limit = 10 if (alldebrid_service or torbox_service) else 25  # Plus de résultats si pas de debrid
            logging.info(f"qBittorrent: Processing {min(len(uncached_torrents), limit)} torrents (out of {len(uncached_torrents)} available)")
            
            qbit_added = 0
            for torrent, clean_hash in uncached_torrents[:limit]:
                download_link = torrent.get('link') or torrent.get('download_link')
                if not download_link:
                    logging.debug(f"Skipping torrent without download link: {torrent.get('name')}")
                    continue
                
                source_prefix = "[Sharewood]" if torrent.get('source') == 'sharewood' else \
                               "[YGG]" if torrent.get('source') == 'ygg' else \
                               f"[{torrent.get('tracker_name', 'UNIT3D')}]"
                
                size_str = format_size(torrent.get('size', 0))
                extra_info = parse_torrent_name(torrent.get('name', ''))
                
                # Indicateur qBittorrent
                title = f"📥 {extra_info}\n{torrent.get('name')}\n💾 {size_str} - {source_prefix} [qBittorrent]"
                
                import urllib.parse
                encoded_link = urllib.parse.quote(download_link, safe='')
                
                # On passe la config encodée pour avoir accès aux credentials qBittorrent
                resolve_url = f"{host_url}/{config_str}/resolve/qbit/{clean_hash}?link={encoded_link}"
                
                if season is not None and episode is not None:
                    resolve_url += f"&season={season}&episode={episode}"
                elif stream_type == 'movie':
                    resolve_url += "&type=movie"

                streams.append({
                    "name": "Frenchio",
                    "title": title,
                    "url": resolve_url
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
        
        # Décoder le lien
        import urllib.parse
        download_link = urllib.parse.unquote(download_link)
        
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
        
        # Télécharger le .torrent
        logging.info(f"Downloading torrent from: {download_link[:100]}...")
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
            logging.info(f"qBittorrent stream ready: {stream_url}")
            raise web.HTTPFound(stream_url)
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
            raise web.HTTPFound(stream_url)
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
            raise web.HTTPFound(stream_url)
        else:
            logging.error(f"TorBox resolve: Failed to get stream URL for hash {info_hash}")
            return web.Response(status=404, text="Could not resolve TorBox stream")
    
    else:
        return web.Response(status=400, text=f"Unknown service: {service_name}")

async def get_app():
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get('/', handle_configure)
    app.router.add_get('/configure', handle_configure)
    app.router.add_get('/{config}/', handle_configure) # Nouvelle route pour config pré-remplie
    app.router.add_get('/{config}/configure', handle_configure) # Nouvelle route pour config pré-remplie
    app.router.add_get('/{config}/manifest.json', handle_manifest)
    app.router.add_get('/{config}/stream/{type}/{id}.json', handle_stream)
    
    # Routes de résolution (avec config)
    app.router.add_get('/{config}/resolve/{service}/{hash}', handle_resolve)
    
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