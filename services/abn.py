import aiohttp
import logging
import asyncio
from html.parser import HTMLParser
import re

class ABNService:
    """
    Service pour le tracker ABNormal (ABN)
    Tracker privé français avec authentification par username/password
    """
    
    def __init__(self, username, password, base_url="https://abn.lol"):
        self.username = username
        self.password = password
        self.base_url = base_url.rstrip('/')
        self.session = None
        self._login_lock = None
    
    async def close(self):
        """Ferme proprement la session"""
        if self.session:
            await self.session.close()
            self.session = None
            logging.debug("ABN: Session closed")
        
    async def _ensure_session(self):
        """Crée et authentifie une session persistante"""
        if self.session is not None:
            return True
        
        # Créer une session avec cookie jar
        self.session = aiohttp.ClientSession(trust_env=True)
        
        login_url = f"{self.base_url}/Home/Login"
        
        # Première requête pour obtenir le token CSRF
        try:
            async with self.session.get(login_url, timeout=10) as resp:
                if resp.status != 200:
                    logging.error(f"ABN: Failed to get login page: {resp.status}")
                    await self.session.close()
                    self.session = None
                    return False
                    
                html = await resp.text()
                # Extraction du token CSRF
                token_match = re.search(r'name="__RequestVerificationToken".*?value="([^"]+)"', html)
                if not token_match:
                    logging.error("ABN: Could not find CSRF token")
                    await self.session.close()
                    self.session = None
                    return False
                    
                csrf_token = token_match.group(1)
                
            # Authentification
            login_data = {
                'Username': self.username,
                'Password': self.password,
                'RememberMe': 'true',
                '__RequestVerificationToken': csrf_token
            }
            
            async with self.session.post(login_url, data=login_data, allow_redirects=True, timeout=10) as resp:
                if resp.status == 200:
                    # Vérifier qu'on est bien connecté
                    html = await resp.text()
                    if 'logoutForm' in html or 'Déconnexion' in html or 'Logout' in html:
                        logging.info("ABN: Login successful - session established")
                        return True
                    else:
                        logging.error("ABN: Login failed - bad credentials")
                        await self.session.close()
                        self.session = None
                        return False
                else:
                    logging.error(f"ABN: Login failed with status {resp.status}")
                    await self.session.close()
                    self.session = None
                    return False
                    
        except Exception as e:
            logging.error(f"ABN: Login exception: {e}")
            if self.session:
                await self.session.close()
                self.session = None
            return False
    
    async def search(self, params):
        """
        Recherche générique sur ABN
        params peut contenir: q, categories, freeleech, etc.
        """
        if not self.username or not self.password:
            return []
        
        # S'assurer d'avoir une session authentifiée
        if not await self._ensure_session():
            logging.error("ABN: Cannot search without valid session")
            return []
        
        search_url = f"{self.base_url}/Torrent"
        
        # Paramètres de recherche de base
        search_params = {
            'Search': params.get('q', ''),
            'UserId': '',
            'YearOperator': '≥',
            'Year': '',
            'RatingOperator': '≥',
            'Rating': '',
            'Pending': '',
            'Pack': '',
            'Scene': '',
            'Freeleech': '',
            'SortOn': 'Created',
            'SortOrder': 'desc'
        }
        
        logging.info(f"ABN: Searching with query: {params.get('q', '')}")
        
        # Construire l'URL avec les catégories
        # ABN utilise SelectedCats=X pour chaque catégorie
        if 'categories' in params and params['categories']:
            from urllib.parse import urlencode
            # Construire les params avec les catégories multiples
            cat_params = '&'.join([f'SelectedCats={cat}' for cat in params['categories']])
            base_params = urlencode(search_params)
            full_url = f"{search_url}?{base_params}&{cat_params}"
        else:
            from urllib.parse import urlencode
            full_url = f"{search_url}?{urlencode(search_params)}"
        
        try:
            async with self.session.get(full_url, timeout=10) as response:
                if response.status == 200:
                    html = await response.text()
                    results = self._parse_results(html)
                    logging.info(f"ABN: Found {len(results)} results")
                    return results
                else:
                    logging.warning(f"ABN: Search error {response.status}")
                    return []
        except Exception as e:
            logging.error(f"ABN: Search exception: {e}")
            return []
    
    def _parse_results(self, html):
        """Parse les résultats HTML de ABN"""
        results = []
        
        # Méthode 1: Parser les liens de détails d'abord
        # Format: <a href="/Torrent/Details?ReleaseId=XXXXX">Nom du torrent</a>
        details_pattern = re.compile(r'href="/Torrent/Details\?ReleaseId=(\d+)"[^>]*>([^<]+)</a>', re.IGNORECASE)
        details_matches = list(details_pattern.finditer(html))
        
        logging.debug(f"ABN: Found {len(details_matches)} potential torrent links")
        
        if not details_matches:
            logging.warning("ABN: No torrent details links found in HTML")
            # Essayer de voir s'il y a des download links
            download_pattern = re.compile(r'href="/Torrent/Download\?ReleaseId=(\d+)"', re.IGNORECASE)
            download_matches = list(download_pattern.finditer(html))
            logging.debug(f"ABN: Found {len(download_matches)} download links")
            return results
        
        # Méthode 2: Pour chaque torrent, extraire les infos complémentaires
        for idx, match in enumerate(details_matches):
            torrent_id = match.group(1)
            name = match.group(2).strip()
            
            # Nettoyer le nom (supprimer les espaces multiples, etc.)
            name = re.sub(r'\s+', ' ', name)
            
            logging.debug(f"ABN: Processing torrent {idx+1}/{len(details_matches)}: ID={torrent_id}, name={name[:50]}...")
            
            # Chercher la ligne complète du torrent dans le tableau
            # On cherche les td suivants après le lien de détails
            start_pos = match.start()
            # Trouver le début de la ligne <tr>
            tr_start = html.rfind('<tr', 0, start_pos)
            if tr_start == -1:
                logging.debug(f"ABN: No <tr> found before torrent {torrent_id}")
                tr_start = start_pos
            
            # Extraire jusqu'à la fin de la ligne </tr>
            tr_end = html.find('</tr>', start_pos)
            if tr_end == -1:
                logging.debug(f"ABN: No </tr> found after torrent {torrent_id}")
                continue
            
            row_html = html[tr_start:tr_end]
            
            # Extraire taille, seeders, leechers depuis cette ligne
            # Taille format: "X,XX Go" ou "XXX Mo" ou "XXX Ko"
            size_match = re.search(r'([\d,.]+ [KMGTkmgt][Oo])', row_html, re.IGNORECASE)
            size_str = size_match.group(1) if size_match else "0 o"
            
            # Seeders et leechers (dernières colonnes numériques)
            numbers = re.findall(r'<td[^>]*>(\d+)</td>', row_html)
            seeders = int(numbers[-2]) if len(numbers) >= 2 else 0
            leechers = int(numbers[-1]) if len(numbers) >= 1 else 0
            
            # Conversion de la taille en bytes
            size_bytes = self._parse_size(size_str)
            
            # Construction du lien de téléchargement
            download_url = f"{self.base_url}/Torrent/Download?ReleaseId={torrent_id}"
            details_url = f"{self.base_url}/Torrent/Details?ReleaseId={torrent_id}"
            
            result = {
                'name': name,
                'size': size_bytes,
                'tracker_name': 'ABN',
                'info_hash': None,  # ABN ne fournit pas le hash dans la liste
                'magnet': None,
                'link': download_url,
                'source': 'abn',
                'seeders': seeders,
                'leechers': leechers,
                'details_url': details_url,
                'torrent_id': torrent_id
            }
            results.append(result)
        
        logging.info(f"ABN: Successfully parsed {len(results)} torrents from HTML")
        return results
    
    def _parse_size(self, size_str):
        """Convertit une taille (ex: '1.5 Go') en bytes"""
        size_str = size_str.replace(',', '.').replace('o', 'B')
        
        match = re.match(r'([\d.]+)\s*([KMGT]?)B?', size_str, re.IGNORECASE)
        if not match:
            return 0
        
        value = float(match.group(1))
        unit = match.group(2).upper()
        
        multipliers = {
            '': 1,
            'K': 1024,
            'M': 1024**2,
            'G': 1024**3,
            'T': 1024**4
        }
        
        return int(value * multipliers.get(unit, 1))
    
    async def get_torrent_hash(self, torrent_id):
        """Récupère le hash d'un torrent depuis sa page de détails"""
        details_url = f"{self.base_url}/Torrent/Details?ReleaseId={torrent_id}"
        
        try:
            async with self.session.get(details_url, timeout=5) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    # Chercher le hash dans la page de détails
                    # Format ABN: Hash : <span class="text-italic">HASH_VALUE</span>
                    hash_match = re.search(r'Hash\s*:\s*<span[^>]*>([a-fA-F0-9]{40})</span>', html, re.IGNORECASE)
                    if hash_match:
                        hash_value = hash_match.group(1).lower()
                        logging.debug(f"ABN: Found hash for torrent {torrent_id}: {hash_value[:8]}...")
                        return hash_value
                    
                    # Fallback: essayer un format plus simple
                    hash_match = re.search(r'Hash[:\s]+([a-fA-F0-9]{40})', html, re.IGNORECASE)
                    if hash_match:
                        hash_value = hash_match.group(1).lower()
                        logging.debug(f"ABN: Found hash (fallback) for torrent {torrent_id}: {hash_value[:8]}...")
                        return hash_value
                    
                    logging.warning(f"ABN: No hash found in details page for torrent {torrent_id}")
                else:
                    logging.warning(f"ABN: Failed to get details page for torrent {torrent_id}: status {resp.status}")
        except Exception as e:
            logging.error(f"ABN: Error getting hash for torrent {torrent_id}: {e}")
        
        return None
    
    async def enrich_with_hashes(self, results):
        """Enrichit les résultats avec les info_hash en récupérant les pages de détails"""
        if not results:
            return results
        
        # Limiter à 15 pour plus de rapidité
        limit = min(len(results), 15)
        logging.info(f"ABN: Enriching {limit} torrents with hashes (parallel)...")
        
        # S'assurer d'avoir une session authentifiée
        if not await self._ensure_session():
            logging.warning("ABN: Cannot enrich hashes without valid session")
            return results
        
        # Récupérer les hash en parallèle
        tasks = []
        indices = []
        for i, result in enumerate(results[:limit]):
            if result.get('torrent_id'):
                tasks.append(self.get_torrent_hash(result['torrent_id']))
                indices.append(i)
        
        if tasks:
            # Utiliser un timeout pour ne pas attendre trop longtemps
            try:
                hashes = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=10.0  # Max 10 secondes pour tous les hash
                )
                
                enriched_count = 0
                for idx, hash_value in zip(indices, hashes):
                    if not isinstance(hash_value, Exception) and hash_value:
                        results[idx]['info_hash'] = hash_value
                        enriched_count += 1
                
                logging.info(f"ABN: Successfully enriched {enriched_count}/{len(tasks)} torrents with hashes")
            except asyncio.TimeoutError:
                logging.warning(f"ABN: Hash enrichment timed out after 10s")
        
        return results
    
    async def download_torrent(self, download_url):
        """Télécharge le fichier .torrent depuis ABN"""
        # S'assurer qu'on est connecté
        if not await self._ensure_session():
            return None
        
        try:
            async with self.session.get(download_url, timeout=15) as resp:
                if resp.status == 200:
                    return await resp.read()
                logging.error(f"ABN: Download error {resp.status}")
        except Exception as e:
            logging.error(f"ABN: Download exception: {e}")
        
        return None
    
    async def search_movie(self, title, year, original_title=None):
        """Recherche de films sur ABN (en français et anglais en parallèle)"""
        tasks = []
        
        # Préparer les recherches en parallèle
        if title:
            q = f"{title} {year}".strip()
            logging.info(f"ABN: Launching parallel search with French title: {q}")
            tasks.append(self.search({
                'q': q,
                'categories': [2]  # 2 = Movies selon la config Jackett
            }))
        
        # Recherche avec le titre original (anglais) si différent
        if original_title and original_title != title:
            q = f"{original_title} {year}".strip()
            logging.info(f"ABN: Launching parallel search with English title: {q}")
            tasks.append(self.search({
                'q': q,
                'categories': [2]
            }))
        
        # Exécuter toutes les recherches en parallèle
        if not tasks:
            return []
        
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Fusionner et dédupliquer
        all_results = []
        seen_ids = set()
        
        for results in results_list:
            if isinstance(results, Exception):
                logging.error(f"ABN: Search error: {results}")
                continue
            for r in results:
                if r.get('torrent_id') not in seen_ids:
                    all_results.append(r)
                    seen_ids.add(r.get('torrent_id'))
        
        # Enrichir avec les hash si possible
        all_results = await self.enrich_with_hashes(all_results)
        return all_results
    
    async def search_series(self, title, season, episode, original_title=None):
        """Recherche de séries sur ABN (en français et anglais en parallèle)"""
        tasks = []
        
        titles_to_search = [(title, "French")]
        if original_title and original_title != title:
            titles_to_search.append((original_title, "English"))
        
        # Préparer toutes les recherches en parallèle
        for search_title, lang in titles_to_search:
            # Recherche avec SxxExx
            if season is not None and episode is not None:
                s_str = f"S{int(season):02d}"
                e_str = f"E{int(episode):02d}"
                q = f"{search_title} {s_str}{e_str}"
                logging.info(f"ABN: Launching parallel search with {lang} title: {q}")
                tasks.append(self.search({
                    'q': q,
                    'categories': [1]  # 1 = Series selon la config Jackett
                }))
            
            # Recherche pack saison
            if season is not None:
                q = f"{search_title} S{int(season):02d}"
                logging.info(f"ABN: Launching parallel search for season pack with {lang} title: {q}")
                tasks.append(self.search({
                    'q': q,
                    'categories': [1]
                }))
        
        # Exécuter toutes les recherches en parallèle
        if not tasks:
            return []
        
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Fusionner et dédupliquer
        all_results = []
        seen_ids = set()
        
        for results in results_list:
            if isinstance(results, Exception):
                logging.error(f"ABN: Search error: {results}")
                continue
            for r in results:
                if r.get('torrent_id') not in seen_ids:
                    all_results.append(r)
                    seen_ids.add(r.get('torrent_id'))
        
        # Enrichir avec les hash
        all_results = await self.enrich_with_hashes(all_results)
        return all_results

