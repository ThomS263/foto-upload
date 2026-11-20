import os
import secrets
import tempfile
import time
from pathlib import Path

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

from .media import files_in, zip_chunks, zip_response
from .storage import locked, safe_name
from .views import admin_ok, admin_stamp, payload, require_admin, share_target, storage

admin = Blueprint("admin", __name__, url_prefix="/admin")


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
    )


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
        sizes = [p.stat().st_size for p in files_in(folder)]
        result = {
            key: event[key] for key in ("title", "subtitle", "folder", "archived", "public_access")
        }
        result.update(
            slug=slug,
            files=len(sizes),
            bytes=sum(sizes),
            orphan_thumbs=sum(1 for _ in orphan_previews(folder)),
            needs_password=event.get("needs_password", False),
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
    paths = [store.catalog, store.root / ".secret", store.admin_file, store.bootstrap]
    for event in store.events().values():
        folder = store.folder(event)
        paths.append(folder / ".meta.jsonl")
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
