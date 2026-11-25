"""Persistent v2-compatible album catalogue. Writers share a lock across workers."""

import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import tempfile
import time
from contextlib import closing, contextmanager
from pathlib import Path

from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


class Problem(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def safe_name(name):
    return (
        isinstance(name, str)
        and bool(name)
        and not name.startswith(".")
        and not any(char in name for char in ("/", "\\", "\0"))
    )


def plain(value, limit=80):
    if not isinstance(value, str):
        raise Problem("Bitte Text eingeben.")
    return "".join(c for c in value if c.isprintable()).strip()[:limit]


def password_value(value, minimum=1):
    if not isinstance(value, str) or not minimum <= len(value) <= 256:
        raise Problem(f"Bitte ein Passwort mit {minimum} bis 256 Zeichen eingeben.")
    return value


@contextmanager
def locked(path):
    with path.open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def atomic_text(path, text):
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, prefix=".writing-", encoding="utf-8", delete=False
    ) as out:
        tmp = Path(out.name)
        try:
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    atomic_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def directory(path):
    if path.is_symlink():
        raise ValueError(f"Verknüpfter Datenordner: {path.name}")
    path.mkdir(exist_ok=True)
    return path


class Store:
    def __init__(self, root, seeds, password, configured_hash):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.uploads = directory(self.root / "uploads")
        self.locks = directory(self.root / ".locks")
        self.catalog = self.root / ".events.json"
        self.admin_file = self.root / ".admin_password_hash"
        self.bootstrap = self.root / ".initial-admin-password"
        self.public_url_file = self.root / ".public-url"
        self.audit_file = self.root / ".audit.jsonl"
        self.admin_generation = self.root / ".admin-session-generation"
        self.configured_hash = configured_hash
        with self.transaction():
            secret_file = self.root / ".secret"
            if not secret_file.exists():
                atomic_text(secret_file, secrets.token_hex(32))
            self.secret = secret_file.read_text().strip()
            if not self.secret:
                raise ValueError("Die vorhandene .secret ist leer.")
            os.chmod(secret_file, 0o600)
            if not configured_hash and not self.admin_file.exists():
                if not password:
                    if not self.bootstrap.exists():
                        atomic_text(self.bootstrap, secrets.token_urlsafe(22) + "\n")
                    password = self.bootstrap.read_text().strip()
                atomic_text(self.admin_file, generate_password_hash(password))
            if self.admin_file.exists():
                os.chmod(self.admin_file, 0o600)
            if not self.admin_generation.exists():
                atomic_text(self.admin_generation, secrets.token_hex(16) + "\n")
            os.chmod(self.admin_generation, 0o600)
            self._discover(seeds)
        with closing(self._rates()) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS quota (id TEXT PRIMARY KEY, window INTEGER, hits INTEGER)"
            )

    def transaction(self):
        return locked(self.locks / "catalog")

    def _discover(self, seeds):
        persisted = self.events() if self.catalog.exists() else {}
        events = {key: dict(value) for key, value in persisted.items()}
        for slug, data in seeds.items():
            events.setdefault(slug, dict(data))
        known = set()
        for slug, event in events.items():
            name = event.setdefault("folder", slug)
            if not SLUG.fullmatch(slug) or not safe_name(name) or name in known:
                raise ValueError("Ungültige oder doppelte Ordnerzuordnung in .events.json.")
            known.add(name)
            password = event.pop("password", None)
            if not event.get("password_hash"):
                event["password_hash"] = generate_password_hash(
                    password or secrets.token_urlsafe(32)
                )
                if not password:
                    event.update(archived=True, needs_password=True)
            event.setdefault("title", slug)
            event.setdefault("subtitle", "")
            event.setdefault("archived", False)
            event.setdefault("public_access", False)
            event.setdefault("allow_upload", True)
            event.setdefault("allow_gallery", True)
            event.setdefault("allow_download", True)
            event.setdefault("expose_gps", False)
            event.setdefault("allow_reactions", True)
            event.setdefault("allow_comments", False)
            event.setdefault("event_date", "")
            event.setdefault("tone", "green")
            event.setdefault("quota_bytes", 0)
            event.setdefault("revision", 0)
            self.prepare(event)
        for folder in sorted(self.uploads.iterdir()):
            if (
                not safe_name(folder.name)
                or folder.name in known
                or folder.is_symlink()
                or not folder.is_dir()
            ):
                continue
            base = (
                re.sub(r"[^a-z0-9]+", "-", secure_filename(folder.name).lower()).strip("-")[:48]
                or "album"
            )
            slug = base
            index = 2
            while slug in events:
                slug = f"{base}-{index}"
                index += 1
            events[slug] = {
                "folder": folder.name,
                "title": folder.name,
                "subtitle": "",
                "archived": True,
                "password_hash": generate_password_hash(secrets.token_urlsafe(32)),
                "public_access": False,
                "revision": 0,
                "needs_password": True,
            }
            self.prepare(events[slug])
        if not self.catalog.exists() or events != persisted:
            write_json(self.catalog, events)

    def folder(self, event):
        name = event["folder"]
        if not safe_name(name) or (self.uploads / name).is_symlink():
            raise ValueError("Ungültiger Albumordner.")
        return self.uploads / name

    def prepare(self, event):
        folder = directory(self.folder(event))
        directory(folder / ".thumbs")
        directory(folder / ".pending")

    def events(self):
        data = read_json(self.catalog)
        if not isinstance(data, dict):
            raise TypeError("Ungültiger Eventkatalog. Bitte die Datensicherung prüfen.")
        return data

    def admin_hash(self):
        return self.configured_hash or self.admin_file.read_text().strip()

    def public_url(self, fallback=""):
        if self.public_url_file.exists():
            return self.public_url_file.read_text(encoding="utf-8").strip()
        return fallback

    def set_public_url(self, value):
        with self.transaction():
            if value:
                atomic_text(self.public_url_file, value + "\n")
            else:
                self.public_url_file.unlink(missing_ok=True)

    def rotate_admin(self, password):
        if self.configured_hash:
            raise Problem("Das Adminpasswort wird über PHOTO_ADMIN_PASSWORD_HASH verwaltet.", 409)
        with self.transaction():
            atomic_text(self.admin_file, generate_password_hash(password_value(password, 10)))
            self.bootstrap.unlink(missing_ok=True)
        self.revoke_admin_sessions()

    def admin_session_value(self):
        return self.admin_generation.read_text(encoding="utf-8").strip()

    def revoke_admin_sessions(self):
        with self.transaction():
            atomic_text(self.admin_generation, secrets.token_hex(16) + "\n")
            os.chmod(self.admin_generation, 0o600)

    def audit(self, action, **details):
        """Append a bounded, credential-free administrator activity record."""
        allowed = {key: plain(str(value), 120) for key, value in details.items()}
        with locked(self.locks / "audit"):
            previous_hash = ""
            if self.audit_file.exists():
                try:
                    last = self.audit_file.read_text(encoding="utf-8").splitlines()[-1]
                    previous_hash = str(json.loads(last).get("hash", ""))
                except (IndexError, OSError, ValueError):
                    previous_hash = ""
            if self.audit_file.exists() and self.audit_file.stat().st_size > 2 * 1024**2:
                previous = self.audit_file.with_suffix(".jsonl.1")
                previous.unlink(missing_ok=True)
                os.replace(self.audit_file, previous)
                previous_hash = ""
            record = {
                "time": int(time.time()), "action": plain(action, 64),
                "previous": previous_hash, **allowed,
            }
            canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            record["hash"] = hmac.new(
                self.secret.encode(), canonical.encode(), hashlib.sha256
            ).hexdigest()
            with self.audit_file.open("a", encoding="utf-8") as output:
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
            os.chmod(self.audit_file, 0o600)

    def audit_records(self, maximum=100):
        if not self.audit_file.exists() or self.audit_file.is_symlink():
            return []
        rows = []
        with self.audit_file.open(encoding="utf-8", errors="replace") as source:
            for line in source:
                try:
                    record = json.loads(line)
                    if isinstance(record, dict):
                        rows.append(record)
                except ValueError:
                    continue
        return rows[-maximum:][::-1]

    def audit_integrity(self):
        previous_hash = ""
        for source in reversed(self.audit_records(100000)):
            record = dict(source)
            supplied = str(record.pop("hash", ""))
            if not supplied and "previous" not in record:
                continue  # Records created before hash chaining was introduced.
            if record.get("previous", "") != previous_hash:
                return False
            canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            expected = hmac.new(self.secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
            if not supplied or not hmac.compare_digest(supplied, expected):
                return False
            previous_hash = supplied
        return True

    def change(self, slug, values, action):
        if not isinstance(slug, str) or not SLUG.fullmatch(slug):
            raise Problem(
                "Die Albumadresse darf Kleinbuchstaben, Ziffern und Bindestriche enthalten."
            )
        with self.transaction():
            events = self.events()
            if action == "create":
                if slug in events or (self.uploads / slug).exists():
                    raise Problem("Diese Albumadresse ist bereits vergeben.", 409)
                event = {
                    "folder": slug,
                    "archived": False,
                    "public_access": False,
                    "allow_upload": True,
                    "allow_gallery": True,
                    "allow_download": True,
                    "expose_gps": False,
                    "allow_reactions": True,
                    "allow_comments": False,
                    "event_date": "",
                    "tone": "green",
                    "revision": 0,
                    "subtitle": "",
                }
                events[slug] = event
                if not plain(values.get("title", "")) or not values.get("password"):
                    raise Problem("Bitte Albumname und Passwort eingeben.")
            else:
                if slug not in events:
                    raise Problem("Album nicht gefunden.", 404)
                event = events[slug]
            if action in {"archive", "restore"}:
                if action == "restore" and event.get("needs_password"):
                    raise Problem(
                        "Für diesen gefundenen Ordner bitte zuerst ein Albumpasswort speichern."
                    )
                event["archived"] = action == "archive"
                event["revision"] += 1
            else:
                if "title" in values:
                    title = plain(values["title"])
                    if not title:
                        raise Problem("Der Albumname fehlt.")
                    event["title"] = title
                if "subtitle" in values:
                    event["subtitle"] = plain(values["subtitle"], 180)
                if "event_date" in values:
                    date = plain(values["event_date"], 10)
                    if date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                        raise Problem("Ungültiges Veranstaltungsdatum.")
                    event["event_date"] = date
                if "tone" in values:
                    tone = plain(values["tone"], 12)
                    if tone not in {"green", "blue", "rose", "gold"}:
                        raise Problem("Ungültige Albumfarbe.")
                    event["tone"] = tone
                if "quota_bytes" in values:
                    quota = values["quota_bytes"]
                    if not isinstance(quota, int) or isinstance(quota, bool) or quota < 0:
                        raise Problem("Ungültiges Speicherlimit.")
                    event["quota_bytes"] = min(quota, 100 * 1024**4)
                if "password" in values:
                    event["password_hash"] = generate_password_hash(
                        password_value(values["password"])
                    )
                    event.pop("needs_password", None)
                    event["revision"] += 1
                if "public_access" in values:
                    enabled = values["public_access"]
                    if not isinstance(enabled, bool):
                        raise Problem("Ungültige Linkfreigabe.")
                    if enabled != event["public_access"]:
                        event["public_access"] = enabled
                        event["revision"] += 1
                for permission in (
                    "allow_upload", "allow_gallery", "allow_download", "expose_gps",
                    "allow_reactions", "allow_comments",
                ):
                    if permission in values:
                        enabled = values[permission]
                        if not isinstance(enabled, bool):
                            raise Problem("Ungültige Albumberechtigung.")
                        event[permission] = enabled
                if "share_expires" in values:
                    expiry = values["share_expires"]
                    if not isinstance(expiry, int) or isinstance(expiry, bool) or expiry < 0:
                        raise Problem("Ungültiges Ablaufdatum.")
                    if expiry != event.get("share_expires", 0):
                        event["share_expires"] = expiry
                        event["revision"] += 1
            if action == "create":
                self.prepare(event)
            write_json(self.catalog, events)

    def _rates(self):
        return sqlite3.connect(self.root / ".limits.sqlite", timeout=12, isolation_level=None)

    def limit(self, group, identity, maximum, seconds=600, fail_only=False):
        now = int(time.time())
        key = group + hashlib.sha256(identity.encode()).hexdigest()
        with closing(self._rates()) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM quota WHERE window <= ?", (now,))
            row = db.execute("SELECT hits FROM quota WHERE id = ?", (key,)).fetchone()
            if row and row[0] >= maximum:
                raise Problem("Zu viele Versuche. Bitte in einigen Minuten erneut versuchen.", 429)
            if fail_only:
                db.commit()
                return
            db.execute(
                """INSERT INTO quota VALUES (?, ?, 1)
                       ON CONFLICT(id) DO UPDATE SET hits = hits + 1""",
                (key, now + seconds),
            )
            db.commit()
