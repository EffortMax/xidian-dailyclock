from __future__ import annotations

import csv
from pathlib import Path
from typing import Callable

import courseQuery as timetable

from app.models import ExportResult
from app.services.auth_service import AuthService


LogCallback = Callable[[str], None]


class TimetableService:
    """已选课程读取与 CSV 导出服务。"""

    FIELDS = ["课程名称", "星期", "开始节次", "结束节数", "老师", "地点", "周数", "备注"]

    def __init__(self, auth: AuthService, log: LogCallback | None = None) -> None:
        self.auth = auth
        self.log = log or (lambda _message: None)

    def export_csv(
        self,
        output_path: str | Path,
        semester: str = "",
        include_unscheduled: bool = False,
    ) -> ExportResult:
        try:
            courses = timetable.fetchChosenCourses(self.auth.require_session())
        except RuntimeError as exc:
            # 课表脚本的历史接口适配器将 302/非 JSON 统一报告为 RuntimeError；
            # 桌面应用在这里补一轮会话恢复，避免用户必须回登录页重试。
            self.log("课表请求失败，尝试恢复会话：{0}".format(exc))
            self.auth.relogin()
            courses = timetable.fetchChosenCourses(self.auth.require_session())
        if semester.strip():
            courses = [
                course for course in courses
                if str(course.get("XNXQMC") or "") == semester.strip()
            ]

        warnings: list[str] = []
        rows, unscheduled = timetable.buildRows(
            courses,
            include_unscheduled=include_unscheduled,
            warnings=warnings,
        )
        path = Path(output_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.FIELDS)
            writer.writeheader()
            writer.writerows({field: row.get(field, "") for field in self.FIELDS} for row in rows)

        self.log(
            "课表导出完成：{0} 门课程，{1} 条安排，{2} 条警告，文件：{3}".format(
                len(courses), len(rows), len(warnings), path
            )
        )
        if unscheduled and not include_unscheduled:
            self.log("有 {0} 门无固定排课的课程未写入 CSV".format(len(unscheduled)))
        for warning in warnings:
            self.log("解析警告：{0}".format(warning))
        return ExportResult(str(path), len(courses), len(rows), len(warnings))
