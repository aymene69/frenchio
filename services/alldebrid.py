import aiohttp
import logging
import math
import json
import binascii
import asyncio

class AllDebridService:
    def __init__(self, api_key):
        self.api_key = api_key
        # On s'assure qu'il n'y a pas de slash final pour éviter les doubles //
        self.base_url = "https://api.alldebrid.com/v4"
        self.agent = "jackett"

    def _clean_hash(self, hash_str):
        """
        Nettoie le hash si nécessaire.
        """
        if not hash_str:
            return None
            
        clean = hash_str.strip().lower()
        
        if len(clean) == 80:
            try:
                decoded = binascii.unhexlify(clean).decode('utf-8')
                if len(decoded) == 40 and all(c in '0123456789abcdef' for c in decoded):
                    return decoded
            except Exception:
                pass
                
        return clean

    async def cleanup(self):
        """
        Nettoie les magnets finis ou en erreur pour ne pas polluer le compte.
        On évite de supprimer ce qui est en cours de téléchargement (Downloading).
        """
        url_list = f"{self.base_url}/magnet/status"
        params = {
            "agent": self.agent,
            "apikey": self.api_key
        }
        
        async with aiohttp.ClientSession(trust_env=True) as session:
            try:
                # 1. Récupérer la liste
                async with session.get(url_list, params=params) as resp:
                    if resp.status != 200:
                        return
                    data = await resp.json()
                    if data.get('status') != 'success':
                        return
                    
                    magnets = data.get('data', {}).get('magnets', [])
                    if not magnets:
                        return

                # 2. Identifier ceux à supprimer
                ids_to_delete = []
                logging.info(f"Cleanup: Checking {len(magnets)} magnets")
                
                for m in magnets:
                    status_code = m.get('statusCode')
                    
                    # 4: Ready
                    if status_code != 4: 
                        ids_to_delete.append(m['id'])
                
                if not ids_to_delete:
                    logging.info("Cleanup: Nothing to delete")
                    return

                logging.info(f"Cleaning up {len(ids_to_delete)} magnets from AllDebrid")

                # 3. Supprimer (POST obligatoire)
                delete_url = f"{self.base_url}/magnet/delete"
                
                tasks = []
                for mid in ids_to_delete:
                    data = {
                        "agent": self.agent,
                        "apikey": self.api_key,
                        "id": mid
                    }
                    tasks.append(session.post(delete_url, data=data))
                
                # Exécution parallèle
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                success_count = 0
                for res in results:
                    if isinstance(res, aiohttp.ClientResponse) and res.status == 200:
                        try:
                            js = await res.json()
                            if js.get('status') == 'success':
                                success_count += 1
                        except:
                            pass
                
                if success_count > 0:
                    logging.info(f"Cleanup: Successfully deleted {success_count}/{len(ids_to_delete)} magnets")
                else:
                    logging.info("Cleanup: No magnets deleted")

            except Exception as e:
                logging.error(f"Cleanup Error: {e}")

    async def check_availability(self, hashes):
        """
        Vérifie la disponibilité en UPLOADANT les magnets.
        """
        if not hashes:
            return {}
            
        # Nettoyage préalable (AVANT)
        try:
            await self.cleanup()
        except Exception as e:
            logging.error(f"Pre-check cleanup failed: {e}")
            
        # Nettoyage des hashs avant envoi
        cleaned_hashes = []
        for h in hashes:
            cleaned = self._clean_hash(h)
            if cleaned:
                cleaned_hashes.append(cleaned)
        
        if not cleaned_hashes:
            return {}

        # Découpage en lots
        batch_size = 20
        all_availability = {}
        
        logging.info(f"Checking availability via UPLOAD for {len(cleaned_hashes)} hashes")

        for i in range(0, len(cleaned_hashes), batch_size):
            batch = cleaned_hashes[i:i + batch_size]
            url = f"{self.base_url}/magnet/upload"
            
            data = {
                "agent": self.agent,
                "apikey": self.api_key,
                "magnets[]": batch
            }
            
            async with aiohttp.ClientSession(trust_env=True) as session:
                try:
                    async with session.post(url, data=data) as response:
                        if response.status == 200:
                            resp_json = await response.json()
                            
                            if i == 0:
                                logging.info(f"DEBUG AD Response (First Batch Sample): {json.dumps(resp_json)[:1000]}")
                            
                            if resp_json.get('status') == 'success':
                                magnets_data = resp_json.get('data', {}).get('magnets', [])
                                
                                instant_count = 0
                                for m in magnets_data:
                                    h = m.get('hash') or m.get('magnet')
                                    
                                    is_ready = m.get('ready', False)
                                    status_code = m.get('statusCode')
                                    
                                    if not is_ready and status_code == 4:
                                        is_ready = True
                                    
                                    if h:
                                        h_clean = self._clean_hash(h)
                                        all_availability[h_clean] = is_ready
                                        if h != h_clean:
                                             all_availability[h] = is_ready

                                        if is_ready:
                                            instant_count += 1
                                            
                                logging.info(f"Batch {i//batch_size + 1}: {instant_count} ready / {len(batch)} uploaded")
                            else:
                                logging.warning(f"AllDebrid Upload Error: {resp_json.get('error')}")
                        else:
                            logging.warning(f"AllDebrid Upload HTTP Error: {response.status}")
                            
                except Exception as e:
                    logging.error(f"Erreur AllDebrid Upload Batch {i}: {e}")
        
        # Nettoyage final (APRES)
        try:
            # Petite pause pour laisser l'API respirer et indexer les nouveaux ajouts
            await asyncio.sleep(1)
            await self.cleanup()
        except Exception as e:
            logging.error(f"Post-check cleanup failed: {e}")

        return all_availability

    async def unlock_magnet(self, magnet_hash, season=None, episode=None, media_type=None):
        """
        Upload magnet -> Get link -> Unlock
        """
        # Nettoyage hash
        magnet_hash = self._clean_hash(magnet_hash)
        
        async with aiohttp.ClientSession(trust_env=True) as session:
            # 1. Upload Magnet
            upload_url = f"{self.base_url}/magnet/upload"
            params = {
                "agent": self.agent,
                "apikey": self.api_key,
                "magnets[]": magnet_hash
            }
            
            try:
                async with session.post(upload_url, data=params) as resp:
                    data = await resp.json()
                    
                    if data.get('status') != 'success':
                        logging.error(f"AD Upload Failed: {data}")
                        return None
                    
                    magnets = data.get('data', {}).get('magnets', [])
                    if not magnets:
                        return None
                    
                    magnet_info = magnets[0]
                    magnet_id = magnet_info['id']
                    
                    # Si ready, on a les liens
                    if magnet_info.get('ready') and magnet_info.get('links'):
                        target_link = self._select_link(magnet_info['links'], season, episode, media_type)
                        if target_link:
                            return await self._unlock_link(session, target_link)

            except Exception as e:
                logging.error(f"Exception AD Upload: {e}")
                return None

            # 2. Get Status
            status_url = f"{self.base_url}/magnet/status"
            params = {
                "agent": self.agent,
                "apikey": self.api_key,
                "id": magnet_id
            }
            
            try:
                async with session.get(status_url, params=params) as resp:
                    data = await resp.json()
                    if data.get('status') != 'success':
                        return None
                    
                    magnet_data = data.get('data', {}).get('magnets', {})
                    if isinstance(magnet_data, list):
                         magnet_data = magnet_data[0]
                    
                    links = magnet_data.get('links', [])
                    if not links:
                        return None
                    
                    target_link = self._select_link(links, season, episode, media_type)
                    if not target_link:
                        return None
                        
                    return await self._unlock_link(session, target_link)
                    
            except Exception as e:
                logging.error(f"Exception AD Status: {e}")
                return None
                
        return None

    def _select_link(self, links, season, episode, media_type):
        """Sélectionne le bon fichier dans le torrent"""
        if not links:
            return None
            
        logging.info(f"Selecting file for S{season}E{episode} among {len(links)} files")
        
        # Si épisode spécifique
        if season is not None and episode is not None:
            import re
            # Patterns pour S01E01, 1x01, etc.
            s_str = f"{int(season):02d}"
            e_str = f"{int(episode):02d}"
            
            patterns = [
                f"S{s_str}E{e_str}", # S01E01
                f"{int(season)}x{e_str}", # 1x01
                f"S{int(season)}E{e_str}", # S1E01
                f"S{s_str}.E{e_str}" # S01.E01
            ]
            
            for link in links:
                filename = link.get('filename', '').upper()
                for pat in patterns:
                    if pat.upper() in filename:
                        logging.info(f"Match found: {filename} (Pattern: {pat})")
                        return link['link']
            
            logging.warning(f"No strict match found for S{season}E{episode}. Files available: {[l.get('filename') for l in links[:5]]}...")

        # Si Film ou pas trouvé, on prend le plus gros fichier
        # Tri par taille décroissante
        sorted_links = sorted(links, key=lambda x: x.get('size', 0), reverse=True)
        best_link = sorted_links[0]
        
        logging.info(f"Fallback: Selected largest file: {best_link.get('filename')} ({best_link.get('size')} bytes)")
        return best_link['link']

    async def _unlock_link(self, session, link):
        unlock_url = f"{self.base_url}/link/unlock"
        params = {
            "agent": self.agent,
            "apikey": self.api_key,
            "link": link
        }
        try:
            async with session.get(unlock_url, params=params) as resp:
                data = await resp.json()
                if data.get('status') == 'success':
                    return data['data']['link']
        except Exception as e:
            logging.error(f"Exception AD Unlock: {e}")
        return None
