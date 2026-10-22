"""Сверка с расчётом исходной программы.

    python3 tools/compare_reference.py шрифт.otf авторасчёт.json
    python3 tools/compare_reference.py папка-срезов авторасчёт.json

Вариативный шрифт исходная программа меряет по срезам весов (`срезы/100.otf` …
рядом с `авторасчёт.json`): папка срезов — это мастера, вес — имя файла.

Эталон — `авторасчёт.json`, который пишет исходная программа. Печатает, что
разошлось: поля знаков, пробел, классы, ячейки и пары кернинга.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from autokerner import auto, otf  # noqa: E402


def _pairs(ряд):
    return {ряд[i]: ряд[i + 1] for i in range(0, len(ряд), 2)}


def compare(font_path, json_path, verbose=True):
    эталон = json.load(open(json_path))
    if os.path.isdir(font_path):
        срезы = sorted((float(os.path.splitext(ф)[0]), ф) for ф in os.listdir(font_path)
                       if ф.endswith((".otf", ".ttf")))
        мастера = [otf.load_master(os.path.join(font_path, ф), weight=вес) for вес, ф in срезы]
    else:
        мастера = [otf.load_master(font_path)]
    t = time.time()
    итог = auto.run(мастера).to_json()
    прошло = time.time() - t
    расхождений = 0

    def сказать(*слова):
        if verbose:
            print(*слова)

    # поля
    э = {имя: _pairs(ряд) for имя, ряд in эталон["spacing"].items()}
    м = {имя: _pairs(ряд) for имя, ряд in итог["spacing"].items()}
    for имя in sorted(set(э) | set(м)):
        a, b = э.get(имя), м.get(имя)
        if a is None or b is None:
            расхождений += 1
            сказать("поля: знак", имя, "только в", "эталоне" if b is None else "нашем", a or b)
            continue
        for вес in set(a) | set(b):
            if a.get(вес) != b.get(вес):
                расхождений += 1
                сказать("поля:", имя, вес, "эталон", a.get(вес), "наш", b.get(вес))
    if _pairs(эталон["space"]) != _pairs(итог["space"]):
        расхождений += 1
        сказать("пробел: эталон", эталон["space"], "наш", итог["space"])
    # кернинг
    эк, мк = эталон["kern"], итог["kern"]
    for ключ in ("precision", "truncated", "weights"):
        if эк[ключ] != мк[ключ]:
            расхождений += 1
            сказать("кернинг:", ключ, "эталон", эк[ключ], "наш", мк[ключ])
    for ключ in ("leftClass", "rightClass", "cells", "pairs"):
        a, b = эк[ключ], мк[ключ]
        разные = [к for к in set(a) | set(b) if a.get(к) != b.get(к)]
        if разные:
            расхождений += len(разные)
            сказать("кернинг: %s — расходится %d из %d/%d" % (ключ, len(разные), len(a), len(b)))
            for к in sorted(разные)[:12]:
                сказать("   ", к, "эталон", a.get(к), "наш", b.get(к))
    сказать("%s: знаков с полями %d (эталон %d), пар %d (эталон %d), ячеек %d (эталон %d), "
            "расхождений %d, расчёт %.1f с" % (
                os.path.basename(font_path), len(м), len(э), len(мк["pairs"]), len(эк["pairs"]),
                len(мк["cells"]), len(эк["cells"]), расхождений, прошло))
    return расхождений


if __name__ == "__main__":
    sys.exit(1 if compare(sys.argv[1], sys.argv[2]) else 0)
