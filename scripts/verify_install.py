"""Verify a fresh installation over HTTP. Read its bootstrap password from stdin."""

import json
import sys
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, build_opener


def main():
    base = sys.argv[1].rstrip("/")
    password = sys.stdin.read().strip()
    if not password:
        raise ValueError("Missing bootstrap password")
    browser = build_opener(HTTPCookieProcessor(CookieJar()))
    with browser.open(base + "/health?ready=1", timeout=10) as response:
        assert json.load(response)["ok"]
    with browser.open(base + "/qr.png", timeout=10) as response:
        assert response.read(8) == b"\x89PNG\r\n\x1a\n"
    form = urlencode({"password": password}).encode()
    with browser.open(base + "/admin", data=form, timeout=10) as response:
        assert response.status == 200
    with browser.open(base + "/admin/api/events", timeout=10) as response:
        assert json.load(response) == []
    print("Health, QR code and first admin login verified.")


if __name__ == "__main__":
    main()
