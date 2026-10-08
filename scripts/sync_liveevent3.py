#!/usr/bin/env python3
"""
sync_liveevent3.py
===================
Sinkronisasi jadwal & direct stream Live Event 3 (xr3edtv-liveevent3.m3u).
Engine ini generik: seluruh URL target, struktur endpoint, aturan parsing,
dan fungsi decrypt murni dimuat dari environment variable / GitHub Secrets.
"""

import os
import sys
import json
import base64
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

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

def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def clean_env(val: str) -> str:
    return (val or '').strip().lstrip('\ufeff\uffef\u200b\u200c\u200d').strip()

# ─── Load Environment Variables (Murni tanpa hardcoded default) ─────────────
BASE_URL = clean_env(os.environ.get('EVENT3_BASE_URL', '')).rstrip('/')
ENDPOINTS_RAW = clean_env(os.environ.get('EVENT3_ENDPOINTS', ''))
PARSER_RULES_RAW = clean_env(os.environ.get('EVENT3_PARSER_RULES', ''))
DECRYPTOR_RAW = clean_env(os.environ.get('EVENT3_DECRYPTOR', ''))
HEADERS_RAW = clean_env(os.environ.get('EVENT3_HEADERS', ''))
OUTPUT_FILE = clean_env(os.environ.get('EVENT3_OUTPUT', '')) or 'xr3edtv-liveevent3.m3u'

if not BASE_URL or not ENDPOINTS_RAW or not PARSER_RULES_RAW or not DECRYPTOR_RAW:
    log("FATAL: Environment variables rahasia belum dikonfigurasi (EVENT3_*).")
    log("Pastikan EVENT3_BASE_URL, EVENT3_ENDPOINTS, EVENT3_PARSER_RULES, dan EVENT3_DECRYPTOR terisi.")
    sys.exit(1)

try:
    ENDPOINTS = json.loads(ENDPOINTS_RAW)
    if not isinstance(ENDPOINTS, list):
        raise ValueError("EVENT3_ENDPOINTS harus berupa JSON array.")
except Exception as e:
    log(f"FATAL: Gagal parsing EVENT3_ENDPOINTS: {e}")
    sys.exit(1)

try:
    RULES = json.loads(PARSER_RULES_RAW)
    if not isinstance(RULES, dict):
        raise ValueError("EVENT3_PARSER_RULES harus berupa JSON object.")
except Exception as e:
    log(f"FATAL: Gagal parsing EVENT3_PARSER_RULES: {e}")
    sys.exit(1)

HTTP_HEADERS = {}
if HEADERS_RAW:
    try:
        HTTP_HEADERS = json.loads(HEADERS_RAW)
    except Exception:
        HTTP_HEADERS = {'User-Agent': 'Mozilla/5.0'}
else:
    HTTP_HEADERS = {'User-Agent': 'Mozilla/5.0'}

# ─── Load Decryptor Function (Dynamic In-Memory) ─────────────────────────────
decrypt_stream = None
try:
    code_text = DECRYPTOR_RAW
    if 'def ' not in code_text and not code_text.strip().startswith('import'):
        # Coba decode base64 jika diberikan dalam format base64
        try:
            pad = code_text + '=' * (-len(code_text) % 4)
            code_text = base64.b64decode(pad).decode('utf-8')
        except Exception:
            pass

    scope = {}
    exec(code_text, scope)
    decrypt_stream = scope.get('extract_stream') or scope.get('decrypt') or scope.get('decode')
    if not callable(decrypt_stream):
        raise ValueError("Fungsi 'extract_stream', 'decrypt', atau 'decode' tidak ditemukan dalam modul decryptor.")
except Exception as e:
    log(f"FATAL: Gagal inisialisasi modul decryptor: {e}")
    sys.exit(1)

WIB = timezone(timedelta(hours=7))

GROUP_INFO = "📢 INFO"
GROUP_INDO = "🇮🇩 Indonesia"
GROUP_LIVE = "🔴 Live Event"
GROUP_UPCOMING = "⏳ Upcoming Event"

TG_LINK = "https://t.me/CloudstreamXR"
TG_LOGO = "https://raw.githubusercontent.com/xr3ed/xr3ed-tv/main/assets/telegram.png"
COFFEE_LINK = "https://lynk.id/xr3ed"
COFFEE_LOGO = "https://raw.githubusercontent.com/xr3ed/xr3ed-tv/main/assets/coffee.png"

SPORT_ICONS = {
    'soccer': 'football.png',
    'football': 'football.png',
    'basketball': 'basketball.png',
    'tennis': 'tennis.png',
    'badminton': 'badminton.png',
    'baseball': 'baseball.png',
    'volleyball': 'volleyball.png',
    'table tennis': 'sports.png',
    'handball': 'handball.png',
    'boxing': 'fighting.png',
    'mma': 'fighting.png',
    'fighting': 'fighting.png',
    'rugby': 'rugby.png',
    'american football': 'american_football.png',
    'motorsport': 'motorsport.png',
    'f1': 'motorsport.png',
    'futsal': 'football.png',
    'cycling': 'cycling.png',
    'golf': 'golf.png',
    'cricket': 'cricket.png',
}

def get_sport_icon(category_name: str) -> str:
    cat_lower = (category_name or '').lower()
    for k, v in SPORT_ICONS.items():
        if k in cat_lower:
            return f"https://raw.githubusercontent.com/xr3ed/xr3ed-tv/main/assets/sports/{v}"
    return "https://raw.githubusercontent.com/xr3ed/xr3ed-tv/main/assets/sports/sports.png"

def fetch_json(endpoint: str):
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    try:
        req = urllib.request.Request(url, headers=HTTP_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get('items', []) or data.get('data', [])
            return []
    except Exception as e:
        log(f"Gagal mengambil {endpoint}: {e}")
        return []

def parse_all_matches():
    log(f"Mengambil data dari {len(ENDPOINTS)} endpoint...")
    all_raw = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(fetch_json, ep): ep for ep in ENDPOINTS}
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                all_raw.extend(res)

    log(f"Total raw items didapat: {len(all_raw)}")

    name_k = RULES.get('name_key', 'name')
    cat_k = RULES.get('category_key', 'category')
    tourn_k = RULES.get('tournament_key', 'playing')
    time_k = RULES.get('time_key', 'time')
    ts_k = RULES.get('timestamp_key', 'timestamp')
    streams_k = RULES.get('streams_key', 'streams')
    url_k = RULES.get('url_key', 'url')
    stream_name_k = RULES.get('stream_name_key', 'name')
    indo_keywords = [k.lower() for k in RULES.get('indonesia_keywords', [])]

    now_ts = int(datetime.now(timezone.utc).timestamp())
    parsed_matches = {}

    for item in all_raw:
        if not isinstance(item, dict):
            continue

        raw_name = clean_env(str(item.get(name_k, '')))
        if not raw_name:
            continue

        # Normalisasi judul match untuk deduplikasi
        norm_key = " ".join(raw_name.lower().split())

        category = clean_env(str(item.get(cat_k, ''))) or 'Sports'
        tournament = clean_env(str(item.get(tourn_k, '')))
        time_str = clean_env(str(item.get(time_k, '')))
        ts_val = item.get(ts_k, 0)
        try:
            ts = int(ts_val) if ts_val else 0
            if ts > 1e11:  # Milliseconds ke seconds
                ts = ts // 1000
        except Exception:
            ts = 0

        # Ekstraksi stream URLs
        raw_streams = item.get(streams_k, [])
        valid_streams = []
        if isinstance(raw_streams, list):
            for s in raw_streams:
                if isinstance(s, dict):
                    u = s.get(url_k, '')
                    label = s.get(stream_name_k, 'Stream')
                elif isinstance(s, str):
                    u = s
                    label = 'Stream'
                else:
                    continue

                direct_url = decrypt_stream(u)
                if direct_url and (direct_url.startswith('http://') or direct_url.startswith('https://')):
                    valid_streams.append({'name': label, 'url': direct_url})

        if not valid_streams:
            continue

        if norm_key in parsed_matches:
            # Gabungkan stream tanpa duplikasi URL
            existing = parsed_matches[norm_key]
            exist_urls = {x['url'] for x in existing['streams']}
            for vs in valid_streams:
                if vs['url'] not in exist_urls:
                    existing['streams'].append(vs)
                    exist_urls.add(vs['url'])
            continue

        # Tentukan status live
        is_live = False
        time_lower = time_str.lower()
        if 'progress' in time_lower or 'live' in time_lower or "'" in time_lower or 'ht' in time_lower:
            is_live = True
        elif ts > 0:
            # Jika timestamp berada di rentang 2.5 jam lalu sampai 15 menit ke depan
            if (now_ts - 2.5 * 3600) <= ts <= (now_ts + 15 * 60):
                is_live = True

        # Tentukan Indonesia
        check_text = f"{raw_name} {tournament}".lower()
        is_indo = any(kw in check_text for kw in indo_keywords)

        logo = clean_env(str(item.get('image', '')))
        if not logo or not logo.startswith('http') or 'fav.png' in logo:
            logo = get_sport_icon(category)

        parsed_matches[norm_key] = {
            'name': raw_name,
            'category': category,
            'tournament': tournament,
            'time_str': time_str,
            'timestamp': ts,
            'is_live': is_live,
            'is_indo': is_indo,
            'logo': logo,
            'streams': valid_streams
        }

    return list(parsed_matches.values())

def generate_m3u(matches: list) -> str:
    now_wib = datetime.now(WIB).strftime('%Y-%m-%d %H:%M')
    lines = [
        "#EXTM3U",
        f"# XR3ED LIVE SPORTS PLAYLIST (LIVE EVENT 3) — Updated: {now_wib} WIB",
        "# Categories: 📢 INFO | 🇮🇩 Indonesia | 🔴 Live Event | ⏳ Upcoming Event",
        "",
        f'#EXTINF:-1 tvg-id="xr3ed-telegram" tvg-name="📢 Gabung Telegram: t.me/CloudstreamXR" tvg-logo="{TG_LOGO}" group-title="{GROUP_INFO}",📢 Gabung Telegram: t.me/CloudstreamXR',
        TG_LINK,
        "",
        f'#EXTINF:-1 tvg-id="xr3ed-coffee" tvg-name="☕ Traktir Kopi: lynk.id/xr3ed" tvg-logo="{COFFEE_LOGO}" group-title="{GROUP_INFO}",☕ Traktir Kopi: lynk.id/xr3ed',
        COFFEE_LINK,
        ""
    ]

    indo_matches = []
    live_matches = []
    upcoming_matches = []

    for m in matches:
        if m['is_indo']:
            indo_matches.append(m)
        elif m['is_live']:
            live_matches.append(m)
        else:
            upcoming_matches.append(m)

    # Sort upcoming by timestamp
    upcoming_matches.sort(key=lambda x: x['timestamp'] if x['timestamp'] > 0 else 9999999999)

    ua_header = HTTP_HEADERS.get('User-Agent', 'Mozilla/5.0')

    def add_match_entries(m_list, group_title, prefix_status):
        for m in m_list:
            match_name = m['name']
            tournament = m['tournament']
            logo = m['logo']

            time_label = ""
            if prefix_status == 'LIVE':
                time_label = "🔴 LIVE"
            elif m['timestamp'] > 0:
                match_dt = datetime.fromtimestamp(m['timestamp'], tz=WIB)
                time_label = f"⏳ {match_dt.strftime('%d/%m %H:%M')} WIB"
            elif m['time_str']:
                time_label = f"⏳ {m['time_str']}"

            title_parts = []
            if tournament:
                title_parts.append(f"[{tournament}]")
            title_parts.append(match_name)
            if time_label:
                title_parts.append(f"• {time_label}")

            base_title = " ".join(title_parts)

            for idx, stream in enumerate(m['streams']):
                server_num = idx + 1
                server_label = f" [Server {server_num}]" if len(m['streams']) > 1 else ""
                entry_title = f"{base_title}{server_label}"

                stream_url = stream['url']
                lines.append(f'#EXTINF:-1 tvg-id="event3-{abs(hash(match_name)) % 10000000}" tvg-name="{entry_title}" tvg-logo="{logo}" group-title="{group_title}",{entry_title}')
                lines.append(f'#EXTVLCOPT:http-user-agent={ua_header}')
                lines.append(stream_url)
                lines.append("")

    if indo_matches:
        add_match_entries(indo_matches, GROUP_INDO, 'INDO')
    if live_matches:
        add_match_entries(live_matches, GROUP_LIVE, 'LIVE')
    if upcoming_matches:
        add_match_entries(upcoming_matches, GROUP_UPCOMING, 'UPCOMING')

    return "\n".join(lines)

def main():
    log("=== Sinkronisasi Live Event 3 Dimulai ===")
    matches = parse_all_matches()
    log(f"Pertandingan tervalidasi dengan stream: {len(matches)}")

    m3u_content = generate_m3u(matches)

    if os.path.basename(script_dir) == 'scripts':
        out_path = os.path.normpath(os.path.join(script_dir, '..', OUTPUT_FILE))
    else:
        out_path = os.path.normpath(os.path.join(script_dir, OUTPUT_FILE))

    with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(m3u_content)

    total_streams = m3u_content.count('http://') + m3u_content.count('https://') - 2
    size_kb = os.path.getsize(out_path) / 1024
    log(f"Playlist berhasil disimpan ke: {out_path} ({size_kb:.1f} KB, {total_streams} streams)")
    log("=== Sinkronisasi Live Event 3 Selesai ===")

if __name__ == '__main__':
    main()
