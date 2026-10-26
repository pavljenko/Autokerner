"""Авторасчёт по всем мастерам: апроши и пробел, затем кернинг.

Перенос исходного правила на Python. Апроши — на каждом мастере своим
расчётом; знак правится на всех мастерах, если выбился хоть на одном
(иначе по оси вышла бы ступенька). Шрифт без своей расстановки
расставляется с нуля, и поправка к угаданной плотности одна на ось
(`_carry_zero`). Кернинг меряется по мастерам,
переписанным с новыми полями, классы — одни на все мастера, числа по
каждому.
"""

import copy
import math

from .kerning import KernLaw, KernRule, adjust_values, make_matrix, matrix_names, plan_variable
from .spacing import SpacingRule, plan as spacing_plan
from .geometry import contours_rect, irnd


class AutoResult:
    """Итог расчёта.

    `spacing` — имя → {номер мастера: (сдвиг рисунка, ширина)};
    `space` — {номер мастера: ширина пробела}, если пробел правится;
    `kern` — `KernPlanVariable`; `plans` — планы апрошей по мастерам (для
    окна «было / станет»)."""

    def __init__(self, weights, spacing, space, kern, plans):
        self.weights = weights
        self.spacing = spacing
        self.space = space
        self.kern = kern
        self.plans = plans
        # цифры, что сходятся через запятую, точку, двоеточие (см. kerning.number_separators)
        self.collisions = []

    def to_json(self):
        """Тот же вид, что у файла для сверки `авторасчёт.json`"""
        spacing = {}
        for имя, по_мастерам in self.spacing.items():
            ряд = []
            for w, (dx, ширина) in sorted(по_мастерам.items()):
                ряд += [self.weights[w], {"dx": dx, "advance": ширина}]
            spacing[имя] = ряд
        space = []
        for w, ширина in sorted(self.space.items()):
            space += [self.weights[w], ширина]
        k = self.kern
        return {
            "spacing": spacing,
            "space": space,
            "kern": {
                "weights": list(k.weights),
                "leftClass": dict(k.left_class),
                "rightClass": dict(k.right_class),
                "cells": {str(ключ): числа for ключ, числа in k.cells.items()},
                "pairs": dict(k.pairs),
                "precision": k.precision,
                "truncated": k.truncated,
            },
        }


def _along_stem(штамб, опоры):
    """Поправка мастера со штамбом `штамб` по опорам [(штамб, {группа:
    поправка})]: между опорами — в логарифмах по толщине штамба, за
    крайними — как у крайней"""
    опоры = sorted(опоры, key=lambda о: о[0])
    if штамб <= опоры[0][0]:
        return dict(опоры[0][1])
    if штамб >= опоры[-1][0]:
        return dict(опоры[-1][1])
    for (ш1, п1), (ш2, п2) in zip(опоры, опоры[1:]):
        if ш1 <= штамб <= ш2:
            t = (штамб - ш1) / (ш2 - ш1) if ш2 > ш1 else 0.0
            return {г: math.exp(math.log(п1.get(г, п2.get(г))) * (1 - t) + math.log(п2.get(г, п1.get(г))) * t)
                    for г in set(п1) | set(п2)}
    return dict(опоры[-1][1])


def _carry_zero(masters, планы, правило, looseness, fixed):
    """С нуля у нескольких мастеров: поправка к угаданной плотности — от
    букв-образцов или числа из окна — одна на ось. Мастер с образцами (с
    числом — средний по толщине штамба) держит свою плотность, остальные
    берут его поправку к своей угаданной; между несколькими опорами
    поправка идёт по толщине штамба. Иначе вес с образцами выбивался из
    ряда, а число давало всем весам одно поле H (замер 26.10.2026)"""
    нули = [w for w, п in enumerate(планы) if п.from_zero and п.zero_scale and п.zero_stem]
    if len(нули) < 2:
        return планы
    if правило.side_h:
        по_штамбу = sorted(нули, key=lambda w: планы[w].zero_stem)
        опоры = [по_штамбу[(len(по_штамбу) - 1) // 2]]
    else:
        опоры = [w for w in нули if планы[w].side_source == "hand"]
    if not опоры:
        return планы
    вышло = list(планы)
    for w in нули:
        if w in опоры:
            continue
        своё = copy.copy(правило)
        своё.side_h = 0.0
        своё.zero_scale = _along_stem(планы[w].zero_stem, [(планы[о].zero_stem, планы[о].zero_scale)
                                                           for о in опоры])
        вышло[w] = spacing_plan(masters[w], своё, looseness, fixed)
    return вышло


def _nbsp(masters, пробел, fixed):
    """Правки неразрывного пробела (U+00A0): ширина — как у пробела того же
    мастера (новая, если пробел правится). Пусто — уже равны, знака нет или
    один знак стоит на обоих кодах"""
    m0 = masters[0]
    i, j = m0.glyph(0x20), m0.glyph(0xA0)
    if i is None or j is None or i == j or m0.name(j) in fixed:
        return {}
    имя = m0.name(j)
    по_мастерам = {}
    for w, мастер in enumerate(masters):
        a, b = мастер.glyph(0x20), мастер.by_name(имя)
        if a is None or b is None or мастер.contours(b):
            return {}
        по_мастерам[w] = (0, пробел.get(w, мастер.advance(a)))
    if all(masters[w].advance(masters[w].by_name(имя)) == ширина
           for w, (_, ширина) in по_мастерам.items()):
        return {}
    return {имя: по_мастерам}


def run(masters, spacing_rule=None, kern_rule=None, progress=None, kern=True, options=None,
        fixed=()):
    """Авторасчёт. `masters` — мастера одного шрифта (`model.Master`) с одним
    набором имён знаков; `progress(текст)` — сообщения о ходе (бросит
    исключение — расчёт прервётся).

    `options` — настройки окна (`options.Options`): что считать, правило и
    запись; без них — исходное правило. `fixed` — знаки, поля которых
    не трогаются (выбор пользователя: не выделенные, с меткой, с формулой
    метрик, снятые в окне правок)"""
    looseness, round_to, max_tight, max_loose = 0.0, 1, 0, 0
    do_spacing = do_space = True
    закон = None
    if options is not None:
        spacing_rule = options.spacing_rule()
        kern_rule = options.kern_rule()
        закон = options.kern_law()
        looseness = options.total_looseness()
        do_spacing, do_space, kern = options.spacing, options.space, options.kerning
        round_to, max_tight, max_loose = options.kern_round, options.kern_max_tight, options.kern_max_loose
    правило = spacing_rule or SpacingRule()
    кернинг = kern_rule or KernRule()
    say = progress or (lambda текст: None)
    веса = [m.weight for m in masters]
    fixed = frozenset(fixed)

    # ── апроши на каждом мастере ──
    планы = []
    for номер, мастер in enumerate(masters):
        say("апроши: мастер %d из %d" % (номер + 1, len(masters)))
        планы.append(spacing_plan(мастер, правило, looseness, fixed))
    планы = _carry_zero(masters, планы, правило, looseness, fixed)
    правятся = set()
    if do_spacing:
        for план in планы:
            for знак in план.deviating:
                правятся.add(знак.name)
    места = {}
    for имя in sorted(правятся):
        по_мастерам = {}
        for w, план in enumerate(планы):
            знак = план.item(имя)
            if знак is None:
                continue
            по_мастерам[w] = (знак.delta_left, знак.target_advance)
        места[имя] = по_мастерам

    # ── пробел: правится на всех мастерах, если выбился хоть на одном ──
    пробел = {}
    i = masters[0].glyph(0x20) if masters else None
    if i is not None and masters[0].name(i) in fixed:
        do_space = False
    if do_space and any(п.space is not None and п.space.deviating for п in планы):
        for w, план in enumerate(планы):
            if план.space is not None:
                пробел[w] = план.space.target

    # ── неразрывный пробел — шириной как пробел (вне исходного правила:
    # разные ширины — частая ошибка, её ловит проверка FontBakery) ──
    if options is not None and options.space and options.nbsp_follows_space:
        места.update(_nbsp(masters, пробел, fixed))

    if not kern:
        return AutoResult(веса, места, пробел, None, планы)

    # ── кернинг по выровненным апрошам ──
    if закон is None:
        закон = KernLaw(threshold=кернинг.threshold)
    матрицы = []
    общие = None
    for w, мастер in enumerate(masters):
        правки = {}
        for имя, по_мастерам in места.items():
            место = по_мастерам.get(w)
            i = мастер.by_name(имя)
            if место is None or i is None or contours_rect(мастер.contours(i)) is None:
                continue
            правки[имя] = место
        if w in пробел:
            i = мастер.glyph(0x20)
            if i is not None:
                правки[мастер.name(i)] = (0, пробел[w])
        выровненный = мастер.with_metrics(правки)
        if общие is None:
            общие = matrix_names(выровненный, закон)

        def ход(л, n, w=w):
            say("кернинг: мастер %d из %d, знак %d из %d" % (w + 1, len(masters), л + 1, n))

        матрица = make_matrix(выровненный, закон, общие, ход)
        матрицы.append(adjust_values(матрица, round_to, irnd(max_tight * мастер.upm / 1000.0),
                                     irnd(max_loose * мастер.upm / 1000.0)))
    say("кернинг: классы на все мастера")
    план = plan_variable(матрицы, веса, masters[0].upm, кернинг, progress=progress)
    итог = AutoResult(веса, места, пробел, план, планы)
    # цифры, что сходятся через запятую, точку, двоеточие — худшее по мастерам
    худшее = {}
    for матрица in матрицы:
        for л, р, п, глубина in матрица.collisions:
            худшее[(л, р, п)] = max(глубина, худшее.get((л, р, п), 0))
    итог.collisions = sorted(((к[0], к[1], к[2], г) for к, г in худшее.items()), key=lambda с: -с[3])
    return итог
