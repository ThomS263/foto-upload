"""Produce the exact Apps/ directory to submit to the CasaOS store."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import yaml


def main():
    root = Path(__file__).resolve().parents[1]
    album = root / "Apps" / "FotoUpload"
    template = (album / "docker-compose.yml").read_text(encoding="utf-8")
    manifest = yaml.safe_load(template)
    version = manifest["x-casaos"]["version"]
    if manifest["services"]["foto-upload"]["image"].split(":")[-1] != version:
        raise ValueError("Store-Version und Image-Tag stimmen nicht überein.")
    output = root / "dist" / f"foto-upload-casaos-{version}.zip"
    output.parent.mkdir(exist_ok=True)
    # The manual installer loads the archive first and has no store-provided AppID.
    manual = output.with_name("foto-upload-casaos.yaml")
    service = manifest["services"]["foto-upload"]
    service["pull_policy"] = "never"
    for volume in service["volumes"]:
        volume["source"] = volume["source"].replace("$AppID", manifest["name"])
    manual.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    files = (
        "docker-compose.yml",
        "icon.svg",
        "icon.png",
        "thumbnail.png",
        "screenshot-1.png",
        "screenshot-2.png",
    )
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name in files:
            path = album / name
            archive.write(path, path.relative_to(root))
    print(output)
    print(manual)


if __name__ == "__main__":
    main()
