import aiohttp
import logging
import asyncio

class YggService:
    def __init__(self, passkey, url="http://89.168.37.159:8888"): 
        # URL par défaut basée sur yggapi.eu (standard pour ces docs), configurable si besoin
        self.passkey = passkey
        self.base_url = url

    async def download_torrent(self, session, download_url):
        # YGG nécessite ?passkey=... pour télécharger
        if not self.passkey:
            logging.warning("YGG: Cannot download torrent without passkey")
            return None
            
        if 'passkey=' not in download_url:
            download_url += f"&passkey={self.passkey}"
            
        try:
            async with session.get(download_url) as resp:
                if resp.status == 200:
                    return await resp.read()
        except Exception:
            pass
        return None

    async def search(self, params):
        """
        Recherche générique sur YGG
        La passkey n'est PAS nécessaire pour la recherche, seulement pour le téléchargement
        """
        search_url = f"{self.base_url}/torrents"
        
        # On log l'appel (sans passkey car elle n'est pas dans l'URL de recherche ici, mais utilisée plus tard)
        logging.info(f"YGG Search Params: {params}")

        async with aiohttp.ClientSession(trust_env=True) as session:
            try:
                async with session.get(search_url, params=params, timeout=20) as response:
                    if response.status == 200:
                        results = await response.json()
                        # results est une liste de TorrentResult
                        if not results:
                            return []
                        
                        logging.info(f"YGG found {len(results)} results")
                        
                        # Problème : on a besoin du hash pour AllDebrid.
                        # TorrentResult n'a PAS de hash selon la doc.
                        # On doit récupérer les détails pour chaque torrent.
                        # On le fait en parallèle.
                        
                        tasks = [self.get_details(session, t['id']) for t in results]
                        details_results = await asyncio.gather(*tasks)
                        
                        normalized = []
                        for res in details_results:
                            if not res: continue
                            
                            # On construit le lien de téléchargement avec la passkey
                            download_url = f"{self.base_url}/torrent/{res['id']}/download?passkey={self.passkey}"
                            
                            item = {
                                "name": res.get("title"),
                                "size": res.get("size", 0),
                                "tracker_name": "YGG",
                                "info_hash": res.get("hash"),
                                "magnet": None, 
                                "link": download_url,
                                "source": "ygg"
                            }
                            normalized.append(item)
                        return normalized
                    else:
                        logging.warning(f"YGG Error {response.status}")
            except Exception as e:
                logging.error(f"YGG Exception: {e}")
        return []

    async def get_details(self, session, torrent_id):
        """Récupère les détails (notamment le hash)"""
        url = f"{self.base_url}/torrent/{torrent_id}"
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
        except Exception:
            pass
        return None

    async def search_movie(self, title, year, tmdb_id=None):
        # Priorité au TMDB ID si dispo
        if tmdb_id:
            return await self.search({"tmdb_id": tmdb_id, "type": "movie"})
        
        # Sinon recherche textuelle
        q = f"{title} {year}"
        return await self.search({"q": q, "category_id": 2145}) # 2145 = Film/Vidéo généralement sur YGG, à vérifier selon l'instance API

    async def search_series(self, title, season, episode, tmdb_id=None):
        # Priorité au TMDB ID
        if tmdb_id:
            # L'API supporte season/episode avec tmdb_id
            params = {"tmdb_id": tmdb_id, "type": "tv"}
            if season: params["season"] = season
            if episode: params["episode"] = episode
            return await self.search(params)
            
        # Fallback textuel
        results = []
        if season is not None and episode is not None:
            s_str = f"S{int(season):02d}"
            e_str = f"E{int(episode):02d}"
            q = f"{title} {s_str}{e_str}"
            results.extend(await self.search({"q": q, "category_id": 2145}))
        
        return results

