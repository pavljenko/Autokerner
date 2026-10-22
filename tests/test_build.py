"""Сборка для FontLab: один файл, в нём все модули пакета как есть"""

import ast
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from tools.build_fontlab_script import МОДУЛИ, ПАКЕТ, build  # noqa: E402


def модули(путь):
    дерево = ast.parse(open(путь, encoding="utf-8").read())
    for узел in дерево.body:
        if isinstance(узел, ast.Assign) and getattr(узел.targets[0], "id", "") == "_MODULES":
            return ast.literal_eval(узел.value)
    return None


class BuildTest(unittest.TestCase):
    def test_modules_embedded_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as папка:
            м = модули(build(os.path.join(папка, "Autokerner.py")))
            self.assertEqual(list(м), МОДУЛИ)
            for имя, текст in м.items():
                self.assertEqual(текст, open(os.path.join(ПАКЕТ, имя + ".py"), encoding="utf-8").read())
                compile(текст, имя, "exec")


if __name__ == "__main__":
    unittest.main()
