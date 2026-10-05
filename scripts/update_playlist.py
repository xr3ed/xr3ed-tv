#!/usr/bin/env python3
"""
update_playlist.py
==================
Sinkronisasi playlist Master XR3ED TV (xr3dtv.m3u8) dengan:
- Live Sports terpadu dari OnDemand, Kltra, dan Beesport via live_engine.py
- Multi-server failover & deduplikasi otomatis
- Isolasi channel linear 24/7 (NFL Network, Willow, Fox Cricket, Rally TV) ke grup '⚽ SPORTS'
- Kategori TV Nasional & Internasional 24/7 dari nasional.m3u
- Murni membaca dari environment variable tanpa hardcoded fallback
"""

import os
import sys
import re
from datetime import datetime, timezone, timedelta

# Ensure UTF-8 output on Windows
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

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

OUTPUT_FILE = clean_env(os.environ.get('XR3EDTV_OUTPUT', 'xr3dtv.m3u8')) or 'xr3dtv.m3u8'
NASIONAL_ENV = clean_env(os.environ.get('NASIONAL_OUTPUT', 'nasional.m3u')) or 'nasional.m3u'

from live_engine import (
    fetch_merged_matches,
    render_m3u_entry,
    is_fight_match,
    log,
    GROUP_HOT_EVENT,
    GROUP_LIVE_EVENT,
    GROUP_UPCOMING_EVENT,
    GROUP_FIGHT_EVENT
)

def generate_playlist():
    log("=== update_playlist.py dimulai ===")
    merged_data = fetch_merged_matches()

    hot_entries = []
    live_event_entries = []
    fight_entries = []
    upcoming_sorted_lines = []
    total_live_servers = 0

    # 1. Hot Event (Hanya yang LIVE & HOT)
    for m in merged_data.get('hot_matches', []):
        for idx, srv in enumerate(m.get('servers', [])):
            hot_entries.extend(render_m3u_entry(GROUP_HOT_EVENT, m, idx + 1, srv))
            total_live_servers += 1

    # 2. Live Event (Semua match LIVE)
    for m in merged_data.get('live_matches', []):
        for idx, srv in enumerate(m.get('servers', [])):
            live_event_entries.extend(render_m3u_entry(GROUP_LIVE_EVENT, m, idx + 1, srv))
            total_live_servers += 1

    # 3. Fight & Combat (Match LIVE khusus combat/fight)
    fight_matches = [m for m in merged_data.get('live_matches', []) if is_fight_match(m.get('league', ''), m.get('title', ''))]
    for m in fight_matches:
        for idx, srv in enumerate(m.get('servers', [])):
            fight_entries.extend(render_m3u_entry(GROUP_FIGHT_EVENT, m, idx + 1, srv))

    # 4. Upcoming Event (Top 10 terdekat)
    for m in merged_data.get('upcoming_matches', [])[:10]:
        for idx, srv in enumerate(m.get('servers', [])):
            upcoming_sorted_lines.extend(render_m3u_entry(GROUP_UPCOMING_EVENT, m, idx + 1, srv))
            total_live_servers += 1

    # 5. Baca Channel 24/7 dari nasional.m3u
    if os.path.basename(script_dir) == 'scripts':
        nasional_path = os.path.normpath(os.path.join(script_dir, '..', NASIONAL_ENV))
    else:
        nasional_path = os.path.normpath(os.path.join(script_dir, NASIONAL_ENV))
    if not os.path.exists(nasional_path) and os.path.exists(NASIONAL_ENV):
        nasional_path = NASIONAL_ENV

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
                    # Fix broken attribute repetitions (e.g. logo="... group-title=" group-title="XYZ")
                    l = re.sub(r'(\S+)\s+group-title="\s*(?=group-title=")', r'\1" ', l)
                    grp_matches = [m.strip() for m in re.findall(r'group-title="([^"]*)"', l) if m.strip() and not m.strip().startswith('group-title=')]
                    current_grp = grp_matches[-1] if grp_matches else 'Other'
                    if current_grp not in nasional_cat_order:
                        nasional_cat_order.append(current_grp)
                    total_247_channels += 1
                current_chunk.append(l)
            if current_grp and current_chunk:
                nasional_categories.setdefault(current_grp, []).extend(current_chunk)

    # 6. Alihkan Channel Linear 24/7 dari OnDemand (NFL Network, Willow, Fox Cricket, Rally TV, dll)
    # ke urutan PERTAMA di kategori '⚽ SPORTS'
    linear_sports = merged_data.get('linear_channels', [])
    if linear_sports:
        sports_grp = '⚽ SPORTS'
        if sports_grp not in nasional_categories:
            nasional_categories[sports_grp] = []
        if sports_grp not in nasional_cat_order:
            nasional_cat_order.append(sports_grp)
        linear_entries = []
        for m in linear_sports:
            for idx, srv in enumerate(m.get('servers', [])):
                linear_entries.extend(render_m3u_entry(sports_grp, m, idx + 1, srv))
                total_247_channels += 1
        # Prepend ke urutan paling awal di kategori SPORTS
        nasional_categories[sports_grp] = linear_entries + nasional_categories[sports_grp]

    # 7. Susun Playlist Master Final
    final_lines = ['#EXTM3U url-tvg="https://raw.githubusercontent.com/apistech/project/refs/heads/main/epgs/guide.xml"']

    # 0. 📢 INFO (Paling Atas)
    if '📢 INFO' in nasional_categories:
        final_lines.extend(nasional_categories['📢 INFO'])

    # 1. 🔥 Hot Event (Live Big Matches)
    if hot_entries:
        final_lines.extend(hot_entries)

    # 2. 🔴 Live Event (All Live Sports)
    if live_event_entries:
        final_lines.extend(live_event_entries)

    # 3. ⏳ Upcoming Event (Top 10 Upcoming Matches)
    if upcoming_sorted_lines:
        final_lines.extend(upcoming_sorted_lines)

    # 4. 🥊 FIGHT & COMBAT (Hanya jika ada match LIVE fight)
    if fight_entries:
        final_lines.extend(fight_entries)

    # 5. 🇮🇩 NASIONAL (TV Indonesia 24/7)
    if '🇮🇩 NASIONAL' in nasional_categories:
        final_lines.extend(nasional_categories['🇮🇩 NASIONAL'])

    # 6. ⚽ SPORTS (Channel TV 24/7: beIN, SPOTV, Willow, NFL Network, dll)
    if '⚽ SPORTS' in nasional_categories:
        final_lines.extend(nasional_categories['⚽ SPORTS'])

    # 7. Kategori TV 24/7 Lainnya (Movies, Kids, Doc, Religi, Asia, Music)
    for cat in nasional_cat_order:
        if cat not in ['📢 INFO', '🇮🇩 NASIONAL', '⚽ SPORTS'] and cat in nasional_categories:
            final_lines.extend(nasional_categories[cat])

    if os.path.basename(script_dir) == 'scripts':
        out_path = os.path.normpath(os.path.join(script_dir, '..', OUTPUT_FILE))
    else:
        out_path = os.path.normpath(os.path.join(script_dir, OUTPUT_FILE))

    with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(final_lines) + '\n')

    log(f"Synced {out_path} successfully: {total_live_servers} live event servers + {total_247_channels} 24/7 channels merged.")
    log("=== update_playlist.py selesai ===")
    return True

if __name__ == '__main__':
    generate_playlist()
