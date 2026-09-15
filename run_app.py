"""启动西电研究生选课桌面应用。"""

import sys
import tempfile
from pathlib import Path

try:
    from app.main import main
except ModuleNotFoundError as exc:
    if exc.name and exc.name.startswith("PySide6"):
        raise SystemExit(
            "缺少桌面依赖 PySide6，请执行：python -m pip install -r requirements.txt"
        ) from exc
    raise


def self_test() -> None:
    """验证发布包内的 OCR 运行时、模型文件和 Windows DPAPI。"""

    import ddddocr

    from app.services.credential_store import CredentialStore

    ocr = ddddocr.DdddOcr(show_ad=False)
    if not callable(getattr(ocr, "classification", None)):
        raise RuntimeError("ddddocr 初始化后缺少 classification 方法")
    with tempfile.TemporaryDirectory() as directory:
        store = CredentialStore(Path(directory) / "credentials.json")
        store.save("release-self-test", "release-self-test-password")
        saved = store.load()
        if saved.user_id != "release-self-test" or saved.password != "release-self-test-password":
            raise RuntimeError("Windows DPAPI 自检结果不一致")
        if "release-self-test-password" in store.path.read_text(encoding="utf-8"):
            raise RuntimeError("凭据文件包含明文密码")
        store.clear()


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
        raise SystemExit(0)
    raise SystemExit(main())
