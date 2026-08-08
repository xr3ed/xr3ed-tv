import os
import json
import hashlib
import urllib.request
import urllib.parse
import base64
import re
from Crypto.Cipher import AES

# Muat file .env jika ada (untuk jalan lokal)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --- 1. PLAYLIST 1 ---
try:
    url = os.environ.get('DECRYPT_URL', '')
    key_a = os.environ.get('DECRYPT_KEY_A', '').encode()
    key_b = os.environ.get('DECRYPT_KEY_B', '').encode()
    key_v = os.environ.get('DECRYPT_KEY_V', '').encode()
    pkg = os.environ.get('DECRYPT_PKG', '').encode()

    if not all([url, key_a, key_b, key_v, pkg]):
        print("Warning: Missing Playlist 1 environment variables, skipping.")
    else:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        enc_data = urllib.request.urlopen(req).read()

        combo = key_a + key_b + key_v + pkg
        key = hashlib.sha256(combo).digest()

        iv = enc_data[:12]
        ct = enc_data[12:-16]
        tag = enc_data[-16:]

        cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
        decrypted = cipher.decrypt_and_verify(ct, tag)

        with open('xr3ed-tv.m3u', 'wb') as f:
            f.write(decrypted)
        print("Sukses update Playlist 1!")
except Exception as e:
    print(f"Error Playlist 1: {e}")


