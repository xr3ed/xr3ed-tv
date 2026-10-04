#!/usr/bin/env python3
"""
sync_liveevent.py
=================
Otomatisasi sinkronisasi jadwal & stream pertandingan langsung (xr3edtv-liveevent.m3u)
menggunakan unified live engine yang menggabungkan:
- OnDemand (Primary Anchor + internal deduplication)
- Kltra (/jos/ dynamic XOR decryption + parallel vivo resolution)
- Beesport (Direct CDN token authorization)
- Filter channel linear 24/7 & kartun
"""

import os
import sys

# Ensure UTF-8 output on Windows
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

from live_engine import fetch_merged_matches, generate_liveevent_m3u, log

OUTPUT_FILE = os.environ.get('LIVEEVENT_OUTPUT', 'xr3edtv-liveevent.m3u').strip() or 'xr3edtv-liveevent.m3u'
MAX_UPCOMING = int(os.environ.get('LIVEEVENT_MAX_UPCOMING', '25'))

def main():
    log("=== sync_liveevent.py dimulai ===")
    merged_data = fetch_merged_matches()

    if not merged_data.get('all_matches') and not merged_data.get('linear_channels'):
        log("Tidak ada pertandingan yang ditemukan.")
        return

    m3u_content = generate_liveevent_m3u(merged_data, max_upcoming=MAX_UPCOMING)

    if os.path.basename(script_dir) == 'scripts':
        out_path = os.path.normpath(os.path.join(script_dir, '..', OUTPUT_FILE))
    else:
        out_path = os.path.normpath(os.path.join(script_dir, OUTPUT_FILE))

    with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(m3u_content)

    file_size_kb = os.path.getsize(out_path) / 1024
    total_streams = m3u_content.count('http://') + m3u_content.count('https://') - 2
    log(f"File M3U berhasil disimpan: {out_path} ({file_size_kb:.1f} KB, ~{total_streams} streams)")
    log("=== sync_liveevent.py selesai ===")

if __name__ == '__main__':
    main()
