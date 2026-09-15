import unittest
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

from app.services.auth_service import AuthService
from app.services.course_service import CourseService
from app.services.timetable_service import TimetableService
from app.models import SelectionTarget
import courseChoose as chooser
import courseQuery as timetable


class ServiceImportTests(unittest.TestCase):
    def test_services_are_importable(self):
        auth = AuthService()
        self.assertIsInstance(CourseService(auth), CourseService)
        self.assertIsInstance(TimetableService(auth), TimetableService)

    def test_auto_selection_requires_final_verification(self):
        class FakeAuth:
            def require_session(self):
                return object()

            def relogin(self):
                raise AssertionError("mocked selection should not need relogin")

        record = {
            "KCDM": "X1TEST",
            "KCMC": "测试课程",
            "BJDM": "BJ001",
            "BJMC": "01班",
            "XQMC": "北校区",
            "KXRS": 30,
            "DQRS": 1,
            "_lx": "0",
        }
        with patch.object(chooser, "getPublicInfo", return_value={"csrfToken": "token"}), \
             patch.object(chooser, "queryCourseList", return_value=[record]), \
             patch.object(chooser, "chooseCourse", return_value=(True, "accepted")), \
             patch.object(chooser, "fetchChosenCourses", return_value=[record]):
            service = CourseService(FakeAuth())
            started = time.monotonic()
            result = service.auto_select(
                SelectionTarget("X1TEST", bjdm="BJ001", poll_interval=3),
                threading.Event(),
            )
        self.assertEqual(result["BJDM"], "BJ001")
        self.assertLess(time.monotonic() - started, 1)

    def test_multi_target_selection_reuses_one_course_list(self):
        class FakeAuth:
            def require_session(self):
                return object()

            def relogin(self):
                raise AssertionError("mocked selection should not need relogin")

        records = [
            {
                "KCDM": "X1ONE", "KCMC": "课程一", "BJDM": "BJ001", "BJMC": "01班",
                "XQMC": "北校区", "KXRS": 30, "DQRS": 1, "_lx": "0",
            },
            {
                "KCDM": "X1TWO", "KCMC": "课程二", "BJDM": "BJ002", "BJMC": "02班",
                "XQMC": "南校区", "KXRS": 40, "DQRS": 2, "_lx": "2",
            },
        ]
        with patch.object(chooser, "getPublicInfo", return_value={"csrfToken": "token"}), \
             patch.object(chooser, "queryCourseList", return_value=records) as query, \
             patch.object(chooser, "chooseCourse", return_value=(True, "accepted")) as choose, \
             patch.object(chooser, "fetchChosenCourses", return_value=records):
            result = CourseService(FakeAuth()).auto_select_many([
                SelectionTarget("X1ONE", xqmc_keyword="北校区", poll_interval=3),
                SelectionTarget("X1TWO", xqmc_keyword="南校区", poll_interval=3),
            ])
        self.assertEqual([entry["BJDM"] for entry in result], ["BJ001", "BJ002"])
        self.assertEqual(query.call_count, 1)
        self.assertEqual(choose.call_count, 2)

    def test_multi_target_can_relax_its_own_filter(self):
        class FakeAuth:
            def require_session(self):
                return object()

        record = {
            "KCDM": "X1TEST", "KCMC": "测试课程", "BJDM": "BJ001", "BJMC": "01班",
            "XQMC": "北校区", "KXRS": 30, "DQRS": 1, "_lx": "0",
        }
        with patch.object(chooser, "getPublicInfo", return_value={"csrfToken": "token"}), \
             patch.object(chooser, "queryCourseList", return_value=[record]), \
             patch.object(chooser, "chooseCourse", return_value=(True, "accepted")), \
             patch.object(chooser, "fetchChosenCourses", return_value=[record]):
            result = CourseService(FakeAuth()).auto_select_many([
                SelectionTarget(
                    "X1TEST", xqmc_keyword="南校区", on_empty="ignore_filter", poll_interval=3
                ),
            ])
        self.assertEqual(result[0]["BJDM"], "BJ001")

    def test_multi_target_rejects_duplicate_course_codes(self):
        class FakeAuth:
            def require_session(self):
                return object()

        with patch.object(chooser, "getPublicInfo", return_value={"csrfToken": "token"}):
            with self.assertRaises(ValueError):
                CourseService(FakeAuth()).auto_select_many([
                    SelectionTarget("X1TEST", xqmc_keyword="北校区"),
                    SelectionTarget("x1test", xqmc_keyword="南校区"),
                ])

    def test_drop_course_uses_exact_bjdm_and_verifies_removal(self):
        class FakeAuth:
            def require_session(self):
                return object()

        record = {"KCDM": "X1TEST", "KCMC": "测试课程", "BJDM": "BJ001"}
        with patch.object(chooser, "fetchChosenCourses", side_effect=[[record], []]), \
             patch.object(chooser, "getPublicInfo", return_value={"csrfToken": "token"}), \
             patch.object(chooser, "cancelCourse", return_value=(True, "accepted")) as cancel:
            result = CourseService(FakeAuth()).drop_course("BJ001", verify_tries=1)
        self.assertEqual(result, record)
        cancel.assert_called_once_with(unittest.mock.ANY, "BJ001", "token")

    def test_drop_course_reports_server_rejection(self):
        class FakeAuth:
            def require_session(self):
                return object()

        record = {"KCDM": "X1TEST", "KCMC": "测试课程", "BJDM": "BJ001"}
        with patch.object(chooser, "fetchChosenCourses", return_value=[record]), \
             patch.object(chooser, "getPublicInfo", return_value={"csrfToken": "token"}), \
             patch.object(chooser, "cancelCourse", return_value=(False, "服务器拒绝")):
            with self.assertRaisesRegex(RuntimeError, "服务器拒绝"):
                CourseService(FakeAuth()).drop_course("BJ001", verify_tries=1)

    def test_drop_course_requires_final_removal_verification(self):
        class FakeAuth:
            def require_session(self):
                return object()

        record = {"KCDM": "X1TEST", "KCMC": "测试课程", "BJDM": "BJ001"}
        with patch.object(chooser, "fetchChosenCourses", return_value=[record]), \
             patch.object(chooser, "getPublicInfo", return_value={"csrfToken": "token"}), \
             patch.object(chooser, "cancelCourse", return_value=(True, "accepted")):
            with self.assertRaisesRegex(RuntimeError, "仍在已选课程"):
                CourseService(FakeAuth()).drop_course("BJ001", verify_tries=1)

    def test_timetable_export_writes_csv(self):
        class FakeAuth:
            def require_session(self):
                return object()

        courses = [{
            "KCDM": "X1TEST",
            "KCMC": "测试课程",
            "XQMC": "北校区",
            "RKJS": "教师",
            "PKSJDD": "1-2周 星期一[1-2节]A-101",
        }]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "course.csv"
            with patch.object(timetable, "fetchChosenCourses", return_value=courses):
                result = TimetableService(FakeAuth()).export_csv(output)
            self.assertTrue(output.exists())
            self.assertEqual(result.course_count, 1)
            self.assertGreaterEqual(result.row_count, 1)


if __name__ == "__main__":
    unittest.main()
