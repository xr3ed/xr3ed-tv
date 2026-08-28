#!/usr/bin/env python3
"""
sync_liveevent.py
==================
Otomatisasi sinkronisasi jadwal & stream pertandingan langsung:
- 🔥 Hot Event (Hanya Hot Matches yang SEDANG LIVE)
- 🔴 Live Event (Semua match yang sedang berlangsung / On The Air)
- ⏳ Upcoming Event (10 match mendatang terdekat dengan stream)

Setiap stream dikonversi 100% ke direct HLS CDN (enewl.greenvora.net)
sehingga tidak pernah menggunakan placeholder twinspeed.space yang unresolvable.
"""

import os
import sys
import json
import re
import urllib.parse
import urllib.request
import urllib.error
import http.cookiejar
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

script_dir = os.path.dirname(os.path.abspath(__file__))
env_file = os.path.normpath(os.path.join(script_dir, '..', '.env'))
try:
    from dotenv import load_dotenv
    if os.path.exists(env_file):
        load_dotenv(env_file, override=True)
    else:
        load_dotenv(override=True)
except ImportError:
    pass

sys.stdout.reconfigure(encoding='utf-8')

# ─── Konfigurasi & Secret (Dibaca dari GitHub Secrets / .env lokal) ───────────

SRC_URL = os.environ.get('LIVEEVENT_SRC_URL', '').rstrip('/')
REF_URL = os.environ.get('LIVEEVENT_REF_URL', '').rstrip('/')
if REF_URL and not REF_URL.endswith('/'):
    REF_URL += '/'
CDN_BASE = os.environ.get('LIVEEVENT_CDN_BASE', '').rstrip('/')
OUTPUT_FILE = os.environ.get('LIVEEVENT_OUTPUT', 'xr3edtv-liveevent.m3u').strip()

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
WIB = timezone(timedelta(hours=7))

GROUP_INFO = "📢 INFO"
GROUP_HOT = "🔥 Hot Event"
GROUP_LIVE = "🔴 Live Event"
GROUP_UPCOMING = "⏳ Upcoming Event"

TG_LINK = "https://t.me/CloudstreamXR"
TG_LOGO = "https://raw.githubusercontent.com/xr3ed/xr3ed-tv/main/assets/telegram.png"
COFFEE_LINK = "https://lynk.id/xr3ed"
COFFEE_LOGO = "https://raw.githubusercontent.com/xr3ed/xr3ed-tv/main/assets/coffee.png"

MAX_UPCOMING_MATCHES = 10


def log(msg):
    now_str = datetime.now(WIB).strftime('%H:%M:%S')
    print(f"[{now_str}] {msg}", flush=True)


# ─── Fetch Page & Setup Session ───────────────────────────────────────────────

def init_session():
    if not SRC_URL:
        log("ERROR: LIVEEVENT_SRC_URL tidak diset.")
        return None, None, None

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    
    req = urllib.request.Request(SRC_URL, headers={
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    })
    
    try:
        with opener.open(req, timeout=20) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        log(f"ERROR fetch homepage: {e}")
        return None, None, None

    xsrf_token = None
    for cookie in cj:
        if cookie.name == 'XSRF-TOKEN':
            xsrf_token = urllib.parse.unquote(cookie.value)
            break

    return opener, xsrf_token, html


def parse_web_sections(html):
    """Membaca data widget website"""
    m = re.search(r'data-page="([^"]+)"', html)
    if not m:
        log("ERROR: data-page tidak ditemukan di HTML.")
        return [], [], []

    raw_json = m.group(1).replace('&quot;', '"').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    try:
        data = json.loads(raw_json)
    except Exception as e:
        log(f"ERROR parse JSON data-page: {e}")
        return [], [], []

    props = data.get('props', {})
    widgets = props.get('widgets', [])

    on_the_air_matches = []
    hot_matches = []
    all_matches = []

    for w in widgets:
        wdata = w.get('data', {})
        title = wdata.get('title', '')
        if title == 'On The Air':
            on_the_air_matches = wdata.get('matches', [])
        elif title == 'Hot Matches':
            hot_matches = wdata.get('matches', [])
        elif title == 'All Matches':
            all_matches = wdata.get('matches', [])

    if not on_the_air_matches and not hot_matches:
        raw_hot = props.get('hotMatches', [])
        on_the_air_matches = [m for m in raw_hot if m.get('is_live')]
        hot_matches = [m for m in raw_hot if m.get('is_hot')]
        all_matches = raw_hot

    # 1. Hot Event: HANYA yang sedang LIVE (is_live == 1)
    hot_live_matches = [m for m in hot_matches if m.get('is_live')]

    # 2. Live Event: Semua match yang sedang berlangsung (On The Air)
    live_all_matches = on_the_air_matches if on_the_air_matches else [m for m in all_matches if m.get('is_live')]

    # 3. Upcoming: 10 match mendatang terdekat yang belum live dan punya stream channel
    now_ts = int(datetime.now(timezone.utc).timestamp())
    upcoming_candidates = [
        m for m in all_matches 
        if not m.get('is_live') and m.get('play_at', 0) > now_ts and len(m.get('channels', [])) > 0
    ]
    upcoming_candidates.sort(key=lambda x: x.get('play_at', 0))
    upcoming_10 = upcoming_candidates[:MAX_UPCOMING_MATCHES]

    log(f"Kategori: Hot Live={len(hot_live_matches)} match | Live Event={len(live_all_matches)} match | Upcoming={len(upcoming_10)} match (Limit 10)")
    return hot_live_matches, live_all_matches, upcoming_10


# ─── Resolve Channel Stream Token & URL ───────────────────────────────────────

def extract_channel_name(ch_url):
    """Mengekstrak nama channel dari URL stream (misal: Sky-Bundesliga-1)"""
    if not ch_url:
        return ""
    clean = ch_url.rstrip('/')
    if clean.endswith('/index.m3u8'):
        return clean.split('/')[-2]
    return clean.split('/')[-1]


def resolve_channel_stream(opener, xsrf_token, ch_url):
    """
    POST /authorize-channel untuk mendapatkan direct HLS m3u8 stream token.
    Jika API mengembalikan /player atau placeholder, otomatis dikonversi
    ke direct CDN URL (enewl.greenvora.net/<ch_name>/index.jpg) yang 100% playable.
    """
    if not ch_url:
        return None

    ch_name = extract_channel_name(ch_url)
    default_direct_url = f"{CDN_BASE}/{ch_name}/index.jpg"

    auth_url = f"{SRC_URL}/authorize-channel"
    payload = json.dumps({"channel": ch_url}).encode('utf-8')

    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': USER_AGENT,
        'Origin': SRC_URL,
        'Referer': f"{SRC_URL}/",
        'X-Requested-With': 'XMLHttpRequest'
    }
    if xsrf_token:
        headers['X-XSRF-TOKEN'] = xsrf_token

    req = urllib.request.Request(auth_url, data=payload, headers=headers)
    try:
        with opener.open(req, timeout=12) as res:
            data = json.loads(res.read().decode('utf-8', errors='ignore'))
            server_url = data.get('server', '')
            if 'link=' in server_url:
                parsed = urllib.parse.urlparse(server_url)
                qs = urllib.parse.parse_qs(parsed.query)
                if 'link' in qs and qs['link']:
                    direct = qs['link'][0]
                    if direct.startswith('http') and 'twinspeed.space' not in direct:
                        return direct
            if server_url and server_url.startswith('http') and 'twinspeed.space' not in server_url:
                return server_url
    except Exception:
        pass

    return default_direct_url


def resolve_match_channels(opener, xsrf_token, match):
    channels = match.get('channels', [])
    if not channels:
        return []

    results = []
    seen_urls = set()
    for ch_url in channels:
        direct_stream = resolve_channel_stream(opener, xsrf_token, ch_url)
        if direct_stream and direct_stream.startswith('http') and direct_stream not in seen_urls:
            seen_urls.add(direct_stream)
            results.append({
                'server_index': len(results) + 1,
                'stream_url': direct_stream
            })
    return results


# ─── Helper Format Jam & Status ───────────────────────────────────────────────

def format_match_time(epoch_ts):
    if not epoch_ts:
        return ""
    dt = datetime.fromtimestamp(epoch_ts, tz=WIB)
    return dt.strftime('%H:%M WIB')


def clean_league_name(name):
    if not name:
        return "Sport"
    clean = re.sub(r'[^\w\s\-\.]', '', name).strip()
    return clean or "Sport"


# ─── Build M3U Playlist ───────────────────────────────────────────────────────

def generate_m3u(opener, xsrf_token, hot_live_list, live_all_list, upcoming_list):
    now_wib = datetime.now(WIB).strftime('%Y-%m-%d %H:%M WIB')

    all_target_matches = []
    seen_ids = set()
    for match_items in [hot_live_list, live_all_list, upcoming_list]:
        for item in match_items:
            if not item.get('channels') or len(item.get('channels')) == 0:
                continue
            m_id = item.get('origin_id') or item.get('slug') or item.get('name')
            if m_id not in seen_ids:
                seen_ids.add(m_id)
                all_target_matches.append(item)

    log(f"Menyelesaikan stream token untuk {len(all_target_matches)} pertandingan unik...")

    resolved_streams = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(resolve_match_channels, opener, xsrf_token, m): (m.get('origin_id') or m.get('slug') or m.get('name'))
            for m in all_target_matches
        }
        for f in futures:
            m_key = futures[f]
            try:
                resolved_streams[m_key] = f.result()
            except Exception:
                resolved_streams[m_key] = []

    lines = [
        "#EXTM3U",
        f"# XR3ED LIVE SPORTS PLAYLIST — Updated: {now_wib}",
        "# Categories: 📢 INFO | 🔥 Hot Event | 🔴 Live Event | ⏳ Upcoming Event",
        "",
        f'#EXTINF:-1 tvg-id="xr3ed-telegram" tvg-name="📢 Gabung Telegram: t.me/CloudstreamXR" tvg-logo="{TG_LOGO}" group-title="{GROUP_INFO}",📢 Gabung Telegram: t.me/CloudstreamXR',
        TG_LINK,
        "",
        f'#EXTINF:-1 tvg-id="xr3ed-coffee" tvg-name="☕ Traktir Kopi: lynk.id/xr3ed" tvg-logo="{COFFEE_LOGO}" group-title="{GROUP_INFO}",☕ Traktir Kopi: lynk.id/xr3ed',
        COFFEE_LINK,
        ""
    ]

    total_streams = 0

    categories_to_render = [
        (GROUP_HOT, hot_live_list),
        (GROUP_LIVE, live_all_list),
        (GROUP_UPCOMING, upcoming_list)
    ]

    for cat_name, matches in categories_to_render:
        if not matches:
            continue

        for m in matches:
            m_key = m.get('origin_id') or m.get('slug') or m.get('name')
            streams = resolved_streams.get(m_key, [])
            if not streams:
                continue

            name = m.get('name', 'Match').strip()
            league = clean_league_name(m.get('league', {}).get('name', ''))
            play_at = m.get('play_at') or m.get('start_at') or 0
            time_str = format_match_time(play_at)
            score = m.get('score')
            elapsed = m.get('elapsed')
            logo = m.get('homeTeam', {}).get('logo') or m.get('league', {}).get('logo') or ''

            for s in streams:
                srv_num = s['server_index']
                stream_url = s['stream_url']

                display_title = f"[{league}] {name}"
                
                if m.get('is_live'):
                    if score and score != '0 - 0':
                        display_title += f" ({score})"
                    if elapsed:
                        display_title += f" • {elapsed}'"
                    elif time_str:
                        display_title += f" • {time_str}"
                elif time_str:
                    display_title += f" • {time_str}"

                display_title += f" [Server {srv_num}]"

                extinf = f'#EXTINF:-1 tvg-id="{m_key}" tvg-name="{display_title}"'
                if logo:
                    extinf += f' tvg-logo="{logo}"'
                extinf += f' group-title="{cat_name}",{display_title}'

                lines.append(extinf)
                lines.append(f"#EXTVLCOPT:http-referrer={REF_URL}")
                lines.append(f"#EXTVLCOPT:http-user-agent={USER_AGENT}")
                lines.append(stream_url)
                lines.append("")
                total_streams += 1

    log(f"Total stream link berhasil dimasukkan ke M3U: {total_streams}")
    return "\n".join(lines)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    log("=== sync_liveevent.py dimulai ===")
    opener, xsrf_token, html = init_session()
    if not html:
        log("ERROR: Gagal inisialisasi session.")
        sys.exit(0)

    hot_live_list, live_all_list, upcoming_list = parse_web_sections(html)
    if not hot_live_list and not live_all_list and not upcoming_list:
        log("Tidak ada match yang ditemukan.")
        sys.exit(0)

    m3u_content = generate_m3u(opener, xsrf_token, hot_live_list, live_all_list, upcoming_list)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(script_dir) == 'scripts':
        out_path = os.path.join(script_dir, '..', OUTPUT_FILE)
    else:
        out_path = os.path.join(script_dir, OUTPUT_FILE)
    out_path = os.path.normpath(out_path)

    with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(m3u_content)

    file_size_kb = os.path.getsize(out_path) / 1024
    log(f"File M3U berhasil disimpan: {out_path} ({file_size_kb:.1f} KB)")
    log("=== Selesai ===")


if __name__ == '__main__':
    main()
