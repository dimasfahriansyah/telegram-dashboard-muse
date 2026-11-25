"""Bot Dashboard Telegram untuk memantau kerja Muse.

Bot ini HANYA membaca status dari file status.json lokal, tidak pernah
menghubungi layanan lain. Muse yang memperbarui status.json, bot yang
menyajikannya lewat perintah Telegram.

Perintah:
  /start    pengantar + daftar perintah
  /status   status semua job, dikelompokkan per kategori (folder)
  /laporan  ringkasan hari ini: yang jalan, yang beres, yang butuh keputusan
  /agen     daftar agen/job yang dipantau, per kategori, + aktivitas terakhir
  /draft    antrean keputusan draf Threads (jumlah + item tertua)
  /tugas    tugas terbuka, dikelompokkan per kategori
  /help     sama dengan /start

Dua mode update status (lihat README):
  1. Mode lokal: Muse menulis status.json langsung (satu mesin yang sama).
  2. Mode push: Muse di mesin lain mengirim POST /api/report ke endpoint
     HTTP bot ini dengan Bearer DASHBOARD_SECRET. Endpoint menyimpan
     payload ke status.json, jadi /status dan /laporan langsung membaca
     data terbaru. Tanpa DASHBOARD_SECRET, endpoint tidak aktif.

Env var:
  TELEGRAM_BOT_TOKEN  token bot dari @BotFather (wajib)
  TELEGRAM_CHAT_ID    id grup/chat tujuan laporan (untuk forward push)
  STATUS_FILE         path status.json (default: status.json di folder ini)
  DASHBOARD_SECRET    secret untuk POST /api/report (kosong = endpoint mati)
  DASHBOARD_HOST      host endpoint HTTP (default 127.0.0.1)
  DASHBOARD_PORT      port endpoint HTTP (default 8080, Railway pakai $PORT)
"""

import asyncio
import hmac
import html
import json
import logging
import os
import signal
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from status import CATEGORY_ORDER, DEFAULT_PATH, apply_payload, load_status, save_status

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
log = logging.getLogger("muse-dashboard")

STATUS_PATH = os.environ.get("STATUS_FILE", DEFAULT_PATH)
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DASHBOARD_SECRET = os.environ.get("DASHBOARD_SECRET", "")
DASHBOARD_HOST = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = int(
    os.environ.get("DASHBOARD_PORT") or os.environ.get("PORT", "8080")
)

# Urutan kategori diimpor dari status.py supaya sama dengan bot.py.
JOB_ICON = {"ok": "✅", "failed": "❌", "pending": "⏳", "blocked": "🚫", "idle": "💤"}
TASK_ICON = {"open": "⭕", "blocked": "🚫", "done": "✅"}
MAX_LEN = 4000  # batas aman di bawah limit pesan Telegram (4096)

# Referensi ke bot yang sedang jalan, dipakai endpoint HTTP untuk forward.
_APP = None
_LOOP = None


def _load():
    """Baca status terbaru dari file."""
    return load_status(STATUS_PATH)


def _trim(text):
    if len(text) > MAX_LEN:
        return text[: MAX_LEN - 1] + "…"
    return text


def _jam(iso):
    """Format ISO 8601 jadi '24 Nov 09:36', atau '-' kalau kosong/rusak."""
    if not iso:
        return "-"
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.strftime("%d %b %H:%M")
    except ValueError:
        return str(iso)


def _kelompokkan(items):
    """Kelompokkan list (job/tugas) per kategori, urut sesuai CATEGORY_ORDER."""
    grup = {}
    for it in items:
        grup.setdefault(it.get("category") or "Lainnya", []).append(it)
    urut = []
    for cat in CATEGORY_ORDER:
        if cat in grup:
            urut.append((cat, grup.pop(cat)))
    for cat in sorted(grup):
        urut.append((cat, grup[cat]))
    return urut


def _baris_job(job):
    ikon = JOB_ICON.get(job.get("status"), "❓")
    nama = html.escape(job.get("name") or job.get("id", "?"))
    ringkas = html.escape(job.get("summary") or "")
    teks = "%s <b>%s</b> (%s, terakhir %s)" % (
        ikon, nama, html.escape(job.get("schedule") or "-"), _jam(job.get("last_run")),
    )
    if ringkas:
        teks += "\n   %s" % ringkas
    return teks


# ---------------------------------------------------------------- perintah bot

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teks = (
        "👋 <b>Dashboard Muse</b>\n\n"
        "Saya memantau kerja Muse untuk user, ala kantor virtual: "
        "pagi Muse kerja, sore lapor ke sini.\n\n"
        "<b>Yang dipantau:</b>\n"
        "• Pantauan Threads, 3x sehari, draf komentar (tidak pernah auto-post)\n"
        "• Ngirit, cek malam + pengingat gajian tiap tanggal 25\n"
        "• Booklogd, review dan retest aplikasi\n"
        "• Bot Telegram + setup MCP Muse\n"
        "• Perburuan VPS gratis\n"
        "• Produksi kreatif (video, desain)\n\n"
        "<b>Perintah:</b>\n"
        "/status, status semua job per kategori\n"
        "/laporan, ringkasan hari ini\n"
        "/agen, daftar agen dan aktivitas terakhir\n"
        "/draft, antrean keputusan draf Threads\n"
        "/tugas, tugas terbuka\n"
    )
    await update.message.reply_text(_trim(teks), parse_mode="HTML")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = _load()
    jobs = data.get("jobs", [])
    if not jobs:
        await update.message.reply_text(
            "Belum ada data job. Muse belum menulis status.json.",
            parse_mode="HTML",
        )
        return
    bagian = ["📊 <b>Status Muse</b>"]
    for cat, daftar in _kelompokkan(jobs):
        bagian.append("\n<b>%s</b>" % html.escape(cat))
        for job in daftar:
            bagian.append(_baris_job(job))
    total_pending = data.get("drafts", {}).get("total_pending", 0)
    bagian.append("\n📝 Draf Threads menunggu keputusan: <b>%d</b>" % total_pending)
    bagian.append("Diperbarui: %s" % html.escape(str(data.get("updated_at", "-"))))
    await update.message.reply_text(_trim("\n".join(bagian)), parse_mode="HTML")


async def cmd_laporan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Bangun teks laporan sore dari reporter.py supaya formatnya sama
    # dengan laporan otomatis yang dikirim tiap sore.
    from reporter import build_sore_message

    await update.message.reply_text(_trim(build_sore_message(_load())), parse_mode="HTML")


async def cmd_agen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = _load()
    jobs = data.get("jobs", [])
    if not jobs:
        await update.message.reply_text(
            "Belum ada agen yang dipantau.", parse_mode="HTML"
        )
        return
    bagian = ["🤖 <b>Agen yang dipantau</b>"]
    for cat, daftar in _kelompokkan(jobs):
        bagian.append("\n<b>%s</b>" % html.escape(cat))
        for job in daftar:
            bagian.append(
                "• <b>%s</b> [%s] — %s, terakhir %s"
                % (
                    html.escape(job.get("name") or job.get("id", "?")),
                    html.escape(job.get("status", "?")),
                    html.escape(job.get("schedule") or "-"),
                    _jam(job.get("last_run")),
                )
            )
    await update.message.reply_text(_trim("\n".join(bagian)), parse_mode="HTML")


async def cmd_draft(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = _load()
    draf = data.get("drafts", {})
    total = draf.get("total_pending", 0)
    tertua = draf.get("oldest", [])
    bagian = ["📝 <b>Antrean keputusan draf Threads</b>",
              "Menunggu keputusan: <b>%d</b> draf" % total]
    if tertua:
        bagian.append("\n<b>Item tertua:</b>")
        for item in tertua:
            bagian.append(
                "• #%s %s — %s%s"
                % (
                    html.escape(str(item.get("id", "?"))),
                    html.escape(item.get("author", "?")),
                    html.escape(item.get("topic", "")),
                    (" (%s)" % html.escape(item["note"])) if item.get("note") else "",
                )
            )
    else:
        bagian.append("\nTidak ada item tertua yang tercatat.")
    bagian.append("\nDraf tidak pernah diposting otomatis, semua menunggu keputusan user.")
    await update.message.reply_text(_trim("\n".join(bagian)), parse_mode="HTML")


async def cmd_tugas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = _load()
    tugas = [t for t in data.get("tasks", []) if t.get("status") != "done"]
    if not tugas:
        await update.message.reply_text(
            "🎉 Tidak ada tugas terbuka.", parse_mode="HTML"
        )
        return
    bagian = ["📌 <b>Tugas terbuka</b>"]
    for cat, daftar in _kelompokkan(tugas):
        bagian.append("\n<b>%s</b>" % html.escape(cat))
        for t in daftar:
            ikon = TASK_ICON.get(t.get("status"), "❓")
            baris = "%s <b>%s</b>" % (ikon, html.escape(t.get("title", "?")))
            if t.get("due"):
                baris += " (tenggat %s)" % html.escape(str(t["due"]))
            if t.get("note"):
                baris += "\n   %s" % html.escape(t["note"])
            bagian.append(baris)
    await update.message.reply_text(_trim("\n".join(bagian)), parse_mode="HTML")


# ------------------------------------------------------- endpoint HTTP (push)

def _forward_text(text):
    """Kirim teks ke grup Telegram dari thread HTTP. Kembalikan True kalau
    terkirim, False kalau bot belum jalan atau chat belum diset."""
    if _APP is None or _LOOP is None or not CHAT_ID:
        return False
    coro = _APP.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="HTML")
    fut = asyncio.run_coroutine_threadsafe(coro, _LOOP)
    fut.result(timeout=20)
    return True


class _Handler(BaseHTTPRequestHandler):
    """Endpoint push sederhana. Satu-satunya rute tulis: POST /api/report.

    Header otentikasi (salah satu):
      Authorization: Bearer <DASHBOARD_SECRET>
      X-Dashboard-Secret: <DASHBOARD_SECRET>

    Body JSON yang dikenal:
      {"text": "pesan untuk diteruskan ke grup"}
      {"job": {"id": "threads-pagi", "status": "ok", "summary": "3 draf"}}
      {"drafts": {"total_pending": 96, "oldest": [...]}}
      {"tasks": [{"id": "vps-pilih", "title": "...", "status": "open"}]}
      {"report": "pagi" | "sore"}   -> kirim laporan pagi/sore ke grup
    Kunci-kunci di atas bisa digabung dalam satu payload.
    """

    def log_message(self, fmt, *args):  # diamkan log HTTP bawaan
        log.debug("%s - %s", self.address_string(), fmt % args)

    def _jawab(self, kode, obj):
        badan = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(kode)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(badan)))
        self.end_headers()
        self.wfile.write(badan)

    def _boleh(self):
        if not DASHBOARD_SECRET:
            return False
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return hmac.compare_digest(auth[7:].strip(), DASHBOARD_SECRET)
        return hmac.compare_digest(
            self.headers.get("X-Dashboard-Secret", ""), DASHBOARD_SECRET
        )

    def do_GET(self):
        if self.path in ("/", "/health"):
            self._jawab(200, {"ok": True, "push": bool(DASHBOARD_SECRET)})
        else:
            self._jawab(404, {"ok": False, "error": "tidak dikenal"})

    def do_POST(self):
        if self.path != "/api/report":
            self._jawab(404, {"ok": False, "error": "tidak dikenal"})
            return
        if not DASHBOARD_SECRET:
            self._jawab(503, {"ok": False, "error": "endpoint push belum aktif (DASHBOARD_SECRET kosong)"})
            return
        if not self._boleh():
            self._jawab(401, {"ok": False, "error": "secret salah"})
            return
        try:
            panjang = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(panjang).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            self._jawab(400, {"ok": False, "error": "body bukan JSON"})
            return
        if not isinstance(payload, dict):
            self._jawab(400, {"ok": False, "error": "body harus objek JSON"})
            return

        data = _load()
        perubahan = apply_payload(data, payload)
        if perubahan:
            save_status(data, STATUS_PATH)

        diteruskan = False
        try:
            if payload.get("text"):
                diteruskan = _forward_text(str(payload["text"]))
            mode = payload.get("report")
            if mode in ("pagi", "sore"):
                from reporter import build_pagi_message, build_sore_message

                teks = (
                    build_pagi_message(data)
                    if mode == "pagi"
                    else build_sore_message(data)
                )
                diteruskan = _forward_text(teks) or diteruskan
        except Exception as exc:  # noqa: BLE001 - laporkan sebagai error HTTP
            log.exception("gagal forward ke Telegram: %s", exc)
            self._jawab(502, {"ok": False, "error": "gagal kirim ke Telegram: %s" % exc,
                              "applied": perubahan})
            return
        self._jawab(200, {"ok": True, "applied": perubahan, "forwarded": diteruskan})


def start_http_server():
    """Jalankan endpoint push di thread terpisah. Tidak jalan kalau
    DASHBOARD_SECRET kosong."""
    if not DASHBOARD_SECRET:
        log.warning("DASHBOARD_SECRET kosong, endpoint push tidak aktif")
        return None
    server = ThreadingHTTPServer((DASHBOARD_HOST, DASHBOARD_PORT), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True, name="dashboard-http")
    thread.start()
    log.info("Endpoint push aktif di %s:%d (POST /api/report)", DASHBOARD_HOST, DASHBOARD_PORT)
    return server


# ------------------------------------------------------------------- jalan bot

async def _run(token):
    global _APP, _LOOP
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("laporan", cmd_laporan))
    app.add_handler(CommandHandler("agen", cmd_agen))
    app.add_handler(CommandHandler("draft", cmd_draft))
    app.add_handler(CommandHandler("tugas", cmd_tugas))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    _APP = app
    _LOOP = asyncio.get_running_loop()
    log.info("Bot jalan, membaca %s", STATUS_PATH)
    start_http_server()

    berhenti = asyncio.Event()
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, berhenti.set)
    except NotImplementedError:
        pass  # Windows: tidak ada add_signal_handler, Ctrl+C tetap jalan
    try:
        await berhenti.wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN belum diset. Isi file .env dulu, lihat README.")
    asyncio.run(_run(token))


if __name__ == "__main__":
    main()
