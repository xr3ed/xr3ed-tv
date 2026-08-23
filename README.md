# ⚡ XR3ED-TV (All-In-One IPTV Master Playlist)

Otomatisasi sinkronisasi playlist IPTV terlengkap yang menggabungkan **🔴 Siaran Langsung Olahraga (Live Sports Harian)** dan **📺 Channel TV 24/7 (Nasional & Internasional)** dengan multi-server, failover otomatis, dan dukungan panduan EPG resmi.

---

## 🚀 Fitur Unggulan

- ⚽ **Live Sports Event Terdedikasi (`xr3edtv-liveevent.m3u`)**: Playlist khusus siaran langsung pertandingan olahraga terkini dengan resolusi 720p60 FPS, multi-server alternatif, skor langsung, dan menit pertandingan real-time.
- 🔴 **Sinkronisasi Otomatis**: GitHub Actions workflow berjalan otomatis setiap 5–10 menit untuk memperbarui jadwal kick-off dan token live stream terbaru.
- 📺 **TV Nasional & Internasional 24/7**: Channel TV Indonesia (RCTI, Trans, SCTV, Indosiar, TVRI, dll) dengan sistem cadangan `Server 1`, `Server 2`, `Server 3` dan logo resmi beresolusi tinggi.
- ⚡ **Multi-Server & Anti-Duplikat**: Menggabungkan beberapa link sumber per channel ke dalam satu nama channel terstruktur, otomatis membuang duplikat mati.
- 🛡️ **Cloudflare Edge Proxy**: Bypass proteksi Geo-block dan hotlink header secara transparan.
- 📑 **Panduan Jadwal TV (EPG XML)**: Terintegrasi dengan XMLTV EPG guide resmi.

---

## 🔗 Daftar Playlist M3U (Direct RAW)

Masukkan link RAW di bawah ini langsung ke aplikasi IPTV player favorit kamu (**OTT Navigator, TiviMate, VLC, Kodi, Smart TV, Android Box, iOS / Android**):

### 🌟 1. Master Playlist All-In-One (Live Sports + TV 24/7)
> **Rekomendasi Utama** — Berisi info + siaran langsung olahraga hari ini di bagian atas + seluruh channel TV 24/7 di bawahnya.

```text
https://raw.githubusercontent.com/xr3ed/xr3ed-tv/main/xr3dtv.m3u8
```

---

### ⚽ 2. Dedicated Live Sports Event Playlist (Khusus Olahraga Harian)
> **Khusus Pecinta Bola & Olahraga** — Fokus 100% pada siaran langsung match sepakbola (EPL, Serie A, La Liga, Bundesliga, UCL) dan olahraga dunia tanpa channel TV biasa.

```text
https://raw.githubusercontent.com/xr3ed/xr3ed-tv/main/xr3edtv-liveevent.m3u
```

---

### 📺 3. 24/7 Channels Only Playlist (Murni TV Linear)
> Berisi seluruh siaran TV 24/7 (Nasional, Olahraga 24/7, Film HBO, Kartun, Berita, Religi, Mancanegara, Musik).

```text
https://raw.githubusercontent.com/xr3ed/xr3ed-tv/main/nasional.m3u
```

---

## 📂 Struktur Kategori Playlist

### 🌟 A. Master Playlist All-In-One (`xr3dtv.m3u8`)
```
📂 [xr3dtv.m3u8]
 ├── 📢 INFO (Telegram: t.me/CloudstreamXR & Lynk.id: lynk.id/xr3ed)
 ├── 🔥 Hot Event (Big Matches LIVE)
 ├── 🔴 Live Event (Semua Olahraga LIVE: Bola, F1, UFC, Tenis, Badminton)
 ├── ⏳ Upcoming Event (Top 10 Match Terdekat Mendatang)
 ├── 🥊 FIGHT & COMBAT (Hanya jika ada match LIVE: UFC, Boxing, MMA, WWE)
 ├── 🇮🇩 NASIONAL (Channel TV Indonesia, Multi-Server 1, 2, 3)
 ├── ⚽ SPORTS (Channel TV 24/7: beIN Sports, SPOTV, Fight Sports, dll)
 ├── 🏆 LIGA CHAMPION (Arena Sport & Digi Sport)
 ├── ⚽ LIGA INGGRIS (Fubo Sports)
 ├── ⚽ LIGA SPANYOL (LaLiga Feeds)
 ├── ⚽ LIGA ITALIA (Serie A Feeds)
 ├── ⚽ LIGA JERMAN (Bundesliga Feeds)
 ├── 🏎️ OTOMOTIF (Cars.TV, Canal Motor, Choppertown)
 ├── 🎬 MOVIES & ENTERTAINMENT (HBO Pack, Cinemax, HITS, tvN)
 ├── 👫 KIDS & ANIME (Animax, DreamWorks, Cartoonito, Anime 24/7)
 ├── 📚 DOCUMENTARY & KNOWLEDGE (BBC Earth, History, Love Nature)
 ├── 🛰 NEWS & BUSINESS (CNBC, CNN, FOX News, IDX)
 ├── ☪️ ISLAM (Al Quran, TVMU, Al Iman, TV9)
 ├── ✝️ KRISTEN (EWTN, GMS, LIFE, Reformed 21)
 ├── 🇲🇾 MALAYSIA (RTM & Drama Hebat)
 ├── 🇰🇷 KOREA (tvN, tvN Movies, ONE HD, Arirang)
 ├── 🇨🇳 CHINA (CCTV & Dragon TV)
 └── 🎵 MUSIC (Radio & Video Musik)
```

### ⚽ B. Playlist Live Event (`xr3edtv-liveevent.m3u`)
```
📂 [xr3edtv-liveevent.m3u]
 ├── 📢 INFO (Telegram: t.me/CloudstreamXR & Lynk.id: lynk.id/xr3ed)
 ├── 🔥 Hot Event (Big Matches pilihan yang SEDANG LIVE saat ini)
 ├── 🔴 Live Event (Semua pertandingan live broadcast On The Air)
 └── ⏳ Upcoming Event (10 pertandingan mendatang terdekat dengan jadwal WIB)
```

### 📺 C. Playlist 24/7 Channels (`nasional.m3u`)
```
📂 [nasional.m3u]
 ├── 📢 INFO (Telegram: t.me/CloudstreamXR & Lynk.id: lynk.id/xr3ed)
 ├── 🇮🇩 NASIONAL (98 TV Nasional Indonesia)
 ├── ⚽ SPORTS (beIN Sports, SPOTV 24/7)
 └── ... (Kategori Hiburan, Film, Kartun, Berita, Religi, Mancanegara, Musik)
```

---

## 🛠️ Panduan Pasang di Player

### 📱 OTT Navigator (Android / Google TV):
1. Buka **Settings** ➔ **Provider** ➔ **Add Provider** ➔ **M3U Playlist**.
2. Masukkan salah satu URL Playlist RAW di atas.
3. Centang opsi **Auto reload** (agar match baru otomatis terupdate).

### 📺 TiviMate (Android TV / Firestick):
1. Masuk ke **Settings** ➔ **Playlists** ➔ **Add Playlist** ➔ **M3U Playlist**.
2. Masukkan salah satu URL Playlist RAW di atas.
3. Simpan dan aktifkan update interval berkala.

---

## ⚡ Otomasi CI/CD
- **Sync Master & 24/7 Playlist** (`.github/workflows/update_playlist.yml`): Berjalan otomatis tiap 5 menit (`*/5 * * * *`).
- **Sync Live Sports Event** (`.github/workflows/sync_liveevent.yml`): Berjalan otomatis tiap 10 menit (`*/10 * * * *`).
- **GitHub Secrets Protection**: Semua URL dan kredensial sensitif diamankan menggunakan GitHub Actions Secrets.