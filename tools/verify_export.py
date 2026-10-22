"""Сверка шрифта, выгруженного из FontLab после записи, с расчётом.

    python3 tools/verify_export.py исходник.otf выгрузка.otf

Расчёт повторяется по исходнику (fontTools, точки без округления — как
мерит мост FontLab), выгрузка читается как готовый файл: кернинг каждой
пары знаков по правилам OpenType (`gpos_kerning.py`), ширина и сдвиг
рисунка каждого знака. Знаки сопоставляются по коду Юникода: выгрузка
FontLab даёт им «производственные» имена (Iocyrillic → uni0401).
Только для одного мастера.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fontTools.ttLib import TTFont  # noqa: E402

from autokerner import auto, otf  # noqa: E402
from autokerner.geometry import contours_rect  # noqa: E402
from tools.gpos_kerning import GposKerning  # noqa: E402


def verify(source_path, export_path):
    исходник = otf.load_master(source_path)
    исходник.round_shifted = False
    итог = auto.run([исходник])
    файл = TTFont(export_path)
    кернинг = GposKerning(файл)
    выгрузка = otf.load_master(export_path)
    cmap = файл.getBestCmap()
    имя = {}
    for g in исходник.glyphs:
        if g.codes and g.codes[0] in cmap:
            имя[g.name] = cmap[g.codes[0]]
        elif выгрузка.by_name(g.name) is not None:
            имя[g.name] = g.name
    имена = [g.name for g in исходник.glyphs if g.name in имя]
    пары = []
    for л in имена:
        for п in имена:
            надо = итог.kern.value(л, п, 0)
            есть = кернинг.value(имя[л], имя[п])
            if надо != есть:
                пары.append((л, п, надо, есть))
    поля = []
    for g in исходник.glyphs:
        if g.name not in имя:
            continue
        h = выгрузка.glyphs[выгрузка.by_name(имя[g.name])]
        dx, ширина = итог.spacing.get(g.name, {}).get(0, (0, g.advance))
        if 0x20 in g.codes and 0 in итог.space:
            ширина = итог.space[0]
        r0, r1 = contours_rect(g.contours), contours_rect(h.contours)
        if h.advance != ширина:
            поля.append((g.name, "ширина", h.advance, ширина))
        if r0 and r1 and abs(r1[0] - (r0[0] + dx)) > 0.51:
            поля.append((g.name, "сдвиг", round(r1[0] - r0[0], 2), dx))
    print("пар знаков проверено %d, расходится %d %s" % (len(имена) ** 2, len(пары), пары[:6]))
    print("знаков проверено %d из %d, поля расходятся %d %s" % (
        len(имена), len(исходник.glyphs), len(поля), поля[:6]))
    без_пары = [g.name for g in исходник.glyphs if g.name not in имя]
    if без_пары:
        print("не сопоставлены:", без_пары[:20])
    return len(пары) + len(поля)


if __name__ == "__main__":
    sys.exit(1 if verify(sys.argv[1], sys.argv[2]) else 0)
