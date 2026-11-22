import hashlib
import io
import os
import re
import shutil
import subprocess
import threading
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import zxingcpp
from flask import jsonify, request
from PIL import Image
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from foto_upload import create_app

DEMO_ALBUMS = {
    "gartenfest": {
        "title": "Gartenfest",
        "subtitle": "Fotos und Videos vom gemeinsamen Abend.",
        "password": "Testfest",
        "allow_comments": True,
    },
    "see": {
        "title": "Sommer am See",
        "subtitle": "Die Bilder unserer Reise.",
        "password": "Testsommer",
    },
}


@pytest.fixture
def attempts():
    return []


@pytest.fixture
def site(tmp_path, attempts):
    app = create_app(
        {
            "DATA_DIR": tmp_path,
            "ADMIN_PASSWORD": "Manager-Test",
            "SEED_EVENTS": DEMO_ALBUMS,
            "MIN_FREE_BYTES": 0,
            "PUBLIC_URL": "",
        }
    )

    @app.after_request
    def simulate_lost_ack(response):
        if request.path == "/upload/chunk":
            index = int(request.form["index"])
            attempts.append(index)
            if index == 1 and attempts.count(1) == 1:
                failed = jsonify(error="Testunterbrechung")
                failed.status_code = 503
                return failed
        return response

    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()


def shot(page, name):
    output = os.getenv("FOTO_TEST_SHOTS")
    if output:
        path = Path(output)
        path.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=path / (name + ".png"), animations="disabled")


def assert_fits(page):
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def scan(page):
    codes = page.get_by_role("img", name="QR-Code zur Startseite")
    expect(codes).to_have_count(1)
    expect(codes).to_be_visible()
    codes.evaluate("image => image.decode()")
    result = zxingcpp.read_barcode(Image.open(io.BytesIO(codes.screenshot())))
    assert result
    return result.text


@pytest.mark.parametrize("width,height", [(360, 800), (390, 844), (1280, 800)])
def test_guests(site, browser, width, height):
    context = browser.new_context(
        viewport={"width": width, "height": height}, is_mobile=width < 500, has_touch=width < 500
    )
    # Screenshots must also work with external resources blocked.
    context.route(
        re.compile("^https?://"),
        lambda route: (
            route.continue_() if route.request.url.startswith(site + "/") else route.abort()
        ),
    )
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(site)
        expect(page.get_by_role("heading", name="Gemeinsame Fotoalben")).to_be_visible()
        assert_fits(page)
        target = scan(page)
        assert target == site + "/"
        scan_page = context.new_page()
        scan_page.goto(target)
        expect(scan_page.get_by_role("link", name=re.compile("Gartenfest"))).to_be_visible()
        scan_page.close()
        shot(page, "start-" + str(width))
        page.get_by_role("link", name=re.compile("Gartenfest")).click()
        page.get_by_label("Albumpasswort").fill("falscher Versuch")
        page.get_by_role("button", name="Album öffnen").click()
        expect(page.get_by_role("alert")).to_contain_text("Passwort")
        page.get_by_label("Albumpasswort").fill("Testfest")
        page.get_by_role("button", name="Anzeigen").click()
        expect(page.get_by_label("Albumpasswort")).to_have_attribute("type", "text")
        page.get_by_role("button", name="Album öffnen").click()
        expect(page.get_by_role("heading", name="Fotos hinzufügen")).to_be_visible()
        assert_fits(page)
        assert scan(page) == target
        shot(page, "album-" + str(width))
        page.locator("#who").fill("Lena")
        content = (Path(__file__).parent / "foto_upload/static/cover.webp").read_bytes()
        page.locator("#files").set_input_files(
            {"name": "Sommer.webp", "mimeType": "image/webp", "buffer": content}
        )
        expect(page.locator("#summary")).to_have_text("1 von 1 gespeichert")
        expect(page.locator("#grid article")).to_have_count(1)
        page.locator("#gallery-view").select_option("timeline")
        expect(page.locator(".timeline-day")).to_have_count(1)
        page.locator("#gallery-view").select_option("map")
        expect(page.locator("#gallery-status")).to_contain_text("Keine Fotos mit GPS")
        page.locator("#gallery-view").select_option("grid")
        page.get_by_role("button", name="Diashow").click()
        expect(page.get_by_role("button", name="Pause")).to_be_visible()
        page.get_by_role("button", name="Pause").click()
        page.keyboard.press("Escape")
        page.get_by_role("button", name=re.compile("Foto öffnen")).click()
        expect(page.locator("#stage img")).to_be_visible()
        page.get_by_role("button", name=re.compile("Favorit")).click()
        expect(page.get_by_role("button", name=re.compile(r"Favorit \(1\)"))).to_be_visible()
        page.locator("#comment-text").fill("Ein schönes Foto!")
        page.locator("#comment-form").get_by_role("button", name="Absenden").click()
        expect(page.locator("#comment-list")).to_contain_text("Ein schönes Foto!")
        with page.expect_download() as download:
            page.get_by_role("link", name="Original laden").click()
        assert download.value.path().read_bytes() == content
        shot(page, "grossansicht-" + str(width))
        page.keyboard.press("Escape")
        page.get_by_label("Person", exact=True).select_option(":Lena")
        page.get_by_role("button", name="Alle wählen").click()
        with page.expect_download() as download:
            page.get_by_role("button", name="Auswahl als ZIP (1)").click()
        with zipfile.ZipFile(download.value.path()) as archive:
            (name,) = archive.namelist()
            assert name.startswith("Lena/") and archive.read(name) == content
        context.set_offline(True)
        expect(page.locator("#network")).to_be_visible()
        context.set_offline(False)
        expect(page.locator("#network")).to_be_hidden()
        page.get_by_role("button", name="Abmelden").click()
        expect(page.get_by_role("heading", name="Gemeinsame Fotoalben")).to_be_visible()
        page.locator("#language").select_option("en")
        expect(page.get_by_role("heading", name="Shared photo albums")).to_be_visible()
        page.locator("#language").select_option("de")
        assert not errors, errors
    finally:
        context.close()


def test_admin(site, browser):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.goto(site + "/admin")
        page.get_by_label("Adminpasswort").fill("Manager-Test")
        page.get_by_role("button", name="Anmelden").click()
        page.locator("#create summary").click()
        form = page.locator("#new-album")
        form.get_by_label("Albumname").fill("Wandertag")
        form.get_by_label("Albumpasswort").fill("Testberg")
        form.get_by_role("button", name="Anlegen").click()
        album = page.locator('[data-slug="wandertag"]')
        expect(album).to_be_visible()
        album.get_by_label("Gästelink ohne Passwort freigeben").check()
        album.get_by_role("button", name="Speichern").click()
        invite = album.get_by_role("link", name="Gästelink öffnen")
        expect(invite).to_be_visible()
        visitor = browser.new_page()
        try:
            visitor.goto(invite.get_attribute("href"))
            expect(visitor.get_by_role("heading", name="Fotos hinzufügen")).to_be_visible()
            assert not urlsplit(visitor.url).query
        finally:
            visitor.close()
        shot(page, "verwaltung-390")
        assert_fits(page)
        page.get_by_label("Alben suchen").fill("Wandertag")
        expect(page.locator("#manage > details")).to_have_count(1)
        page.get_by_label("Alben suchen").fill("")
        page.get_by_label("Sortieren").select_option("files")
        page.get_by_text("Sicherung & Pflege").click()
        expect(page.locator("#disk-space")).to_contain_text("frei")
        album.get_by_text("Dateien verwalten").click()
        album.get_by_role("button", name="Dateien anzeigen").click()
        expect(album.get_by_text("Keine Dateien vorhanden.")).to_be_visible()
        page.once("dialog", lambda confirmation: confirmation.accept())
        album.get_by_role("button", name="Archivieren").click()
        expect(album.get_by_text(re.compile("Archiviert"))).to_be_visible()
        album.get_by_role("button", name="Wiederherstellen").click()
        expect(album.get_by_text(re.compile("Aktiv"))).to_be_visible()
    finally:
        page.close()


def test_large_transfer_retries_one_block(site, browser, attempts):
    page = browser.new_page()
    try:
        page.goto(site + "/event/gartenfest")
        page.get_by_label("Albumpasswort").fill("Testfest")
        page.get_by_role("button", name="Album öffnen").click()
        expect(page.locator("#files")).to_be_enabled()
        page.evaluate("""async () => {
          const data = await (await fetch('/static/cover.webp')).arrayBuffer();
          const file = new File([data, new Uint8Array(17 * 1024 * 1024)], 'gross.webp', {type:'image/webp'});
          const transfer = new DataTransfer();
          transfer.items.add(file);
          const input = document.querySelector('#files');
          input.files = transfer.files;
          input.dispatchEvent(new Event('change'));
        }""")
        expect(page.locator("#summary")).to_have_text("1 von 1 gespeichert", timeout=25000)
        assert attempts == [0, 1, 1, 2]
        with page.expect_download() as result:
            page.locator(".tile footer a").click()
        original = (Path(__file__).parent / "foto_upload/static/cover.webp").read_bytes()
        expected = hashlib.sha256(original + bytes(17 * 1024**2)).digest()
        assert hashlib.sha256(result.value.path().read_bytes()).digest() == expected
    finally:
        page.close()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="Videosimulation benötigt FFmpeg")
def test_video_and_camera_picker(site, browser, tmp_path):
    clip = tmp_path / "film.webm"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=green:s=64x64:r=5:d=1",
            "-c:v",
            "libvpx",
            str(clip),
        ],
        check=True,
    )
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.goto(site + "/event/gartenfest")
        page.get_by_label("Albumpasswort").fill("Testfest")
        page.get_by_role("button", name="Album öffnen").click()
        expect(page.locator("#files")).to_be_enabled()
        page.locator("#files").set_input_files(clip)
        expect(page.locator("#summary")).to_have_text("1 von 1 gespeichert", timeout=12000)
        page.get_by_role("button", name=re.compile("Video öffnen")).click()
        expect(page.locator("#stage video")).to_have_js_property("readyState", 4)
        page.keyboard.press("Escape")
        camera = page.locator("#camera")
        expect(camera).to_have_attribute("capture", "environment")
        camera.set_input_files(Path(__file__).parent / "foto_upload/static/icon-192.png")
        expect(page.locator("#summary")).to_have_text("2 von 2 gespeichert")
    finally:
        page.close()
