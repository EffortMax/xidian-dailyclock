import unittest

from app.models import CourseClass, SelectionTarget


class AppModelTests(unittest.TestCase):
    def test_target_rejects_empty_kcdm(self):
        with self.assertRaises(ValueError):
            SelectionTarget("").validate()

    def test_target_rejects_too_short_interval(self):
        with self.assertRaises(ValueError):
            SelectionTarget("X1TEST", poll_interval=0).validate()

    def test_target_rejects_unknown_empty_policy(self):
        with self.assertRaises(ValueError):
            SelectionTarget("X1TEST", on_empty="guess").validate()

    def test_course_class_detects_free_seat(self):
        course = CourseClass.from_record(
            {
                "KCDM": "X1TEST",
                "KCMC": "测试课程",
                "BJDM": "BJ001",
                "BJMC": "01班",
                "KXRS": 30,
                "DQRS": 29,
            }
        )
        self.assertTrue(course.has_free_seat)

    def test_course_class_handles_invalid_capacity(self):
        course = CourseClass.from_record({"KXRS": "?", "DQRS": "?"})
        self.assertFalse(course.has_free_seat)


if __name__ == "__main__":
    unittest.main()

