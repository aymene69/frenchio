import aiohttp
import logging
import asyncio

class DebridLinkService:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://debrid-link.com/api/v2"
        
    async def check_availability(self, hashes):
        """
        Vérifie la disponibilité de plusieurs hash en parallèle
        Retourne un dict {hash: bool} indiquant si chaque hash est caché
        """
        if not hashes:
            return {}
        
        logging.info(f"DebridLink: Checking {len(hashes)} hashes in parallel")
        
        # Créer une tâche pour chaque hash
        tasks = [self._check_single_hash(h) for h in hashes]
        
        # Exécuter toutes les vérifications en parallèle
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Construire le dictionnaire de résultats
        availability = {}
        for hash_value, result in zip(hashes, results):
            if isinstance(result, Exception):
                logging.error(f"DebridLink: Error checking {hash_value}: {result}")
                availability[hash_value.lower()] = False
            else:
                availability[hash_value.lower()] = result
        
        cached_count = sum(1 for v in availability.values() if v)
        logging.info(f"DebridLink: {cached_count}/{len(hashes)} hashes are cached")
        
        return availability
    
    async def _check_single_hash(self, hash_value):
        """
        Vérifie un seul hash en l'ajoutant au seedbox
        Retourne True si caché (downloadPercent == 100), False sinon
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        add_url = f"{self.base_url}/seedbox/add"
        
        async with aiohttp.ClientSession(trust_env=True) as session:
            try:
                # Ajouter le torrent par hash
                payload = {
                    "url": hash_value,
                    "wait": False
                }
                
                async with session.post(add_url, json=payload, headers=headers, timeout=10) as resp:
                    if resp.status != 200:
                        logging.warning(f"DebridLink: Failed to add {hash_value[:8]}... status {resp.status}")
                        return False
                    
                    data = await resp.json()
                    
                    if not data.get('success'):
                        logging.debug(f"DebridLink: {hash_value[:8]}... not successful")
                        return False
                    
                    torrent = data.get('value', {})
                    torrent_id = torrent.get('id')
                    download_percent = torrent.get('downloadPercent', 0)
                    error = torrent.get('error', 0)
                    
                    # Si erreur ou pas complètement téléchargé, supprimer et retourner False
                    is_cached = error == 0 and download_percent == 100
                    
                    if not is_cached and torrent_id:
                        # Supprimer le torrent car il n'est pas caché
                        await self._remove_torrent(session, headers, torrent_id)
                        logging.debug(f"DebridLink: {hash_value[:8]}... not cached (removed)")
                    else:
                        logging.debug(f"DebridLink: {hash_value[:8]}... cached!")
                    
                    return is_cached
                    
            except asyncio.TimeoutError:
                logging.warning(f"DebridLink: Timeout checking {hash_value[:8]}...")
                return False
            except Exception as e:
                logging.error(f"DebridLink: Exception checking {hash_value[:8]}...: {e}")
                return False
    
    async def _remove_torrent(self, session, headers, torrent_id):
        """Supprime un torrent du seedbox"""
        try:
            remove_url = f"{self.base_url}/seedbox/{torrent_id}/remove"
            async with session.delete(remove_url, headers=headers, timeout=5) as resp:
                if resp.status == 200:
                    logging.debug(f"DebridLink: Removed torrent {torrent_id}")
                else:
                    logging.warning(f"DebridLink: Failed to remove {torrent_id}: {resp.status}")
        except Exception as e:
            logging.error(f"DebridLink: Error removing {torrent_id}: {e}")
    
    async def unlock_magnet(self, info_hash, season=None, episode=None, media_type=None):
        """
        Déverrouille un magnet et retourne l'URL de streaming
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        add_url = f"{self.base_url}/seedbox/add"
        
        async with aiohttp.ClientSession(trust_env=True) as session:
            try:
                # Ajouter le torrent
                payload = {
                    "url": info_hash,
                    "wait": False
                }
                
                async with session.post(add_url, json=payload, headers=headers, timeout=15) as resp:
                    if resp.status != 200:
                        logging.error(f"DebridLink: Failed to add torrent: {resp.status}")
                        return None
                    
                    data = await resp.json()
                    
                    if not data.get('success'):
                        logging.error("DebridLink: Add torrent failed")
                        return None
                    
                    torrent = data.get('value', {})
                    torrent_id = torrent.get('id')
                    files = torrent.get('files', [])
                    
                    if not files:
                        logging.error("DebridLink: No files in torrent")
                        return None
                    
                    # Sélectionner le bon fichier
                    selected_file = None
                    
                    if season is not None and episode is not None:
                        # Série : trouver le fichier correspondant à l'épisode
                        import re
                        s_pattern = f"S{season:02d}E{episode:02d}"
                        
                        for f in files:
                            filename = f.get('name', '')
                            if re.search(s_pattern, filename, re.IGNORECASE):
                                selected_file = f
                                break
                        
                        # Fallback : prendre le plus gros fichier vidéo
                        if not selected_file:
                            video_files = [f for f in files if f.get('name', '').lower().endswith(('.mkv', '.mp4', '.avi'))]
                            if video_files:
                                selected_file = max(video_files, key=lambda x: x.get('size', 0))
                    else:
                        # Film : prendre le plus gros fichier
                        selected_file = max(files, key=lambda x: x.get('size', 0))
                    
                    if selected_file:
                        download_url = selected_file.get('downloadUrl')
                        if download_url:
                            logging.info(f"DebridLink: Stream URL found for torrent {torrent_id}")
                            return download_url
                    
                    logging.error("DebridLink: Could not find suitable file")
                    return None
                    
            except Exception as e:
                logging.error(f"DebridLink: Exception in unlock_magnet: {e}")
                return None

