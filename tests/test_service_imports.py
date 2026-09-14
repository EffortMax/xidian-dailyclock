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
