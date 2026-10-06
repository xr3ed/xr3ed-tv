#!/usr/bin/env python3
"""
sync_rbtv.py
=============
Otomatisasi sinkronisasi jadwal & stream pertandingan RBTV+:
- 🇮🇩 Indonesia (Semua match Indonesia, baik Live maupun Upcoming)
- 🔴 Live Event (Match non-Indo yang sedang berlangsung)
- ⏳ Upcoming Event (Match non-Indo yang akan segera tayang)

Stream di-resolve secara on-demand via Cloudflare Worker resolver (xr3ed-edge).
"""

import os
import sys
import json
import re
import time
import gzip
import base64
import hashlib
import urllib.parse
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    AESGCM = None

script_dir = os.path.dirname(os.path.abspath(__file__))
env_file = os.path.normpath(os.path.join(script_dir, '..', '.env'))
try:
    from dotenv import load_dotenv
    if os.path.exists(env_file):
        load_dotenv(env_file, override=True, interpolate=False)
    else:
        load_dotenv(override=True, interpolate=False)
except ImportError:
    pass

sys.stdout.reconfigure(encoding='utf-8')

def clean_env(val: str) -> str:
    return (val or '').strip().lstrip('\ufeff\uffef\u200b\u200c\u200d').strip()

# ─── Konfigurasi & Secret (Murni dibaca dari GitHub Secrets / .env lokal) ────
RBTV_MAIN_URL = clean_env(os.environ.get('RBTV_MAIN_URL', '')).rstrip('/')
RBTV_API_HOST = clean_env(os.environ.get('RBTV_API_HOST', '')).rstrip('/')
RBTV_GIST_URL = clean_env(os.environ.get('RBTV_GIST_URL', ''))
RBTV_PATH_BS = clean_env(os.environ.get('RBTV_PATH_BS', ''))
RBTV_PATH_LIVE = clean_env(os.environ.get('RBTV_PATH_LIVE', ''))
RBTV_PATH_DETAIL = clean_env(os.environ.get('RBTV_PATH_DETAIL', ''))
RBTV_USER_AGENT = clean_env(os.environ.get('RBTV_USER_AGENT', ''))
RBTV_STREAM_REFERER = clean_env(os.environ.get('RBTV_STREAM_REFERER', ''))
RBTV_POSTER_URL = clean_env(os.environ.get('RBTV_POSTER_URL', ''))
RBTV_RESOLVER_URL = clean_env(os.environ.get('RBTV_RESOLVER_URL', '')).rstrip('/')
WORKER_AUTH_KEY = clean_env(os.environ.get('WORKER_AUTH_KEY', ''))
OUTPUT_FILE = clean_env(os.environ.get('RBTV_OUTPUT', 'xr3edtv-liveevent2.m3u')) or 'xr3edtv-liveevent2.m3u'

WIB = timezone(timedelta(hours=7))

GROUP_INFO = "📢 INFO"
GROUP_INDO = "🇮🇩 Indonesia"
GROUP_LIVE = "🔴 Live Event"
GROUP_UPCOMING = "⏳ Upcoming Event"

TG_LINK = "https://t.me/CloudstreamXR"
TG_LOGO = "https://raw.githubusercontent.com/xr3ed/xr3ed-tv/main/assets/telegram.png"
COFFEE_LINK = "https://lynk.id/xr3ed"
COFFEE_LOGO = "https://raw.githubusercontent.com/xr3ed/xr3ed-tv/main/assets/coffee.png"

SPORT_NAMES = {
    1: "Sepak Bola", 2: "Basket", 3: "Tenis", 4: "Bisbol", 6: "Kriket",
    7: "Motorsport", 8: "Rugby", 9: "Am.Football", 10: "AussieRules",
    12: "Bulutangkis", 13: "Voli", 14: "Fighting", 15: "Balap Sepeda",
    16: "Handball", 90: "Golf"
}

STATUS_NAMES = {
    0: "Coming", 1: "Live", 100: "FTB Live", 101: "Babak 1", 102: "HT",
    103: "Babak 2", 104: "Extra Time", 105: "Penalti",
    200: "BSK Live", 201: "Q1", 202: "Q2", 203: "Q3", 204: "Q4",
    300: "TNS Live", 400: "Baseball Live", 600: "Cricket Live",
    700: "Motorsport Live", 800: "Rugby Live", 900: "AmFootball Live",
    1000: "AussieRules Live", 1200: "BMT Live", 1300: "Voli Live",
    1400: "Fighting Live", 1500: "Cycling Live", 1600: "Handball Live",
    9000: "Other Live"
}

ONGOING_STATUSES = {
    1, 100, 101, 102, 103, 104, 105, 200, 201, 202, 203, 204, 211, 212, 213, 214,
    300, 400, 600, 700, 800, 900, 1000, 1100, 1200, 1300, 1400, 1500, 1600, 9000
}

INDONESIA_KEYWORDS = [
    'indonesia', 'piala presiden', 'piala aff', 'aff cup',
    'persija', 'persib', 'persebaya', 'bali united', 'timnas'
]

def log(msg):
    now_str = datetime.now(WIB).strftime('%H:%M:%S')
    print(f"[{now_str}] {msg}", flush=True)

def md5_hex(s: str) -> str:
    return hashlib.md5(s.encode('utf-8')).hexdigest()

def read_varint(data: bytes, idx: int):
    val, shift = 0, 0
    while idx < len(data):
        b = data[idx]
        idx += 1
        val |= (b & 0x7f) << shift
        if (b & 0x80) == 0:
            break
        shift += 7
    return val, idx

def skip_field(data: bytes, idx: int, wire: int) -> int:
    if wire == 0:
        _, idx = read_varint(data, idx)
    elif wire == 1:
        idx += 8
    elif wire == 2:
        length, idx = read_varint(data, idx)
        idx += length
    elif wire == 5:
        idx += 4
    return idx

def read_string(data: bytes, idx: int):
    length, idx = read_varint(data, idx)
    return data[idx:idx + length].decode('utf-8', errors='ignore'), idx + length

def parse_match_basic(mdata: bytes) -> dict:
    idx = 0
    match_id = match_status = match_time = sport_type = 0
    teams = []
    team_logos = []
    league_name = None
    league_logo = None
    match_title = None
    while idx < len(mdata):
        try:
            key, idx = read_varint(mdata, idx)
            tag, wire = key >> 3, key & 7
            if tag == 1 and wire == 0:
                match_id, idx = read_varint(mdata, idx)
            elif tag == 2 and wire == 0:
                sport_type, idx = read_varint(mdata, idx)
            elif tag == 3 and wire == 0:
                match_time, idx = read_varint(mdata, idx)
            elif tag == 4 and wire == 0:
                match_status, idx = read_varint(mdata, idx)
            elif tag == 10 and wire == 2:
                length, idx = read_varint(mdata, idx)
                ldata = mdata[idx:idx + length]
                idx += length
                li = 0
                while li < len(ldata):
                    lk, li = read_varint(ldata, li)
                    lt, lw = lk >> 3, lk & 7
                    if lt == 3 and lw == 2:
                        l2, li = read_varint(ldata, li)
                        sub = ldata[li:li + l2]
                        li += l2
                        si = 0
                        while si < len(sub):
                            sk, si = read_varint(sub, si)
                            st, sw = sk >> 3, sk & 7
                            if st == 2 and sw == 2:
                                league_name, si = read_string(sub, si)
                                break
                            else:
                                si = skip_field(sub, si, sw)
                    elif lt == 4 and lw == 2:
                        league_logo, li = read_string(ldata, li)
                    elif lt == 80 and lw == 2:
                        l80, li = read_varint(ldata, li)
                        sub80 = ldata[li:li + l80]
                        li += l80
                        s80i = 0
                        while s80i < len(sub80):
                            s80k, s80i = read_varint(sub80, s80i)
                            s80t, s80w = s80k >> 3, s80k & 7
                            if s80t == 4 and s80w == 2:
                                if not league_logo:
                                    league_logo, s80i = read_string(sub80, s80i)
                                else:
                                    s80i = skip_field(sub80, s80i, s80w)
                            else:
                                s80i = skip_field(sub80, s80i, s80w)
                    else:
                        li = skip_field(ldata, li, lw)
            elif tag == 30 and wire == 2:
                cl, idx = read_varint(mdata, idx)
                cdata = mdata[idx:idx + cl]
                idx += cl
                ci = 0
                while ci < len(cdata):
                    ck, ci = read_varint(cdata, ci)
                    ct, cw = ck >> 3, ck & 7
                    if ct == 2 and cw == 2:
                        s_title, ci = read_string(cdata, ci)
                        if not match_title:
                            match_title = s_title
                    elif ct in (10, 20) and cw == 2:
                        tl, ci = read_varint(cdata, ci)
                        tdata = cdata[ci:ci + tl]
                        ci += tl
                        ti = 0
                        tname = None
                        tlogo = None
                        while ti < len(tdata):
                            tk, ti = read_varint(tdata, ti)
                            tt, tw = tk >> 3, tk & 7
                            if tt == 3 and tw == 2:
                                sl, ti = read_varint(tdata, ti)
                                sub = tdata[ti:ti + sl]
                                ti += sl
                                si = 0
                                while si < len(sub):
                                    sk, si = read_varint(sub, si)
                                    st, sw = sk >> 3, sk & 7
                                    if st == 2 and sw == 2:
                                        tname, si = read_string(sub, si)
                                        break
                                    else:
                                        si = skip_field(sub, si, sw)
                            elif tt == 4 and tw == 2:
                                tlogo, ti = read_string(tdata, ti)
                            else:
                                ti = skip_field(tdata, ti, tw)
                        if tname:
                            teams.append(tname)
                        if tlogo:
                            team_logos.append(tlogo)
                    else:
                        ci = skip_field(cdata, ci, cw)
            else:
                idx = skip_field(mdata, idx, wire)
        except Exception:
            break
    return {
        'id': match_id,
        'status': match_status,
        'time': match_time,
        'sport': sport_type,
        'teams': teams,
        'team_logos': team_logos,
        'league': league_name or "",
        'league_logo': league_logo,
        'match_title': match_title or ""
    }

def parse_api_response(data: bytes, sport_type_hint: int = 0) -> list:
    matches = []
    idx = 0
    while idx < len(data):
        try:
            key, idx = read_varint(data, idx)
            tag, wire = key >> 3, key & 7
            if tag == 10 and wire == 2:
                length, idx = read_varint(data, idx)
                block = data[idx:idx + length]
                idx += length
                bi = 0
                while bi < len(block):
                    bk, bi = read_varint(block, bi)
                    bt, bw = bk >> 3, bk & 7
                    if bt == 1 and bw == 2:
                        ml, bi = read_varint(block, bi)
                        mdata = block[bi:bi + ml]
                        bi += ml
                        m = parse_match_basic(mdata)
                        if m['id'] > 0:
                            if m['sport'] == 0:
                                m['sport'] = sport_type_hint
                            matches.append(m)
                    else:
                        bi = skip_field(block, bi, bw)
                break
            elif wire == 2:
                l, idx = read_varint(data, idx)
                idx += l
            else:
                _, idx = read_varint(data, idx)
        except Exception:
            break
    return matches

def parse_detail_streams(data: bytes) -> list:
    idx = 0
    detail_payload = None
    while idx < len(data):
        try:
            key, idx = read_varint(data, idx)
            tag, wire = key >> 3, key & 7
            if tag == 10 and wire == 2:
                length, idx = read_varint(data, idx)
                detail_payload = data[idx:idx + length]
                break
            else:
                idx = skip_field(data, idx, wire)
        except Exception:
            break

    streams = []
    if detail_payload:
        dp_idx = 0
        while dp_idx < len(detail_payload):
            try:
                key, dp_idx = read_varint(detail_payload, dp_idx)
                tag, wire = key >> 3, key & 7
                if tag == 2 and wire == 2:
                    length, dp_idx = read_varint(detail_payload, dp_idx)
                    stream_bytes = detail_payload[dp_idx:dp_idx + length]
                    dp_idx += length

                    s_id = 0
                    s_site_type = 2001
                    s_name = ""
                    sp_idx = 0
                    while sp_idx < len(stream_bytes):
                        skey, sp_idx = read_varint(stream_bytes, sp_idx)
                        stag, swire = skey >> 3, skey & 7
                        if stag == 1 and swire == 0:
                            s_id, sp_idx = read_varint(stream_bytes, sp_idx)
                        elif stag == 9 and swire == 0:
                            s_site_type, sp_idx = read_varint(stream_bytes, sp_idx)
                        elif stag == 3 and swire == 2:
                            s_name, sp_idx = read_string(stream_bytes, sp_idx)
                        else:
                            sp_idx = skip_field(stream_bytes, sp_idx, swire)
                    if s_id > 0:
                        streams.append({'id': s_id, 'siteType': s_site_type, 'name': s_name})
                else:
                    dp_idx = skip_field(detail_payload, dp_idx, wire)
            except Exception:
                break
    return streams

def is_indonesia_match(title: str, league: str, home: str, away: str) -> bool:
    combined = f"{title} {league} {home} {away}".lower()
    return any(kw in combined for kw in INDONESIA_KEYWORDS)

def get_sport_max_duration_ms(sport_id: int) -> int:
    durations = {
        1: 130 * 60 * 1000,   # Sepak Bola: 130 menit (persis plugin)
        2: 160 * 60 * 1000,   # Basket: 160 menit
        3: 300 * 60 * 1000,   # Tenis: 300 menit
        4: 240 * 60 * 1000,   # Bisbol: 240 menit
        6: 480 * 60 * 1000,   # Kriket: 480 menit
        7: 210 * 60 * 1000,   # Motorsport: 210 menit
        8: 120 * 60 * 1000,   # Rugby: 120 menit
        12: 180 * 60 * 1000,  # Bulutangkis: 180 menit
        13: 180 * 60 * 1000,  # Voli: 180 menit
        14: 360 * 60 * 1000,  # Fighting: 360 menit
        15: 480 * 60 * 1000,  # Balap Sepeda: 480 menit
        16: 180 * 60 * 1000,  # Handball: 180 menit
        90: 480 * 60 * 1000   # Golf: 480 menit
    }
    return durations.get(sport_id, 180 * 60 * 1000)

def encrypt_match_id(payload: str, secret: str) -> str:
    if not secret:
        return ""
    if not AESGCM:
        return base64.urlsafe_b64encode(payload.encode('utf-8')).decode('utf-8').rstrip('=')
    key = hashlib.sha256(secret.encode('utf-8')).digest()
    aesgcm = AESGCM(key)
    iv = os.urandom(12)
    ct = aesgcm.encrypt(iv, payload.encode('utf-8'), None)
    return base64.urlsafe_b64encode(iv + ct).decode('utf-8').rstrip('=')

SPORT_FALLBACK_SLUGS = {
    1: "football",
    2: "basketball",
    3: "tennis",
    4: "baseball",
    6: "cricket",
    7: "motorsport",
    8: "rugby",
    9: "american_football",
    10: "aussierules",
    12: "badminton",
    13: "volleyball",
    14: "fighting",
    15: "cycling",
    16: "handball",
    90: "golf",
}
DEFAULT_SPORT_SLUG = "sports"
SPORT_POSTER_BASE_URL = "https://raw.githubusercontent.com/xr3ed/xr3ed-tv/main/assets/sports"

def get_sport_fallback_url(sport_type: int) -> str:
    slug = SPORT_FALLBACK_SLUGS.get(sport_type, DEFAULT_SPORT_SLUG)
    return f"{SPORT_POSTER_BASE_URL}/{slug}.png"

def resolve_logo_url(raw_logo: str, api_host: str, main_url: str) -> str:
    if not raw_logo:
        return ""
    active_logo_host = ""
    if api_host:
        try:
            parsed = urllib.parse.urlparse(api_host)
            host = parsed.netloc or ""
            if '.' in host:
                base = host.split('.', 1)[1]
                active_logo_host = f"https://logos1.{base}"
        except Exception:
            pass

    domain = main_url
    if "/aelogo/" in raw_logo:
        path = raw_logo.split("/aelogo/", 1)[1]
        return f"{active_logo_host}/aelogo/{path}" if active_logo_host else raw_logo
    if raw_logo.startswith("http://") or raw_logo.startswith("https://"):
        return raw_logo
    if raw_logo.startswith("//"):
        return f"https:{raw_logo}"
    if domain:
        if raw_logo.startswith("/"):
            return f"{domain}{raw_logo}"
        return f"{domain}/{raw_logo}"
    return raw_logo

def select_match_poster(m: dict, api_host: str, main_url: str) -> str:
    # 1. Ambil poster Tim A (Home) jika ada, fallback ke tim berikutnya jika ada
    team_logos = m.get('team_logos') or []
    for tl in team_logos:
        if tl:
            resolved = resolve_logo_url(tl, api_host, main_url)
            if resolved:
                return resolved

    # 2. Jika tidak ada logo tim / single event, ambil logo kompetisi/liga
    league_logo = m.get('league_logo')
    if league_logo:
        resolved = resolve_logo_url(league_logo, api_host, main_url)
        if resolved:
            return resolved

    # 3. Fallback sesuai jenis olahraga
    return get_sport_fallback_url(m.get('sport', 0))

def build_poster_url(base_url: str, sport: str, league: str, home: str, away: str,
                     time_str: str, countdown: str, phase: str, is_live: bool,
                     is_indo: bool, is_solo: bool) -> str:
    if not base_url:
        return ""
    params = [('sport', sport)]
    if league: params.append(('league', league))
    if home: params.append(('home', home))
    if not is_solo and away: params.append(('away', away))
    if time_str: params.append(('time', time_str))
    if countdown: params.append(('countdown', countdown))
    if phase: params.append(('phase', phase))
    if is_live: params.append(('live', '1'))
    if is_indo: params.append(('indo', '1'))
    if is_solo: params.append(('solo', '1'))
    qs = urllib.parse.urlencode(params)
    sep = '&' if '?' in base_url else '?'
    return f"{base_url}{sep}{qs}"

def fetch_url(url: str, headers: dict = None, timeout: int = 15) -> bytes:
    h = {'User-Agent': RBTV_USER_AGENT or 'Mozilla/5.0'}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        if data.startswith(b'\x1f\x8b'):
            try:
                data = gzip.decompress(data)
            except Exception:
                pass
        return data

def get_or_resolve_main_url() -> str:
    if RBTV_GIST_URL:
        try:
            content = fetch_url(RBTV_GIST_URL, timeout=8).decode('utf-8', errors='ignore')
            data = json.loads(content)
            if data.get('active_domain'):
                return data['active_domain'].rstrip('/')
        except Exception:
            pass
    return RBTV_MAIN_URL

def get_api_host(main_url: str) -> str:
    if not main_url:
        return RBTV_API_HOST
    try:
        page_url = main_url if main_url.endswith('/id') or main_url.endswith('/id/') else f"{main_url.rstrip('/')}/id/"
        content = fetch_url(page_url, timeout=10).decode('utf-8', errors='ignore')
        js_urls = re.findall(r"https://statics1\.[a-zA-Z0-9.-]+/[^\x22\x27\s]+\.js", content)
        for js_url in set(js_urls):
            try:
                js_content = fetch_url(js_url, timeout=8).decode('utf-8', errors='ignore')
                m = re.search(r"CF_DA_API['\"]?\s*:\s*['\"]?(https://apis-data[0-9]*\.[a-zA-Z0-9.-]+)", js_content)
                if m:
                    return m.group(1).rstrip('/')
            except Exception:
                pass
    except Exception:
        pass
    return RBTV_API_HOST

def get_bs_token(api_host: str, main_url: str, sport_type: int) -> str:
    if not RBTV_PATH_BS or not api_host:
        return ""
    url = f"{api_host}{RBTV_PATH_BS}?code=100&code=101&stream=true&sportType={sport_type}&language=34"
    origin = main_url
    if main_url:
        try:
            p = urllib.parse.urlparse(main_url)
            origin = f"{p.scheme}://{p.netloc}"
        except Exception:
            pass
    headers = {
        'Referer': f"{main_url}/" if not main_url.endswith('/') else main_url,
        'Origin': origin,
        'Accept': 'application/json, text/plain, */*'
    }
    try:
        data = fetch_url(url, headers=headers, timeout=10)
        marker = bytes([8, 100, 18, 32])
        for i in range(len(data) - len(marker)):
            if data[i:i + len(marker)] == marker:
                return data[i + 4:i + 4 + 32].decode('utf-8', errors='ignore')
    except Exception:
        pass
    return ""

def fetch_sport_matches(api_host: str, main_url: str, sport_type: int) -> list:
    token = get_bs_token(api_host, main_url, sport_type)
    if not token or not RBTV_PATH_LIVE:
        return []
    jp = f'{{"sportType":{sport_type},"language":34,"stream":true}}'
    sfver = f"sfver{md5_hex(jp)[:6]}{token}"
    url = f"{api_host}/{sfver}{RBTV_PATH_LIVE}?sportType={sport_type}&language=34&stream=true"
    origin = main_url
    if main_url:
        try:
            p = urllib.parse.urlparse(main_url)
            origin = f"{p.scheme}://{p.netloc}"
        except Exception:
            pass
    headers = {
        'Referer': f"{main_url}/" if not main_url.endswith('/') else main_url,
        'Origin': origin,
        'Accept': 'application/json, text/plain, */*'
    }
    try:
        data = fetch_url(url, headers=headers, timeout=12)
        return parse_api_response(data, sport_type)
    except Exception:
        return []

def fetch_match_streams_count(api_host: str, main_url: str, match_id: int, sport_type: int) -> int:
    token = get_bs_token(api_host, main_url, sport_type)
    if not token or not RBTV_PATH_DETAIL:
        return 1
    jp = f'{{"matchId":{match_id},"sportType":{sport_type},"language":34}}'
    sfver = f"sfver{md5_hex(jp)[:6]}{token}"
    url = f"{api_host}/{sfver}{RBTV_PATH_DETAIL}?matchId={match_id}&sportType={sport_type}&language=34"
    origin = main_url
    if main_url:
        try:
            p = urllib.parse.urlparse(main_url)
            origin = f"{p.scheme}://{p.netloc}"
        except Exception:
            pass
    headers = {
        'Referer': f"{main_url}/" if not main_url.endswith('/') else main_url,
        'Origin': origin,
        'Accept': 'application/json, text/plain, */*'
    }
    try:
        data = fetch_url(url, headers=headers, timeout=8)
        streams = parse_detail_streams(data)
        return max(1, len(streams))
    except Exception:
        return 1

def main():
    log("Memulai sinkronisasi playlist RBTV+ (xr3edtv-liveevent2.m3u)...")
    now_ms = int(time.time() * 1000)

    main_url = get_or_resolve_main_url()
    api_host = get_api_host(main_url)
    log(f"Upstream Main URL: {main_url}")
    log(f"Upstream API Host: {api_host}")

    if not api_host:
        log("ERROR: API Host tidak ditemukan. Keluar.")
        return

    # Ambil Gist Live & Upcoming Match IDs jika ada
    gist_live_ids = set()
    gist_upcoming_ids = set()
    if RBTV_GIST_URL:
        try:
            content = fetch_url(RBTV_GIST_URL, timeout=8).decode('utf-8', errors='ignore')
            gdata = json.loads(content)
            for gm in gdata.get('matches', []):
                mid = gm.get('matchId')
                if not mid:
                    continue
                g_status = gm.get('status', 0)
                if g_status in ONGOING_STATUSES:
                    gist_live_ids.add(mid)
                else:
                    gist_upcoming_ids.add(mid)
            log(f"Loaded from Gist: {len(gist_live_ids)} live IDs, {len(gist_upcoming_ids)} upcoming IDs")
        except Exception as e:
            log(f"Warning: Gagal membaca Gist: {e}")

    # Fetch semua cabang olahraga secara paralel
    sport_types = [1, 2, 3, 4, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 90]
    all_matches_map = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fetch_sport_matches, api_host, main_url, st): st for st in sport_types}
        for future in as_completed(futures):
            st = futures[future]
            try:
                matches = future.result()
                for m in matches:
                    if m['id'] > 0 and m['id'] not in all_matches_map:
                        all_matches_map[m['id']] = m
            except Exception as e:
                log(f"Error fetching sport {st}: {e}")

    log(f"Total pertandingan ditemukan dari API: {len(all_matches_map)}")

    # Klasifikasi ke 3 Grup
    indo_matches = []
    live_matches = []
    upcoming_matches = []

    for m in all_matches_map.values():
        status = m.get('status', 0)
        if status >= 10000:
            continue  # Selesai / batal

        m_time = m.get('time', 0)
        sport = m.get('sport', 1)
        teams = m.get('teams', [])
        league = m.get('league', '')
        match_title = m.get('match_title', '').strip()
        home = ""
        away = ""

        if len(teams) == 2:
            home = teams[0].strip()
            away = teams[1].strip()
            title = f"{home} vs {away}"
        elif len(teams) == 4:
            home = f"{teams[0]} / {teams[2]}".strip()
            away = f"{teams[1]} / {teams[3]}".strip()
            title = f"{home} vs {away}"
        elif match_title:
            title = match_title
            if ' vs ' in match_title:
                parts = match_title.split(' vs ', 1)
                home, away = parts[0].strip(), parts[1].strip()
        elif len(teams) == 1:
            home = teams[0].strip()
            title = home
        elif league:
            title = league
        else:
            title = f"Match {m['id']}"

        is_indo = is_indonesia_match(title, league, home, away)

        # Match yang waktu mulainya masih di masa depan (> 5 menit lagi) tidak boleh dianggap Live
        is_future = (m_time > 0 and m_time > (now_ms + 5 * 60 * 1000))
        if is_future:
            is_live = False
        else:
            is_live = (status in ONGOING_STATUSES) or (m['id'] in gist_live_ids and status < 10000)

        m_item = {
            **m,
            'home': home,
            'away': away,
            'title': title,
            'league': league,
            'is_indo': is_indo,
            'is_live': is_live
        }

        if is_indo:
            indo_matches.append(m_item)
        elif is_live:
            live_matches.append(m_item)
        else:
            # Upcoming: ada di Gist atau mulai dalam 12 jam ke depan
            if (m['id'] in gist_upcoming_ids) or (0 < m_time <= now_ms + 12 * 3600 * 1000):
                upcoming_matches.append(m_item)

    # Sort logic: Live (Sepak bola -> waktu terbaru di atas), Upcoming (urutan waktu kickoff terdekat)
    def live_sort_key(item):
        sport_score = 0 if item['sport'] == 1 else 1
        time_score = -item['time'] if item['time'] > 0 else 0
        return (sport_score, time_score)

    def upcoming_sort_key(item):
        time_score = item['time'] if item['time'] > 0 else 9999999999999
        sport_score = 0 if item['sport'] == 1 else 1
        return (time_score, sport_score)

    indo_matches.sort(key=live_sort_key)
    live_matches.sort(key=live_sort_key)
    upcoming_matches.sort(key=upcoming_sort_key)

    log(f"Hasil filter: Indonesia={len(indo_matches)}, Live={len(live_matches)}, Upcoming={len(upcoming_matches)}")

    # Ambil jumlah stream untuk pertandingan yang Live secara paralel
    active_matches_to_probe = [m for m in (indo_matches + live_matches) if m['is_live']]
    stream_counts = {}
    if active_matches_to_probe:
        with ThreadPoolExecutor(max_workers=5) as executor:
            fut_map = {executor.submit(fetch_match_streams_count, api_host, main_url, m['id'], m['sport']): m['id'] for m in active_matches_to_probe}
            for fut in as_completed(fut_map):
                mid = fut_map[fut]
                try:
                    stream_counts[mid] = fut.result()
                except Exception:
                    stream_counts[mid] = 1

    # Tulis playlist M3U
    m3u_lines = [
        "#EXTM3U",
        f"# XR3ED LIVE SPORTS PLAYLIST (RBTV+) — Updated: {datetime.now(WIB).strftime('%Y-%m-%d %H:%M')} WIB",
        "# Categories: 📢 INFO | 🇮🇩 Indonesia | 🔴 Live Event | ⏳ Upcoming Event",
        "",
        f'#EXTINF:-1 tvg-id="xr3ed-telegram" tvg-name="📢 Gabung Telegram: t.me/CloudstreamXR" tvg-logo="{TG_LOGO}" group-title="{GROUP_INFO}",📢 Gabung Telegram: t.me/CloudstreamXR',
        TG_LINK,
        "",
        f'#EXTINF:-1 tvg-id="xr3ed-coffee" tvg-name="☕ Traktir Kopi: lynk.id/xr3ed" tvg-logo="{COFFEE_LOGO}" group-title="{GROUP_INFO}",☕ Traktir Kopi: lynk.id/xr3ed',
        COFFEE_LINK,
        ""
    ]

    def render_match(m, group_name):
        time_wib = datetime.fromtimestamp(m['time'] / 1000, WIB).strftime("%H:%M") if m['time'] > 0 else "?"
        poster_url = select_match_poster(m, api_host, main_url)

        league_prefix = f"[{m['league']}] " if m['league'] and not m['title'].lower().startswith(m['league'].lower()) else ""
        time_suffix = f" • 🔴 LIVE" if m['is_live'] else f" • {time_wib} WIB"
        base_title = f"{league_prefix}{m['title']}{time_suffix}"

        server_count = stream_counts.get(m['id'], 1)
        for s_idx in range(server_count):
            server_suffix = f" [Server {s_idx + 1}]" if server_count > 1 else " [Server 1]"
            full_title = f"{base_title}{server_suffix}"
            tvg_id = f"rbtv-{m['id']}"

            logo_attr = f' tvg-logo="{poster_url}"' if poster_url else ''
            m3u_lines.append(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{full_title}"{logo_attr} group-title="{group_name}",{full_title}')
            if RBTV_STREAM_REFERER:
                m3u_lines.append(f"#EXTVLCOPT:http-referrer={RBTV_STREAM_REFERER}")
            if RBTV_USER_AGENT:
                m3u_lines.append(f"#EXTVLCOPT:http-user-agent={RBTV_USER_AGENT}")

            # Token enkripsi untuk worker resolver
            token_payload = f"{m['id']}:{m['sport']}"
            enc_token = encrypt_match_id(token_payload, WORKER_AUTH_KEY)
            resolver_base = RBTV_RESOLVER_URL
            stream_url = f"{resolver_base}/live/{enc_token}.m3u8?s={s_idx}"
            m3u_lines.append(stream_url)
            m3u_lines.append("")

    for m in indo_matches:
        render_match(m, GROUP_INDO)

    for m in live_matches:
        render_match(m, GROUP_LIVE)

    for m in upcoming_matches:
        render_match(m, GROUP_UPCOMING)

    output_path = os.path.normpath(os.path.join(script_dir, '..', OUTPUT_FILE))
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(m3u_lines))

    log(f"Berhasil menulis {len(m3u_lines)} baris ke {output_path}")

if __name__ == '__main__':
    main()
