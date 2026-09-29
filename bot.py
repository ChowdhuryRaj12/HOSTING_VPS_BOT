import os
import sys
import json
import time
import signal
import sqlite3
import subprocess
import threading
import ast
import shutil
import hashlib
import re
from pathlib import Path
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from concurrent.futures import ThreadPoolExecutor

import requests

# ============================================================
# SHIELD X HOSTING - VERSION 8.0 ULTRA
# ============================================================

APP_NAME = "SHIELD X HOSTING"
VERSION = "8.0"

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_CHAT_ID_RAW = os.getenv("OWNER_CHAT_ID", "").strip()

try:
    OWNER_CHAT_ID = int(OWNER_CHAT_ID_RAW)
except Exception:
    OWNER_CHAT_ID = 0

BOT_USERNAME = ""  # Polling শুরুতে অটো ফেচ হবে

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "host_data"))).expanduser()
CLIENTS_DIR = DATA_DIR / "clients"
DB_FILE = DATA_DIR / "hosting.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)
CLIENTS_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# RUNTIME & STATE MANAGEMENT
# ============================================================

processes = {}
process_lock = threading.RLock()
stop_requested = set()
bot_operation_locks = {}
bot_operation_locks_lock = threading.RLock()

# Interactive User States
# chat_id -> {"state": "...", "data": {...}}
user_conversations = {}
user_conversations_lock = threading.RLock()

telegram_offset = 0
telegram_session = requests.Session()
MAX_LOG_CHARS = 10000

# ============================================================
# MULTI-LANGUAGE STRINGS (বাংলা & ENGLISH)
# ============================================================

MESSAGES = {
    "bn": {
        "welcome": "👋 স্বাগতম <b>{name}</b>!\n\n🚀 <b>{app_name}</b> এ আপনাকে স্বাগতম। এখান থেকে আপনি খুব সহজেই আপনার পাইথন টেলিগ্রাম বট ২৪/৭ হোস্ট করতে পারবেন।\n\nনিচের মেনু থেকে আপনার কাঙ্ক্ষিত অপশন সিলেক্ট করুন:",
        "profile": "👤 <b>আপনার প্রোফাইল</b>\n\n👋 হ্যালো, <b>{name}</b>\n🔹 ইউজারনেম: @{username}\n🆔 চ্যাট আইডি: <code>{chat_id}</code>\n💰 ব্যালেন্স: <b>{balance:.2f} টাকা</b>\n📦 মেয়াদের অবস্থা: <b>{plan_status}</b>\n🤖 হোস্ট করা বট: <b>{bot_count}/{bot_limit}</b>\n🌐 ভাষা: <b>বাংলা</b>",
        "no_plan_deploy": "❌ <b>দুঃখিত!</b> আপনার কোনো একটিভ সাবস্ক্রিপশন প্ল্যান নেই।\nবট হোস্ট করার জন্য দয়া করে প্রথমে <b>BUY PACK</b> থেকে একটি প্ল্যান কিনুন।",
        "bot_limit_exceeded": "❌ আপনি আপনার সর্বোচ্চ বটের সীমা ({limit} টি) অতিক্রম করেছেন!",
        "balance": "💰 <b>আপনার অ্যাকাউন্ট ব্যালেন্স</b>\n\nবর্তমান ব্যালেন্স: <b>{balance:.2f} টাকা</b>\n\nব্যালেন্স রিচার্জ করতে <b>DEPOSITE</b> বাটনে ক্লিক করুন।",
        "buy_pack_title": "📦 <b>প্যাকেজ নির্বাচন করুন</b>\n\nআপনার পছন্দের মেয়াদের প্যাকেজ কিনতে নিচের বাটনে ক্লিক করুন:\n(আপনার ব্যালেন্স: <b>{balance:.2f} টাকা</b>)",
        "pack_bought_success": "🎉 অভিনন্দন! <b>{name}</b> সফলভাবে সক্রিয় করা হয়েছে। মেয়াদ বৃদ্ধি পেয়েছে: {days} দিন।",
        "insufficient_balance": "❌ আপনার একাউন্টে পর্যাপ্ত ব্যালেন্স নেই! প্রয়োজন: {price} টাকা। দয়া করে আগে ডিপোজিট করুন।",
        "deposit_select": "💳 <b>ডিপোজিট মেথড সিলেক্ট করুন</b>\n\nটাকা পাঠানোর জন্য যেকোনো একটি মাধ্যম নির্বাচন করুন:",
        "refer_text": "👥 <b>রেফার করে আয় করুন</b>\n\nআপনার বন্ধুদের আমাদের বট শেয়ার করে আকর্ষণীয় বোনাস জিতে নিন!\n\n🔗 <b>আপনার রেফারেল লিঙ্ক:</b>\n<code>{link}</code>\n\n🎁 প্রতি সফল রেফারে পাবেন: <b>{reward:.2f} টাকা</b>\n📊 মোট রেফার করেছেন: <b>{ref_count} জন</b>",
        "support": "💬 <b>সাপোর্ট ও যোগাযোগ</b>\n\nযেকোনো প্রশ্ন বা সহায়তার জন্য আমাদের সাপোর্টে যোগাযোগ করুন:",
        "help": "❓ <b>হেল্প ও নির্দেশিকা</b>\n\n{help_text}",
        "force_join": "⚠️ <b>চ্যানেলে জয়েন করা বাধ্যতামূলক!</b>\n\nবটটি ব্যবহার করতে আপনাকে প্রথমে আমাদের অফিসিয়াল চ্যানেলে জয়েন করতে হবে।\n\nচ্যানেল: @{channel}",
        "banned": "🚫 <b>আপনার অ্যাকাউন্টটি ব্যান করা হয়েছে!</b>\nআপনি এই বটটি আর ব্যবহার করতে পারবেন না।"
    },
    "en": {
        "welcome": "👋 Welcome <b>{name}</b>!\n\n🚀 Welcome to <b>{app_name}</b>. Host your Python Telegram Bots 24/7 with zero hassle.\n\nChoose an option from the menu below:",
        "profile": "👤 <b>Your Profile</b>\n\n👋 Hello, <b>{name}</b>\n🔹 Username: @{username}\n🆔 Chat ID: <code>{chat_id}</code>\n💰 Balance: <b>{balance:.2f} BDT</b>\n📦 Plan Status: <b>{plan_status}</b>\n🤖 Hosted Bots: <b>{bot_count}/{bot_limit}</b>\n🌐 Language: <b>English</b>",
        "no_plan_deploy": "❌ Sorry! You do not have an active subscription plan. Please buy a plan from BUY PACK first.",
        "bot_limit_exceeded": "❌ You have reached your maximum bot limit ({limit} bots)!",
        "balance": "💰 <b>Your Account Balance</b>\n\nCurrent Balance: <b>{balance:.2f} BDT</b>\n\nClick <b>DEPOSITE</b> to top-up your balance.",
        "buy_pack_title": "📦 <b>Select a Hosting Package</b>\n\nClick a button to purchase a plan:\n(Your Balance: <b>{balance:.2f} BDT</b>)",
        "pack_bought_success": "🎉 Congratulations! <b>{name}</b> has been activated. Extended by {days} days.",
        "insufficient_balance": "❌ Insufficient balance! Required: {price} BDT. Please deposit first.",
        "deposit_select": "💳 <b>Select Deposit Method</b>\n\nChoose a payment option below:",
        "refer_text": "👥 <b>Refer & Earn</b>\n\nInvite your friends and earn rewards!\n\n🔗 <b>Your Referral Link:</b>\n<code>{link}</code>\n\n🎁 Reward per referral: <b>{reward:.2f} BDT</b>\n📊 Total Referrals: <b>{ref_count} users</b>",
        "support": "💬 <b>Support & Assistance</b>\n\nIf you need any help, contact our support team:",
        "help": "❓ <b>Help & FAQ</b>\n\n{help_text}",
        "force_join": "⚠️ <b>Channel Join Required!</b>\n\nYou must join our official channel to use this bot.\n\nChannel: @{channel}",
        "banned": "🚫 <b>Your account has been banned!</b>\nYou are restricted from using this bot."
    }
}

# ============================================================
# PACKAGES & STDLIB
# ============================================================

IMPORT_TO_PACKAGE = {
    "telegram": "python-telegram-bot==22.5",
    "telegram.ext": "python-telegram-bot==22.5",
    "openai": "openai>=1.50.0,<2",
    "requests": "requests>=2.31.0",
    "httpx": "httpx",
    "aiohttp": "aiohttp",
    "flask": "Flask",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "bs4": "beautifulsoup4",
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "dotenv": "python-dotenv",
    "yaml": "PyYAML",
    "Crypto": "pycryptodome",
    "numpy": "numpy",
    "pandas": "pandas",
    "qrcode": "qrcode",
    "schedule": "schedule",
    "rich": "rich",
    "colorama": "colorama",
    "selenium": "selenium",
    "jwt": "PyJWT",
    "google": "google-api-python-client",
    "discord": "discord.py",
    "psutil": "psutil"
}

STDLIB_MODULES = set(getattr(sys, "stdlib_module_names", set()))
STDLIB_MODULES.update({
    "os", "sys", "re", "json", "time", "math", "random", "datetime",
    "calendar", "sqlite3", "subprocess", "threading", "signal", "pathlib",
    "typing", "asyncio", "logging", "traceback", "collections", "itertools",
    "functools", "statistics", "hashlib", "secrets", "uuid", "base64",
    "urllib", "http", "email", "socket", "ssl", "csv", "io", "tempfile",
    "shutil", "zipfile", "glob", "inspect", "dataclasses", "enum"
})

# ============================================================
# DATABASE SETUP
# ============================================================

db_lock = threading.RLock()

def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def init_db():
    with db_lock:
        conn = get_db()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS clients (
                    chat_id INTEGER PRIMARY KEY,
                    username TEXT DEFAULT '',
                    first_name TEXT DEFAULT '',
                    last_name TEXT DEFAULT '',
                    balance REAL DEFAULT 0.0,
                    language TEXT DEFAULT 'bn',
                    plan_expires_at TEXT DEFAULT '',
                    referred_by INTEGER DEFAULT 0,
                    is_banned INTEGER DEFAULT 0,
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT '',
                    last_seen TEXT DEFAULT ''
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS bots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_chat_id INTEGER NOT NULL,
                    name TEXT DEFAULT '',
                    filename TEXT DEFAULT '',
                    folder TEXT DEFAULT '',
                    status TEXT DEFAULT 'stopped',
                    pid INTEGER DEFAULT 0,
                    auto_restart INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT '',
                    updated_at TEXT DEFAULT ''
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS packages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    days INTEGER NOT NULL,
                    price REAL NOT NULL
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS deposit_methods (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    number TEXT NOT NULL,
                    instructions TEXT DEFAULT ''
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS deposits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    method_name TEXT NOT NULL,
                    amount REAL NOT NULL,
                    trx_id TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT DEFAULT ''
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS global_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT DEFAULT ''
                )
            """)

            # Default global settings
            defaults = [
                ("bot_limit", "10"),
                ("refer_reward", "5.0"),
                ("force_join_enabled", "0"),
                ("force_join_channel", ""),
                ("support_link", "https://t.me/telegram"),
                ("help_text", "1. আপলোড বাটন প্রেস করে .py ফাইল দিন।\n2. প্যাকেজ কিনে ডিপ্লয় করুন।\n3. 24/7 লাইভ থাকবে।")
            ]
            for k, v in defaults:
                conn.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES (?, ?)", (k, v))

            # Default packages if empty
            if conn.execute("SELECT COUNT(*) as c FROM packages").fetchone()["c"] == 0:
                conn.execute("INSERT INTO packages (name, days, price) VALUES ('3 Days VPS', 3, 30.0)")
                conn.execute("INSERT INTO packages (name, days, price) VALUES ('7 Days VPS', 7, 60.0)")
                conn.execute("INSERT INTO packages (name, days, price) VALUES ('30 Days VPS', 30, 200.0)")

            # Default deposit methods if empty
            if conn.execute("SELECT COUNT(*) as c FROM deposit_methods").fetchone()["c"] == 0:
                conn.execute("INSERT INTO deposit_methods (name, number, instructions) VALUES ('Bkash (Personal)', '01XXXXXXXXX', 'Send Money করুন এবং Transaction ID সাবমিট করুন।')")
                conn.execute("INSERT INTO deposit_methods (name, number, instructions) VALUES ('Nagad (Personal)', '01XXXXXXXXX', 'Send Money করুন এবং Transaction ID সাবমিট করুন।')")

            conn.commit()
        finally:
            conn.close()

def get_setting(key, default=""):
    with db_lock:
        conn = get_db()
        try:
            r = conn.execute("SELECT value FROM global_settings WHERE key=?", (key,)).fetchone()
            return r["value"] if r else default
        finally:
            conn.close()

def set_setting(key, value):
    with db_lock:
        conn = get_db()
        try:
            conn.execute("INSERT INTO global_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
            conn.commit()
        finally:
            conn.close()

# ============================================================
# TELEGRAM API HELPERS
# ============================================================

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

def telegram(method, data=None, timeout=60):
    try:
        res = telegram_session.post(f"{TG_API}/{method}", data=data or {}, timeout=timeout)
        if not res.ok:
            return None
        return res.json()
    except Exception as e:
        print(f"[TG ERROR] {method}: {e}")
        return None

def send_message(chat_id, text, reply_markup=None):
    data = {
        "chat_id": int(chat_id),
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if reply_markup is not None:
        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    return telegram("sendMessage", data, timeout=30)

def edit_message(chat_id, message_id, text, reply_markup=None):
    data = {
        "chat_id": int(chat_id),
        "message_id": int(message_id),
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if reply_markup is not None:
        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    return telegram("editMessageText", data, timeout=30)

def answer_callback(callback_id, text="", alert=False):
    if not callback_id:
        return
    return telegram("answerCallbackQuery", {
        "callback_query_id": callback_id,
        "text": str(text)[:190],
        "show_alert": alert
    }, timeout=15)

def escape_html(val):
    if val is None:
        return ""
    return str(val).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def send_long_message(chat_id, text, reply_markup=None):
    limit = 3800
    if len(text) <= limit:
        return send_message(chat_id, text, reply_markup)
    chunks = [text[i:i + limit] for i in range(0, len(text), limit)]
    for idx, c in enumerate(chunks):
        send_message(chat_id, c, reply_markup if idx == len(chunks) - 1 else None)

def is_owner(chat_id):
    try:
        return int(chat_id) == OWNER_CHAT_ID
    except Exception:
        return False

# ============================================================
# USER & SUBSCRIPTION HELPERS
# ============================================================

def get_client(chat_id):
    with db_lock:
        conn = get_db()
        try:
            return conn.execute("SELECT * FROM clients WHERE chat_id=?", (int(chat_id),)).fetchone()
        finally:
            conn.close()

def upsert_client(user, ref_id=0):
    chat_id = int(user.get("id", 0))
    if not chat_id:
        return False, False
    created = False
    with db_lock:
        conn = get_db()
        try:
            row = conn.execute("SELECT * FROM clients WHERE chat_id=?", (chat_id,)).fetchone()
            if row is None:
                created = True
                conn.execute("""
                    INSERT INTO clients (chat_id, username, first_name, last_name, balance, language, plan_expires_at, referred_by, is_banned, enabled, created_at, last_seen)
                    VALUES (?, ?, ?, ?, 0.0, 'bn', '', ?, 0, 1, ?, ?)
                """, (chat_id, user.get("username", "") or "", user.get("first_name", "") or "", user.get("last_name", "") or "", ref_id, now(), now()))
            else:
                conn.execute("""
                    UPDATE clients SET username=?, first_name=?, last_name=?, last_seen=? WHERE chat_id=?
                """, (user.get("username", "") or "", user.get("first_name", "") or "", user.get("last_name", "") or "", now(), chat_id))
            conn.commit()
        finally:
            conn.close()
    return created, row

def user_lang(chat_id):
    c = get_client(chat_id)
    return c["language"] if c and c["language"] in ["bn", "en"] else "bn"

def t(chat_id, key, **kwargs):
    lang = user_lang(chat_id)
    tmpl = MESSAGES.get(lang, MESSAGES["bn"]).get(key, "")
    return tmpl.format(**kwargs)

def has_active_plan(chat_id):
    if is_owner(chat_id):
        return True
    c = get_client(chat_id)
    if not c or not c["plan_expires_at"]:
        return False
    try:
        exp = datetime.strptime(c["plan_expires_at"], "%Y-%m-%d %H:%M:%S")
        return exp > datetime.now()
    except Exception:
        return False

def add_user_subscription(chat_id, days):
    c = get_client(chat_id)
    cur_exp = None
    if c and c["plan_expires_at"]:
        try:
            dt = datetime.strptime(c["plan_expires_at"], "%Y-%m-%d %H:%M:%S")
            if dt > datetime.now():
                cur_exp = dt
        except Exception:
            pass
    start_time = cur_exp if cur_exp else datetime.now()
    new_exp = (start_time + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with db_lock:
        conn = get_db()
        try:
            conn.execute("UPDATE clients SET plan_expires_at=? WHERE chat_id=?", (new_exp, int(chat_id)))
            conn.commit()
        finally:
            conn.close()
    return new_exp

def check_force_join(chat_id):
    if is_owner(chat_id):
        return True
    enabled = get_setting("force_join_enabled", "0") == "1"
    channel = get_setting("force_join_channel", "").strip().replace("@", "")
    if not enabled or not channel:
        return True
    res = telegram("getChatMember", {"chat_id": f"@{channel}", "user_id": chat_id})
    if res and res.get("ok"):
        status = res.get("result", {}).get("status", "")
        if status in ["member", "administrator", "creator"]:
            return True
    return False

# ============================================================
# KEYBOARDS
# ============================================================

def main_reply_keyboard(chat_id):
    # Persistent reply keyboard as requested
    kb = [
        [{"text": "👤 PROFILE"}, {"text": "🚀 DEPLY BOT"}],
        [{"text": "📦 BUY PACK"}, {"text": "💰 BALANCE"}],
        [{"text": "💳 DEPOSITE"}, {"text": "👥 REFER & EARN"}],
        [{"text": "🌐 LANGUAGE"}, {"text": "💬 SUPPORT"}, {"text": "❓ HELP"}]
    ]
    if is_owner(chat_id):
        kb.append([{"text": "👑 ADMIN PANEL"}])
    return {"keyboard": kb, "resize_keyboard": True}

# ============================================================
# BOT HOSTING & PROCESS MANAGEMENT (PRESERVED & ISOLATED)
# ============================================================

def create_bot(owner_chat_id, name, filename, folder):
    with db_lock:
        conn = get_db()
        try:
            c = conn.execute("""
                INSERT INTO bots (owner_chat_id, name, filename, folder, status, pid, auto_restart, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'stopped', 0, 1, ?, ?)
            """, (int(owner_chat_id), name, filename, folder, now(), now()))
            conn.commit()
            return int(c.lastrowid)
        finally:
            conn.close()

def get_bot(bot_id):
    with db_lock:
        conn = get_db()
        try:
            return conn.execute("SELECT * FROM bots WHERE id=?", (int(bot_id),)).fetchone()
        finally:
            conn.close()

def get_bots(owner_chat_id=None):
    with db_lock:
        conn = get_db()
        try:
            if owner_chat_id is None:
                return conn.execute("SELECT * FROM bots ORDER BY id DESC").fetchall()
            return conn.execute("SELECT * FROM bots WHERE owner_chat_id=? ORDER BY id DESC", (int(owner_chat_id),)).fetchall()
        finally:
            conn.close()

def update_bot(bot_id, **fields):
    allowed = {"name", "filename", "folder", "status", "pid", "auto_restart", "updated_at"}
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        return
    clean["updated_at"] = now()
    assignments = [f"{k}=?" for k in clean.keys()]
    values = list(clean.values()) + [int(bot_id)]
    with db_lock:
        conn = get_db()
        try:
            conn.execute(f"UPDATE bots SET {', '.join(assignments)} WHERE id=?", values)
            conn.commit()
        finally:
            conn.close()

def get_bot_operation_lock(bot_id):
    bot_id = int(bot_id)
    with bot_operation_locks_lock:
        if bot_id not in bot_operation_locks:
            bot_operation_locks[bot_id] = threading.RLock()
        return bot_operation_locks[bot_id]

def client_folder(chat_id):
    folder = CLIENTS_DIR / str(int(chat_id))
    folder.mkdir(parents=True, exist_ok=True)
    return folder

def bot_script(row):
    return Path(row["folder"]) / row["filename"]

def bot_log_file(row):
    return Path(row["folder"]) / "bot.log"

def write_log(path, text):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", errors="ignore") as f:
            f.write(str(text))
    except Exception:
        pass

def read_log(row, max_chars=MAX_LOG_CHARS):
    p = bot_log_file(row)
    if not p.exists():
        return "No logs available."
    try:
        data = p.read_text(encoding="utf-8", errors="ignore")
        if len(data) > max_chars:
            data = "… older logs trimmed …\n\n" + data[-max_chars:]
        return data or "Log is empty."
    except Exception as e:
        return f"Log error: {e}"

def detect_imports(script):
    modules = set()
    try:
        source = script.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source, filename=str(script))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[0])
    except Exception:
        pass
    return modules

def detect_packages(script):
    modules = detect_imports(script)
    pkgs = set()
    for mod in modules:
        if not mod or mod == script.stem or mod in STDLIB_MODULES:
            continue
        pkgs.add(IMPORT_TO_PACKAGE.get(mod, mod))
    return sorted(pkgs)

def venv_python(folder):
    folder = Path(folder)
    return folder / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

def ensure_venv(folder, log_file):
    python = venv_python(folder)
    if python.exists():
        return python
    write_log(log_file, "\n[HOST] Initializing clean virtual environment...\n")
    res = subprocess.run([sys.executable, "-m", "venv", str(Path(folder) / ".venv")],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300)
    write_log(log_file, res.stdout or "")
    if res.returncode != 0:
        raise RuntimeError("Venv creation failed.")
    return python

def install_dependencies(folder, script, log_file):
    pkgs = detect_packages(script)
    marker = Path(folder) / ".dep_hash"
    cur_hash = hashlib.sha256((script.read_bytes() + b"\n" + "\n".join(pkgs).encode())).hexdigest()
    if marker.exists():
        try:
            if marker.read_text(encoding="utf-8").strip() == cur_hash:
                return
        except Exception:
            pass

    python = ensure_venv(folder, log_file)
    if not pkgs:
        marker.write_text(cur_hash, encoding="utf-8")
        return

    write_log(log_file, f"\n[HOST] Installing Auto-Detected Packages: {', '.join(pkgs)}\n")
    res = subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", *pkgs],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=1200)
    write_log(log_file, res.stdout or "")
    if res.returncode != 0:
        raise RuntimeError("Dependency installation failed.")
    marker.write_text(cur_hash, encoding="utf-8")

def process_alive(p):
    return p is not None and p.poll() is None

def kill_process(p):
    if not p:
        return
    try:
        if os.name == "posix":
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except Exception:
                p.kill()
        else:
            p.kill()
    except Exception:
        pass

def start_bot(bot_id):
    bot_id = int(bot_id)
    with get_bot_operation_lock(bot_id):
        row = get_bot(bot_id)
        if not row:
            return False, "Bot not found."

        owner_id = int(row["owner_chat_id"])
        if not has_active_plan(owner_id):
            return False, "❌ Subscription plan expired. Please buy a pack first."

        folder = Path(row["folder"])
        script = bot_script(row)
        if not script.exists():
            update_bot(bot_id, status="error", pid=0)
            return False, "Python file not found."

        with process_lock:
            cur = processes.get(bot_id)
            if cur and process_alive(cur):
                return False, "Bot is already running."
            stop_requested.discard(bot_id)

        log_f = bot_log_file(row)
        write_log(log_f, f"\n{'='*50}\n[HOST] STARTING BOT #{bot_id} at {now()}\n{'='*50}\n")
        try:
            compile(script.read_text(encoding="utf-8", errors="ignore"), str(script), "exec")
            python = ensure_venv(folder, log_f)
            install_dependencies(folder, script, log_f)
            out = open(log_f, "a", encoding="utf-8", errors="ignore")
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            cmd = [str(python), str(script)]

            if os.name == "posix":
                p = subprocess.Popen(cmd, cwd=str(folder), stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env, start_new_session=True)
            else:
                p = subprocess.Popen(cmd, cwd=str(folder), stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env)

            out.close()
            with process_lock:
                processes[bot_id] = p
                stop_requested.discard(bot_id)

            update_bot(bot_id, status="running", pid=p.pid)
            write_log(log_f, f"[HOST] Bot started successfully. PID: {p.pid}\n")
            threading.Thread(target=watch_process, args=(bot_id, p), daemon=True).start()
            return True, f"Bot started successfully! PID: {p.pid}"
        except Exception as e:
            write_log(log_f, f"\n[HOST ERROR] {repr(e)}\n")
            update_bot(bot_id, status="error", pid=0)
            return False, str(e)

def watch_process(bot_id, proc):
    try:
        proc.wait()
    except Exception:
        pass
    row = get_bot(bot_id)
    if row:
        write_log(bot_log_file(row), f"\n[HOST] Process terminated at {now()}.\n")

    with process_lock:
        if processes.get(bot_id) is proc:
            processes.pop(bot_id, None)
        intentional = bot_id in stop_requested

    row = get_bot(bot_id)
    if not row or intentional:
        update_bot(bot_id, status="stopped", pid=0)
        return

    # Check active plan before auto restart
    if not has_active_plan(int(row["owner_chat_id"])):
        update_bot(bot_id, status="stopped", pid=0)
        return

    if bool(row["auto_restart"]):
        update_bot(bot_id, status="restarting", pid=0)
        time.sleep(2)
        start_bot(bot_id)
    else:
        update_bot(bot_id, status="stopped", pid=0)

def stop_bot(bot_id, intentional=True):
    bot_id = int(bot_id)
    with get_bot_operation_lock(bot_id):
        row = get_bot(bot_id)
        if not row:
            return False, "Bot not found."
        if intentional:
            with process_lock:
                stop_requested.add(bot_id)
        with process_lock:
            p = processes.get(bot_id)
        if p and process_alive(p):
            kill_process(p)
            try:
                p.wait(timeout=2)
            except Exception:
                pass
        with process_lock:
            processes.pop(bot_id, None)
        update_bot(bot_id, status="stopped", pid=0)
        return True, "Bot stopped successfully."

def restart_bot(bot_id):
    stop_bot(bot_id, intentional=True)
    time.sleep(1)
    return start_bot(bot_id)

def stop_all_user_bots(chat_id):
    for b in get_bots(chat_id):
        stop_bot(int(b["id"]), intentional=True)

def delete_bot_permanently(bot_id):
    stop_bot(bot_id, intentional=True)
    row = get_bot(bot_id)
    if not row:
        return False, "Not found."
    with db_lock:
        conn = get_db()
        try:
            conn.execute("DELETE FROM bots WHERE id=?", (bot_id,))
            conn.commit()
        finally:
            conn.close()
    try:
        shutil.rmtree(Path(row["folder"]), ignore_errors=True)
    except Exception:
        pass
    return True, "Bot permanently deleted."

# ============================================================
# SUBSCRIPTION EXPIRY WATCHER
# ============================================================

def subscription_checker():
    while True:
        try:
            time.sleep(60)
            with db_lock:
                conn = get_db()
                try:
                    users = conn.execute("SELECT * FROM clients WHERE plan_expires_at != ''").fetchall()
                finally:
                    conn.close()

            cur = datetime.now()
            for u in users:
                if is_owner(u["chat_id"]):
                    continue
                try:
                    exp = datetime.strptime(u["plan_expires_at"], "%Y-%m-%d %H:%M:%S")
                    if exp <= cur:
                        # Plan Expired! Stop all bots
                        stop_all_user_bots(u["chat_id"])
                        with db_lock:
                            conn = get_db()
                            try:
                                conn.execute("UPDATE clients SET plan_expires_at='' WHERE chat_id=?", (u["chat_id"],))
                                conn.commit()
                            finally:
                                conn.close()
                        send_message(
                            u["chat_id"],
                            "⚠️ <b>আপনার সাবস্ক্রিপশন প্ল্যানের মেয়াদ শেষ হয়েছে!</b>\n\nআপনার হোস্ট করা সকল বট স্বয়ংক্রিয়ভাবে বন্ধ করা হয়েছে। দয়া করে <b>BUY PACK</b> থেকে নতুন প্ল্যান কিনে বট পুনরায় চালু করুন।"
                        )
                except Exception:
                    pass
        except Exception as e:
            print(f"[SUB CHECK ERROR] {e}")

# ============================================================
# UI PANELS & FLOWS
# ============================================================

def show_hosting_panel(chat_id, message_id=None):
    if not has_active_plan(chat_id):
        send_message(chat_id, t(chat_id, "no_plan_deploy"))
        return

    bots = get_bots(chat_id)
    txt = f"🚀 <b>DEPLOY & HOSTING MANAGER</b>\n\nহোস্ট করা বট: <b>{len(bots)}</b>\n\nনতুন বট হোস্ট করতে একটি <code>.py</code> ফাইল সরাসরি এই চ্যাটে সেন্ড করুন।"
    rows = []
    for b in bots:
        icon = "🟢" if b["status"] == "running" else "🔴"
        rows.append([{"text": f"{icon} #{b['id']} {b['name'][:20]}", "callback_data": f"cbot:{b['id']}"}])
    rows.append([{"text": "📤 Upload Bot Info", "callback_data": "uploadinfo"}])

    kb = {"inline_keyboard": rows}
    if message_id:
        edit_message(chat_id, message_id, txt, kb)
    else:
        send_message(chat_id, txt, kb)

def show_bot_detail(chat_id, bot_id, message_id=None):
    row = get_bot(bot_id)
    if not row or (int(row["owner_chat_id"]) != int(chat_id) and not is_owner(chat_id)):
        send_message(chat_id, "❌ Bot not found.")
        return

    icon = "🟢" if row["status"] == "running" else "🔴"
    txt = (
        f"🤖 <b>বট কন্ট্রোল প্যানেল</b>\n\n"
        f"আইডি: <code>{row['id']}</code>\n"
        f"নাম: <b>{escape_html(row['name'])}</b>\n"
        f"ফাইল: <code>{escape_html(row['filename'])}</code>\n"
        f"অবস্থা: {icon} <b>{str(row['status']).upper()}</b>\n"
        f"PID: <code>{row['pid']}</code>\n"
        f"Auto Restart: <b>{'ON' if row['auto_restart'] else 'OFF'}</b>"
    )

    prefix = "ob" if is_owner(chat_id) and int(row["owner_chat_id"]) != int(chat_id) else "cb"
    kb = {
        "inline_keyboard": [
            [
                {"text": "▶️ Start", "callback_data": f"{prefix}:s:{row['id']}"},
                {"text": "⏹ Stop", "callback_data": f"{prefix}:t:{row['id']}"}
            ],
            [
                {"text": "🔄 Restart", "callback_data": f"{prefix}:r:{row['id']}"},
                {"text": "📜 Logs", "callback_data": f"{prefix}:l:{row['id']}"}
            ],
            [
                {"text": "🗑️ Delete Bot", "callback_data": f"{prefix}:d:{row['id']}"}
            ],
            [
                {"text": "⬅️ Back", "callback_data": "refresh_hosting"}
            ]
        ]
    }
    if message_id:
        edit_message(chat_id, message_id, txt, kb)
    else:
        send_message(chat_id, txt, kb)

def show_admin_panel(chat_id, message_id=None):
    if not is_owner(chat_id):
        return

    with db_lock:
        conn = get_db()
        try:
            total_users = conn.execute("SELECT COUNT(*) as c FROM clients").fetchone()["c"]
            total_bots = conn.execute("SELECT COUNT(*) as c FROM bots").fetchone()["c"]
            running_bots = conn.execute("SELECT COUNT(*) as c FROM bots WHERE status='running'").fetchone()["c"]
        finally:
            conn.close()

    fj_state = "ON" if get_setting("force_join_enabled") == "1" else "OFF"
    limit = get_setting("bot_limit", "10")

    txt = (
        f"👑 <b>ADMIN CONTROL PANEL</b>\n\n"
        f"👥 মোট ইউজার: <b>{total_users}</b>\n"
        f"🤖 মোট বট: <b>{total_bots}</b> (🟢 {running_bots} Running)\n"
        f"🔒 Force Join: <b>{fj_state}</b>\n"
        f"⚙️ Bot Limit: <b>{limit}</b>"
    )

    kb = {
        "inline_keyboard": [
            [{"text": "👥 ইউজার লিস্ট ও বট", "callback_data": "adm_users"}, {"text": "🤖 সকল বটস", "callback_data": "adm_allbots"}],
            [{"text": "➕ ব্যালেন্স অ্যাড", "callback_data": "adm_add_bal"}, {"text": "📢 ব্রডকাস্ট", "callback_data": "adm_broadcast"}],
            [{"text": "📦 প্যাকেজ ম্যানেজমেন্ট", "callback_data": "adm_packs"}, {"text": "💳 ডিপোজিট মেথডস", "callback_data": "adm_dep_methods"}],
            [{"text": f"🔒 Force Join ({fj_state})", "callback_data": "adm_toggle_fj"}, {"text": "📢 চ্যানেল সেট", "callback_data": "adm_set_channel"}],
            [{"text": "🔢 বট লিমিট সেট", "callback_data": "adm_set_limit"}, {"text": "🎁 রেফার বোনাস সেট", "callback_data": "adm_set_ref"}],
            [{"text": "💬 সাপোর্ট লিঙ্ক সেট", "callback_data": "adm_set_support"}, {"text": "❓ হেল্প টেক্সট সেট", "callback_data": "adm_set_help"}],
            [{"text": "🚫 ব্যান / আনব্যান", "callback_data": "adm_ban_menu"}, {"text": "🔄 রিফ্রেশ", "callback_data": "adm_refresh"}]
        ]
    }

    if message_id:
        edit_message(chat_id, message_id, txt, kb)
    else:
        send_message(chat_id, txt, kb)

# ============================================================
# MESSAGE HANDLER
# ============================================================

def handle_message(msg):
    if not msg:
        return
    chat_id = msg.get("chat", {}).get("id")
    user = msg.get("from", {})
    text = (msg.get("text") or "").strip()

    if not chat_id or not user:
        return

    # Check ban
    client = get_client(chat_id)
    if client and client["is_banned"] and not is_owner(chat_id):
        send_message(chat_id, t(chat_id, "banned"))
        return

    # User conversation state handling
    with user_conversations_lock:
        conv = user_conversations.get(chat_id)

    if conv:
        state = conv.get("state")
        data = conv.get("data", {})

        # Deposit flows
        if state == "deposit_amount":
            try:
                amt = float(text)
                if amt <= 0:
                    raise ValueError
                with user_conversations_lock:
                    user_conversations[chat_id] = {"state": "deposit_trx", "data": {"method": data["method"], "amount": amt}}
                send_message(chat_id, f"✅ ডিপোজিট পরিমাণ: <b>{amt:.2f} টাকা</b>\n\nএখন আপনার পেমেন্টের <b>Transaction ID (TrxID)</b> টি সেন্ড করুন:")
            except ValueError:
                send_message(chat_id, "❌ অনুগ্রহ করে সঠিক টাকার পরিমাণ ইংরেজিতে সংখ্যায় লিখুন (যেমন: 100):")
            return

        elif state == "deposit_trx":
            trx = text
            amt = data["amount"]
            method = data["method"]
            with user_conversations_lock:
                user_conversations.pop(chat_id, None)

            with db_lock:
                conn = get_db()
                try:
                    c = conn.execute("INSERT INTO deposits (chat_id, method_name, amount, trx_id, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
                                     (chat_id, method, amt, trx, now()))
                    dep_id = c.lastrowid
                    conn.commit()
                finally:
                    conn.close()

            send_message(chat_id, "✅ <b>ডিপোজিট রিকোয়েস্ট জমা হয়েছে!</b>\nএডমিন ভেরিফাই করে কিছুক্ষণের মধ্যে আপনার ব্যালেন্স যুক্ত করে দেবে।")
            # Notify Admin
            admin_msg = (
                f"🔔 <b>নতুন ডিপোজিট নোটিশ!</b>\n\n"
                f"👤 ইউজার: @{user.get('username', 'N/A')} (<code>{chat_id}</code>)\n"
                f"💳 মাধ্যম: <b>{method}</b>\n"
                f"💰 পরিমাণ: <b>{amt:.2f} টাকা</b>\n"
                f"🧾 TrxID: <code>{escape_html(trx)}</code>"
            )
            admin_kb = {
                "inline_keyboard": [
                    [
                        {"text": "✅ Approve", "callback_data": f"dep_appr:{dep_id}"},
                        {"text": "❌ Reject", "callback_data": f"dep_rej:{dep_id}"}
                    ]
                ]
            }
            send_message(OWNER_CHAT_ID, admin_msg, admin_kb)
            return

        # Admin Settings Conversation States
        if is_owner(chat_id):
            if state == "adm_pack_name":
                with user_conversations_lock:
                    user_conversations[chat_id] = {"state": "adm_pack_days", "data": {"name": text}}
                send_message(chat_id, "প্যাকেজের মেয়াদ কত দিন হবে তা সংখ্যায় দিন (যেমন: 7):")
                return
            elif state == "adm_pack_days":
                try:
                    days = int(text)
                    with user_conversations_lock:
                        user_conversations[chat_id] = {"state": "adm_pack_price", "data": {"name": data["name"], "days": days}}
                    send_message(chat_id, "প্যাকেজের মূল্য কত টাকা তা লিখুন (যেমন: 50):")
                except ValueError:
                    send_message(chat_id, "❌ সংখ্যায় লিখুন:")
                return
            elif state == "adm_pack_price":
                try:
                    price = float(text)
                    with db_lock:
                        conn = get_db()
                        try:
                            conn.execute("INSERT INTO packages (name, days, price) VALUES (?, ?, ?)", (data["name"], data["days"], price))
                            conn.commit()
                        finally:
                            conn.close()
                    with user_conversations_lock:
                        user_conversations.pop(chat_id, None)
                    send_message(chat_id, "✅ প্যাকেজ সফলভাবে তৈরি হয়েছে!")
                    show_admin_panel(chat_id)
                except ValueError:
                    send_message(chat_id, "❌ সঠিক সংখ্যা লিখুন:")
                return

            elif state == "adm_dep_name":
                with user_conversations_lock:
                    user_conversations[chat_id] = {"state": "adm_dep_num", "data": {"name": text}}
                send_message(chat_id, "পেমেন্ট নম্বর দিন (যেমন: 017XXXXXXXX):")
                return
            elif state == "adm_dep_num":
                with user_conversations_lock:
                    user_conversations[chat_id] = {"state": "adm_dep_ins", "data": {"name": data["name"], "num": text}}
                send_message(chat_id, "ইন্সট্রাকশন বা নিয়ম লিখে দিন:")
                return
            elif state == "adm_dep_ins":
                with db_lock:
                    conn = get_db()
                    try:
                        conn.execute("INSERT INTO deposit_methods (name, number, instructions) VALUES (?, ?, ?)", (data["name"], data["num"], text))
                        conn.commit()
                    finally:
                        conn.close()
                with user_conversations_lock:
                    user_conversations.pop(chat_id, None)
                send_message(chat_id, "✅ নতুন ডিপোজিট মেথড যুক্ত হয়েছে!")
                show_admin_panel(chat_id)
                return

            elif state == "adm_set_limit":
                try:
                    lim = int(text)
                    set_setting("bot_limit", str(lim))
                    with user_conversations_lock:
                        user_conversations.pop(chat_id, None)
                    send_message(chat_id, f"✅ সর্বোচ্চ বট লিমিট নির্ধারণ করা হয়েছে: {lim}")
                    show_admin_panel(chat_id)
                except ValueError:
                    send_message(chat_id, "❌ সংখ্যা লিখুন:")
                return

            elif state == "adm_set_ref":
                try:
                    rew = float(text)
                    set_setting("refer_reward", str(rew))
                    with user_conversations_lock:
                        user_conversations.pop(chat_id, None)
                    send_message(chat_id, f"✅ রেফারেল রিওয়ার্ড নির্ধারণ করা হয়েছে: {rew:.2f} টাকা")
                    show_admin_panel(chat_id)
                except ValueError:
                    send_message(chat_id, "❌ সংখ্যা লিখুন:")
                return

            elif state == "adm_set_channel":
                ch = text.strip().replace("@", "")
                set_setting("force_join_channel", ch)
                with user_conversations_lock:
                    user_conversations.pop(chat_id, None)
                send_message(chat_id, f"✅ Force Join চ্যানেল সেট করা হয়েছে: @{ch}")
                show_admin_panel(chat_id)
                return

            elif state == "adm_set_support":
                set_setting("support_link", text.strip())
                with user_conversations_lock:
                    user_conversations.pop(chat_id, None)
                send_message(chat_id, "✅ সাপোর্ট লিঙ্ক আপডেট করা হয়েছে!")
                show_admin_panel(chat_id)
                return

            elif state == "adm_set_help":
                set_setting("help_text", text.strip())
                with user_conversations_lock:
                    user_conversations.pop(chat_id, None)
                send_message(chat_id, "✅ হেল্প মেসেজ আপডেট করা হয়েছে!")
                show_admin_panel(chat_id)
                return

            elif state == "adm_add_bal_user":
                try:
                    uid = int(text)
                    with user_conversations_lock:
                        user_conversations[chat_id] = {"state": "adm_add_bal_amount", "data": {"target": uid}}
                    send_message(chat_id, "কত টাকা যোগ করতে চান লিখুন:")
                except ValueError:
                    send_message(chat_id, "❌ সঠিক Chat ID দিন:")
                return

            elif state == "adm_add_bal_amount":
                try:
                    amt = float(text)
                    uid = data["target"]
                    with db_lock:
                        conn = get_db()
                        try:
                            conn.execute("UPDATE clients SET balance=balance+? WHERE chat_id=?", (amt, uid))
                            conn.commit()
                        finally:
                            conn.close()
                    with user_conversations_lock:
                        user_conversations.pop(chat_id, None)
                    send_message(chat_id, f"✅ {amt:.2f} টাকা যোগ করা হয়েছে ইউজার <code>{uid}</code> এর একাউন্টে।")
                    send_message(uid, f"🎉 অ্যাডমিন আপনার একাউন্টে <b>{amt:.2f} টাকা</b> ব্যালেন্স যোগ করেছেন!")
                except ValueError:
                    send_message(chat_id, "❌ সঠিক সংখ্যা লিখুন:")
                return

            elif state == "adm_ban_user":
                try:
                    uid = int(text)
                    with db_lock:
                        conn = get_db()
                        try:
                            conn.execute("UPDATE clients SET is_banned=1 WHERE chat_id=?", (uid,))
                            conn.commit()
                        finally:
                            conn.close()
                    stop_all_user_bots(uid)
                    with user_conversations_lock:
                        user_conversations.pop(chat_id, None)
                    send_message(chat_id, f"✅ ইউজার <code>{uid}</code> কে ব্যান করা হয়েছে!")
                except ValueError:
                    send_message(chat_id, "❌ সঠিক Chat ID লিখুন:")
                return

            elif state == "adm_unban_user":
                try:
                    uid = int(text)
                    with db_lock:
                        conn = get_db()
                        try:
                            conn.execute("UPDATE clients SET is_banned=0 WHERE chat_id=?", (uid,))
                            conn.commit()
                        finally:
                            conn.close()
                    with user_conversations_lock:
                        user_conversations.pop(chat_id, None)
                    send_message(chat_id, f"✅ ইউজার <code>{uid}</code> কে আনব্যান করা হয়েছে!")
                except ValueError:
                    send_message(chat_id, "❌ সঠিক Chat ID লিখুন:")
                return

            elif state == "adm_broadcast":
                with user_conversations_lock:
                    user_conversations.pop(chat_id, None)
                with db_lock:
                    conn = get_db()
                    try:
                        all_c = conn.execute("SELECT chat_id FROM clients").fetchall()
                    finally:
                        conn.close()
                count = 0
                for c in all_c:
                    try:
                        send_message(c["chat_id"], f"📢 <b>অফিসিয়াল নোটিশ:</b>\n\n{text}")
                        count += 1
                        time.sleep(0.05)
                    except Exception:
                        pass
                send_message(chat_id, f"✅ ব্রডকাস্ট সম্পন্ন! মোট <b>{count}</b> জনের কাছে মেসেজ পাঠানো হয়েছে।")
                return

    # Check referral on /start
    ref_id = 0
    if text.startswith("/start"):
        parts = text.split()
        if len(parts) > 1 and parts[1].startswith("ref_"):
            try:
                ref_id = int(parts[1].replace("ref_", ""))
                if ref_id == chat_id:
                    ref_id = 0
            except Exception:
                ref_id = 0

    is_new, _ = upsert_client(user, ref_id=ref_id)

    # If new referral user, reward referrer
    if is_new and ref_id > 0:
        reward = float(get_setting("refer_reward", "5.0"))
        with db_lock:
            conn = get_db()
            try:
                conn.execute("UPDATE clients SET balance = balance + ? WHERE chat_id=?", (reward, ref_id))
                conn.commit()
            finally:
                conn.close()
        send_message(ref_id, f"🎉 আপনার রেফারেল লিঙ্কে একজন নতুন ইউজার যুক্ত হয়েছে! আপনি <b>{reward:.2f} টাকা</b> বোনাস পেয়েছেন।")

    # Force Join Check
    if not check_force_join(chat_id):
        ch = get_setting("force_join_channel", "")
        send_message(
            chat_id,
            t(chat_id, "force_join", channel=ch),
            {"inline_keyboard": [
                [{"text": "📢 Join Channel", "url": f"https://t.me/{ch}"}],
                [{"text": "🔄 Check Membership", "callback_data": "check_membership"}]
            ]}
        )
        return

    # Handling Document (.py file upload)
    doc = msg.get("document")
    if doc:
        handle_file_upload(chat_id, doc)
        return

    # Commands & Button interactions
    if text.startswith("/start") or text == "🔄 Refresh":
        name = user.get("first_name", "User")
        send_message(chat_id, t(chat_id, "welcome", name=name, app_name=APP_NAME), main_reply_keyboard(chat_id))
        return

    if text == "👤 PROFILE":
        c = get_client(chat_id)
        b_count = len(get_bots(chat_id))
        b_limit = "Unlimited" if is_owner(chat_id) else get_setting("bot_limit", "10")
        plan_str = c["plan_expires_at"] if c and c["plan_expires_at"] else "No Active Plan"
        if is_owner(chat_id):
            plan_str = "👑 Lifetime Admin"
        send_message(
            chat_id,
            t(chat_id, "profile",
              name=user.get("first_name", "User"),
              username=user.get("username", "N/A"),
              chat_id=chat_id,
              balance=c["balance"] if c else 0.0,
              plan_status=plan_str,
              bot_count=b_count,
              bot_limit=b_limit)
        )
        return

    if text == "🚀 DEPLY BOT":
        show_hosting_panel(chat_id)
        return

    if text == "📦 BUY PACK":
        with db_lock:
            conn = get_db()
            try:
                packs = conn.execute("SELECT * FROM packages").fetchall()
            finally:
                conn.close()
        c = get_client(chat_id)
        bal = c["balance"] if c else 0.0
        kb = []
        for p in packs:
            kb.append([{"text": f"🛒 {p['days']} Days VPS - {p['price']:.0f} টাকা", "callback_data": f"buy_p:{p['id']}"}])
        send_message(chat_id, t(chat_id, "buy_pack_title", balance=bal), {"inline_keyboard": kb})
        return

    if text == "💰 BALANCE":
        c = get_client(chat_id)
        bal = c["balance"] if c else 0.0
        send_message(chat_id, t(chat_id, "balance", balance=bal))
        return

    if text == "💳 DEPOSITE":
        with db_lock:
            conn = get_db()
            try:
                methods = conn.execute("SELECT * FROM deposit_methods").fetchall()
            finally:
                conn.close()
        kb = []
        for m in methods:
            kb.append([{"text": f"💳 {m['name']}", "callback_data": f"dep_sel:{m['id']}"}])
        send_message(chat_id, t(chat_id, "deposit_select"), {"inline_keyboard": kb})
        return

    if text == "👥 REFER & EARN":
        global BOT_USERNAME
        ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{chat_id}"
        rew = float(get_setting("refer_reward", "5.0"))
        with db_lock:
            conn = get_db()
            try:
                ref_count = conn.execute("SELECT COUNT(*) as c FROM clients WHERE referred_by=?", (chat_id,)).fetchone()["c"]
            finally:
                conn.close()
        send_message(chat_id, t(chat_id, "refer_text", link=ref_link, reward=rew, ref_count=ref_count))
        return

    if text == "🌐 LANGUAGE":
        kb = {
            "inline_keyboard": [
                [{"text": "🇧🇩 বাংলা", "callback_data": "lang:bn"}, {"text": "🇺🇸 English", "callback_data": "lang:en"}]
            ]
        }
        send_message(chat_id, "🌐 অনুগ্রহ করে আপনার ভাষা নির্বাচন করুন / Select your language:", kb)
        return

    if text == "💬 SUPPORT":
        s_link = get_setting("support_link", "https://t.me/telegram")
        send_message(chat_id, t(chat_id, "support"), {"inline_keyboard": [[{"text": "💬 Contact Support", "url": s_link}]]})
        return

    if text == "❓ HELP":
        h_text = get_setting("help_text", "")
        send_message(chat_id, t(chat_id, "help", help_text=h_text))
        return

    if text == "👑 ADMIN PANEL" and is_owner(chat_id):
        show_admin_panel(chat_id)
        return

# ============================================================
# FILE UPLOAD (BOT DEPLOYMENT)
# ============================================================

def handle_file_upload(chat_id, doc):
    if not has_active_plan(chat_id):
        send_message(chat_id, t(chat_id, "no_plan_deploy"))
        return

    # Check bot limit
    if not is_owner(chat_id):
        limit = int(get_setting("bot_limit", "10"))
        if len(get_bots(chat_id)) >= limit:
            send_message(chat_id, t(chat_id, "bot_limit_exceeded", limit=limit))
            return

    fn = doc.get("file_name", "main.py")
    if not fn.lower().endswith(".py"):
        send_message(chat_id, "❌ শুধুমাত্র পাইথন (<code>.py</code>) ফাইল গ্রহণযোগ্য!")
        return

    send_message(chat_id, "⏳ ফাইল ডাউনলোড এবং সিনট্যাক্স চেক করা হচ্ছে...")
    res = telegram("getFile", {"file_id": doc.get("file_id")})
    if not res or not res.get("ok"):
        send_message(chat_id, "❌ টেলিগ্রাম ফাইল তথ্য পাওয়া যায়নি!")
        return

    fp = res["result"].get("file_path")
    try:
        r = telegram_session.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{fp}", timeout=120)
        r.raise_for_status()
    except Exception as e:
        send_message(chat_id, f"❌ ডাউনলোড ব্যর্থ হয়েছে: {e}")
        return

    # Create folder and save
    c_folder = client_folder(chat_id)
    tmp_name = f".upload_{hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:10]}"
    tmp_path = c_folder / tmp_name
    tmp_path.mkdir(parents=True, exist_ok=True)
    target_py = tmp_path / fn

    try:
        target_py.write_bytes(r.content)
        compile(target_py.read_text(encoding="utf-8", errors="ignore"), str(target_py), "exec")
    except SyntaxError as e:
        shutil.rmtree(tmp_path, ignore_errors=True)
        send_message(chat_id, f"❌ <b>Python Syntax Error:</b>\n<code>{escape_html(e)}</code>")
        return

    bot_name = Path(fn).stem
    bot_id = create_bot(chat_id, bot_name, fn, str(tmp_path))
    final_path = c_folder / f"bot_{bot_id}"
    tmp_path.rename(final_path)
    update_bot(bot_id, folder=str(final_path))

    send_message(
        chat_id,
        f"✅ <b>বট সফলভাবে আপলোড হয়েছে!</b>\n\n🆔 বট আইডি: <code>{bot_id}</code>\n📄 ফাইল: <code>{fn}</code>\n\nএখন নিচের বাটনে ক্লিক করে চালু করুন:",
        {"inline_keyboard": [
            [{"text": "▶️ Start Bot", "callback_data": f"cb:s:{bot_id}"}],
            [{"text": "🤖 Deployment List", "callback_data": "refresh_hosting"}]
        ]}
    )

# ============================================================
# CALLBACK HANDLER
# ============================================================

def handle_callback(q):
    if not q:
        return
    cid = q.get("id")
    data = q.get("data", "")
    msg = q.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    mid = msg.get("message_id")

    if not chat_id:
        return

    # Check Membership button
    if data == "check_membership":
        if check_force_join(chat_id):
            answer_callback(cid, "✅ ভেরিফিকেশন সফল হয়েছে!", alert=True)
            send_message(chat_id, "🎉 স্বাগতম! আপনি চ্যানেল জয়েন করেছেন। নিচের মেনু ব্যবহার করুন:", main_reply_keyboard(chat_id))
        else:
            answer_callback(cid, "❌ আপনি এখনো চ্যানেলে জয়েন করেননি!", alert=True)
        return

    # Language Switch
    if data.startswith("lang:"):
        l = data.split(":")[1]
        with db_lock:
            conn = get_db()
            try:
                conn.execute("UPDATE clients SET language=? WHERE chat_id=?", (l, chat_id))
                conn.commit()
            finally:
                conn.close()
        answer_callback(cid, "Language updated!")
        edit_message(chat_id, mid, "✅ ভাষা সফলভাবে পরিবর্তন করা হয়েছে / Language updated successfully!")
        return

    # Package Purchase
    if data.startswith("buy_p:"):
        pid = int(data.split(":")[1])
        with db_lock:
            conn = get_db()
            try:
                pack = conn.execute("SELECT * FROM packages WHERE id=?", (pid,)).fetchone()
                c = conn.execute("SELECT * FROM clients WHERE chat_id=?", (chat_id,)).fetchone()
            finally:
                conn.close()
        if not pack:
            answer_callback(cid, "প্যাকেজ পাওয়া যায়নি।")
            return
        if c["balance"] < pack["price"]:
            answer_callback(cid, "পর্যাপ্ত ব্যালেন্স নেই!", alert=True)
            return

        with db_lock:
            conn = get_db()
            try:
                conn.execute("UPDATE clients SET balance = balance - ? WHERE chat_id=?", (pack["price"], chat_id))
                conn.commit()
            finally:
                conn.close()
        add_user_subscription(chat_id, pack["days"])
        answer_callback(cid, "✅ প্যাকেজ কেনা সফল হয়েছে!", alert=True)
        edit_message(chat_id, mid, t(chat_id, "pack_bought_success", name=pack["name"], days=pack["days"]))
        return

    # Deposit selection
    if data.startswith("dep_sel:"):
        mid_id = int(data.split(":")[1])
        with db_lock:
            conn = get_db()
            try:
                meth = conn.execute("SELECT * FROM deposit_methods WHERE id=?", (mid_id,)).fetchone()
            finally:
                conn.close()
        if not meth:
            answer_callback(cid, "মেথড পাওয়া যায়নি।")
            return
        answer_callback(cid)
        txt = (
            f"💳 <b>{meth['name']}</b>\n\n"
            f"নম্বর: <code>{meth['number']}</code> (Tap to Copy)\n\n"
            f"📌 নিয়ম:\n{meth['instructions']}\n\n"
            f"টাকা পাঠানোর পর নিচের <b>Done</b> বাটনে ক্লিক করুন।"
        )
        kb = {"inline_keyboard": [[{"text": "✅ Done", "callback_data": f"dep_done:{meth['id']}"}]]}
        edit_message(chat_id, mid, txt, kb)
        return

    if data.startswith("dep_done:"):
        mid_id = int(data.split(":")[1])
        with db_lock:
            conn = get_db()
            try:
                meth = conn.execute("SELECT * FROM deposit_methods WHERE id=?", (mid_id,)).fetchone()
            finally:
                conn.close()
        answer_callback(cid)
        with user_conversations_lock:
            user_conversations[chat_id] = {"state": "deposit_amount", "data": {"method": meth["name"] if meth else "Unknown"}}
        send_message(chat_id, "💵 আপনি কত টাকা পাঠিয়েছেন তার পরিমাণ ইংরেজিতে সংখ্যায় লিখুন (যেমন: 100):")
        return

    # Admin Deposit Approve / Reject
    if data.startswith("dep_appr:") and is_owner(chat_id):
        dep_id = int(data.split(":")[1])
        with db_lock:
            conn = get_db()
            try:
                d = conn.execute("SELECT * FROM deposits WHERE id=?", (dep_id,)).fetchone()
                if d and d["status"] == "pending":
                    conn.execute("UPDATE deposits SET status='approved' WHERE id=?", (dep_id,))
                    conn.execute("UPDATE clients SET balance = balance + ? WHERE chat_id=?", (d["amount"], d["chat_id"]))
                    conn.commit()
                    answer_callback(cid, "Approved!")
                    edit_message(chat_id, mid, f"✅ Deposit #{dep_id} Approved! (+{d['amount']} BDT to {d['chat_id']})")
                    send_message(d["chat_id"], f"🎉 আপনার <b>{d['amount']:.2f} টাকা</b> ডিপোজিট সফলভাবে অ্যাপ্রুভ হয়েছে এবং একাউন্টে যোগ করা হয়েছে!")
                else:
                    answer_callback(cid, "Already processed.")
            finally:
                conn.close()
        return

    if data.startswith("dep_rej:") and is_owner(chat_id):
        dep_id = int(data.split(":")[1])
        with db_lock:
            conn = get_db()
            try:
                d = conn.execute("SELECT * FROM deposits WHERE id=?", (dep_id,)).fetchone()
                if d and d["status"] == "pending":
                    conn.execute("UPDATE deposits SET status='rejected' WHERE id=?", (dep_id,))
                    conn.commit()
                    answer_callback(cid, "Rejected.")
                    edit_message(chat_id, mid, f"❌ Deposit #{dep_id} Rejected.")
                    send_message(d["chat_id"], f"❌ আপনার <b>{d['amount']:.2f} টাকা</b> ডিপোজিট রিকোয়েস্ট বাতিল করা হয়েছে। সঠিক TrxID দিয়ে পুনরায় চেষ্টা করুন।")
                else:
                    answer_callback(cid, "Already processed.")
            finally:
                conn.close()
        return

    # Bot Management Actions (cb:action:id & ob:action:id)
    if data.startswith("cb:") or data.startswith("ob:"):
        parts = data.split(":")
        action, bid = parts[1], int(parts[2])
        answer_callback(cid)

        if action == "s":
            s, m = start_bot(bid)
            send_message(chat_id, f"▶️ {m}")
        elif action == "t":
            s, m = stop_bot(bid, intentional=True)
            send_message(chat_id, f"⏹ {m}")
        elif action == "r":
            s, m = restart_bot(bid)
            send_message(chat_id, f"🔄 {m}")
        elif action == "l":
            row = get_bot(bid)
            send_long_message(chat_id, f"📜 <b>LOGS #{bid}</b>\n\n<pre>{escape_html(read_log(row))}</pre>")
        elif action == "d":
            s, m = delete_bot_permanently(bid)
            send_message(chat_id, f"🗑️ {m}")
            show_hosting_panel(chat_id)
            return

        show_bot_detail(chat_id, bid)
        return

    if data.startswith("cbot:"):
        bid = int(data.split(":")[1])
        answer_callback(cid)
        show_bot_detail(chat_id, bid, mid)
        return

    if data == "refresh_hosting":
        answer_callback(cid)
        show_hosting_panel(chat_id, mid)
        return

    # ADMIN PANEL CALLBACKS
    if is_owner(chat_id):
        if data == "adm_refresh":
            answer_callback(cid)
            show_admin_panel(chat_id, mid)
            return

        if data == "adm_users":
            answer_callback(cid)
            with db_lock:
                conn = get_db()
                try:
                    users = conn.execute("SELECT * FROM clients ORDER BY created_at DESC LIMIT 50").fetchall()
                finally:
                    conn.close()
            txt = "👥 <b>ইউজার ও তাদের বট সংখ্যা:</b>\n\n"
            for u in users:
                b_cnt = len(get_bots(u["chat_id"]))
                ban = " [BANNED]" if u["is_banned"] else ""
                txt += f"• <code>{u['chat_id']}</code> (@{u['username'] or 'N/A'}) - 🤖 {b_cnt} bots{ban}\n"
            send_long_message(chat_id, txt)
            return

        if data == "adm_allbots":
            answer_callback(cid)
            bots = get_bots()
            kb = []
            for b in bots:
                icon = "🟢" if b["status"] == "running" else "🔴"
                kb.append([{"text": f"{icon} #{b['id']} {b['name']} ({b['owner_chat_id']})", "callback_data": f"cbot:{b['id']}"}])
            send_message(chat_id, f"🤖 <b>সকল বট তালিকা ({len(bots)} টি):</b>", {"inline_keyboard": kb})
            return

        if data == "adm_toggle_fj":
            cur = get_setting("force_join_enabled", "0")
            new_v = "0" if cur == "1" else "1"
            set_setting("force_join_enabled", new_v)
            answer_callback(cid, f"Force join set to {new_v}")
            show_admin_panel(chat_id, mid)
            return

        if data == "adm_set_channel":
            answer_callback(cid)
            with user_conversations_lock:
                user_conversations[chat_id] = {"state": "adm_set_channel"}
            send_message(chat_id, "📢 চ্যানেলের ইউজারনেম দিন (যেমন: mychannel):")
            return

        if data == "adm_set_limit":
            answer_callback(cid)
            with user_conversations_lock:
                user_conversations[chat_id] = {"state": "adm_set_limit"}
            send_message(chat_id, "🔢 একজন ইউজার সর্বোচ্চ কয়টি বট হোস্ট করতে পারবে? (যেমন: 10):")
            return

        if data == "adm_set_ref":
            answer_callback(cid)
            with user_conversations_lock:
                user_conversations[chat_id] = {"state": "adm_set_ref"}
            send_message(chat_id, "🎁 প্রতি রেফারে কত টাকা দিতে চান? (যেমন: 5):")
            return

        if data == "adm_add_bal":
            answer_callback(cid)
            with user_conversations_lock:
                user_conversations[chat_id] = {"state": "adm_add_bal_user"}
            send_message(chat_id, "👤 যে ইউজারের ব্যালেন্স বাড়াতে চান তার Chat ID দিন:")
            return

        if data == "adm_broadcast":
            answer_callback(cid)
            with user_conversations_lock:
                user_conversations[chat_id] = {"state": "adm_broadcast"}
            send_message(chat_id, "📢 সকল ইউজারকে পাঠানোর মেসেজটি এখানে লিখে সেন্ড করুন:")
            return

        if data == "adm_set_support":
            answer_callback(cid)
            with user_conversations_lock:
                user_conversations[chat_id] = {"state": "adm_set_support"}
            send_message(chat_id, "💬 সাপোর্ট লিংক দিন (যেমন: https://t.me/your_username):")
            return

        if data == "adm_set_help":
            answer_callback(cid)
            with user_conversations_lock:
                user_conversations[chat_id] = {"state": "adm_set_help"}
            send_message(chat_id, "❓ হেল্প মেসেজটি লিখে পাঠান:")
            return

        if data == "adm_ban_menu":
            answer_callback(cid)
            kb = {
                "inline_keyboard": [
                    [{"text": "🚫 Ban User", "callback_data": "adm_do_ban"}, {"text": "✅ Unban User", "callback_data": "adm_do_unban"}]
                ]
            }
            send_message(chat_id, "ব্যান অথবা আনব্যান নির্বাচন করুন:", kb)
            return

        if data == "adm_do_ban":
            answer_callback(cid)
            with user_conversations_lock:
                user_conversations[chat_id] = {"state": "adm_ban_user"}
            send_message(chat_id, "ব্যান করার জন্য ইউজার Chat ID দিন:")
            return

        if data == "adm_do_unban":
            answer_callback(cid)
            with user_conversations_lock:
                user_conversations[chat_id] = {"state": "adm_unban_user"}
            send_message(chat_id, "আনব্যান করার জন্য ইউজার Chat ID দিন:")
            return

        if data == "adm_packs":
            answer_callback(cid)
            with db_lock:
                conn = get_db()
                try:
                    packs = conn.execute("SELECT * FROM packages").fetchall()
                finally:
                    conn.close()
            txt = "📦 <b>বর্তমান প্যাকেজসমূহ:</b>\n\n"
            for p in packs:
                txt += f"• #{p['id']} <b>{p['name']}</b> ({p['days']} Days) - {p['price']} BDT\n"
            kb = {"inline_keyboard": [[{"text": "➕ নতুন প্যাকেজ যোগ করুন", "callback_data": "adm_new_pack"}]]}
            send_message(chat_id, txt, kb)
            return

        if data == "adm_new_pack":
            answer_callback(cid)
            with user_conversations_lock:
                user_conversations[chat_id] = {"state": "adm_pack_name"}
            send_message(chat_id, "প্যাকেজের নাম লিখুন (যেমন: 15 Days VPS):")
            return

        if data == "adm_dep_methods":
            answer_callback(cid)
            with db_lock:
                conn = get_db()
                try:
                    methods = conn.execute("SELECT * FROM deposit_methods").fetchall()
                finally:
                    conn.close()
            txt = "💳 <b>ডিপোজিট মেথডস:</b>\n\n"
            for m in methods:
                txt += f"• #{m['id']} <b>{m['name']}</b>: {m['number']}\n"
            kb = {"inline_keyboard": [[{"text": "➕ নতুন মেথড যোগ করুন", "callback_data": "adm_new_dep"}]]}
            send_message(chat_id, txt, kb)
            return

        if data == "adm_new_dep":
            answer_callback(cid)
            with user_conversations_lock:
                user_conversations[chat_id] = {"state": "adm_dep_name"}
            send_message(chat_id, "মেথডের নাম লিখুন (যেমন: Rocket Personal):")
            return

# ============================================================
# HEALTH CHECK SERVER (FOR RENDER/KOYEB/VPS)
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = f"{APP_NAME} v{VERSION} - ONLINE".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return

def start_health_server():
    try:
        port = int(os.getenv("PORT", "10000"))
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        print(f"[HEALTH] Server listening on port {port}")
        server.serve_forever()
    except Exception as e:
        print(f"[HEALTH ERROR] {e}")

# ============================================================
# TELEGRAM LONG POLLING
# ============================================================

def poll_updates():
    global telegram_offset, BOT_USERNAME
    me = telegram("getMe")
    if me and me.get("ok"):
        BOT_USERNAME = me["result"].get("username", "")
        print(f"[BOT] Connected as @{BOT_USERNAME}")

    print("[POLL] Telegram Bot Polling started...")
    while True:
        try:
            res = telegram("getUpdates", {"offset": telegram_offset, "timeout": 45, "allowed_updates": json.dumps(["message", "callback_query"])}, timeout=55)
            if not res or not res.get("ok"):
                time.sleep(2)
                continue
            for upd in res.get("result", []):
                telegram_offset = int(upd["update_id"]) + 1
                if "message" in upd:
                    threading.Thread(target=handle_message, args=(upd["message"],), daemon=True).start()
                elif "callback_query" in upd:
                    threading.Thread(target=handle_callback, args=(upd["callback_query"],), daemon=True).start()
        except Exception as e:
            print(f"[POLL LOOP ERROR] {e}")
            time.sleep(2)

# ============================================================
# RECOVERY PREVIOUSLY RUNNING BOTS
# ============================================================

def recover_running_bots():
    print("[RECOVERY] Checking active bots from database...")
    for b in get_bots():
        if b["status"] == "running":
            if has_active_plan(b["owner_chat_id"]):
                threading.Thread(target=start_bot, args=(b["id"],), daemon=True).start()
                time.sleep(0.15)
            else:
                update_bot(b["id"], status="stopped", pid=0)

# ============================================================
# MAIN ENTRY
# ============================================================

def main():
    print(f"==================================================")
    print(f"  {APP_NAME} - VERSION {VERSION}")
    print(f"==================================================")
    if not BOT_TOKEN or not OWNER_CHAT_ID:
        print("[FATAL] BOT_TOKEN and OWNER_CHAT_ID must be set in environment variables!")
        sys.exit(1)

    init_db()

    # 1. Health server
    threading.Thread(target=start_health_server, daemon=True).start()

    # 2. Subscription auto-expiry & bot stopping worker
    threading.Thread(target=subscription_checker, daemon=True).start()

    # 3. Recover previously running bots
    threading.Thread(target=recover_running_bots, daemon=True).start()

    # 4. Telegram Polling
    poll_updates()

if __name__ == "__main__":
    main()
