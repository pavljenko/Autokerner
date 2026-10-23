"""Мастер из готового файла OTF/TTF — через fontTools (проверка вне FontLab).

Статичный файл — один мастер. Контуры — теми же вызовами пера, что видит
исходная программа: она читает файл своим разбором, повторяющим fontTools.
"""

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont

from .geometry import split_contours
from .model import Glyph, Master


def _pen_commands(запись):
    вышло = []
    for вид, точки in запись:
        if вид in ("moveTo", "lineTo"):
            вышло.append((вид, tuple(map(float, точки[0]))))
        elif вид == "curveTo":
            # длинный ряд curveTo fontTools рисует по три точки
            for i in range(0, len(точки), 3):
                вышло.append((вид,) + tuple(tuple(map(float, p)) for p in точки[i:i + 3]))
        elif вид == "qCurveTo":
            вне = [tuple(map(float, p)) for p in точки[:-1]]
            конец = точки[-1]
            вышло.append((вид, вне, tuple(map(float, конец)) if конец is not None else None))
        elif вид in ("closePath", "endPath"):
            вышло.append((вид,))
    return вышло


def load_master(path, weight=None):
    """Мастер из файла. `weight` — число мастера в итоге; по умолчанию вес
    OS/2 (usWeightClass), как в исходной программе"""
    return master_from_font(TTFont(path), str(path), weight)


def master_from_font(шрифт, label="", weight=None):
    """Мастер из открытого `TTFont` (веб-версия читает файл из памяти)"""
    порядок = шрифт.getGlyphOrder()
    набор = шрифт.getGlyphSet()
    cmap = шрифт.getBestCmap() or {}
    коды = {}
    for код, имя in cmap.items():
        коды.setdefault(имя, []).append(код)
    ширины = шрифт["hmtx"].metrics
    составные = {}
    if "glyf" in шрифт:
        glyf = шрифт["glyf"]
        for имя in порядок:
            g = glyf[имя]
            if g.isComposite():
                составные[имя] = [к.glyphName for к in g.components]
    знаки = []
    for имя in порядок:
        перо = DecomposingRecordingPen(набор)
        набор[имя].draw(перо)
        контуры = split_contours(_pen_commands(перо.value))
        знаки.append(Glyph(имя, коды.get(имя, []), ширины[имя][0], контуры, составные.get(имя, [])))
    os2 = шрифт["OS/2"] if "OS/2" in шрифт else None
    рост = капитель = None
    if os2 is not None and os2.version >= 2:
        рост = getattr(os2, "sxHeight", 0) or None
        капитель = getattr(os2, "sCapHeight", 0) or None
    if weight is None:
        weight = float(os2.usWeightClass) if os2 is not None else 400.0
    наклон = float(getattr(шрифт["post"], "italicAngle", 0.0) or 0.0) if "post" in шрифт else 0.0
    return Master(шрифт["head"].unitsPerEm, знаки, рост, капитель, label=label, weight=weight,
                  round_shifted="glyf" not in шрифт, italic_angle=наклон)
