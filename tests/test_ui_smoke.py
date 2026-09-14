import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QTabWidget
    from app.main import MainWindow
except ModuleNotFoundError:
    QApplication = None
    QTabWidget = None
    MainWindow = None


@unittest.skipUnless(QApplication is not None, "PySide6 is not installed in this interpreter")
class UiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_contains_three_workflow_tabs(self):
        window = MainWindow()
        tabs = window.findChild(QTabWidget)
        self.assertIsNotNone(tabs)
        self.assertEqual(tabs.count(), 3)
        window.close()


if __name__ == "__main__":
    unittest.main()
