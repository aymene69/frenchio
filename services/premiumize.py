import aiohttp
import logging
import asyncio


class PremiumizeService:
    STREMTHRU_URL = "https://stremthru.13377001.xyz"

    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = self.STREMTHRU_URL
        self.headers = {
            "X-StremThru-Store-Name": "premiumize",
            "X-StremThru-Store-Authorization": f"Bearer {api_key}",
        }

    async def check_availability(self, hashes):
        if not hashes:
            return {}

        all_availability = {}
        batch_size = 50
        logging.info(f"Premiumize (StremThru): Checking {len(hashes)} hashes")

        async with aiohttp.ClientSession(trust_env=True) as session:
            for i in range(0, len(hashes), batch_size):
                batch = hashes[i:i + batch_size]
                params = [("magnet", f"magnet:?xt=urn:btih:{h}") for h in batch]
                try:
                    url = f"{self.base_url}/v0/store/magnets/check"
                    async with session.get(url, headers=self.headers, params=params) as resp:
                        if resp.status == 200:
                            result = await resp.json()
                            items = result.get("data", {}).get("items", [])
                            for item in items:
                                h = item.get("hash", "").lower()
                                status = item.get("status", "")
                                all_availability[h] = status == "cached"
                        else:
                            text = await resp.text()
                            logging.warning(f"Premiumize check failed: HTTP {resp.status} - {text[:300]}")
                            for h in batch:
                                all_availability[h.lower()] = False
                except Exception as e:
                    logging.error(f"Premiumize check exception: {e}")
                    for h in batch:
                        all_availability[h.lower()] = False

                if i + batch_size < len(hashes):
                    await asyncio.sleep(0.2)

        instant_count = sum(1 for v in all_availability.values() if v)
        logging.info(f"Premiumize: {instant_count}/{len(hashes)} cached")
        return all_availability

    async def unlock_magnet(self, magnet_hash, season=None, episode=None, media_type=None):
        magnet_hash = magnet_hash.strip().lower()
        logging.info(f"🔓 Premiumize unlock: hash={magnet_hash[:16]}...")

        async with aiohttp.ClientSession(trust_env=True) as session:
            magnet_link = f"magnet:?xt=urn:btih:{magnet_hash}"
            add_url = f"{self.base_url}/v0/store/magnets"

            try:
                async with session.post(add_url, headers=self.headers, json={"magnet": magnet_link}) as resp:
                    if resp.status not in (200, 201):
                        text = await resp.text()
                        logging.error(f"❌ Premiumize add magnet failed: HTTP {resp.status} - {text[:300]}")
                        return None

                    result = await resp.json()
                    magnet_data = result.get("data", {})
                    magnet_id = magnet_data.get("id")
                    status = magnet_data.get("status", "")
                    files = magnet_data.get("files", [])
            except Exception as e:
                logging.error(f"❌ Premiumize add magnet exception: {e}")
                return None

            if not files or status not in ("downloaded", "cached"):
                max_wait = 15
                poll_interval = 1.5
                elapsed = 0

                while elapsed < max_wait:
                    try:
                        info_url = f"{self.base_url}/v0/store/magnets/{magnet_id}"
                        async with session.get(info_url, headers=self.headers) as resp:
                            if resp.status == 200:
                                result = await resp.json()
                                magnet_data = result.get("data", {})
                                status = magnet_data.get("status", "")
                                files = magnet_data.get("files", [])
                                if status in ("downloaded", "cached") and files:
                                    break
                                elif status in ("failed", "invalid"):
                                    return None
                    except Exception as e:
                        logging.error(f"Premiumize info exception: {e}")

                    await asyncio.sleep(poll_interval)
                    elapsed += poll_interval

                if not files:
                    return None

            target_file = self._select_best_file(files, season, episode, media_type)
            if not target_file:
                return None

            file_link = target_file.get("link")
            if not file_link:
                return None

            try:
                gen_url = f"{self.base_url}/v0/store/link/generate"
                async with session.post(gen_url, headers=self.headers, json={"link": file_link}) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return result.get("data", {}).get("link")
            except Exception as e:
                logging.error(f"❌ Premiumize generate link exception: {e}")

        return None

    def _select_best_file(self, files, season=None, episode=None, media_type=None):
        if not files:
            return None

        video_extensions = ('.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.ts', '.m2ts', '.vob')
        bad_extensions = ('.iso', '.pdf', '.epub', '.txt', '.nfo', '.jpg', '.jpeg', '.png', '.rar', '.zip')

        video_files = [f for f in files if any(
            f.get('name', '').lower().endswith(ext) for ext in video_extensions
        )]

        if not video_files:
            video_files = [f for f in files if not any(
                f.get('name', '').lower().endswith(ext) for ext in bad_extensions
            )]

        if not video_files:
            return None

        if season is not None and episode is not None:
            s_str = f"{int(season):02d}"
            e_str = f"{int(episode):02d}"
            patterns = [f"S{s_str}E{e_str}", f"{int(season)}x{e_str}", f"S{int(season)}E{e_str}"]

            for f in video_files:
                name = (f.get('name', '') or f.get('path', '')).upper()
                for pat in patterns:
                    if pat.upper() in name:
                        return f

        return max(video_files, key=lambda x: x.get('size', 0))
