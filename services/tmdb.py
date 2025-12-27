import aiohttp
import logging

class TMDBService:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.themoviedb.org/3"

    async def get_tmdb_id(self, imdb_id, media_type):
        """
        Convertit un IMDB ID en TMDB ID via l'endpoint find
        """
        url = f"{self.base_url}/find/{imdb_id}"
        params = {
            "api_key": self.api_key,
            "external_source": "imdb_id"
        }
        
        async with aiohttp.ClientSession(trust_env=True) as session:
            try:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        results = []
                        if media_type == "movie":
                            results = data.get("movie_results", [])
                        elif media_type == "series":
                            results = data.get("tv_results", [])
                        
                        if results:
                            return results[0]["id"]
            except Exception as e:
                logging.error(f"Erreur TMDB Find: {e}")
        return None

