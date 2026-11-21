import io
import json
import os
import tempfile
import time
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import zxingcpp
from itsdangerous import URLSafeTimedSerializer
from PIL import Image
from werkzeug.security import generate_password_hash

from foto_upload import create_app
from foto_upload.media import CHUNK


def jpeg():
    data = io.BytesIO()
    Image.new("RGB", (40, 32), "#137d63").save(data, format="JPEG")
    return data.getvalue()


def decoded(image):
    with Image.open(io.BytesIO(image)) as qr:
        result = zxingcpp.read_barcode(qr)
        assert result is not None
        return result.text


class AlbumsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.config = {
            "TESTING": True,
            "DATA_DIR": self.root,
            "ADMIN_PASSWORD": "test-manager",
            "PUBLIC_URL": "https://alben.example",
            "MIN_FREE_BYTES": 0,
            "SEED_EVENTS": {"sommer": {"title": "Sommer", "folder": "ferien", "password": "Gast"}},
        }
        self.app = create_app(self.config)
        self.client = self.app.test_client()

    def enter(self, client=None, slug="sommer", password="Gast"):
        client = client or self.client
        self.assertEqual(
            client.post("/enter", json={"event": slug, "password": password}).status_code, 200
        )
        return client

    def admin(self, client=None, password="test-manager"):
        client = client or self.client
        self.assertEqual(client.post("/admin", data={"password": password}).status_code, 303)
        return client

    def chunk(self, identifier, index, data, client=None, total=2, name="strand.jpg", extra=None):
        return (client or self.client).post(
            "/upload/chunk",
            data={
                "index": str(index),
                "total": str(total),
                "upload_id": identifier,
                "name": "Lena",
                "filename": name,
                "chunk": (io.BytesIO(data), "block"),
                **(extra or {}),
            },
        )

    def test_login_gallery_and_separate_album(self):
        self.assertIn("Sommer", self.client.get("/").text)
        self.assertEqual(self.client.get("/health").json["files"], {"sommer": 0})
        self.assertTrue(self.client.get("/health?ready=1").json["ok"])
        self.assertEqual(self.client.get("/gallery/list").status_code, 401)
        self.assertEqual(self.client.post("/upload").status_code, 401)
        self.assertEqual(
            self.client.post("/enter", json={"event": "sommer", "password": "x"}).status_code, 401
        )
        self.enter()
        self.assertIn('id="files"', self.client.get("/event/sommer").text)
        self.assertEqual(self.client.get("/gallery/list?event=sommer").json["items"], [])
        self.assertEqual(self.client.get("/gallery/list?event=winter").status_code, 409)
        self.client.post("/leave")
        self.assertEqual(self.client.get("/gallery/list").status_code, 401)

    def test_clean_install_and_password_rotation(self):
        clean = self.root / "fresh"
        app = create_app(dict(self.config, DATA_DIR=clean, ADMIN_PASSWORD="", SEED_EVENTS={}))
        client = app.test_client()
        self.assertFalse(json.loads((clean / ".events.json").read_text()))
        bootstrap = clean / ".initial-admin-password"
        self.assertEqual(bootstrap.stat().st_mode & 0o777, 0o600)
        token = bootstrap.read_text().strip()
        self.admin(client, token)
        second = self.admin(app.test_client(), token)
        self.assertEqual(
            client.put(
                "/admin/api/admin-password", json={"password": "changed-long-password"}
            ).status_code,
            200,
        )
        self.assertFalse(bootstrap.exists())
        self.assertEqual(second.get("/admin/api/events").status_code, 401)
        self.assertEqual(client.get("/admin/api/events").status_code, 200)

    def test_migration_preserves_folder_names_files_and_existing_hashes(self):
        legacy = self.root / "legacy"
        folder = legacy / "uploads" / "standard"
        (folder / ".thumbs").mkdir(parents=True)
        (folder / "alt.jpg").write_bytes(jpeg())
        (folder / ".thumbs" / "alt.jpg.jpg").write_bytes(jpeg())
        (folder / ".meta.jsonl").write_text('{"f":"alt.jpg","n":"Anna"}\n')
        (legacy / ".secret").write_text("local-fixture-signing-key")
        admin_hash = generate_password_hash("bisher")
        (legacy / ".admin_password_hash").write_text(admin_hash)
        (legacy / ".events.json").write_text(
            json.dumps({"reise": {"title": "Reise", "folder": "standard", "password": "Gast"}})
        )
        (legacy / "uploads" / "Familie 2020").mkdir()
        config = dict(self.config, DATA_DIR=legacy, SEED_EVENTS={})
        app = create_app(config)
        self.enter(app.test_client(), "reise")
        client = self.enter(app.test_client(), "reise")
        (item,) = client.get("/gallery/list").json["items"]
        self.assertEqual((item["f"], item["n"]), ("alt.jpg", "Anna"))
        for key in ("url", "thumb"):
            with client.get(item[key]) as response:
                self.assertEqual(response.data, jpeg())
        events = json.loads((legacy / ".events.json").read_text())
        self.assertNotIn("password", events["reise"])
        self.assertNotIn("standard", events)
        self.assertTrue(events["familie-2020"]["archived"])
        self.admin(client, "bisher")
        client.put("/admin/api/events/familie-2020", json={"password": "Familie"})
        self.assertEqual(client.post("/admin/api/events/familie-2020/restore").status_code, 200)
        create_app(config)
        self.assertEqual(
            json.loads((legacy / ".events.json").read_text())["reise"]["password_hash"],
            events["reise"]["password_hash"],
        )
        self.assertEqual((legacy / ".admin_password_hash").read_text(), admin_hash)

    def test_damaged_catalog_is_preserved(self):
        self.app.extensions["albums"].catalog.write_text("broken")
        with self.assertRaises(ValueError):
            create_app(self.config)
        self.assertEqual(self.app.extensions["albums"].catalog.read_text(), "broken")

    def test_qrs_decode_guest_links_can_be_revoked(self):
        self.assertEqual(decoded(self.client.get("/qr.png").data), "https://alben.example/")
        self.assertEqual(decoded(self.client.get("/qr/sommer.png").data), "https://alben.example/")
        manager = self.admin()
        manager.put("/admin/api/events/sommer", json={"public_access": True})
        other = self.app.test_client()
        self.assertEqual(other.get("/qr/sommer.png").status_code, 401)
        link = urlsplit(decoded(manager.get("/qr/sommer.png").data))
        self.assertEqual((link.netloc, link.path), ("alben.example", "/event/sommer"))
        result = other.get(link.path + "?" + link.query)
        self.assertEqual(result.status_code, 303)
        self.assertNotIn("access=", result.headers["Location"])
        self.assertEqual(other.get("/gallery/list").status_code, 200)
        for enabled in (False, True):
            manager.put("/admin/api/events/sommer", json={"public_access": enabled})
        self.assertEqual(other.get("/gallery/list").status_code, 401)
        self.assertIn("Albumpasswort", other.get(link.path + "?" + link.query).text)

    def test_existing_printed_public_invite(self):
        config = dict(
            self.config,
            DATA_DIR=self.root / "printed",
            SEED_EVENTS={
                "alt": {"title": "Alt", "folder": "alt", "password": "Gast", "public_access": True}
            },
        )
        app = create_app(config)
        token = URLSafeTimedSerializer(app.secret_key, salt="event-access-v1").dumps(
            {"event": "alt", "public": True}
        )
        client = app.test_client()
        self.assertEqual(client.get("/event/alt?access=" + token).status_code, 303)
        self.assertEqual(client.get("/gallery/list").status_code, 200)

    def test_upload_thumbnail_duplicate_response_and_zip(self):
        self.enter()
        identifier = "a" * 32
        for _ in range(2):
            result = self.client.post(
                "/upload",
                data={
                    "file": (io.BytesIO(jpeg()), "Äpfel.jpg"),
                    "upload_id": identifier,
                    "name": "Lena",
                },
            )
            self.assertTrue(result.json["complete"])
        (item,) = self.client.get("/gallery/list").json["items"]
        self.assertEqual(item["n"], "Lena")
        with self.client.get(item["thumb"]) as response:
            self.assertEqual(Image.open(io.BytesIO(response.data)).size, (40, 32))
        with self.client.get(item["dl"], headers={"Range": "bytes=0-3"}) as response:
            self.assertEqual((response.status_code, response.data), (206, jpeg()[:4]))
        for selection in ({"all": "1"}, {"f": item["f"]}):
            with (
                self.client.post("/gallery/zip", data=selection) as response,
                zipfile.ZipFile(io.BytesIO(response.data)) as archive,
            ):
                self.assertEqual(archive.read("Lena/" + item["f"]), jpeg())

    def test_resume_across_workers_and_final_retry(self):
        first = self.enter()
        second = self.enter(create_app(self.config).test_client())
        identifier = "b" * 32
        self.assertEqual(self.chunk(identifier, 0, jpeg()[:16], first).json["received"], 1)
        self.assertEqual(second.get("/upload/status/" + identifier).json["received"], 1)
        self.assertEqual(self.chunk(identifier, 0, jpeg()[:16], second).json["received"], 1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(self.chunk, identifier, 1, jpeg()[16:], client)
                for client in (first, second)
            ]
        self.assertTrue(all(job.result().json["complete"] for job in futures))
        (item,) = first.get("/gallery/list").json["items"]
        with second.get(item["url"]) as response:
            self.assertEqual(response.data, jpeg())
        self.assertTrue(second.get("/upload/status/" + identifier).json["complete"])

    def test_media_limits_and_space(self):
        self.enter()
        for data, name in ((b"plain", "test.jpg"), (b"plain", "test.txt")):
            self.assertEqual(
                self.client.post("/upload", data={"file": (io.BytesIO(data), name)}).status_code,
                400,
            )
        self.assertEqual(self.chunk("c" * 32, 0, b"0" * (CHUNK + 1)).status_code, 413)
        self.app.config["MIN_FREE_BYTES"] = 2**62
        self.assertEqual(self.chunk("d" * 32, 0, jpeg()).status_code, 507)
        self.assertEqual(self.client.get("/gallery/list").json["items"], [])

    def test_rate_and_distinct_album_storage(self):
        manager = self.admin()
        self.assertEqual(
            manager.post(
                "/admin/api/events",
                json={"slug": "winter", "title": "Winter", "password": "Schnee"},
            ).status_code,
            201,
        )
        self.enter()
        identifier = "e" * 32
        self.chunk(identifier, 0, jpeg())
        guest = self.enter(self.app.test_client(), "winter", "Schnee")
        self.assertEqual(guest.get("/upload/status/" + identifier).json["received"], 0)
        self.assertEqual(guest.get("/gallery/list").json["items"], [])
        for _ in range(15):
            self.client.post("/enter", json={"event": "none", "password": "x"})
        self.assertEqual(
            self.client.post("/enter", json={"event": "none", "password": "x"}).status_code, 429
        )

    def test_heic_and_exif_previews_preserve_originals(self):
        self.enter()
        for name, fmt in (("handy.heic", "HEIF"), ("gedreht.jpg", "JPEG")):
            data = io.BytesIO()
            image = Image.new("RGB", (80, 40), "#2d6541")
            exif = Image.Exif()
            exif[274] = 6
            image.save(data, format=fmt, exif=exif.tobytes())
            original = data.getvalue()
            response = self.client.post("/upload", data={"file": (io.BytesIO(original), name)})
            self.assertTrue(response.json["complete"])
            with self.client.get("/gallery/thumb/" + response.json["filename"]) as thumb:
                self.assertEqual(Image.open(io.BytesIO(thumb.data)).size, (40, 80))
            with self.client.get("/gallery/file/" + response.json["filename"]) as file:
                self.assertEqual(file.data, original)

    def test_admin_lifecycle_backup_and_cleanup(self):
        self.assertEqual(self.client.get("/admin/backup").status_code, 401)
        self.admin()
        event_path = "/admin/api/events/sommer"
        guest = self.enter(self.app.test_client())
        self.client.put(event_path, json={"password": "neu"})
        self.assertEqual(guest.get("/gallery/list").status_code, 401)
        self.client.delete(event_path)
        self.assertNotIn("Sommer", self.client.get("/").text)
        self.client.post(event_path + "/restore")
        self.assertEqual(self.enter(guest, password="neu").get("/gallery/list").status_code, 200)
        folder = self.root / "uploads/ferien"
        (folder / "bestehend.jpg").write_bytes(jpeg())
        (folder / "altes-format.bin").write_bytes(b"original")
        (folder / ".thumbs/verwaist.jpg.jpg").write_bytes(jpeg())
        self.assertEqual(self.client.get("/admin/api/events").json[0]["orphan_thumbs"], 1)
        self.assertEqual(self.client.post("/admin/api/cleanup").json["removed"], 1)
        self.app.config["BACKUP_DIR"] = str(self.root / "zweiter-speicher")
        (self.root / "unrelated.txt").write_text("not app data")
        with self.client.get("/admin/backup") as response:
            archive = zipfile.ZipFile(io.BytesIO(response.data))
            self.assertEqual(archive.read("uploads/ferien/bestehend.jpg"), jpeg())
            self.assertEqual(archive.read("uploads/ferien/altes-format.bin"), b"original")
            self.assertIn(".secret", archive.namelist())
            self.assertNotIn("unrelated.txt", archive.namelist())
            self.assertEqual(
                next((self.root / "zweiter-speicher").glob("*.zip")).read_bytes(), response.data
            )

    def test_admin_file_management_and_storage(self):
        folder = self.root / "uploads/ferien"
        photo = folder / "urlaub.jpg"
        photo.write_bytes(jpeg())
        (folder / ".thumbs/urlaub.jpg.jpg").write_bytes(jpeg())
        self.assertEqual(self.client.get("/admin/api/storage").status_code, 401)
        self.assertEqual(
            self.client.delete("/admin/api/events/sommer/files/urlaub.jpg").status_code, 401
        )
        self.admin()
        self.assertGreater(self.client.get("/admin/api/storage").json["total"], 0)
        self.assertEqual(
            self.client.get("/admin/api/events/sommer/files").json["files"][0]["name"], "urlaub.jpg"
        )
        self.assertEqual(
            self.client.delete("/admin/api/events/sommer/files/urlaub.jpg").status_code, 200
        )
        self.assertFalse(photo.exists())
        self.assertTrue((folder / ".trash/urlaub.jpg").exists())
        self.assertEqual(self.client.post("/admin/api/cleanup").json["removed"], 0)
        self.assertEqual(self.client.get("/admin/api/events/sommer/files").json["files"], [])
        self.assertEqual(
            self.client.post(
                "/admin/api/events/sommer/trash", json={"name": "urlaub.jpg"}
            ).status_code,
            200,
        )
        self.assertEqual(photo.read_bytes(), jpeg())

    def test_android_zip_redirect_requires_same_session(self):
        self.enter()
        folder = self.root / "uploads/ferien"
        (folder / "strand.jpg").write_bytes(jpeg())
        response = self.client.post(
            "/gallery/zip", data={"f": "strand.jpg"}, headers={"User-Agent": "FotoUploadAndroid/1"}
        )
        self.assertEqual(response.status_code, 303)
        location = response.headers["Location"]
        self.assertEqual(self.app.test_client().get(location).status_code, 401)
        with (
            self.client.get(location) as downloaded,
            zipfile.ZipFile(io.BytesIO(downloaded.data)) as archive,
        ):
            self.assertEqual(archive.read("ohne-Name/strand.jpg"), jpeg())

    def test_share_expiry_and_automatic_backup(self):
        from foto_upload.admin import automatic_backup

        self.admin()
        event = "/admin/api/events/sommer"
        self.assertEqual(
            self.client.put(
                event, json={"public_access": True, "share_expires": int(time.time()) - 60}
            ).status_code,
            200,
        )
        link = self.client.get("/admin/api/events").json[0]["share"]
        self.assertIn(
            "Albumpasswort",
            self.app.test_client().get(urlsplit(link).path + "?" + urlsplit(link).query).text,
        )
        self.assertEqual(
            self.client.put("/admin/api/automatic-backup", json={"enabled": True}).status_code, 400
        )
        backup = self.root / "second-disk"
        backup.mkdir()
        self.app.config["BACKUP_DIR"] = str(backup)
        self.assertEqual(
            self.client.put("/admin/api/automatic-backup", json={"enabled": True}).status_code, 200
        )
        automatic_backup(self.app)
        status = self.client.get("/admin/api/automatic-backup").json["status"]
        self.assertTrue(status["success"])
        with zipfile.ZipFile(next(backup.glob("*.zip"))) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn(".events.json", archive.namelist())

    def test_stale_partial_expiry(self):
        self.enter()
        self.chunk("f" * 32, 0, jpeg()[:16])
        folder = self.root / "uploads/ferien/.pending" / ("f" * 32)
        os.utime(folder, (time.time() - 90000,) * 2)
        (self.root / ".locks/last-prune").unlink()
        create_app(self.config)
        self.assertFalse(folder.exists())


if __name__ == "__main__":
    unittest.main()
