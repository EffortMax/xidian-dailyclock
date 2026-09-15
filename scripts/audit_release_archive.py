from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


def normalized(name: str) -> str:
    value = name.replace("\\", "/").lower()
    while "//" in value:
        value = value.replace("//", "/")
    return value


def forbidden_reason(name: str) -> str | None:
    basename = name.rsplit("/", 1)[-1]
    if name in {"ddddocr/common.onnx", "ddddocr/common_det.onnx"}:
        return "未使用的 ddddocr beta/目标检测模型"
    if name == "cv2" or name.startswith("cv2/"):
        return "未使用的 OpenCV"
    if name == "cryptography" or name.startswith(("cryptography/", "cryptography-")):
        return "requests 可选 PyOpenSSL 链路"
    if name == "openssl" or name.startswith("openssl/"):
        return "requests 可选 PyOpenSSL 链路"
    if name == "threadpoolctl" or name.startswith("threadpoolctl/"):
        return "NumPy 可选线程池诊断链路"
    if name == "yaml" or name.startswith("yaml/"):
        return "NumPy 可选 YAML 展示链路"
    if basename.startswith("_cffi_backend.") or basename in {"libcrypto-3-x64.dll", "libssl-3-x64.dll"}:
        return "cryptography 可选运行时"
    if name.startswith("pil/") and basename.startswith((
        "_avif.", "_imagingcms.", "_imagingmath.", "_imagingtk.", "_webp.",
    )):
        return "未使用的 Pillow 非 JPEG 扩展"
    if name in {
        "pil/avifimageplugin", "pil/imagecms", "pil/imagemath", "pil/imagetk", "pil/webpimageplugin",
    }:
        return "未使用的 Pillow 非 JPEG 模块"
    if name.startswith("pyside6/translations/"):
        return "应用未加载的 Qt 翻译"
    if name.startswith("pyside6/plugins/platforms/") and basename != "qwindows.dll":
        return "未使用的 Qt 平台插件"
    if name.startswith("pyside6/plugins/imageformats/") and basename != "qjpeg.dll":
        return "未使用的 Qt 图片插件"
    if name.startswith((
        "pyside6/plugins/generic/",
        "pyside6/plugins/iconengines/",
        "pyside6/plugins/networkinformation/",
        "pyside6/plugins/platforminputcontexts/",
        "pyside6/plugins/tls/",
    )):
        return "未使用的 Qt 插件"
    if basename in {
        "qt6network.dll", "qt6opengl.dll", "qt6openglwidgets.dll", "qt6pdf.dll",
        "qt6pdfwidgets.dll", "qt6qml.dll", "qt6qmlmeta.dll", "qt6qmlmodels.dll",
        "qt6qmlworkerscript.dll", "qt6quick.dll", "qt6svg.dll", "qt6svgwidgets.dll",
        "qt6virtualkeyboard.dll", "qtnetwork.pyd", "qtopengl.pyd", "qtopenglwidgets.pyd",
        "qtpdf.pyd", "qtpdfwidgets.pyd", "qtqml.pyd", "qtquick.pyd", "qtsvg.pyd",
        "qtsvgwidgets.pyd", "qtvirtualkeyboard.pyd",
    }:
        return "未使用的 Qt Addons 组件"
    return None


def audit(path: Path) -> None:
    archive = CArchiveReader(str(path))
    names = {normalized(name) for name in archive.toc}
    pyz = archive.open_embedded_archive("PYZ.pyz")
    pure_names = {normalized(name).replace(".", "/") for name in pyz.toc}
    audited_names = names | pure_names
    required = {
        "_ssl.pyd",
        "ddddocr/common_old.onnx",
        "libcrypto-3.dll",
        "libssl-3.dll",
        "onnxruntime/capi/onnxruntime.dll",
        "onnxruntime/capi/onnxruntime_pybind11_state.pyd",
        "pil/_imaging.cp313-win_amd64.pyd",
        "pyside6/qt6core.dll",
        "pyside6/qt6gui.dll",
        "pyside6/qt6widgets.dll",
        "pyside6/opengl32sw.dll",
        "pyside6/plugins/platforms/qwindows.dll",
        "pyside6/plugins/imageformats/qjpeg.dll",
    }
    missing = sorted(required - names)
    forbidden = sorted(
        (name, forbidden_reason(name)) for name in audited_names if forbidden_reason(name)
    )
    if missing:
        raise RuntimeError("发布包缺少必要成员：{0}".format(", ".join(missing)))
    if forbidden:
        details = "; ".join("{0}（{1}）".format(name, reason) for name, reason in forbidden)
        raise RuntimeError("发布包仍包含待裁剪成员：{0}".format(details))
    print(
        "Archive audit passed: {0:,} bytes, {1} top-level + {2} PYZ entries, no forbidden members".format(
            path.stat().st_size,
            len(names),
            len(pure_names),
        )
    )


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: audit_release_archive.py <single-file.exe>")
    audit(Path(sys.argv[1]).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
