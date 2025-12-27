import aiohttp
import logging
import urllib.parse

class SharewoodService:
    def __init__(self, passkey):
        self.passkey = passkey
        self.base_url = "https://www.sharewood.tv/api"

    async def download_torrent(self, session, download_url):
        # L'URL Sharewood nécessite le passkey, souvent inclus ou à ajouter
        # Format: https://www.sharewood.tv/api/{passkey}/download/{id}
        # Si download_url est complet, c'est bon.
        try:
            async with session.get(download_url) as resp:
                if resp.status == 200:
                    return await resp.read()
        except Exception:
            pass
        return None

    async def search(self, query):
        if not self.passkey:
            return []

        # URL encodée correctement
        encoded_query = urllib.parse.quote(query)
        url = f"{self.base_url}/{self.passkey}/search?name={encoded_query}"
        
        # Log avec passkey masquée
        log_url = url.replace(self.passkey, '***PASSKEY***')
        logging.info(f"Sharewood Request: {log_url}")

        async with aiohttp.ClientSession(trust_env=True) as session:
            try:
                async with session.get(url, timeout=20) as response:
                    if response.status == 200:
                        data = await response.json()
                        # L'API retourne une liste d'objets directement
                        results = data if isinstance(data, list) else []
                        
                        logging.info(f"Sharewood found {len(results)} results for '{query}'")
                        if not results and isinstance(data, dict):
                             logging.warning(f"Sharewood returned dict instead of list? {str(data)[:200]}")
                        
                        normalized = []
                        for res in results:
                            # Mapping des champs Sharewood vers notre format interne
                            item = {
                                "name": res.get("name"),
                                "size": res.get("size", 0), # Taille brute en octets
                                "tracker_name": "Sharewood",
                                "info_hash": res.get("info_hash"),
                                "magnet": None, # Sharewood donne info_hash et download_url, magnet à construire si besoin
                                "link": res.get("download_url"),
                                "source": "sharewood"
                            }
                            normalized.append(item)
                        return normalized
                    else:
                        logging.warning(f"Sharewood Error {response.status}")
                        text = await response.text()
                        logging.warning(f"Sharewood Body: {text[:200]}")
            except Exception as e:
                logging.error(f"Sharewood Exception: {e}")
        return []

    async def search_movie(self, title, year):
        # Recherche combinée pour maximiser les chances
        # Sharewood est assez flexible mais "Titre Année" est souvent le standard release
        queries = [f"{title} {year}", title]
        results = []
        
        # On utilise un set pour éviter les doublons si les deux recherches donnent les mêmes résultats
        seen_hashes = set()
        
        for q in queries:
            res_list = await self.search(q)
            for res in res_list:
                if res['info_hash'] not in seen_hashes:
                    results.append(res)
                    seen_hashes.add(res['info_hash'])
            
        return results

    async def search_series(self, title, season, episode):
        results = []
        seen_hashes = set()
        
        # SxxExx
        if season is not None and episode is not None:
            s_str = f"S{int(season):02d}"
            e_str = f"E{int(episode):02d}"
            q = f"{title} {s_str}{e_str}"
            
            res_list = await self.search(q)
            for res in res_list:
                if res['info_hash'] not in seen_hashes:
                    results.append(res)
                    seen_hashes.add(res['info_hash'])
        
        # Saison Pack (Sxx)
        if season is not None:
             s_str = f"S{int(season):02d}"
             q = f"{title} {s_str}"
             
             res_list = await self.search(q)
             for res in res_list:
                if res['info_hash'] not in seen_hashes:
                    results.append(res)
                    seen_hashes.add(res['info_hash'])

        return results

