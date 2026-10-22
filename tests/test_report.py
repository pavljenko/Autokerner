"""«Было / станет»: числа окна на рисованном шрифте"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from autokerner import auto, report  # noqa: E402
from tests.synthetic import мастер  # noqa: E402


class Прежний:
    """Кернинг «как в шрифте»: одна пара T–o"""
    count = 1
    classes = 0

    def value(self, левый, правый):
        return -20.0 if (левый, правый) == ("T", "o") else 0.0


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.мастера = [мастер(жир=60, weight=300.0), мастер(жир=140, weight=700.0)]
        self.итог = auto.run(self.мастера)
        self.отчёт = report.build(self.мастера, self.итог, [Прежний(), Прежний()])

    def test_spacing_rows_per_master(self):
        имена = {п.name for п in self.отчёт.spacing}
        self.assertEqual(имена, set(self.итог.spacing))
        крупные = [п.size for п in self.отчёт.spacing]
        self.assertEqual(крупные, sorted(крупные, reverse=True))

    def test_space_before_after(self):
        for мастер_, было, стало in self.отчёт.space:
            self.assertEqual(было, 600)
            self.assertLess(стало, было)

    def test_kerning_numbers(self):
        a = self.отчёт.kern_after
        self.assertEqual(a["cells"], len(self.итог.kern.cells))
        self.assertEqual(a["pairs"], len(self.итог.kern.pairs))
        self.assertEqual([x[1] for x in self.отчёт.kern_before], [1, 1])

    def test_pair_changes_are_real(self):
        for л, п, м, было, стало in self.отчёт.pair_changes:
            self.assertNotEqual(было, стало)


if __name__ == "__main__":
    unittest.main()
