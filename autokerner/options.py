"""Настройки расчёта и записи — то, что пользователь выбирает в окне.

Числа правила по умолчанию — исходное правило как есть; поверх него окно
по умолчанию включает поправки: пробел сужается только до края
допуска, цифры с запятой и точкой не сходятся, обычный карман шрифта
берётся по медиане, знаки препинания на разной высоте (кавычка и
запятая) не заходят друг под друга, метки, отдельные акценты и «_» не
кернятся, пара не раздвигается сильнее 150 тысячных кегля; с 0.4 — общая
плотность на 10 % выше исходного правила (все знаки разом, ползунок
«Разрядка» отсчитывается от неё), пропорциональные цифры ставятся и
кернятся, знак не зажимается соседом сверху и снизу.
`Options.classic()` — исходное правило без поправок:
с ним итог совпадает с исходным расчётом до единицы. Наборы («Текст»,
«Заголовки», «Лёгкий кернинг») — отправные точки, после выбора любой
ползунок можно сдвинуть.
"""

import json

from .kerning import (FIGURES_OFF, FIGURES_RULE, FIGURES_SAFE, NEUTRAL_MAX, NEUTRAL_MEDIAN, KernLaw,
                      KernRule)
from .spacing import SpacingRule

REPLACE, MERGE = "replace", "merge"
# цифры с запятой, точкой, двоеточием: как в правиле, без столкновений, не кернить
FIGURES = (FIGURES_RULE, FIGURES_SAFE, FIGURES_OFF)
ALL, SELECTED = "all", "selected"


class Options:
    # что считать
    spacing = True
    space = True
    kerning = True
    # какие знаки и мастера
    glyphs = ALL                 # ALL | SELECTED (выделенные в окне шрифта)
    keep_marked = False          # не трогать знаки с цветной меткой
    keep_metric_keys = True      # не трогать знаки с формулами метрик FontLab
    nbsp_follows_space = True    # неразрывный пробел — шириной как пробел
    masters = None               # имена мастеров; None — все
    # правило апрошей
    looseness = 0                # разрядка, %: −20 плотнее … +20 свободнее
    spacing_threshold = 12       # править знак, если поле уходит на столько (/1000 кегля)
    word_gap = 47                # пробел — доля медианной строчной, %
    space_edge = True            # широкий пробел — до края допуска (True) или до нормы (False)
    # правило кернинга
    kern_strength = 100          # сила: какую долю «кармана» закрывать, %
    kern_threshold = 8           # пары меньше этого не пишутся (/1000)
    kern_clearance = 25          # ближе этого чернила пары не сходятся (/1000)
    kern_precision = 10          # точность классов (/1000)
    kern_limit = 12000           # предел пар поимённо; 0 — без предела
    kern_round = 1               # шаг округления значений, единиц
    kern_max_tight = 0           # не сжимать пару сильнее (/1000); 0 — без предела
    kern_max_loose = 150         # не раздвигать пару сильнее (/1000); 0 — без предела
    kern_figures = FIGURES_SAFE  # цифры с , . : — как в правиле, без столкновений, не кернить
    # поправки к исходному правилу (в окне не показываются; см. classic)
    kern_neutral = NEUTRAL_MEDIAN  # обычный карман шрифта — медиана пар-образцов
    kern_marks_apart = True      # кавычка и запятая не заходят друг под друга
    kern_skip_nontext = True     # метки, отдельные акценты и «_» не кернятся
    spacing_optical = True       # белое у края — мягко, с укрытием (задачи #1, #2)
    kern_lower_overhang = True   # хвостик f над строчной не кернится (задача #3)
    heights_by_letters = True    # рост и капитель сверены с медианой верхов букв
    kern_guard_body = True       # буквы раздвигаются только за сход в теле строки
    italic_slant = True          # курсив меряется вдоль угла наклона
    spacing_cursive = True       # у рукописного строения белое за входом — от тела
    spacing_density = -10        # общая плотность окна, %: от неё отсчитывается ползунок «Разрядка»
    spacing_even_density = True  # разрядка двигает все знаки группы, порог — только выравнивание
    spacing_figures = True       # пропорциональные цифры — по норме своей группы
    kern_figure_pairs = True     # пропорциональные цифры кернятся между собой
    kern_enclosure = True        # знак не зажимается чернилами соседа сверху и снизу
    kern_mode = REPLACE          # REPLACE — заменить целиком; MERGE — дописать к своему

    FIELDS = ("spacing", "space", "kerning", "glyphs", "keep_marked", "keep_metric_keys",
              "nbsp_follows_space", "masters", "looseness", "spacing_threshold", "word_gap",
              "kern_strength", "kern_threshold", "kern_clearance", "kern_precision", "kern_limit",
              "kern_round", "kern_max_tight", "kern_figures", "kern_mode", "space_edge",
              "kern_neutral", "kern_marks_apart", "kern_max_loose", "kern_skip_nontext",
              "spacing_optical", "kern_lower_overhang", "heights_by_letters",
              "kern_guard_body", "italic_slant", "spacing_cursive", "spacing_density",
              "spacing_even_density", "spacing_figures", "kern_figure_pairs", "kern_enclosure")

    def __init__(self, **kw):
        for k, v in kw.items():
            if k not in self.FIELDS:
                raise KeyError(k)
            setattr(self, k, v)

    def to_dict(self):
        return {k: getattr(self, k) for k in self.FIELDS}

    @classmethod
    def from_dict(cls, d):
        """Терпимо к старым и чужим записям: неизвестное пропускается"""
        o = cls()
        for k in cls.FIELDS:
            if k in d:
                setattr(o, k, d[k])
        return o

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, text):
        try:
            return cls.from_dict(json.loads(text))
        except (ValueError, TypeError):
            return cls()

    # ── в правила расчёта ──

    @classmethod
    def classic(cls, **kw):
        """Исходное правило без поправок окна — для сверки с исходным расчётом"""
        o = cls(kern_figures=FIGURES_RULE, space_edge=False, kern_neutral=NEUTRAL_MAX,
                nbsp_follows_space=False, kern_marks_apart=False, kern_max_loose=0,
                kern_skip_nontext=False, spacing_optical=False, kern_lower_overhang=False,
                heights_by_letters=False, kern_guard_body=False, italic_slant=False,
                spacing_cursive=False, spacing_density=0, spacing_even_density=False,
                spacing_figures=False, kern_figure_pairs=False, kern_enclosure=False)
        for k, v in kw.items():
            setattr(o, k, v)
        return o

    def spacing_rule(self):
        return SpacingRule(threshold=self.spacing_threshold, word_gap=self.word_gap / 100.0,
                           word_gap_edge=bool(self.space_edge), soft=bool(self.spacing_optical),
                           robust_heights=bool(self.heights_by_letters), slant=bool(self.italic_slant),
                           cursive=bool(self.spacing_cursive), even_density=bool(self.spacing_even_density),
                           figures=bool(self.spacing_figures))

    def kern_rule(self):
        return KernRule(threshold=self.kern_threshold, visible=self.kern_precision,
                        exception_limit=self.kern_limit or None)

    def kern_law(self):
        return KernLaw(threshold=self.kern_threshold, strength=self.kern_strength / 100.0,
                       clearance=self.kern_clearance, figures=self.kern_figures,
                       neutral=self.kern_neutral, marks_apart=bool(self.kern_marks_apart),
                       skip_nontext=bool(self.kern_skip_nontext),
                       lower_overhang=bool(self.kern_lower_overhang),
                       robust_heights=bool(self.heights_by_letters),
                       guard_body=bool(self.kern_guard_body), slant=bool(self.italic_slant),
                       figure_pairs=bool(self.kern_figure_pairs), enclosure=bool(self.kern_enclosure))

    def total_looseness(self):
        """Разрядка расчёта в долях: общая плотность окна и ползунок вместе
        (−10 % и ползунок 0 → −0,1; ползунок +10 → −0,01)"""
        return (1.0 + self.spacing_density / 100.0) * (1.0 + self.looseness / 100.0) - 1.0

    def is_default_rule(self):
        """Числа правила — как по умолчанию (поправки окна не в счёт)"""
        d = Options()
        return all(getattr(self, k) == getattr(d, k) for k in (
            "looseness", "spacing_threshold", "word_gap", "space_edge", "kern_strength", "kern_threshold",
            "kern_clearance", "kern_precision", "kern_limit", "kern_round", "kern_max_tight",
            "kern_max_loose", "kern_figures"))


# Наборы: имя → поля правила
PRESETS = {
    "default": {},
    "display": {"looseness": -8, "kern_strength": 120, "kern_clearance": 15, "kern_threshold": 5,
                "kern_precision": 5, "kern_limit": 0},
    "light": {"kern_strength": 80, "kern_threshold": 15, "kern_precision": 20, "kern_limit": 3000,
              "kern_round": 5},
}

PRESET_TITLES = {
    "default": ("Текст — правило по умолчанию", "Text — default rule"),
    "display": ("Заголовки — плотнее, кернинг сильнее", "Display — tighter, stronger kerning"),
    "light": ("Лёгкий кернинг — малый файл", "Light kerning — small file"),
}

PRESET_NOTES = {
    "default": ("Для набора текста и для большинства шрифтов.",
                "For running text and most fonts."),
    "display": ("Для крупного кегля: разрядка −8 %, кернинг сильнее, зазор меньше, классы точнее, "
                "пары без предела — файл больше.",
                "For large sizes: spacing −8%, stronger kerning, smaller clearance, finer classes, "
                "unlimited pairs — a bigger file."),
    "light": ("Только заметные пары, значения кратны 5, до 3 000 пар знаков — для веба и малых файлов.",
              "Only visible pairs, values in steps of 5, up to 3,000 glyph pairs — for the web and small files."),
}


def preset(name, base=None):
    """Настройки набора поверх `base` (что считать, знаки и мастера не меняются)"""
    o = Options.from_dict(base.to_dict()) if base is not None else Options()
    d = Options()
    for k in ("looseness", "spacing_threshold", "word_gap", "space_edge", "kern_strength", "kern_threshold",
              "kern_clearance", "kern_precision", "kern_limit", "kern_round", "kern_max_tight",
              "kern_max_loose", "kern_figures"):
        setattr(o, k, getattr(d, k))
    for k, v in PRESETS.get(name, {}).items():
        setattr(o, k, v)
    return o
