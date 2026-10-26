"""Тексты окна: немецкий словарь полон и подставляет те же числа, что
русский и английский"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from autokerner import fontlab_ui as ui  # noqa: E402
from autokerner.options import PRESET_NOTES, PRESET_TITLES  # noqa: E402

_PLACE = re.compile(r"%[-+ 0#]*\d*(?:\.\d+)?[dsf]")


def места(текст):
    return _PLACE.findall(текст)


class GermanTextTest(unittest.TestCase):
    def test_same_keys(self):
        self.assertEqual(set(ui._TEXT_DE), set(ui._TEXT))
        self.assertEqual(set(ui._PRESET_DE), set(PRESET_TITLES))
        self.assertEqual(set(ui._PRESET_DE), set(PRESET_NOTES))

    def test_same_placeholders(self):
        for ключ, (ru, en) in ui._TEXT.items():
            de = ui._TEXT_DE[ключ]
            self.assertEqual(места(de), места(en), ключ)
            self.assertEqual(места(ru), места(en), ключ)
            self.assertEqual(de.count("|"), en.count("|"), ключ)

    def test_progress_messages(self):
        self.assertEqual([ш.pattern for ш, _ in ui._TR_DE], [ш.pattern for ш, _ in ui._TR_EN])

    def test_switch(self):
        было = ui.LANG
        try:
            ui.LANG = 2
            self.assertEqual(ui.t("apply"), "Anwenden")
            self.assertEqual(ui.preset_title("light"), ui._PRESET_DE["light"][0])
            self.assertTrue(ui.support_url().endswith("?lang=en"))
            self.assertEqual(ui._tr("апроши: мастер 1 из 2"), "Zurichtung: Master 1 von 2")
            self.assertEqual(ui._n(12000), "12\xa0000")
            ui.LANG = 0
            self.assertEqual(ui.t("apply"), "Применить")
            self.assertFalse(ui.support_url().endswith("?lang=en"))
            ui.LANG = 1
            self.assertEqual(ui.t("apply"), "Apply")
            self.assertEqual(ui._n(12000), "12,000")
        finally:
            ui.LANG = было

    def test_lang_env(self):
        было = os.environ.get("AUTOKERNER_LANG")
        try:
            for код, номер in (("de", 2), ("ru", 0), ("en", 1)):
                os.environ["AUTOKERNER_LANG"] = код
                self.assertEqual(ui._lang(), номер)
        finally:
            if было is None:
                os.environ.pop("AUTOKERNER_LANG", None)
            else:
                os.environ["AUTOKERNER_LANG"] = было


if __name__ == "__main__":
    unittest.main()
