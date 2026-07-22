import re
import unicodedata

def normalize_title(title):
    if not title:
        return ""
    # Remove accents
    title = unicodedata.normalize('NFD', title).encode('ascii', 'ignore').decode('utf-8')
    # Remove punctuation and special characters, replace with space
    title = re.sub(r'[^\w\s]', ' ', title)
    # lowercase and normalize spaces
    return " ".join(title.lower().split())

def check_title_match(torrent_name, title_fr, title_en, year=None, is_movie=False):
    """
    Vérifie si le titre français ou anglais est présent dans le nom du torrent.
    Amélioré pour détecter les faux positifs (ex: Narcos match Narcos Mexico).
    """
    if not title_fr and not title_en:
        return True
        
    norm_torrent = normalize_title(torrent_name)
    norm_fr = normalize_title(title_fr)
    norm_en = normalize_title(title_en)
    
    # Mots qui peuvent suivre un titre sans que ce soit un autre média
    tech_tags = {
        '1080p', '720p', '4k', '2160p', 'uhd', 'dvd', 'sd', 'bluray', 'brrip', 'bdrip',
        'webrip', 'web', 'webdl', 'dvdrip', 'cam', 'ts', 'vff', 'vf', 'vfq', 'vf2', 
        'vostfr', 'multi', 'truefrench', 'french', 'eng', 'english', 'en', 'vo', 'fr',
        'x264', 'x265', 'hevc', 'h264', 'h265', 'av1', 'hdr', 'dv', 'dolby', 'vision',
        '10bit', 'light', 'repack', 'proper', 'internal', 'extended', 'uncut',
        'subfrench', 'subforced', 'nf', 'netflix', 'amzn', 'amazon', 'dnp', 'dsnp', 'hmax',
        'ac3', 'dts', 'dd5', 'dd2', 'aac', 'mkv', 'mp4', 'avi', 'tv', 'show', 'complete',
        'integrale', 'integra', 'vol', 'volume', 'part', 'party', 'uncut', 'dual', 'hdtv'
    }

    def is_strict_match(target, torrent):
        if not target: return False
        
        # On cherche le titre exact avec bordures de mots
        pattern = r'\b' + re.escape(target) + r'\b'
        match = re.search(pattern, torrent)
        if not match:
            return False
            
        # On vérifie ce qui suit immédiatement le titre
        end_idx = match.end()
        after_text = torrent[end_idx:].strip()
        if not after_text:
            return True # Titre exact à la fin
            
        # On prend le prochain mot
        next_word = after_text.split()[0]
        
        # Si le prochain mot est une année, un épisode (s01, 1x01) ou un tag technique -> OK
        if re.match(r'^(19|20)\d{2}$', next_word): # Année
            return True
        if re.match(r'^[sx]\d+$', next_word): # S01, x01
            return True
        if re.match(r'^s\d+e\d+$', next_word): # S01E01
            return True
        if next_word in tech_tags:
            return True
            
        # Si le prochain mot fait partie de l'AUTRE titre (ex: "Narcos" vs "Narcos Mexico")
        # Si on cherche "Narcos" (FR) et que EN est "Narcos Mexico", et que le torrent a "Mexico" -> OK
        # Mais ici on vérifie si next_word est dans norm_fr ou norm_en
        if next_word in norm_fr.split() or next_word in norm_en.split():
            return True
            
        # Si c'est un mot inconnu (ex: "Mexico" alors que la cible est juste "Narcos") -> Faux positif probable
        return False

    title_match = is_strict_match(norm_fr, norm_torrent) or is_strict_match(norm_en, norm_torrent)
            
    if not title_match:
        return False
    if is_movie and year:
        try:
            y = int(year)
            # Pour les films, l'année est cruciale pour éviter les remakes/suites
            if str(y) not in norm_torrent and str(y-1) not in norm_torrent and str(y+1) not in norm_torrent:
                return False
        except ValueError:
            if str(year) not in norm_torrent:
                return False
                
    return True

def format_size(size_bytes):
    """Formate une taille en octets vers une chaine lisible (Go, Mo)"""
    try:
        size = float(size_bytes)
    except (ValueError, TypeError):
        return "0 B"

    if size >= 1024**3:
        return f"{size / (1024**3):.2f} Go"
    elif size >= 1024**2:
        return f"{size / (1024**2):.2f} Mo"
    else:
        return f"{size / 1024:.2f} Ko"

def is_video_file(filename):
    """
    Vérifie si le fichier/torrent semble être une vidéo.
    On exclut les extensions non-vidéo connues (.iso, .pdf, .epub, .zip, etc.).
    Pour les torrents, le nom n'a souvent pas d'extension, on l'accepte par défaut.
    """
    if not filename:
        return False
    
    filename_lower = filename.lower()
    
    # Liste des extensions non-vidéo à exclure absolument
    bad_extensions = (
        '.iso', '.pdf', '.epub', '.txt', '.nfo', '.jpg', '.jpeg', '.png', 
        '.rar', '.zip', '.7z', '.tar', '.gz', '.exe', '.doc', '.docx'
    )
    if filename_lower.endswith(bad_extensions):
        return False
        
    # Liste des extensions vidéo connues (pour acceptation immédiate)
    video_extensions = (
        '.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', 
        '.m4v', '.mpg', '.mpeg', '.ts', '.m2ts', '.vob', '.divx'
    )
    if filename_lower.endswith(video_extensions):
        return True
    
    # Si le nom contient un point suivi de 2-4 caractères à la fin, 
    # c'est probablement une extension inconnue (et potentiellement non-vidéo)
    # Mais attention, beaucoup de torrents ont des points dans le nom (ex: Movie.Name.1080p)
    # On ne filtre PAS si ça ressemble à un titre de torrent standard (sans extension de fichier à la fin)
    
    # Si le nom se termine par une extension (3-4 caractères après le dernier point)
    # qui n'est pas dans notre liste de vidéos, on pourrait être suspicieux.
    # Mais pour l'instant, on va rester permissif : on ne bloque que les "bad_extensions".
    
    return True

def parse_torrent_name(name):
    """Analyse le nom du torrent pour extraire qualité, langue, codec et type de release"""
    if not name:
        return {"name": "", "quality": "", "codec": "", "language": "", "release_type": ""}
        
    name_upper = name.upper()
    
    # Qualité
    quality = ""
    if any(q in name_upper for q in ["2160P", "4K", "UHD"]):
        quality = "4K"
    elif "1080P" in name_upper:
        quality = "1080p"
    elif "720P" in name_upper:
        quality = "720p"
    elif any(q in name_upper for q in ["480P", "SD", "DVD"]):
        quality = "SD"
        
    # Codec
    codec = ""
    if any(c in name_upper for c in ["X265", "HEVC", "H265"]):
        codec = "x265"
    elif any(c in name_upper for c in ["X264", "AVC", "H264"]):
        codec = "x264"
    elif "AV1" in name_upper:
        codec = "AV1"
    
    # HDR / Bitrate
    extras = []
    if "HDR" in name_upper: extras.append("HDR")
    if any(dv in name_upper for dv in ["DV", "DOLBY VISION"]): extras.append("DV")
    if "10BIT" in name_upper: extras.append("10bit")
    
    # Release Type
    release_type = ""
    if "WEBRIP" in name_upper:
        release_type = "WebRIP"
    elif "WEB-DL" in name_upper or "WEBDL" in name_upper:
        release_type = "WEB-DL"
    elif re.search(r'\bWEB\b', name_upper):
        release_type = "WEB-DL"
    elif any(br in name_upper for br in ["BRRIP", "BDRIP", "BLURAY", "BDLIGHT"]):
        release_type = "BDRip"
    elif "DVDRIP" in name_upper:
        release_type = "DVDRip"
    elif re.search(r'\bCAM\b', name_upper) or re.search(r'\bHDTS\b|\bHD-TS\b|\bTS\b', name_upper):
        release_type = "CAM"

    # Langues
    languages = []
    if "MULTI" in name_upper:
        languages.append("Multi")
    if "VOSTFR" in name_upper:
        languages.append("VOSTFR")
    if "TRUEFRENCH" in name_upper or "VFF" in name_upper:
        languages.append("VFF")
    elif "VF2" in name_upper:
        languages.append("VF2")
    elif "VFQ" in name_upper:
        languages.append("VFQ")
    elif "FRENCH" in name_upper or "VF" in name_upper:
        languages.append("VF")
    
    # Si rien de détecté mais original_title != title
    if not languages and ("EN" in name_upper or "VO" in name_upper or "ENG" in name_upper):
        languages.append("VO")
    
    # Formatage de l'affichage classique (title)
    display_langs = []
    for lang in languages:
        if lang == "Multi": display_langs.append("🇫🇷+🇺🇸 MULTI")
        elif lang == "VFF": display_langs.append("🇫🇷 VFF")
        elif lang == "VF": display_langs.append("🇫🇷 VF")
        elif lang == "VFQ": display_langs.append("🇨🇦 VFQ")
        elif lang == "VOSTFR": display_langs.append("🇫🇷🇯🇵 VOSTFR")
        elif lang == "VO": display_langs.append("🇺🇸 VO")

    title_parts = []
    if quality: title_parts.append(f"📺 {quality}")
    if release_type: title_parts.append(f"📦 {release_type}")
    if codec: title_parts.append(f"🎞️ {codec}")
    if extras: title_parts.append(f"✨ {' '.join(extras)}")
    if display_langs: title_parts.append(f"{' '.join(display_langs)}")
    
    return {
        "name": " | ".join(title_parts),
        "quality": quality,
        "codec": codec,
        "language": ", ".join(languages) if languages else "Français",
        "release_type": release_type
    }

def check_season_episode(name, target_season, target_episode, exclude_packs=False):
    """
    Vérifie si le torrent correspond à la saison/épisode demandé.
    Retourne True si c'est bon (match exact ou pack saison).
    Retourne False si c'est un autre épisode/saison.
    """
    if target_season is None:
        return True
        
    name_upper = name.upper()
    
    # Extraction SxxExx
    # Regex améliorée pour capturer les ranges d'épisodes (ex: S05E02-E03 ou S05E02E03)
    se_pattern = re.compile(r'(?:S|SAISON|SEASON)[ ._-]?(\d{1,2})(?:[ ._-]?E(\d{1,2}))(?:(?:[ ._-]*(?:E|-|~)[ ._-]*)(\d{1,2}))?', re.IGNORECASE)
    matches = se_pattern.findall(name_upper)
    
    # Si aucun pattern Sxx trouvé, on essaie 1x01
    if not matches:
        x_pattern = re.compile(r'(\d{1,2})x(\d{1,2})', re.IGNORECASE)
        matches = [(m[0], m[1], None) for m in x_pattern.findall(name_upper)]
        
    # Si toujours rien, on cherche juste le pattern Saison sans épisode (Pack Saison)
    if not matches:
        s_only_pattern = re.compile(r'(?:S|SAISON|SEASON)[ ._-]?(\d{1,2})', re.IGNORECASE)
        matches = [(m, None, None) for m in s_only_pattern.findall(name_upper)]

    if not matches:
        return False # Pour une série, si on ne trouve aucune info de saison/épisode, on rejette

    for s, e_start, e_end in matches:
        try:
            season = int(s)
            if season != target_season:
                continue
                
            # Si pas d'épisode dans le nom (Pack Saison) -> OK sauf si on exclut les packs
            if e_start is None:
                if exclude_packs:
                    return False
                return True
                
            start = int(e_start)
            end = int(e_end) if e_end else start
            
            # Vérification de l'épisode (dans le range)
            if start <= target_episode <= end:
                return True
                
        except ValueError:
            continue
            
    return False

