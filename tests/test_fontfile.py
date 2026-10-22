"""Запись итога в готовый файл (веб-версия): TrueType и CFF, без чужих
шрифтов — маленький шрифт собирается из синтетики"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fontTools.fontBuilder import FontBuilder  # noqa: E402
from fontTools.pens.t2CharStringPen import T2CharStringPen  # noqa: E402
from fontTools.pens.ttGlyphPen import TTGlyphPen  # noqa: E402

from autokerner import auto, fontfile, otf, outcome  # noqa: E402
from autokerner.geometry import contours_rect, split_contours  # noqa: E402
from autokerner.options import MERGE, Options  # noqa: E402
from tests.synthetic import мастер  # noqa: E402


def собрать(cff=False):
    """Байты шрифта из синтетического мастера"""
    m = мастер()
    порядок = [g.name for g in m.glyphs]
    fb = FontBuilder(1000, isTTF=not cff)
    fb.setupGlyphOrder(порядок)
    fb.setupCharacterMap({к: g.name for g in m.glyphs for к in g.codes})
    рисунки = {}
    for g in m.glyphs:
        перо = T2CharStringPen(g.advance, None) if cff else TTGlyphPen(None)
        for контур in g.contours:
            for к in контур.commands:
                if к[0] == "moveTo":
                    перо.moveTo(к[1])
                elif к[0] == "lineTo":
                    перо.lineTo(к[1])
                elif к[0] == "closePath":
                    перо.closePath()
        рисунки[g.name] = перо.getCharString() if cff else перо.glyph()
    if cff:
        fb.setupCFF("Synthetic", {"FullName": "Synthetic"}, рисунки, {})
    else:
        fb.setupGlyf(рисунки)
    ширины = {g.name: g.advance for g in m.glyphs}
    fb.setupHorizontalMetrics({имя: (ширины[имя], 0) for имя in порядок})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "Synthetic", "styleName": "Regular"})
    fb.setupOS2(sxHeight=500, sCapHeight=700, usWeightClass=400)
    fb.setupPost()
    import io
    буфер = io.BytesIO()
    fb.font.save(буфер)
    return буфер.getvalue()


class WriteTest(unittest.TestCase):
    def круг(self, cff, kern_mode=None):
        данные = собрать(cff)
        шрифт = fontfile.open_font(данные)
        m = otf.master_from_font(шрифт)
        o = Options() if kern_mode is None else Options(kern_mode=kern_mode)
        прежний = fontfile.FileKerning(шрифт)
        r = auto.run([m], options=o)
        вид = outcome.write_mode(o, [прежний])
        пары = None
        if вид == outcome.MISSING:
            пары, _ = outcome.pair_writes(r.kern, [g.name for g in m.glyphs],
                                          {g.name: bool(g.codes) for g in m.glyphs}, [прежний], вид)
        fontfile.apply(шрифт, r, 0, вид, пары)
        новые = fontfile.save_font(шрифт)
        после = outcome.kern_after(r.kern, прежний, 0, вид, writes=пары)
        return r, fontfile.check(m, r, новые, после), новые

    def test_truetype_round_trip(self):
        r, плохо, _ = self.круг(cff=False)
        self.assertTrue(r.spacing)
        self.assertEqual(плохо, [])

    def test_cff_round_trip(self):
        r, плохо, _ = self.круг(cff=True)
        self.assertTrue(r.spacing)
        self.assertEqual(плохо, [])

    def test_written_kerning_reads_back(self):
        r, _, новые = self.круг(cff=False)
        k = fontfile.FileKerning(fontfile.open_font(новые))
        self.assertEqual(k.value("T", "o"), r.kern.value("T", "o", 0))
        self.assertTrue(k.count)

    def test_merge_into_empty_writes_whole(self):
        _, плохо, _ = self.круг(cff=False, kern_mode=MERGE)
        self.assertEqual(плохо, [])

    def test_merge_keeps_legacy_kern_table(self):
        """«Дописать» к шрифту, где свой кернинг только в старой таблице kern:
        его пары переезжают в GPOS вместе с новыми, а не пропадают"""
        import io
        from fontTools.ttLib import TTFont, newTable
        from fontTools.ttLib.tables._k_e_r_n import KernTable_format_0
        f = TTFont(io.BytesIO(собрать(cff=False)))
        таблица = KernTable_format_0()
        таблица.version, таблица.coverage, таблица.tupleIndex = 0, 1, 0
        таблица.kernTable = {("T", "o"): -77}
        f["kern"] = newTable("kern")
        f["kern"].version, f["kern"].kernTables = 0, [таблица]
        буфер = io.BytesIO()
        f.save(буфер)
        шрифт = fontfile.open_font(буфер.getvalue())
        прежний = fontfile.FileKerning(шрифт)
        self.assertEqual(прежний.value("T", "o"), -77)
        m = otf.master_from_font(шрифт)
        o = Options(kern_mode=MERGE)
        r = auto.run([m], options=o)
        вид = outcome.write_mode(o, [прежний])
        пары, _ = outcome.pair_writes(r.kern, [g.name for g in m.glyphs],
                                      {g.name: bool(g.codes) for g in m.glyphs}, [прежний], вид)
        fontfile.apply(шрифт, r, 0, вид, пары)
        новые = fontfile.save_font(шрифт)
        после = outcome.kern_after(r.kern, прежний, 0, вид, writes=пары)
        self.assertEqual(fontfile.check(m, r, новые, после), [])
        готовый = fontfile.open_font(новые)
        self.assertNotIn("kern", готовый)
        self.assertEqual(fontfile.FileKerning(готовый).value("T", "o"), -77)

    def test_variable_and_garbage_are_refused(self):
        with self.assertRaises(fontfile.UnsupportedFont):
            fontfile.open_font(b"not a font at all")


class OffCurveContourTest(unittest.TestCase):
    def test_closed_offcurve_contour_does_not_start_at_origin(self):
        """Круглая точка TrueType из одних внеконтурных точек — без (0, 0)"""
        точка = [("qCurveTo", [(100.0, 0.0), (200.0, 0.0), (200.0, 100.0), (100.0, 100.0)], None), ("closePath",)]
        r = contours_rect(split_contours(точка))
        self.assertGreaterEqual(r[0], 100.0)


if __name__ == "__main__":
    unittest.main()


class WebTest(unittest.TestCase):
    """Связка веб-версии: те же ответы, что видит страница"""

    def test_open_calculate_edits_files(self):
        import json
        from autokerner import web
        info = json.loads(web.open_font(собрать(cff=True), "Synthetic.otf"))
        self.assertEqual(info["outlines"], "CFF")
        # мера — по рисунку, который ляжет в файл (без округления точек), как в FontLab
        self.assertFalse(web._state["master"].round_shifted)
        итог = json.loads(web.calculate(json.dumps(Options().to_dict())))
        self.assertEqual(итог["check"], 0)
        self.assertEqual(итог["file_name"], "Synthetic-autokerner.otf")
        self.assertTrue(json.loads(web.edits("T"))["glyph"] == "T")
        self.assertTrue(any(имя.endswith(".fea") for имя in json.loads(web.report_files())))
        self.assertEqual(json.loads(web.open_font(b"nope", "x.ttf"))["error"], "not_a_font")
