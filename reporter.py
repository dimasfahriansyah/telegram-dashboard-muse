"""reporter.py, kirim laporan harian Muse ke grup Telegram.

Pola kantor virtual ala Gege Vision: pagi pemilik kasih perintah
(rencana hari ini), agen kerja, sore agen lapor ke grup.

  python3 reporter.py pagi   -> kirim rencana pagi
  python3 reporter.py sore   -> kirim laporan sore

Laporan dibangun murni dari status.json, jadi perintah /laporan di bot
memakai fungsi yang sama dan hasilnya konsisten.

Env var:
  TELEGRAM_BOT_TOKEN  token bot dari @BotFather (wajib saat kirim)
  TELEGRAM_CHAT_ID    id grup/chat tujuan (wajib saat kirim)
  STATUS_FILE         path status.json (default: status.json di folder ini)
"""

import html
import os
import sys
from datetime import datetime

from status import DEFAULT_PATH, WIB, load_status

BULAN_ID = [
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]
HARI_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


def _tanggal(dt=None):
    """Tanggal hari ini zona WIB, misal 'Selasa, 24 November 2026'."""
    dt = dt or datetime.now(WIB)
    return "%s, %d %s %d" % (HARI_ID[dt.weekday()], dt.day, BULAN_ID[dt.month - 1], dt.year)


def _hari_ini(data):
    """Job yang terakhir jalan hari ini (zona WIB)."""
    hari = datetime.now(WIB).date()
    hasil = []
    for job in data.get("jobs", []):
        try:
            jalan = datetime.fromisoformat(str(job.get("last_run", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if jalan.astimezone(WIB).date() == hari:
            hasil.append(job)
    return hasil


def _kelompok_teks(items):
    """Kelompokkan job/tugas per kategori jadi teks, urut sesuai status.py."""
    from status import CATEGORY_ORDER

    grup = {}
    for it in items:
        grup.setdefault(it.get("category") or "Lainnya", []).append(it)
    baris = []
    for cat in CATEGORY_ORDER:
        if cat in grup:
            baris.append("  • %s: %s" % (cat, ", ".join(
                x.get("name") or x.get("title") or x.get("id", "?") for x in grup.pop(cat))))
    for cat in sorted(grup):
        baris.append("  • %s: %s" % (cat, ", ".join(
            x.get("name") or x.get("title") or x.get("id", "?") for x in grup[cat])))
    return "\n".join(baris) if baris else "  • (tidak ada)"


def build_pagi_message(data):
    """Rencana pagi: apa yang jalan hari ini, apa yang butuh keputusan."""
    jobs = data.get("jobs", [])
    draf = data.get("drafts", {})
    tugas = [t for t in data.get("tasks", []) if t.get("status") != "done"]
    tertahan = [j for j in jobs if j.get("status") in ("blocked", "failed")]
    baris = [
        "☀️ <b>Rencana Pagi, %s</b>" % html.escape(_tanggal()),
        "",
        "<b>Yang jalan hari ini:</b>",
    ]
    for job in jobs:
        baris.append("  • <b>%s</b> (%s)" % (
            html.escape(job.get("name") or job.get("id", "?")),
            html.escape(job.get("schedule") or "-"),
        ))
    baris.append("")
    baris.append("<b>Yang butuh keputusan user:</b>")
    baris.append("  • Draf Threads menunggu: <b>%d</b>" % draf.get("total_pending", 0))
    if tugas:
        baris.append("  • Tugas terbuka: <b>%d</b>" % len(tugas))
        baris.append(_kelompok_teks(tugas))
    if tertahan:
        baris.append("")
        baris.append("<b>Yang tertahan:</b>")
        for job in tertahan:
            baris.append("  • %s, %s" % (
                html.escape(job.get("name") or job.get("id", "?")),
                html.escape(job.get("summary") or job.get("status", "")),
            ))
    baris.append("")
    baris.append("Perintah: /status /laporan /agen /draft /tugas")
    return "\n".join(baris)


def build_sore_message(data):
    """Laporan sore ala Gege Vision: yang jalan, yang beres, yang butuh
    keputusan, yang tertahan."""
    jalan = _hari_ini(data)
    beres = [j for j in jalan if j.get("status") == "ok"]
    gagal = [j for j in jalan if j.get("status") == "failed"]
    tertahan = [j for j in data.get("jobs", []) if j.get("status") in ("blocked", "failed")]
    draf = data.get("drafts", {})
    tugas = [t for t in data.get("tasks", []) if t.get("status") != "done"]
    baris = ["🌇 <b>Laporan Sore, %s</b>" % html.escape(_tanggal()), ""]
    baris.append("<b>Yang jalan hari ini:</b>")
    if jalan:
        for job in jalan:
            ikon = "✅" if job.get("status") == "ok" else ("❌" if job.get("status") == "failed" else "⏳")
            baris.append("  %s <b>%s</b>, %s" % (
                ikon, html.escape(job.get("name") or job.get("id", "?")),
                html.escape(job.get("summary") or "-"),
            ))
    else:
        baris.append("  • Belum ada job yang jalan hari ini.")
    baris.append("")
    baris.append("<b>Yang beres:</b> %d job" % len(beres))
    if gagal:
        baris.append("<b>Yang gagal:</b> %d job" % len(gagal))
    baris.append("")
    baris.append("<b>Yang butuh keputusan user:</b>")
    baris.append("  • Draf Threads menunggu: <b>%d</b>" % draf.get("total_pending", 0))
    tertua = draf.get("oldest", [])
    if tertua:
        for item in tertua[:3]:
            baris.append("    - #%s %s" % (
                html.escape(str(item.get("id", "?"))),
                html.escape(item.get("author", "?")),
            ))
    if tugas:
        baris.append("  • Tugas terbuka: <b>%d</b>" % len(tugas))
        baris.append(_kelompok_teks(tugas))
    if tertahan:
        baris.append("")
        baris.append("<b>Yang tertahan:</b>")
        for job in tertahan:
            baris.append("  • %s, %s" % (
                html.escape(job.get("name") or job.get("id", "?")),
                html.escape(job.get("summary") or job.get("status", "")),
            ))
    baris.append("")
    baris.append("Detail: /status /agen /draft /tugas")
    return "\n".join(baris)


def send_message(text):
    """Kirim teks ke grup Telegram. Import telegram ditunda sampai di sini
    supaya file ini tetap bisa dites tanpa library terpasang."""
    from telegram import Bot
    import asyncio

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise SystemExit("TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID wajib diset di env.")

    async def _kirim():
        await Bot(token).send_message(chat_id=chat_id, text=text, parse_mode="HTML")

    asyncio.run(_kirim())


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("pagi", "sore"):
        print("Pakai: python3 reporter.py pagi|sore")
        return 2
    data = load_status(os.environ.get("STATUS_FILE", DEFAULT_PATH))
    teks = build_pagi_message(data) if sys.argv[1] == "pagi" else build_sore_message(data)
    send_message(teks)
    print("Laporan %s terkirim." % sys.argv[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
