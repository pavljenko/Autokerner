"""Сборка веб-версии: один кусок кода для статьи на сайте.

    python3 tools/build_web.py

`dist/web/autokerner-article.html` — вставить в тело статьи целиком
(стили, разметка, скрипт; расчёт — пакет autokerner в Pyodide, тексты —
из окна FontLab, чтобы подписи совпадали). `dist/web/preview.html` — та
же вставка на отдельной странице для проверки: `preview.html?font=адрес`
сразу открывает шрифт.
"""

import ast
import json
import os
import sys

КОРЕНЬ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, КОРЕНЬ)

from autokerner import __version__, fontlab_ui, outcome  # noqa: E402
from autokerner.options import FIGURES, PRESET_NOTES, PRESET_TITLES, PRESETS, Options  # noqa: E402

PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/"
MODULES = ["__init__", "unicode_props", "geometry", "model", "spacing", "kerning", "options", "auto",
           "report", "outcome", "export", "otf", "fontfile", "web"]
# что настраивается на странице (выделения, мастеров, формул и меток в файле нет)
FIELDS = ["spacing", "space", "kerning", "kern_mode", "nbsp_follows_space", "looseness", "spacing_threshold",
          "word_gap", "space_edge", "kern_strength", "kern_threshold", "kern_clearance", "kern_figures",
          "kern_precision", "kern_limit", "kern_round", "kern_max_tight", "kern_max_loose"]


def compact(source):
    """Модуль без комментариев и строк документации — страница легче"""
    дерево = ast.parse(source)
    for узел in ast.walk(дерево):
        тело = getattr(узел, "body", None)
        if isinstance(тело, list) and тело and isinstance(тело[0], ast.Expr) \
                and isinstance(getattr(тело[0], "value", None), ast.Constant) and isinstance(тело[0].value.value, str):
            узел.body = тело[1:] or [ast.Pass()]
    return ast.unparse(дерево) + "\n"


def data():
    исходники = {}
    for имя in MODULES:
        with open(os.path.join(КОРЕНЬ, "autokerner", имя + ".py"), encoding="utf-8") as f:
            исходники[имя + ".py"] = compact(f.read())
    with open(os.path.join(КОРЕНЬ, "web", "worker.js"), encoding="utf-8") as f:
        поток = f.read()
    умолчания = Options().to_dict()
    return {
        "version": __version__,
        "pyodide": PYODIDE,
        "sources": исходники,
        "worker": поток,
        "texts": {k: list(v) for k, v in fontlab_ui._TEXT.items()},
        "titles": {k: list(v) for k, v in PRESET_TITLES.items()},
        "notes": {k: list(v) for k, v in PRESET_NOTES.items()},
        "presets": PRESETS,
        "preset_keys": fontlab_ui._PRESET_KEYS,
        "defaults": {k: умолчания[k] for k in FIELDS},
        "precision": fontlab_ui._PRECISION,
        "limits": fontlab_ui._LIMITS,
        "rounds": fontlab_ui._ROUNDS,
        "figures": list(FIGURES),
        "tr": [[ш.pattern, з] for ш, з in fontlab_ui._TR_EN],
        "sample": outcome.DEFAULT_TEXT,
    }


def article():
    with open(os.path.join(КОРЕНЬ, "web", "app.css"), encoding="utf-8") as f:
        стили = f.read()
    with open(os.path.join(КОРЕНЬ, "web", "app.js"), encoding="utf-8") as f:
        скрипт = f.read()
    # внутри <script> не должно быть «</» и «<!--» — иначе HTML закроет тег раньше
    данные = json.dumps(data(), ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")
    скрипт = скрипт.replace("__AK_DATA__", данные)
    return ("<!-- Автокернер (Autokerner) %s — веб-версия. Вставлять в статью целиком, ничего не меняя. "
            "Всё живёт внутри #ak-app и страницу сайта не трогает. -->\n"
            '<div id="ak-app" class="ak"></div>\n<style>\n%s</style>\n<script>\n%s</script>\n' % (__version__, стили, скрипт))


PREVIEW = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Autokerner — web</title>
<style>
  body { margin: 0; background: #fff; color: #20241F; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
  .page { max-width: 1280px; margin: 0 auto; padding: 24px 16px 0; }
  h1 { font-size: 40px; margin: 8px 0 24px; }
</style>
</head>
<body>
<div class="page">
<h1>Автокернер</h1>
%s
</div>
<script>
  // стенд: preview.html?font=адрес — сразу открыть шрифт
  (function () {
    var m = /[?&]font=([^&]+)/.exec(location.search);
    if (!m) return;
    var url = decodeURIComponent(m[1]);
    fetch(url).then(function (r) { return r.arrayBuffer(); }).then(function (buf) {
      return window.AutokernerApp.open(url.split('/').pop(), buf);
    });
  })();
</script>
</body>
</html>
"""


def main():
    папка = os.path.join(КОРЕНЬ, "dist", "web")
    os.makedirs(папка, exist_ok=True)
    вставка = article()
    with open(os.path.join(папка, "autokerner-article.html"), "w", encoding="utf-8") as f:
        f.write(вставка)
    with open(os.path.join(папка, "preview.html"), "w", encoding="utf-8") as f:
        f.write(PREVIEW % вставка)
    print("%s — %d КБ" % (os.path.join(папка, "autokerner-article.html"), len(вставка.encode("utf-8")) // 1024))


if __name__ == "__main__":
    main()
