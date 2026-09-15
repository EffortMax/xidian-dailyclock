from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


ON_EMPTY_POLICIES = ("warn", "ignore_filter", "abort")


@dataclass(frozen=True)
class SelectionTarget:
    """一次自动选课任务的明确目标。"""

    kcdm: str
    bjdm: str = ""
    bjmc_keyword: str = ""
    xqmc_keyword: str = ""
    poll_interval: float = 15.0
    on_empty: str = "warn"

    def validate(self) -> None:
        if not self.kcdm.strip():
            raise ValueError("课程代码不能为空")
        if self.poll_interval < 1:
            raise ValueError("轮询间隔不能小于 1 秒")
        if self.on_empty not in ON_EMPTY_POLICIES:
            raise ValueError(
                "未找到课程时的策略必须是：{0}".format(" / ".join(ON_EMPTY_POLICIES))
            )


@dataclass(frozen=True)
class CourseClass:
    """把选课系统原始课程记录转换为 UI 使用的稳定模型。"""

    kcdm: str
    kcmc: str
    bjdm: str
    bjmc: str
    campus: str
    source: str
    lx: str
    capacity: str
    selected_count: str
    teacher: str
    schedule: str
    raw: Mapping[str, Any]

    @property
    def has_free_seat(self) -> bool:
        try:
            return int(self.selected_count or 0) < int(self.capacity or 0)
        except (TypeError, ValueError):
            return False

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "CourseClass":
        return cls(
            kcdm=str(record.get("KCDM") or ""),
            kcmc=str(record.get("KCMC") or ""),
            bjdm=str(record.get("BJDM") or ""),
            bjmc=str(record.get("BJMC") or ""),
            campus=str(record.get("XQMC") or ""),
            source=str(record.get("_source") or ""),
            lx=str(record.get("_lx") or "0"),
            capacity=str(record.get("KXRS") or ""),
            selected_count=str(record.get("DQRS") or ""),
            teacher=str(record.get("RKJS") or ""),
            schedule=str(record.get("PKSJDDMS") or record.get("PKSJDD") or ""),
            raw=record,
        )


@dataclass(frozen=True)
class ExportResult:
    output_path: str
    course_count: int
    row_count: int
    warning_count: int
