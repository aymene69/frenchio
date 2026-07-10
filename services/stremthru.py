import aiohttp
import asyncio
import base64
import binascii
import json
import logging

# Stores supportés par StremThru et mapping vers les clés de config Frenchio
STREMTHRU_STORES = {
    "alldebrid": "alldebrid_key",
    "torbox": "torbox_key",
    "debridlink": "debridlink_key",
    "realdebrid": "realdebrid_key",
}


class StremThruService:
    """
    Proxy les appels à l'API du débrideur via une instance StremThru
    (https://github.com/MunifTanjim/stremthru).

    Utile quand l'IP du serveur Frenchio est bloquée par le débrideur
    (ex: AllDebrid refuse les IP de datacenter). StremThru expose une API
    "store" unifiée : c'est lui qui parle au débrideur, avec sa propre IP.
    Interface identique aux services natifs : check_availability + unlock_magnet.
    """

    # Statuts de magnet StremThru considérés comme lisibles immédiatement
    READY_STATUSES = ("cached", "downloaded")

    def __init__(self, url, store_name, api_key, auth=None, client_ip=None):
        self.base_url = url.rstrip('/') + "/v0/store"
        self.store_name = store_name
        self.api_key = api_key
        self.auth = auth  # "user:pass" si l'instance est protégée (STREMTHRU_AUTH)
        self.client_ip = client_ip

    def _headers(self):
        headers = {
            "X-StremThru-Store-Name": self.store_name,
            "X-StremThru-Store-Authorization": f"Bearer {self.api_key}",
            "User-Agent": "frenchio",
        }
        if self.auth:
            encoded = base64.b64encode(self.auth.encode('utf-8')).decode('ascii')
            headers["Proxy-Authorization"] = f"Basic {encoded}"
        return headers

    def _params(self, extra=None):
        params = dict(extra or {})
        if self.client_ip:
            params["client_ip"] = self.client_ip
        return params

    def _clean_hash(self, hash_str):
        """Nettoie le hash (même logique que les services natifs)."""
        if not hash_str:
            return None

        clean = hash_str.strip().lower()

        # Certains trackers renvoient le hash hex-encodé deux fois (80 chars)
        if len(clean) == 80:
            try:
                decoded = binascii.unhexlify(clean).decode('utf-8')
                if len(decoded) == 40 and all(c in '0123456789abcdef' for c in decoded):
                    return decoded
            except Exception:
                pass

        return clean

    @staticmethod
    def _extract_error(data):
        """Extrait un message d'erreur lisible d'une réponse StremThru."""
        if not isinstance(data, dict):
            return None
        error = data.get('error')
        if isinstance(error, dict):
            upstream = error.get('__upstream_cause__') or {}
            return error.get('message') or upstream.get('detail') or upstream.get('message') or json.dumps(error)[:300]
        if error:
            return str(error)
        return None

    async def check_availability(self, hashes):
        """
        Vérifie la disponibilité en cache via GET /v0/store/magnets/check.
        Retourne un dict {hash: bool}.
        """
        if not hashes:
            return {}

        cleaned_hashes = []
        seen = set()
        for h in hashes:
            cleaned = self._clean_hash(h)
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                cleaned_hashes.append(cleaned)

        if not cleaned_hashes:
            return {}

        availability = {}
        batch_size = 100
        url = f"{self.base_url}/magnets/check"

        logging.info(f"StremThru [{self.store_name}]: Checking availability for {len(cleaned_hashes)} hashes")

        async with aiohttp.ClientSession(trust_env=True) as session:
            async def _check_batch(batch):
                params = self._params({"magnet": ",".join(batch)})
                try:
                    async with session.get(url, params=params, headers=self._headers()) as resp:
                        data = await resp.json(content_type=None)
                        error = self._extract_error(data)
                        if error or resp.status >= 400:
                            logging.warning(f"StremThru [{self.store_name}] check error (HTTP {resp.status}): {error}")
                            return []
                        return data.get('data', {}).get('items', [])
                except Exception as e:
                    logging.error(f"StremThru [{self.store_name}] check exception: {e}")
                    return []

            batches = [cleaned_hashes[i:i + batch_size] for i in range(0, len(cleaned_hashes), batch_size)]
            results = await asyncio.gather(*[_check_batch(b) for b in batches])

        cached_count = 0
        for items in results:
            for item in items:
                h = (item.get('hash') or '').lower()
                if not h:
                    continue
                is_cached = item.get('status') == 'cached'
                availability[h] = is_cached
                if is_cached:
                    cached_count += 1

        logging.info(f"StremThru [{self.store_name}]: {cached_count}/{len(cleaned_hashes)} cached")
        return availability

    async def unlock_magnet(self, magnet_hash, season=None, episode=None, media_type=None):
        """
        Ajoute le magnet au store via StremThru puis génère le lien direct.
        POST /v0/store/magnets -> sélection du fichier -> POST /v0/store/link/generate
        """
        magnet_hash = self._clean_hash(magnet_hash)
        logging.info(f"🔓 StremThru [{self.store_name}] unlock_magnet: hash={magnet_hash}, S{season}E{episode}, type={media_type}")

        magnet_uri = f"magnet:?xt=urn:btih:{magnet_hash}"

        async with aiohttp.ClientSession(trust_env=True) as session:
            # 1. Ajout du magnet au store
            try:
                async with session.post(
                    f"{self.base_url}/magnets",
                    params=self._params(),
                    json={"magnet": magnet_uri},
                    headers=self._headers()
                ) as resp:
                    data = await resp.json(content_type=None)
                    error = self._extract_error(data)
                    if error or resp.status >= 400:
                        logging.error(f"❌ StremThru [{self.store_name}] add magnet failed (HTTP {resp.status}): {error}")
                        return None
            except Exception as e:
                logging.error(f"❌ StremThru [{self.store_name}] add magnet exception: {e}")
                return None

            magnet_data = data.get('data', {})
            status = magnet_data.get('status', '')

            if status not in self.READY_STATUSES:
                logging.error(f"❌ StremThru [{self.store_name}]: Magnet not cached (status: {status})")
                return None

            files = [
                {
                    'link': f.get('link'),
                    'filename': f.get('name') or f.get('path', ''),
                    'size': f.get('size', 0)
                }
                for f in magnet_data.get('files', [])
                if f.get('link')
            ]

            if not files:
                logging.error(f"❌ StremThru [{self.store_name}]: No files in magnet response")
                return None

            logging.info(f"🔗 StremThru [{self.store_name}]: {len(files)} files in torrent")
            target_link = self._select_link(files, season, episode, media_type)
            if not target_link:
                logging.error(f"❌ StremThru [{self.store_name}]: No suitable file selected")
                return None

            # 2. Génération du lien direct
            try:
                async with session.post(
                    f"{self.base_url}/link/generate",
                    params=self._params(),
                    json={"link": target_link},
                    headers=self._headers()
                ) as resp:
                    data = await resp.json(content_type=None)
                    error = self._extract_error(data)
                    if error or resp.status >= 400:
                        logging.error(f"❌ StremThru [{self.store_name}] link generation failed (HTTP {resp.status}): {error}")
                        return None

                    link = data.get('data', {}).get('link')
                    if link:
                        logging.info(f"✅ StremThru [{self.store_name}] unlocked: {link[:80]}...")
                    else:
                        logging.error(f"❌ StremThru [{self.store_name}]: No link in generation response")
                    return link
            except Exception as e:
                logging.error(f"❌ StremThru [{self.store_name}] link generation exception: {e}")
                return None

    def _select_link(self, links, season, episode, media_type):
        """Sélectionne le bon fichier dans le torrent (même logique qu'AllDebrid)."""
        if not links:
            return None

        logging.info(f"🎯 StremThru selecting file for S{season}E{episode} (type={media_type}) among {len(links)} files")

        # Si épisode spécifique
        if season is not None and episode is not None:
            s_str = f"{int(season):02d}"
            e_str = f"{int(episode):02d}"

            patterns = [
                f"S{s_str}E{e_str}",  # S01E01
                f"{int(season)}x{e_str}",  # 1x01
                f"S{int(season)}E{e_str}",  # S1E01
                f"S{s_str}.E{e_str}"  # S01.E01
            ]

            for link in links:
                filename = link.get('filename', '').upper()
                for pat in patterns:
                    if pat.upper() in filename:
                        logging.info(f"Match found: {link.get('filename')} (Pattern: {pat})")
                        return link['link']

            logging.warning(f"No strict match found for S{season}E{episode}. Files available: {[l.get('filename') for l in links[:5]]}...")

        # Filtrage par extension (Vidéos uniquement)
        video_extensions = ('.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.ts', '.m2ts', '.vob')
        bad_extensions = ('.iso', '.pdf', '.epub', '.txt', '.nfo', '.jpg', '.jpeg', '.png', '.rar', '.zip')

        video_links = [l for l in links if any(l.get('filename', '').lower().endswith(ext) for ext in video_extensions)]

        if not video_links:
            video_links = [lnk for lnk in links if not any(lnk.get('filename', '').lower().endswith(ext) for ext in bad_extensions)]

        if not video_links:
            logging.error(f"❌ StremThru _select_link: No video files found in torrent")
            return None

        # Si Film ou pas trouvé par pattern, on prend le plus gros fichier parmi les vidéos
        sorted_links = sorted(video_links, key=lambda x: x.get('size', 0), reverse=True)
        best_link = sorted_links[0]

        logging.info(f"Fallback/Movie: Selected largest video: {best_link.get('filename')} ({best_link.get('size')} bytes)")
        return best_link['link']
