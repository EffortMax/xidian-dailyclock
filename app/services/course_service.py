from __future__ import annotations

import threading
import time
from typing import Callable, Sequence

import requests

import courseChoose as chooser
import xidian_login as xl
from app.models import CourseClass, SelectionTarget
from app.services.auth_service import AuthService


LogCallback = Callable[[str], None]


class CourseService:
    """课程查询、已选课程和自动选课服务。"""

    def __init__(self, auth: AuthService, log: LogCallback | None = None) -> None:
        self.auth = auth
        self.log = log or (lambda _message: None)

    def _session(self):
        return self.auth.require_session()

    def list_courses(self, keyword: str = "") -> list[CourseClass]:
        records = chooser.queryCourseList(self._session(), pause=1)
        if keyword.strip():
            key = keyword.strip().lower()
            records = [
                record for record in records
                if key in str(record.get("KCDM") or "").lower()
                or keyword in str(record.get("KCMC") or "")
                or keyword in str(record.get("BJMC") or "")
                or keyword in str(record.get("RKJS") or "")
            ]
        return [CourseClass.from_record(record) for record in records]

    def chosen_courses(self) -> list[dict]:
        return chooser.fetchChosenCourses(self._session())

    def drop_course(self, bjdm: str, verify_tries: int = 5) -> dict:
        """退掉一个明确的教学班，并复核它已从已选课程中消失。"""

        bjdm = bjdm.strip()
        if not bjdm:
            raise ValueError("教学班代码 BJDM 不能为空")
        chosen = self.chosen_courses()
        course = next(
            (entry for entry in chosen if str(entry.get("BJDM") or "").strip() == bjdm),
            None,
        )
        if course is None:
            raise RuntimeError("已选课程中没有教学班 {0}".format(bjdm))

        csrf_token = self._refresh_csrf()
        ok, why = chooser.cancelCourse(self._session(), bjdm, csrf_token)
        if not ok:
            raise RuntimeError("退课失败：{0}".format(why or "接口未说明原因"))

        for attempt in range(1, max(1, verify_tries) + 1):
            remaining = self.chosen_courses()
            if not any(str(entry.get("BJDM") or "").strip() == bjdm for entry in remaining):
                self.log("退课成功，已确认教学班 {0} 不在已选课程中".format(bjdm))
                return course
            if attempt < verify_tries:
                time.sleep(1)
        raise RuntimeError("退课接口返回成功，但复核时该教学班仍在已选课程中")

    @staticmethod
    def _wait(seconds: float, stop_event: threading.Event | None) -> bool:
        if stop_event is None:
            time.sleep(seconds)
            return False
        return stop_event.wait(max(0.0, seconds))

    def _refresh_csrf(self) -> str:
        public_info = chooser.getPublicInfo(self._session())
        token = public_info.get("csrfToken") if isinstance(public_info, dict) else None
        if not token:
            raise RuntimeError("选课公共信息中没有 csrfToken")
        return str(token)

    def _recover(self, reason: str) -> None:
        self.log("需要恢复会话：{0}".format(reason))
        state, why = xl.login_state(self._session())
        if state is True:
            self.log("会话仍然有效：{0}".format(why))
            return
        self.auth.relogin()

    def _verify_chosen(
        self,
        bjdm: str,
        stop_event: threading.Event | None,
        tries: int = 8,
        pause: float = 2.0,
    ) -> tuple[bool, dict | None]:
        """可中断地复核最终选课结果，避免停止按钮等待完整轮询。"""
        for attempt in range(1, tries + 1):
            if stop_event is not None and stop_event.is_set():
                return False, None
            chosen = self.chosen_courses()
            for course in chosen:
                if course.get("BJDM") == bjdm:
                    return True, course
            if attempt < tries and self._wait(pause, stop_event):
                return False, None
        return False, None

    @staticmethod
    def _target_label(target: SelectionTarget) -> str:
        details = []
        if target.bjdm.strip():
            details.append("BJDM={0}".format(target.bjdm.strip()))
        if target.bjmc_keyword.strip():
            details.append("教学班含 {0}".format(target.bjmc_keyword.strip()))
        if target.xqmc_keyword.strip():
            details.append("校区 {0}".format(target.xqmc_keyword.strip()))
        suffix = "，" + "，".join(details) if details else ""
        return "{0}{1}".format(target.kcdm.strip(), suffix)

    @staticmethod
    def _chosen_entry(target: SelectionTarget, chosen: Sequence[dict]) -> dict | None:
        wanted_bjdm = target.bjdm.strip()
        wanted_kcdm = target.kcdm.strip().casefold()
        for entry in chosen:
            if wanted_bjdm:
                if str(entry.get("BJDM") or "").strip() == wanted_bjdm:
                    return entry
            elif str(entry.get("KCDM") or "").strip().casefold() == wanted_kcdm:
                return entry
        return None

    @staticmethod
    def _filter_for_target(records: list[dict], target: SelectionTarget) -> list[dict]:
        classes = chooser.filterClasses(
            records,
            target.kcdm.strip(),
            target.bjmc_keyword.strip(),
            target.xqmc_keyword.strip(),
        )
        if target.bjdm.strip():
            classes = [
                course for course in classes
                if str(course.get("BJDM") or "").strip() == target.bjdm.strip()
            ]
        return classes

    def auto_select_many(
        self,
        targets: Sequence[SelectionTarget],
        stop_event: threading.Event | None = None,
    ) -> list[dict]:
        """轮询多个目标；每轮只拉一次课程列表，并使用每个目标自己的筛选条件。"""

        target_list = list(targets)
        if not target_list:
            raise ValueError("至少需要一个抢课目标")
        seen_codes: set[str] = set()
        for target in target_list:
            target.validate()
            code = target.kcdm.strip().casefold()
            if code in seen_codes:
                raise ValueError(
                    "多目标队列不能重复课程代码 {0}；请在同一个目标中设置教学班或校区筛选".format(
                        target.kcdm.strip()
                    )
                )
            seen_codes.add(code)

        session = self._session()
        csrf_token = self._refresh_csrf()
        pending = {index: target for index, target in enumerate(target_list)}
        selected: dict[int, dict] = {}
        last_states: dict[int, str] = {}
        round_number = 0

        self.log("开始多目标自动抢课，共 {0} 个目标".format(len(target_list)))
        for index, target in pending.items():
            self.log("  {0}. {1}（空结果策略：{2}）".format(
                index + 1, self._target_label(target), target.on_empty
            ))

        def log_state(index: int, state: str, message: str) -> None:
            if last_states.get(index) != state:
                last_states[index] = state
                self.log(message)

        while pending and (stop_event is None or not stop_event.is_set()):
            round_number += 1
            started = time.monotonic()
            self.log(
                "轮询第 {0} 轮开始：正在获取课程列表（待完成 {1}/{2}）".format(
                    round_number,
                    len(pending),
                    len(target_list),
                )
            )
            try:
                records = chooser.queryCourseList(
                    session,
                    retries=3,
                    pause=min(min(t.poll_interval for t in pending.values()), 5),
                )
                chosen_cache: list[dict] | None = None

                for index, target in list(pending.items()):
                    if stop_event is not None and stop_event.is_set():
                        break

                    label = self._target_label(target)
                    classes = self._filter_for_target(records, target)
                    relaxed = False
                    if (
                        not classes
                        and target.on_empty == "ignore_filter"
                        and not target.bjdm.strip()
                    ):
                        classes = chooser.filterClasses(records, target.kcdm.strip())
                        relaxed = bool(classes)
                        if relaxed:
                            log_state(
                                index,
                                "relaxed",
                                "[{0}] 严格筛选无结果，已按策略放宽教学班/校区条件".format(label),
                            )

                    if not classes:
                        if chosen_cache is None:
                            chosen_cache = self.chosen_courses()
                        already = self._chosen_entry(target, chosen_cache)
                        if already is not None:
                            selected[index] = already
                            del pending[index]
                            self.log("[{0}] 已在已选课程中，标记为完成".format(label))
                            continue
                        if target.on_empty == "abort":
                            raise RuntimeError(
                                "目标 {0} 没有符合筛选条件的教学班，已按 abort 策略停止".format(label)
                            )
                        locked_hint = "；已锁定 BJDM，不会自动放宽" if target.bjdm.strip() else ""
                        log_state(
                            index,
                            "empty",
                            "[{0}] 暂未找到符合条件的教学班{1}".format(label, locked_hint),
                        )
                        continue

                    course = chooser.pickClass(classes)
                    if not course:
                        log_state(index, "empty", "[{0}] 暂无可用教学班".format(label))
                        continue

                    bjdm = str(course.get("BJDM") or "")
                    state = "{0}:{1}/{2}:{3}".format(
                        bjdm,
                        course.get("DQRS") or "?",
                        course.get("KXRS") or "?",
                        "free" if chooser.hasFreeSeat(course) else "full",
                    )
                    note = "（已放宽筛选）" if relaxed else ""
                    log_state(
                        index,
                        state,
                        "[{0}] 当前教学班 {1}，容量 {2}/{3}，{4}{5}".format(
                            label,
                            course.get("BJMC") or bjdm,
                            course.get("DQRS") or "?",
                            course.get("KXRS") or "?",
                            "有空位" if chooser.hasFreeSeat(course) else "已满",
                            note,
                        ),
                    )
                    if not chooser.hasFreeSeat(course):
                        continue

                    ok, why = chooser.chooseCourse(
                        session,
                        bjdm,
                        csrf_token,
                        lx=course.get("_lx", "0"),
                    )
                    if not ok:
                        self.log("[{0}] 本次选课未成功：{1}".format(label, why))
                        continue

                    self.log("[{0}] 请求已受理，正在复核最终结果：{1}".format(label, why))
                    verified, entry = self._verify_chosen(bjdm, stop_event)
                    if verified:
                        selected[index] = entry or course
                        del pending[index]
                        self.log("[{0}] 选课成功，已在已选课程中确认".format(label))
                    elif stop_event is None or not stop_event.is_set():
                        self.log("[{0}] 接口表示成功，但暂未在已选课程中看到该教学班".format(label))

            except chooser.SessionExpired as exc:
                self._recover(str(exc))
                session = self._session()
                csrf_token = self._refresh_csrf()
            except chooser.ServerError as exc:
                self.log("选课系统内部错误：{0}".format(exc))
                self._recover(str(exc))
                session = self._session()
                csrf_token = self._refresh_csrf()
            except requests.RequestException as exc:
                self.log("网络异常：{0}".format(exc))

            if pending and (stop_event is None or not stop_event.is_set()):
                elapsed = time.monotonic() - started
                interval = min(target.poll_interval for target in pending.values())
                wait_seconds = max(0.0, interval - elapsed)
                self.log(
                    "轮询第 {0} 轮完成：仍有 {1} 个目标等待，{2:.1f} 秒后继续".format(
                        round_number,
                        len(pending),
                        wait_seconds,
                    )
                )
                if self._wait(wait_seconds, stop_event):
                    break
            elif not pending:
                self.log("轮询第 {0} 轮完成：全部目标已完成".format(round_number))

        if pending:
            raise RuntimeError("自动抢课已停止")
        return [selected[index] for index in range(len(target_list))]

    def auto_select(
        self,
        target: SelectionTarget,
        stop_event: threading.Event | None = None,
    ) -> dict:
        """兼容单目标调用；实际由多目标引擎执行。"""

        return self.auto_select_many([target], stop_event)[0]
