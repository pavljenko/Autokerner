"""Что окажется в шрифте: режимы записи кернинга, неразрывный пробел,
живая строка и сохранение в файл"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from autokerner import auto, export, outcome, report  # noqa: E402
from autokerner.fontlab_bridge import OldKerning  # noqa: E402
from autokerner.geometry import contours_rect  # noqa: E402
from autokerner.model import Glyph, Master  # noqa: E402
from autokerner.options import MERGE, Options  # noqa: E402
from tests.synthetic import мастер, прямоугольник  # noqa: E402


def мастера(nbsp=None):
    вышло = []
    for жир, вес in ((60, 300.0), (140, 700.0)):
        m = мастер(жир=жир, weight=вес)
        if nbsp is not None:
            m = Master(m.upm, m.glyphs + [Glyph("nbspace", [0xA0], nbsp, [])], m.x_height,
                       m.cap_height, m.label, m.weight)
        вышло.append(m)
    return вышло


ПУСТО = OldKerning([], {})


class WriteModeTest(unittest.TestCase):
    def test_merge_into_empty_writes_whole(self):
        свой = OldKerning([("T", False, "o", False, -20.0)], {})
        self.assertEqual(outcome.write_mode(Options(kern_mode=MERGE), [ПУСТО, ПУСТО]), outcome.WHOLE)
        self.assertEqual(outcome.write_mode(Options(kern_mode=MERGE), [свой, ПУСТО]), outcome.MISSING)
        self.assertEqual(outcome.write_mode(Options(), [свой]), outcome.WHOLE)
        self.assertEqual(outcome.write_mode(Options(), [свой], only={"T"}), outcome.SELECTED)

    def test_after_values_by_mode(self):
        r = auto.run(мастера())
        план = r.kern
        свой = OldKerning([("T", False, "o", False, -20.0), ("H", False, "H", False, 7.0)], {})
        целиком = outcome.kern_after(план, свой, 0, outcome.WHOLE)
        self.assertEqual(целиком("T", "o"), план.value("T", "o", 0))
        дописать = outcome.kern_after(план, свой, 0, outcome.MISSING)
        self.assertEqual(дописать("T", "o"), -20.0)
        self.assertEqual(дописать("T", "period"), план.value("T", "period", 0))
        выделенные = outcome.kern_after(план, свой, 0, outcome.SELECTED, only={"T"})
        self.assertEqual(выделенные("H", "H"), 7.0)
        self.assertEqual(выделенные("T", "o"), план.value("T", "o", 0))
        снята = outcome.kern_after(план, свой, 0, outcome.WHOLE, rejected={"T|o"})
        self.assertEqual(снята("T", "o"), -20.0)

    def test_selected_pairs_override_classes_with_zero(self):
        r = auto.run(мастера())
        имена = [g.name for g in мастера()[0].glyphs]
        коды = {g.name: bool(g.codes) for g in мастера()[0].glyphs}
        # прежний кернинг классами: у пары «T o» из расчёта может быть 0 —
        # тогда пишется пара с нулём, перебивающая класс
        свой = OldKerning([("L_T", True, "R_o", True, -99.0)],
                          {"L_T": (["T"], "KernLeft"), "R_o": (["o", "O"], "KernRight")})
        пары, _ = outcome.pair_writes(r.kern, имена, коды, [свой, свой], outcome.SELECTED, only={"T"})
        self.assertIn("T|O", пары)
        self.assertEqual(пары["T|O"], [r.kern.value("T", "O", 0), r.kern.value("T", "O", 1)])
        self.assertTrue(all("T" in к.split("|") for к in пары))
        дописать, _ = outcome.pair_writes(r.kern, имена, коды, [свой, свой], outcome.MISSING,
                                          rejected={"period|T"})
        self.assertNotIn("T|o", дописать)
        self.assertNotIn("period|T", дописать)

    def test_changed_pairs(self):
        r = auto.run(мастера())
        имена = [g.name for g in мастера()[0].glyphs]
        после = outcome.kern_after(r.kern, ПУСТО, 0, outcome.WHOLE)
        крупные = outcome.changed_pairs(имена, ПУСТО.value, после, top=3)
        self.assertEqual(len(крупные), 3)
        self.assertGreaterEqual(abs(крупные[0][3]), abs(крупные[-1][3]))
        с_t = outcome.changed_pairs(имена, ПУСТО.value, после, glyph="T")
        self.assertTrue(all("T" in (л, п) for л, п, _, _ in с_t))


class NbspTest(unittest.TestCase):
    def test_nbsp_follows_space(self):
        r = auto.run(мастера(nbsp=333), options=Options(kerning=False))
        цель = [r.space.get(w, 600) for w in range(2)]
        self.assertEqual(r.spacing["nbspace"], {0: (0, цель[0]), 1: (0, цель[1])})
        # без настроек окна — исходное правило как есть
        self.assertNotIn("nbspace", auto.run(мастера(nbsp=333), kern=False).spacing)
        self.assertNotIn("nbspace", auto.run(мастера(nbsp=333), options=Options(
            kerning=False, nbsp_follows_space=False)).spacing)

    def test_fixed_space_is_kept(self):
        m = [мастер(пробел=900, weight=300.0), мастер(пробел=900, weight=700.0)]
        self.assertTrue(auto.run(m, kern=False).space)
        self.assertEqual(auto.run(m, kern=False, fixed={"space"}).space, {})


def мастера_с_цифрами():
    """Синтетика с семёркой-навесом, четвёркой и запятой — как «7,4»"""
    вышло = []
    for жир, вес in ((60, 300.0), (140, 700.0)):
        m = мастер(жир=жир, weight=вес)
        добавка = [
            Glyph("seven", [0x37], 560, [прямоугольник(40, 700 - жир, 520, 700),
                                         прямоугольник(200, 0, 200 + жир, 700 - жир)]),
            Glyph("four", [0x34], 560, [прямоугольник(60, 0, 60 + жир, 700), прямоугольник(60, 250, 500, 250 + жир)]),
            Glyph("comma", [0x2C], 220, [прямоугольник(60, -140, 60 + жир, жир)]),
        ]
        вышло.append(Master(m.upm, m.glyphs + добавка, m.x_height, m.cap_height, m.label, m.weight))
    return вышло


class FiguresTest(unittest.TestCase):
    """Цифры с запятой, точкой, двоеточием: как в правиле, без столкновений, не кернить"""

    def ширина(self, r, мм, имя, w):
        return r.spacing.get(имя, {}).get(w, (0, мм[w].advance(мм[w].by_name(имя))))[1]

    def test_safe_keeps_figures_apart(self):
        мм = мастера_с_цифрами()
        цифры = ["one", "two", "four", "seven"]
        r = auto.run(мм, options=Options(kern_figures="safe", nbsp_follows_space=False))
        for w in range(len(мм)):
            for знак in ("comma", "period"):
                for a in цифры:
                    for b in цифры:
                        вместе = self.ширина(r, мм, знак, w) + r.kern.value(a, знак, w) + r.kern.value(знак, b, w)
                        # класс может разойтись с замером не больше чем на полузазор
                        self.assertGreaterEqual(вместе, -13, (a, знак, b, w))
                    # цифра после знака к нему не подтягивается
                    self.assertGreaterEqual(r.kern.value(знак, a, w), 0, (знак, a, w))
        self.assertEqual(r.collisions, [])

    def test_off_and_rule(self):
        мм = мастера_с_цифрами()
        выкл = auto.run(мм, options=Options(kern_figures="off", nbsp_follows_space=False))
        for a in ("one", "two", "four", "seven"):
            for знак in ("comma", "period"):
                self.assertTrue(abs(выкл.kern.value(a, знак, 0)) < 10 and abs(выкл.kern.value(знак, a, 0)) < 10)
        # «как в правиле» без прочих поправок — исходное правило как есть
        self.assertEqual(auto.run(мм).to_json(), auto.run(мм, options=Options.classic()).to_json())


def мастера_с_кавычкой():
    """Синтетика с кавычкой наверху и запятой внизу — общих высот у них нет"""
    вышло = []
    for жир, вес in ((60, 300.0), (140, 700.0)):
        m = мастер(жир=жир, weight=вес)
        добавка = [
            Glyph("quoteright", [0x2019], 120 + жир, [прямоугольник(60, 520, 60 + жир, 700)]),
            Glyph("comma", [0x2C], 120 + жир, [прямоугольник(60, -140, 60 + жир, жир)]),
        ]
        вышло.append(Master(m.upm, m.glyphs + добавка, m.x_height, m.cap_height, m.label, m.weight))
    return вышло


class MarksApartTest(unittest.TestCase):
    """Кавычка и запятая не заходят друг под друга"""

    def просветы(self, мм, r):
        """(пара, мастер) → (просвет рамок без кернинга, кернинг)"""
        вышло = {}
        for w, m in enumerate(мм):
            for л, п in (("quoteright", "comma"), ("comma", "quoteright")):
                поля = []
                for имя in (л, п):
                    i = m.by_name(имя)
                    рамка = contours_rect(m.contours(i))
                    сдвиг, ширина = r.spacing.get(имя, {}).get(w, (0, m.advance(i)))
                    поля.append((рамка[0] + сдвиг, ширина - рамка[2] - сдвиг))
                вышло[(л, п, w)] = (поля[0][1] + поля[1][0], r.kern.value(л, п, w))
        return вышло

    def test_quote_and_comma_stay_side_by_side(self):
        мм = мастера_с_кавычкой()
        # исходное правило заводит запятую под кавычку
        было = self.просветы(мм, auto.run(мм, options=Options.classic()))
        self.assertTrue(any(просвет + k < 0 for просвет, k in было.values()), было)
        стало = self.просветы(мм, auto.run(мм, options=Options(nbsp_follows_space=False)))
        for ключ, (просвет, k) in стало.items():
            # не ближе зазора (с запасом на полузазор класса); раздвигать не раздвигает
            self.assertGreaterEqual(k, min(0, 25 - просвет) - 13, (ключ, просвет, k))
            self.assertLessEqual(k, 0, ключ)


class PreviewTest(unittest.TestCase):
    def test_parse_and_layout(self):
        m = мастера()[0]
        имена = outcome.parse_text("To/period/space Hя", m)
        self.assertEqual(имена, ["T", "o", "period", "space", "H"])
        места, ширина = outcome.layout(["T", "o"], m, lambda л, п: -50)
        self.assertEqual(места, [("T", 0), ("o", 600 - 50)])
        self.assertEqual(ширина, 600 - 50 + 520)


class ExportTest(unittest.TestCase):
    def test_fea_and_csv(self):
        мм = мастера()
        r = auto.run(мм)
        отчёт = report.build(мм, r, [ПУСТО, ПУСТО])
        fea = export.kerning_fea(r.kern, 1, "Bold")
        self.assertIn("feature kern {", fea)
        self.assertTrue(fea.rstrip().endswith("} kern;"))
        # пары знаков — до пар классов
        if r.kern.pairs and r.kern.cells:
            self.assertLess(fea.index("pos " + sorted(r.kern.pairs)[0].replace("|", " ")), fea.index("pos @"))
        with tempfile.TemporaryDirectory() as папка:
            файлы = export.save(папка, "Test: Sans/Bold", "<p>итог</p>", отчёт, r,
                                [m.label for m in мм])
            self.assertTrue(all(os.path.exists(ф) for ф in файлы))
            self.assertTrue(all("/" not in os.path.basename(ф).replace(" — ", "") for ф in файлы))
            self.assertEqual(sum(ф.endswith(".fea") for ф in файлы), 2)


if __name__ == "__main__":
    unittest.main()
