from __future__ import annotations

import contextlib
import io
import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.models import CourseClass, SelectionTarget
from app.services.auth_service import AuthService
from app.services.course_service import CourseService
from app.services.timetable_service import TimetableService


class _Stream(io.TextIOBase):
    def __init__(self, callback: Callable[[str], None]) -> None:
        self.callback = callback

    def write(self, text: str) -> int:
        if text:
            for line in text.splitlines():
                if line.strip():
                    self.callback(line)
        return len(text)

    def flush(self) -> None:
        return None


class TaskThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    log_line = Signal(str)

    def __init__(self, task: Callable[[Callable[[str], None], threading.Event], object]) -> None:
        super().__init__()
        self.task = task
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        stream = _Stream(self.log_line.emit)
        try:
            with contextlib.redirect_stdout(stream):
                result = self.task(self.log_line.emit, self.stop_event)
            self.succeeded.emit(result)
        except Exception as exc:  # noqa: BLE001 - UI 线程必须转成可读错误
            self.failed.emit(str(exc))


class LoginPage(QWidget):
    logged_in = Signal()

    def __init__(self, auth: AuthService, log: Callable[[str], None]) -> None:
        super().__init__()
        self.auth = auth
        self.log = log
        self.thread: TaskThread | None = None
        self.user_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.unattended = QCheckBox("启用无人值守（使用 ddddocr 自动识别验证码）")
        self.force_login = QCheckBox("忽略本地登录态，强制重新登录")
        self.login_button = QPushButton("登录 / 恢复会话")
        self.status = QLabel("未登录")
        self.login_button.clicked.connect(self.start_login)

        form = QFormLayout()
        form.addRow("学号", self.user_edit)
        form.addRow("密码", self.password_edit)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.unattended)
        layout.addWidget(self.force_login)
        layout.addWidget(self.login_button)
        layout.addWidget(self.status)
        layout.addStretch()

    def start_login(self) -> None:
        user_id = self.user_edit.text().strip()
        password = self.password_edit.text()
        unattended = self.unattended.isChecked()
        force_login = self.force_login.isChecked()
        self.auth.set_unattended(unattended)
        self.login_button.setEnabled(False)
        self.status.setText("登录中…")

        def task(log: Callable[[str], None], _stop: threading.Event):
            self.auth.log = log
            return self.auth.login(user_id, password, force=force_login)

        self.thread = TaskThread(task)
        self.thread.log_line.connect(self.log)
        self.thread.succeeded.connect(self.login_succeeded)
        self.thread.failed.connect(self.login_failed)
        self.thread.start()

    def login_succeeded(self, _result: object) -> None:
        self.status.setText("已登录")
        self.login_button.setEnabled(True)
        self.logged_in.emit()

    def login_failed(self, message: str) -> None:
        self.status.setText("登录失败")
        self.login_button.setEnabled(True)
        self.log("登录失败：" + message)


class CoursePage(QWidget):
    def __init__(self, auth: AuthService, log: Callable[[str], None]) -> None:
        super().__init__()
        self.auth = auth
        self.log = log
        self.service = CourseService(auth, log)
        self.thread: TaskThread | None = None
        self.kcdm = QLineEdit()
        self.bjdm = QLineEdit()
        self.bj_filter = QLineEdit()
        self.campus_filter = QLineEdit()
        self.keyword = QLineEdit()
        self.interval = QSpinBox()
        self.interval.setRange(1, 3600)
        self.interval.setValue(15)
        self.unattended = QCheckBox("无人值守验证码")
        self.unattended.stateChanged.connect(lambda state: self.auth.set_unattended(bool(state)))
        self.query_button = QPushButton("查询课程")
        self.use_selected_button = QPushButton("使用选中教学班")
        self.chosen_button = QPushButton("查看已选课程")
        self.start_button = QPushButton("开始自动抢课")
        self.stop_button = QPushButton("停止")
        self.stop_button.setEnabled(False)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["课程代码", "课程名称", "教学班", "教学班代码", "校区", "来源", "容量", "已选", "时间地点"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.query_button.clicked.connect(self.query_courses)
        self.use_selected_button.clicked.connect(self.use_selected_course)
        self.chosen_button.clicked.connect(self.query_chosen_courses)
        self.start_button.clicked.connect(self.start_selection)
        self.stop_button.clicked.connect(self.stop_task)

        form = QFormLayout()
        form.addRow("课程代码 KCDM", self.kcdm)
        form.addRow("教学班代码 BJDM（可选）", self.bjdm)
        form.addRow("教学班筛选", self.bj_filter)
        form.addRow("校区筛选", self.campus_filter)
        form.addRow("查询关键字", self.keyword)
        form.addRow("轮询间隔（秒）", self.interval)
        buttons = QHBoxLayout()
        buttons.addWidget(self.query_button)
        buttons.addWidget(self.use_selected_button)
        buttons.addWidget(self.chosen_button)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.unattended)
        layout.addLayout(buttons)
        layout.addWidget(self.table)

    def query_courses(self) -> None:
        self.set_busy(True)
        keyword = self.keyword.text()
        self.thread = TaskThread(lambda _log, _stop: self.service.list_courses(keyword))
        self.thread.log_line.connect(self.log)
        self.thread.succeeded.connect(self.populate)
        self.thread.failed.connect(self.task_failed)
        self.thread.start()

    def populate(self, courses: object) -> None:
        self.table.setRowCount(0)
        for course in courses:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                course.kcdm, course.kcmc, course.bjmc, course.bjdm, course.campus,
                course.source, course.capacity, course.selected_count, course.schedule,
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.set_busy(False)
        self.log("查询完成，共 {0} 个教学班".format(len(courses)))

    def use_selected_course(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "未选择课程", "请先在课程列表中选择一个教学班。")
            return
        self.kcdm.setText(self.table.item(row, 0).text())
        self.bj_filter.setText(self.table.item(row, 2).text())
        self.bjdm.setText(self.table.item(row, 3).text())
        self.campus_filter.setText(self.table.item(row, 4).text())
        self.log("已带入选中的教学班；自动抢课将锁定 BJDM。")

    def query_chosen_courses(self) -> None:
        self.set_busy(True)
        self.thread = TaskThread(lambda _log, _stop: self.service.chosen_courses())
        self.thread.log_line.connect(self.log)
        self.thread.succeeded.connect(
            lambda courses: self.populate([CourseClass.from_record(course) for course in courses])
        )
        self.thread.failed.connect(self.task_failed)
        self.thread.start()

    def start_selection(self) -> None:
        if not self.kcdm.text().strip():
            QMessageBox.warning(self, "缺少目标", "请输入课程代码 KCDM。")
            return
        answer = QMessageBox.question(
            self,
            "确认自动抢课",
            "自动抢课会持续向学校系统轮询并提交选课请求，确认继续吗？",
        )
        if answer != QMessageBox.Yes:
            return
        target = SelectionTarget(
            kcdm=self.kcdm.text(),
            bjdm=self.bjdm.text(),
            bjmc_keyword=self.bj_filter.text(),
            xqmc_keyword=self.campus_filter.text(),
            poll_interval=float(self.interval.value()),
        )
        self.set_busy(True)
        self.stop_button.setEnabled(True)
        self.thread = TaskThread(lambda _log, stop: self.service.auto_select(target, stop))
        self.thread.log_line.connect(self.log)
        self.thread.succeeded.connect(self.selection_succeeded)
        self.thread.failed.connect(self.task_failed)
        self.thread.start()

    def stop_task(self) -> None:
        if self.thread:
            self.thread.stop()
            self.log("已请求停止后台任务")

    def selection_succeeded(self, course: object) -> None:
        self.set_busy(False)
        self.stop_button.setEnabled(False)
        self.log("自动抢课完成：{0}".format(course.get("KCMC") or course.get("KCDM") or "目标课程"))

    def task_failed(self, message: str) -> None:
        self.set_busy(False)
        self.stop_button.setEnabled(False)
        if message != "自动抢课已停止":
            self.log("任务失败：" + message)

    def set_busy(self, busy: bool) -> None:
        self.query_button.setEnabled(not busy)
        self.use_selected_button.setEnabled(not busy)
        self.chosen_button.setEnabled(not busy)
        self.start_button.setEnabled(not busy)
        if not busy:
            self.stop_button.setEnabled(False)


class TimetablePage(QWidget):
    def __init__(self, auth: AuthService, log: Callable[[str], None]) -> None:
        super().__init__()
        self.service = TimetableService(auth, log)
        self.log = log
        self.thread: TaskThread | None = None
        self.semester = QLineEdit()
        self.include_unscheduled = QCheckBox("包含线上课/无固定排课课程")
        self.path = QLineEdit(str(Path.cwd() / "course.csv"))
        browse = QPushButton("选择文件")
        export = QPushButton("导出 CSV")
        browse.clicked.connect(self.choose_path)
        export.clicked.connect(self.export)
        form = QFormLayout()
        form.addRow("学期（可选）", self.semester)
        form.addRow("导出路径", self.path)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.include_unscheduled)
        layout.addWidget(browse)
        layout.addWidget(export)
        layout.addStretch()

    def choose_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出课表", self.path.text(), "CSV 文件 (*.csv)")
        if path:
            self.path.setText(path)

    def export(self) -> None:
        output = self.path.text().strip()
        if not output:
            QMessageBox.warning(self, "缺少路径", "请选择导出文件路径。")
            return
        self.thread = TaskThread(
            lambda _log, _stop: self.service.export_csv(
                output,
                self.semester.text(),
                self.include_unscheduled.isChecked(),
            )
        )
        self.thread.log_line.connect(self.log)
        self.thread.succeeded.connect(lambda result: self.log("已导出：" + result.output_path))
        self.thread.failed.connect(lambda message: self.log("导出失败：" + message))
        self.thread.start()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("西电研究生选课助手")
        self.resize(1180, 720)
        self.auth = AuthService()
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.login_page = LoginPage(self.auth, self.log_line)
        self.course_page = CoursePage(self.auth, self.log_line)
        self.timetable_page = TimetablePage(self.auth, self.log_line)
        self.login_page.unattended.stateChanged.connect(self.course_page.unattended.setChecked)
        self.course_page.unattended.stateChanged.connect(self.login_page.unattended.setChecked)
        tabs = QTabWidget()
        tabs.addTab(self.login_page, "登录")
        tabs.addTab(self.course_page, "选课 / 自动抢课")
        tabs.addTab(self.timetable_page, "课表导出")
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(tabs)
        layout.addWidget(QLabel("运行日志"))
        layout.addWidget(self.log_view)
        self.setCentralWidget(root)

    def log_line(self, message: str) -> None:
        self.log_view.append(message)


def main() -> int:
    app = QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
