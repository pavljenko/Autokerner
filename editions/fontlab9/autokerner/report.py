"""«Было / станет»: что расчёт поменяет в шрифте — числами и таблицами.

Без FontLab: на вход — итог расчёта (`auto.AutoResult`) и прежний кернинг
мастеров (любой объект с `value(левый, правый)`, `count`, `classes`).
"""

# Пары, по которым кернинг судят глазами (контрольные пары исходной программы)
CONTROL_PAIRS = [
    ("A", "V"), ("A", "W"), ("A", "T"), ("A", "Y"), ("F", "a"), ("L", "T"),
    ("P", "a"), ("T", "a"), ("T", "o"), ("V", "a"), ("W", "a"), ("Y", "o"),
    ("r", "."), ("y", ","), ("f", ")"), ("L", "V"), ("к", "о"),
    ("Г", "а"), ("Г", "у"), ("У", "ж"), ("Т", "а"), ("Т", "о"),
    ("Л", "о"), ("Р", "."), ("У", ","), ("А", "У"), ("Д", "А"),
    ("Ь", "Т"), ("ъ", "е"), ("«", "А"), ("У", "»"), ("7", ","),
    ("Г", "."), ("L", "’"), ("!", "»"),
]

# Сколько пар перебирать для «крупнейших изменений» — дальше выборка мастеров
PAIR_BUDGET = 4000000


class SpacingChange:
    __slots__ = ("name", "master", "lsb", "rsb", "advance", "new_lsb", "new_rsb", "new_advance")

    @property
    def size(self):
        return max(abs(self.new_lsb - self.lsb), abs(self.new_rsb - self.rsb))


class Report:
    """Числа окна «было / станет».

    `spacing` — правки полей (`SpacingChange`) всех мастеров, от крупных;
    `space` — [(мастер, было, станет)]; `kern_before` — [(мастер, пар,
    классов)]; `kern_after` — числа новой записи; `control` — контрольные
    пары [(текст, [(было, станет) по мастерам])]; `pair_changes` —
    крупнейшие изменения пар [(левый, правый, мастер, было, станет)]."""

    def __init__(self):
        self.masters = []
        self.glyphs = 0
        self.spacing = []
        self.spacing_glyphs = 0
        self.space = []
        self.kern_before = []
        self.kern_after = {}
        self.control = []
        self.pair_changes = []


def build(masters, result, old_kerning, top=25, after=None):
    """`masters` — мастера расчёта; `old_kerning` — по мастерам, объекты
    с `value`, `count`, `classes`; `after(w)` — число пары после записи на
    мастере w, `value(левый, правый)` (по умолчанию — план расчёта: так
    при записи целиком)"""
    отчёт = Report()
    отчёт.masters = [m.label for m in masters]
    отчёт.glyphs = len(masters[0].glyphs) if masters else 0

    # ── поля ──
    for w, план in enumerate(result.plans):
        for имя in result.spacing:
            знак = план.item(имя)
            if знак is None or w not in result.spacing[имя]:
                continue
            правка = SpacingChange()
            правка.name, правка.master = имя, masters[w].label
            правка.lsb, правка.rsb, правка.advance = знак.lsb, знак.rsb, знак.advance
            правка.new_lsb, правка.new_rsb, правка.new_advance = (
                знак.target_lsb, знак.target_rsb, знак.target_advance)
            отчёт.spacing.append(правка)
    отчёт.spacing.sort(key=lambda п: (-п.size, п.name, п.master))
    отчёт.spacing_glyphs = len(result.spacing)

    # ── пробел ──
    for w, m in enumerate(masters):
        if w in result.space:
            i = m.glyph(0x20)
            отчёт.space.append((m.label, m.advance(i) if i is not None else None, result.space[w]))

    # ── кернинг ──
    k = result.kern
    for w, m in enumerate(masters):
        отчёт.kern_before.append((m.label, old_kerning[w].count, old_kerning[w].classes))
    if k is None:
        return отчёт
    if after is None:
        def after(w):
            return lambda л, п: k.value(л, п, w)
    станет = [after(w) for w in range(len(masters))]
    отчёт.kern_after = {
        "left": len(k.left_members), "right": len(k.right_members),
        "cells": len(k.cells), "pairs": len(k.pairs),
        "precision": k.precision, "truncated": k.truncated,
    }
    m0 = masters[0]
    for л, п in CONTROL_PAIRS:
        a, b = m0.glyph(ord(л)), m0.glyph(ord(п))
        if a is None or b is None:
            continue
        левый, правый = m0.name(a), m0.name(b)
        ряд = [(old_kerning[w].value(левый, правый), станет[w](левый, правый))
               for w in range(len(masters))]
        отчёт.control.append((л + п, ряд))

    # крупнейшие изменения — среди знаков с кодом, что есть в новом кернинге
    кернятся = set(k.left_class) | set(k.right_class)
    for ключ in k.pairs:
        л, п = ключ.split("|")
        кернятся.add(л)
        кернятся.add(п)
    имена = [g.name for g in m0.glyphs if g.codes and g.name in кернятся]
    веса = list(range(len(masters)))
    if len(имена) ** 2 * len(веса) > PAIR_BUDGET and len(веса) > 2:
        веса = [0, len(masters) - 1]
    лучшие = []
    for w in веса:
        old = old_kerning[w]
        for л in имена:
            for п in имена:
                было = old.value(л, п)
                стало = станет[w](л, п)
                разница = abs(стало - было)
                if разница:
                    лучшие.append((разница, л, п, w, было, стало))
        лучшие.sort(key=lambda x: -x[0])
        del лучшие[top * 4:]
    лучшие.sort(key=lambda x: (-x[0], x[1], x[2], x[3]))
    отчёт.pair_changes = [(л, п, masters[w].label, было, стало)
                          for _, л, п, w, было, стало in лучшие[:top]]
    return отчёт
