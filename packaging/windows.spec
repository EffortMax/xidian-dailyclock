# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import get_package_paths


ROOT = Path(SPECPATH).parent
_, ddddocr_package = get_package_paths("ddddocr")
ocr_model = Path(ddddocr_package) / "common_old.onnx"
if not ocr_model.is_file():
    raise FileNotFoundError("缺少固定版本 ddddocr 的 common_old.onnx：{0}".format(ocr_model))

# 应用只调用默认 OCR 分类，不使用 beta 模型、目标检测、滑块匹配或 API 服务。
# 仅收集实际加载的模型；onnxruntime DLL 继续由 PyInstaller 官方 hook 收集。
datas = [(str(ocr_model), "ddddocr")]

analysis_excludes = [
    "OpenSSL",
    "_cffi_backend",
    "cryptography",
    "cv2",
    "numpy.f2py",
    "numpy.testing",
    "PIL.AvifImagePlugin",
    "PIL.ImageCms",
    "PIL.ImageMath",
    "PIL.ImageTk",
    "PIL.WebPImagePlugin",
    "PySide6.QtNetwork",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtVirtualKeyboard",
    "threadpoolctl",
    "yaml",
]

a = Analysis(
    [str(ROOT / "run_app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=["ddddocr"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=analysis_excludes,
    noarchive=False,
    optimize=0,
)


def normalized_destination(entry):
    """规范化 PyInstaller 在 Windows TOC 中可能重复的路径分隔符。"""

    name = entry[0].replace("\\", "/").lower()
    while "//" in name:
        name = name.replace("//", "/")
    return name


qt_addon_binaries = {
    "qt6network.dll",
    "qt6opengl.dll",
    "qt6openglwidgets.dll",
    "qt6pdf.dll",
    "qt6pdfwidgets.dll",
    "qt6qml.dll",
    "qt6qmlmeta.dll",
    "qt6qmlmodels.dll",
    "qt6qmlworkerscript.dll",
    "qt6quick.dll",
    "qt6svg.dll",
    "qt6svgwidgets.dll",
    "qt6virtualkeyboard.dll",
    "qtnetwork.pyd",
    "qtopengl.pyd",
    "qtopenglwidgets.pyd",
    "qtpdf.pyd",
    "qtpdfwidgets.pyd",
    "qtqml.pyd",
    "qtquick.pyd",
    "qtsvg.pyd",
    "qtsvgwidgets.pyd",
    "qtvirtualkeyboard.pyd",
}
pil_optional_extensions = (
    "_avif.",
    "_imagingcms.",
    "_imagingmath.",
    "_imagingtk.",
    "_webp.",
)


def should_drop(entry):
    name = normalized_destination(entry)
    basename = name.rsplit("/", 1)[-1]
    if name == "cv2" or name.startswith("cv2/"):
        return True
    if name == "cryptography" or name.startswith(("cryptography/", "cryptography-")):
        return True
    if name == "yaml" or name.startswith("yaml/"):
        return True
    if basename in {"_cffi_backend.pyd", "libcrypto-3-x64.dll", "libssl-3-x64.dll"}:
        return True
    if basename.startswith("_cffi_backend."):
        return True
    if name.startswith("pil/") and basename.startswith(pil_optional_extensions):
        return True
    if name.startswith("pyside6/translations/"):
        return True
    if name.startswith("pyside6/plugins/platforms/"):
        return basename != "qwindows.dll"
    if name.startswith("pyside6/plugins/imageformats/"):
        return basename != "qjpeg.dll"
    if name.startswith((
        "pyside6/plugins/generic/",
        "pyside6/plugins/iconengines/",
        "pyside6/plugins/networkinformation/",
        "pyside6/plugins/platforminputcontexts/",
        "pyside6/plugins/tls/",
    )):
        return True
    if name.startswith("pyside6/") and basename in qt_addon_binaries:
        return True
    return False


a.binaries = [entry for entry in a.binaries if not should_drop(entry)]
a.datas = [entry for entry in a.datas if not should_drop(entry)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="XDU-Course-Assistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(ROOT / "packaging" / "version_info.txt"),
)
