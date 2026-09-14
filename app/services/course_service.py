from __future__ import annotations

import threading
import time
from typing import Callable

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

    def auto_select(
        self,
        target: SelectionTarget,
        stop_event: threading.Event | None = None,
    ) -> dict:
        """自动轮询课程并在最终复核成功后返回已选课程记录。"""

        target.validate()
        session = self._session()
        csrf_token = self._refresh_csrf()
        last_bjdm = ""
        completed = False

        self.log(
            "开始自动抢课：{0}，校区={1}，教学班={2}，间隔={3}s".format(
                target.kcdm,
                target.xqmc_keyword or "不限",
                target.bjmc_keyword or "不限",
                target.poll_interval,
            )
        )

        while stop_event is None or not stop_event.is_set():
            started = time.monotonic()
            try:
                records = chooser.queryCourseList(
                    session,
                    retries=3,
                    pause=min(target.poll_interval, 5),
                )
                classes = chooser.filterClasses(
                    records,
                    target.kcdm,
                    target.bjmc_keyword,
                    target.xqmc_keyword,
                )
                if target.bjdm.strip():
                    classes = [
                        course for course in classes
                        if str(course.get("BJDM") or "") == target.bjdm.strip()
                    ]
                if not classes:
                    chosen = self.chosen_courses()
                    already = [c for c in chosen if c.get("KCDM") == target.kcdm]
                    if already:
                        self.log("目标课程已在已选课程中，任务完成")
                        completed = True
                        return already[0]
                    self.log("暂未找到符合条件的教学班")
                else:
                    course = chooser.pickClass(classes)
                    if course and course.get("BJDM") != last_bjdm:
                        last_bjdm = course.get("BJDM") or ""
                        self.log(
                            "当前教学班：{0}，容量 {1}/{2}，{3}".format(
                                course.get("BJMC") or target.kcdm,
                                course.get("DQRS") or "?",
                                course.get("KXRS") or "?",
                                "有空位" if chooser.hasFreeSeat(course) else "已满",
                            )
                        )
                    if course and chooser.hasFreeSeat(course):
                        ok, why = chooser.chooseCourse(
                            session,
                            course["BJDM"],
                            csrf_token,
                            lx=course.get("_lx", "0"),
                        )
                        if ok:
                            self.log("请求已受理，正在复核最终结果：{0}".format(why))
                            verified, entry = self._verify_chosen(
                                course["BJDM"], stop_event
                            )
                            if verified:
                                self.log("选课成功，已在已选课程中确认")
                                completed = True
                                return entry or course
                            self.log("接口表示成功，但暂未在已选课程中看到该教学班")
                        else:
                            self.log("本次选课未成功：{0}".format(why))
                    else:
                        self.log("当前教学班已满，等待下一轮")

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
            finally:
                if not completed:
                    elapsed = time.monotonic() - started
                    if self._wait(max(0.0, target.poll_interval - elapsed), stop_event):
                        break

        raise RuntimeError("自动抢课已停止")
