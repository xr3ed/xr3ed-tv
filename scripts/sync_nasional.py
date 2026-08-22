import os
import sys
import re

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

sys.stdout.reconfigure(encoding='utf-8')

import urllib.request

NASIONAL_SOURCE_URL = os.environ.get('NASIONAL_SOURCE_URL', os.environ.get('DECCOTECH_URL', '')).strip()
OUTPUT_M3U = os.environ.get('NASIONAL_OUTPUT', 'nasional.m3u').strip()
RAW_CACHE_FILE = os.path.join(os.path.dirname(__file__), '..', '.raw_source_cache.m3u')

def get_source_content():
    # 1. Download directly from NASIONAL_SOURCE_URL in memory
    if NASIONAL_SOURCE_URL:
        try:
            print(f"Fetching 24/7 source playlist from upstream URL...")
            req = urllib.request.Request(NASIONAL_SOURCE_URL, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
                'Accept': '*/*',
            })
            with urllib.request.urlopen(req, timeout=30) as res:
                raw_data = res.read().decode('utf-8', errors='ignore')
                print(f"Successfully fetched {len(raw_data)} bytes from upstream.")
                start_idx = raw_data.find('#EXTM3U')
                if start_idx == -1:
                    start_idx = raw_data.find('#EXTINF')
                if start_idx != -1 and len(raw_data) > 50000:
                    # Save persistent raw cache
                    try:
                        with open(RAW_CACHE_FILE, 'w', encoding='utf-8') as cf:
                            cf.write(raw_data[start_idx:])
                    except Exception:
                        pass
                    return raw_data[start_idx:]
        except Exception as e:
            print(f"Warning: Failed to fetch from NASIONAL_SOURCE_URL: {e}.")

    # 2. Fallback to raw persistent cache if present
    if os.path.exists(RAW_CACHE_FILE):
        print("Using persistent raw source cache...")
        with open(RAW_CACHE_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()

    return ""



# High Quality Canonical Logos Mapping (100% Uniform Vision+ & IndiHome Official CDN Badges)
CANONICAL_LOGOS = {

    'RCTI': 'https://www.visionplus.id/images/repository/580/580-LOGO-l.png',
    'MNC TV': 'https://www.visionplus.id/images/repository/581/581-LOGO-l.png',
    'GTV': 'https://www.visionplus.id/images/repository/582/582-LOGO-l.png',
    'iNews': 'https://www.visionplus.id/images/repository/583/583-LOGO-l.png',
    'SindoNews TV': 'https://www.visionplus.id/images/repository/584/584-LOGO-l.png',
    'SCTV': 'https://www.visionplus.id/images/repository/062/569062-LOGO-l.png',
    'Indosiar': 'https://www.visionplus.id/images/repository/066/569066-LOGO-l.png',
    'Moji': 'https://www.visionplus.id/images/repository/070/569070-LOGO-l.png',
    'Mentari TV': 'https://www.visionplus.id/images/repository/074/569074-LOGO-l.png',
    'Trans TV': 'https://www.visionplus.id/images/repository/585/585-LOGO-l.png',
    'Trans 7': 'https://www.visionplus.id/images/repository/586/586-LOGO-l.png',
    'ANTV': 'https://www.visionplus.id/images/repository/587/587-LOGO-l.png',
    'RTV': 'https://www.visionplus.id/images/repository/588/588-LOGO-l.png',
    'NET TV': 'https://www.visionplus.id/images/repository/589/589-LOGO-l.png',
    'Kompas TV': 'https://www.visionplus.id/images/repository/590/590-LOGO-l.png',
    'Metro TV': 'https://www.visionplus.id/images/repository/591/591-LOGO-l.png',
    'BTV': 'https://www.visionplus.id/images/repository/357/273357-LOGO-l.png',
    'Jak TV': 'https://www.visionplus.id/images/repository/594/594-LOGO-l.png',
    'DAAI TV': 'https://www.visionplus.id/images/repository/595/595-LOGO-l.png',
    'Bali TV': 'https://www.visionplus.id/images/repository/599/599-LOGO-l.png',
    'tvOne': 'https://images.indihometv.com/assets/88_TVONE_2025_03_17_14_49_56.png',
    'TVRI Nasional': 'https://images.indihometv.com/assets/88_TVRI_2025_03_17_14_57_26.png',
    'Nusantara TV': 'https://images.indihometv.com/assets/88_NUSANTARATV_2025_03_17_15_11_54.png',
    'Garuda TV': 'https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQ6t-MI3xuy_9qoyHhSD2nFxkLnB6xZT_EbfiwQtLKMQrIo2PTrCrfAL53n&s=10',
    'JTV': 'https://thumbor.prod.vidiocdn.com/4e5Dt4Vl_lZ8yY26m_L2jK8n3n8=/filters:strip_icc():quality(70)/vidio-web-prod-livestreaming/uploads/livestreaming/image/123/jtv-4a7b9c.png',
    'CNN Indonesia': 'https://thumbor.prod.vidiocdn.com/xOqK_67zF2R7K6R8ZlU6Xm6T2g=/filters:quality(70)/vidio-web-prod-livestreaming/uploads/livestreaming/image/6334/cnn-indonesia-724458.png',
    'CNBC Indonesia': 'https://thumbor.prod.vidiocdn.com/mZk8m8_L0Yq5n1R8ZlU6Xm6T2g=/filters:quality(70)/vidio-web-prod-livestreaming/uploads/livestreaming/image/6335/cnbc-indonesia-5b321a.png',
}

# Major National Channels Priority Sort List
MAJOR_SORT_ORDER = [
    'RCTI', 'MNC TV', 'GTV', 'iNews', 'SindoNews TV',
    'SCTV', 'Indosiar', 'Moji', 'Mentari TV',
    'Trans TV', 'Trans 7',
    'ANTV', 'tvOne',
    'Metro TV', 'Kompas TV', 'RTV', 'NET TV',
    'BTV', 'Nusantara TV', 'Garuda TV',
    'TVRI Nasional', 'TVRI Sport', 'TVRI World',
    'CNN Indonesia', 'CNBC Indonesia',
    'Jak TV', 'Jawa Pos TV', 'JTV', 'Bali TV', 'DAAI TV',
    'TV9 NU', 'TVMu'
]

# Major Sports Priority Sort List
MAJOR_SPORTS_ORDER = [
    'beIN Sports 1', 'beIN Sports 2', 'beIN Sports 3', 'beIN Sports 4', 'beIN Sports 5',
    'SPOTV', 'SPOTV 2', 'Soccer Channel', 'Sportstars', 'Sportstars 2',
    'Fight Sports', 'WWE Channel', 'MNC Sports', 'Champions TV 1', 'Champions TV 2',
    'Champions TV 3', 'Premier Sports 1', 'Premier Sports 2', 'Fubo Sports 1', 'Fubo Sports 2'
]

# Major Movies Priority Sort List
MAJOR_MOVIES_ORDER = [
    'HBO', 'HBO Hits', 'HBO Family', 'HBO Signature', 'Cinemax',
    'Hits Movies', 'Hits Now', 'tvN Movies', 'tvN', 'ONE HD',
    'Celestial Movies', 'Celestial Classic Movies', 'Zee Bioskop', 'Warner TV', 'AXN'
]

# Major Kids Priority Sort List
MAJOR_KIDS_ORDER = [
    'Animax', 'Cartoonito', 'DreamWorks', 'Moonbug', 'Zoomoo', 'Kids TV',
    'Biznet Kids', 'My Kidz', 'Baby Shark TV', 'ANIME x HIDIVE', 'Anime 24/7', 'ADN TV+'
]

def clean_title(title):
    t = title.strip()
    # Remove clutter tags
    t = re.sub(r'\s*\((?:v\+|FHD|HD|SD|OTT NAV|4K|1080p|720p|576p|480p|360p|Indonesia|Official)\)', '', t, flags=re.I)
    t = re.sub(r'\s*\[(?:Not 24/7|24/7|Geo-blocked|Checked|Live)\]', '', t, flags=re.I)
    t = re.sub(r'\s+(?:FHD|HD|SD|Digital|Plus|R\+|Official)$', '', t, flags=re.I)
    t = re.sub(r'\s{2,}', ' ', t).strip()
    return t

def normalize_national_name(raw_name):
    n = raw_name.strip()
    n = re.sub(r'\s*(HD|\(HD\)|\(FHD\)|\(OTT NAV\)|Digital|Plus|R\+|Official)\s*', ' ', n, flags=re.I)
    n = re.sub(r'[^a-zA-Z0-9\s]', '', n).strip()
    key = n.upper()
    
    aliases = {
        'RCTI': 'RCTI',
        'MNCTV': 'MNC TV',
        'MNC TV': 'MNC TV',
        'GTV': 'GTV',
        'GLOBAL TV': 'GTV',
        'INEWS': 'iNews',
        'SINDONEWS': 'SindoNews TV',
        'SINDONEWS TV': 'SindoNews TV',
        'MNC NEWS': 'SindoNews TV',
        'TRANS TV': 'Trans TV',
        'TRANSTV': 'Trans TV',
        'TRANS 7': 'Trans 7',
        'TRANS7': 'Trans 7',
        'SCTV': 'SCTV',
        'INDOSIAR': 'Indosiar',
        'ANTV': 'ANTV',
        'TVONE': 'tvOne',
        'TV ONE': 'tvOne',
        'METRO TV': 'Metro TV',
        'METROTV': 'Metro TV',
        'KOMPAS TV': 'Kompas TV',
        'KOMPASTV': 'Kompas TV',
        'RTV': 'RTV',
        'NET TV': 'NET TV',
        'NET': 'NET TV',
        'MOJI': 'Moji',
        'MOJI TV': 'Moji',
        'MENTARI TV': 'Mentari TV',
        'MENTARI': 'Mentari TV',
        'BTV': 'BTV',
        'BERITA SATU': 'BTV',
        'NUSANTARA TV': 'Nusantara TV',
        'GARUDA TV': 'Garuda TV',
        'JAWA POS TV': 'Jawa Pos TV',
        'JTV': 'JTV',
        'JAK TV': 'Jak TV',
        'JAKTV': 'Jak TV',
        'DAAI TV': 'DAAI TV',
        'BALI TV': 'Bali TV',
        'CNN INDONESIA': 'CNN Indonesia',
        'CNBC INDONESIA': 'CNBC Indonesia',
        'TVRI': 'TVRI Nasional',
        'TVRI NASIONAL': 'TVRI Nasional',
        'TVRI SPORT': 'TVRI Sport',
        'TVRI SPORTS': 'TVRI Sport',
        'TVRI WORLD': 'TVRI World',
        'TV9': 'TV9 NU',
        'TV 9': 'TV9 NU',
        'TV9 NU': 'TV9 NU',
        'TVMU': 'TVMu',
        'TV MU': 'TVMu',
        'UGTV': 'UGTV',
        'UG TV': 'UGTV',
    }
    return aliases.get(key, n.title())

def parse_m3u_robust(content):
    entries = []
    current_entry = None
    current_headers = []

    for line in content.splitlines():
        l = line.strip()
        if not l:
            continue
        
        if l.startswith('#EXTINF:'):
            grp_m = re.search(r'group-title="([^"]*)"', l)
            grp = grp_m.group(1).strip() if grp_m else 'Other'
            
            logo_m = re.search(r'tvg-logo="([^"]*)"', l)
            logo = logo_m.group(1).strip() if logo_m else ''
            
            comma_idx = l.rfind(',')
            name = l[comma_idx+1:].strip() if comma_idx != -1 else ''
            
            current_entry = {
                'grp': grp,
                'logo': logo,
                'raw_name': name,
            }
            current_headers = []
        elif l.startswith('#EXTVLCOPT:') or l.startswith('#KODIPROP:') or l.startswith('#EXTHTTP:'):
            if current_entry is not None:
                current_headers.append(l)
        elif l.startswith('http://') or l.startswith('https://'):
            if current_entry is not None:
                current_entry['headers'] = list(current_headers)
                current_entry['url'] = l
                entries.append(current_entry)
                current_entry = None
                current_headers = []
    
    return entries

def generate_consolidated_playlist():
    content = get_source_content()
    if not content:
        print("Error: No source content available for national channels.")
        return False

    entries = parse_m3u_robust(content)
    print(f"Parsed {len(entries)} total entries from source.")

    # Category Mapping definitions
    # 1. 🇮🇩 NASIONAL
    national_raw = [e for e in entries if e['grp'] in ['🇮🇩 NASIONAL 1', '🇮🇩 NASIONAL 2', '🇮🇩 NASIONAL 3', '🇮🇩 NASIONAL 4']]
    
    # 2. SPORTS
    sports_raw = [e for e in entries if e['grp'] == 'SPORTS']

    
    # 3-8. Leagues & Automotif
    champions_raw = [e for e in entries if e['grp'] == 'LIGA CHAMPION🏆']
    inggris_raw = [e for e in entries if e['grp'] == 'LIGA INGGRIS']
    spanyol_raw = [e for e in entries if e['grp'] == 'LIGA SPANYOL']
    italia_raw = [e for e in entries if e['grp'] == 'LIGA ITALIA']
    jerman_raw = [e for e in entries if e['grp'] == 'LIGA JERMAN']
    otomotif_raw = [e for e in entries if e['grp'] == '🚗 automotif']
    
    # 9-12. Entertainment & Knowledge
    movies_raw = [e for e in entries if e['grp'] == 'MOVIES' or ('celestial' in e['raw_name'].lower())]
    kids_raw = [e for e in entries if e['grp'] == '👫 KIDS CARTOON']
    anim_raw = [e for e in entries if e['grp'] == 'Animation']
    doc_raw = [e for e in entries if e['grp'] == 'Documentary']
    news_raw = [e for e in entries if e['grp'] == '🛰 NEWS']
    
    # 13-14. Religi
    islam_raw = [e for e in entries if e['grp'] == '☪️ Islam']
    kristen_raw = [e for e in entries if e['grp'] == '✝️​ Kristen']
    
    # 15-17. Regional
    malaysia_raw = [e for e in entries if e['grp'] == 'Malaysia']
    korea_raw = [e for e in entries if e['grp'] == 'Korean Channels' or ('k-pop' in e['raw_name'].lower())]
    china_raw = [e for e in entries if e['grp'] == 'China' and 'celestial' not in e['raw_name'].lower()]
    
    # 18. Music
    music_raw = [e for e in entries if e['grp'] == 'Music']

    # Dedicated Channel Badges (Individual Channel Posters)
    CHANNEL_LOGOS = {
        # UCL Channels
        'Arena Premium 1': 'https://raw.githubusercontent.com/mimipipi22/logo/refs/heads/main/png/arena-sport-premium-1.png',
        'Arena Premium 2': 'https://raw.githubusercontent.com/mimipipi22/logo/refs/heads/main/png/arena-sport-premium-2.png',
        'Arena Premium 3': 'https://raw.githubusercontent.com/mimipipi22/logo/refs/heads/main/png/arena-sport-premium-3.png',
        'DIGI SPORT 1': 'https://www.unblockitall.com/wp-content/uploads/2018/07/digi-sport.jpg',
        'DIGI SPORT 2': 'https://www.unblockitall.com/wp-content/uploads/2018/07/digi-sport.jpg',
        'DIGI SPORT 3': 'https://www.unblockitall.com/wp-content/uploads/2018/07/digi-sport.jpg',
        'DIGI SPORT 4': 'https://www.unblockitall.com/wp-content/uploads/2018/07/digi-sport.jpg',
        'Prima Sport 1': 'https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQUtY8Rc2n6SO5ac7An15amazpi-zbuVUz31g&s',
        'Prima Sport 2': 'https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQUtY8Rc2n6SO5ac7An15amazpi-zbuVUz31g&s',
        'Prima Sport 3': 'https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQUtY8Rc2n6SO5ac7An15amazpi-zbuVUz31g&s',
        'Prima Sport 4': 'https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQUtY8Rc2n6SO5ac7An15amazpi-zbuVUz31g&s',
        'Prima Sport 5': 'https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQUtY8Rc2n6SO5ac7An15amazpi-zbuVUz31g&s',
        
        # EPL Channels
        'FUBO SPORTS 1': 'https://i.ibb.co.com/7Md2qy9/fubosp.png',
        'FUBO SPORTS 2': 'https://i.ibb.co.com/7Md2qy9/fubosp.png',
        
        # Serie A / Bundesliga Channels
        'CAZE TV 1': 'https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTpFVJGATy70KVBZ0txjIVDSVXTQUCSykt_5A&s',
        'BUNDESLIGA 2': 'https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTT3YgKhAMGlkn_9DFUR74KdIPl4oi-qpXTaiLrOa_630grs2jqRjkRd9BI&s=10',
        'SLOVAKIA: SPORT 1': 'https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRqZgyuL2ZXIz_UUHIe4qmLxQavlz7_wx-CTQ&s',
        
        # Korean Channels
        'tvN': 'https://www.visionplus.id/images/repository/614/614-LOGO-l.png',
        'tvN Movies': 'https://www.mncvision.id/userfiles/image/channel/channel_25.png',
        'ONE HD': 'https://www.visionplus.id/images/repository/675/675-LOGO-l.png',
        'Arirang': 'https://images.indihometv.com/assets/88_ARIRANG_2025_03_17_14_45_16.png',
        'K-POP': 'https://i.imgur.com/mMbntB5.png',
    }

    output_lines = [
        '#EXTM3U url-tvg="https://raw.githubusercontent.com/apistech/project/refs/heads/main/epgs/guide.xml"',
        '// ========================================================================',
        '// XR3ED TV - MASTER CHANNELS PLAYLIST',
        '// Cleaned, Consolidated Multi-Server & Uniform Badges',
        '// ========================================================================'
    ]

    total_streams = 0

    # Helper function to group and write channels with multi-server support
    def write_category_multi_server(cat_display_name, raw_items, priority_sort_list=None):
        nonlocal total_streams
        grouped = {}
        fallback_logos = {}
        
        for item in raw_items:
            ctitle = clean_title(item['raw_name'])
            # Normalize variations
            if re.match(r'^bein\s*sport[s]?\s*(\d+)$', ctitle, re.I):
                m = re.match(r'^bein\s*sport[s]?\s*(\d+)$', ctitle, re.I)
                ctitle = f"beIN Sports {m.group(1)}"
            elif re.match(r'^spotv\s*(\d*)$', ctitle, re.I):
                m = re.match(r'^spotv\s*(\d*)$', ctitle, re.I)
                num = m.group(1).strip()
                ctitle = f"SPOTV {num}".strip()
            elif re.match(r'^hbo\s*hits\s*(\d*)$', ctitle, re.I):
                ctitle = "HBO Hits"
            elif ctitle.lower() in ['tvn', 'tvn (v+)']:
                ctitle = 'tvN'
            elif ctitle.lower() in ['tvn movies', 'tvn movies hd', 'tvn movies hd (v+)']:
                ctitle = 'tvN Movies'
            elif ctitle.lower() in ['one', 'one (v+)', 'one hd']:
                ctitle = 'ONE HD'
            elif ctitle.lower() in ['arirang', 'arirang (v+)']:
                ctitle = 'Arirang'

            if item.get('logo') and ctitle not in fallback_logos:
                fallback_logos[ctitle] = item['logo']

            grouped.setdefault(ctitle, []).append(item)

        # Sort channels
        def sort_key(cname):
            if priority_sort_list:
                for idx, p in enumerate(priority_sort_list):
                    if p.lower() == cname.lower() or cname.lower().startswith(p.lower()):
                        return (0, idx)
            return (1, cname.lower())

        sorted_cnames = sorted(grouped.keys(), key=sort_key)

        for cname in sorted_cnames:
            items = grouped[cname]
            # Deduplicate by URL
            seen_urls = set()
            unique_items = []
            for it in items:
                u = it['url'].strip()
                if u not in seen_urls:
                    seen_urls.add(u)
                    unique_items.append(it)

            # Determine best channel logo
            logo = CHANNEL_LOGOS.get(cname, fallback_logos.get(cname, unique_items[0].get('logo', '')))

            if len(unique_items) == 1:
                it = unique_items[0]
                extinf = f'#EXTINF:-1 tvg-id="{cname}" tvg-name="{cname}" tvg-logo="{logo}" group-title="{cat_display_name}",{cname}'
                output_lines.append(extinf)
                for h in it['headers']:
                    output_lines.append(h)
                output_lines.append(it['url'])
                total_streams += 1
            else:
                for idx, it in enumerate(unique_items, start=1):
                    server_title = f"{cname} - Server {idx}"
                    extinf = f'#EXTINF:-1 tvg-id="{cname}" tvg-name="{server_title}" tvg-logo="{logo}" group-title="{cat_display_name}",{server_title}'
                    output_lines.append(extinf)
                    for h in it['headers']:
                        output_lines.append(h)
                    output_lines.append(it['url'])
                    total_streams += 1

    # --- 1. 🇮🇩 NASIONAL (Custom Merged 4 -> 3 -> 2 -> 1) ---
    def write_national_category():
        nonlocal total_streams
        national_channel_groups = {}
        fallback_logos = {}

        for item in national_raw:
            cname = normalize_national_name(item['raw_name'])
            grp = item['grp']
            url = item['url']
            headers_lines = item['headers']
            
            if item.get('logo') and cname not in fallback_logos:
                fallback_logos[cname] = item['logo']

            national_channel_groups.setdefault(cname, {}).setdefault(grp, []).append({
                'headers': headers_lines,
                'url': url
            })

        def nat_sort_key(cname):
            if cname in MAJOR_SORT_ORDER:
                return (0, MAJOR_SORT_ORDER.index(cname))
            return (1, cname)

        sorted_nat_channels = sorted(national_channel_groups.keys(), key=nat_sort_key)

        for cname in sorted_nat_channels:
            sources_by_grp = national_channel_groups[cname]
            logo = CANONICAL_LOGOS.get(cname, fallback_logos.get(cname, ''))
            
            ordered_streams = []
            seen_urls = set()
            for target_grp in ['🇮🇩 NASIONAL 4', '🇮🇩 NASIONAL 3', '🇮🇩 NASIONAL 2', '🇮🇩 NASIONAL 1']:
                if target_grp in sources_by_grp:
                    for item in sources_by_grp[target_grp]:
                        u = item['url'].strip()
                        if u not in seen_urls:
                            seen_urls.add(u)
                            ordered_streams.append((target_grp, item))

            if not ordered_streams:
                continue

            for idx, (grp, item) in enumerate(ordered_streams, start=1):
                server_title = f"{cname} - Server {idx}"
                extinf = f'#EXTINF:-1 tvg-id="{cname}" tvg-name="{server_title}" tvg-logo="{logo}" group-title="🇮🇩 NASIONAL",{server_title}'
                output_lines.append(extinf)
                for h in item['headers']:
                    output_lines.append(h)
                output_lines.append(item['url'])
                total_streams += 1

    # --- 0. 📢 INFO (Telegram & Coffee) ---
    def write_info_category():
        nonlocal total_streams
        tg_logo = "https://raw.githubusercontent.com/xr3ed/xr3ed-tv/main/assets/telegram.png"
        coffee_logo = "https://raw.githubusercontent.com/xr3ed/xr3ed-tv/main/assets/coffee.png"
        
        output_lines.append(f'#EXTINF:-1 tvg-id="xr3ed-telegram" tvg-name="📢 Gabung Telegram: t.me/CloudstreamXR" tvg-logo="{tg_logo}" group-title="📢 INFO",📢 Gabung Telegram: t.me/CloudstreamXR')
        output_lines.append("https://t.me/CloudstreamXR")
        
        output_lines.append(f'#EXTINF:-1 tvg-id="xr3ed-coffee" tvg-name="☕ Traktir Kopi: lynk.id/xr3ed" tvg-logo="{coffee_logo}" group-title="📢 INFO",☕ Traktir Kopi: lynk.id/xr3ed')
        output_lines.append("https://lynk.id/xr3ed")
        total_streams += 2

    # --- EXECUTE IN CATEGORY ORDER WITH TEXT EMOJIS ONLY (NO BADGES) ---
    print("Writing 0. 📢 INFO...")
    write_info_category()

    print("Writing 1. 🇮🇩 NASIONAL...")
    write_national_category()

    print("Writing 2. ⚽ SPORTS...")
    write_category_multi_server('⚽ SPORTS', sports_raw, MAJOR_SPORTS_ORDER)

    print("Writing 3. 🏆 LIGA CHAMPION...")
    write_category_multi_server('🏆 LIGA CHAMPION', champions_raw)

    print("Writing 4. ⚽ LIGA INGGRIS...")
    write_category_multi_server('⚽ LIGA INGGRIS', inggris_raw)

    print("Writing 5. ⚽ LIGA SPANYOL...")
    write_category_multi_server('⚽ LIGA SPANYOL', spanyol_raw)

    print("Writing 6. ⚽ LIGA ITALIA...")
    write_category_multi_server('⚽ LIGA ITALIA', italia_raw)

    print("Writing 7. ⚽ LIGA JERMAN...")
    write_category_multi_server('⚽ LIGA JERMAN', jerman_raw)

    print("Writing 8. 🏎️ OTOMOTIF...")
    write_category_multi_server('🏎️ OTOMOTIF', otomotif_raw)

    print("Writing 9. 🎬 MOVIES & ENTERTAINMENT...")
    write_category_multi_server('🎬 MOVIES & ENTERTAINMENT', movies_raw, MAJOR_MOVIES_ORDER)

    print("Writing 10. 👫 KIDS & ANIME...")
    write_category_multi_server('👫 KIDS & ANIME', kids_raw, MAJOR_KIDS_ORDER)

    print("Writing 11. 📚 DOCUMENTARY & KNOWLEDGE...")
    write_category_multi_server('📚 DOCUMENTARY & KNOWLEDGE', doc_raw)

    print("Writing 12. 🛰 NEWS & BUSINESS...")
    write_category_multi_server('🛰 NEWS & BUSINESS', news_raw)

    print("Writing 13. ☪️ ISLAM...")
    write_category_multi_server('☪️ ISLAM', islam_raw)

    print("Writing 14. ✝️ KRISTEN...")
    write_category_multi_server('✝️ KRISTEN', kristen_raw)

    print("Writing 15. 🇲🇾 MALAYSIA...")
    write_category_multi_server('🇲🇾 MALAYSIA', malaysia_raw)

    print("Writing 16. 🇰🇷 KOREA...")
    write_category_multi_server('🇰🇷 KOREA', korea_raw)

    print("Writing 17. 🇨🇳 CHINA...")
    write_category_multi_server('🇨🇳 CHINA', china_raw)

    print("Writing 18. 🎵 MUSIC...")
    write_category_multi_server('🎵 MUSIC', music_raw)

    if total_streams < 100 and os.path.exists(OUTPUT_M3U):
        print(f"Warning: Only {total_streams} streams parsed. Keeping existing {OUTPUT_M3U} to prevent data loss.")
        return True

    script_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(script_dir) == 'scripts':
        out_path = os.path.join(script_dir, '..', OUTPUT_M3U)
    else:
        out_path = os.path.join(script_dir, OUTPUT_M3U)
    out_path = os.path.normpath(out_path)

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(output_lines) + '\n')

    print(f"\nGenerated {out_path} successfully!")
    print(f"Total Channels/Streams: {total_streams}")
    return True



if __name__ == '__main__':
    generate_consolidated_playlist()


