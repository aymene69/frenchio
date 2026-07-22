import aiohttp
import logging
import urllib.parse
import xml.etree.ElementTree as ET
import re

class NekoBTService:
    def __init__(self, apikey):
        self.apikey = apikey
        self.base_url = "https://nekobt.to/api/torznab/api"

    async def search(self, params):
        if not self.apikey:
            return []

        params['apikey'] = self.apikey
        params['cat'] = '5070'  # Anime category for NekoBT
        params['t'] = 'search'  # Force generic search since NekoBT doesn't handle tmdbid well
        
        # Log request (masking apikey)
        log_params = params.copy()
        log_params['apikey'] = '***APIKEY***'
        logging.info(f"NekoBT Search: {self.base_url}?{urllib.parse.urlencode(log_params)}")

        async with aiohttp.ClientSession(trust_env=True) as session:
            try:
                async with session.get(self.base_url, params=params, timeout=20) as response:
                    if response.status == 200:
                        text = await response.text()
                        
                        try:
                            root = ET.fromstring(text)
                        except ET.ParseError as e:
                            logging.error(f"NekoBT XML Parse Error: {e}")
                            return []

                        items = root.findall('.//item')
                        logging.info(f"NekoBT found {len(items)} results")
                        
                        normalized = []
                        for res in items:
                            title = res.findtext('title')
                            description = res.findtext('description', default='')
                            
                            # Filtre strict FR : on rejette tout ce qui n'a pas de tag FR/VF/VOSTFR dans le titre ou la description
                            title_upper = (title or "").upper()
                            desc_upper = description.upper()
                            
                            has_fr_in_title = any(kw in title_upper for kw in ["FRENCH", "VOSTFR", "SUBFRENCH", "TRUEFRENCH", "VFF", "VF2", "VFQ"]) or re.search(r'\bVF\b', title_upper) or re.search(r'\bFR\b', title_upper)
                            has_fr_in_desc = any(kw in desc_upper for kw in ["FRENCH", "FRANCAIS", "FRANÇAIS", "VOSTFR"]) or re.search(r'\bVF\b', desc_upper) or re.search(r'\bFR\b', desc_upper)
                            
                            if not has_fr_in_title and not has_fr_in_desc:
                                continue # Skip this result as it has no French/VOSTFR
                                
                            torznab_ns = {'torznab': 'http://torznab.com/schemas/2015/feed'}
                            
                            info_hash = None
                            seeders = 0
                            leechers = 0
                            size = int(res.findtext('size', default='0'))
                            
                            for attr in res.findall('torznab:attr', namespaces=torznab_ns):
                                name = attr.get('name')
                                value = attr.get('value')
                                
                                if name == 'infohash':
                                    info_hash = value
                                elif name == 'seeders':
                                    seeders = int(value) if value else 0
                                elif name == 'peers':
                                    leechers = int(value) if value else 0
                                elif name == 'size' and size == 0:
                                    size = int(value) if value else 0
                            
                            # Fallback si infohash introuvable
                            if not info_hash:
                                guid = res.findtext('guid')
                                if guid and len(guid) >= 40: # Extrait l'infohash d'une string si c'est un magnet ou un hash brut
                                    match = re.search(r'([a-fA-F0-9]{40})', guid)
                                    if match:
                                        info_hash = match.group(1)

                            if not info_hash:
                                continue

                            enclosure = res.find('enclosure')
                            download_link = enclosure.get('url') if enclosure is not None else None
                            if not download_link:
                                download_link = res.findtext('link')

                            item = {
                                "name": title,
                                "size": size,
                                "tracker_name": "NekoBT",
                                "info_hash": info_hash,
                                "magnet": None,
                                "link": download_link,
                                "source": "nekobt",
                                "seeders": seeders,
                                "leechers": leechers
                            }
                            normalized.append(item)
                        return normalized
                    else:
                        logging.warning(f"NekoBT Error {response.status}")
            except Exception as e:
                logging.error(f"NekoBT Exception: {e}")
        return []

    async def search_movie(self, title, year, imdb_id=None, tmdb_id=None):
        params = {"q": f"{title} {year}"}
        return await self.search(params)

    async def search_series(self, title, season, episode, imdb_id=None, tmdb_id=None):
        # Méthode inspirée de UwU-FR : Lancer plusieurs requêtes en parallèle pour contourner 
        # la limite de 50/100 résultats de l'API NekoBT et trouver les vieux épisodes/packs.
        queries = [title]
        if season is not None and episode is not None:
            queries.append(f"{title} S{season:02d}E{episode:02d}")
            queries.append(f"{title} {episode:02d}")
            queries.append(f"{title} S{season:02d}")
            queries.append(f"{title} Saison {season}")
            queries.append(f"{title} Integrale")
            
        all_results = []
        seen_hashes = set()
        
        # Exécution parallèle via asyncio.gather
        import asyncio
        tasks = [self.search({"q": q, "limit": "100"}) for q in set(queries)]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        for res in results_list:
            if isinstance(res, list):
                for item in res:
                    info_hash = item.get('info_hash')
                    if info_hash and info_hash not in seen_hashes:
                        seen_hashes.add(info_hash)
                        all_results.append(item)
                        
        return all_results
