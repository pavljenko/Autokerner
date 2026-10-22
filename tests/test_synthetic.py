"""Расчёт на рисованном шрифте: что правило правит и чего не трогает"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from autokerner import auto  # noqa: E402
from autokerner.spacing import plan  # noqa: E402
from tests.synthetic import мастер  # noqa: E402


class SpacingTest(unittest.TestCase):
    def test_wide_u_is_pulled_in(self):
        п = plan(мастер())
        u = п.item("u")
        self.assertIn("u", [з.name for з in п.deviating])
        self.assertLess(u.delta_left, 0)
        self.assertLess(u.target_advance, u.advance)

    def test_wide_space_is_narrowed(self):
        п = plan(мастер())
        self.assertTrue(п.space.deviating)
        self.assertLess(п.space.target, 600)

    def test_narrow_space_is_left_alone(self):
        self.assertFalse(plan(мастер(пробел=200)).space.deviating)


class KernTest(unittest.TestCase):
    def setUp(self):
        self.итог = auto.run([мастер(широкая_u=False)])
        self.k = self.итог.kern

    def test_overhang_kerns_in(self):
        self.assertLess(self.k.value("T", "o", 0), 0)
        self.assertLess(self.k.value("T", "period", 0), 0)

    def test_straight_pair_is_zero(self):
        self.assertEqual(self.k.value("H", "H", 0), 0)
        self.assertEqual(self.k.value("n", "n", 0), 0)

    def test_digits_not_kerned_with_digits(self):
        self.assertEqual(self.k.value("one", "two", 0), 0)
        self.assertEqual(self.k.value("two", "one", 0), 0)


class MastersTest(unittest.TestCase):
    def test_classes_shared_numbers_per_master(self):
        итог = auto.run([мастер(жир=60, weight=300.0), мастер(жир=140, weight=700.0)])
        k = итог.kern
        self.assertEqual(k.weights, [300.0, 700.0])
        for числа in list(k.cells.values()) + list(k.pairs.values()):
            self.assertEqual(len(числа), 2)
        # знак правится на всех мастерах, если выбился хоть на одном
        for имя, по_мастерам in итог.spacing.items():
            self.assertEqual(sorted(по_мастерам), [0, 1], имя)


if __name__ == "__main__":
    unittest.main()
