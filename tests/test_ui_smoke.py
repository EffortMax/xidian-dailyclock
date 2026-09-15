import os
import re
import tempfile
import unittest
from pathlib import Path
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

    def test_pages_use_consistent_spacing_and_grouped_course_actions(self):
        window = MainWindow()
        page = window.course_page

        for widget in (window.centralWidget(), window.login_page, page, window.timetable_page):
            margins = widget.layout().contentsMargins()
            self.assertEqual(
                (margins.left(), margins.top(), margins.right(), margins.bottom()),
                (12, 10, 12, 10),
            )
            self.assertEqual(widget.layout().spacing(), 8)

        form = page.layout().itemAt(0).layout()
        self.assertEqual(form.horizontalSpacing(), 12)
        self.assertEqual(form.verticalSpacing(), 6)
        self.assertEqual(page.interval.minimumWidth(), 120)
        self.assertEqual(page.interval.maximumWidth(), 160)
        self.assertEqual(page.empty_policy.minimumWidth(), 180)
        self.assertEqual(page.empty_policy.maximumWidth(), 240)

        target_toolbar = page.layout().itemAt(2).layout()
        target_texts = [
            item.widget().text()
            for index in range(target_toolbar.count())
            if (item := target_toolbar.itemAt(index)).widget() is not None
        ]
        self.assertEqual(target_texts, [
            "自动抢课目标队列（每轮只请求一次课程列表）",
            "添加到目标队列",
            "移除选中目标",
            "清空目标",
        ])

        action_toolbar = page.layout().itemAt(4).layout()
        action_texts = [
            item.widget().text()
            for index in range(action_toolbar.count())
            if (item := action_toolbar.itemAt(index)).widget() is not None
        ]
        self.assertEqual(action_texts, [
            "课程操作",
            "查询课程",
            "使用选中教学班",
            "查看已选课程",
            "退掉选中课程",
            "自动任务",
            "开始自动抢课",
            "停止",
        ])
        window.close()

    def test_log_panel_is_resizable_expandable_and_remembers_preferences(self):
        class MemorySettings:
            def __init__(self):
                self.values = {}

            def value(self, key, default=None):
                return self.values.get(key, default)

            def setValue(self, key, value):
                self.values[key] = value

        settings = MemorySettings()
        with patch("app.main.QSettings", return_value=settings):
            window = MainWindow()
        window.show()
        self.app.processEvents()

        normal_sizes = window.log_splitter.sizes()
        self.assertEqual(window.log_splitter.count(), 2)
        self.assertGreaterEqual(window.log_panel.height(), 170)
        self.assertEqual(window.log_panel.minimumHeight(), 120)
        self.assertTrue(window.log_auto_scroll.isChecked())

        window.log_auto_scroll.setChecked(False)
        self.assertFalse(settings.values["ui/log_auto_scroll"])
        window.remember_log_splitter_sizes(0, 0)
        self.assertEqual(settings.values["ui/log_splitter_sizes"], normal_sizes)

        window.toggle_log_expansion()
        self.app.processEvents()
        expanded_sizes = window.log_splitter.sizes()
        self.assertTrue(window.log_expanded)
        self.assertEqual(window.expand_log_button.text(), "恢复布局")
        self.assertGreater(expanded_sizes[1], expanded_sizes[0])

        window.toggle_log_expansion()
        self.app.processEvents()
        restored_sizes = window.log_splitter.sizes()
        self.assertFalse(window.log_expanded)
        self.assertEqual(window.expand_log_button.text(), "展开日志")
        self.assertEqual(restored_sizes, normal_sizes)
        window.close()

        with patch("app.main.QSettings", return_value=settings):
            restored_window = MainWindow()
        self.assertFalse(restored_window.log_auto_scroll.isChecked())
        self.assertEqual(restored_window._saved_log_splitter_sizes(), normal_sizes)
        restored_window.close()

    def test_log_auto_scroll_can_pause_and_resume_following(self):
        window = MainWindow()
        original_setting = window.log_auto_scroll.isChecked()
        window.show()
        self.app.processEvents()
        window.log_line("\n".join("测试日志 {0}".format(index) for index in range(100)))
        self.app.processEvents()
        scroll_bar = window.log_view.verticalScrollBar()

        window.log_auto_scroll.setChecked(False)
        scroll_bar.setValue(0)
        window.log_line("暂停跟随后追加")
        self.app.processEvents()
        self.assertEqual(scroll_bar.value(), 0)

        window.log_auto_scroll.setChecked(True)
        window.log_line("恢复跟随后追加")
        self.app.processEvents()
        self.assertEqual(scroll_bar.value(), scroll_bar.maximum())
        window.log_auto_scroll.setChecked(original_setting)
        window.close()

    def test_log_toolbar_timestamps_copies_saves_and_clears_plain_text(self):
        window = MainWindow()
        window.log_line("第一行")
        window.log_line("第二行\n第三行")

        lines = window.log_view.toPlainText().splitlines()
        self.assertEqual(len(lines), 3)
        for line, message in zip(lines, ("第一行", "第二行", "第三行")):
            self.assertRegex(line, r"^\[\d{2}:\d{2}:\d{2}\] " + re.escape(message) + r"$")
        self.assertEqual(window.log_count_label.text(), "运行日志（3 条）")

        window.copy_all_logs()
        self.assertEqual(QApplication.clipboard().text(), window.log_view.toPlainText())

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "saved.log"
            with patch("app.main.QFileDialog.getSaveFileName", return_value=(str(output), "日志文件 (*.log)")):
                window.save_logs()
            self.assertEqual(output.read_text(encoding="utf-8"), window.log_view.toPlainText())

        with patch("app.main.QMessageBox.question", return_value=QMessageBox.Yes):
            window.clear_logs()
        self.assertEqual(window.log_view.toPlainText(), "")
        self.assertEqual(window.log_count_label.text(), "运行日志（0 条）")
        window.close()

    def test_auto_selection_routes_service_logs_through_task_signal(self):
        window = MainWindow()
        page = window.course_page
        page.kcdm.setText("X2FL2130")
        page.add_target()

        def fake_select(_targets, _stop_event):
            page.service.log("轮询第 1 轮开始：测试日志")
            return []

        original_log = page.service.log
        with patch("app.main.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch.object(TaskThread, "start") as start, \
             patch.object(page.service, "auto_select_many", side_effect=fake_select):
            page.start_selection()
            captured = []
            page.thread.task(captured.append, page.thread.stop_event)

        start.assert_called_once()
        self.assertEqual(captured, ["轮询第 1 轮开始：测试日志"])
        self.assertEqual(page.service.log, original_log)
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
