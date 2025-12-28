"""
TorBox Debrid Service
Converti en async avec aiohttp et compatible avec l'architecture Frenchio
"""
import aiohttp
import asyncio
import logging
import re

class TorBoxService:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.torbox.app/v1/api"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
        }
    
    async def check_availability(self, magnet_hash):
        """
        Vérifie si un hash est en cache sur TorBox.
        
        Args:
            magnet_hash: Hash du torrent
            
        Returns:
            dict ou None: Informations si disponible
        """
        url = f"{self.base_url}/torrents/checkcached"
        params = {
            "hash": magnet_hash,
            "format": "object",
            "list_files": "true"
        }
        
        async with aiohttp.ClientSession(trust_env=True) as session:
            try:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        logging.warning(f"TorBox check availability returned {response.status}")
                        return None
                    
                    data = await response.json()
                    
                    if data.get("success") and data.get("data"):
                        # data est un dict avec le hash comme clé
                        torrent_info = data["data"].get(magnet_hash)
                        if torrent_info:
                            return {
                                "name": torrent_info.get("name", ""),
                                "size": torrent_info.get("size", 0),
                                "files": torrent_info.get("files", []),
                                "cached": True
                            }
                    
                    return None
                    
            except Exception as e:
                logging.error(f"TorBox check availability error: {e}")
                return None
    
    async def add_magnet(self, magnet_link):
        """
        Ajoute un magnet à TorBox.
        
        Args:
            magnet_link: Lien magnet
            
        Returns:
            dict ou None: {"torrent_id": id, "hash": hash, "is_cached": bool}
        """
        url = f"{self.base_url}/torrents/createtorrent"
        data = {
            "magnet": magnet_link,
            "seed": 2  # Mode de seed
        }
        
        async with aiohttp.ClientSession(trust_env=True) as session:
            try:
                async with session.post(url, headers=self.headers, data=data) as response:
                    if response.status != 200:
                        text = await response.text()
                        logging.error(f"TorBox add magnet failed: {response.status} - {text}")
                        return None
                    
                    result = await response.json()
                    
                    if result.get("success"):
                        data = result.get("data", {})
                        cached = "Found Cached Torrent" in result.get("detail", "")
                        
                        return {
                            "torrent_id": data.get("torrent_id"),
                            "hash": data.get("hash"),
                            "is_cached": cached
                        }
                    else:
                        logging.error(f"TorBox add magnet failed: {result}")
                        return None
                        
            except Exception as e:
                logging.error(f"TorBox add magnet error: {e}")
                return None
    
    async def get_torrent_info(self, torrent_hash):
        """
        Récupère les informations d'un torrent via checkcached (pour vérification cache).
        
        Args:
            torrent_hash: Hash du torrent
            
        Returns:
            dict ou None
        """
        url = f"{self.base_url}/torrents/checkcached"
        params = {
            "hash": torrent_hash,
            "format": "object",
            "list_files": "true"
        }
        
        async with aiohttp.ClientSession(trust_env=True) as session:
            try:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        return None
                    
                    data = await response.json()
                    
                    if data.get("success") and data.get("data"):
                        return data["data"].get(torrent_hash)
                    
                    return None
                    
            except Exception as e:
                logging.error(f"TorBox get torrent info error: {e}")
                return None
    
    async def get_torrent_details(self, torrent_id):
        """
        Récupère les détails complets d'un torrent ajouté via mylist.
        Retourne les fichiers avec leurs vrais IDs assignés par TorBox.
        
        Args:
            torrent_id: ID du torrent sur TorBox
            
        Returns:
            dict ou None: Contient les fichiers avec leur champ "id"
        """
        url = f"{self.base_url}/torrents/mylist"
        params = {"id": torrent_id}
        
        async with aiohttp.ClientSession(trust_env=True) as session:
            try:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status != 200:
                        text = await response.text()
                        logging.error(f"TorBox get torrent details failed: {response.status} - {text}")
                        return None
                    
                    data = await response.json()
                    
                    if data.get("success"):
                        return data.get("data")
                    else:
                        logging.error(f"TorBox get torrent details failed: {data}")
                        return None
                        
            except Exception as e:
                logging.error(f"TorBox get torrent details error: {e}")
                return None
    
    async def wait_for_files(self, torrent_hash, timeout=30, interval=5):
        """
        Attend que les fichiers soient disponibles (pour torrents non-cachés).
        
        Args:
            torrent_hash: Hash du torrent
            timeout: Timeout en secondes
            interval: Intervalle entre les vérifications
            
        Returns:
            list ou None: Liste des fichiers
        """
        start_time = asyncio.get_event_loop().time()
        
        while (asyncio.get_event_loop().time() - start_time) < timeout:
            info = await self.get_torrent_info(torrent_hash)
            
            if info and "files" in info:
                files = info["files"]
                if files:
                    logging.info(f"TorBox: Files ready ({len(files)} files)")
                    return files
            
            logging.info("TorBox: Files not ready yet, waiting...")
            await asyncio.sleep(interval)
        
        logging.error("TorBox: Timeout waiting for files")
        return None
    
    async def get_download_link(self, torrent_id, file_id, max_retries=3):
        """
        Récupère le lien de téléchargement direct d'un fichier.
        Avec retry automatique en cas d'erreur 500 (DATABASE_ERROR).
        
        Args:
            torrent_id: ID du torrent sur TorBox
            file_id: ID/index du fichier
            max_retries: Nombre maximum de tentatives (défaut: 3)
            
        Returns:
            str ou None: Lien de téléchargement
        """
        url = f"{self.base_url}/torrents/requestdl"
        params = {
            "token": self.api_key,
            "torrent_id": torrent_id,
            "file_id": file_id,
            "zip_link": "false",
            "torrent_file": "false"
        }
        
        for attempt in range(max_retries):
            async with aiohttp.ClientSession(trust_env=True) as session:
                try:
                    if attempt > 0:
                        logging.info(f"TorBox: Retry attempt {attempt + 1}/{max_retries}")
                        await asyncio.sleep(1 + attempt)  # Délai croissant: 1s, 2s, 3s
                    
                    logging.debug(f"TorBox: Requesting download with params: {params}")
                    async with session.get(url, headers=self.headers, params=params) as response:
                        text = await response.text()
                        
                        if response.status == 500:
                            # Erreur serveur temporaire, on va retry
                            logging.warning(f"TorBox: Server error 500, attempt {attempt + 1}/{max_retries}")
                            if attempt < max_retries - 1:
                                continue  # Retry
                            else:
                                logging.error(f"TorBox: Max retries reached - {text}")
                                return None
                        
                        if response.status != 200:
                            logging.error(f"TorBox get download link failed: {response.status} - {text}")
                            logging.error(f"TorBox: URL was: {url} with params: {params}")
                            return None
                        
                        data = await response.json()
                        
                        if data.get("success"):
                            download_url = data.get("data")
                            logging.info(f"TorBox: Download link obtained: {download_url}")
                            return download_url
                        else:
                            logging.error(f"TorBox download link failed: {data}")
                            return None
                            
                except Exception as e:
                    logging.error(f"TorBox get download link error (attempt {attempt + 1}): {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1 + attempt)
                        continue
                    return None
    
    async def get_stream_link(self, magnet_link, stream_type, season=None, episode=None):
        """
        Obtient un lien de streaming depuis un magnet.
        
        Args:
            magnet_link: Lien magnet
            stream_type: "movie" ou "series"
            season: Numéro de saison (pour séries)
            episode: Numéro d'épisode (pour séries)
            
        Returns:
            str ou None: Lien de streaming
        """
        # 1. Ajouter le magnet
        magnet_data = await self.add_magnet(magnet_link)
        if not magnet_data:
            logging.error("TorBox: Failed to add magnet")
            return None
        
        torrent_id = magnet_data.get("torrent_id")
        torrent_hash = magnet_data.get("hash")
        is_cached = magnet_data.get("is_cached", False)
        
        if not torrent_id or not torrent_hash:
            logging.error("TorBox: Missing torrent_id or hash")
            return None
        
        # 2. Récupérer les fichiers avec leurs IDs réels via mylist
        logging.info(f"TorBox: Fetching torrent details for ID {torrent_id}")
        torrent_details = await self.get_torrent_details(torrent_id)
        
        if not torrent_details or "files" not in torrent_details:
            logging.error("TorBox: Failed to get torrent details or no files")
            return None
        
        files = torrent_details["files"]
        logging.info(f"TorBox: Found {len(files)} files in torrent")
        
        # 3. Sélectionner le fichier approprié
        # IMPORTANT : Utiliser le champ "id" du fichier, pas l'index dans le tableau
        
        # Log tous les fichiers pour debug
        logging.info(f"TorBox: All files in torrent:")
        for f in files:
            file_id_debug = f.get('id', 'N/A')
            logging.info(f"  [id={file_id_debug}] {f.get('name')} - {f.get('size', 0)} bytes - video: {self._is_video_file(f.get('name', ''))}")
        
        if stream_type == "movie":
            # Plus gros fichier vidéo
            video_files = [
                f for f in files
                if self._is_video_file(f.get("name", ""))
            ]
            
            if not video_files:
                logging.error("TorBox: No video files found")
                return None
            
            selected_file = max(video_files, key=lambda x: x.get("size", 0))
            # Utiliser le champ "id" du fichier
            file_id = selected_file.get("id")
            if file_id is None:
                logging.error("TorBox: Selected file has no 'id' field")
                return None
            logging.info(f"TorBox: Selected file (id={file_id}): {selected_file.get('name')}")
            
        elif stream_type == "series":
            # Fichier correspondant à S{season}E{episode}
            matching_files = []
            
            for f in files:
                filename = f.get("name", "")
                is_video = self._is_video_file(filename)
                matches_ep = self._matches_episode(filename, season, episode)
                
                logging.debug(f"  File {filename}: is_video={is_video}, matches_S{season:02d}E{episode:02d}={matches_ep}")
                
                if is_video and matches_ep:
                    matching_files.append(f)
            
            if not matching_files:
                logging.error(f"TorBox: No video file matching S{season:02d}E{episode:02d}")
                return None
            
            logging.info(f"TorBox: Found {len(matching_files)} matching video file(s)")
            
            # Prendre le plus gros si plusieurs matchent
            selected_file = max(matching_files, key=lambda x: x.get("size", 0))
            # Utiliser le champ "id" du fichier
            file_id = selected_file.get("id")
            if file_id is None:
                logging.error("TorBox: Selected file has no 'id' field")
                return None
            logging.info(f"TorBox: Selected episode file (id={file_id}): {selected_file.get('name')}")
        
        else:
            logging.error(f"TorBox: Unsupported stream type: {stream_type}")
            return None
        
        # 4. Obtenir le lien de téléchargement
        # Utiliser le champ "id" du fichier comme file_id
        logging.info(f"TorBox: Requesting download link with file_id={file_id} (torrent_id={torrent_id})")
        download_link = await self.get_download_link(torrent_id, file_id)
        
        if download_link:
            logging.info(f"TorBox: Stream link obtained successfully: {download_link}")
            return download_link
        else:
            logging.error(f"TorBox: Failed to get download link")
        
        return None
    
    def _is_video_file(self, filename):
        """Vérifie si un fichier est une vidéo."""
        video_extensions = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.ts', '.m2ts'}
        excluded_extensions = {'.nfo', '.txt', '.srt', '.sub', '.idx', '.jpg', '.png', '.gif'}
        
        filename_lower = filename.lower()
        
        # Exclure explicitement les fichiers non-vidéo
        if any(filename_lower.endswith(ext) for ext in excluded_extensions):
            return False
        
        # Vérifier que c'est une vidéo
        return any(filename_lower.endswith(ext) for ext in video_extensions)
    
    def _matches_episode(self, filename, season, episode):
        """
        Vérifie si un nom de fichier correspond à un épisode.
        
        Patterns supportés:
        - S01E01
        - 1x01
        - s01e01
        - etc.
        """
        if not season or not episode:
            return False
        
        patterns = [
            rf"[Ss]{season:02d}[Ee]{episode:02d}",  # S01E01
            rf"[Ss]{season}[Ee]{episode}",          # S1E1
            rf"{season}x{episode:02d}",             # 1x01
            rf"{season}x{episode}",                 # 1x1
        ]
        
        for pattern in patterns:
            if re.search(pattern, filename):
                return True
        
        return False

