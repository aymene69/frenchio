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
        self.base_url = "https://api.alldebrid.com/v4.1"
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

    def _extract_files_recursive(self, entries, path=""):
        """
        Extrait récursivement tous les fichiers d'une structure de dossiers AllDebrid.
        
        Args:
            entries: Liste d'entrées (fichiers ou dossiers)
            path: Chemin du dossier parent (pour logging)
            
        Returns:
            Liste de dicts avec {link, filename, size}
        """
        files = []
        
        for entry in entries:
            name = entry.get('n', '')
            
            # Si l'entrée a un lien 'l', c'est un fichier
            if 'l' in entry:
                files.append({
                    'link': entry['l'],
                    'filename': f"{path}/{name}" if path else name,
                    'size': entry.get('s', 0)
                })
            # Si l'entrée a des sous-entrées 'e', c'est un dossier
            elif 'e' in entry:
                # Récursion dans le sous-dossier
                new_path = f"{path}/{name}" if path else name
                files.extend(self._extract_files_recursive(entry['e'], new_path))
        
        return files

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
        logging.info(f"🔓 AD unlock_magnet: hash={magnet_hash}, S{season}E{episode}, type={media_type}")
        
        async with aiohttp.ClientSession(trust_env=True) as session:
            # 1. Upload Magnet
            upload_url = f"{self.base_url}/magnet/upload"
            params = {
                "agent": self.agent,
                "apikey": self.api_key,
                "magnets[]": magnet_hash
            }
            
            logging.info(f"📤 AD Uploading to {upload_url}")
            
            try:
                async with session.post(upload_url, data=params) as resp:
                    data = await resp.json()
                    logging.info(f"📤 AD Upload response: {json.dumps(data)[:500]}")
                    
                    if data.get('status') != 'success':
                        logging.error(f"❌ AD Upload Failed: {data}")
                        return None
                    
                    magnets = data.get('data', {}).get('magnets', [])
                    if not magnets:
                        logging.error(f"❌ AD No magnets in response")
                        return None
                    
                    magnet_info = magnets[0]
                    magnet_id = magnet_info['id']
                    is_ready = magnet_info.get('ready', False)
                    has_links = 'links' in magnet_info and magnet_info['links']
                    
                    logging.info(f"✅ AD Magnet uploaded: id={magnet_id}, ready={is_ready}, has_links={has_links}")
                    
                    # Si ready, on a les liens
                    if is_ready and has_links:
                        logging.info(f"⚡ AD Instant ready with {len(magnet_info['links'])} links")
                        target_link = self._select_link(magnet_info['links'], season, episode, media_type)
                        if target_link:
                            logging.info(f"🔓 AD Unlocking instant link...")
                            unlocked = await self._unlock_link(session, target_link)
                            if unlocked:
                                logging.info(f"✅ AD Instant unlock successful")
                            return unlocked
                        else:
                            logging.error(f"❌ AD No suitable file selected from instant links")

            except Exception as e:
                logging.error(f"❌ Exception AD Upload: {e}")
                import traceback
                logging.error(traceback.format_exc())
                return None

            # 2. Get Files (l'API v4.1 utilise /magnet/files)
            logging.info(f"📊 AD Fetching files for magnet_id={magnet_id}")
            files_url = f"{self.base_url}/magnet/files"
            
            # L'API /magnet/files attend un POST avec id[] (peut être un array)
            post_data = {
                "agent": self.agent,
                "apikey": self.api_key,
                "id[]": [magnet_id]
            }
            
            try:
                async with session.post(files_url, data=post_data) as resp:
                    data = await resp.json()
                    logging.info(f"📊 AD Files response: {json.dumps(data)[:800]}")
                    
                    if data.get('status') != 'success':
                        logging.error(f"❌ AD Files failed: {data}")
                        return None
                    
                    # L'API retourne data.magnets qui est une liste
                    magnets_list = data.get('data', {}).get('magnets', [])
                    if not magnets_list:
                        logging.error(f"❌ AD No magnets in files response")
                        return None
                    
                    # Trouver notre magnet par ID
                    magnet_data = None
                    for m in magnets_list:
                        if str(m.get('id')) == str(magnet_id):
                            magnet_data = m
                            break
                    
                    if not magnet_data:
                        logging.error(f"❌ AD Magnet {magnet_id} not found in response")
                        return None
                    
                    # Vérifier si une erreur est retournée pour ce magnet
                    if 'error' in magnet_data:
                        logging.error(f"❌ AD Magnet error: {magnet_data['error']}")
                        return None
                    
                    # Extraire récursivement tous les fichiers
                    files_structure = magnet_data.get('files', [])
                    if not files_structure:
                        logging.error(f"❌ AD No files in magnet data")
                        return None
                    
                    links = self._extract_files_recursive(files_structure)
                    
                    if not links:
                        logging.error(f"❌ AD No files extracted from structure")
                        return None
                    
                    logging.info(f"🔗 AD Extracted {len(links)} files from recursive structure")
                    target_link = self._select_link(links, season, episode, media_type)
                    if not target_link:
                        logging.error(f"❌ AD No suitable file selected")
                        return None
                    
                    # Les liens de /magnet/files doivent encore être unlock pour obtenir le lien direct
                    logging.info(f"🔓 AD Unlocking file link...")
                    unlocked = await self._unlock_link(session, target_link)
                    if unlocked:
                        logging.info(f"✅ AD Unlocked successfully")
                    return unlocked
                    
            except Exception as e:
                logging.error(f"❌ Exception AD Files: {e}")
                import traceback
                logging.error(traceback.format_exc())
                return None
                
        return None

    def _select_link(self, links, season, episode, media_type):
        """Sélectionne le bon fichier dans le torrent"""
        if not links:
            logging.error(f"❌ AD _select_link: No links provided")
            return None
            
        logging.info(f"🎯 AD Selecting file for S{season}E{episode} (type={media_type}) among {len(links)} files")
        
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
        logging.info(f"🔐 AD Unlocking link: {link[:80]}...")
        try:
            async with session.get(unlock_url, params=params) as resp:
                data = await resp.json()
                logging.info(f"🔐 AD Unlock response: {json.dumps(data)[:300]}")
                if data.get('status') == 'success':
                    unlocked = data['data']['link']
                    logging.info(f"✅ AD Successfully unlocked: {unlocked[:80]}...")
                    return unlocked
                else:
                    logging.error(f"❌ AD Unlock failed: {data}")
        except Exception as e:
            logging.error(f"❌ Exception AD Unlock: {e}")
            import traceback
            logging.error(traceback.format_exc())
        return None