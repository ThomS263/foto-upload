import json
import os
import secrets
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

from .media import files_in, media_file, preview, read_names, zip_chunks, zip_response
from .storage import Problem, directory, locked, read_json, safe_name, write_json
from .views import admin_ok, admin_stamp, payload, require_admin, share_target, storage

admin = Blueprint("admin", __name__, url_prefix="/admin")
VERSION = "3.1.1"


@admin.route("", methods=["GET", "POST"])
def panel():
    if request.method == "POST":
        store = storage()
        identity = request.remote_addr or "local"
        store.limit("admin", identity, 10, fail_only=True)
        password = request.form.get("password", "")
        if len(password) > 256 or not check_password_hash(store.admin_hash(), password):
            store.limit("admin", identity, 10)
            return render_template(
                "login.html",
                manager=True,
                first_login=store.bootstrap.is_file(),
                error="Das Passwort stimmt nicht.",
            ), 401
        session.permanent = True
        session["manager"] = admin_stamp()
        return redirect(url_for(".panel"), 303)
    if not admin_ok():
        return render_template(
            "login.html", manager=True, first_login=storage().bootstrap.is_file()
        )
    return render_template("admin.html", managed_password=bool(storage().configured_hash))


@admin.post("/logout")
def logout():
    session.pop("manager", None)
    return redirect(url_for("pages.home"), 303)


def orphan_previews(folder):
    return (
        thumb
        for thumb in (folder / ".thumbs").iterdir()
        if safe_name(thumb.name)
        and thumb.suffix == ".jpg"
        and not thumb.is_symlink()
        and thumb.is_file()
        and not (folder / thumb.name[:-4]).is_file()
        and not (folder / ".trash" / thumb.name[:-4]).is_file()
    )


@admin.get("/api/storage")
def disk_space():
    require_admin()
    usage = shutil.disk_usage(storage().root)
    return jsonify(total=usage.total, free=usage.free, reserve=current_app.config["MIN_FREE_BYTES"])


@admin.route("/api/public-url", methods=["GET", "PUT"])
def public_url():
    require_admin()
    if request.method == "GET":
        configured = storage().public_url(current_app.config["PUBLIC_URL"])
        return jsonify(url=configured, managed=bool(current_app.config["PUBLIC_URL"]))
    value = str((request.get_json(silent=True) or {}).get("url", "")).strip().rstrip("/")
    if value:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise Problem("Bitte eine vollständige HTTPS-Adresse ohne zusätzlichen Pfad eingeben.")
    storage().set_public_url(value)
    return jsonify(ok=True, url=value)


@admin.get("/api/version")
def version():
    require_admin()
    result = {"current": VERSION, "latest": None}
    try:
        req = Request(
            "https://api.github.com/repos/ThomS263/foto_upload_offiziel/releases/latest",
            headers={"User-Agent": "Foto-Upload"},
        )
        with urlopen(req, timeout=4) as response:
            tag = json.load(response).get("tag_name", "")
        if isinstance(tag, str) and len(tag) <= 32:
            result["latest"] = tag.lstrip("v")
    except (OSError, URLError, ValueError):
        pass
    return jsonify(result)


@admin.get("/api/diagnostics")
def diagnostics():
    require_admin()
    store = storage()
    public = store.public_url(current_app.config["PUBLIC_URL"])
    usage = shutil.disk_usage(store.root)
    backup_status = store.root / ".backup-status.json"
    backup = read_json(backup_status) if backup_status.exists() else {}
    issues = []
    if not public:
        issues.append("Keine feste öffentliche HTTPS-Adresse für QR-Codes eingerichtet.")
    elif not public.startswith("https://"):
        issues.append("Die öffentliche Adresse verwendet kein HTTPS.")
    if usage.free <= current_app.config["MIN_FREE_BYTES"] * 2:
        issues.append("Der freie Speicher wird knapp.")
    if not backup.get("success"):
        issues.append("Noch keine erfolgreiche automatische Sicherung vorhanden.")
    expired = sum(
        1 for event in store.events().values()
        if event.get("share_expires") and event["share_expires"] <= time.time()
    )
    if expired:
        issues.append(f"{expired} abgelaufene Gästefreigabe(n) können deaktiviert werden.")
    return jsonify(
        public_url=public,
        https=bool(public and public.startswith("https://")),
        free=usage.free,
        backup=backup.get("success", 0),
        expired=expired,
        issues=issues,
        update_command="cd foto-upload && git pull --ff-only origin main && docker compose up -d --build --wait",
    )


@admin.get("/api/events/<slug>/files")
def album_files(slug):
    require_admin()
    event = storage().events().get(slug)
    if not event:
        raise Problem("Album nicht gefunden.", 404)
    folder = storage().folder(event)
    names = read_names(folder)
    files = []
    for path in files_in(folder):
        stat = path.stat()
        files.append(
            {
                "name": path.name,
                "guest": names.get(path.name, ""),
                "size": stat.st_size,
                "time": int(stat.st_mtime),
            }
        )
    files.sort(key=lambda item: (item["time"], item["name"]), reverse=True)
    return jsonify(files=files)


@admin.delete("/api/events/<slug>/files/<path:filename>")
def delete_file(slug, filename):
    require_admin()
    event = storage().events().get(slug)
    if not event:
        raise Problem("Album nicht gefunden.", 404)
    folder = storage().folder(event)
    with locked(folder / ".metadata.lock"):
        path = media_file(folder, filename)
        trash = directory(folder / ".trash")
        target = trash / filename
        if target.exists() or target.is_symlink():
            raise Problem("Eine Datei mit diesem Namen liegt bereits im Papierkorb.", 409)
        os.replace(path, target)
    return jsonify(ok=True)


@admin.route("/api/events/<slug>/trash", methods=["GET", "POST"])
def trash_files(slug):
    require_admin()
    event = storage().events().get(slug)
    if not event:
        raise Problem("Album nicht gefunden.", 404)
    folder = storage().folder(event)
    with locked(folder / ".metadata.lock"):
        trash = directory(folder / ".trash")
        if request.method == "GET":
            return jsonify(
                files=[{"name": p.name, "size": p.stat().st_size} for p in files_in(trash)]
            )
        filename = payload().get("name")
        source = media_file(trash, filename)
        target = folder / filename
        if target.exists() or target.is_symlink():
            raise Problem("Im Album gibt es bereits eine Datei mit diesem Namen.", 409)
        os.replace(source, target)
    return jsonify(ok=True)


@admin.route("/api/events", methods=["GET", "POST"])
def albums():
    require_admin()
    store = storage()
    if request.method == "POST":
        data = payload()
        store.change(data.get("slug"), data, "create")
        return jsonify(ok=True), 201
    results = []
    for slug, event in store.events().items():
        folder = store.folder(event)
        stats = [p.stat() for p in files_in(folder)]
        result = {key: event[key] for key in (
            "title", "subtitle", "folder", "archived", "public_access", "allow_upload",
            "allow_gallery", "allow_download", "event_date", "tone"
        )}
        result.update(
            slug=slug,
            files=len(stats),
            bytes=sum(item.st_size for item in stats),
            latest=max((int(item.st_mtime) for item in stats), default=0),
            orphan_thumbs=sum(1 for _ in orphan_previews(folder)),
            needs_password=event.get("needs_password", False),
            share_expires=event.get("share_expires", 0),
        )
        if not event["archived"] and event["public_access"]:
            result.update(share=share_target(slug, event), qr=url_for("pages.qr", slug=slug))
        results.append(result)
    return jsonify(results)


@admin.route("/api/events/<slug>", methods=["PUT", "DELETE"])
def edit(slug):
    require_admin()
    if request.method == "DELETE":
        storage().change(slug, {}, "archive")
    else:
        storage().change(slug, payload(), "edit")
    return jsonify(ok=True)


@admin.post("/api/events/<slug>/cover")
def event_cover(slug):
    require_admin()
    event = storage().events().get(slug)
    if not event:
        raise Problem("Album nicht gefunden.", 404)
    image = request.files.get("cover")
    if not image or not image.filename:
        raise Problem("Bitte ein Titelbild auswählen.")
    target = storage().folder(event) / ".cover.jpg"
    with locked(storage().locks / ("cover-" + slug)):
        if not preview(image.stream, target):
            raise Problem("Das Titelbild konnte nicht gelesen werden.")
    return jsonify(ok=True)


@admin.post("/api/events/<slug>/restore")
def restore(slug):
    require_admin()
    storage().change(slug, {}, "restore")
    return jsonify(ok=True)


@admin.put("/api/admin-password")
def password():
    require_admin()
    storage().rotate_admin(payload().get("password"))
    session["manager"] = admin_stamp()
    return jsonify(ok=True)


@admin.post("/api/cleanup")
def cleanup():
    require_admin()
    store = storage()
    removed = 0
    for event in store.events().values():
        folder = store.folder(event)
        with locked(folder / ".metadata.lock"):
            for thumb in orphan_previews(folder):
                thumb.unlink()
                removed += 1
    return jsonify(ok=True, removed=removed)


def backup_entries(store):
    paths = [
        store.catalog,
        store.root / ".secret",
        store.admin_file,
        store.bootstrap,
        store.root / ".backup-settings.json",
    ]
    for event in store.events().values():
        folder = store.folder(event)
        paths.append(folder / ".meta.jsonl")
        paths.append(folder / ".cover.jpg")
        trash = folder / ".trash"
        if trash.is_dir() and not trash.is_symlink():
            paths.extend(files_in(trash))
        paths.extend(
            p for p in folder.iterdir() if safe_name(p.name) and p.suffix.lower() != ".zip"
        )
        paths.extend(
            p
            for p in (folder / ".thumbs").iterdir()
            if p.suffix == ".jpg" and not p.name.startswith(".")
        )
    return [
        (p.relative_to(store.root).as_posix(), p)
        for p in paths
        if not p.is_symlink() and p.is_file()
    ]


def automatic_backup(app):
    store = app.extensions["albums"]
    config = store.root / ".backup-settings.json"
    status = store.root / ".backup-status.json"
    with locked(store.locks / "automatic-backup"):
        settings = read_json(config) if config.exists() else {}
        previous = read_json(status) if status.exists() else {}
        if not settings.get("enabled") or time.time() < previous.get("attempted", 0) + 86400:
            return
        now = int(time.time())
        result = {"attempted": now, "success": previous.get("success", 0), "error": ""}
        tmp = None
        try:
            target = Path(app.config["BACKUP_DIR"])
            if not app.config["BACKUP_DIR"] or not target.is_dir():
                raise OSError("Der zweite Speicher ist nicht verfügbar.")
            filename = (
                time.strftime("foto-upload-auto-%Y%m%d-%H%M%S-") + secrets.token_hex(3) + ".zip"
            )
            with tempfile.NamedTemporaryFile(dir=target, prefix=".backup-", delete=False) as out:
                tmp = Path(out.name)
                for part in zip_chunks(backup_entries(store)):
                    out.write(part)
                out.flush()
                os.fsync(out.fileno())
            with zipfile.ZipFile(tmp) as archive:
                if archive.testzip() is not None:
                    raise OSError("Die Sicherung ist beschädigt.")
            os.replace(tmp, target / filename)
            result["success"] = now
        except (OSError, zipfile.BadZipFile) as error:
            result["error"] = str(error)
        finally:
            if tmp:
                tmp.unlink(missing_ok=True)
        write_json(status, result)


@admin.route("/api/automatic-backup", methods=["GET", "PUT"])
def backup_settings():
    require_admin()
    store = storage()
    path = store.root / ".backup-settings.json"
    if request.method == "PUT":
        enabled = payload().get("enabled")
        if not isinstance(enabled, bool):
            raise Problem("Ungültige Einstellung.")
        if enabled and (
            not current_app.config["BACKUP_DIR"]
            or not Path(current_app.config["BACKUP_DIR"]).is_dir()
        ):
            raise Problem("Bitte zuerst einen zweiten Speicher als PHOTO_BACKUP_DIR einbinden.")
        with locked(store.locks / "automatic-backup"):
            write_json(path, {"enabled": enabled})
    settings = read_json(path) if path.exists() else {}
    status = store.root / ".backup-status.json"
    return jsonify(
        enabled=settings.get("enabled", False), status=read_json(status) if status.exists() else {}
    )


@admin.get("/backup")
def backup():
    require_admin()
    store = storage()
    entries = backup_entries(store)
    filename = time.strftime("foto-upload-%Y%m%d-%H%M%S-") + secrets.token_hex(3) + ".zip"
    destination = current_app.config["BACKUP_DIR"]
    if not destination:
        return zip_response(entries, filename)
    directory = Path(destination)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    with tempfile.NamedTemporaryFile(dir=directory, prefix=".backup-", delete=False) as out:
        tmp = Path(out.name)
        try:
            for part in zip_chunks(entries):
                out.write(part)
            out.flush()
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
    return send_file(path, mimetype="application/zip", as_attachment=True)
