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


class OpticalSpacingTest(unittest.TestCase):
    """Мягкий замер белого у края (`white_soft`, задачи #1, #2)"""

    def белое(self, контуры, ширина):
        from autokerner.geometry import ink_profile
        from autokerner.model import Glyph
        from autokerner.spacing import SpacingRule, white, white_soft
        профиль = ink_profile(Glyph("a", [], ширина, контуры).edges, 0, 700, 1000 / 256)
        return white(профиль, ширина, 70)[1], white_soft(профиль, ширина, SpacingRule(soft=True), 1000)[1]

    def test_plain_stem_same_as_hard(self):
        from tests.synthetic import прямоугольник
        жёстко, мягко = self.белое([прямоугольник(50, -20, 130, 720)], 180)
        self.assertAlmostEqual(жёстко, мягко, places=6)

    def test_white_behind_serif_counts_less(self):
        from tests.synthetic import прямоугольник
        I = [прямоугольник(110, 0, 190, 700), прямоугольник(50, 0, 250, 40), прямоугольник(50, 660, 250, 700)]
        жёстко, мягко = self.белое(I, 300)
        self.assertLess(мягко, жёстко)

    def test_deep_open_side_counts_more(self):
        from tests.synthetic import прямоугольник
        скобка = [прямоугольник(50, 0, 130, 700), прямоугольник(50, 0, 400, 60), прямоугольник(50, 640, 400, 700)]
        жёстко, мягко = self.белое(скобка, 450)
        self.assertGreater(мягко, жёстко)

    def мягко(self, контуры, ширина, вес):
        from autokerner.geometry import ink_profile
        from autokerner.model import Glyph
        from autokerner.spacing import SpacingRule, white_soft
        профиль = ink_profile(Glyph("a", [], ширина, контуры).edges, 0, 700, 1000 / 256)
        return white_soft(профиль, ширина, SpacingRule(soft=True, serif_weight=вес), 1000)

    def test_short_serif_weighs_less(self):
        from tests.synthetic import прямоугольник
        I = [прямоугольник(110, 0, 190, 700), прямоугольник(50, 0, 250, 40), прямоугольник(50, 660, 250, 700)]
        self.assertLess(self.мягко(I, 300, 0.75)[1], self.мягко(I, 300, 1.0)[1])

    def test_diagonal_and_long_arm_are_not_serifs(self):
        from autokerner.geometry import Contour
        from tests.synthetic import прямоугольник
        диагональ = [Contour([("moveTo", (50, 0)), ("lineTo", (130, 0)), ("lineTo", (330, 700)),
                               ("lineTo", (250, 700)), ("closePath",)])]
        T = [прямоугольник(260, 0, 340, 700), прямоугольник(10, 640, 590, 700)]
        for контуры, ширина in ((диагональ, 380), (T, 600)):
            self.assertEqual(self.мягко(контуры, ширина, 0.75), self.мягко(контуры, ширина, 1.0))

    def test_classic_keeps_hard_rule(self):
        self.assertFalse(Options.classic().spacing_rule().soft)
        self.assertTrue(Options().spacing_rule().soft)


class LowerOverhangTest(unittest.TestCase):
    """Хвостик строчной над строчной кармана не образует (задача #3)"""

    def мастер_с_f(self):
        from autokerner.model import Glyph, Master
        from tests.synthetic import прямоугольник
        m = мастер()
        f = Glyph("f", [0x66], 380, [прямоугольник(60, 0, 140, 760), прямоугольник(60, 700, 360, 760),
                                      прямоугольник(20, 440, 170, 500)])
        f_alt = Glyph("f.ss01", [], 380, list(f.contours))
        return Master(1000, list(m.glyphs) + [f, f_alt], x_height=500, cap_height=700, label="с f")

    def значение(self, m, law, a, b):
        мат = kerning.make_matrix(m, law)
        i, j = мат.names.index(a), мат.names.index(b)
        return мат.values[i * мат.n + j]

    def test_hook_over_lowercase_is_not_kerned(self):
        m = self.мастер_с_f()
        self.assertLess(self.значение(m, Options.classic().kern_law(), "f", "o"), 0)
        self.assertEqual(self.значение(m, Options().kern_law(), "f", "o"), 0)
        self.assertEqual(self.значение(m, Options().kern_law(), "f.ss01", "o"), 0)
        # прописная над строчной — как прежде
        self.assertEqual(self.значение(m, Options().kern_law(), "T", "o"),
                         self.значение(m, Options.classic().kern_law(), "T", "o"))

    def test_fast_loop_matches_kernel(self):
        m = self.мастер_с_f()
        law = Options().kern_law()
        мат = kerning.make_matrix(m, law)
        grid, рост = kerning.Grid(m.upm), kerning.x_height_of(m)
        формы = {}
        for имя in мат.names:
            i = m.by_name(имя)
            ф = kerning.make_shape(m.glyphs[i].edges, m.advance(i), grid, рост, law)
            коды = m.codes_by_glyph.get(i)
            ф.lower = kerning._lower_letter(m, min(коды) if коды else kerning.MAXCODE, имя)
            формы[имя] = ф
        ctx = kerning.make_context(m, grid, рост, law, lambda i: формы[m.name(i)])
        for a in ("f", "f.ss01", "n", "o", "T", "u"):
            for b in ("o", "n", "u", "x", "f"):
                л, п = формы[a], формы[b]
                вид = kerning.pair_kind(л.kind, п.kind)
                часть = law.part(вид)
                k, _ = kerning.kernel(л, п, часть, law.slopes.index(часть.slope),
                                      kerning.floor_of(вид, ctx.neutral_pocket), law, m.upm, ctx.usual_gap)
                self.assertEqual(мат.values[мат.names.index(a) * мат.n + мат.names.index(b)], k, a + b)
