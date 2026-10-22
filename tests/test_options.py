"""Настройки окна: правило по умолчанию не меняется, остальное делает своё"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from autokerner import auto, kerning  # noqa: E402
from autokerner.fontlab_bridge import OldKerning  # noqa: E402
from autokerner.options import MERGE, Options, preset  # noqa: E402
from tests.synthetic import мастер  # noqa: E402


def мастера():
    return [мастер(жир=60, weight=300.0), мастер(жир=140, weight=700.0)]


class OptionsTest(unittest.TestCase):
    def test_classic_options_equal_plain_run(self):
        # исходное правило без поправок окна — итог расчёта без настроек
        self.assertEqual(auto.run(мастера()).to_json(), auto.run(мастера(), options=Options.classic()).to_json())
        self.assertTrue(Options().is_default_rule())

    def test_json_roundtrip_tolerates_unknown(self):
        o = preset("display")
        o.kern_mode = MERGE
        o2 = Options.from_json(o.to_json().replace("{", '{"чужое": 1, ', 1))
        self.assertEqual(o2.to_dict(), o.to_dict())
        self.assertEqual(Options.from_json("не json").to_dict(), Options().to_dict())

    def test_what_to_calculate(self):
        r = auto.run(мастера(), options=Options(spacing=False, space=False))
        self.assertEqual(r.spacing, {})
        self.assertEqual(r.space, {})
        self.assertIsNotNone(r.kern)
        self.assertIsNone(auto.run(мастера(), options=Options(kerning=False)).kern)

    def test_looseness_moves_sidebearings(self):
        плотно = auto.run(мастера(), options=Options(looseness=-15, kerning=False))
        свободно = auto.run(мастера(), options=Options(looseness=15, kerning=False))
        a, b = плотно.plans[0].item("n"), свободно.plans[0].item("n")
        self.assertLess(a.target_lsb, b.target_lsb)

    def test_fixed_glyph_keeps_its_fields(self):
        r = auto.run(мастера(), fixed={"u"})
        self.assertNotIn("u", r.spacing)
        self.assertIn("u", auto.run(мастера()).spacing)

    def test_strength_scales_kerning(self):
        слабо = auto.run(мастера(), options=Options(kern_strength=50))
        сильно = auto.run(мастера(), options=Options(kern_strength=150))
        self.assertGreater(слабо.kern.value("T", "o", 0), сильно.kern.value("T", "o", 0))


class CorrectionsTest(unittest.TestCase):
    """Поправки окна к исходному правилу"""

    def test_wide_space_goes_to_edge_and_stays(self):
        m = [мастер(пробел=900, weight=300.0), мастер(пробел=900, weight=700.0)]
        исходное = auto.run(m, kern=False).space[0]
        мягкое = auto.run(m, options=Options(kerning=False)).space[0]
        self.assertGreater(мягкое, исходное)
        self.assertLess(мягкое, 900)
        # повторный расчёт по уже поправленному пробелу его не трогает
        m2 = [мастер(пробел=мягкое, weight=300.0), мастер(пробел=мягкое, weight=700.0)]
        self.assertEqual(auto.run(m2, options=Options(kerning=False)).space, {})

    def test_wide_space_to_target_as_in_rule(self):
        """Выбор в окне «сузить до нормы» — пробел как в исходном правиле; набор возвращает умолчание"""
        m = [мастер(пробел=900, weight=300.0), мастер(пробел=900, weight=700.0)]
        до_нормы = Options(kerning=False, space_edge=False)
        self.assertEqual(auto.run(m, options=до_нормы).space, auto.run(m, kern=False).space)
        self.assertFalse(Options.from_dict(до_нормы.to_dict()).space_edge)
        self.assertTrue(preset("display", до_нормы).space_edge)

    def test_median_neutral_pocket_never_above_max(self):
        from autokerner.kerning import Grid, make_context, make_shape, x_height_of
        m = мастер()
        grid, рост = Grid(m.upm), x_height_of(m)

        def форма(i, law):
            return make_shape(m.glyphs[i].edges, m.advance(i), grid, рост, law)
        a = make_context(m, grid, рост, Options.classic().kern_law(), lambda i: форма(i, Options().kern_law()))
        b = make_context(m, grid, рост, Options().kern_law(), lambda i: форма(i, Options().kern_law()))
        self.assertLessEqual(b.neutral_pocket, a.neutral_pocket)


class KernValuesTest(unittest.TestCase):
    def test_round_toward_looser_and_cap(self):
        m = kerning.KernMatrix(["a"], [True], [False], [-13, 13, -200, 0])
        kerning.adjust_values(m, round_to=5, max_tight=120)
        self.assertEqual(m.values, [-10, 15, -120, 0])

    def test_loose_cap_zeroes_slack(self):
        m = kerning.KernMatrix(["a"], [True], [False], [533, 120, -60, 0], slack=[0, 7, 9, 0])
        kerning.adjust_values(m, max_loose=150)
        self.assertEqual(m.values, [150, 120, -60, 0])
        self.assertEqual(m.slack, [0, 7, 9, 0])
        m = kerning.KernMatrix(["a"], [True], [False], [533, 0, 0, 0], slack=[40, 0, 0, 0])
        kerning.adjust_values(m, max_loose=150)
        self.assertEqual(m.slack[0], 0)
        self.assertEqual(Options.classic().kern_max_loose, 0)

    def test_nontext_glyphs_are_not_kerned(self):
        from autokerner.model import Glyph, Master
        from tests.synthetic import прямоугольник
        m = мастер()
        знаки = list(m.glyphs) + [
            Glyph("underscore", [0x5F], 500, [прямоугольник(0, -120, 500, -60)]),
            Glyph("caron", [0x2C7], 300, [прямоугольник(60, 560, 240, 640)]),
            Glyph("acutecomb", [0x301], 0, [прямоугольник(-180, 560, -60, 680)]),
            Glyph("acutecomb.case", [], 0, [прямоугольник(-180, 760, -60, 880)]),
            Glyph("degree", [0xB0], 300, [прямоугольник(60, 500, 240, 700)]),
        ]
        m = Master(1000, знаки, x_height=500, cap_height=700, label="с метками")
        вне = kerning.nontext_glyphs(m)
        self.assertEqual(вне, {"underscore", "caron", "acutecomb", "acutecomb.case"})
        с = kerning.matrix_names(m, Options().kern_law())
        без = kerning.matrix_names(m, Options.classic().kern_law())
        self.assertNotIn("caron", с)
        self.assertIn("degree", с)
        self.assertIn("caron", без)

    def test_unlimited_and_fine_precision(self):
        r = kerning.KernRule(visible=5, exception_limit=0)
        self.assertEqual(r.steps()[0][0], 5)
        self.assertGreater(r.limit, 10 ** 9)
        self.assertEqual(kerning.KernRule().steps(), kerning.PRECISION_STEPS)

    def test_merge_keeps_own_pairs(self):
        r = auto.run(мастера())
        имена = [g.name for g in мастера()[0].glyphs]
        коды = {g.name: bool(g.codes) for g in мастера()[0].glyphs}
        свой = OldKerning([("T", False, "o", False, -20.0)], {})
        пары, _ = kerning.merge_pairs(r.kern, имена, коды, свой.has)
        self.assertNotIn("T|o", пары)
        self.assertTrue(пары)
        только, _ = kerning.merge_pairs(r.kern, имена, коды, свой.has, only={"period"})
        self.assertTrue(all("period" in ключ.split("|") for ключ in только))

    def test_overrides_win(self):
        r = auto.run(мастера())
        план = kerning.with_overrides(r.kern, {"T|o": [-5, -6]})
        self.assertEqual([план.value("T", "o", 0), план.value("T", "o", 1)], [-5, -6])
        self.assertNotEqual(r.kern.value("T", "o", 0), -5)


if __name__ == "__main__":
    unittest.main()
