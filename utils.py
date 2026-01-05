import re

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

def parse_torrent_name(name):
    """Analyse le nom du torrent pour extraire qualité et langue"""
    name_upper = name.upper()
    
    # Qualité
    quality = ""
    if "2160P" in name_upper or "4K" in name_upper:
        quality = "4K"
    elif "1080P" in name_upper:
        quality = "1080p"
    elif "720P" in name_upper:
        quality = "720p"
    elif "480P" in name_upper or "SD" in name_upper:
        quality = "SD"
        
    # Codec / HDR
    extras = []
    if "HDR" in name_upper: extras.append("HDR")
    if "DV" in name_upper or "DOLBY VISION" in name_upper: extras.append("DV")
    if "X265" in name_upper or "HEVC" in name_upper: extras.append("x265")
    
    # Langues
    langs = []
    
    # Priorité aux Multi et VFF
    if "MULTI" in name_upper:
        langs.append("🇫🇷+🇺🇸 MULTI")
    elif "TRUEFRENCH" in name_upper or "VFF" in name_upper:
        langs.append("🇫🇷 VFF")
    elif "FRENCH" in name_upper or "VF" in name_upper:
        langs.append("🇫🇷 VF")
    elif "VOSTFR" in name_upper or "SUBFRENCH" in name_upper:
        langs.append("🇫🇷🇯🇵 VOSTFR")
        
    # Formatage final
    title_parts = []
    if quality: title_parts.append(f"📺 {quality}")
    if extras: title_parts.append(f"🎞️ {' '.join(extras)}")
    if langs: title_parts.append(f"{' '.join(langs)}")
    
    return " | ".join(title_parts)

def replace_complete_with_episode(name, season, episode):
    """
    Remplace 'INTEGRALE' ou 'COMPLETE' dans le nom du torrent par le format SxxExx
    si une saison et un épisode sont spécifiés.
    """
    if season is None or episode is None:
        return name
    
    # Format SxxExx
    se_format = f"S{int(season):02d}E{int(episode):02d}"
    
    # Remplacer INTEGRALE et COMPLETE (insensible à la casse) par SxxExx
    # On utilise re.sub avec IGNORECASE pour remplacer toutes les variantes
    result = re.sub(r'\bINTEGRALE\b', se_format, name, flags=re.IGNORECASE)
    result = re.sub(r'\bCOMPLETE\b', se_format, result, flags=re.IGNORECASE)
    
    return result

def check_season_episode(name, target_season, target_episode):
    """
    Vérifie si le torrent correspond à la saison/épisode demandé.
    Retourne True si c'est bon (match exact ou pack saison).
    Retourne False si c'est un autre épisode/saison.
    """
    if target_season is None:
        return True
        
    name_upper = name.upper()
    
    # Extraction SxxExx
    # Regex stricte : S01E01, S1E1, 1x01
    se_pattern = re.compile(r'(?:S|SAISON|SEASON)[ ._-]?(\d{1,2})(?:[ ._-]?E(\d{1,2}))?', re.IGNORECASE)
    matches = se_pattern.findall(name_upper)
    
    # Si aucun pattern Sxx trouvé, on essaie 1x01
    if not matches:
        x_pattern = re.compile(r'(\d{1,2})x(\d{1,2})', re.IGNORECASE)
        matches = [(m[0], m[1]) for m in x_pattern.findall(name_upper)]

    # Si toujours rien, c'est peut-être un film ou un nommage exotique, on laisse passer dans le doute ?
    # Non, pour une série, si on cherche S05, il faut S05.
    if not matches:
        # Cas spécial : juste le chiffre "5" isolé ? Trop risqué.
        # On accepte si "COMPLETE" ou "INTEGRALE" est présent ?
        return True # On laisse passer par défaut pour ne pas trop filtrer

    for s, e in matches:
        try:
            season = int(s)
            episode = int(e) if e else None
            
            # Vérification Saison
            if season != target_season:
                continue # Ce n'est pas la bonne saison, on check le match suivant (ex: S01-S05)
            
            # Si bonne saison :
            # Cas 1 : Pas d'épisode dans le nom (Pack Saison) -> OK
            if episode is None:
                return True
            
            # Cas 2 : Épisode présent -> Doit matcher (ou être un range E01-E05 ?)
            # Pour l'instant match strict
            if episode == target_episode:
                return True
            else:
                # Mauvais épisode (ex: cherche E07, trouve E03)
                # Mais attention aux doubles épisodes S05E03-E04 !
                # Ma regex actuelle ne capture que le premier E.
                # Si le nom est S05E03E04, match = (5, 3). Si on veut 4, ça fail.
                # C'est une limitation acceptable pour l'instant vs afficher n'importe quoi.
                pass
                
        except ValueError:
            continue
            
    # Si on a trouvé des patterns SxxExx mais aucun ne correspond
    # (Ex: trouvé S05E03 alors qu'on veut S05E07)
    return False
