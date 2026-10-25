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
        до_нормы = Options(kerning=False, space_edge=False, spacing_density=0)
        self.assertEqual(auto.run(m, options=до_нормы).space, auto.run(m, kern=False).space)
        # с общей плотностью строчные уже — и цель пробела меньше, от их новых ширин
        плотно = auto.run(m, options=Options(kerning=False, space_edge=False)).space[0]
        self.assertLess(плотно, auto.run(m, kern=False).space[0])
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

    def test_heights_by_letters(self):
        from autokerner.model import Glyph, Master
        from autokerner.spacing import heights
        from tests.synthetic import прямоугольник
        m = мастер()
        # «x» с росчерками вверх и вниз: габарит больше роста строчных
        знаки = [g for g in m.glyphs if g.name != "x"] + [
            Glyph("x", [0x78], 480, [прямоугольник(30, -150, 450, 700)]),
            Glyph("z", [0x7A], 480, [прямоугольник(30, 0, 450, 500)]),
            Glyph("v", [0x76], 480, [прямоугольник(30, 0, 450, 500)])]
        m = Master(1000, знаки, x_height=500, cap_height=700, label="росчерки")
        self.assertEqual(heights(m)[2], 850)
        self.assertEqual(heights(m, True)[2], 500)
        self.assertFalse(Options.classic().spacing_rule().robust_heights)

    def test_punctuation_edge_at_mid_protrusion(self):
        from autokerner.model import Glyph, Master
        from autokerner.spacing import SpacingRule, _protruding_sides, stem_sides
        from tests.synthetic import прямоугольник
        m = мастер()
        дуга = Glyph("n", [0x6E], 500, [прямоугольник(150, 0, 230, 500), прямоугольник(20, 330, 150, 360),
                                         прямоугольник(370, 0, 450, 500)])
        засечки = Glyph("H", [0x48], 640, [прямоугольник(160, 0, 240, 700), прямоугольник(60, 0, 340, 30),
                                            прямоугольник(400, 0, 480, 700)])
        m = Master(1000, [g for g in m.glyphs if g.name not in ("n", "H")] + [дуга, засечки], x_height=500,
                   cap_height=700, label="выступы")
        rule = SpacingRule(soft=True)
        i = m.glyph(0x6E)
        # выступ на 70 % высоты дальше засечки — краем считается он
        self.assertEqual(_protruding_sides(m, i, stem_sides(m, i, 250), 500, rule)[0], 20)
        # длинная засечка у базовой линии — штамб остаётся краем
        i = m.glyph(0x48)
        поля = stem_sides(m, i, 350)
        self.assertEqual(_protruding_sides(m, i, поля, 700, rule), поля)

    def test_classic_keeps_hard_rule(self):
        self.assertFalse(Options.classic().spacing_rule().soft)
        self.assertTrue(Options().spacing_rule().soft)


class ItalicTest(unittest.TestCase):
    """Курсив вдоль наклона (`deskewed`) и рукописное строение (`cursive_of`)"""

    def test_slanted_stem_is_straight_after_deskew(self):
        import math
        from autokerner.geometry import Contour, deskewed, ink_profile, slant_of
        from autokerner.model import Glyph
        self.assertEqual(slant_of(0), 0.0)
        t = slant_of(-12)
        self.assertAlmostEqual(t, math.tan(math.radians(12)))
        штамб = Contour([("moveTo", (100, 0)), ("lineTo", (180, 0)), ("lineTo", (180 + 500 * t, 500)),
                         ("lineTo", (100 + 500 * t, 500)), ("closePath",)])
        профиль = ink_profile(Glyph("l", [], 300, [штамб]).edges, 0, 500, 1000 / 256)
        левые = [x for x in deskewed(профиль, t).left if x is not None]
        self.assertLess(max(левые) - min(левые), 1.0)
        self.assertGreater(max(профиль.left) - min(профиль.left), 90)

    def знак_со_входом(self, имя, код, засечка_внизу=False):
        from autokerner.model import Glyph
        from tests.synthetic import прямоугольник
        # штамб и вход-крючок вверху слева, на 110 дальше штамба
        контуры = [прямоугольник(150, 0, 230, 500), прямоугольник(40, 380, 150, 420),
                   прямоугольник(370, 0, 450, 500)]
        if засечка_внизу:
            контуры.append(прямоугольник(40, 0, 150, 40))
        return Glyph(имя, [код], 500, контуры)

    def мастер(self, засечка_внизу=False):
        from autokerner.model import Master
        m = мастер()
        буквы = {ord(ch): ch for ch in "nmuirp"}
        свои = [g for g in m.glyphs if not set(g.codes) & set(буквы)]
        return Master(1000, свои + [self.знак_со_входом(ch, к, засечка_внизу) for к, ch in буквы.items()],
                      x_height=500, cap_height=700, label="вход")

    def test_cursive_structure(self):
        from autokerner.spacing import cursive_of
        self.assertTrue(cursive_of(self.мастер(), 500, 1000 / 256))
        # выступ и вверху, и внизу — засечки прямого шрифта
        self.assertFalse(cursive_of(self.мастер(засечка_внизу=True), 500, 1000 / 256))
        self.assertFalse(cursive_of(мастер(), 500, 1000 / 256))

    def test_white_behind_entry_counts_from_body(self):
        from autokerner.geometry import ink_profile
        from autokerner.spacing import SpacingRule, white_soft
        from tests.synthetic import прямоугольник
        from autokerner.model import Glyph
        rule = SpacingRule(soft=True, cursive=True)
        n = self.знак_со_входом("n", 0x6E)
        профиль = ink_profile(n.edges, 0, 500, 1000 / 256)
        без, со = white_soft(профиль, 500.0, rule, 1000), white_soft(профиль, 500.0, rule, 1000, True)
        self.assertGreater(со[0], без[0])
        self.assertEqual(со[1], без[1])
        штамб = ink_profile(Glyph("l", [], 300, [прямоугольник(100, 0, 180, 500)]).edges, 0, 500, 1000 / 256)
        self.assertEqual(white_soft(штамб, 300.0, rule, 1000), white_soft(штамб, 300.0, rule, 1000, True))

    def test_options(self):
        self.assertTrue(Options().spacing_rule().cursive)
        self.assertTrue(Options().spacing_rule().slant)
        self.assertFalse(Options.classic().spacing_rule().cursive)
        self.assertFalse(Options.classic().spacing_rule().slant)


class LowerOverhangTest(unittest.TestCase):
    """Хвостик строчной над строчной кармана не образует (задача #3)"""

    def мастер_с_f(self):
        from autokerner.model import Glyph, Master
        from tests.synthetic import прямоугольник
        m = мастер()
        f = Glyph("f", [0x66], 380, [прямоугольник(60, 0, 140, 760), прямоугольник(60, 700, 360, 760),
                                      прямоугольник(20, 440, 170, 500)])
        f_alt = Glyph("f.ss01", [], 380, list(f.contours))
        # «д» с завитком влево высоко над соседкой
        d = Glyph("d", [0x64], 480, [прямоугольник(60, 0, 420, 500), прямоугольник(-200, 760, 300, 820),
                                      прямоугольник(260, 500, 320, 820)])
        return Master(1000, list(m.glyphs) + [f, f_alt, d], x_height=500, cap_height=700, label="с f")

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

    def test_letters_collide_above_the_line_without_push(self):
        m = self.мастер_с_f()
        # завитки двух «d» сходятся выше строки: исходное правило раздвигает, поправка — нет
        self.assertGreater(self.значение(m, Options.classic().kern_law(), "d", "d"), 0)
        self.assertEqual(self.значение(m, Options().kern_law(), "d", "d"), 0)

    def test_curl_of_right_letter_over_lowercase_is_not_kerned(self):
        m = self.мастер_с_f()
        self.assertLess(self.значение(m, Options.classic().kern_law(), "u", "d"), 0)
        self.assertEqual(self.значение(m, Options().kern_law(), "u", "d"), 0)

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
            код = min(коды) if коды else kerning.MAXCODE
            ф.lower = kerning._lower_letter(m, код, имя)
            регистр = kerning._letter_case(m, код, имя)
            if регистр is not None:
                _, кап, рост_ = kerning.heights(m, True)
                ф.body_lo = kerning._row(grid, -kerning.BODY_MARGIN * m.upm)
                ф.body_hi = kerning._row(grid, (рост_ if регистр == "lower" else кап) + kerning.BODY_MARGIN * m.upm)
            формы[имя] = ф
        ctx = kerning.make_context(m, grid, рост, law, lambda i: формы[m.name(i)])
        for a in ("f", "f.ss01", "n", "o", "T", "u", "d"):
            for b in ("o", "n", "u", "x", "f", "d"):
                л, п = формы[a], формы[b]
                вид = kerning.pair_kind(л.kind, п.kind)
                часть = law.part(вид)
                k, _ = kerning.kernel(л, п, часть, law.slopes.index(часть.slope),
                                      kerning.floor_of(вид, ctx.neutral_pocket), law, m.upm, ctx.usual_gap)
                self.assertEqual(мат.values[мат.names.index(a) * мат.n + мат.names.index(b)], k, a + b)


def с_цифрами(жир=80, широкие=True):
    """Синтетика с десятью цифрами: разной ширины (пропорциональные) или одной"""
    from autokerner.model import Glyph, Master
    from tests.synthetic import прямоугольник
    м = мастер(жир=жир)
    знаки = [g for g in м.glyphs if g.name not in ("one", "two")]
    for к in range(10):
        ширина = (420 + 30 * к) if широкие else 560
        x0 = 60 + 4 * к
        if к == 7:
            # «7» с перекладиной поверху: карман снизу, пары с ней кернятся
            контуры = [прямоугольник(x0, 620, ширина - 60, 700),
                       прямоугольник((x0 + ширина - 60) / 2 - 40, 0, (x0 + ширина - 60) / 2 + 40, 700)]
        else:
            # «4» ниже остальных: уходит под перекладину «7»
            контуры = [прямоугольник(x0, 0, ширина - 60, 500 if к == 4 else 700)]
        знаки.append(Glyph("d%d" % к, [0x30 + к], ширина, контуры))
    знаки.append(Glyph("hyphen", [0x2D], 330, [прямоугольник(40, 230, 290, 300)]))
    return Master(1000, знаки, x_height=500, cap_height=700, label="цифры", weight=400.0)


class DensityTest(unittest.TestCase):
    """Общая плотность окна: −10 % разом у всех знаков группы, без порога"""

    def test_every_letter_moves_alike(self):
        m = [мастер(жир=80)]
        ровно = auto.run(m, options=Options(kerning=False, spacing_density=0)).plans[0]
        плотно = auto.run(m, options=Options(kerning=False)).plans[0]
        сдвиги = set()
        for имя in ("n", "u", "o", "x"):
            а, б = ровно.item(имя), плотно.item(имя)
            # выравнивание то же, что без плотности (только за порогом)
            правка = (а.delta_left, а.delta_right) if а.shift >= ровно.threshold_units else (0, 0)
            сдвиги.add((б.delta_left - правка[0], б.delta_right - правка[1]))
            self.assertTrue(б.applied(плотно.threshold_units))
        # сдвиг плотности один на группу: −10 % белого на строку
        self.assertEqual(len(сдвиги), 1)
        dl, dr = сдвиги.pop()
        self.assertLess(dl, 0)
        self.assertEqual(dl, dr)

    def test_classic_rule_untouched(self):
        self.assertEqual(Options.classic().total_looseness(), 0.0)
        self.assertAlmostEqual(Options().total_looseness(), -0.1)
        self.assertAlmostEqual(Options(looseness=10).total_looseness(), -0.01)

    def test_punctuation_follows_letters(self):
        m = [мастер(жир=80)]
        ровно = auto.run(m, options=Options(kerning=False, spacing_density=0)).plans[0].item("period")
        плотно = auto.run(m, options=Options(kerning=False)).plans[0].item("period")
        self.assertLess(плотно.target_lsb + плотно.target_rsb, ровно.target_lsb + ровно.target_rsb)


class FiguresTest(unittest.TestCase):
    def test_proportional_figures_spaced_tabular_not(self):
        r = auto.run([с_цифрами()], options=Options(kerning=False)).plans[0]
        self.assertIsNotNone(r.item("d1"))
        r = auto.run([с_цифрами(широкие=False)], options=Options(kerning=False)).plans[0]
        self.assertIsNone(r.item("d1"))
        r = auto.run([с_цифрами()], options=Options.classic(kerning=False)).plans[0]
        self.assertIsNone(r.item("d1"))

    def test_figure_pairs_kerned_only_when_proportional(self):
        from autokerner.kerning import make_matrix
        закон = Options().kern_law()
        for широкие, есть in ((True, True), (False, False)):
            м = с_цифрами(широкие=широкие)
            мат = make_matrix(м, закон)
            цифры = [i for i, имя in enumerate(мат.names) if имя.startswith("d")]
            n = len(мат.names)
            ненулевых = sum(1 for a in цифры for b in цифры if мат.values[a * n + b])
            self.assertEqual(ненулевых > 0, есть)


class EnclosureTest(unittest.TestCase):
    def test_hyphen_not_clamped_in_fork(self):
        from autokerner.kerning import ENCLOSURE_GAP, Grid, KernShape, make_shape, stop_enclosure, _row
        from autokerner.geometry import Contour
        from autokerner.model import Glyph, Master

        def ломаная(*точки):
            return Contour([("moveTo", точки[0])] + [("lineTo", p) for p in точки[1:]] + [("closePath",)])
        # «k» с развилкой справа: плечо вверху, нога внизу, середина пуста
        k = Glyph("k", [0x6B], 520, [ломаная((40, 0), (120, 0), (120, 700), (40, 700)),
                                     ломаная((120, 230), (480, 500), (400, 500), (120, 290)),
                                     ломаная((120, 210), (400, 0), (480, 0), (120, 270))])
        дефис = Glyph("hyphen", [0x2D], 330, [ломаная((40, 230), (290, 230), (290, 300), (40, 300))])
        м = Master(1000, [k, дефис], x_height=500, cap_height=700, label="охват", weight=400.0)
        закон = Options().kern_law()
        grid = Grid(1000)
        ф = [make_shape(g.edges, g.advance, grid, 500, закон) for g in м.glyphs]
        значения = [0, -200, 0, 0]       # k|hyphen задвинут глубоко в развилку
        запасы = [32767] * 4
        stop_enclosure(значения, запасы, 2, ф, _row(grid, 0), _row(grid, 700), 1000, 10)
        self.assertGreater(значения[1], -200)
        self.assertLessEqual(значения[1], 0)
        # граница точная: ещё на 1 % плотнее — и дефис был бы зажат
        self.assertLess(значения[1], 0)


class PerSideTest(unittest.TestCase):
    def test_only_the_side_that_stands_out_moves(self):
        """Выбилась одна сторона — правится она, вторая стоит, как у дизайнера"""
        from autokerner.model import Glyph, Master
        from tests.synthetic import прямоугольник
        м = мастер(жир=80)
        # левое поле n на 60 шире, правое как было: правило двигает правое на 10
        n = Glyph("n", [0x6E], 560, [прямоугольник(110, 0, 190, 500), прямоугольник(430, 0, 510, 500),
                                     прямоугольник(110, 420, 510, 500)])
        м2 = Master(1000, [g if g.name != "n" else n for g in м.glyphs], x_height=500, cap_height=700,
                    label="n сдвинута", weight=400.0)
        по_сторонам = auto.run([м2], options=Options(kerning=False, spacing_density=0,
                                                      spacing_per_side=True)).plans[0].item("n")
        целиком = auto.run([м2], options=Options(kerning=False, spacing_density=0,
                                                  spacing_per_side=False)).plans[0].item("n")
        self.assertEqual(по_сторонам.delta_left, целиком.delta_left)
        self.assertLess(по_сторонам.delta_left, -12)
        self.assertEqual(целиком.delta_right, 10)
        self.assertEqual(по_сторонам.delta_right, 0)


class BelowCutTest(unittest.TestCase):
    def test_hook_under_neighbour_makes_no_pocket(self):
        """Крючок «j», ушедший далеко влево под соседа, кармана не образует"""
        from autokerner.geometry import Contour
        from autokerner.kerning import make_matrix
        from autokerner.model import Glyph, Master
        from tests.synthetic import прямоугольник

        def ломаная(*точки):
            return Contour([("moveTo", точки[0])] + [("lineTo", p) for p in точки[1:]] + [("closePath",)])
        n = Glyph("n", [0x6E], 500, [прямоугольник(50, 0, 130, 500), прямоугольник(370, 0, 450, 500),
                                     прямоугольник(50, 420, 450, 500)])
        # j: штамб и крючок под строкой, уходящий влево на 160 за штамб
        j = Glyph("j", [0x6A], 230, [прямоугольник(100, -150, 180, 500), прямоугольник(-60, -230, 180, -150)])
        м = Master(1000, [n, j], x_height=500, cap_height=700, label="nj", weight=400.0)
        for cut, есть in ((False, True), (True, False)):
            мат = make_matrix(м, Options(kern_below_cut=cut).kern_law())
            i, k = мат.names.index("n"), мат.names.index("j")
            self.assertEqual(мат.values[i * мат.n + k] < 0, есть)
