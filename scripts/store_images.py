"""Capture the real web interface with fictitious albums for the catalog."""

import tempfile
import threading
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from foto_upload import create_app


def main():
    root = Path(__file__).resolve().parents[1]
    out = root / "Apps" / "FotoUpload"
    with tempfile.TemporaryDirectory() as data:
        app = create_app(
            {
                "DATA_DIR": data,
                "PUBLIC_URL": "https://fotos.example",
                "MIN_FREE_BYTES": 0,
                "SEED_EVENTS": {
                    "gartenfest": {
                        "title": "Gartenfest",
                        "subtitle": "Fotos und Videos vom gemeinsamen Abend.",
                        "password": "Demo",
                    },
                    "see": {
                        "title": "Sommer am See",
                        "subtitle": "Die Bilder unserer Reise.",
                        "password": "Demo",
                    },
                },
            }
        )
        client = app.test_client()
        client.post("/enter", json={"event": "gartenfest", "password": "Demo"})
        with (root / "foto_upload/static/cover.webp").open("rb") as photo:
            response = client.post("/upload", data={"name": "Lena", "file": (photo, "Sommer.webp")})
            assert response.json["complete"]
        server = make_server("127.0.0.1", 0, app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={"width": 1280, "height": 800})
                page.goto(f"http://127.0.0.1:{server.server_port}/", wait_until="networkidle")
                page.screenshot(path=out / "thumbnail.png")
                page.get_by_role("link", name="Gartenfest", exact=False).click()
                page.get_by_label("Albumpasswort").fill("Demo")
                page.get_by_role("button", name="Album öffnen").click()
                expect(page.locator(".tile")).to_have_count(1)
                page.set_viewport_size({"width": 1280, "height": 940})
                page.screenshot(path=out / "screenshot-1.png")
                page.set_viewport_size({"width": 390, "height": 844})
                page.goto(f"http://127.0.0.1:{server.server_port}/", wait_until="networkidle")
                page.screenshot(path=out / "screenshot-2.png")
                browser.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
