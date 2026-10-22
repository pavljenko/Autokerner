"""Картинка «было / стало»: строки, набранные двумя файлами шрифта.

    python3 tools/proof.py было.otf стало.otf картинка.png ["строка" ...]

Набор — по cmap, ширинам hmtx и кернингу GPOS (`gpos_kerning.py`), без
подстановок. Рисунок — заливка «чёт-нечет» по ломаным контуров.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fontTools.ttLib import TTFont  # noqa: E402
from PIL import Image, ImageChops, ImageDraw, ImageFont  # noqa: E402

from autokerner import otf  # noqa: E402
from autokerner.geometry import polygons  # noqa: E402
from tools.gpos_kerning import GposKerning  # noqa: E402

СТРОКИ = ["AVATAR To Ty LT «Г» ГОРОД", "Тот УАЗ, ДАЧА. Лёд «ЖЖ»", "Hamburgefonstiv — съешь же ещё",
          "этих мягких французских булок."]


def набрать(путь, строки, кегль, поле=20):
    шрифт = TTFont(путь)
    мастер = otf.load_master(путь)
    кернинг = GposKerning(шрифт)
    cmap = шрифт.getBestCmap()
    масштаб = кегль / мастер.upm
    высота_строки = int(кегль * 1.25)
    ширина = 0
    раскладки = []
    for строка in строки:
        x, прежний, ряд = 0.0, None, []
        for буква in строка:
            имя = cmap.get(ord(буква))
            if имя is None:
                continue
            if прежний is not None:
                x += кернинг.value(прежний, имя)
            ряд.append((имя, x))
            x += мастер.advance(мастер.by_name(имя))
            прежний = имя
        раскладки.append(ряд)
        ширина = max(ширина, int(x * масштаб) + 2 * поле)
    картинка = Image.new("L", (ширина, высота_строки * len(строки) + 2 * поле), 0)
    for номер, ряд in enumerate(раскладки):
        база = поле + int(высота_строки * (номер + 0.8))
        for имя, x in ряд:
            g = мастер.glyphs[мастер.by_name(имя)]
            for полигон in polygons(g.contours):
                маска = Image.new("1", картинка.size, 0)
                точки = [(поле + (x + px) * масштаб, база - py * масштаб) for px, py in полигон]
                if len(точки) > 2:
                    ImageDraw.Draw(маска).polygon(точки, fill=1)
                    слой = Image.new("L", картинка.size, 0)
                    слой.paste(255, mask=маска)
                    картинка = ImageChops.logical_xor(картинка.convert("1"), слой.convert("1")).convert("L")
    return ImageChops.invert(картинка)


def proof(было, стало, выход, строки=None, кегль=64):
    строки = строки or СТРОКИ
    a, b = набрать(было, строки, кегль), набрать(стало, строки, кегль)
    подпись = 28
    лист = Image.new("L", (max(a.width, b.width), a.height + b.height + 2 * подпись), 255)
    рисунок = ImageDraw.Draw(лист)
    try:
        подписи = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 18)
    except OSError:
        подписи = ImageFont.load_default()
    рисунок.text((20, 4), "было: " + os.path.basename(было), fill=0, font=подписи)
    лист.paste(a, (0, подпись))
    рисунок.text((20, a.height + подпись + 4), "стало: выгрузка из FontLab после «Применить»", fill=0,
                 font=подписи)
    лист.paste(b, (0, a.height + 2 * подпись))
    лист.save(выход)
    return выход


if __name__ == "__main__":
    print(proof(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:] or None))
