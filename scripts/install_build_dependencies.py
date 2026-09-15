from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DDDDOCR_VERSION = "1.6.1"


def run(*arguments: str) -> None:
    subprocess.run([sys.executable, "-m", "pip", *arguments], cwd=ROOT, check=True)


def main() -> int:
    """安装发布所需最小依赖，不安装分类链路未使用的 OpenCV。"""

    run("install", "--upgrade", "pip")
    run("install", "-r", str(ROOT / "requirements-build.txt"))
    run("install", "--no-deps", "ddddocr=={0}".format(DDDDOCR_VERSION))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
