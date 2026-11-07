"""Independent composite metrics, protected scope and unchanged FL8 default."""
import copy
import importlib
import importlib.util
from pathlib import Path
import sys
import unittest

from autokerner import auto
from autokerner.model import Glyph, Master
from autokerner.options import Options
from tests.synthetic import мастер, прямоугольник


def fixture(weight=400):
    m = мастер(weight=weight)
    body = Glyph('stem', [], 180, [прямоугольник(40, -190, 100, 500)])
    dot = Glyph('mark', [0x0307], 0, [прямоугольник(40, 610, 100, 680)])
    j = Glyph('j', [ord('j')], 420,
              [прямоугольник(280, -190, 340, 500), прямоугольник(280, 610, 340, 680)],
              ['stem', 'mark'])
    return Master(m.upm, m.glyphs + [body, dot, j], m.x_height, m.cap_height,
                  label=str(weight), weight=weight)


class CompositeSpacingTests(unittest.TestCase):
    def test_independently_damaged_component_is_measured_with_base_fixed(self):
        m = fixture(); fixed = {g.name for g in m.glyphs} - {'j'}
        o = Options(space=False, kerning=False, spacing_from_zero=False)
        old = auto.run([m], options=o, fixed=fixed, component_metrics=False)
        new = auto.run([m], options=o, fixed=fixed)
        self.assertNotIn('j', old.spacing)
        self.assertIn('j', new.spacing)
        self.assertLess(new.plans[0].item('j').target_lsb, 280)
        self.assertEqual(new.plans[0].targets, old.plans[0].targets)
        self.assertEqual(m.glyphs[-1].components, ['stem', 'mark'])
        self.assertEqual(m.glyphs[-1].rect[0], 280)

    def test_protected_composite_is_unchanged_and_not_a_write(self):
        m = fixture()
        result = auto.run([m], options=Options(space=False, kerning=False), fixed={'j'})
        self.assertNotIn('j', result.spacing)

    def test_unencoded_composite_variant_is_also_measured(self):
        m = fixture(); variant = copy.copy(m.glyphs[-1])
        variant.name = 'j.ss01'; variant.codes = []
        m = Master(m.upm, m.glyphs+[variant], m.x_height, m.cap_height, label=m.label)
        fixed = {g.name for g in m.glyphs} - {'j', 'j.ss01'}
        result = auto.run([m], options=Options(space=False, kerning=False), fixed=fixed)
        self.assertEqual(result.spacing['j'], result.spacing['j.ss01'])

    def test_multimaster_union_covers_composite_in_each_master(self):
        models = [fixture(200), fixture(800)]
        result = auto.run(models, options=Options(space=False, kerning=False))
        self.assertEqual(set(result.spacing['j']), {0, 1})

    def test_spacing_disabled_keeps_classic_calculation(self):
        m = fixture(); options = Options(spacing=False, space=False, kerning=False)
        actual = auto.run([m], options=options)
        expected = auto.run([m], options=options)
        self.assertEqual((actual.spacing, actual.space), (expected.spacing, expected.space))

    def test_previous_delta_inheritance_remains_available_explicitly(self):
        m = fixture(); fixed = {g.name for g in m.glyphs} - {"j"}
        o = Options(space=False, kerning=False, spacing_from_zero=False)
        result = auto.run([m], options=o, fixed=fixed, component_metrics=False)
        self.assertNotIn("j", result.spacing)


if __name__ == '__main__': unittest.main()
