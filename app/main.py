from __future__ import annotations

import contextlib
import io
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QSettings, QThread, Qt, Signal
from PySide6.QtGui import QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.models import CourseClass, SelectionTarget
from app.services.auth_service import AuthService
from app.services.course_service import CourseService
from app.services.timetable_service import TimetableService


PAGE_MARGINS = (12, 10, 12, 10)
PAGE_SPACING = 8
CONTROL_SPACING = 6
FORM_HORIZONTAL_SPACING = 12
FORM_VERTICAL_SPACING = 6


def configure_form_layout(form: QFormLayout) -> None:
    form.setContentsMargins(0, 0, 0, 0)
    form.setHorizontalSpacing(FORM_HORIZONTAL_SPACING)
    form.setVerticalSpacing(FORM_VERTICAL_SPACING)
    form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)


def configure_page_layout(layout: QVBoxLayout) -> None:
    layout.setContentsMargins(*PAGE_MARGINS)
    layout.setSpacing(PAGE_SPACING)


def configure_action_button(button: QPushButton, minimum_width: int = 88) -> None:
    button.setMinimumWidth(minimum_width)
    button.setMinimumHeight(30)
    button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)


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


class CaptchaBridge(QObject):
    """把工作线程的验证码请求同步转交给 Qt 主线程。"""

    requested = Signal(object, int, object, object)

    def request_code(self, image: bytes, attempt: int) -> str:
        result: dict[str, str] = {}
        completed = threading.Event()
        self.requested.emit(image, attempt, result, completed)
        completed.wait()
        return result.get("code", "")


class LoginPage(QWidget):
    logged_in = Signal()

    def __init__(self, auth: AuthService, log: Callable[[str], None]) -> None:
        super().__init__()
        self.auth = auth
        self.log = log
        self.thread: TaskThread | None = None
        self.captcha_bridge = CaptchaBridge()
        self.captcha_bridge.requested.connect(self.show_captcha_dialog)
        self.auth.set_manual_captcha_provider(self.captcha_bridge.request_code)
        self.user_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.unattended = QCheckBox("启用无人值守（使用 ddddocr 自动识别验证码）")
        self.unattended.setChecked(True)
        self.force_login = QCheckBox("忽略本地登录态，强制重新登录")
        self.remember_credentials = QCheckBox("保存账户和密码（Windows DPAPI 加密）")
        self.remember_credentials.setToolTip(
            "仅当前 Windows 用户可解密；取消勾选并成功登录后会删除已保存凭据。"
        )
        self.login_button = QPushButton("登录 / 恢复会话")
        self.status = QLabel("未登录")
        self.login_button.clicked.connect(self.start_login)

        saved = self.auth.load_saved_credentials()
        if saved is not None:
            self.user_edit.setText(saved.user_id)
            self.password_edit.setText(saved.password)
            self.remember_credentials.setChecked(True)
            self.status.setText("已加载本机加密保存的账户")

        form = QFormLayout()
        configure_form_layout(form)
        form.addRow("学号", self.user_edit)
        form.addRow("密码", self.password_edit)
        configure_action_button(self.login_button, 144)
        login_actions = QHBoxLayout()
        login_actions.setSpacing(CONTROL_SPACING)
        login_actions.addWidget(self.login_button)
        login_actions.addStretch(1)
        layout = QVBoxLayout(self)
        configure_page_layout(layout)
        layout.addLayout(form)
        layout.addWidget(self.unattended)
        layout.addWidget(self.force_login)
        layout.addWidget(self.remember_credentials)
        layout.addLayout(login_actions)
        layout.addWidget(self.status)
        layout.addStretch()

    def show_captcha_dialog(
        self,
        image: bytes,
        attempt: int,
        result: dict[str, str],
        completed: threading.Event,
    ) -> None:
        try:
            dialog = QDialog(self)
            dialog.setWindowTitle("输入验证码")
            dialog.setModal(True)
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel("请输入图片中的 4 位验证码（第 {0} 次尝试）".format(attempt)))
            image_label = QLabel()
            image_label.setAlignment(Qt.AlignCenter)
            pixmap = QPixmap()
            pixmap.loadFromData(image)
            image_label.setPixmap(pixmap.scaledToWidth(240, Qt.SmoothTransformation))
            layout.addWidget(image_label)
            code_edit = QLineEdit()
            code_edit.setMaxLength(8)
            code_edit.setPlaceholderText("验证码")
            layout.addWidget(code_edit)
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            code_edit.returnPressed.connect(dialog.accept)
            code_edit.setFocus()
            if dialog.exec() == QDialog.Accepted:
                result["code"] = code_edit.text().strip()
        finally:
            completed.set()

    def start_login(self) -> None:
        user_id = self.user_edit.text().strip()
        password = self.password_edit.text()
        unattended = self.unattended.isChecked()
        force_login = self.force_login.isChecked()
        remember_credentials = self.remember_credentials.isChecked()
        self.auth.set_unattended(unattended)
        self.login_button.setEnabled(False)
        self.status.setText("登录中…")

        def task(log: Callable[[str], None], _stop: threading.Event):
            self.auth.log = log
            return self.auth.login(
                user_id,
                password,
                force=force_login,
                remember_credentials=remember_credentials,
            )

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
    POLICY_LABELS = {
        "warn": "警告并继续",
        "ignore_filter": "无结果时放宽筛选",
        "abort": "无结果时停止",
    }

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
        self.interval.setMinimumWidth(120)
        self.interval.setMaximumWidth(160)
        self.empty_policy = QComboBox()
        for value, label in self.POLICY_LABELS.items():
            self.empty_policy.addItem(label, value)
        self.empty_policy.setMinimumWidth(180)
        self.empty_policy.setMaximumWidth(240)
        self.unattended = QCheckBox("无人值守验证码")
        self.unattended.setChecked(True)
        self.unattended.stateChanged.connect(lambda state: self.auth.set_unattended(bool(state)))
        self.query_button = QPushButton("查询课程")
        self.use_selected_button = QPushButton("使用选中教学班")
        self.chosen_button = QPushButton("查看已选课程")
        self.drop_button = QPushButton("退掉选中课程")
        self.drop_button.setEnabled(False)
        self.start_button = QPushButton("开始自动抢课")
        self.stop_button = QPushButton("停止")
        self.stop_button.setEnabled(False)
        self.add_target_button = QPushButton("添加到目标队列")
        self.remove_target_button = QPushButton("移除选中目标")
        self.clear_targets_button = QPushButton("清空目标")
        for button, minimum_width in (
            (self.query_button, 88),
            (self.use_selected_button, 128),
            (self.chosen_button, 112),
            (self.drop_button, 112),
            (self.start_button, 120),
            (self.stop_button, 80),
            (self.add_target_button, 128),
            (self.remove_target_button, 112),
            (self.clear_targets_button, 88),
        ):
            configure_action_button(button, minimum_width)
        self.target_table = QTableWidget(0, 5)
        self.target_table.setHorizontalHeaderLabels(
            ["课程代码", "教学班代码", "教学班筛选", "校区筛选", "无结果策略"]
        )
        self.target_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.target_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.target_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["课程代码", "课程名称", "教学班", "教学班代码", "校区", "来源", "容量", "已选", "时间地点"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.add_target_button.clicked.connect(self.add_target)
        self.remove_target_button.clicked.connect(self.remove_selected_target)
        self.clear_targets_button.clicked.connect(lambda: self.target_table.setRowCount(0))
        self.query_button.clicked.connect(self.query_courses)
        self.use_selected_button.clicked.connect(self.use_selected_course)
        self.chosen_button.clicked.connect(self.query_chosen_courses)
        self.drop_button.clicked.connect(self.drop_selected_course)
        self.start_button.clicked.connect(self.start_selection)
        self.stop_button.clicked.connect(self.stop_task)

        form = QFormLayout()
        configure_form_layout(form)
        form.addRow("课程代码 KCDM", self.kcdm)
        form.addRow("教学班代码 BJDM（可选）", self.bjdm)
        form.addRow("教学班筛选", self.bj_filter)
        form.addRow("校区筛选", self.campus_filter)
        form.addRow("查询关键字", self.keyword)
        form.addRow("轮询间隔（秒）", self.interval)
        form.addRow("未找到教学班时", self.empty_policy)

        target_toolbar = QHBoxLayout()
        target_toolbar.setSpacing(CONTROL_SPACING)
        target_toolbar.addWidget(QLabel("自动抢课目标队列（每轮只请求一次课程列表）"))
        target_toolbar.addStretch(1)
        target_toolbar.addWidget(self.add_target_button)
        target_toolbar.addWidget(self.remove_target_button)
        target_toolbar.addWidget(self.clear_targets_button)

        action_toolbar = QHBoxLayout()
        action_toolbar.setSpacing(CONTROL_SPACING)
        action_toolbar.addWidget(QLabel("课程操作"))
        action_toolbar.addWidget(self.query_button)
        action_toolbar.addWidget(self.use_selected_button)
        action_toolbar.addWidget(self.chosen_button)
        action_toolbar.addWidget(self.drop_button)
        action_toolbar.addStretch(1)
        action_toolbar.addWidget(QLabel("自动任务"))
        action_toolbar.addWidget(self.start_button)
        action_toolbar.addWidget(self.stop_button)

        layout = QVBoxLayout(self)
        configure_page_layout(layout)
        layout.addLayout(form)
        layout.addWidget(self.unattended)
        layout.addLayout(target_toolbar)
        layout.addWidget(self.target_table)
        layout.addLayout(action_toolbar)
        layout.addWidget(QLabel("课程查询结果"))
        layout.addWidget(self.table)
        self.table_mode = "available"
        self.current_courses: list[CourseClass] = []

    def current_target(self) -> SelectionTarget:
        target = SelectionTarget(
            kcdm=self.kcdm.text().strip(),
            bjdm=self.bjdm.text().strip(),
            bjmc_keyword=self.bj_filter.text().strip(),
            xqmc_keyword=self.campus_filter.text().strip(),
            poll_interval=float(self.interval.value()),
            on_empty=str(self.empty_policy.currentData()),
        )
        target.validate()
        return target

    def add_target(self) -> None:
        try:
            target = self.current_target()
        except ValueError as exc:
            QMessageBox.warning(self, "目标无效", str(exc))
            return
        signature = (
            target.kcdm.casefold(),
            target.bjdm.casefold(),
            target.bjmc_keyword.casefold(),
            target.xqmc_keyword.casefold(),
        )
        for row in range(self.target_table.rowCount()):
            if self.target_table.item(row, 0).text().strip().casefold() == target.kcdm.casefold():
                QMessageBox.information(
                    self,
                    "课程代码已存在",
                    "同一课程代码只能加入一次；请移除原目标，或直接调整教学班/校区筛选后重新添加。",
                )
                return
            existing = tuple(
                self.target_table.item(row, column).text().strip().casefold()
                for column in range(4)
            )
            if existing == signature:
                QMessageBox.information(self, "目标已存在", "相同筛选条件的目标已经在队列中。")
                return
        row = self.target_table.rowCount()
        self.target_table.insertRow(row)
        values = [
            target.kcdm,
            target.bjdm,
            target.bjmc_keyword,
            target.xqmc_keyword,
            self.POLICY_LABELS[target.on_empty],
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 4:
                item.setData(Qt.UserRole, target.on_empty)
            self.target_table.setItem(row, column, item)
        self.log("已添加抢课目标：" + target.kcdm)

    def remove_selected_target(self) -> None:
        rows = sorted({index.row() for index in self.target_table.selectedIndexes()}, reverse=True)
        if not rows:
            QMessageBox.information(self, "未选择目标", "请先选择要移除的目标行。")
            return
        for row in rows:
            self.target_table.removeRow(row)

    def queued_targets(self) -> list[SelectionTarget]:
        targets = []
        for row in range(self.target_table.rowCount()):
            policy_item = self.target_table.item(row, 4)
            targets.append(SelectionTarget(
                kcdm=self.target_table.item(row, 0).text(),
                bjdm=self.target_table.item(row, 1).text(),
                bjmc_keyword=self.target_table.item(row, 2).text(),
                xqmc_keyword=self.target_table.item(row, 3).text(),
                poll_interval=float(self.interval.value()),
                on_empty=str(policy_item.data(Qt.UserRole) or "warn"),
            ))
        return targets

    def query_courses(self) -> None:
        self.table_mode = "available"
        self.set_busy(True)
        keyword = self.keyword.text()
        self.thread = TaskThread(lambda _log, _stop: self.service.list_courses(keyword))
        self.thread.log_line.connect(self.log)
        self.thread.succeeded.connect(self.populate)
        self.thread.failed.connect(self.task_failed)
        self.thread.start()

    def populate(self, courses: object) -> None:
        self.current_courses = list(courses)
        self.table.setRowCount(0)
        for course in self.current_courses:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                course.kcdm, course.kcmc, course.bjmc, course.bjdm, course.campus,
                course.source, course.capacity, course.selected_count, course.schedule,
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.set_busy(False)
        table_name = "已选课程" if self.table_mode == "chosen" else "教学班"
        self.log("查询完成，共 {0} 个{1}".format(len(self.current_courses), table_name))

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
        self.table_mode = "chosen"
        self.set_busy(True)
        self.thread = TaskThread(lambda _log, _stop: self.service.chosen_courses())
        self.thread.log_line.connect(self.log)
        self.thread.succeeded.connect(
            lambda courses: self.populate([CourseClass.from_record(course) for course in courses])
        )
        self.thread.failed.connect(self.task_failed)
        self.thread.start()

    def drop_selected_course(self) -> None:
        if self.table_mode != "chosen":
            QMessageBox.information(self, "退课", "请先点击“查看已选课程”。")
            return
        row = self.table.currentRow()
        if row < 0 or row >= len(self.current_courses):
            QMessageBox.information(self, "退课", "请先选择一门已选课程。")
            return
        course = self.current_courses[row]
        detail = "{0}（{1}）\n教学班：{2}".format(
            course.kcmc or "未命名课程",
            course.kcdm or "无课程代码",
            course.bjdm,
        )
        first = QMessageBox.question(
            self,
            "第一次确认退课",
            "确定要退掉下面这门课程吗？\n\n{0}".format(detail),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if first != QMessageBox.Yes:
            return
        second = QMessageBox.question(
            self,
            "第二次确认退课",
            "这是最后一次确认。提交后课程可能无法重新选回。\n\n"
            "再次确认退掉：\n{0}".format(detail),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if second != QMessageBox.Yes:
            self.log("第二次确认未通过，未提交退课请求")
            return

        bjdm = course.bjdm
        self.set_busy(True)
        self.log("正在提交退课并复核教学班 {0}……".format(bjdm))
        self.thread = TaskThread(lambda _log, _stop: self.service.drop_course(bjdm))
        self.thread.log_line.connect(self.log)
        self.thread.succeeded.connect(self.drop_succeeded)
        self.thread.failed.connect(self.task_failed)
        self.thread.start()

    def drop_succeeded(self, dropped: object) -> None:
        record = dropped if isinstance(dropped, dict) else {}
        bjdm = str(record.get("BJDM") or "").strip()
        name = str(record.get("KCMC") or bjdm or "该课程")
        self.current_courses = [course for course in self.current_courses if course.bjdm != bjdm]
        self.populate(self.current_courses)
        self.log("退课成功并完成复核：{0}".format(name))
        QMessageBox.information(self, "退课成功", "已退掉并复核：{0}".format(name))

    def start_selection(self) -> None:
        if self.target_table.rowCount() == 0:
            self.add_target()
        targets = self.queued_targets()
        if not targets:
            return
        answer = QMessageBox.question(
            self,
            "确认自动抢课",
            "将同时监控 {0} 个目标。每轮会请求一次学校课程列表，并在有空位时提交选课请求。确认继续吗？".format(
                len(targets)
            ),
        )
        if answer != QMessageBox.Yes:
            return
        self.set_busy(True)
        self.stop_button.setEnabled(True)

        def task(log: Callable[[str], None], stop: threading.Event):
            # 服务日志必须通过 TaskThread 信号回到 Qt 主线程，避免工作线程直接操作 QTextEdit。
            original_log = self.service.log
            self.service.log = log
            try:
                return self.service.auto_select_many(targets, stop)
            finally:
                self.service.log = original_log

        self.thread = TaskThread(task)
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
        courses = course if isinstance(course, list) else [course]
        names = [
            entry.get("KCMC") or entry.get("KCDM") or "目标课程"
            for entry in courses
            if isinstance(entry, dict)
        ]
        self.log("自动抢课全部完成（{0} 个目标）：{1}".format(len(courses), "、".join(names)))

    def task_failed(self, message: str) -> None:
        self.set_busy(False)
        self.stop_button.setEnabled(False)
        if message != "自动抢课已停止":
            self.log("任务失败：" + message)

    def set_busy(self, busy: bool) -> None:
        self.query_button.setEnabled(not busy)
        self.use_selected_button.setEnabled(not busy and self.table_mode == "available")
        self.chosen_button.setEnabled(not busy)
        self.drop_button.setEnabled(not busy and self.table_mode == "chosen")
        self.start_button.setEnabled(not busy)
        self.add_target_button.setEnabled(not busy)
        self.remove_target_button.setEnabled(not busy)
        self.clear_targets_button.setEnabled(not busy)
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
        configure_action_button(browse, 96)
        configure_action_button(export, 96)
        browse.clicked.connect(self.choose_path)
        export.clicked.connect(self.export)
        form = QFormLayout()
        configure_form_layout(form)
        form.addRow("学期（可选）", self.semester)
        form.addRow("导出路径", self.path)
        actions = QHBoxLayout()
        actions.setSpacing(CONTROL_SPACING)
        actions.addWidget(browse)
        actions.addWidget(export)
        actions.addStretch(1)
        layout = QVBoxLayout(self)
        configure_page_layout(layout)
        layout.addLayout(form)
        layout.addWidget(self.include_unscheduled)
        layout.addLayout(actions)
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
    DEFAULT_LOG_SPLITTER_SIZES = [500, 180]
    NORMAL_TABS_MINIMUM_HEIGHT = 360
    EXPANDED_TABS_MINIMUM_HEIGHT = 180

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("西电研究生选课助手 {0}".format(__version__))
        self.resize(1180, 720)
        self.settings = QSettings("EffortMax", "DailyClockXDU")
        self.log_line_count = 0
        self.log_expanded = False
        self.log_restore_sizes: list[int] | None = None
        self.auth = AuthService()
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setAcceptRichText(False)
        self.log_count_label = QLabel("运行日志（0 条）")
        self.log_auto_scroll = QCheckBox("自动滚动")
        self.log_auto_scroll.setChecked(self._setting_as_bool(
            self.settings.value("ui/log_auto_scroll", True)
        ))
        self.copy_log_button = QPushButton("复制全部")
        self.save_log_button = QPushButton("保存日志")
        self.clear_log_button = QPushButton("清空")
        self.expand_log_button = QPushButton("展开日志")
        for button, minimum_width in (
            (self.copy_log_button, 88),
            (self.save_log_button, 88),
            (self.clear_log_button, 72),
            (self.expand_log_button, 88),
        ):
            configure_action_button(button, minimum_width)
        self.log_auto_scroll.toggled.connect(self.remember_log_auto_scroll)
        self.copy_log_button.clicked.connect(self.copy_all_logs)
        self.save_log_button.clicked.connect(self.save_logs)
        self.clear_log_button.clicked.connect(self.clear_logs)
        self.expand_log_button.clicked.connect(self.toggle_log_expansion)

        self.login_page = LoginPage(self.auth, self.log_line)
        self.course_page = CoursePage(self.auth, self.log_line)
        self.timetable_page = TimetablePage(self.auth, self.log_line)
        self.login_page.unattended.stateChanged.connect(self.course_page.unattended.setChecked)
        self.course_page.unattended.stateChanged.connect(self.login_page.unattended.setChecked)
        self.tabs = QTabWidget()
        self.tabs.setMinimumHeight(self.NORMAL_TABS_MINIMUM_HEIGHT)
        self.tabs.addTab(self.login_page, "登录")
        self.tabs.addTab(self.course_page, "选课 / 自动抢课")
        self.tabs.addTab(self.timetable_page, "课表导出")

        log_header = QHBoxLayout()
        log_header.setSpacing(CONTROL_SPACING)
        log_header.addWidget(self.log_count_label)
        log_header.addStretch(1)
        log_header.addWidget(self.log_auto_scroll)
        log_header.addWidget(self.copy_log_button)
        log_header.addWidget(self.save_log_button)
        log_header.addWidget(self.clear_log_button)
        log_header.addWidget(self.expand_log_button)

        self.log_panel = QWidget()
        self.log_panel.setMinimumHeight(120)
        log_layout = QVBoxLayout(self.log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(CONTROL_SPACING)
        log_layout.addLayout(log_header)
        log_layout.addWidget(self.log_view)

        self.log_splitter = QSplitter(Qt.Vertical)
        self.log_splitter.setChildrenCollapsible(False)
        self.log_splitter.setHandleWidth(6)
        self.log_splitter.addWidget(self.tabs)
        self.log_splitter.addWidget(self.log_panel)
        self.log_splitter.setStretchFactor(0, 3)
        self.log_splitter.setStretchFactor(1, 1)
        self.log_splitter.setSizes(self._saved_log_splitter_sizes())
        self.log_splitter.splitterMoved.connect(self.remember_log_splitter_sizes)

        root = QWidget()
        layout = QVBoxLayout(root)
        configure_page_layout(layout)
        layout.addWidget(self.log_splitter)
        self.setCentralWidget(root)

    @staticmethod
    def _setting_as_bool(value: object) -> bool:
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    def _saved_log_splitter_sizes(self) -> list[int]:
        value = self.settings.value("ui/log_splitter_sizes")
        if isinstance(value, (list, tuple)) and len(value) == 2:
            try:
                sizes = [int(value[0]), int(value[1])]
            except (TypeError, ValueError):
                pass
            else:
                if all(size > 0 for size in sizes):
                    return sizes
        return list(self.DEFAULT_LOG_SPLITTER_SIZES)

    def remember_log_auto_scroll(self, checked: bool) -> None:
        self.settings.setValue("ui/log_auto_scroll", checked)

    def remember_log_splitter_sizes(self, _position: int, _index: int) -> None:
        if not self.log_expanded:
            self.settings.setValue("ui/log_splitter_sizes", self.log_splitter.sizes())

    def copy_all_logs(self) -> None:
        QApplication.clipboard().setText(self.log_view.toPlainText())

    def save_logs(self) -> None:
        default_name = "DailyClockXDU-{0}.log".format(datetime.now().strftime("%Y%m%d-%H%M%S"))
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存运行日志",
            str(Path.home() / default_name),
            "日志文件 (*.log);;文本文件 (*.txt)",
        )
        if not path:
            return
        try:
            Path(path).write_text(self.log_view.toPlainText(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "保存日志失败", str(exc))

    def clear_logs(self) -> None:
        if not self.log_view.toPlainText():
            return
        answer = QMessageBox.question(
            self,
            "清空运行日志",
            "确定清空当前显示的全部运行日志吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.log_view.clear()
        self.log_line_count = 0
        self.log_count_label.setText("运行日志（0 条）")

    def toggle_log_expansion(self) -> None:
        sizes = self.log_splitter.sizes()
        total = max(sum(sizes), self.log_splitter.height(), 1)
        if not self.log_expanded:
            self.log_restore_sizes = sizes if all(size > 0 for size in sizes) else None
            self.tabs.setMinimumHeight(self.EXPANDED_TABS_MINIMUM_HEIGHT)
            self.log_expanded = True
            self.log_splitter.setSizes([int(total * 0.35), int(total * 0.65)])
            self.expand_log_button.setText("恢复布局")
            return

        self.tabs.setMinimumHeight(self.NORMAL_TABS_MINIMUM_HEIGHT)
        self.log_splitter.setSizes(
            self.log_restore_sizes or self._saved_log_splitter_sizes()
        )
        self.log_restore_sizes = None
        self.log_expanded = False
        self.expand_log_button.setText("展开日志")

    def log_line(self, message: str) -> None:
        scroll_bar = self.log_view.verticalScrollBar()
        previous_scroll = scroll_bar.value()
        lines = str(message).splitlines() or [""]
        timestamp = datetime.now().strftime("%H:%M:%S")
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        for line in lines:
            if not self.log_view.document().isEmpty():
                cursor.insertBlock()
            cursor.insertText("[{0}] {1}".format(timestamp, line))
            self.log_line_count += 1
        self.log_view.setTextCursor(cursor)
        self.log_count_label.setText("运行日志（{0} 条）".format(self.log_line_count))
        if self.log_auto_scroll.isChecked():
            scroll_bar.setValue(scroll_bar.maximum())
        else:
            scroll_bar.setValue(min(previous_scroll, scroll_bar.maximum()))


def main() -> int:
    app = QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
