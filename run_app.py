"""启动西电研究生选课桌面应用。"""

import base64
import os
import sys
import tempfile
import traceback
from pathlib import Path

try:
    from app.main import main
except ModuleNotFoundError as exc:
    if exc.name and exc.name.startswith("PySide6"):
        raise SystemExit(
            "缺少桌面依赖 PySide6，请执行：python -m pip install -r requirements.txt"
        ) from exc
    raise


_OCR_SMOKE_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAoHBwgHBgoICAgLCgoLDhgQDg0NDh0VFhEYIx8lJCIfIiEmKzcvJik0KSEiMEEx"
    "NDk7Pj4+JS5ESUM8SDc9Pjv/wAALCAAsAHgBAREA/8QAGwABAAIDAQEAAAAAAAAAAAAAAAUGAQQHAgP/xAA1EAAABQMBBQYE"
    "BQUAAAAAAAAAAQIDBAUGESEHEhMxQRQVIjJRYRZTYoE3UnGRsXSy0eHw/9oACAEBAAA/AOzAAAAAAAAAACr3VPudb6aPbVOI"
    "nX2t5ypvqImYxGZloXNS9M46ZLQxFbGFrd2fNOOKNa1yXjUpR5MzNWpmPUyz592XdUHbnJ8qHGJCKfEbk7qHvzLUSDznJdc"
    "cy9BoU6KVl7UoFvUiS+ql1SKt1yE66bhR1JJRkpJnqRHu4+5+2JCo2jOuy75jly8UrfitpTBityN1Lyj8y17p5098cy9DGh"
    "ZiipO0ap27RZrsyhtRCeNCnTdTFdyRbiVH7Z0/wLTeFyKt6loTEa7RVJq+BAjFzccPqf0lzP8A2KrsfZlxn7ojzpHaJTVTN"
    "Dz3zFlkjP7mOlAAAADCvKf6Cg7Ffw7Y/qHf7hMXfejNucGBDjqqFamaRYLepn9SvRP84P3MtezbRlUyXIuCvyCl16eWHVl5"
    "GEfLR+xZP2+5ych+gXe1U7ecdKWUZSW5rBGtBpPOSLOnVPQ+gpsKAmwtptNodFdc7qrTTi3YS1b/AAlpSZktJnrjQufv7Y1o"
    "NwTSvOdcFctG5ZDzRnHpzcemmtthnqrJmXiV1PHLrro2ZXDvXTcMfuarF3jVXHeIcbwRvMe68efArpjXUdXAAAAGDLJYED"
    "ZVr/B9ut0jtnbNxxa+LwuHnePOMZP+RW5GzWtndU+4YV5KiSpij17uSs2286II1L5EREWmM4EvRrZuqBVmJVRvZypRW88S"
    "KqAhsnMkZF4iUZlgzI/sMVqxlyq8qv0KtP0SpuoJD7jbSXW3iLlvIPQz0L9h9beslFJq7tcqdTfrFXdRw+1PpJJNo9EILR"
    "P/AHqebQK/bVrfDs+tSu29o72mqlbvC3OFkzPdzk88+egsAAAAAAAAAAAAAAAAAAAAAAAAP//Z"
)


def self_test() -> None:
    """验证发布包内的 OCR 分类、JPEG 解码、模型和 Windows DPAPI。"""

    from app.services.ocr_compat import ensure_opencv_module

    ensure_opencv_module()
    import ddddocr

    from app.services.credential_store import CredentialStore

    ocr = ddddocr.DdddOcr(show_ad=False)
    if not callable(getattr(ocr, "classification", None)):
        raise RuntimeError("ddddocr 初始化后缺少 classification 方法")
    ocr_result = ocr.classification(base64.b64decode(_OCR_SMOKE_JPEG_B64))
    if ocr_result != "1234":
        raise RuntimeError("OCR JPEG 分类自检失败：期望 1234，实际 {0!r}".format(ocr_result))
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
        report_path = Path(
            os.environ.get("XDU_SELF_TEST_REPORT")
            or Path(tempfile.gettempdir()) / "XDU-Course-Assistant-self-test.log"
        )
        try:
            self_test()
        except Exception:
            report_path.write_text(traceback.format_exc(), encoding="utf-8")
            raise
        else:
            report_path.unlink(missing_ok=True)
        raise SystemExit(0)
    raise SystemExit(main())
