# xr3ed-tv

Utilitas sinkronisasi otomatis untuk mendekompresi dan menyinkronkan feed playlist IPTV privat menggunakan GitHub Actions dan Update Tools Lokal.

## Fitur Utama

- 🔄 **Sinkronisasi Hibrida**: 
  - **Otomatis (Cloud)**: Playlist 1 & 4 diperbarui secara berkala oleh GitHub Actions (tiap 15 menit).
  - **Lokal (Anti-Block)**: Playlist 2 & 3 diperbarui langsung dari komputer lokal Anda untuk menghindari pemblokiran server awan (*cloud block*) dan pembatasan wilayah (*Geo-IP*).
- 🔒 **Aman**: Pengaturan sensitif (Token, Kunci Dekripsi, dsb) disimpan secara rahasia di GitHub Secrets (untuk cloud) dan di berkas `config.json` lokal (tidak akan bocor ke publik Git).
- ⚡ **Ringan**: Dekripsi on-the-fly yang cepat dan langsung siap pakai.

---

## Tautan Playlist IPTV Player

Gunakan tautan RAW berikut langsung pada aplikasi pemutar IPTV pilihan Anda (TiviMate, VLC, OTT Navigator, Smart TV, dsb):

- **Playlist 1**:
  ```text
  https://raw.githubusercontent.com/xr3ed/xr3ed-tv/main/xr3ed-tv.m3u
  ```
- **Playlist 2**:
  ```text
  https://raw.githubusercontent.com/xr3ed/xr3ed-tv/main/xr3ed-tv2.m3u
  ```
- **Playlist 3**:
  ```text
  https://raw.githubusercontent.com/xr3ed/xr3ed-tv/main/xr3ed-tv3.m3u
  ```

---

## Cara Memperbarui Playlist

### A. Playlist 1 (Diperbarui via GitHub Actions)
Playlist 1 otomatis diperbarui setiap 15 menit. Jika ingin memperbarui secara manual/instan:
1. Masuk ke akun GitHub Anda dan buka tab **Actions**.
2. Pilih alur kerja **Update Playlist** di sebelah kiri.
3. Klik menu dropdown **Run workflow**, lalu pilih tombol hijau **Run workflow**.

### B. Playlist 2 & 3 (Diperbarui via Windows PC)
Playlist 2 dan 3 memblokir IP cloud, sehingga harus diperbarui dari komputer lokal Anda:
1. Klik ganda berkas **`update_playlist_local.exe`** di dalam folder proyek Anda.
2. Jendela konsol hitam akan muncul dan menampilkan proses dekripsi siaran.
3. Tunggu hingga proses selesai (~15-20 detik) dan kotak dialog **"Pembaruan Playlist Sukses!"** muncul di layar.
4. Klik **OK** pada kotak dialog, jendela konsol akan otomatis tertutup dan berkas `xr3ed-tv2.m3u` serta `xr3ed-tv3.m3u` Anda di GitHub sudah otomatis terperbarui.

> [!NOTE]
> Semua konfigurasi Token API GitHub disimpan di dalam berkas **`config.json`**. Jika tautan atau kunci otentikasi kedaluwarsa, Anda cukup mengedit berkas JSON tersebut menggunakan Notepad tanpa perlu menyentuh kode program.


