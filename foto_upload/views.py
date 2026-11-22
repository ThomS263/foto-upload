import hashlib
import io
import secrets
import shutil
import time
from urllib.parse import urlencode

import qrcode
from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.security import check_password_hash

from .storage import Problem, read_json

pages = Blueprint("pages", __name__)


def storage():
    return current_app.extensions["albums"]


def payload():
    data = request.get_json(silent=True) if request.is_json else request.form
    if data is None or not hasattr(data, "get"):
        raise Problem("Ungültige Formulardaten.")
    return data


def active(slug):
    event = storage().events().get(slug) if isinstance(slug, str) else None
    return event if event and not event["archived"] else None


def guest_ok(slug, event):
    return event and session.get("guest") == [slug, event["revision"]]


def guest():
    login = session.get("guest") or [None]
    slug = login[0]
    event = active(slug)
    if not guest_ok(slug, event):
        raise Problem("Bitte zuerst im Album anmelden.", 401)
    if request.args.get("event", slug) != slug:
        raise Problem("Das geöffnete Album hat gewechselt. Bitte diese Seite neu laden.", 409)
    return slug, event


def admin_stamp():
    return hashlib.sha256(storage().admin_hash().encode()).hexdigest()


def admin_ok():
    return bool(session.get("manager")) and session["manager"] == admin_stamp()


def require_admin():
    if not admin_ok():
        raise Problem("Bitte zuerst in der Verwaltung anmelden.", 401)


def remember(slug, event):
    session.permanent = True
    session.setdefault("device", secrets.token_urlsafe(18))
    session["guest"] = [slug, event["revision"]]


def serializer():
    return URLSafeTimedSerializer(storage().secret, salt="event-access-v1")


def share_target(slug=None, event=None):
    base = storage().public_url(current_app.config["PUBLIC_URL"])
    base = (base or request.host_url).rstrip("/")
    if event and event["public_access"]:
        token = serializer().dumps({"event": slug, "public": True, "revision": event["revision"]})
        return base + url_for("pages.album", slug=slug) + "?" + urlencode({"access": token})
    return base + "/"


def valid_invite(slug, event, token):
    if not token or not event["public_access"]:
        return False
    try:
        data = serializer().loads(token, max_age=365 * 86400)
    except BadSignature:
        return False
    return (
        isinstance(data, dict)
        and data.get("event") == slug
        and data.get("public") is True
        and data.get("revision", 0) == event["revision"]
        and (not event.get("share_expires") or time.time() < event["share_expires"])
    )


@pages.get("/")
def home():
    albums = [(slug, data) for slug, data in storage().events().items() if not data["archived"]]
    return render_template("home.html", albums=albums, share=share_target())


@pages.get("/event/<slug>")
def album(slug):
    event = active(slug)
    if not event:
        return render_template("message.html", message="Dieses Album ist nicht verfügbar."), 404
    if valid_invite(slug, event, request.args.get("access")):
        remember(slug, event)
        return redirect(url_for(".album", slug=slug), 303)
    if not guest_ok(slug, event):
        return render_template("login.html", event=event, slug=slug, share=share_target())
    event = dict(event)
    event["has_cover"] = (storage().folder(event) / ".cover.jpg").is_file()
    return render_template("album.html", event=event, slug=slug, share=share_target())


@pages.get("/event/<slug>/cover.jpg")
def cover(slug):
    event = active(slug)
    if not event:
        abort(404)
    path = storage().folder(event) / ".cover.jpg"
    if not path.is_file() or path.is_symlink():
        abort(404)
    return send_file(path, mimetype="image/jpeg", conditional=True)


@pages.post("/gallery/login")
@pages.post("/enter")
def enter():
    data = payload()
    slug = data.get("event") or (session.get("guest") or [None])[0]
    event = active(slug)
    identity = request.remote_addr or "local"
    password = data.get("password", "")
    if not isinstance(password, str) or len(password) > 256:
        raise Problem("Ungültiges Passwort.")
    storage().limit("login", identity, 15, fail_only=True)
    if not event or not check_password_hash(event["password_hash"], password):
        storage().limit("login", identity, 15)
        if request.is_json or not event:
            raise Problem("Das Passwort stimmt nicht.", 401)
        return render_template(
            "login.html",
            event=event,
            slug=slug,
            share=share_target(),
            error="Das Passwort stimmt nicht.",
        ), 401
    remember(slug, event)
    return jsonify(ok=True) if request.is_json else redirect(url_for(".album", slug=slug), 303)


@pages.post("/leave")
def leave():
    session.pop("guest", None)
    return redirect(url_for(".home"), 303)


@pages.get("/qr.png")
@pages.get("/qr/<slug>.png")
def qr(slug=None):
    event = active(slug) if slug else None
    if slug and not event:
        abort(404)
    if event and event["public_access"] and not (admin_ok() or guest_ok(slug, event)):
        abort(401)
    buffer = io.BytesIO()
    qrcode.make(share_target(slug, event), box_size=8, border=4).save(buffer, format="PNG")
    buffer.seek(0)
    return send_file(buffer, mimetype="image/png")


@pages.get("/health")
def health():
    from .admin import VERSION
    from .media import files_in

    status = {"ok": True, "gallery": True, "version": VERSION}
    if request.args.get("ready") != "1":
        store = storage()
        events = store.events()
        active = {slug: event for slug, event in events.items() if not event["archived"]}
        paths = [path for event in active.values() for path in files_in(store.folder(event))]
        usage = shutil.disk_usage(store.root)
        backup_settings = store.root / ".backup-settings.json"
        backup_status = store.root / ".backup-status.json"
        status.update(
            files={slug: sum(1 for _ in files_in(store.folder(event))) for slug, event in active.items()},
            storage={"free": usage.free, "total": usage.total},
            albums={"active": len(active), "archived": len(events) - len(active)},
            last_upload=max((int(path.stat().st_mtime) for path in paths), default=0),
            backup={
                "enabled": read_json(backup_settings).get("enabled", False) if backup_settings.exists() else False,
                **(read_json(backup_status) if backup_status.exists() else {}),
            },
            expired_shares=sum(1 for event in events.values() if event.get("share_expires") and event["share_expires"] <= time.time()),
        )
    return jsonify(status)


@pages.get("/manifest.webmanifest")
def manifest():
    return jsonify(
        name="Foto-Upload",
        short_name="Foto-Upload",
        start_url="/",
        display="standalone",
        background_color="#f6f4ef",
        theme_color="#173c34",
        lang="de",
        icons=[
            {"src": f"/static/icon-{n}.png", "sizes": f"{n}x{n}", "type": "image/png"}
            for n in (192, 512)
        ],
    )


@pages.get("/service-worker.js")
def worker():
    return current_app.send_static_file("service-worker.js")
