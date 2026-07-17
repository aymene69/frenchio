import aiohttp
import logging
import urllib.parse
import xml.etree.ElementTree as ET
import re

class NyaaService:
    def __init__(self):
        self.base_url = "https://nyaa.si/"

    async def search(self, params):
        params['page'] = 'rss'
        params['c'] = '0_0' # All categories
        params['f'] = '0'   # No filter
        
        logging.info(f"Nyaa Search: {self.base_url}?{urllib.parse.urlencode(params)}")

        async with aiohttp.ClientSession(trust_env=True) as session:
            try:
                async with session.get(self.base_url, params=params, timeout=20) as response:
                    if response.status == 200:
                        text = await response.text()
                        
                        try:
                            root = ET.fromstring(text)
                        except ET.ParseError as e:
                            logging.error(f"Nyaa XML Parse Error: {e}")
                            return []

                        items = root.findall('.//item')
                        logging.info(f"Nyaa found {len(items)} results")
                        
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
                                
                            # Nyaa custom namespace for properties
                            nyaa_ns = {'nyaa': 'https://nyaa.si/xmlns/nyaa'}
                            
                            seeders = res.findtext('nyaa:seeders', namespaces=nyaa_ns)
                            leechers = res.findtext('nyaa:leechers', namespaces=nyaa_ns)
                            size_str = res.findtext('nyaa:size', namespaces=nyaa_ns) # usually like "1.4 GiB"
                            info_hash = res.findtext('nyaa:infoHash', namespaces=nyaa_ns)
                            download_link = res.findtext('link')
                            
                            # Convert size string to bytes roughly (Frenchio uses size in bytes)
                            size_bytes = 0
                            if size_str:
                                try:
                                    parts = size_str.strip().split()
                                    if len(parts) == 2:
                                        val = float(parts[0])
                                        unit = parts[1].lower()
                                        if 'gib' in unit or 'gb' in unit:
                                            size_bytes = int(val * 1024 * 1024 * 1024)
                                        elif 'mib' in unit or 'mb' in unit:
                                            size_bytes = int(val * 1024 * 1024)
                                        elif 'kib' in unit or 'kb' in unit:
                                            size_bytes = int(val * 1024)
                                        else:
                                            size_bytes = int(val)
                                except Exception:
                                    size_bytes = 0

                            if not info_hash:
                                continue

                            item = {
                                "name": title,
                                "size": size_bytes,
                                "tracker_name": "Nyaa",
                                "info_hash": info_hash,
                                "magnet": None,
                                "link": download_link,
                                "source": "nyaa",
                                "seeders": int(seeders) if seeders else 0,
                                "leechers": int(leechers) if leechers else 0
                            }
                            normalized.append(item)
                        return normalized
                    else:
                        logging.warning(f"Nyaa Error {response.status}")
            except Exception as e:
                logging.error(f"Nyaa Exception: {e}")
        return []

    async def search_movie(self, title, year, imdb_id=None, tmdb_id=None):
        params = {"q": f"{title} {year}"}
        return await self.search(params)

    async def search_series(self, title, season, episode, imdb_id=None, tmdb_id=None):
        queries = [title]
        if season is not None and episode is not None:
            queries.append(f"{title} S{season:02d}E{episode:02d}")
            queries.append(f"{title} {episode:02d}")
            queries.append(f"{title} S{season:02d}")
            queries.append(f"{title} Saison {season}")
            queries.append(f"{title} Integrale")
            
        all_results = []
        seen_hashes = set()
        
        import asyncio
        tasks = [self.search({"q": q}) for q in set(queries)]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        for res in results_list:
            if isinstance(res, list):
                for item in res:
                    info_hash = item.get('info_hash')
                    if info_hash and info_hash not in seen_hashes:
                        seen_hashes.add(info_hash)
                        all_results.append(item)
                        
        return all_results
