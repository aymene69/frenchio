import aiohttp
import asyncio
import logging
import json
from urllib.parse import urlencode

class Unit3DService:
    def __init__(self, trackers_config):
        """
        trackers_config: liste de dicts {url, token, categories}
        """
        self.trackers = trackers_config

    async def search_tracker(self, session, tracker, query_params):
        url = f"{tracker['url']}/api/torrents/filter"
        params = {
            "api_token": tracker['token'],
            **query_params
        }
        
        # On ignore les catégories comme demandé
        if 'categories' in params:
            del params['categories']
            
        # Construction de la query string standard
        query_string = urlencode(params)
        full_url = f"{url}?{query_string}"
        
        # Masquage du token pour les logs
        log_url = full_url.replace(tracker['token'], '***TOKEN***')
        logging.info(f"[{tracker['url']}] Requesting: {log_url}")

        try:
            async with session.get(full_url, timeout=15) as response:
                logging.info(f"[{tracker['url']}] Status: {response.status}")
                
                if response.status == 200:
                    text_data = await response.text()
                    # Log plus court pour ne pas spammer si grosse réponse, mais suffisant pour voir le format
                    logging.info(f"[{tracker['url']}] Raw Response Start: {text_data[:200]} ...")
                    
                    try:
                        data = json.loads(text_data)
                    except json.JSONDecodeError as e:
                        logging.error(f"[{tracker['url']}] JSON Decode Error: {e}")
                        return []

                    results = []
                    if isinstance(data, dict):
                        if 'data' in data and isinstance(data['data'], list):
                            results = data['data']
                        else:
                            # Cas où data serait directement la liste ou autre structure
                            # logging.warning(f"[{tracker['url']}] Structure 'data' list not found. Keys: {data.keys()}")
                            pass
                    elif isinstance(data, list):
                        results = data
                    
                    logging.info(f"[{tracker['url']}] Found {len(results)} items for params {query_params}")

                    cleaned_results = []
                    for res in results:
                        item = res
                        if 'attributes' in res:
                            item = {**res, **res['attributes']}
                        
                        item['tracker_name'] = tracker['url']
                        
                        # Extraction du lien de téléchargement pour qBittorrent
                        # Format typique: {"download_link": "https://tracker.com/torrents/download/123?api_token=xxx"}
                        if 'download_link' in item:
                            item['link'] = item['download_link']
                        elif 'download_link' in res.get('attributes', {}):
                            item['link'] = res['attributes']['download_link']
                        
                        cleaned_results.append(item)
                        
                    return cleaned_results
                else:
                    logging.warning(f"[{tracker['url']}] Error Status: {response.status}")
                    # text = await response.text()
                    # logging.warning(f"[{tracker['url']}] Error Body: {text[:200]}")

        except Exception as e:
            logging.error(f"[{tracker['url']}] Exception: {e}")
            # Traceback complet inutile si c'est juste un timeout ou connection error fréquent
            # import traceback
            # logging.error(traceback.format_exc())
            pass
            
        return []

    async def download_torrent(self, session, download_url):
        """Télécharge le fichier .torrent depuis l'URL fournie"""
        # download_url contient souvent déjà l'api_token
        try:
            async with session.get(download_url) as resp:
                if resp.status == 200:
                    return await resp.read()
                logging.error(f"UNIT3D Download Error: {resp.status}")
        except Exception as e:
            logging.error(f"UNIT3D Download Exception: {e}")
        return None

    async def search_all(self, tmdb_id=None, imdb_id=None, type=None, season=None, episode=None):
        tasks = []
        
        # Préparation des paramètres
        params_list = []
        
        # 1. Recherche Standard (Saison + Episode si dispo)
        base_params = {}
        if type == 'series' and season is not None:
            base_params['seasonNumber'] = season
            if episode is not None:
                base_params['episodeNumber'] = episode
        params_list.append(base_params)
        
        # 2. Recherche Pack Saison (Saison sans Episode)
        # Si on a un épisode, on ajoute aussi une recherche pour la saison entière pour trouver les packs
        if type == 'series' and season is not None and episode is not None:
            pack_params = {'seasonNumber': season}
            params_list.append(pack_params)

        async with aiohttp.ClientSession() as session:
            for tracker in self.trackers:
                for common_params in params_list:
                    # Recherche TMDB
                    if tmdb_id:
                        params_tmdb = {'tmdbId': tmdb_id, **common_params}
                        tasks.append(self.search_tracker(session, tracker, params_tmdb))
                    
                    # Recherche IMDB
                    if imdb_id:
                        # Certains trackers UNIT3D attendent l'ID sans 'tt'
                        clean_imdb = imdb_id.replace('tt', '')
                        params_imdb = {'imdbId': clean_imdb, **common_params}
                        tasks.append(self.search_tracker(session, tracker, params_imdb))
            
            logging.info(f"Launching {len(tasks)} search tasks across {len(self.trackers)} trackers")
            
            # Exécution parallèle de toutes les requêtes
            responses = await asyncio.gather(*tasks)
            
            # Aplatir les résultats
            all_results = []
            for resp in responses:
                all_results.extend(resp)
        
        # Filtrage et déduplication
        unique_results = {} # info_hash -> data
        for res in all_results:
            info_hash = res.get('info_hash') or res.get('attributes', {}).get('info_hash')
            
            if info_hash:
                if info_hash not in unique_results:
                    unique_results[info_hash] = res
            else:
                pass
                # logging.debug("Item without info_hash ignored")
        
        logging.info(f"Total unique torrents found after deduplication: {len(unique_results)}")
        return list(unique_results.values())
