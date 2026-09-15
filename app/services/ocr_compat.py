"""Compatibility helpers for the classification-only ddddocr integration."""

from __future__ import annotations

import importlib
import sys
import types


def ensure_opencv_module() -> types.ModuleType:
    """Provide a fail-closed cv2 stub when OpenCV is intentionally absent.

    ddddocr 1.6.1 imports optional preprocessing/detection helpers when the
    package is loaded, and those helpers probe ``cv2`` eagerly. The project's
    captcha path only calls the Pillow/NumPy/ONNX classification pipeline, so a
    stub lets that supported path load without bundling the OpenCV wheel. Any
    accidental use of an OpenCV-only API still fails immediately.
    """

    existing = sys.modules.get("cv2")
    if existing is not None:
        return existing

    try:
        return importlib.import_module("cv2")
    except ModuleNotFoundError as exc:
        if exc.name != "cv2":
            raise

    stub = types.ModuleType("cv2")

    def unavailable(name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        raise RuntimeError(
            "此发布包只支持 ddddocr 验证码分类；未包含 OpenCV 功能：{0}".format(name)
        )

    stub.__getattr__ = unavailable
    sys.modules["cv2"] = stub
    return stub
