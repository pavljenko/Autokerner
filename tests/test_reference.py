"""Сверка с расчётом исходной программы — на шрифтах, которых в репозитории нет.

Шрифты лежат в `test-fonts/`, эталоны — в `reference/root-ИМЯ/` (обе папки
вне git). Нет их — тест пропускается. Вариативный шрифт
меряется по срезам весов, которые исходная программа оставила рядом с эталоном.
Шрифты больше 600 знаков считаются минутами — только с
`AUTOKERNER_REFERENCE=all`.
"""

import glob
import os
import sys
import unittest

КОРЕНЬ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, КОРЕНЬ)

from tools.compare_reference import compare  # noqa: E402


def найти():
    вышло = []
    for эталон in sorted(glob.glob(os.path.join(КОРЕНЬ, "reference", "root-*", "Finishing", "*", "*.json"))):
        имя = os.path.basename(эталон.split(os.sep + "Finishing" + os.sep)[0])[len("root-"):]
        срезы = os.path.join(os.path.dirname(эталон), "срезы")
        if os.path.isdir(срезы):
            вышло.append((имя, срезы, эталон))
            continue
        for расширение in (".otf", ".ttf"):
            шрифт = os.path.join(КОРЕНЬ, "test-fonts", имя + расширение)
            if os.path.exists(шрифт):
                вышло.append((имя, шрифт, эталон))
    return вышло


class ReferenceTest(unittest.TestCase):
    def test_matches_reference(self):
        найдено = найти()
        if not найдено:
            self.skipTest("нет эталонных расчётов (reference/) — проверка только локальная")
        все = os.environ.get("AUTOKERNER_REFERENCE") == "all"
        for имя, шрифт, эталон in найдено:
            if not все and not os.path.isdir(шрифт):
                from fontTools.ttLib import TTFont
                if TTFont(шрифт)["maxp"].numGlyphs > 600:
                    continue
            with self.subTest(шрифт=имя):
                self.assertEqual(compare(шрифт, эталон, verbose=False), 0)


if __name__ == "__main__":
    unittest.main()
