import os
import json
import base64
import hashlib
import time
import re
import urllib.parse
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    AESGCM = None

try:
    from dotenv import load_dotenv
    load_dotenv(override=True, interpolate=False)
except ImportError:
    pass

API_BASE = os.environ.get('XR3EDTV_API_BASE', '').rstrip('/')
XOR_KEY = os.environ.get('XR3EDTV_XOR_KEY', '')
SALT_KEY = os.environ.get('XR3EDTV_SALT_KEY', '')
ONDEMAND_API = os.environ.get('XR3EDTV_ONDEMAND_API', '').strip()
ONDEMAND_EXTRACT = os.environ.get('XR3EDTV_ONDEMAND_EXTRACT', '').strip()
ONDEMAND_REFERER = os.environ.get('XR3EDTV_ONDEMAND_REFERER', '').strip()
DEFAULT_REFERER = os.environ.get('XR3EDTV_REFERER', '')
OUTPUT_FILE = os.environ.get('XR3EDTV_OUTPUT', 'xr3dtv.m3u8')
WORKER_BASE = os.environ.get('WORKER_BASE_URL', 'https://stream-cdn-box.xr3ed-edge.workers.dev').rstrip('/')
WORKER_AUTH_KEY = os.environ.get('WORKER_AUTH_KEY', '')

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

# WIB Timezone (UTC+7)
WIB = timezone(timedelta(hours=7))

# Sport Categories Configuration (Exact mapping matching website testa.js)
SPORT_CATEGORY_CONFIG = {
    'badminton': '🏸 Badminton',
    'soccer': '⚽ Soccer',
    'football': '⚽ Soccer',
    'basketball': '🏀 Basketball',
    'motorsport': '🏎️ Motorsport',
    'motor-sports': '🏎️ Motorsport',
    'racing': '🏎️ Motorsport',
    'tennis': '🎾 Tennis',
    'table_tennis': '🏓 Table Tennis',
    'table tennis': '🏓 Table Tennis',
    'combat': '🥊 Combat Sports',
    'ufc': '🥊 Combat Sports',
    'mma': '🥊 Combat Sports',
    'boxing': '🥊 Combat Sports',
    'baseball': '⚾ Baseball',
    'billiards': '🎱 Billiards',
    'billiard': '🎱 Billiards',
    'cricket': '🏏 Cricket',
    'golf': '⛳ Golf',
    'volleyball': '🏐 Volleyball',
    'hockey': '🏒 Hockey',
    '24/7-streams': '📺 24/7 Streams'
}

GROUP_LIVE_EVENT = "🔴 Live Event"
GROUP_HOT_EVENT = "🔥 Hot Event"
GROUP_UPCOMING_EVENT = "⏳ Upcoming Event"

SPORT_ORDER = [
    '🏸 Badminton',
    '⚽ Soccer',
    '🏀 Basketball',
    '🏎️ Motorsport',
    '🎾 Tennis',
    '🏓 Table Tennis',
    '🥊 Combat Sports',
    '⚾ Baseball',
    '🎱 Billiards',
    '🏏 Cricket',
    '⛳ Golf',
    '🏐 Volleyball',
    '🏒 Hockey',
    '📺 24/7 Streams'
]

GENERIC_PLACEHOLDERS = {'table tennis', 'tennis', 'soccer', 'football', 'basketball', 'baseball', 'billiards', 'badminton', 'volleyball'}

def clean_league_name(league_str):
    if not league_str:
        return "Sports"
    clean = league_str.replace('|', '-')
    clean = re.sub(r'[^\x00-\x7F]+', '', clean).strip()
    clean = re.sub(r'\s+', ' ', clean)
    if clean.islower():
        clean = clean.title()
    return clean or "Sports"

def clean_title_str(s):
    s = re.sub(r'[^\x00-\x7F]+', '', s or '').replace('|', '-').strip()
    return re.sub(r'\s+', ' ', s) or 'Sports'

def fetch_url(url, referer=None):
    headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    if referer:
        headers['Referer'] = referer
        headers['Origin'] = referer.rstrip('/')
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=25) as res:
        return res.read()

def xor_decrypt(encrypted_b64, key_str):
    raw_data = base64.b64decode(encrypted_b64.strip())
    key_bytes = key_str.encode('utf-8')
    key_len = len(key_bytes)
    decrypted = bytearray(len(raw_data))
    for i in range(len(raw_data)):
        decrypted[i] = raw_data[i] ^ key_bytes[i % key_len]
    return json.loads(decrypted.decode('utf-8'))

def get_event_hidden_id(uuid_str, salt):
    parts = uuid_str.split('-')
    if len(parts) < 5:
        return ""
    s1 = salt[:7]
    s2 = salt[12:20]
    raw = parts[2] + s1 + parts[4] + s2 + parts[0]
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]

def encrypt_match_id(match_id: str, secret: str) -> str:
    if not AESGCM or not secret:
        return base64.urlsafe_b64encode(match_id.encode('utf-8')).decode('utf-8').rstrip('=')
    key = hashlib.sha256(secret.encode('utf-8')).digest()
    aesgcm = AESGCM(key)
    iv = os.urandom(12)
    encrypted_with_tag = aesgcm.encrypt(iv, match_id.encode('utf-8'), None)
    combined = iv + encrypted_with_tag
    return base64.urlsafe_b64encode(combined).decode('utf-8').rstrip('=')

def parse_icon_category(icon_url):
    if not icon_url:
        return 'other_sports', False
    clean = icon_url.split('?')[0].split('/')[-1]
    name = clean.replace('.png', '').replace('.jpg', '').replace('.webp', '')
    lower = name.lower()
    is_main = False
    cat = name

    if lower.startswith('main_') or lower.startswith('main-'):
        is_main = True
        cat = name[5:]
    elif lower.endswith('_main'):
        is_main = True
        cat = name[:-5]

    clean_key = cat.lower().replace('-', '_').strip()
    return clean_key, is_main

def get_sport_group(clean_key):
    if clean_key in SPORT_CATEGORY_CONFIG:
        return SPORT_CATEGORY_CONFIG[clean_key]
    title_name = clean_key.replace('_', ' ').title()
    return f"🏆 {title_name}" if title_name else "🏆 Other Sports"

def get_stream_referer(url):
    """Returns exact referer only if required. Avoids 403 blocks from hostile CDNs."""
    lower = url.lower()
    if 'vivo200.com' in lower or 'online909.com' in lower:
        return 'https://player.online909.com/'
    elif 'dens.tv' in lower:
        return 'https://www.dens.tv/'
    elif 'detik.com' in lower:
        return 'https://video.detik.com/'
    elif 'rctiplus' in lower:
        return 'https://www.rctiplus.com/'
    elif 'starzplayarabia' in lower:
        return 'https://starzplay.com/'
    elif 'stream-cdn-box' in lower or 'damitv' in lower or 'messi.damitv' in lower:
        return 'https://damitv.st/'
    elif 'elutuna.workers.dev' in lower or 'resolve-web' in lower:
        return 'https://playerkltratv.pages.dev/'
    return None

def check_match_status(match_date, match_time, duration=3.5):
    """Calculates live/upcoming/ended status matching exact website logic within 24h."""
    if not match_date or not match_time:
        return "SCHEDULED", "", 0
    try:
        dt_str = f"{match_date.strip()} {match_time.strip()}"
        match_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M").replace(tzinfo=WIB)
        now_wib = datetime.now(WIB)

        dur_hours = float(duration) if duration else 3.5
        end_dt = match_dt + timedelta(hours=dur_hours)
        match_ts = int(match_dt.timestamp())

        if match_dt > now_wib + timedelta(hours=24):
            return "OUT_OF_WINDOW", "", match_ts

        if match_dt <= now_wib < end_dt:
            return "LIVE", f"• LIVE {match_time}", match_ts
        elif now_wib < match_dt:
            return "UPCOMING", f"• {match_time} WIB", match_ts
        else:
            return "ENDED", f"• Ended", match_ts
    except Exception:
        return "SCHEDULED", f"• {match_time} WIB" if match_time else "", 0

def get_base_server_type(raw_label):
    if not raw_label or not raw_label.strip():
        return "SD"
    upper = raw_label.upper()
    if 'COURT' in upper:
        clean = raw_label.replace('[', '').replace(']', '').replace('(', '').replace(')', '').strip()
        return clean
    elif 'SD' in upper and 'Y' in upper:
        return "SD Yalla"
    elif 'SD' in upper and 'V' in upper:
        return "SD Vivo"
    elif 'AUTO' in upper:
        return "HD"
    elif 'DAMI' in upper or ('HD' in upper and 'IOS' in upper):
        return "HD Damiya"
    elif 'HD' in upper:
        return "HD"
    elif 'SD' in upper:
        return "SD"
    else:
        clean = raw_label.replace('[', '').replace(']', '').replace('(', '').replace(')', '').strip()
        return clean or "Stream"

def resolve_vivo_redirect(url):
    """Resolves livevent.elutuna.workers.dev/resolve-web/vivo200 302 redirect to direct m3u8 stream."""
    if 'resolve-web' not in url and 'livevent.elutuna.workers.dev' not in url:
        return url
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    headers = {'User-Agent': USER_AGENT, 'Referer': 'https://playerkltratv.pages.dev/'}
    req = urllib.request.Request(url, headers=headers)
    try:
        loc = None
        try:
            res = opener.open(req, timeout=4)
            loc = res.headers.get('Location')
        except urllib.error.HTTPError as e:
            loc = e.headers.get('Location')
        if loc:
            parsed_loc = urllib.parse.urlparse(loc)
            qs_loc = urllib.parse.parse_qs(parsed_loc.query)
            if 'liveUrl' in qs_loc and qs_loc['liveUrl'][0]:
                return qs_loc['liveUrl'][0]
            elif loc.startswith('http') and ('.m3u8' in loc or '.mpd' in loc or 'vivo200.com' in loc):
                return loc
    except Exception:
        pass
    return url

def fetch_ondemand_streams():
    """Fetches live/upcoming matches from messi.damitv.st/papi/matches/all.
    Returns flat list — same schema as ondemand.st/papi/matches/all."""
    if not ONDEMAND_API:
        return []
    try:
        raw = fetch_url(ONDEMAND_API, referer=ONDEMAND_REFERER)
        data = json.loads(raw.decode('utf-8'))
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"Ondemand streams fetch exception: {e}")
        return []

def _norm(s):
    """Normalize team name for fuzzy comparison."""
    s = (s or '').lower().strip()
    s = re.sub(r'[^\w\s]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    # Common abbreviation expansions
    s = s.replace(' fc', '').replace(' cf', '').replace(' sc', '')
    s = s.replace(' utd', ' united').replace(' city', '').strip()
    return s

def _name_tokens(s):
    return set(_norm(s).split())

def fuzzy_match_od(t1_primary, t2_primary, od_list, time_ms_primary=None):
    """Find best OD match for a primary event pair (t1 vs t2).
    Uses token-overlap: both team names must have significant word overlap.
    Optional time_ms_primary (unix ms) to restrict to ±5h window.
    Returns matched OD entry or None."""
    tok1 = _name_tokens(t1_primary)
    tok2 = _name_tokens(t2_primary)
    if not tok1 or not tok2:
        return None
    # Remove very short/common tokens
    tok1 = {t for t in tok1 if len(t) > 2}
    tok2 = {t for t in tok2 if len(t) > 2}
    if not tok1 or not tok2:
        return None

    best = None
    best_score = 0

    for m in od_list:
        teams = m.get('teams') or {}
        ot1 = (teams.get('home') or {}).get('name', '')
        ot2 = (teams.get('away') or {}).get('name', '')
        if not ot1 or not ot2:
            continue

        otok1 = {t for t in _name_tokens(ot1) if len(t) > 2}
        otok2 = {t for t in _name_tokens(ot2) if len(t) > 2}
        if not otok1 or not otok2:
            continue

        # Score: sum of intersection / union for both pairs
        def overlap(a, b):
            inter = len(a & b)
            if not inter:
                return 0.0
            return inter / min(len(a), len(b))  # recall-based

        # Try both home/away orderings
        s_normal = (overlap(tok1, otok1) + overlap(tok2, otok2)) / 2
        s_flipped = (overlap(tok1, otok2) + overlap(tok2, otok1)) / 2
        score = max(s_normal, s_flipped)

        if score < 0.6:
            continue

        # Optional time check ±5h
        if time_ms_primary:
            od_date = m.get('date', 0) or 0
            if od_date and abs(od_date - time_ms_primary) > 5 * 3600 * 1000:
                continue

        if score > best_score:
            best_score = score
            best = m

    return best

def generate_playlist():
    ts = int(time.time() * 1000)
    channels_data = {}
    events_data = []
    players_data = []

    # 1. Fetch Primary API Data
    if API_BASE and XOR_KEY and SALT_KEY:
        print("Fetching primary API channel & event definitions...")
        try:
            raw_channels = fetch_url(f"{API_BASE}/vip/channels.json?v={ts}")
            channels_data = xor_decrypt(raw_channels.decode('utf-8'), XOR_KEY)
            print(f"Loaded {len(channels_data)} channel references.")
        except Exception as e:
            print(f"Channels decode exception: {e}")

        try:
            events_raw = fetch_url(f"{API_BASE}/vip/eventweb.json?v={ts}")
            events_data = json.loads(events_raw.decode('utf-8'))
            print(f"Loaded {len(events_data)} primary events.")
        except Exception as e:
            print(f"Events parse exception: {e}")

        try:
            players_raw = fetch_url(f"{API_BASE}/vip/sdplayer.json?v={ts}")
            players_data = json.loads(players_raw.decode('utf-8'))
            print(f"Loaded {len(players_data)} player definitions.")
        except Exception as e:
            print(f"Players parse exception: {e}")

    # 2. Fetch OnDemand Streams (messi.damitv.st — supports all sports IDs)
    print("Fetching OnDemand streams...")
    ondemand_matches = fetch_ondemand_streams()
    print(f"Loaded {len(ondemand_matches)} OnDemand stream entries.")

    # All entries from streams API are valid — messi.damitv.st/papi/extract-url handles them all
    valid_ondemand = [m for m in ondemand_matches if m.get('id')]

    ondemand_handled_ids = set()
    # valid_ondemand list used for fuzzy lookup at primary event time

    player_map = {item['id']: item.get('servers', []) for item in players_data if 'id' in item}

    # Resolve Vivo URLs in parallel
    vivo_url_map = {}
    vivo_urls_to_resolve = set()
    for item in players_data:
        for s in item.get('servers', []):
            u = s.get('url', '')
            if 'resolve-web' in u or 'livevent.elutuna.workers.dev' in u:
                vivo_urls_to_resolve.add(u)

    if vivo_urls_to_resolve:
        print(f"Resolving {len(vivo_urls_to_resolve)} Vivo web-player streams to direct HLS...")
        with ThreadPoolExecutor(max_workers=12) as executor:
            future_to_url = {executor.submit(resolve_vivo_redirect, u): u for u in vivo_urls_to_resolve}
            for future in future_to_url:
                orig_u = future_to_url[future]
                try:
                    vivo_url_map[orig_u] = future.result()
                except Exception:
                    vivo_url_map[orig_u] = orig_u

    hot_entries = []
    live_event_entries = []
    upcoming_dict = {}
    total_servers = 0

    # 3. Process Primary Events (EVERY match in eventweb.json is processed)
    for ev in events_data:
        ev_id = ev.get('id', '')
        hidden_id = get_event_hidden_id(ev_id, SALT_KEY)
        servers = player_map.get(hidden_id, [])

        active_servers = [s for s in servers if s.get('url')]
        if not active_servers:
            continue

        league = clean_league_name((ev.get('league') or 'Sports Event').strip())
        t1 = (ev.get('team1', {}).get('name') or '').strip()
        t2 = (ev.get('team2', {}).get('name') or '').strip()

        is_t1_placeholder = t1.lower() in GENERIC_PLACEHOLDERS
        is_t2_placeholder = t2.lower() in GENERIC_PLACEHOLDERS
        is_identical = t1.lower() == t2.lower()

        # Fuzzy match OD entry to primary event
        m_date_str = ev.get('match_date') or ev.get('kickoff_date') or ''
        m_time_str = ev.get('match_time') or ev.get('kickoff_time') or ''
        prim_time_ms = None
        try:
            if m_date_str and m_time_str:
                from datetime import datetime as _dt
                prim_dt = _dt.strptime(f"{m_date_str} {m_time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=WIB)
                prim_time_ms = int(prim_dt.timestamp() * 1000)
        except Exception:
            pass

        matched_od = fuzzy_match_od(t1, t2, valid_ondemand, prim_time_ms) if (t1 and t2) else None

        if matched_od:
            ondemand_handled_ids.add(matched_od.get('id'))
            od_badge = (matched_od.get('teams') or {}).get('home', {}).get('badge') or matched_od.get('poster') or ''
            channels = [ch.get('name') for ch in matched_od.get('tvChannels', []) if ch.get('name')]
            unique_tv = list(dict.fromkeys(channels))
            od_tv = f" [{' | '.join(unique_tv[:3])}]" if unique_tv else ""
        else:
            od_badge = ""
            od_tv = ""

        if t1 and t2 and not is_identical and not is_t1_placeholder and not is_t2_placeholder:
            match_title = f"[{league}] {t1} vs {t2}{od_tv}"
        elif t1 and not is_t1_placeholder and t1.lower() != league.lower():
            match_title = f"[{league}] {t1}{od_tv}"
        else:
            match_title = f"[{league}]{od_tv}"

        logo = (
            od_badge or
            ev.get('team1', {}).get('logo') or
            ev.get('team2', {}).get('logo') or
            ev.get('icon') or
            ""
        ).strip()

        clean_key, is_main = parse_icon_category(ev.get('icon', ''))
        sport_group = get_sport_group(clean_key)

        m_date = ev.get('match_date') or ev.get('kickoff_date') or ""
        m_time = ev.get('match_time') or ev.get('kickoff_time') or ""
        duration = ev.get('duration', 3.5)

        status_type, status_suffix, match_ts = check_match_status(m_date, m_time, duration)

        if status_type in ("ENDED", "OUT_OF_WINDOW"):
            continue
        seen_match_urls = set()
        server_list = []

        # Optional worker stream
        if matched_od and WORKER_AUTH_KEY:
            m_od_id = matched_od.get('id')
            if m_od_id:
                enc_id = encrypt_match_id(m_od_id, WORKER_AUTH_KEY)
                worker_stream = f"{WORKER_BASE}/live/{enc_id}.m3u8"
                seen_match_urls.add(worker_stream)
                server_list.append((
                    "Server 1 (Worker HLS)",
                    worker_stream,
                    'https://damitv.st/',
                    None
                ))

        # Add servers from Primary API (Kltra) with exact de-duplication
        for s_obj in active_servers:
            raw_label = s_obj.get('label', '')
            base_type = get_base_server_type(raw_label)
            s_url = s_obj.get('url', '').strip()

            if s_url in vivo_url_map:
                s_url = vivo_url_map[s_url]

            if not s_url or s_url.startswith('javascript:'):
                continue

            final_stream_url = s_url
            clearkey_str = None

            parsed = urllib.parse.urlparse(s_url)
            qs = urllib.parse.parse_qs(parsed.query)
            if 'channel' in qs and qs['channel'][0] in channels_data:
                ch_target = channels_data[qs['channel'][0]]
                final_stream_url = ch_target.get('url', s_url)
                if 'drm' in ch_target and ch_target['drm']:
                    drm_dict = ch_target['drm']
                    k_id = list(drm_dict.keys())[0]
                    clearkey_str = f"{k_id}:{drm_dict[k_id]}"
            elif 'src' in qs:
                final_stream_url = qs['src'][0]
                if 'ck' in qs:
                    clearkey_str = qs['ck'][0]

            # Ignore exact identical streams
            if final_stream_url in seen_match_urls:
                continue
            seen_match_urls.add(final_stream_url)

            srv_idx = len(server_list) + 1
            if 'COURT' in base_type.upper():
                srv_label = base_type
            else:
                srv_label = f"Server {srv_idx} ({base_type})"

            ref = get_stream_referer(final_stream_url)
            server_list.append((srv_label, final_stream_url, ref, clearkey_str))

        if not server_list:
            continue

        # Build entries for each server
        for srv_label, stream_url, ref, clearkey_str in server_list:
            if status_type == "UPCOMING":
                full_display_title = f"[UPCOMING] {match_title} - {srv_label} {status_suffix}".strip()
            elif status_suffix:
                full_display_title = f"{match_title} - {srv_label} {status_suffix}".strip()
            else:
                full_display_title = f"{match_title} - {srv_label}".strip()

            def build_entry(grp_title, _title=full_display_title, _url=stream_url, _ref=ref, _ck=clearkey_str):
                item = []
                extinf = f'#EXTINF:-1 tvg-id="" tvg-name="{_title}" tvg-logo="{logo}" group-title="{grp_title}",{_title}'
                item.append(extinf)
                if _ref:
                    item.append(f'#EXTVLCOPT:http-referrer={_ref}')
                item.append(f'#EXTVLCOPT:http-user-agent={USER_AGENT}')
                if _ck:
                    item.append('#KODIPROP:inputstream.adaptive.license_type=clearkey')
                    item.append(f'#KODIPROP:inputstream.adaptive.license_key={_ck}')
                item.append(_url)
                return item

            # 1. Hot Event (Matches with Main_ icon)
            if is_main and status_type == "LIVE":
                hot_entries.extend(build_entry(GROUP_HOT_EVENT))

            # 2. Live Event (Ongoing live matches)
            if status_type == "LIVE":
                live_event_entries.append((match_ts, build_entry(GROUP_LIVE_EVENT)))

            # 3. Upcoming Event (Collected for top 10 upcoming list)
            if status_type == "UPCOMING":
                if ev_id not in upcoming_dict:
                    upcoming_dict[ev_id] = (match_ts, [])
                upcoming_dict[ev_id][1].extend(build_entry(GROUP_UPCOMING_EVENT))

            total_servers += 1

    # 4. Process Standalone Valid OnDemand Matches with ALL available servers
    if WORKER_AUTH_KEY:
        now_wib = datetime.now(WIB)
        for m in valid_ondemand:
            mid = m.get('id', '')
            if not mid or mid in ondemand_handled_ids:
                continue

            cat_raw = (m.get('_category') or m.get('category') or '').lower().strip()
            league = clean_league_name(m.get('league') or cat_raw.replace('-', ' ').title() or 'Sports')
            name = clean_title_str(m.get('name') or m.get('title') or 'Live Match')

            teams = m.get('teams') or {}
            logo = (
                (teams.get('home') or {}).get('badge') or
                m.get('poster') or ''
            )

            starts_at = m.get('starts_at', 0) or 0
            date_ms = m.get('date', 0) or 0
            if starts_at:
                start_dt = datetime.fromtimestamp(starts_at, tz=WIB)
            elif date_ms:
                start_dt = datetime.fromtimestamp(date_ms / 1000, tz=WIB)
            else:
                start_dt = None

            is_live = m.get('status') == 'live'
            time_str = ''

            if start_dt:
                time_str = start_dt.strftime('%H:%M WIB')
                if start_dt > now_wib + timedelta(hours=24):
                    continue
                ends_at = m.get('ends_at', 0) or 0
                if ends_at and datetime.fromtimestamp(ends_at, tz=WIB) < now_wib:
                    continue
                if is_live or (start_dt <= now_wib < start_dt + timedelta(hours=4) and m.get('status') != 'upcoming'):
                    is_live = True
                    tag = "• LIVE"
                    status_type = "LIVE"
                elif start_dt + timedelta(hours=4) <= now_wib and not is_live:
                    continue
                else:
                    tag = f"• {time_str}"
                    status_type = "UPCOMING"
                match_ts = int(start_dt.timestamp())
            else:
                is_live = True
                tag = "• LIVE"
                status_type = "LIVE"
                match_ts = int(now_wib.timestamp())

            prefix = '' if is_live else '[UPCOMING] '
            match_title_base = f"{prefix}[{league}] {name}".strip()

            # Collect all OnDemand servers (Primary + TV Channels + Substreams)
            od_servers = []
            seen_od_streams = set()

            # Primary stream
            enc_id = encrypt_match_id(mid, WORKER_AUTH_KEY)
            primary_url = f"{WORKER_BASE}/live/{enc_id}.m3u8"
            seen_od_streams.add(primary_url)
            od_servers.append(("Server 1 (Worker HLS)", primary_url))

            # TV Channels
            for ch in (m.get('tvChannels') or []):
                ch_id = ch.get('id')
                ch_name = ch.get('name') or 'TV Feed'
                if ch_id:
                    enc_ch_id = encrypt_match_id(str(ch_id), WORKER_AUTH_KEY)
                    ch_url = f"{WORKER_BASE}/live/{enc_ch_id}.m3u8"
                    if ch_url not in seen_od_streams:
                        seen_od_streams.add(ch_url)
                        srv_idx = len(od_servers) + 1
                        od_servers.append((f"Server {srv_idx} ({ch_name})", ch_url))

            # Substreams
            for sub in (m.get('substreams') or []):
                sub_id = sub.get('id')
                sub_name = sub.get('name') or 'Alt Stream'
                sub_locale = sub.get('locale', '')
                if sub_id:
                    enc_sub_id = encrypt_match_id(str(sub_id), WORKER_AUTH_KEY)
                    sub_url = f"{WORKER_BASE}/live/{enc_sub_id}.m3u8"
                    if sub_url not in seen_od_streams:
                        seen_od_streams.add(sub_url)
                        srv_idx = len(od_servers) + 1
                        loc_str = f" {sub_locale.upper()}" if sub_locale else ""
                        od_servers.append((f"Server {srv_idx} ({sub_name}{loc_str})", sub_url))

            for srv_label, s_url in od_servers:
                full_display_title = f"{match_title_base} - {srv_label} {tag}".strip()

                def build_od_entry(grp_title, _title=full_display_title, _logo=logo, _url=s_url):
                    item = []
                    extinf = f'#EXTINF:-1 tvg-id="" tvg-name="{_title}" tvg-logo="{_logo}" group-title="{grp_title}",{_title}'
                    item.append(extinf)
                    item.append(f'#EXTVLCOPT:http-referrer={ONDEMAND_REFERER}')
                    item.append(f'#EXTVLCOPT:http-user-agent={USER_AGENT}')
                    item.append(_url)
                    return item

                if is_live and cat_raw != '24/7-streams':
                    live_event_entries.append((match_ts, build_od_entry(GROUP_LIVE_EVENT)))
                elif status_type == "UPCOMING" and cat_raw != '24/7-streams':
                    if mid not in upcoming_dict:
                        upcoming_dict[mid] = (match_ts, [])
                    upcoming_dict[mid][1].extend(build_od_entry(GROUP_UPCOMING_EVENT))

                total_servers += 1

    # Sort Live Event newest first (matching website testa.js)
    live_event_entries.sort(key=lambda item: item[0], reverse=True)
    live_event_sorted_lines = []
    for _, entry_lines in live_event_entries:
        live_event_sorted_lines.extend(entry_lines)

    # Sort Upcoming Event closest kick-off first & take top 10 matches
    upcoming_items = list(upcoming_dict.values())
    upcoming_items.sort(key=lambda item: item[0])
    upcoming_sorted_lines = []
    for _, entry_lines in upcoming_items[:10]:
        upcoming_sorted_lines.extend(entry_lines)

    # 3. Read 24/7 Linear Channels grouped by category
    script_dir = os.path.dirname(os.path.abspath(__file__))
    nasional_env = os.environ.get('NASIONAL_OUTPUT', 'nasional.m3u').strip()
    if os.path.basename(script_dir) == 'scripts':
        nasional_path = os.path.normpath(os.path.join(script_dir, '..', nasional_env))
    else:
        nasional_path = os.path.normpath(os.path.join(script_dir, nasional_env))
    if not os.path.exists(nasional_path) and os.path.exists(nasional_env):
        nasional_path = nasional_env

    nasional_categories = {}
    nasional_cat_order = []
    total_247_channels = 0
    if os.path.exists(nasional_path):
        with open(nasional_path, 'r', encoding='utf-8', errors='ignore') as f:
            current_grp = None
            current_chunk = []
            for line in f:
                l = line.strip()
                if not l or l.startswith('#EXTM3U') or l.startswith('//'):
                    continue
                if l.startswith('#EXTINF:'):
                    if current_grp and current_chunk:
                        nasional_categories.setdefault(current_grp, []).extend(current_chunk)
                        current_chunk = []
                    grp_m = re.search(r'group-title="([^"]*)"', l)
                    current_grp = grp_m.group(1).strip() if grp_m else 'Other'
                    if current_grp not in nasional_cat_order:
                        nasional_cat_order.append(current_grp)
                    total_247_channels += 1
                current_chunk.append(l)
            if current_grp and current_chunk:
                nasional_categories.setdefault(current_grp, []).extend(current_chunk)

    # 4. Assemble Final Master Playlist
    final_lines = ['#EXTM3U url-tvg="https://raw.githubusercontent.com/apistech/project/refs/heads/main/epgs/guide.xml"']

    # 0. 📢 INFO (Paling Atas)
    if '📢 INFO' in nasional_categories:
        final_lines.extend(nasional_categories['📢 INFO'])

    # 1. 🔥 Hot Event (Live Big Matches)
    if hot_entries:
        final_lines.extend(hot_entries)

    # 2. 🔴 Live Event (All Live Sports)
    if live_event_sorted_lines:
        final_lines.extend(live_event_sorted_lines)

    # 3. ⏳ Upcoming Event (Top 10 Upcoming Matches)
    if upcoming_sorted_lines:
        final_lines.extend(upcoming_sorted_lines)

    # 4. 🇮🇩 NASIONAL (TV Indonesia 24/7)
    if '🇮🇩 NASIONAL' in nasional_categories:
        final_lines.extend(nasional_categories['🇮🇩 NASIONAL'])

    # 5. ⚽ SPORTS (Channel TV 24/7: beIN, SPOTV, dll)
    if '⚽ SPORTS' in nasional_categories:
        final_lines.extend(nasional_categories['⚽ SPORTS'])

    # 6. Remaining 24/7 Categories (Movies, Kids, Doc, Religi, Asia, Music)
    for cat in nasional_cat_order:
        if cat not in ['📢 INFO', '🇮🇩 NASIONAL', '⚽ SPORTS'] and cat in nasional_categories:
            final_lines.extend(nasional_categories[cat])

    script_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(script_dir) == 'scripts':
        out_path = os.path.join(script_dir, '..', OUTPUT_FILE)
    else:
        out_path = os.path.join(script_dir, OUTPUT_FILE)
    out_path = os.path.normpath(out_path)

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(final_lines) + '\n')

    print(f"Synced {out_path} successfully: {total_servers} live event servers + {total_247_channels} 24/7 channels merged.")
    return True




if __name__ == '__main__':
    generate_playlist()
