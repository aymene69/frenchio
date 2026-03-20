# “””
Frenchio - Stremio Addon

A powerful Stremio addon for searching and streaming content from multiple
French private/semi-private trackers with AllDebrid integration and qBittorrent
fallback for non-cached torrents.

Features:
- Multi-tracker search (UNIT3D, Sharewood, YGGTorrent, ABNormal)
- AllDebrid instant caching detection
- qBittorrent sequential streaming for non-cached torrents
- Intelligent episode selection in season packs
- Parallel API requests for maximum speed
- Automatic magnet cleanup

Author: Frenchio Contributors
License: MIT
Repository: https://github.com/aymene69/frenchio
“””

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
from services.debridlink import DebridLinkService
from services.realdebrid import RealDebridService
from services.premiumize import PremiumizeService
from services.sharewood import SharewoodService
from services.ygg import YggService
from services.abn import ABNService
from services.lacale import LaCaleService
from services.c411 import C411Service
from services.torr9 import Torr9Service
from services.qbittorrent import QBittorrentService
from utils import format_size, parse_torrent_name, check_season_episode, check_title_match, is_video_file

# Configuration du logging

logging.basicConfig(
level=logging.INFO,
format=’%(levelname)s:%(name)s:%(message)s’
)

# Configuration du proxy (HTTP_PROXY, HTTPS_PROXY)

HTTP_PROXY = os.getenv(‘HTTP_PROXY’) or os.getenv(‘http_proxy’)
HTTPS_PROXY = os.getenv(‘HTTPS_PROXY’) or os.getenv(‘https_proxy’)

if HTTP_PROXY or HTTPS_PROXY:
logging.info(f”Proxy configuration detected:”)
if HTTP_PROXY:
logging.info(f”  HTTP_PROXY: {HTTP_PROXY}”)
if HTTPS_PROXY:
logging.info(f”  HTTPS_PROXY: {HTTPS_PROXY}”)

# Version de l’application

APP_VERSION = “1.4.7”

# Stremio Addons Config (signature)

STREMIO_ADDONS_CONFIG = {
“issuer”: “https://stremio-addons.net”,
“signature”: “eyJhbGciOiJkaXIiLCJlbmMiOiJBMTI4Q0JDLUhTMjU2In0..9l2RL_spVPK81eoy5BUkDg.efNcrE-IQ2DOoYtul30Y1bf3YuCxW8imVaKluLvX2ThwHlgi14rEajndgvRKjVDv57fazbZncm3uySZvqyi_OpQCb5tTHZJcxwD1uhdO5hXDwgSV25T-eOV8tnhnFhNd.0o5__kzn1_ygVSGX7whq3A”
}

# Configuration des fonctionnalités

QBITTORRENT_ENABLE = os.getenv(‘QBITTORRENT_ENABLE’, ‘true’).lower() in (‘true’, ‘1’, ‘yes’)
MANIFEST_TITLE_SUFFIX = os.getenv(‘MANIFEST_TITLE_SUFFIX’, ‘’)
MANIFEST_BLURB = os.getenv(‘MANIFEST_BLURB’, ‘’)

logging.info(f”qBittorrent enabled: {QBITTORRENT_ENABLE}”)
if MANIFEST_TITLE_SUFFIX:
logging.info(f”Manifest title suffix: {MANIFEST_TITLE_SUFFIX}”)
if MANIFEST_BLURB:
logging.info(f”Manifest blurb configured”)

# ============================================================================

# Middleware

# ============================================================================

@web.middleware
async def cors_middleware(request, handler):
response = await handler(request)
response.headers[‘Access-Control-Allow-Origin’] = ‘*’
response.headers[‘Access-Control-Allow-Methods’] = ‘GET, POST, OPTIONS’
response.headers[‘Access-Control-Allow-Headers’] = ‘Content-Type, Authorization’
return response

# ============================================================================

# Configuration Handlers

# ============================================================================

async def handle_configure(request):
config_str = request.match_info.get(‘config’, ‘’)
prefill_data = “{}”

```
if config_str:
    try:
        decoded = decode_config(config_str)
        if decoded:
            prefill_data = json.dumps(decoded)
    except:
        pass

try:
    async with aiofiles.open('templates/configure.html', mode='r') as f:
        content = await f.read()
    
    content = content.replace('const prefillConfig = {};', f'const prefillConfig = {prefill_data};')
    
    qbit_enabled_js = 'true' if QBITTORRENT_ENABLE else 'false'
    content = content.replace('const qbittorrentEnabled = true;', f'const qbittorrentEnabled = {qbit_enabled_js};')
    
    blurb_escaped = json.dumps(MANIFEST_BLURB) if MANIFEST_BLURB else '""'
    content = content.replace('const manifestBlurb = "";', f'const manifestBlurb = {blurb_escaped};')
    
    content = content.replace('const appVersion = "1.1.0";', f'const appVersion = "{APP_VERSION}";')
    
    return web.Response(text=content, content_type='text/html')
except Exception as e:
    return web.Response(text=str(e), status=500)
```

def decode_config(config_str):
try:
decoded = base64.b64decode(config_str).decode(‘utf-8’)
return json.loads(decoded)
except Exception as e:
logging.error(f”Config Decode Error: {e}”)
return None

async def handle_manifest(request):
config_str = request.match_info.get(‘config’, ‘’)
config = decode_config(config_str)

```
if not config:
    return web.Response(status=400, text="Invalid Config")

addon_name = "Frenchio"
if MANIFEST_TITLE_SUFFIX:
    addon_name += f" {MANIFEST_TITLE_SUFFIX}"

description = "Stream from French Trackers (UNIT3D, Sharewood, YGG, ABN, LaCale, C411, Torr9) via AllDebrid, TorBox, DebridLink, RealDebrid, Premiumize ou qBittorrent"

manifest = {
    "id": "community.aymene69.frenchio",
    "version": APP_VERSION,
    "name": addon_name,
    "description": description,
    "icon": "https://i.imgur.com/MgdGxnR.png",
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
```

async def handle_manifest_no_config(request):
addon_name = “Frenchio”
if MANIFEST_TITLE_SUFFIX:
addon_name += f” {MANIFEST_TITLE_SUFFIX}”

```
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
    "resources": ["stream"],
    "behaviorHints": {
        "configurable": True,
        "configurationRequired": True
    },
    "beyiond_support": True
}
return web.json_response(manifest)
```

async def handle_stream_no_config(request):
host_url = f”{request.scheme}://{request.host}”
config_url = f”{host_url}/configure”

```
return web.json_response({
    "streams": [{
        "name": "Configure l'addon",
        "title": "⚙️ Configure Frenchio (ouvre la page de configuration)",
        "externalUrl": config_url
    }]
})
```

async def handle_stream(request):
config_str = request.match_info.get(‘config’, ‘’)
config = decode_config(config_str)
if not config:
return web.json_response({“streams”: []})

```
stream_type = request.match_info.get('type')
stream_id = request.match_info.get('id')

imdb_id = stream_id
season = None
episode = None

if ":" in stream_id:
    parts = stream_id.split(":")
    imdb_id = parts[0]
    season = int(parts[1])
    episode = int(parts[2])

logging.info(f"Searching for {stream_type} {imdb_id} S{season}E{episode}")

tmdb_service = TMDBService(config['tmdb_key'])

alldebrid_service = None
torbox_service = None
debridlink_service = None
realdebrid_service = None
premiumize_service = None

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

if config.get('premiumize_key') and config['premiumize_key'].strip():
    premiumize_service = PremiumizeService(config['premiumize_key'])
    logging.info("Premiumize service initialized")

if not alldebrid_service and not torbox_service and not debridlink_service and not realdebrid_service and not premiumize_service:
    logging.info("No debrid service configured, using qBittorrent fallback")

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
        
        try:
            qbit_service.test_connection()
        except Exception as e:
            logging.error(f"qBittorrent test failed: {e}")
    else:
        logging.warning("qBittorrent config incomplete, skipping")
elif not QBITTORRENT_ENABLE:
    logging.info("qBittorrent disabled by QBITTORRENT_ENABLE environment variable")

if not alldebrid_service and not torbox_service and not debridlink_service and not realdebrid_service and not premiumize_service and not qbit_service:
    logging.error("No debrid or torrent client configured!")
    return web.json_response({"streams": []})

unit3d_results = []
sharewood_results = []

tmdb_id = await tmdb_service.get_tmdb_id(imdb_id, stream_type)

media_info = None
needs_media_info = True

if needs_media_info:
    if tmdb_id:
         async with aiohttp.ClientSession(trust_env=True) as session:
            url = f"https://api.themoviedb.org/3/{'movie' if stream_type == 'movie' else 'tv'}/{tmdb_id}"
            params = {"api_key": config['tmdb_key'], "language": "fr-FR"}
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    media_info = await resp.json()

tasks = []

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

if config.get('sharewood_passkey') and media_info:
    logging.info("Starting Sharewood search")
    sharewood_service = SharewoodService(config.get('sharewood_passkey'))
    
    title = media_info.get('title') or media_info.get('name')
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

ygg_service = YggService()

target_title = (media_info.get('title') or media_info.get('name')) if media_info else ""
original_title = (media_info.get('original_title') or media_info.get('original_name')) if media_info else ""
year = ""
if media_info:
    date = media_info.get('release_date') or media_info.get('first_air_date')
    year = date.split('-')[0] if date else ""

if stream_type == 'movie':
    tasks.append(ygg_service.search_movie(target_title, year, original_title=original_title))
elif stream_type == 'series':
    tasks.append(ygg_service.search_series(target_title, season, episode, original_title=original_title))

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

lacale_key = config.get('lacale_apikey') or config.get('lacale_passkey')
if lacale_key:
    logging.info("Starting LaCale search")
    lacale_service = LaCaleService(lacale_key)
    if stream_type == 'movie':
        tasks.append(lacale_service.search_movie(target_title, year, tmdb_id=tmdb_id, imdb_id=imdb_id))
    elif stream_type == 'series':
        tasks.append(lacale_service.search_series(target_title, season, episode, tmdb_id=tmdb_id, imdb_id=imdb_id))
else:
    async def empty(): return []
    tasks.append(empty())

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

try:
    results_list = await asyncio.gather(*tasks)
    unit3d_results = results_list[0]
    for t in unit3d_results:
        t['source'] = 'unit3d'
        
    sharewood_results = results_list[1] if len(results_list) > 1 else []
    ygg_results = results_list[2] if len(results_list) > 2 else []
    abn_results = results_list[3] if len(results_list) > 3 else []
    lacale_results = results_list[4] if len(results_list) > 4 else []
    c411_results = results_list[5] if len(results_list) > 5 else []
    torr9_results = results_list[6] if len(results_list) > 6 else []
finally:
    if abn_service:
        await abn_service.close()

logging.info(f"Results breakdown: UNIT3D={len(unit3d_results)}, Sharewood={len(sharewood_results)}, YGG={len(ygg_results)}, ABN={len(abn_results)}, LaCale={len(lacale_results)}, C411={len(c411_results)}, Torr9={len(torr9_results)}")

all_torrents = unit3d_results + sharewood_results + ygg_results + abn_results + lacale_results + c411_results + torr9_results

max_size_gb = config.get('max_size', 0)
if max_size_gb > 0:
    max_size_bytes = max_size_gb * 1024 * 1024 * 1024
    before_filter = len(all_torrents)
    all_torrents = [t for t in all_torrents if t.get('size', 0) <= max_size_bytes]
    filtered_count = before_filter - len(all_torrents)
    if filtered_count > 0:
        logging.info(f"Filtered {filtered_count} torrents exceeding {max_size_gb} Go")

before_filter = len(all_torrents)
all_torrents = [t for t in all_torrents if is_video_file(t.get('name', ''))]
filtered_count = before_filter - len(all_torrents)
if filtered_count > 0:
    logging.info(f"Filtered {filtered_count} non-video files")

unique_torrents = {}

for t in all_torrents:
    if t.get('source') == 'unit3d':
        res_tmdb = t.get('tmdb_id') or t.get('tmdb')
        res_imdb = t.get('imdb_id') or t.get('imdb')
        
        if res_tmdb and str(res_tmdb) != "0" and tmdb_id and str(res_tmdb) != str(tmdb_id):
            continue
            
        if res_imdb and str(res_imdb) != "0" and imdb_id:
            clean_res = str(res_imdb).replace('tt', '')
            clean_req = str(imdb_id).replace('tt', '')
            if clean_res != clean_req:
                continue

    if stream_type in ('movie', 'series'):
        if not check_title_match(t.get('name', ''), target_title, original_title, year=year, is_movie=(stream_type == 'movie')):
            continue

    if stream_type == 'series' and season is not None:
        if not check_season_episode(t.get('name', ''), season, episode):
            continue

    ih = t.get('info_hash')
    if ih:
        ih = ih.lower()
        if ih not in unique_torrents:
            unique_torrents[ih] = t
        
torrents = list(unique_torrents.values())

if not torrents:
    return web.json_response({"streams": []})

logging.info(f"Total unique torrents: {len(torrents)}")

streams = []
host_url = f"{request.scheme}://{request.host}"

availability = {}
debrid_provider = None

if alldebrid_service:
    hashes = [t['info_hash'] for t in torrents if t.get('info_hash')]
    availability = await alldebrid_service.check_availability(hashes)
    debrid_provider = "alldebrid"
    logging.info(f"AllDebrid: {len([v for v in availability.values() if v])} cached torrents")

elif torbox_service:
    hashes = [t['info_hash'] for t in torrents if t.get('info_hash')]
    results = await asyncio.gather(
        *[torbox_service.check_availability(h) for h in hashes],
        return_exceptions=True
    )
    for h, result in zip(hashes, results):
        if not isinstance(result, Exception) and result:
            availability[h] = result
    debrid_provider = "torbox"
    logging.info(f"TorBox: {len([v for v in availability.values() if v])} cached torrents")

elif debridlink_service:
    hashes = [t['info_hash'] for t in torrents if t.get('info_hash')]
    availability = await debridlink_service.check_availability(hashes)
    debrid_provider = "debridlink"
    logging.info(f"DebridLink: {len([v for v in availability.values() if v])} cached torrents")

elif realdebrid_service:
    hashes = [t['info_hash'] for t in torrents if t.get('info_hash')]
    availability = await realdebrid_service.check_availability(hashes)
    debrid_provider = "realdebrid"
    logging.info(f"Real-Debrid: {len([v for v in availability.values() if v])} cached torrents")

elif premiumize_service:
    hashes = [t['info_hash'] for t in torrents if t.get('info_hash')]
    availability = await premiumize_service.check_availability(hashes)
    debrid_provider = "premiumize"
    logging.info(f"Premiumize: {len([v for v in availability.values() if v])} cached torrents")

cached_torrents = []
uncached_torrents = []

for torrent in torrents:
    info_hash = torrent.get('info_hash')
    if not info_hash:
        continue
        
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
    elif premiumize_service:
        clean_hash = info_hash.lower().strip()
        is_cached = availability.get(clean_hash, False)
    else:
        clean_hash = info_hash.lower().strip()
        is_cached = False
    
    if is_cached:
        cached_torrents.append((torrent, clean_hash))
    else:
        uncached_torrents.append((torrent, clean_hash))

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
    providers_order = config.get('providers_order', [])
    if providers_order:
        def get_sort_key(item):
            torrent, _ = item
            source = torrent.get('source', '')
            try:
                return providers_order.index(source)
            except ValueError:
                return len(providers_order)

        cached_torrents.sort(key=get_sort_key)
        uncached_torrents.sort(key=get_sort_key)

logging.info(f"Cached: {len(cached_torrents)}, Uncached: {len(uncached_torrents)}")

for torrent, clean_hash in cached_torrents:
    raw_tracker = torrent.get('tracker_name', 'UNIT3D')
    if raw_tracker.startswith('http'):
        from urllib.parse import urlparse
        domain = urlparse(raw_tracker).hostname or raw_tracker
        clean_name = domain.split('.')[0].capitalize()
    else:
        clean_name = raw_tracker

    source_prefix = "\n🌲 Sharewood" if torrent.get('source') == 'sharewood' else \
                   "\n🐝 YGG" if torrent.get('source') == 'ygg' else \
                   "\n🎬 ABN" if torrent.get('source') == 'abn' else \
                   "\n⚓ LaCale" if torrent.get('source') == 'lacale' else \
                   "\n📡 C411" if torrent.get('source') == 'c411' else \
                   "\n🔥 Torr9" if torrent.get('source') == 'torr9' else \
                   f"\n🌐 {clean_name}"
    
    size_str = format_size(torrent.get('size', 0))
    meta = parse_torrent_name(torrent.get('name', ''))
    
    provider_emoji = "⚡"
    title = f"{provider_emoji} {meta['name']}\n{torrent.get('name')}\n💾 {size_str}"
    
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

if qbit_service and uncached_torrents:
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
        limit = 10 if (alldebrid_service or torbox_service or debridlink_service or realdebrid_service or premiumize_service) else 25
        logging.info(f"qBittorrent: Processing {min(len(uncached_torrents), limit)} torrents")
        
        qbit_added = 0
        for torrent, clean_hash in uncached_torrents[:limit]:
            download_link = torrent.get('link') or torrent.get('download_link')
            if not download_link:
                continue
            
            raw_tracker = torrent.get('tracker_name', 'UNIT3D')
            if raw_tracker.startswith('http'):
                from urllib.parse import urlparse
                domain = urlparse(raw_tracker).hostname or raw_tracker
                clean_name = domain.split('.')[0].capitalize()
            else:
                clean_name = raw_tracker

            source_prefix = "🌲 Sharewood" if torrent.get('source') == 'sharewood' else \
                           "🐝 YGG" if torrent.get('source') == 'ygg' else \
                           "🎬 ABN" if torrent.get('source') == 'abn' else \
                           "⚓ LaCale" if torrent.get('source') == 'lacale' else \
                           "📡 C411" if torrent.get('source') == 'c411' else \
                           "🔥 Torr9" if torrent.get('source') == 'torr9' else \
                           f"🌐 {clean_name}"
            
            size_str = format_size(torrent.get('size', 0))
            meta = parse_torrent_name(torrent.get('name', ''))
            
            title = f"📥 {meta['name']}\n{torrent.get('name')}\n💾 {size_str} [qBittorrent]"
            
            import urllib.parse
            encoded_link = urllib.parse.quote(download_link, safe='')
            
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
```

async def handle_resolve(request):
config_str = request.match_info.get(‘config’, ‘’)
config = decode_config(config_str)

```
if not config:
    return web.Response(status=400, text="Invalid config")

service_name = request.match_info.get('service', 'alldebrid')
info_hash = request.match_info.get('hash')

season = request.query.get('season')
episode = request.query.get('episode')
media_type = request.query.get('type')

if service_name == 'qbit':
    download_link = request.query.get('link')
    if not download_link:
        return web.Response(status=400, text="Missing download link")
    
    import urllib.parse
    download_link = urllib.parse.unquote(download_link)
    
    qbit_config = config.get('qbittorrent')
    if not qbit_config:
        return web.Response(status=400, text="qBittorrent not configured")
    
    qbit_service = QBittorrentService(
        host=qbit_config['host'],
        username=qbit_config.get('username', ''),
        password=qbit_config.get('password', ''),
        public_url_base=qbit_config['public_url']
    )
    
    logging.info(f"Downloading torrent from: {download_link[:100]}...")
    
    if 'abn.lol' in download_link or 'abnormal.ws' in download_link:
        if config.get('abn_username') and config.get('abn_password'):
            abn_service = ABNService(
                username=config.get('abn_username'),
                password=config.get('abn_password')
            )
            try:
                torrent_data = await abn_service.download_torrent(download_link)
                if not torrent_data:
                    return web.Response(status=502, text="Failed to download torrent file from ABN")
            finally:
                await abn_service.close()
        else:
            return web.Response(status=400, text="ABN credentials required")
    else:
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.get(download_link) as resp:
                if resp.status != 200:
                    return web.Response(status=502, text="Failed to download torrent file")
                torrent_data = await resp.read()
    
    stream_url = qbit_service.manage_stream(
        torrent_data, 
        info_hash, 
        is_file=True,
        season=int(season) if season else None,
        episode=int(episode) if episode else None
    )
    
    if stream_url:
        raise web.HTTPFound(stream_url)
    else:
        return web.Response(status=404, text="Could not start qBittorrent stream")

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

elif service_name == 'torbox':
    logging.info(f"TorBox resolve: Starting with hash={info_hash}")
    
    torbox_key = config.get('torbox_key')
    if not torbox_key:
        return web.Response(status=400, text="TorBox not configured")
    
    debrid_service = TorBoxService(torbox_key)
    magnet_link = f"magnet:?xt=urn:btih:{info_hash}"
    
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
        raise web.HTTPFound(stream_url)
    else:
        return web.Response(status=404, text="Could not resolve TorBox stream")

elif service_name == 'debridlink':
    logging.info(f"DebridLink resolve: Starting with hash={info_hash}")
    
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
        raise web.HTTPFound(stream_url)
    else:
        return web.Response(status=404, text="Could not resolve DebridLink stream")

elif service_name == 'realdebrid':
    logging.info(f"Real-Debrid resolve: Starting with hash={info_hash}")
    
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
        raise web.HTTPFound(stream_url)
    else:
        return web.Response(status=404, text="Could not resolve Real-Debrid stream")

elif service_name == 'premiumize':
    logging.info(f"Premiumize resolve: Starting with hash={info_hash}")
    
    premiumize_key = config.get('premiumize_key')
    if not premiumize_key:
        return web.Response(status=400, text="Premiumize not configured")
    
    debrid_service = PremiumizeService(premiumize_key)
    
    stream_url = await debrid_service.unlock_magnet(
        info_hash,
        season=int(season) if season else None,
        episode=int(episode) if episode else None,
        media_type=media_type
    )
    
    if stream_url:
        logging.info(f"Premiumize resolve: Redirecting to stream")
        raise web.HTTPFound(stream_url)
    else:
        logging.error(f"Premiumize resolve: Failed to get stream URL for hash {info_hash}")
        return web.Response(status=404, text="Could not resolve Premiumize stream")

else:
    return web.Response(status=400, text=f"Unknown service: {service_name}")
```

async def get_app():
app = web.Application(middlewares=[cors_middleware])
app.router.add_get(’/’, handle_configure)
app.router.add_get(’/configure’, handle_configure)
app.router.add_get(’/manifest.json’, handle_manifest_no_config)
app.router.add_get(’/stream/{type}/{id}.json’, handle_stream_no_config)
app.router.add_get(’/{config}/’, handle_configure)
app.router.add_get(’/{config}/configure’, handle_configure)
app.router.add_get(’/{config}/manifest.json’, handle_manifest)
app.router.add_get(’/{config}/stream/{type}/{id}.json’, handle_stream)
app.router.add_get(’/{config}/resolve/{service}/{hash}’, handle_resolve)
app.router.add_get(’/resolve/{service}/{api_key}/{hash}’, handle_resolve)
app.router.add_get(’/resolve/{api_key}/{hash}’, handle_resolve)

```
return app
```

if **name** == ‘**main**’:
web.run_app(
get_app(),
host=‘0.0.0.0’,
port=7777
)
