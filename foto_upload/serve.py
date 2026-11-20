"""Container entry point. Respect an existing volume owner's permissions."""

import os
import sys
from pathlib import Path


def main():
    root = Path(os.environ["PHOTO_DATA_DIR"])
    root.mkdir(parents=True, exist_ok=True)
    if os.geteuid() == 0:
        owner = root.stat()
        uid, gid = owner.st_uid, owner.st_gid
        if not uid and not any(root.iterdir()):
            uid = gid = 10001
            os.chown(root, uid, gid)
        if uid:
            os.setgroups([])
            os.setgid(gid)
            os.setuid(uid)
    os.umask(0o077)
    os.execvp(
        "gunicorn",
        [
            "gunicorn",
            "--bind",
            "0.0.0.0:8080",
            "--workers",
            "2",
            "--threads",
            "4",
            "--timeout",
            "180",
            sys.argv[1],
        ],
    )


if __name__ == "__main__":
    main()
