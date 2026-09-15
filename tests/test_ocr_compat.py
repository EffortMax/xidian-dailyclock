import importlib
import sys
import unittest
from unittest import mock

from app.services.ocr_compat import ensure_opencv_module


class OcrCompatibilityTests(unittest.TestCase):
    def test_missing_opencv_gets_fail_closed_stub(self):
        previous = sys.modules.pop("cv2", None)
        missing = ModuleNotFoundError("No module named 'cv2'", name="cv2")
        try:
            with mock.patch.object(importlib, "import_module", side_effect=missing):
                stub = ensure_opencv_module()
            self.assertIs(stub, sys.modules["cv2"])
            with self.assertRaisesRegex(RuntimeError, "未包含 OpenCV"):
                stub.resize
        finally:
            sys.modules.pop("cv2", None)
            if previous is not None:
                sys.modules["cv2"] = previous
