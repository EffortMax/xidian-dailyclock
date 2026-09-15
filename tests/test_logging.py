import io
import os
import tempfile
import unittest
from pathlib import Path


os.environ.setdefault("XDU_LIBRARY_MODE", "1")

from courseChoose import TeeLogger


class TeeLoggerTests(unittest.TestCase):
    def test_rotates_existing_log_before_opening(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "courseChoose.log"
            path.write_text("x" * 64, encoding="utf-8")
            logger = TeeLogger(path, io.StringIO(), max_bytes=32, backup_count=2)
            logger.write("new run\n")
            logger.close()

            self.assertTrue(Path(str(path) + ".1").exists())
            self.assertIn("new run", path.read_text(encoding="utf-8"))

    def test_rotates_log_while_running(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "courseChoose.log"
            logger = TeeLogger(path, io.StringIO(), max_bytes=32, backup_count=2)
            logger.write("x" * 64)
            logger.write("after rotation\n")
            logger.close()

            self.assertTrue(Path(str(path) + ".1").exists())
            self.assertIn("after rotation", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
