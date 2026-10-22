"""«Сохранить в файл»: итог расчёта — таблицей полей (CSV) и кернингом в
синтаксисе фич OpenType (.fea, по файлу на мастер). Без FontLab.

Таблица открывается в Excel / Numbers / Google Таблицах; .fea можно
вставить в панель Features другого шрифта или прочесть глазами.
"""

import csv
import io
import os
import re

from .kerning import class_names

_SAFE = re.compile(r"[^0-9A-Za-zА-Яа-яЁё._-]+")


def safe_name(text):
    """Имя для файла: без косых, двоеточий и прочего, что ломает путь"""
    return _SAFE.sub("_", text).strip("._") or "font"


def spacing_csv(report):
    """Правки полей (`report.Report.spacing`) — CSV с разделителем «;»
    (так его без вопросов открывает русский Excel)"""
    буфер = io.StringIO()
    w = csv.writer(буфер, delimiter=";", lineterminator="\n")
    w.writerow(["glyph", "master", "lsb", "rsb", "width", "new_lsb", "new_rsb", "new_width"])
    for п in sorted(report.spacing, key=lambda п: (п.name, п.master)):
        w.writerow([п.name, п.master, п.lsb, п.rsb, п.advance, п.new_lsb, п.new_rsb, п.new_advance])
    return буфер.getvalue()


def kerning_fea(plan, w, master="", pairs=None):
    """Кернинг мастера w в синтаксисе фич: классы, пары знаков, затем пары
    классов (пары знаков идут первыми — так они перебивают классы).

    `pairs` — {«л|п»: [числа]} вместо пар плана (для «дописать к своему»:
    тогда пишутся только они, без классов)"""
    строки = ["# Autokerner — %s" % master if master else "# Autokerner",
              "", "feature kern {"]
    if pairs is None:
        имена_л, имена_п = class_names(plan)
        for номер, знаки in sorted(plan.left_members.items()):
            строки.append("    @%s = [%s];" % (имена_л[номер], " ".join(знаки)))
        for номер, знаки in sorted(plan.right_members.items()):
            строки.append("    @%s = [%s];" % (имена_п[номер], " ".join(знаки)))
        строки.append("")
        свои = plan.pairs
    else:
        свои = pairs
    for ключ in sorted(свои):
        л, п = ключ.split("|")
        строки.append("    pos %s %s %d;" % (л, п, int(round(свои[ключ][w]))))
    if pairs is None:
        for ключ in sorted(plan.cells):
            число = plan.cells[ключ][w]
            if число:
                строки.append("    pos @%s @%s %d;" % (имена_л[ключ >> 16], имена_п[ключ & 0xFFFF], int(round(число))))
    строки += ["} kern;", ""]
    return "\n".join(строки)


def save(folder, font_name, report_html, report, result, masters, pairs=None):
    """Записать в папку: отчёт (HTML), поля (CSV), кернинг по мастерам
    (.fea). Ответ — список записанных файлов"""
    основа = safe_name(font_name)
    файлы = []

    def записать(имя, текст):
        путь = os.path.join(folder, имя)
        with open(путь, "w", encoding="utf-8") as f:
            f.write(текст)
        файлы.append(путь)

    записать(основа + " — report.html",
             "<!doctype html><meta charset='utf-8'><title>%s</title>%s" % (основа, report_html))
    if report.spacing:
        записать(основа + " — spacing.csv", spacing_csv(report))
    if result.kern is not None:
        for w, m in enumerate(masters):
            хвост = (" — " + safe_name(m)) if len(masters) > 1 else ""
            записать("%s — kern%s.fea" % (основа, хвост), kerning_fea(result.kern, w, m, pairs))
    return файлы
