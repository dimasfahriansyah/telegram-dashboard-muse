# Dashboard Telegram Muse

Dashboard buat mantau kerja Muse, ala kantor virtual Gege Vision: pagi
Muse kerja, sore lapor ke grup Telegram. Bedanya, dashboard di sini bukan
aplikasi terpisah, melainkan Telegram itu sendiri: satu grup laporan
tempat Muse lapor, plus bot yang jawab perintah buat cek status kapan saja.

Yang dipantau, dikelompokkan per kategori kayak folder per divisi:

| Kategori | Isi |
| --- | --- |
| Pantauan Threads | Pantauan Muse AI 3x sehari (09:36, 13:36, 19:36 WIB), draf komentar, tidak pernah auto-post |
| Ngirit | Cek malam 21:36 WIB + pengingat gajian tiap tanggal 25 |
| Booklogd | Review dan retest aplikasi Booklogd |
| Bot Telegram | Setup bot Telegram + MCP Muse |
| VPS | Perburuan VPS gratis (tenggat 30 Nov 2026) |
| Produksi Kreatif | Video, desain, dan produksi lain |

## Cara kerja

```
Muse (cron / kerjaan) ---- tulis ----> status.json
                                        |
Bot Telegram (bot.py) ---- baca -------> status.json
   |-> jawab /status /laporan /agen /draft /tugas di chat
   |-> endpoint POST /api/report (mode push, lihat bawah)

reporter.py (cron pagi/sore) ---- baca status.json ----> kirim laporan ke grup
```

Satu-satunya sumber data adalah `status.json`. Bot tidak pernah
menghubungi layanan lain. Muse yang memperbarui status, bot yang
menyajikan.

## File-file

| File | Fungsi |
| --- | --- |
| `bot.py` | Bot Telegram (python-telegram-bot v21, async) + endpoint push HTTP |
| `status.py` | Skema `status.json` + fungsi baca/tulis/perbarui + `apply_payload` buat push |
| `reporter.py` | Kirim laporan pagi (`pagi`) dan sore (`sore`) ke grup |
| `status.example.json` | Contoh isi `status.json` dengan data realistis |
| `status.json` | Data nyata (dibuat dari contoh, jangan commit kalau ada data asli) |
| `requirements.txt` | Dependensi Python |
| `.env.example` | Contoh env var, salin jadi `.env` |
| `Dockerfile` | Image bot buat Docker / VPS |
| `railway.json` | Deploy ke Railway (Nixpacks, start `python bot.py`) |
| `muse-dashboard.service` | systemd buat bot di VPS |
| `muse-dashboard-reporter@.service` | systemd buat reporter (oneshot, `%i` = pagi/sore) |
| `muse-dashboard-reporter-pagi.timer` | Timer reporter pagi jam 08:00 |
| `muse-dashboard-reporter-sore.timer` | Timer reporter sore jam 17:30 |

## Perintah bot

| Perintah | Fungsi |
| --- | --- |
| `/start` | Pengantar + daftar perintah |
| `/status` | Status semua job, dikelompokkan per kategori |
| `/laporan` | Ringkasan hari ini: yang jalan, yang beres, yang butuh keputusan |
| `/agen` | Daftar agen/job yang dipantau + aktivitas terakhir |
| `/draft` | Antrean keputusan draf Threads (jumlah + item tertua) |
| `/tugas` | Tugas terbuka, dikelompokkan per kategori |
| `/help` | Sama dengan `/start` |

## Dua mode update status

### Mode 1: lokal (status.json)

Dipakai kalau Muse dan bot jalan di mesin yang sama. Muse menulis
`status.json` langsung setiap selesai kerja, bot membaca file itu.

```bash
# Setelah satu job selesai, catat dari cron Muse:
python3 status.py run threads-pagi ok "3 draf baru, 0 dibalas"

# Atau dari kode Python:
from status import load_status, update_job, save_status
data = load_status()
update_job(data, "threads-pagi", status="ok", summary="3 draf baru")
save_status(data)
```

### Mode 2: push (endpoint HTTP)

Dipakai kalau Muse jalan di mesin yang berbeda dari bot (misal bot di
Railway atau VPS, Muse di VM lain). Bot menyediakan endpoint:

```
POST /api/report
Authorization: Bearer <DASHBOARD_SECRET>
Content-Type: application/json
```

Contoh kirim laporan dari Muse:

```bash
curl -X POST http://localhost:8080/api/report \
  -H "Authorization: Bearer $DASHBOARD_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "job": {"id": "threads-pagi", "status": "ok", "summary": "3 draf baru"},
    "drafts": {"total_pending": 96},
    "text": "Pantauan pagi selesai: 3 draf baru menunggu keputusan."
  }'
```

Kunci body yang dikenal (boleh digabung):

| Kunci | Fungsi |
| --- | --- |
| `job` | Satu job (dict) atau list job, diperbarui ke `status.json` |
| `drafts` | `{"total_pending": 96, "oldest": [...]}` |
| `tasks` | List tugas, ditambah/diperbarui ke `status.json` |
| `text` | Pesan teks, langsung diteruskan ke grup Telegram |
| `report` | `"pagi"` atau `"sore"`, kirim laporan pagi/sore ke grup |

Jawaban endpoint: `{"ok": true, "applied": [...], "forwarded": true}`.
Kalau secret salah: 401. Kalau `DASHBOARD_SECRET` kosong, endpoint tidak
aktif (503). Endpoint juga menyediakan `GET /health` buat cek hidup.

Karena payload push disimpan ke `status.json`, perintah `/status` dan
`/laporan` langsung membaca data terbaru dari situ. Tidak ada database.

**Keamanan:** endpoint default mengikat `127.0.0.1` saja. Jangan buka ke
`0.0.0.0` tanpa reverse proxy + HTTPS. Secret harus panjang dan acak,
jangan pakai yang gampang ditebak.

## Setup langkah demi langkah

### 1. Buat bot Telegram

1. Buka `@BotFather` di Telegram, kirim `/newbot`, ikuti langkahnya.
2. Simpan token yang diberikan.
3. Buat grup Telegram buat laporan, tambahkan bot ke grup.
4. Cari ID grup: tambah `@getmyid_bot` ke grup lalu kirim pesan apa saja,
   catat angka negatifnya (misal `-1001234567890`). Atau kirim pesan ke
   `@userinfobot`.

### 2. Siapkan kode

```bash
git clone <repo-ini>
cd telegram-dashboard-muse
cp .env.example .env
# isi TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID di .env
cp status.example.json status.json
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Tes lokal

```bash
python3 -m py_compile bot.py status.py reporter.py
python3 status.py show            # lihat isi status.json
python3 bot.py                    # jalanin bot, lalu tes /start di Telegram
# di terminal lain, tes kirim laporan sore:
python3 reporter.py sore
```

### 4. Deploy (pilih satu)

#### Opsi A: Oracle Cloud Always Free (dipilih user)

VM gratis permanen, bukan trial. Bot kecil ini pemakaiannya ringan,
spek Always Free (2 OCPU/12GB) sudah lebih dari cukup.

1. Buat akun Oracle Cloud di cloud.oracle.com. Pendaftaran butuh kartu
   debit/kredit buat verifikasi identitas, tidak ada tagihan buat
   resource Always Free.

   **Baca dulu sebelum daftar, 4 jebakan yang paling sering bikin gagal:**
   - **Home region jangan salah pilih.** VM Always Free (A1) cuma bisa
     dibuat di home region, dan home region TIDAK bisa diganti nanti.
     Buat lu, pilih **Singapore (ap-singapore-1)**, paling dekat dan
     kapasitas A1-nya relatif lebih gampang dapat daripada region US.
   - **Jangan daftar sambil nyala VPN USA.** Menurut konsensus komunitas,
     Oracle ngecek kecocokan negara IP, negara penerbit kartu, dan alamat
     tagihan. Daftar dari IP Indonesia, pakai kartu Blu Indonesia, alamat
     tagihan Indonesia. (Ini bukan aturan resmi Oracle, tapi pola gagal
     yang paling sering dilaporkan.)
   - **Hold kartu sekitar $1, bukan tagihan.** Oracle FAQ resmi bilang
     hold sementara dilepas bank biasanya 3-5 hari. Jangan kaget kalau
     muncul di mutasi Blu, duitnya balik.
   - **Jangan sentuh kredit trial $300.** Akun baru dapat $300 buat 30
     hari, tapi itu buat resource berbayar. Buat bot ini pakai resource
     yang berlabel **Always Free** saja, jadi tidak ada tagihan.
2. Buat VM: Compute → Instances → Create Instance.
   - Image: Ubuntu 22.04 atau 24.04.
   - Shape: Always Free eligible, VM.Standard.A1.Flex (2 OCPU, 12 GB
     RAM). Kalau A1 habis, VM.Standard.E2.1.Micro juga bisa.
   - **Kalau muncul "Out of host capacity":** itu umum banget buat A1
     gratis, bukan salah lu. Coba lagi beberapa menit kemudian, ganti
     availability domain (AD-1 / AD-2 / AD-3), atau jatuh ke E2.1.Micro
     yang kapasitasnya lebih longgar. Jangan upgrade ke Pay As You Go
     cuma buat dapat kapasitas, kecuali lu sudah paham risikonya.
   - Boot volume: 50 GB (jatah Always Free sampai 200 GB).
   - SSH key: buat baru atau upload yang sudah ada, simpan private key.
3. SSH ke VM, install Python dan Git:
   ```bash
   sudo apt update && sudo apt install -y python3 python3-venv python3-pip git
   ```
4. Clone repo dan siapkan env:
   ```bash
   git clone <repo-ini> /opt/muse-dashboard
   cd /opt/muse-dashboard
   cp .env.example .env
   # isi TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DASHBOARD_SECRET di .env
   cp status.example.json status.json
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
5. Jalankan dengan systemd (file sudah disiapkan di repo):
   ```bash
   sudo cp muse-dashboard.service /etc/systemd/system/
   sudo cp muse-dashboard-reporter@.service /etc/systemd/system/
   sudo cp muse-dashboard-reporter-pagi.timer muse-dashboard-reporter-sore.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now muse-dashboard.service
   sudo systemctl enable --now muse-dashboard-reporter-pagi.timer muse-dashboard-reporter-sore.timer
   sudo systemctl status muse-dashboard.service
   ```
6. Mode lokal paling gampang di Oracle: Muse menulis `status.json` di
   folder yang sama, atau kirim push ke `http://127.0.0.1:8080/api/report`.
   File `status.json` di VM awet karena disk VM permanen (tidak
   ephemeral kayak Railway).

**Port, hanya kalau pakai mode push HTTP dari luar:**
Mode polling saja tidak butuh port terbuka sama sekali. Kalau Muse di
mesin lain mau POST ke endpoint push, buka port 8080 di dua tempat:
- Oracle security list: VCN → Security Lists → Ingress Rule baru,
  Source `0.0.0.0/0`, IP Protocol TCP, Destination Port Range `8080`.
  Lebih aman: isi Source dengan IP publik mesin Muse saja.
- Firewall VM (Ubuntu): `sudo ufw allow 8080/tcp` lalu `sudo ufw enable`
  (kalau ufw belum aktif, cek dulu dengan `sudo ufw status`).
- Set `DASHBOARD_HOST=0.0.0.0` di `.env` supaya endpoint bisa diakses
  dari luar. Tanpa HTTPS, jangan buka ke semua IP kalau tidak perlu,
  batasi source IP di security list.

**Catatan:** Oracle bisa mereklamasi VM Always Free yang lama
menganggur. Bot ini polling Telegram terus-menerus, jadi VM tidak
pernah menganggur.

#### Opsi B: Railway (alternatif)

Railway memberi kredit trial **$5** buat akun baru. Setelah itu
pay-as-you-go sekitar **$5/bulan**. Bot kecil ini pemakaiannya ringan
(polling Telegram + sesekali kirim laporan), jadi biayanya di ujung bawah.

1. Push kode ini ke repo GitHub.
2. Di [railway.app](https://railway.app), buat project baru, pilih
   **Deploy from GitHub repo**, pilih repo ini.
3. Railway membaca `railway.json` otomatis: builder Nixpacks,
   start command `python bot.py`.
4. Di tab **Variables**, isi:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `DASHBOARD_SECRET` (buat string acak yang panjang, misal
     `python3 -c "import secrets; print(secrets.token_hex(16))"`)
5. Deploy. Bot langsung jalan.
6. Endpoint push: Railway memberi domain publik dan mengisi `$PORT`
   otomatis. Bot membaca `$PORT` buat endpoint HTTP. Jadi Muse bisa
   POST ke `https://<domain-railway>/api/report` dengan Bearer secret.
7. Laporan pagi/sore: karena Railway tidak punya cron bawaan buat
   skrip Python, jalankan `reporter.py` dari cron Muse (kirim lewat
   endpoint push dengan `{"report": "pagi"}` atau `{"report": "sore"}`),
   atau dari cron di mesin lain.

**Catatan penting:** filesystem Railway itu ephemeral, `status.json`
tidak dijamin awet saat redeploy. Solusinya: pakai **mode push**
(Muse kirim status lewat endpoint, bot selalu punya data terbaru),
atau pasang **Volume** Railway dan set `STATUS_FILE` ke path di volume
(misal `/app/data/status.json`).

#### Opsi C: VPS lain / Docker (singkat)

VPS lain (RackNerd, Kamatera, dsb): langkahnya sama kayak Oracle,
salin folder, isi `.env`, jalankan service systemd di atas.

Docker:

```bash
docker build -t muse-dashboard .
docker run -d --env-file .env -v muse-status:/app/data \
  -e STATUS_FILE=/app/data/status.json -p 8080:8080 muse-dashboard
```

## Yang masih dibutuhkan sebelum go-live

1. **Token bot** dari `@BotFather` (belum ada, jangan commit ke Git).
2. **Grup Telegram + chat ID** tujuan laporan.
3. **Host**: Oracle Cloud Always Free (dipilih), Railway sebagai
   alternatif, VPS lain juga bisa.
4. **`DASHBOARD_SECRET`** kalau mau pakai mode push (wajib, jangan
   pakai secret kosong di server publik).
5. **Muse menulis status**: cron Muse harus memanggil
   `status.py run ...` (mode lokal) atau POST ke `/api/report`
   (mode push) setiap selesai kerja, supaya dashboard tidak kosong.
6. **Laporan pagi/sore**: atur pemicu `reporter.py pagi` jam 08:00
   dan `reporter.py sore` jam 17:30, atau kirim `{"report": ...}`
   lewat endpoint push dari cron Muse.

## Troubleshooting

| Gejala | Periksa |
| --- | --- |
| Bot tidak balas | Token benar? Bot sudah di grup? `TELEGRAM_BOT_TOKEN` di `.env`? |
| `/status` kosong | `status.json` ada dan terisi? `STATUS_FILE` mengarah ke file yang benar? |
| Laporan tidak terkirim | `TELEGRAM_CHAT_ID` benar (angka negatif buat grup)? Bot sudah jadi member grup? |
| Endpoint 401 | Header `Authorization: Bearer ...` sama dengan `DASHBOARD_SECRET`? |
| Endpoint 503 | `DASHBOARD_SECRET` kosong, endpoint memang tidak aktif. |
| Status hilang setelah deploy Railway | Filesystem ephemeral, pakai mode push atau Volume Railway. |
