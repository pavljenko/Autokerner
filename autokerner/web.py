"""Веб-версия: расчёт для страницы в браузере (Pyodide).

Шрифт приходит байтами и никуда не уходит; итог — новый файл шрифта,
сводка, правки и файлы отчёта. Правило и числа те же, что в окне FontLab:
`auto.run` по одному мастеру, запись — `fontfile`. Ответы — JSON-строки,
чтобы страница читала их без обёрток Pyodide.
"""

import json

from . import __version__, auto, export, fontfile, otf, outcome, report
from .options import Options

_state = {}

# Сколько знаков с кодом сверять попарно после записи: дальше — только
# латиница, кириллица и знаки препинания (на две тысячи знаков проверка
# шла бы минуту)
CHECK_LIMIT = 700


def _dumps(x):
    return json.dumps(x, ensure_ascii=False)


def _name_record(шрифт, *ids):
    if "name" not in шрифт:
        return ""
    for i in ids:
        запись = шрифт["name"].getDebugName(i)
        if запись:
            return запись
    return ""


def open_font(data, file_name=""):
    """Прочитать шрифт. Ответ — сведения о нём или {"error": причина}"""
    _state.clear()
    data = data.to_bytes() if hasattr(data, "to_bytes") else bytes(data)
    try:
        шрифт = fontfile.open_font(data)
    except fontfile.UnsupportedFont as отказ:
        return _dumps({"error": отказ.reason})
    мастер = otf.master_from_font(шрифт, file_name)
    # запись сдвигает рисунок CFF точно, без округления точек (в отличие от
    # исходной программы) — и мерить надо то, что ляжет в файл, как мерит FontLab
    мастер.round_shifted = False
    прежний = fontfile.FileKerning(шрифт)
    _state.update(data=data, file_name=file_name, master=мастер, old=прежний,
                  flavor=шрифт.flavor, cff="CFF " in шрифт)
    return _dumps({
        "family": _name_record(шрифт, 16, 1),
        "style": _name_record(шрифт, 17, 2),
        "glyphs": len(мастер.glyphs),
        "coded": sum(1 for g in мастер.glyphs if g.codes),
        "upm": мастер.upm,
        "outlines": "CFF" if "CFF " in шрифт else "TrueType",
        "flavor": шрифт.flavor or "",
        "kern_pairs": прежний.count,
        "kern_classes": прежний.classes,
        "version": __version__,
    })


def _check_names(мастер):
    коды = [(min(g.codes), g.name) for g in мастер.glyphs if g.codes]
    if len(коды) > CHECK_LIMIT:
        коды = [к for к in коды if к[0] < 0x0530 or 0x2000 <= к[0] < 0x2070]
    return [имя for _, имя in sorted(коды)[:CHECK_LIMIT]]


def calculate(options_json, progress=None):
    """Посчитать, записать новый файл, сверить. Ответ — сводка"""
    мастер, прежний = _state["master"], _state["old"]
    o = Options.from_dict(json.loads(options_json))
    # в файле нет выделения, формул метрик и цветных меток FontLab
    o.glyphs, o.keep_marked, o.keep_metric_keys, o.masters = "all", False, False, None
    say = progress or (lambda текст: None)
    итог = auto.run([мастер], options=o, progress=say)
    вид = outcome.write_mode(o, [прежний]) if итог.kern is not None else None
    пары, усечено = None, 0
    if вид == outcome.MISSING:
        имена = [g.name for g in мастер.glyphs]
        скодом = {g.name: bool(g.codes) for g in мастер.glyphs}
        say("кернинг: подбираю пары")
        пары, усечено = outcome.pair_writes(итог.kern, имена, скодом, [прежний], вид, o.kern_limit or None)
    say("запись")
    шрифт = fontfile.open_font(_state["data"])
    fontfile.apply(шрифт, итог, 0, вид, пары)
    новый = fontfile.save_font(шрифт)
    if итог.kern is not None:
        после = outcome.kern_after(итог.kern, прежний, 0, вид, writes=пары)
    else:
        после = прежний.value
    say("сверка")
    плохо = fontfile.check(мастер, итог, новый, после, names=_check_names(мастер))
    отчёт = report.build([мастер], итог, [прежний], top=25, after=lambda w: после)
    _state.update(result=итог, new=новый, after=после, mode=вид, pairs=пары, report=отчёт)

    k = итог.kern
    кернинг = None
    if k is not None:
        записано = len(пары) if пары is not None else sum(1 for v in k.cells.values() if v[0]) + len(k.pairs)
        кернинг = {
            "before": прежний.count, "before_classes": прежний.classes,
            "mode": "add" if вид == outcome.MISSING else "replace",
            "left": len(k.left_members), "right": len(k.right_members),
            "cells": sum(1 for v in k.cells.values() if v[0]), "pairs": len(k.pairs),
            "written": записано, "truncated": bool(k.truncated or усечено),
            "size": outcome.size_estimate(k, вид, пары),
        }
    m = мастер
    изменены = sorted({chr(к) for имя in итог.spacing for к in m.glyphs[m.by_name(имя)].codes
                       if m.by_name(имя) is not None and к >= 0x20})
    return _dumps({
        "spacing": {"changed": len(итог.spacing), "of": len(m.glyphs)} if o.spacing else None,
        "space": [отчёт.space[0][1], отчёт.space[0][2]] if отчёт.space else None,
        "space_on": bool(o.space),
        "kerning": кернинг,
        "control": [[текст, ряд[0][0], ряд[0][1]] for текст, ряд in отчёт.control],
        "collisions": [[л, з, п, г] for л, з, п, г in итог.collisions[:8]],
        "check": len(плохо),
        "check_first": [[вид_, что, есть, надо] for вид_, что, есть, надо in плохо[:3]],
        "changed_chars": "".join(изменены),
        "new_size": len(новый),
        "file_name": out_name(),
    })


def out_name():
    имя = _state.get("file_name") or "font.ttf"
    основа, точка, расширение = имя.rpartition(".")
    if not точка:
        основа, расширение = имя, ("otf" if _state.get("cff") else "ttf")
    return "%s-autokerner.%s" % (основа, расширение)


def new_font():
    """Байты нового файла"""
    return _state["new"]


def _glyph_of(запрос):
    m = _state["master"]
    if m.by_name(запрос) is not None:
        return запрос
    if len(запрос) == 1 and m.glyph(ord(запрос)) is not None:
        return m.name(m.glyph(ord(запрос)))
    return None


def _char_of(имя):
    m = _state["master"]
    i = m.by_name(имя)
    if i is None or not m.glyphs[i].codes:
        return ""
    к = m.glyphs[i].codes[0]
    return chr(к) if к >= 0x20 else ""


def edits(query=""):
    """Правки: поля знаков и пары кернинга — крупнейшие или одного знака"""
    m, отчёт = _state["master"], _state["report"]
    знак = _glyph_of(query.strip()) if query.strip() else None
    поля = [п for п in отчёт.spacing if знак is None or п.name == знак][:400]
    имена = [g.name for g in m.glyphs if g.codes]
    пары = []
    if _state["result"].kern is not None:
        пары = outcome.changed_pairs(имена, _state["old"].value, _state["after"], top=300, glyph=знак)
    return _dumps({
        "glyph": знак,
        "not_found": bool(query.strip()) and знак is None,
        "spacing_total": len(отчёт.spacing),
        "spacing": [[_char_of(п.name), п.name, п.lsb, п.new_lsb, п.rsb, п.new_rsb, п.advance, п.new_advance]
                    for п in поля],
        "pairs": [[_char_of(л) + _char_of(п), л, п, было, стало] for л, п, было, стало in пары],
    })


def report_files():
    """Файлы отчёта: кернинг в синтаксисе фич и правки полей таблицей"""
    итог, отчёт = _state["result"], _state["report"]
    основа = out_name().rpartition(".")[0]
    файлы = {}
    if итог.kern is not None:
        файлы[основа + "-kern.fea"] = export.kerning_fea(итог.kern, 0, _state["file_name"], _state["pairs"])
    if отчёт.spacing:
        файлы[основа + "-spacing.csv"] = export.spacing_csv(отчёт)
    return _dumps(файлы)
