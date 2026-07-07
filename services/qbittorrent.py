import qbittorrentapi
import logging
import time
import urllib.parse
import os

class QBittorrentService:
    def __init__(self, host, username, password, public_url_base, category=None):
        """
        Initialise le client qBittorrent avec la librairie officielle qbittorrent-api
        Docs: https://pypi.org/project/qbittorrent-api/
        """
        # Parser l'URL pour extraire host et port
        parsed = urllib.parse.urlparse(host if host.startswith('http') else f'http://{host}')
        
        self.host = host.rstrip('/')
        self.public_url_base = public_url_base.rstrip('/')
        self.category = category or os.getenv('QBITTORRENT_CATEGORY', 'frenchio')
        
        # Créer le client qBittorrent
        try:
            self.client = qbittorrentapi.Client(
                host=parsed.hostname or 'localhost',
                port=parsed.port or 8080,
                username=username,
                password=password,
                REQUESTS_ARGS={'timeout': 30}
            )
            logging.info(f"qBittorrent client created for {parsed.hostname}:{parsed.port}")
        except Exception as e:
            logging.error(f"Failed to create qBittorrent client: {e}")
            self.client = None

    def test_connection(self):
        """Test la connexion à qBittorrent"""
        if not self.client:
            return False
            
        try:
            # La librairie gère automatiquement le login lors du premier appel
            version = self.client.app.version
            api_version = self.client.app.web_api_version
            logging.info(f"✅ qBittorrent connected: v{version} (API v{api_version})")
            return True
        except qbittorrentapi.LoginFailed as e:
            logging.error(f"❌ qBittorrent Login Failed: {e}")
            return False
        except qbittorrentapi.Forbidden403Error as e:
            logging.error(f"❌ qBittorrent 403 Forbidden: {e}")
            logging.error("   → Vérifiez que le WebUI est activé et accessible")
            logging.error("   → Vérifiez les identifiants (username/password)")
            return False
        except Exception as e:
            logging.error(f"❌ qBittorrent Connection Error: {e}")
            return False

    def add_torrent(self, torrent_data, is_file=False):
        """
        Ajoute un torrent à qBittorrent
        
        Args:
            torrent_data: Contenu binaire du .torrent ou URL magnet
            is_file: True si torrent_data est un fichier binaire
        """
        if not self.client:
            logging.error("qBittorrent client not initialized")
            return None
            
        try:
            # Activer la pré-allocation globale (requis pour la lecture en cours de téléchargement)
            try:
                self.client.app_set_preferences(prefs={'preallocate_all': True})
                logging.info("🔧 Global preallocation enabled in qBittorrent")
            except Exception as e:
                logging.warning(f"Could not enable global preallocation: {e}")

            # Créer la catégorie si elle n'existe pas
            try:
                self.client.torrents_create_category(name=self.category)
            except qbittorrentapi.Conflict409Error:
                pass
            except Exception as e:
                logging.warning(f"Could not create/verify category '{self.category}': {e}")

            # Options de streaming (l'API les supporte bien)
            streaming_opts = {
                'is_paused': False,
                'is_sequential_download': True,
                'is_first_last_piece_priority': True,
                'category': self.category
            }
            
            if is_file:
                # Ajouter depuis un fichier .torrent
                logging.info(f"Adding .torrent file ({len(torrent_data)} bytes) with streaming options")
                result = self.client.torrents_add(
                    torrent_files=torrent_data,
                    **streaming_opts
                )
            else:
                # Ajouter depuis un magnet/URL
                logging.info("Adding magnet/URL with streaming options")
                result = self.client.torrents_add(
                    urls=torrent_data,
                    **streaming_opts
                )
            
            # La librairie retourne "Ok." en cas de succès
            if result == "Ok.":
                logging.info("✅ Torrent added successfully")
                return True
            else:
                logging.warning(f"Unexpected response from qBittorrent: {result}")
                return True  # On considère quand même que ça a fonctionné
                
        except qbittorrentapi.Conflict409Error:
            # Le torrent existe déjà, ce n'est pas une erreur critique
            logging.info("ℹ️ Torrent already exists in qBittorrent")
            return True
        except Exception as e:
            logging.error(f"❌ Failed to add torrent: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return None

    def configure_sequential(self, info_hash):
        """
        Force l'activation du téléchargement séquentiel et la priorité début/fin
        
        Args:
            info_hash: Hash du torrent
        """
        if not self.client:
            logging.error("Client not initialized")
            return False
            
        try:
            h = info_hash.lower()
            
            logging.info(f"🔧 Forcing streaming options for torrent {h[:8]}...")
            
            # Récupérer l'état actuel depuis torrents_info
            torrents = self.client.torrents_info(torrent_hashes=h)
            if torrents:
                torrent = torrents[0]
                seq_enabled = torrent.get('seq_dl', False)
                first_last_enabled = torrent.get('f_l_piece_prio', False)
            else:
                seq_enabled = False
                first_last_enabled = False
            
            logging.info(f"   Current state: sequential={seq_enabled}, first_last={first_last_enabled}")
            
            # Activer le téléchargement séquentiel (toggle si pas activé)
            if not seq_enabled:
                try:
                    self.client.torrents_toggle_sequential_download(torrent_hashes=h)
                    logging.info(f"   ✅ Sequential download: OFF → ON")
                except Exception as e:
                    logging.error(f"   ❌ Failed to toggle sequential download: {e}")
                    raise
            else:
                logging.info(f"   ℹ️ Sequential download already ON")
            
            # Activer la priorité des premières et dernières pièces (toggle si pas activé)
            if not first_last_enabled:
                try:
                    self.client.torrents_toggle_first_last_piece_priority(torrent_hashes=h)
                    logging.info(f"   ✅ First/Last piece priority: OFF → ON")
                except Exception as e:
                    logging.error(f"   ❌ Failed to toggle first/last priority: {e}")
                    raise
            else:
                logging.info(f"   ℹ️ First/Last piece priority already ON")
            
            logging.info(f"✅ All streaming options configured for {h[:8]}...")
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to configure streaming options: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return False

    def get_torrent_files(self, info_hash, max_retries=15, season=None, episode=None, fast_mode=False):
        """
        Récupère les fichiers d'un torrent et sélectionne le bon
        
        Args:
            info_hash: Hash du torrent
            max_retries: Nombre max de tentatives pour attendre les métadonnées
            season: Numéro de saison (pour séries)
            episode: Numéro d'épisode (pour séries)
            fast_mode: Si True, réduit les délais pour un streaming instantané
            
        Returns:
            Nom du fichier sélectionné ou None
        """
        if not self.client:
            return None
            
        h = info_hash.lower()
        
        # En mode rapide, moins de retries et délais plus courts
        if fast_mode:
            max_retries = 8
            retry_delay = 0.5  # 500ms entre chaque tentative
        else:
            retry_delay = 1.0  # 1s entre chaque tentative
        
        # Attendre que les métadonnées soient disponibles
        logging.info(f"🔍 Looking for files in torrent (fast_mode={fast_mode})...")
        
        for retry in range(max_retries):
            try:
                files = self.client.torrents_files(torrent_hash=h)
                
                if files:
                    logging.info(f"✅ Found {len(files)} files in torrent")
                    
                    # Sélection du fichier
                    target_file = None
                    
                    if season is not None and episode is not None:
                        # Chercher le fichier correspondant à l'épisode
                        import re
                        s_str = f"{int(season):02d}"
                        e_str = f"{int(episode):02d}"
                        
                        patterns = [
                            re.compile(rf'S{s_str}E{e_str}', re.IGNORECASE),
                            re.compile(rf'{int(season)}x{e_str}', re.IGNORECASE),
                            re.compile(rf'E{e_str}', re.IGNORECASE)
                        ]
                        
                        # Chercher parmi les fichiers (triés par taille décroissante)
                        sorted_files = sorted(files, key=lambda x: x.size, reverse=True)
                        
                        for f in sorted_files:
                            fname = f.name
                            for pat in patterns:
                                if pat.search(fname):
                                    target_file = fname
                                    logging.info(f"✅ Selected episode file: {fname}")
                                    break
                            if target_file:
                                break
                    
                    # Fallback: le plus gros fichier vidéo
                    if not target_file:
                        video_exts = ['.mkv', '.mp4', '.avi', '.mov', '.wmv', '.m4v']
                        video_files = [f for f in files if any(f.name.lower().endswith(ext) for ext in video_exts)]
                        
                        if video_files:
                            largest = max(video_files, key=lambda x: x.size)
                            target_file = largest.name
                            logging.info(f"✅ Selected largest video file: {target_file} ({largest.size} bytes)")
                        else:
                            # Prendre le plus gros fichier tout court
                            largest = max(files, key=lambda x: x.size)
                            target_file = largest.name
                            logging.info(f"✅ Selected largest file: {target_file} ({largest.size} bytes)")
                    
                    return target_file
                    
            except Exception as e:
                if retry < max_retries - 1:
                    logging.debug(f"⏳ Waiting for metadata... ({retry + 1}/{max_retries})")
                    time.sleep(retry_delay)
                else:
                    logging.error(f"Failed to get torrent files: {e}")
            
            # Pas d'exception mais pas de fichiers non plus
            if retry < max_retries - 1:
                logging.debug(f"⏳ No files yet, retrying... ({retry + 1}/{max_retries})")
                time.sleep(retry_delay)
                    
        logging.error(f"❌ Could not find files after {max_retries} retries")
        return None

    def verify_and_fix_streaming_options(self, info_hash):
        """
        Vérifie que les options de streaming sont bien activées, sinon les force à nouveau
        """
        if not self.client:
            return False
        
        try:
            h = info_hash.lower()
            
            logging.info(f"🔍 Verifying streaming options for torrent {h[:8]}...")
            
            # Récupérer les propriétés depuis torrents_info
            torrents = self.client.torrents_info(torrent_hashes=h)
            if torrents:
                torrent = torrents[0]
                seq_enabled = torrent.get('seq_dl', False)
                first_last_enabled = torrent.get('f_l_piece_prio', False)
            else:
                seq_enabled = False
                first_last_enabled = False
            
            logging.info(f"📊 Current status (from qBittorrent):")
            logging.info(f"   seq_dl = {seq_enabled} {'✅ ON' if seq_enabled else '❌ OFF'}")
            logging.info(f"   f_l_piece_prio = {first_last_enabled} {'✅ ON' if first_last_enabled else '❌ OFF'}")
            
            # Si l'une des options n'est pas activée, on les force à nouveau
            if not seq_enabled or not first_last_enabled:
                logging.warning("⚠️ Streaming options NOT applied correctly, forcing again...")
                self.configure_sequential(info_hash)
                
                # Vérifier à nouveau
                time.sleep(0.5)
                torrents2 = self.client.torrents_info(torrent_hashes=h)
                if torrents2:
                    t2 = torrents2[0]
                    seq2 = t2.get('seq_dl', False)
                    first_last2 = t2.get('f_l_piece_prio', False)
                else:
                    seq2, first_last2 = False, False
                logging.info(f"📊 After second attempt:")
                logging.info(f"   sequential = {seq2}")
                logging.info(f"   first_last = {first_last2}")
                
                return True
            else:
                logging.info("✅ Streaming options verified: ALL ON")
            
            return True
            
        except Exception as e:
            logging.error(f"❌ Failed to verify streaming options: {e}")
            import traceback
            logging.error(traceback.format_exc())
            return False

    def manage_stream(self, torrent_data, info_hash, is_file=False, season=None, episode=None):
        """
        Orchestre l'ajout du torrent et retourne l'URL de streaming IMMÉDIATEMENT
        Le téléchargement se fait en arrière-plan, le player lit au fur et à mesure
        
        Args:
            torrent_data: Contenu binaire du .torrent ou URL magnet
            info_hash: Hash du torrent
            is_file: True si torrent_data est un fichier binaire
            season: Numéro de saison (pour séries)
            episode: Numéro d'épisode (pour séries)
            
        Returns:
            URL HTTP du fichier vidéo pour streaming (même si téléchargement en cours)
        """
        # 1. Ajouter le torrent avec les options de streaming
        if not self.add_torrent(torrent_data, is_file):
            return None
        
        logging.info("⚡ Torrent added, preparing instant stream...")
        
        # 2. Petite pause pour que qBittorrent initialise le torrent
        time.sleep(1.5)
        
        # 3. FORCER les options de streaming en parallèle de l'obtention des fichiers
        # (ne pas attendre, c'est juste pour être sûr)
        logging.info("🔧 Forcing streaming options (non-blocking)...")
        self.configure_sequential(info_hash)
        
        # 4. Récupérer le fichier cible (avec retry rapide)
        target_file = self.get_torrent_files(info_hash, season=season, episode=episode, fast_mode=True)
        
        if not target_file:
            logging.error("❌ Could not identify target file")
            return None
        
        # 4.5. Attendre que l'allocation disque et le téléchargement des métadonnées soient terminés
        # (évite que le lecteur ne se connecte trop tôt et reçoive une erreur 404 du serveur HTTP/WebDAV)
        logging.info("⏳ Waiting for disk allocation and metadata download to complete...")
        h = info_hash.lower()
        for i in range(15):  # Attendre jusqu'à 15 secondes max
            try:
                torrents = self.client.torrents_info(torrent_hashes=h)
                if torrents:
                    state = torrents[0].get('state', '')
                    logging.info(f"   Torrent state: {state} ({i+1}/15)")
                    if state not in ['metaDL', 'allocating']:
                        logging.info("   ✅ Disk allocation completed (file created on disk)")
                        break
            except Exception as e:
                logging.warning(f"Error checking torrent state: {e}")
            time.sleep(1.0)

        # 5. Construire l'URL de streaming et la retourner IMMÉDIATEMENT
        # Le téléchargement continue en background, le player va lire au fur et à mesure
        safe_path = urllib.parse.quote(target_file)
        stream_url = f"{self.public_url_base}/{safe_path}"
        
        logging.info(f"🎬 INSTANT STREAM ready: {stream_url}")
        logging.info(f"   ⚡ Player will read file as it downloads (sequential mode)")
        logging.info(f"   📥 qBittorrent is downloading in background...")
        
        return stream_url
