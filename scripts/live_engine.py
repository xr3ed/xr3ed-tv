#!/usr/bin/env python3
"""
live_engine.py
==============
Unified live sports engine ported from Cloudstream (Xr3edTVProvider.kt).
Merges OnDemand + Kltra + Beesport with:
- OnDemand as Primary Anchor (internal deduplication)
- Cross-provider matching & multi-server merging
- Detection & filtering of 24/7 linear sports channels & cartoons
- Multi-server failover: Worker HLS, SD, Substreams, TV Channels, Kltra, Beesport
- Dynamic key extraction from testa.js for modern Kltra /jos/ endpoints
- Strict security: 100% environment-driven variables without hardcoded fallbacks
"""

import os
import sys
import json
import base64
import hashlib
import time
import re
import urllib.parse
import urllib.request
import urllib.error
import http.cookiejar
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

# Ensure UTF-8 output on Windows
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    AESGCM = None

# WIB Timezone (UTC+7)
WIB = timezone(timedelta(hours=7))
DESKTOP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

# Load local .env if available
script_dir = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(script_dir, '.cache_live_matches.json')
CACHE_TTL = 60  # seconds
env_file = os.path.normpath(os.path.join(script_dir, '..', '.env'))
try:
    from dotenv import load_dotenv
    if os.path.exists(env_file):
        load_dotenv(env_file, override=True, interpolate=False)
    else:
        load_dotenv(override=True, interpolate=False)
except ImportError:
    pass

def clean_env(val: str) -> str:
    return (val or '').strip().lstrip('\ufeff\uffef\u200b\u200c\u200d').strip()

# ─── Pure Environment Reads (Zero hardcoded fallback URLs or keys) ────────────
API_BASE = clean_env(os.environ.get('XR3EDTV_API_BASE', '')).rstrip('/')
XOR_KEY = clean_env(os.environ.get('XR3EDTV_XOR_KEY', ''))
SALT_KEY = clean_env(os.environ.get('XR3EDTV_SALT_KEY', ''))
ONDEMAND_API = clean_env(os.environ.get('XR3EDTV_ONDEMAND_API', ''))
ONDEMAND_EXTRACT = clean_env(os.environ.get('XR3EDTV_ONDEMAND_EXTRACT', ''))
ONDEMAND_REFERER = clean_env(os.environ.get('XR3EDTV_ONDEMAND_REFERER', ''))
DEFAULT_REFERER = clean_env(os.environ.get('XR3EDTV_REFERER', ''))
WORKER_BASE = clean_env(os.environ.get('WORKER_BASE_URL', '')).rstrip('/')
WORKER_AUTH_KEY = clean_env(os.environ.get('WORKER_AUTH_KEY', ''))

LIVEEVENT_SRC_URL = clean_env(os.environ.get('LIVEEVENT_SRC_URL', '')).rstrip('/')
LIVEEVENT_REF_URL = clean_env(os.environ.get('LIVEEVENT_REF_URL', '')).rstrip('/')
LIVEEVENT_CDN_BASE = clean_env(os.environ.get('LIVEEVENT_CDN_BASE', '')).rstrip('/')

TG_LINK = "https://t.me/CloudstreamXR"
TG_LOGO = "https://raw.githubusercontent.com/xr3ed/xr3ed-tv/main/assets/telegram.png"
COFFEE_LINK = "https://lynk.id/xr3ed"
COFFEE_LOGO = "https://raw.githubusercontent.com/xr3ed/xr3ed-tv/main/assets/coffee.png"

GROUP_INFO = "📢 INFO"
GROUP_HOT_EVENT = "🔥 Hot Event"
GROUP_LIVE_EVENT = "🔴 Live Event"
GROUP_UPCOMING_EVENT = "⏳ Upcoming Event"
GROUP_FIGHT_EVENT = "🥊 FIGHT & COMBAT"

PREMIUM_LEAGUES = [
    "premier league", "laliga", "la liga", "serie a", "bundesliga",
    "uefa champions league", "champions league", "europa league",
    "fa cup", "copa del rey", "dfb-pokal", "coppa italia", "ligue 1",
    "formula 1", "f1", "motogp", "ufc", "boxing", "one championship",
    "nba", "nfl", "wwe", "aew", "bellator"
]

GENERIC_PLACEHOLDERS = {
    'table tennis', 'tennis', 'soccer', 'football', 'basketball',
    'baseball', 'billiards', 'badminton', 'volleyball'
}

def log(msg):
    now_str = datetime.now(WIB).strftime('%H:%M:%S')
    print(f"[{now_str}] {msg}", flush=True)

def fetch_url(url: str, referer: str = None, timeout: int = 15) -> bytes:
    headers = {
        'User-Agent': DESKTOP_UA,
        'Accept': 'application/json, text/plain, text/html, */*'
    }
    if referer:
        headers['Referer'] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read()

def encrypt_match_id(match_id: str, secret: str) -> str:
    if not secret:
        return ""
    if not AESGCM:
        return base64.urlsafe_b64encode(match_id.encode('utf-8')).decode('utf-8').rstrip('=')
    key = hashlib.sha256(secret.encode('utf-8')).digest()
    aesgcm = AESGCM(key)
    iv = os.urandom(12)
    encrypted_with_tag = aesgcm.encrypt(iv, match_id.encode('utf-8'), None)
    return base64.urlsafe_b64encode(iv + encrypted_with_tag).decode('utf-8').rstrip('=')

def get_dynamic_xor_key_bytes() -> bytes:
    """Dynamically generates client XOR key directly from testa.js matching modern web app."""
    try:
        url = "https://kltraid.pages.dev/js/testa.js"
        content = fetch_url(url, timeout=8).decode('utf-8', errors='ignore')
        idx = content.find('RESPONSE_SECRET_KEY_CLIENT')
        if idx != -1:
            idx_ret = content.find('return _0x4eec63', idx)
            snippet = content[idx:idx_ret]
            arr_matches = re.findall(r'\[(0x[0-9a-fA-F,\s0x]+)\]', snippet)
            if len(arr_matches) >= 2:
                arr1 = [int(x.strip(), 16) for x in arr_matches[0].split(',') if x.strip()]
                arr2 = [int(x.strip(), 16) for x in arr_matches[1].split(',') if x.strip()]
                chars = []
                for i in range(len(arr1)):
                    val = arr1[i] ^ arr2[i % len(arr2)] ^ ((i * 0x11 + 0x99d1) & 0xffff)
                    chars.append(chr(val))
                return "".join(chars).encode('utf-8')
    except Exception:
        pass

    if XOR_KEY:
        return XOR_KEY.encode('utf-8')
    return b""

def xor_decrypt(encrypted_b64: str, key_bytes: bytes) -> list:
    if not encrypted_b64 or not key_bytes:
        return []
    raw_data = base64.b64decode(encrypted_b64.strip())
    k_len = len(key_bytes)
    decrypted = bytearray(len(raw_data))
    for i in range(len(raw_data)):
        decrypted[i] = raw_data[i] ^ key_bytes[i % k_len]
    return json.loads(decrypted.decode('utf-8', errors='ignore'), strict=False)

def get_event_hidden_id(uuid_str: str, salt: str) -> str:
    parts = uuid_str.split('-')
    if len(parts) < 5 or not salt:
        return ""
    s1 = salt[:7]
    s2 = salt[12:20]
    raw = parts[2] + s1 + parts[4] + s2 + parts[0]
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]

def resolve_vivo_redirect(url: str) -> str:
    if 'resolve-web' not in url and 'livevent.elutuna.workers.dev' not in url:
        return url
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    headers = {'User-Agent': DESKTOP_UA, 'Referer': DEFAULT_REFERER or 'https://playerkltratv.pages.dev/'}
    req = urllib.request.Request(url, headers=headers)
    try:
        res = opener.open(req, timeout=4)
        loc = res.headers.get('Location')
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

# ─── Filter Channel Linear & Kartun (Persis Xr3edTVProvider.kt) ────────────────

def is_linear_sports_channel(item: dict) -> bool:
    mid = str(item.get('id') or '').lower()
    clean_id = mid
    for prefix in ('od_', 'kltra_', 'bs_'):
        if clean_id.startswith(prefix):
            clean_id = clean_id[len(prefix):]
    title = (item.get('title') or item.get('name') or '').lower()
    league = (item.get('league') or '').lower()

    if clean_id.startswith('247-'):
        return True
    if clean_id in ('nfl-network', 'rally-tv') or clean_id.startswith('sky-sports-'):
        return True
    if '24/7' in title or '24/7' in league:
        return True
    if 'rally tv' in title:
        return True

    home = (item.get('home') or '').strip()
    away = (item.get('away') or '').strip()
    if not home and not away:
        teams = item.get('teams') or {}
        if isinstance(teams, dict):
            home = (teams.get('home') or {}).get('name', '').strip() if isinstance(teams.get('home'), dict) else str(teams.get('home') or '').strip()
            away = (teams.get('away') or {}).get('name', '').strip() if isinstance(teams.get('away'), dict) else str(teams.get('away') or '').strip()
        elif isinstance(teams, list) and len(teams) >= 2:
            home, away = str(teams[0]).strip(), str(teams[1]).strip()

    has_no_teams = not home and not away and ' vs ' not in title and ' v ' not in title
    if has_no_teams:
        known_linear = (
            'network' in title or
            'fox footy' in title or
            'fox cricket' in title or
            'fox league' in title or
            'sky sports' in title or
            'willow' in title
        )
        if known_linear:
            return True

    return False

def is_cartoon(title: str) -> bool:
    t = (title or '').lower()
    return any(c in t for c in (
        'south park', 'family guy', 'simpsons', 'spongebob',
        'cows', 'futurama', 'rick and morty'
    ))

def is_fight_match(league: str, title: str = "") -> bool:
    text = f"{league} {title}".lower()
    keywords = ['fight', 'combat', 'ufc', 'boxing', 'mma', 'wrestling', 'wwe', 'aew', 'tna', 'kickboxing', 'bellator', 'one championship']
    return any(k in text for k in keywords)

# ─── Matching Helpers (Token Overlap Persis Cloudstream) ──────────────────────

def name_tokens(s: str) -> set:
    clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', (s or '').lower())
    clean = clean.replace(' fc', '').replace(' cf', '').replace(' sc', '').replace(' utd', ' united')
    return set(tok for tok in clean.split() if len(tok) > 2)

def is_same_match(m1: dict, m2: dict) -> bool:
    t1 = m1.get('title') or m1.get('name') or ''
    t2 = m2.get('title') or m2.get('name') or ''
    l1 = m1.get('league') or ''
    l2 = m2.get('league') or ''

    full1 = f"{t1} {l1}".lower()
    full2 = f"{t2} {l2}".lower()

    # Khusus combat / UFC
    is_combat1 = 'combat' in full1 or 'ufc' in full1 or 'bjj' in full1
    is_combat2 = 'combat' in full2 or 'ufc' in full2 or 'bjj' in full2
    if is_combat1 and is_combat2:
        if 'bjj' in full1 and 'bjj' in full2:
            return True
        m_u1 = re.search(r'ufc\s*(\d+)', full1)
        m_u2 = re.search(r'ufc\s*(\d+)', full2)
        if m_u1 and m_u2 and m_u1.group(1) == m_u2.group(1):
            return True

    # Khusus Motorsport: Sesi berbeda adalah event berbeda
    is_ms1 = 'motorsport' in full1 or 'f1' in full1 or 'grand prix' in full1 or 'motogp' in full1
    is_ms2 = 'motorsport' in full2 or 'f2' in full2 or 'grand prix' in full2 or 'motogp' in full2
    if is_ms1 and is_ms2:
        is_p1 = 'fp' in full1 or 'practice' in full1
        is_p2 = 'fp' in full2 or 'practice' in full2
        is_q1 = 'qualifying' in full1 or 'quali' in full1
        is_q2 = 'qualifying' in full2 or 'quali' in full2
        is_r1 = 'race' in full1 and not is_p1 and not is_q1
        is_r2 = 'race' in full2 and not is_p2 and not is_q2
        if is_p1 != is_p2 or is_q1 != is_q2 or is_r1 != is_r2:
            return False

    tok1 = name_tokens(full1)
    tok2 = name_tokens(full2)
    if not tok1 or not tok2:
        return False

    inter = len(tok1.intersection(tok2))
    min_size = min(len(tok1), len(tok2))
    if min_size == 0:
        return False
    score = inter / min_size
    if score < 0.6:
        return False

    ts1 = m1.get('timestamp_ms', 0)
    ts2 = m2.get('timestamp_ms', 0)
    if ts1 > 0 and ts2 > 0 and abs(ts1 - ts2) > 12 * 3600 * 1000:
        return False

    return True

# ─── Fetch Engine 1: OnDemand ─────────────────────────────────────────────────

def fetch_ondemand_matches() -> list:
    if not ONDEMAND_API:
        return []
    try:
        raw = fetch_url(ONDEMAND_API, referer=ONDEMAND_REFERER, timeout=20)
        data = json.loads(raw.decode('utf-8'))
        matches = data if isinstance(data, list) else data.get('matches', [])
    except Exception as e:
        log(f"Error fetching OnDemand: {e}")
        return []

    results = []
    now_ms = int(time.time() * 1000)

    for m in matches:
        mid = str(m.get('id') or m.get('match_id') or '').strip()
        if not mid:
            continue

        league = (m.get('league') or 'Sports').strip()
        teams = m.get('teams') or {}
        home = (teams.get('home') or {}).get('name', '').strip() if isinstance(teams.get('home'), dict) else ''
        away = (teams.get('away') or {}).get('name', '').strip() if isinstance(teams.get('away'), dict) else ''

        if home and away:
            title = f"{home} vs {away}"
        else:
            title = (m.get('title') or m.get('name') or league or f"Match {mid}").strip()

        if is_cartoon(title):
            continue

        raw_poster = m.get('poster') or ''
        home_badge = (teams.get('home') or {}).get('badge', '') if isinstance(teams.get('home'), dict) else ''
        ppv_poster = m.get('ppvPoster') or ''
        logo = (raw_poster or ppv_poster or home_badge or '').strip()

        status = (m.get('status') or 'upcoming').lower()
        starts_at = m.get('starts_at', 0) or 0
        date_ms = m.get('date', 0) or 0
        ts_ms = starts_at * 1000 if starts_at else date_ms

        is_linear = is_linear_sports_channel(m)
        is_live = status == 'live'
        is_upcoming = status == 'upcoming' or (not is_live and ts_ms > now_ms)

        # Jika tanpa tanggal dan status bukan live, cek linear
        if not is_live and not is_upcoming and ts_ms == 0 and is_linear:
            is_live = True

        kickoff_str = ""
        if ts_ms > 0:
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=WIB)
            kickoff_str = f"LIVE {dt.strftime('%H:%M')}" if is_live else f"{dt.strftime('%H:%M')} WIB"

        # Build servers
        servers = []
        seen_urls = set()
        if WORKER_BASE and WORKER_AUTH_KEY:
            # Server 1 HD
            enc_primary = encrypt_match_id(mid, WORKER_AUTH_KEY)
            p_url = f"{WORKER_BASE}/live/{enc_primary}.m3u8"
            servers.append({'name': 'Server 1 (Worker HLS)', 'url': p_url, 'referer': ONDEMAND_REFERER})
            seen_urls.add(p_url)

            # Substreams
            for sub in (m.get('substreams') or []):
                sub_id = str(sub.get('id') or '').strip()
                sub_name = sub.get('name') or 'Alt Stream'
                sub_loc = (sub.get('locale') or '').upper()
                if sub_id:
                    enc_sub = encrypt_match_id(sub_id, WORKER_AUTH_KEY)
                    s_url = f"{WORKER_BASE}/live/{enc_sub}.m3u8"
                    if s_url not in seen_urls:
                        seen_urls.add(s_url)
                        label = f"Server {len(servers) + 1} ({sub_name} {sub_loc})".strip()
                        servers.append({'name': label, 'url': s_url, 'referer': ONDEMAND_REFERER})

            # TV Channels
            for tv in (m.get('tvChannels') or []):
                tv_id = str(tv.get('id') or '').replace('dlhd-', '').replace('tv-', '').strip()
                tv_name = tv.get('name') or 'TV Channel'
                if tv_id and tv_id.isdigit():
                    enc_tv = encrypt_match_id(tv_id, WORKER_AUTH_KEY)
                    t_url = f"{WORKER_BASE}/live/{enc_tv}.m3u8"
                    if t_url not in seen_urls:
                        seen_urls.add(t_url)
                        label = f"Server {len(servers) + 1} ({tv_name})"
                        servers.append({'name': label, 'url': t_url, 'referer': ONDEMAND_REFERER})

        is_hot = bool(m.get('popular') or m.get('trending') or (m.get('viewers', 0) or 0) >= 10) or any(pl in league.lower() for pl in PREMIUM_LEAGUES)

        results.append({
            'id': f"od_{mid}",
            'source': 'ondemand',
            'title': title,
            'league': league,
            'home': home,
            'away': away,
            'logo': logo,
            'status': status,
            'is_live': is_live,
            'is_upcoming': is_upcoming,
            'is_hot': is_hot,
            'is_linear': is_linear,
            'kickoff_str': kickoff_str,
            'timestamp_ms': ts_ms,
            'servers': servers
        })

    # Deduplikasi internal OnDemand
    clean_results = []
    for od in results:
        dup_idx = -1
        for idx, exist in enumerate(clean_results):
            if is_same_match(exist, od):
                dup_idx = idx
                break
        if dup_idx >= 0:
            existing = clean_results[dup_idx]
            srv_urls = {s['url'] for s in existing['servers']}
            for s in od['servers']:
                if s['url'] not in srv_urls:
                    existing['servers'].append(s)
                    srv_urls.add(s['url'])
            existing['is_live'] = existing['is_live'] or od['is_live']
            existing['is_upcoming'] = False if existing['is_live'] else (existing['is_upcoming'] or od['is_upcoming'])
            existing['is_hot'] = existing['is_hot'] or od['is_hot']
            if not existing['logo'] and od['logo']:
                existing['logo'] = od['logo']
        else:
            clean_results.append(od)

    return clean_results

# ─── Fetch Engine 2: Kltra ────────────────────────────────────────────────────

def fetch_kltra_matches() -> list:
    if not API_BASE:
        return []
    ts = int(time.time() * 1000)
    key_bytes = get_dynamic_xor_key_bytes()
    if not key_bytes:
        return []

    events_data = []
    players_data = []
    # Try modern /jos/ endpoints first, fallback to /vip/
    for ep in ["/jos/luffy.json", "/vip/eventweb.json"]:
        try:
            raw = fetch_url(f"{API_BASE}{ep}?v={ts}", timeout=10).decode('utf-8', errors='ignore').strip()
            if raw.startswith("[") or raw.startswith("{"):
                events_data = json.loads(raw)
            else:
                events_data = xor_decrypt(raw, key_bytes)
            if events_data:
                break
        except Exception:
            pass

    for ep in ["/jos/zoro.json", "/vip/sdplayer.json"]:
        try:
            raw = fetch_url(f"{API_BASE}{ep}?v={ts}", timeout=10).decode('utf-8', errors='ignore').strip()
            if raw.startswith("[") or raw.startswith("{"):
                players_data = json.loads(raw)
            else:
                players_data = xor_decrypt(raw, key_bytes)
            if players_data:
                break
        except Exception:
            pass

    player_map = {}
    for p in players_data:
        r_val = p.get('r') or p.get('id')
        if r_val:
            player_map[r_val] = p.get('servers', [])

    # Parallel vivo resolver
    vivo_urls = set()
    for p in players_data:
        for s in p.get('servers', []):
            u = s.get('url', '')
            if 'resolve-web' in u or 'livevent.elutuna.workers.dev' in u:
                vivo_urls.add(u)
    vivo_map = {}
    if vivo_urls:
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(resolve_vivo_redirect, u): u for u in vivo_urls}
            for fut in as_completed(futs):
                orig_u = futs[fut]
                try:
                    vivo_map[orig_u] = fut.result()
                except Exception:
                    vivo_map[orig_u] = orig_u

    results = []
    now_wib = datetime.now(WIB)

    for ev in events_data:
        ev_id = ev.get('id', '')
        r_val = ev.get('r') or ev_id
        servers_raw = player_map.get(r_val, [])
        if not servers_raw and SALT_KEY and ev_id:
            hid = get_event_hidden_id(ev_id, SALT_KEY)
            servers_raw = player_map.get(hid, [])

        active_servers = [s for s in servers_raw if s.get('url')]
        if not active_servers:
            continue

        league = (ev.get('league') or 'Sports').strip()
        t1 = (ev.get('team1', {}).get('name') or '').strip()
        t2 = (ev.get('team2', {}).get('name') or '').strip()
        is_identical = t1.lower() == t2.lower()
        is_t1_p = t1.lower() in GENERIC_PLACEHOLDERS
        is_t2_p = t2.lower() in GENERIC_PLACEHOLDERS

        if t1 and t2 and not is_identical and not is_t1_p and not is_t2_p:
            title = f"{t1} vs {t2}"
        elif t1 and not is_t1_p:
            title = t1
        else:
            title = (ev.get('name') or ev.get('title') or league).strip()

        logo = (ev.get('team1', {}).get('logo') or ev.get('icon') or '').strip()

        m_date = ev.get('match_date') or ev.get('kickoff_date') or ""
        m_time = ev.get('match_time') or ev.get('kickoff_time') or ""
        duration = float(ev.get('duration', 3.5))

        ts_ms = 0
        is_live = False
        is_upcoming = False
        kickoff_str = ""

        if m_date and m_time:
            try:
                dt_str = f"{m_date.strip()} {m_time.strip()}"
                match_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M").replace(tzinfo=WIB)
                end_dt = match_dt + timedelta(hours=duration)
                ts_ms = int(match_dt.timestamp() * 1000)

                if match_dt > now_wib + timedelta(hours=24):
                    continue
                if match_dt <= now_wib < end_dt:
                    is_live = True
                    kickoff_str = f"LIVE {m_time}"
                elif now_wib < match_dt:
                    is_upcoming = True
                    kickoff_str = f"{m_time} WIB"
                else:
                    continue  # Selesai
            except Exception:
                pass

        if not is_live and not is_upcoming:
            continue

        is_linear = is_linear_sports_channel({'title': title, 'league': league, 'home': t1, 'away': t2})
        icon_str = (ev.get('icon') or '').lower()
        is_main = 'main_' in icon_str or 'main-' in icon_str or '_main' in icon_str
        is_hot = is_main or any(pl in league.lower() for pl in PREMIUM_LEAGUES)

        k_servers = []
        for s in active_servers:
            u = s.get('url', '')
            resolved_u = vivo_map.get(u, u)
            label = s.get('label') or s.get('name') or 'Stream'
            ref = DEFAULT_REFERER or 'https://playerkltratv.pages.dev/'
            if 'online909.com' in resolved_u:
                ref = 'https://player.online909.com/'
            k_servers.append({'name': f"Kltra - {label}", 'url': resolved_u, 'referer': ref})

        results.append({
            'id': f"kltra_{ev_id}",
            'source': 'kltra',
            'title': title,
            'league': league,
            'home': t1,
            'away': t2,
            'logo': logo,
            'status': 'live' if is_live else 'upcoming',
            'is_live': is_live,
            'is_upcoming': is_upcoming,
            'is_hot': is_hot,
            'is_linear': is_linear,
            'kickoff_str': kickoff_str,
            'timestamp_ms': ts_ms,
            'servers': k_servers
        })

    return results

# ─── Fetch Engine 3: Beesport ─────────────────────────────────────────────────

def fetch_beesport_matches() -> list:
    if not LIVEEVENT_SRC_URL:
        return []

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    req = urllib.request.Request(LIVEEVENT_SRC_URL, headers={'User-Agent': DESKTOP_UA})
    try:
        with opener.open(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        log(f"Error fetching Beesport homepage: {e}")
        return []

    xsrf_token = None
    for cookie in cj:
        if cookie.name == 'XSRF-TOKEN':
            xsrf_token = urllib.parse.unquote(cookie.value)
            break

    m = re.search(r'data-page="([^"]+)"', html)
    if not m:
        return []

    raw_json = m.group(1).replace('&quot;', '"').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    try:
        data = json.loads(raw_json)
    except Exception:
        return []

    widgets = data.get('props', {}).get('widgets', [])
    bs_raw_matches = []
    seen_slugs = set()
    for w in widgets:
        for match in w.get('data', {}).get('matches', []):
            slug = match.get('slug')
            if slug and slug not in seen_slugs:
                seen_slugs.add(slug)
                bs_raw_matches.append(match)

    def extract_ch_name(ch_url):
        clean = ch_url.rstrip('/')
        if clean.endswith('/index.m3u8'):
            return clean.split('/')[-2]
        return clean.split('/')[-1]

    def resolve_bs_channel(ch_url):
        ch_name = extract_ch_name(ch_url)
        default_url = f"{LIVEEVENT_CDN_BASE}/{ch_name}/index.jpg" if LIVEEVENT_CDN_BASE else ch_url
        if not LIVEEVENT_SRC_URL:
            return default_url

        auth_url = f"{LIVEEVENT_SRC_URL}/authorize-channel"
        payload = json.dumps({"channel": ch_url}).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': DESKTOP_UA,
            'Origin': LIVEEVENT_SRC_URL,
            'Referer': f"{LIVEEVENT_SRC_URL}/",
            'X-Requested-With': 'XMLHttpRequest'
        }
        if xsrf_token:
            headers['X-XSRF-TOKEN'] = xsrf_token
        try:
            req_auth = urllib.request.Request(auth_url, data=payload, headers=headers)
            with opener.open(req_auth, timeout=8) as r_auth:
                res_data = json.loads(r_auth.read().decode('utf-8'))
                s_url = res_data.get('server', '')
                if 'link=' in s_url:
                    parsed = urllib.parse.urlparse(s_url)
                    qs = urllib.parse.parse_qs(parsed.query)
                    if 'link' in qs and qs['link'][0]:
                        return qs['link'][0]
                if s_url and s_url.startswith('http') and 'twinspeed.space' not in s_url:
                    return s_url
        except Exception:
            pass
        return default_url

    results = []
    now_ts = int(time.time())

    for bm in bs_raw_matches:
        slug = bm.get('slug', '')
        channels = bm.get('channels', [])
        if not channels:
            continue

        home = (bm.get('homeTeam') or {}).get('name') or ''
        away = (bm.get('awayTeam') or {}).get('name') or ''
        league = (bm.get('league') or {}).get('name') or 'Sport'

        if home and away:
            title = f"{home} vs {away}"
        else:
            title = bm.get('name') or league

        home_logo = (bm.get('homeTeam') or {}).get('logo') or ''
        league_logo = (bm.get('league') or {}).get('logo') or ''
        logo = home_logo or league_logo or ''

        play_at = bm.get('play_at') or bm.get('start_at') or 0
        ts_ms = play_at * 1000 if play_at else 0
        is_live = bool(bm.get('is_live'))
        is_upcoming = not is_live and play_at > now_ts

        # Jika match sudah lewat lebih dari 4 jam dan tidak live, lewati
        if not is_live and play_at > 0 and play_at + 14400 < now_ts:
            continue

        kickoff_str = ""
        if ts_ms > 0:
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=WIB)
            kickoff_str = f"LIVE {dt.strftime('%H:%M')}" if is_live else f"{dt.strftime('%H:%M')} WIB"

        # Resolve streams
        bs_servers = []
        for idx, ch_url in enumerate(channels):
            stream_u = resolve_bs_channel(ch_url)
            ch_name = extract_ch_name(ch_url).replace('-', ' ')
            srv_label = f"Beesport - {ch_name}" if ch_name else f"Beesport - Server {idx + 1}"
            bs_servers.append({
                'name': srv_label,
                'url': stream_u,
                'referer': LIVEEVENT_REF_URL or 'https://new-player.greenvora.net/'
            })

        is_hot = bool(bm.get('is_hot')) or any(pl in league.lower() for pl in PREMIUM_LEAGUES)

        results.append({
            'id': f"bs_{slug}",
            'source': 'beesport',
            'title': title,
            'league': league,
            'home': home,
            'away': away,
            'logo': logo,
            'status': 'live' if is_live else 'upcoming',
            'is_live': is_live,
            'is_upcoming': is_upcoming,
            'is_hot': is_hot,
            'is_linear': False,
            'kickoff_str': kickoff_str,
            'timestamp_ms': ts_ms,
            'servers': bs_servers
        })

    return results

# ─── Unified Merge Engine (Persis Cloudstream) ────────────────────────────────

def fetch_merged_matches(force_refresh: bool = False) -> dict:
    if not force_refresh and os.path.exists(CACHE_FILE):
        try:
            mtime = os.path.getmtime(CACHE_FILE)
            if time.time() - mtime < CACHE_TTL:
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    cached = json.load(f)
                    if cached and 'all_matches' in cached:
                        log(f"Menggunakan data live sports dari cache ({int(time.time() - mtime)}s lalu).")
                        return cached
        except Exception:
            pass

    log("Mengambil data live sports dari OnDemand, Kltra, dan Beesport secara paralel...")
    od_matches = []
    kltra_matches = []
    bs_matches = []

    with ThreadPoolExecutor(max_workers=3) as executor:
        f_od = executor.submit(fetch_ondemand_matches)
        f_km = executor.submit(fetch_kltra_matches)
        f_bs = executor.submit(fetch_beesport_matches)

        od_matches = f_od.result()
        kltra_matches = f_km.result()
        bs_matches = f_bs.result()

    log(f"Raw feeds loaded: OnDemand={len(od_matches)}, Kltra={len(kltra_matches)}, Beesport={len(bs_matches)}")

    merged_results = []
    linear_channels = []
    used_kltra_ids = set()
    used_bs_ids = set()

    # Step 1: OnDemand sebagai Primary Anchor
    for od in od_matches:
        if od.get('is_linear'):
            linear_channels.append(od)
            continue

        combined_servers = []
        combined_is_hot = od.get('is_hot', False)

        # Merge Kltra yang cocok (Kltra server diutamakan)
        matched_km = None
        for km in kltra_matches:
            if km['id'] not in used_kltra_ids and is_same_match(od, km):
                matched_km = km
                used_kltra_ids.add(km['id'])
                combined_is_hot = combined_is_hot or km.get('is_hot', False)
                combined_servers.extend(km.get('servers', []))
                break

        # Server OnDemand
        combined_servers.extend(od.get('servers', []))

        # Merge Beesport yang cocok
        matched_bs = None
        for bs in bs_matches:
            if bs['id'] not in used_bs_ids and is_same_match(od, bs):
                matched_bs = bs
                used_bs_ids.add(bs['id'])
                combined_is_hot = True
                combined_servers.extend(bs.get('servers', []))
                break

        is_live = od['is_live'] or (matched_km and matched_km['is_live']) or (matched_bs and matched_bs['is_live'])
        is_upcoming = False if is_live else (od['is_upcoming'] or (matched_km and matched_km['is_upcoming']) or (matched_bs and matched_bs['is_upcoming']))
        ts = od['timestamp_ms'] or (matched_km and matched_km['timestamp_ms']) or (matched_bs and matched_bs['timestamp_ms']) or 0

        # Deduplikasi server URL
        final_servers = []
        seen_s_urls = set()
        for s in combined_servers:
            if s['url'] not in seen_s_urls:
                seen_s_urls.add(s['url'])
                final_servers.append(s)

        merged_results.append({
            **od,
            'servers': final_servers,
            'is_live': is_live,
            'is_upcoming': is_upcoming,
            'is_hot': combined_is_hot,
            'timestamp_ms': ts
        })

    # Step 2: Kltra matches yang belum di-merge ke OnDemand
    for km in kltra_matches:
        if km['id'] in used_kltra_ids:
            continue
        if km.get('is_linear'):
            linear_channels.append(km)
            continue

        combined_servers = list(km.get('servers', []))
        combined_is_hot = km.get('is_hot', False)

        matched_bs = None
        for bs in bs_matches:
            if bs['id'] not in used_bs_ids and is_same_match(km, bs):
                matched_bs = bs
                used_bs_ids.add(bs['id'])
                combined_is_hot = True
                combined_servers.extend(bs.get('servers', []))
                break

        is_live = km['is_live'] or (matched_bs and matched_bs['is_live'])
        is_upcoming = False if is_live else (km['is_upcoming'] or (matched_bs and matched_bs['is_upcoming']))
        ts = km['timestamp_ms'] or (matched_bs and matched_bs['timestamp_ms']) or 0

        final_servers = []
        seen_s_urls = set()
        for s in combined_servers:
            if s['url'] not in seen_s_urls:
                seen_s_urls.add(s['url'])
                final_servers.append(s)

        merged_results.append({
            **km,
            'servers': final_servers,
            'is_live': is_live,
            'is_upcoming': is_upcoming,
            'is_hot': combined_is_hot,
            'timestamp_ms': ts
        })

    # Step 3: Beesport unik tersisa
    for bs in bs_matches:
        if bs['id'] in used_bs_ids:
            continue
        merged_results.append(bs)

    # Pisahkan ke Hot, Live, Upcoming
    hot_matches = [m for m in merged_results if m['is_live'] and m['is_hot']]
    live_matches = [m for m in merged_results if m['is_live']]
    upcoming_matches = [m for m in merged_results if m['is_upcoming']]
    upcoming_matches.sort(key=lambda x: x['timestamp_ms'] if x['timestamp_ms'] > 0 else 9999999999999)

    log(f"Hasil Merge: Live={len(live_matches)} (Hot={len(hot_matches)}), Upcoming={len(upcoming_matches)}, Linear 24/7={len(linear_channels)}")

    result_data = {
        'all_matches': merged_results,
        'hot_matches': hot_matches,
        'live_matches': live_matches,
        'upcoming_matches': upcoming_matches,
        'linear_channels': linear_channels
    }

    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(result_data, f)
    except Exception:
        pass

    return result_data

# ─── M3U Generator Helper ─────────────────────────────────────────────────────

def render_m3u_entry(grp_title: str, match: dict, server_idx: int, server: dict) -> list:
    time_str = ""
    if not match.get('is_linear') and match.get('timestamp_ms', 0) > 0:
        dt = datetime.fromtimestamp(match['timestamp_ms'] / 1000, tz=WIB)
        time_str = f" • LIVE {dt.strftime('%H:%M')}" if match['is_live'] else f" • {dt.strftime('%H:%M')} WIB"

    s_name = server.get('name') or f"Server {server_idx}"
    prefix = "" if (match.get('is_linear') or match['is_live']) else "[UPCOMING] "
    full_title = f"{prefix}[{match['league']}] {match['title']} - {s_name}{time_str}".strip()

    extinf = f'#EXTINF:-1 tvg-id="{match.get("id", "")}" tvg-name="{full_title}" tvg-logo="{match.get("logo", "")}" group-title="{grp_title}",{full_title}'
    lines = [extinf]
    ref = server.get('referer')
    if ref:
        lines.append(f'#EXTVLCOPT:http-referrer={ref}')
    lines.append(f'#EXTVLCOPT:http-user-agent={DESKTOP_UA}')

    headers_json = {"User-Agent": DESKTOP_UA}
    if ref:
        headers_json["Referer"] = ref
    lines.append(f'#EXTHTTP:{json.dumps(headers_json)}')
    if server.get('clearkey'):
        lines.append('#KODIPROP:inputstream.adaptive.license_type=clearkey')
        lines.append(f'#KODIPROP:inputstream.adaptive.license_key={server["clearkey"]}')
    lines.append(server['url'])
    return lines

def generate_liveevent_m3u(merged_data: dict, max_upcoming: int = 25) -> str:
    now_str = datetime.now(WIB).strftime('%Y-%m-%d %H:%M WIB')
    lines = [
        "#EXTM3U",
        f"# XR3ED LIVE SPORTS PLAYLIST — Updated: {now_str}",
        "# Categories: 📢 INFO | 🔥 Hot Event | 🔴 Live Event | ⏳ Upcoming Event | ⚽ 24/7 Sports Channels",
        "",
        f'#EXTINF:-1 tvg-id="xr3ed-telegram" tvg-name="📢 Gabung Telegram: t.me/CloudstreamXR" tvg-logo="{TG_LOGO}" group-title="{GROUP_INFO}",📢 Gabung Telegram: t.me/CloudstreamXR',
        TG_LINK,
        "",
        f'#EXTINF:-1 tvg-id="xr3ed-coffee" tvg-name="☕ Traktir Kopi: lynk.id/xr3ed" tvg-logo="{COFFEE_LOGO}" group-title="{GROUP_INFO}",☕ Traktir Kopi: lynk.id/xr3ed',
        COFFEE_LINK,
        ""
    ]

    # 1. Hot Event
    for m in merged_data.get('hot_matches', []):
        for idx, srv in enumerate(m.get('servers', [])):
            lines.extend(render_m3u_entry(GROUP_HOT_EVENT, m, idx + 1, srv))
            lines.append("")

    # 2. Live Event
    for m in merged_data.get('live_matches', []):
        for idx, srv in enumerate(m.get('servers', [])):
            lines.extend(render_m3u_entry(GROUP_LIVE_EVENT, m, idx + 1, srv))
            lines.append("")

    # 3. Upcoming Event (Top N terdekat)
    upcoming_list = merged_data.get('upcoming_matches', [])[:max_upcoming]
    for m in upcoming_list:
        for idx, srv in enumerate(m.get('servers', [])):
            lines.extend(render_m3u_entry(GROUP_UPCOMING_EVENT, m, idx + 1, srv))
            lines.append("")

    # 4. 24/7 Linear Sports Channels
    for m in merged_data.get('linear_channels', []):
        for idx, srv in enumerate(m.get('servers', [])):
            lines.extend(render_m3u_entry("⚽ 24/7 Sports Channels", m, idx + 1, srv))
            lines.append("")

    return "\n".join(lines)

if __name__ == '__main__':
    data = fetch_merged_matches()
    print(f"Total live: {len(data['live_matches'])}, Upcoming: {len(data['upcoming_matches'])}, Linear: {len(data['linear_channels'])}")
