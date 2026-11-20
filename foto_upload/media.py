"""Event media, retryable uploads and bounded-memory ZIP delivery."""

import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import time
import zipfile
from pathlib import Path

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    jsonify,
    request,
    send_file,
    session,
    stream_with_context,
    url_for,
)
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener
from werkzeug.utils import secure_filename

from .storage import Problem, directory, locked, plain, read_json, safe_name, write_json
from .views import guest, storage

media = Blueprint("media", __name__)
register_heif_opener()
CHUNK = 8 * 1024**2
UPLOAD_ID = re.compile(r"[a-f0-9]{32}")
IMAGE = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
    ".heic",
    ".heif",
    ".avif",
}
VIDEO = {".mp4", ".m4v", ".mov", ".3gp", ".mkv", ".webm", ".avi"}
EXTENSIONS = IMAGE | VIDEO
MIME_EXT = {"image/heic": ".heic", "image/heif": ".heif", "video/quicktime": ".mov"}
SIGNATURES = {
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".bmp": (b"BM",),
    ".tif": (b"II*\0", b"MM\0*"),
    ".tiff": (b"II*\0", b"MM\0*"),
    ".webm": (b"\x1a\x45\xdf\xa3",),
    ".mkv": (b"\x1a\x45\xdf\xa3",),
}


def media_name(name):
    return safe_name(name) and Path(name).suffix.lower() in EXTENSIONS


def media_file(folder, name):
    if not media_name(name):
        abort(404)
    path = folder / name
    if path.is_symlink() or not path.is_file():
        abort(404)
    return path


def matches(header, ext):
    if ext in SIGNATURES:
        return header.startswith(SIGNATURES[ext])
    if ext in {".avi", ".webp"}:
        return header.startswith(b"RIFF") and header[8:12] == (
            b"AVI " if ext == ".avi" else b"WEBP"
        )
    return len(header) >= 12 and header[4:8] == b"ftyp"


def read_names(folder):
    result = {}
    path = folder / ".meta.jsonl"
    if not path.is_symlink() and path.exists():
        with path.open(encoding="utf-8", errors="replace") as rows:
            for line in rows:
                try:
                    record = json.loads(line)
                    if isinstance(record, dict) and safe_name(record.get("f")):
                        result[record["f"]] = plain(record.get("n", ""), 40)
                except (ValueError, Problem):
                    continue
    return result


def files_in(folder):
    return (
        path
        for path in folder.iterdir()
        if media_name(path.name) and not path.is_symlink() and path.is_file()
    )


def preview(source, dest):
    """Keep the original untouched, auto-orient the small JPEG, bound decoded pixels."""
    try:
        with Image.open(source) as picture:
            if picture.width * picture.height > 52_000_000:
                return False
            picture.draft("RGB", (900, 900))
            picture.thumbnail((720, 720))
            thumb = ImageOps.exif_transpose(picture).convert("RGB")
            with dest.open("wb") as output:
                thumb.save(output, format="JPEG", quality=82)
        return True
    except (UnidentifiedImageError, ValueError, SyntaxError, Image.DecompressionBombError):
        return False
    except OSError as error:
        if error.errno:
            raise
        return False


def clear_job(job):
    for name in ("state.json", "body", "preview.jpg"):
        (job / name).unlink(missing_ok=True)
    for temp in job.glob(".writing-*"):
        temp.unlink(missing_ok=True)
    job.rmdir()


def job_lock(store, upload_id):
    # Fixed lock names remain valid across directory expiry and worker restarts.
    return locked(store.locks / ("upload-" + upload_id[:2]))


def prune_uploads(store):
    cutoff = time.time() - 86400
    stamp = store.locks / "last-prune"
    with locked(store.locks / "prune"):
        if stamp.exists() and stamp.stat().st_mtime > time.time() - 3600:
            return
        for event in store.events().values():
            pending = store.folder(event) / ".pending"
            for job in pending.iterdir():
                if job.is_symlink() or not job.is_dir() or not UPLOAD_ID.fullmatch(job.name):
                    continue
                if job.stat().st_mtime < cutoff:
                    with job_lock(store, job.name):
                        if job.exists() and job.stat().st_mtime < cutoff:
                            clear_job(job)
        stamp.touch()


def save_part(body, source, offset, maximum, reserve):
    source.seek(0, os.SEEK_END)
    size = source.tell()
    source.seek(0)
    if size == 0:
        raise Problem("Die Datei ist leer.")
    if size > maximum:
        raise Problem("Die Datei oder der Upload-Block ist zu groß.", 413)
    if shutil.disk_usage(body.parent).free - size < reserve:
        raise Problem("Auf dem Server ist zu wenig Speicher frei.", 507)
    with body.open("r+b" if body.exists() else "w+b") as dest:
        dest.seek(offset)
        dest.truncate()
        shutil.copyfileobj(source, dest, 1024**2)
        dest.flush()
        os.fsync(dest.fileno())
    return offset + size


def publish(folder, job, state):
    target = folder / state["filename"]
    if target.is_file():
        return
    body = job / "body"
    with body.open("rb") as source:
        if not matches(source.read(32), target.suffix):
            clear_job(job)
            raise Problem("Der Dateiinhalt passt nicht zu einem unterstützten Foto oder Video.")
    # All sidecars are available before the original becomes visible to the gallery.
    with locked(folder / ".metadata.lock"):
        if state["guest"]:
            meta = folder / ".meta.jsonl"
            if meta.is_symlink():
                raise Problem("Die Namensliste ist nicht beschreibbar.", 500)
            with meta.open("a", encoding="utf-8") as out:
                out.write(
                    json.dumps({"f": target.name, "n": state["guest"]}, ensure_ascii=False) + "\n"
                )
        thumb = job / "preview.jpg"
        if thumb.is_file():
            os.replace(thumb, folder / ".thumbs" / (target.name + ".jpg"))
        os.replace(body, target)


def receive(chunked):
    slug, event = guest()
    store = storage()
    prune_uploads(store)
    item = request.files.get("chunk" if chunked else "file")
    if item is None:
        raise Problem("Bitte eine Datei auswählen.")
    filename = request.form.get("filename", "") if chunked else item.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in EXTENSIONS:
        mime = request.form.get("type", item.mimetype)
        suffix = MIME_EXT.get(mime) or mimetypes.guess_extension(mime or "")
    if suffix not in EXTENSIONS:
        raise Problem("Dieser Dateityp wird nicht unterstützt.")
    identifier = request.form.get("upload_id", "" if chunked else secrets.token_hex(16))
    index = request.form.get("index", type=int) if chunked else 0
    total = request.form.get("total", type=int) if chunked else 1
    limit = current_app.config["MAX_FILE_BYTES"]
    if (
        not UPLOAD_ID.fullmatch(identifier)
        or index is None
        or total is None
        or not 0 <= index < total <= 512
    ):
        raise Problem("Ungültige Upload-Daten.")
    folder = store.folder(event)
    job = folder / ".pending" / identifier
    with job_lock(store, identifier):
        state_file = job / "state.json"
        if not state_file.exists():
            if index != 0:
                raise Problem("Bitte die Übertragung beim ersten Block beginnen.", 409)
            store.limit("upload:" + slug, session["device"], 1000)
            safe = secure_filename(Path(filename).stem)[:60] or "datei"
            final = f"{time.strftime('%Y%m%d-%H%M%S')}-{identifier}-{safe}{suffix}"
            state = {
                "original": filename,
                "filename": final,
                "total": total,
                "next": 0,
                "size": 0,
                "guest": plain(request.form.get("name", ""), 40),
            }
            directory(job)
            write_json(state_file, state)
        else:
            state = read_json(state_file)
        if (state["original"], state["total"]) != (filename, total) or index > state["next"]:
            raise Problem("Dieser Block passt nicht zur laufenden Übertragung.", 409)
        if index == state["next"]:
            remaining = limit - state["size"]
            state["size"] = save_part(
                job / "body",
                item.stream,
                state["size"],
                min(CHUNK, remaining) if chunked else remaining,
                current_app.config["MIN_FREE_BYTES"],
            )
            if index == 0 and (thumb := request.files.get("thumb")):
                data = thumb.stream.read(600 * 1024 + 1)
                if 0 < len(data) <= 600 * 1024 and data.startswith(b"\xff\xd8\xff"):
                    preview(io.BytesIO(data), job / "preview.jpg")
            state["next"] += 1
            write_json(state_file, state)
        complete = state["next"] == total
        if complete:
            publish(folder, job, state)
        return jsonify(
            ok=True,
            complete=complete,
            received=state["next"],
            total=total,
            filename=state["filename"] if complete else None,
        )


@media.post("/upload")
def upload():
    return receive(False)


@media.post("/upload/chunk")
def upload_chunk():
    return receive(True)


@media.get("/upload/status/<identifier>")
def upload_status(identifier):
    _, event = guest()
    if not UPLOAD_ID.fullmatch(identifier):
        abort(400)
    state = storage().folder(event) / ".pending" / identifier / "state.json"
    if not state.exists():
        return jsonify(received=0, complete=False)
    data = read_json(state)
    return jsonify(received=data["next"], complete=(state.parents[2] / data["filename"]).is_file())


@media.get("/gallery/list")
def gallery_list():
    slug, event = guest()
    folder = storage().folder(event)
    names = read_names(folder)
    items = []
    for path in files_in(folder):
        stat = path.stat()
        urls = {"fn": path.name, "event": slug}
        items.append(
            {
                "f": path.name,
                "k": "video" if path.suffix.lower() in VIDEO else "image",
                "n": names.get(path.name, ""),
                "t": int(stat.st_mtime),
                "s": stat.st_size,
                "has_preview": path.suffix.lower() in IMAGE
                or (folder / ".thumbs" / (path.name + ".jpg")).is_file(),
                "thumb": url_for(".thumbnail", **urls),
                "url": url_for(".original", **urls),
                "dl": url_for(".original", dl=1, **urls),
            }
        )
    items.sort(key=lambda item: (item["t"], item["f"]), reverse=True)
    return jsonify(ok=True, items=items)


@media.get("/gallery/file/<path:fn>")
def original(fn):
    _, event = guest()
    path = media_file(storage().folder(event), fn)
    return send_file(path, as_attachment=request.args.get("dl") == "1", conditional=True)


@media.get("/gallery/thumb/<path:fn>")
def thumbnail(fn):
    _, event = guest()
    store = storage()
    folder = store.folder(event)
    path = media_file(folder, fn)
    target = folder / ".thumbs" / (fn + ".jpg")
    if target.is_symlink():
        abort(404)
    if not target.is_file():
        if path.suffix.lower() in VIDEO:
            abort(404)
        with locked(folder / ".preview.lock"):
            if not target.is_file():
                tmp = target.parent / ".preview.tmp"
                try:
                    if not preview(path, tmp):
                        abort(404)
                    os.replace(tmp, target)
                finally:
                    tmp.unlink(missing_ok=True)
    return send_file(target, mimetype="image/jpeg", conditional=True)


class ZipBuffer(io.RawIOBase):
    def __init__(self):
        self.data = bytearray()

    def writable(self):
        return True

    def write(self, block):
        self.data.extend(block)
        return len(block)

    def drain(self):
        data = bytes(self.data)
        self.data.clear()
        return data


def zip_chunks(entries):
    buffer = ZipBuffer()
    with zipfile.ZipFile(buffer, "w", allowZip64=True) as archive:
        for name, path in entries:
            info = zipfile.ZipInfo.from_file(path, name, strict_timestamps=False)
            with path.open("rb") as source, archive.open(info, "w", force_zip64=True) as member:
                while block := source.read(1024**2):
                    member.write(block)
                    yield buffer.drain()
            yield buffer.drain()
    yield buffer.drain()


def zip_response(entries, download):
    response = Response(stream_with_context(zip_chunks(entries)), mimetype="application/zip")
    response.headers.set("Content-Disposition", "attachment", filename=download)
    response.headers["X-Accel-Buffering"] = "no"
    return response


@media.post("/gallery/zip")
def gallery_zip():
    _, event = guest()
    folder = storage().folder(event)
    if request.form.get("all") == "1":
        paths = sorted(files_in(folder))
    else:
        paths = [media_file(folder, name) for name in dict.fromkeys(request.form.getlist("f"))]
    if not paths:
        raise Problem("Bitte zuerst Dateien auswählen.")
    names = read_names(folder)
    entries = [
        (f"{secure_filename(names.get(p.name, '')) or 'ohne-Name'}/{p.name}", p) for p in paths
    ]
    return zip_response(entries, (secure_filename(event["title"]) or "Fotos") + ".zip")
