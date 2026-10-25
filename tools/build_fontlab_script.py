"""Сборка сценария FontLab в один файл.

    python3 tools/build_fontlab_script.py

Пишет `dist/Autokerner.py`: модули пакета `autokerner` лежат в нём
текстом и заводятся как настоящие модули при запуске, затем зовётся окно.
Один файл ставится в FontLab проще всего — положить в папку сценариев.
Код внутри — тот же, что проверяют тесты, побайтно.
"""

import os
import sys

КОРЕНЬ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ПАКЕТ = os.path.join(КОРЕНЬ, "autokerner")
# fontTools в FontLab нет: чтение файлов (otf.py) нужно только проверкам вне него
МОДУЛИ = ["__init__", "unicode_props", "geometry", "model", "zero_model", "zero", "spacing", "kerning", "options", "auto",
          "report", "outcome", "export", "fontlab_bridge", "fontlab_ui"]

ШАПКА = '''#FLM: Autokerner
# -*- coding: utf-8 -*-
"""Autokerner {version} for FontLab 8: spacing and kerning for all masters in one run.
Автокернер для FontLab 8: апроши и кернинг одной кнопкой на всех мастерах.

{copyright}. MIT License, see LICENSE in the project repository.

Built from the autokerner package by tools/build_fontlab_script.py; do not edit
this file, changes are lost on the next build.
Собрано из пакета autokerner; правки вносить в исходники, не сюда.
"""

import sys as _sys
import types as _types

_MODULES = {{
'''

ХВОСТ = '''}}


def _install():
    for _name in {order!r}:
        _full = "autokerner" if _name == "__init__" else "autokerner." + _name
        _module = _types.ModuleType(_full)
        _module.__file__ = __file__ if "__file__" in globals() else "<Autokerner>"
        if _name == "__init__":
            _module.__path__ = []
        _module.__package__ = "autokerner"
        _sys.modules[_full] = _module
        exec(compile(_MODULES[_name], "autokerner/" + _name + ".py", "exec"), _module.__dict__)
        if _name != "__init__":
            setattr(_sys.modules["autokerner"], _name, _module)


_install()
from autokerner.fontlab_ui import main  # noqa: E402

main()
'''


def build(out_path=None):
    sys.path.insert(0, КОРЕНЬ)
    import autokerner
    out_path = out_path or os.path.join(КОРЕНЬ, "dist", "Autokerner.py")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    части = [ШАПКА.format(version=autokerner.__version__, copyright=autokerner.__copyright__)]
    for имя in МОДУЛИ:
        текст = open(os.path.join(ПАКЕТ, имя + ".py"), encoding="utf-8").read()
        части.append("%r: %r,\n" % (имя, текст))
    части.append(ХВОСТ.format(order=МОДУЛИ))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("".join(части))
    return out_path


if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else None))
