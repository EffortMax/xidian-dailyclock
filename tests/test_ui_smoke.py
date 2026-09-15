import os
import unittest
from unittest.mock import patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QMessageBox, QTabWidget
    from app.main import MainWindow, TaskThread
    from app.models import CourseClass
    from app.services.auth_service import AuthService
    from app.services.credential_store import SavedCredentials
except ModuleNotFoundError:
    QApplication = None
    QMessageBox = None
    QTabWidget = None
    MainWindow = None
    TaskThread = None
    CourseClass = None
    AuthService = None
    SavedCredentials = None


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

    def test_course_page_can_queue_multiple_targets(self):
        window = MainWindow()
        page = window.course_page
        page.kcdm.setText("X1ONE")
        page.add_target()
        page.kcdm.setText("X1TWO")
        page.campus_filter.setText("北校区")
        page.add_target()
        self.assertEqual(page.target_table.rowCount(), 2)
        self.assertEqual([target.kcdm for target in page.queued_targets()], ["X1ONE", "X1TWO"])
        window.close()

    def test_login_page_loads_dpapi_saved_credentials(self):
        saved = SavedCredentials("24000000000", "encrypted-at-rest")
        with patch.object(AuthService, "load_saved_credentials", return_value=saved):
            window = MainWindow()
        self.assertEqual(window.login_page.user_edit.text(), "24000000000")
        self.assertEqual(window.login_page.password_edit.text(), "encrypted-at-rest")
        self.assertTrue(window.login_page.remember_credentials.isChecked())
        window.close()

    def test_drop_is_not_submitted_when_second_confirmation_is_rejected(self):
        window = MainWindow()
        page = window.course_page
        page.table_mode = "chosen"
        page.populate([CourseClass.from_record({
            "KCDM": "X1TEST", "KCMC": "测试课程", "BJDM": "BJ001", "BJMC": "01班"
        })])
        page.table.selectRow(0)
        with patch("app.main.QMessageBox.question", side_effect=[QMessageBox.Yes, QMessageBox.No]) as ask, \
             patch.object(page.service, "drop_course") as drop:
            page.drop_selected_course()
        self.assertEqual(ask.call_count, 2)
        drop.assert_not_called()
        window.close()

    def test_drop_task_is_created_only_after_two_confirmations(self):
        window = MainWindow()
        page = window.course_page
        page.table_mode = "chosen"
        page.populate([CourseClass.from_record({
            "KCDM": "X1TEST", "KCMC": "测试课程", "BJDM": "BJ001", "BJMC": "01班"
        })])
        page.table.selectRow(0)
        with patch("app.main.QMessageBox.question", return_value=QMessageBox.Yes) as ask, \
             patch.object(TaskThread, "start") as start, \
             patch.object(page.service, "drop_course", return_value={"BJDM": "BJ001"}) as drop:
            page.drop_selected_course()
            page.thread.task(lambda _message: None, page.thread.stop_event)
        self.assertEqual(ask.call_count, 2)
        start.assert_called_once()
        drop.assert_called_once_with("BJ001")
        window.close()


if __name__ == "__main__":
    unittest.main()
