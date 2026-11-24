"""Application factory for the portable Foto-Upload image."""

import errno
import os
import secrets
import threading
import time
from datetime import timedelta
from urllib.parse import urlsplit

from flask import Flask, jsonify, request, session
from flask.sessions import SecureCookieSessionInterface
from werkzeug.exceptions import HTTPException

from .storage import Problem, Store


class SessionCookies(SecureCookieSessionInterface):
    def get_cookie_secure(self, app):
        return (
            super().get_cookie_secure(app)
            or request.is_secure
            or request.headers.get("X-Forwarded-Proto", "").split(",")[-1].strip() == "https"
        )


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATA_DIR=os.getenv("PHOTO_DATA_DIR", "data"),
        BACKUP_DIR=os.getenv("PHOTO_BACKUP_DIR", ""),
        PUBLIC_URL=os.getenv("PHOTO_PUBLIC_URL", "").rstrip("/"),
        ADMIN_PASSWORD=os.getenv("PHOTO_ADMIN_PASSWORD", ""),
        ADMIN_HASH=os.getenv("PHOTO_ADMIN_PASSWORD_HASH", ""),
        SEED_EVENTS={},
        MIN_FREE_BYTES=1_000_000_000,
        MAX_FILE_BYTES=2 * 1024**3,
        SESSION_COOKIE_NAME="foto_session",
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_REFRESH_EACH_REQUEST=False,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        MAX_FORM_PARTS=32,
        MAX_FORM_MEMORY_SIZE=512 * 1024,
    )
    if config:
        app.config.update(config)
    app.config["MAX_CONTENT_LENGTH"] = app.config["MAX_FILE_BYTES"] + 2 * 1024**2
    base = urlsplit(app.config["PUBLIC_URL"])
    if app.config["PUBLIC_URL"] and (
        base.scheme not in {"http", "https"}
        or not base.hostname
        or base.path.strip("/")
        or base.username
        or base.password
        or base.query
        or base.fragment
    ):
        raise ValueError("PHOTO_PUBLIC_URL muss eine HTTP(S)-Adresse ohne Pfad sein.")
    store = Store(
        app.config["DATA_DIR"],
        app.config["SEED_EVENTS"],
        app.config["ADMIN_PASSWORD"],
        app.config["ADMIN_HASH"],
    )
    app.extensions["albums"] = store
    app.secret_key = store.secret
    app.session_interface = SessionCookies()

    from .admin import admin, automatic_backup
    from .media import media, prune_uploads
    from .views import pages

    app.register_blueprint(pages)
    app.register_blueprint(media)
    app.register_blueprint(admin)
    prune_uploads(store)

    if not app.config.get("TESTING"):

        def backup_loop():
            while True:
                try:
                    automatic_backup(app)
                except Exception:
                    app.logger.exception("Automatische Sicherung fehlgeschlagen")
                time.sleep(60)

        threading.Thread(target=backup_loop, daemon=True, name="automatic-backup").start()

    @app.before_request
    def check_origin():
        session.setdefault("csrf", secrets.token_urlsafe(32))
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return
        origin = request.headers.get("Origin")
        if request.headers.get("Sec-Fetch-Site") == "cross-site" or (
            origin and urlsplit(origin).netloc not in {request.host, base.netloc} - {""}
        ):
            raise Problem("Diese Anfrage stammt von einer anderen Seite.", 403)
        # Browsers provide Origin and/or Fetch Metadata. Requiring a session-bound
        # token for those requests protects forms and JavaScript calls while
        # keeping deliberate non-browser API clients backwards compatible.
        if origin or request.headers.get("Sec-Fetch-Site"):
            supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
            expected = session.get("csrf", "")
            if not expected or not secrets.compare_digest(str(supplied), str(expected)):
                raise Problem("Die Sicherheitsprüfung ist abgelaufen. Bitte die Seite neu laden.", 403)
        if request.endpoint == "media.upload_chunk":
            request.max_content_length = 10 * 1024**2
        elif request.endpoint != "media.upload":
            request.max_content_length = 512 * 1024

    @app.context_processor
    def csrf_context():
        return {"csrf_token": lambda: session.get("csrf", "")}

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = (
            "no-referrer" if "access" in request.args else "same-origin"
        )
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        if request.is_secure or request.headers.get("X-Forwarded-Proto", "").split(",")[-1].strip() == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; "
            "media-src 'self' blob:; frame-ancestors 'self'; object-src 'none'; base-uri 'none'; form-action 'self'"
        )
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.errorhandler(Problem)
    def problem(error):
        return jsonify(ok=False, error=str(error)), error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        messages = {
            401: "Bitte erneut anmelden.",
            404: "Nicht gefunden.",
            413: "Die Datei oder Anfrage ist zu groß.",
        }
        return jsonify(ok=False, error=messages.get(error.code, error.name)), error.code

    @app.errorhandler(OSError)
    def storage_error(error):
        if error.errno in {errno.ENOSPC, errno.EDQUOT}:
            return jsonify(ok=False, error="Der Speicher ist voll."), 507
        app.logger.exception("Datenzugriff fehlgeschlagen")
        return jsonify(ok=False, error="Der Datenspeicher ist gerade nicht verfügbar."), 500

    return app
