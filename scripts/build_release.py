from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import __version__  # noqa: E402 - 允许直接运行 scripts 下的脚本


EXECUTABLE_NAME = "XDU-Course-Assistant.exe"
RELEASE_NAME = "XDU-Course-Assistant-v{0}-windows-x64.exe".format(__version__)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(ROOT / "dist"),
            "--workpath",
            str(ROOT / "build"),
            str(ROOT / "packaging" / "windows.spec"),
        ],
        cwd=ROOT,
        check=True,
    )

    source = ROOT / "dist" / EXECUTABLE_NAME
    if not source.is_file():
        raise FileNotFoundError("PyInstaller 未生成预期文件：{0}".format(source))
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "audit_release_archive.py"), str(source)],
        cwd=ROOT,
        check=True,
    )
    release_dir = ROOT / "release"
    release_dir.mkdir(parents=True, exist_ok=True)
    artifact = release_dir / RELEASE_NAME
    shutil.copy2(source, artifact)
    checksum = sha256(artifact)
    checksum_path = release_dir / (RELEASE_NAME + ".sha256")
    checksum_path.write_bytes(
        "{0} *{1}\n".format(checksum, artifact.name).encode("ascii")
    )
    print("Release artifact: {0}".format(artifact))
    print("SHA-256: {0}".format(checksum))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
