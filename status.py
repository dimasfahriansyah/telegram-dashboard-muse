"""Modul status untuk Dashboard Telegram Muse.

Modul ini mendefinisikan skema status.json dan fungsi pembantu untuk
membaca dan memperbaruinya. Tidak ada panggilan jaringan di sini, semua
hanya baca/tulis file lokal.

Skema status.json:
{
  "updated_at": "2026-11-24T19:30:00+07:00",   # ISO 8601, WIB
  "jobs": [                                     # satu item per "agen" / cron
    {
      "id": "threads-pagi",                     # id unik, huruf kecil + strip
      "name": "Pantauan Muse AI Pagi",          # nama yang tampil di bot
      "category": "Pantauan Threads",           # folder/kategori, misal:
                                                # Pantauan Threads, Ngirit,
                                                # Booklogd, Bot Telegram,
                                                # VPS, Produksi Kreatif
      "schedule": "09:36 WIB",                  # jadwal, teks bebas
      "last_run": "2026-11-24T09:36:00+07:00",  # ISO 8601 atau null
      "status": "ok",                           # ok | failed | pending |
                                                # blocked | idle
      "summary": "3 draf baru, 0 dibalas"       # ringkasan hasil terakhir
    }
  ],
  "drafts": {                                   # antrean draf Threads
    "total_pending": 96,                        # jumlah draf menunggu keputusan
    "oldest": [                                 # draf tertua, maks 5 item
      {"id": 52, "author": "@hasbi_shdqi",
       "topic": "Muse AI, kode referral", "note": "sudah basi"}
    ]
  },
  "tasks": [                                    # tugas terbuka
    {
      "id": "vps-pilih",
      "title": "Pilih VPS gratis (A/B/C/D)",
      "category": "VPS",
      "status": "open",                         # open | blocked | done
      "due": "2026-11-30",                      # tanggal atau null
      "note": "RackNerd tutup 30 Nov"
    }
  ]
}

Status job yang dipakai bot:
  ok      = jalan terakhir berhasil
  failed  = jalan terakhir gagal / error
  pending = belum jalan hari ini, menunggu jadwal
  blocked = tertahan, butuh sesuatu dari user
  idle    = tidak terjadwal, jalan kalau diminta
"""

import json
import os
from datetime import datetime, timezone

# Zona waktu WIB (UTC+7), tanpa perlu library tambahan.
try:
    from zoneinfo import ZoneInfo
    WIB = ZoneInfo("Asia/Jakarta")
except Exception:  # pragma: no cover - fallback kalau tzdata tidak ada
    from datetime import timedelta
    WIB = timezone(timedelta(hours=7))

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "status.json")

# Urutan kategori, meniru folder per divisi di referensi Gege Vision.
# Dipakai bot.py dan reporter.py supaya pengelompokannya konsisten.
CATEGORY_ORDER = [
    "Pantauan Threads",
    "Ngirit",
    "Booklogd",
    "Bot Telegram",
    "VPS",
    "Produksi Kreatif",
    "Lainnya",
]

VALID_JOB_STATUS = ("ok", "failed", "pending", "blocked", "idle")
VALID_TASK_STATUS = ("open", "blocked", "done")


def now_wib_iso():
    """Waktu sekarang dalam format ISO 8601 zona WIB."""
    return datetime.now(WIB).isoformat(timespec="seconds")


def new_status():
    """Bikin struktur status kosong sesuai skema."""
    return {"updated_at": now_wib_iso(), "jobs": [], "drafts": {"total_pending": 0, "oldest": []}, "tasks": []}


def load_status(path=DEFAULT_PATH):
    """Baca status.json. Kalau file tidak ada atau rusak, kembalikan
    struktur kosong supaya bot tetap jalan."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return new_status()
        data.setdefault("jobs", [])
        data.setdefault("drafts", {"total_pending": 0, "oldest": []})
        data.setdefault("tasks", [])
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return new_status()


def save_status(data, path=DEFAULT_PATH):
    """Tulis status.json. updated_at selalu diperbarui otomatis."""
    data["updated_at"] = now_wib_iso()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def update_job(data, job_id, status=None, summary=None, last_run=None, name=None,
               category=None, schedule=None):
    """Perbarui satu job. Kalau job belum ada, buat baru.
    last_run kosong berarti pakai waktu sekarang."""
    if status is not None and status not in VALID_JOB_STATUS:
        raise ValueError("status job tidak dikenal: %s" % status)
    job = next((j for j in data["jobs"] if j["id"] == job_id), None)
    if job is None:
        job = {"id": job_id, "name": name or job_id, "category": category or "Lainnya",
               "schedule": schedule or "-", "last_run": None,
               "status": "idle", "summary": ""}
        data["jobs"].append(job)
    if status is not None:
        job["status"] = status
    if summary is not None:
        job["summary"] = summary
    if name is not None:
        job["name"] = name
    if category is not None:
        job["category"] = category
    if schedule is not None:
        job["schedule"] = schedule
    job["last_run"] = last_run if last_run is not None else now_wib_iso()
    return job


def set_drafts(data, total_pending, oldest=None):
    """Perbarui hitungan antrean draf Threads."""
    data["drafts"]["total_pending"] = int(total_pending)
    if oldest is not None:
        data["drafts"]["oldest"] = list(oldest)[:5]
    return data["drafts"]


def upsert_task(data, task_id, title, category="Lainnya", status="open", due=None, note=""):
    """Tambah atau perbarui satu tugas terbuka."""
    if status not in VALID_TASK_STATUS:
        raise ValueError("status tugas tidak dikenal: %s" % status)
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)
    if task is None:
        task = {"id": task_id, "title": title, "category": category,
                "status": status, "due": due, "note": note}
        data["tasks"].append(task)
    else:
        task.update({"title": title, "category": category,
                     "status": status, "due": due, "note": note})
    return task


def mark_run(path, job_id, status, summary=""):
    """Jalan pintas yang dipakai cron Muse: baca status.json, catat satu
    job selesai jalan, lalu simpan lagi. Dipakai seperti:
    python3 status.py run threads-pagi ok "3 draf baru"."""
    data = load_status(path)
    update_job(data, job_id, status=status, summary=summary)
    save_status(data, path)
    return data


def apply_payload(data, payload):
    """Terapkan payload dari endpoint push (POST /api/report) ke data status.

    Kunci payload yang dikenal:
      "job":    dict atau list dict job, misal
                {"id": "threads-pagi", "status": "ok", "summary": "3 draf baru"}
      "drafts": dict, misal {"total_pending": 96, "oldest": [...]}
      "tasks":  list dict tugas, misal
                [{"id": "vps-pilih", "title": "...", "status": "open"}]
    Kunci lain ("text", "report") bukan state, jadi diabaikan di sini dan
    ditangani oleh pemanggil (bot.py). Kembalikan list perubahan yang
    diterapkan, untuk jawaban HTTP."""
    changes = []
    jobs = payload.get("job")
    if jobs:
        if isinstance(jobs, dict):
            jobs = [jobs]
        for j in jobs:
            if not isinstance(j, dict) or not j.get("id"):
                continue
            update_job(data, j["id"], status=j.get("status"),
                       summary=j.get("summary"), last_run=j.get("last_run"),
                       name=j.get("name"), category=j.get("category"),
                       schedule=j.get("schedule"))
            changes.append("job %s -> %s" % (j["id"], j.get("status")))
    drafts = payload.get("drafts")
    if isinstance(drafts, dict):
        total = drafts.get("total_pending", data["drafts"].get("total_pending", 0))
        set_drafts(data, total, drafts.get("oldest"))
        changes.append("drafts -> %s pending" % data["drafts"]["total_pending"])
    tasks = payload.get("tasks")
    if isinstance(tasks, list):
        for t in tasks:
            if not isinstance(t, dict) or not t.get("id"):
                continue
            upsert_task(data, t["id"], t.get("title", t["id"]),
                        t.get("category", "Lainnya"),
                        t.get("status", "open"), t.get("due"),
                        t.get("note", ""))
            changes.append("task %s -> %s" % (t["id"], t.get("status")))
    return changes


if __name__ == "__main__":
    import sys

    def _pakai():
        print("Pakai: python3 status.py show [file]")
        print("       python3 status.py run <job_id> <ok|failed|pending|blocked|idle> [ringkasan]")
        print("       python3 status.py init [file]")

    args = sys.argv[1:]
    if not args:
        _pakai()
    elif args[0] == "show":
        print(json.dumps(load_status(args[1] if len(args) > 1 else DEFAULT_PATH),
                         ensure_ascii=False, indent=2))
    elif args[0] == "init":
        path = args[1] if len(args) > 1 else DEFAULT_PATH
        save_status(new_status(), path)
        print("status kosong dibuat di %s" % path)
    elif args[0] == "run" and len(args) >= 3:
        path = os.environ.get("STATUS_FILE", DEFAULT_PATH)
        mark_run(path, args[1], args[2], " ".join(args[3:]))
        print("job %s dicatat: %s" % (args[1], args[2]))
    else:
        _pakai()
