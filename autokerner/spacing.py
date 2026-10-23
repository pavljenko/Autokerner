"""Правило апрошей: сколько белого знак впускает в строку своим краем.

Перенос правила апрошей исходной программы (Swift). Метод HT Letterspacer
в её изложении: площадь белого
у края знака меряется в полосе высот его группы (строчные, прописные,
капитель), глубина учёта ограничена, эталон — медиана по этому же шрифту.
Знаки препинания меряются иначе — против штамба прямой буквы; знак с
диакритикой ставится по своей основе; составной едет вместе с базой.
"""

import math

from .geometry import INF, ink_profile, irnd, median, rnd
from .unicode_props import base_code, is_letter, is_lowercase, is_uppercase, is_number

LOWER, UPPER, SMALLCAP, OTHER = "lower", "upper", "smallCap", "other"

# Метки капители в имени глифа: «a.sc», «a.smcp», «A.c2sc», «iacute_sc»
SMALLCAP_TAGS = {"sc", "smcp", "c2sc"}

DECLARED_HEIGHT_TOLERANCE = 0.06
FALLBACK_CAP_HEIGHT = 0.7
FALLBACK_X_HEIGHT = 0.5


class SpacingRule:
    """Числа правила.

    depth — глубина учёта белого в долях кегельной; overshoot — выход полосы
    за базовую и за рост в долях роста; threshold — порог «выбился» на 1000
    единиц; word_gap — доля медианной строчной у пробела; word_gap_slack —
    насколько пробелу позволено быть шире правила; word_gap_edge — широкий
    пробел сужать только до края допуска, а не до середины (поправка
    окна, вне исходного правила: у шрифтов с нарочно широким пробелом
    правило сужало его на треть разом — замер 22.10.2026, 285 → 195).

    soft — белое у края мерить мягко (`white_soft`, поправка окна, вне
    исходного правила): plateau — сколько белого от крайней точки весит
    полностью, tail — шаг, с которым вес дальше убывает (доли кегля);
    shelter_slope — наклон «конуса» видимости, shelter_weight — вес белого,
    укрытого выступом сверху или снизу; serif_weight — вес белого между
    концом короткой засечки и штамбом, serif_depth — наибольший вынос такой
    засечки, serif_flat — допуск ровности штамба (доли кегля)."""

    def __init__(self, depth=0.07, overshoot=0.0, threshold=12, word_gap=0.47,
                 word_gap_slack=0.25, word_gap_edge=False, soft=False, plateau=0.03, tail=0.07,
                 shelter_slope=1.0, shelter_weight=0.0, serif_weight=0.75, serif_depth=0.08,
                 serif_flat=0.01):
        self.depth = depth
        self.overshoot = overshoot
        self.threshold = threshold
        self.word_gap = word_gap
        self.word_gap_slack = word_gap_slack
        self.word_gap_edge = word_gap_edge
        self.soft = soft
        self.plateau = plateau
        self.tail = tail
        self.shelter_slope = shelter_slope
        self.shelter_weight = shelter_weight
        self.serif_weight = serif_weight
        self.serif_depth = serif_depth
        self.serif_flat = serif_flat


class SpaceTarget:
    __slots__ = ("advance", "target", "median", "word_gap", "deviating")

    def __init__(self, advance, target, median_, word_gap, deviating):
        self.advance = advance
        self.target = target
        self.median = median_
        self.word_gap = word_gap
        self.deviating = deviating


class SpacingItem:
    """Что правило говорит об одном знаке"""
    __slots__ = ("name", "code", "group", "advance", "lsb", "rsb", "white_left", "white_right",
                 "target_lsb", "target_rsb", "target_advance", "derived")

    def __init__(self, name, code, group, advance, lsb, rsb, white_left, white_right,
                 target_lsb, target_rsb, target_advance, derived=False):
        self.name = name
        self.code = code
        self.group = group
        self.advance = advance
        self.lsb = lsb
        self.rsb = rsb
        self.white_left = white_left
        self.white_right = white_right
        self.target_lsb = target_lsb
        self.target_rsb = target_rsb
        self.target_advance = target_advance
        self.derived = derived

    @property
    def delta_left(self):
        return self.target_lsb - self.lsb

    @property
    def delta_right(self):
        return self.target_rsb - self.rsb

    @property
    def shift(self):
        return max(abs(self.delta_left), abs(self.delta_right))

    def copy(self):
        return SpacingItem(self.name, self.code, self.group, self.advance, self.lsb, self.rsb,
                           self.white_left, self.white_right, self.target_lsb, self.target_rsb,
                           self.target_advance, self.derived)


class SpacingPlan:
    def __init__(self, items, rule, targets, upm, profiles, zone_height, space):
        self.items = items
        self.rule = rule
        self.targets = targets
        self.upm = upm
        self.profiles = profiles
        self.zone_height = zone_height
        self.space = space

    @property
    def threshold_units(self):
        return self.rule.threshold * self.upm / 1000

    @property
    def deviating(self):
        """Знаки, выбившиеся из правила, — от худшего к лучшему; составные
        идут независимо от порога: они заведены только для правленых баз"""
        порог = self.threshold_units
        вышло = [з for з in self.items if з.derived or з.shift >= порог]
        вышло.sort(key=lambda з: (-з.shift, з.name))
        return вышло

    def item(self, name):
        for з in self.items:
            if з.name == name:
                return з
        return None


# ── высоты ──

def _letter_height(master, code):
    i = master.glyph(code)
    if i is None:
        return None
    from .geometry import contours_rect
    r = contours_rect(master.contours(i))
    if r is None:
        return None
    return r[3] - r[1]


def heights(master):
    """Капитель и рост строчных: объявленные, но перемеренные по «H» и «x»,
    если разошлись с рисунком больше 6 % кегля.
    Ответ — (кегль, капитель, рост)"""
    upm = float(master.upm)
    допуск = upm * DECLARED_HEIGHT_TOLERANCE
    капитель = float(master.cap_height) if master.cap_height else None
    рост = float(master.x_height) if master.x_height else None
    мера = _letter_height(master, 0x48)
    if мера is not None and (капитель is None or abs(капитель - мера) > допуск):
        капитель = мера
    мера = _letter_height(master, 0x78)
    if мера is not None and (рост is None or abs(рост - мера) > допуск):
        рост = мера
    return (upm,
            капитель if капитель is not None else upm * FALLBACK_CAP_HEIGHT,
            рост if рост is not None else upm * FALLBACK_X_HEIGHT)


# ── отбор и группы ──

def _valid_scalar(code):
    return code is not None and 0 <= code <= 0x10FFFF and not (0xD800 <= code <= 0xDFFF)


def skipped(code, contours, advance):
    """Знаки, по которым не судят площадью белого: без ширины и рисунка,
    модификаторы и одиночные диакритики, всё, что не буква"""
    if advance <= 0:
        return True
    if not contours:
        return True
    if not _valid_scalar(code):
        return True
    if 0x02B0 <= code <= 0x02FF:
        return True
    if code in (0x00A8, 0x00AF, 0x00B4, 0x00B8, 0x00AA, 0x00BA):
        return True
    return not is_letter(code)


def group(code, x_height, cap_height, upm):
    """Группа знака по регистру; юникейс — одна группа"""
    if not x_height > 0 or not _valid_scalar(code):
        return OTHER
    if not cap_height - x_height > upm * 0.05:
        return LOWER
    if is_lowercase(code):
        return LOWER
    if is_uppercase(code):
        return UPPER
    return OTHER


def name_bases(name, master, codes):
    """Буквы, по которым судится знак без кода, — по имени: «R.ss01» — «R»,
    «f_f_i» — «f» слева и «i» справа, «a.sc» — капитель. Ответ —
    (код слева, код справа, капитель) или None"""
    части = name.split(".")
    ствол = части[0]
    if not ствол:
        return None
    куски = [к for к in ствол.split("_") if к]
    if not (len(части) > 1 or len(куски) > 1):
        return None
    всего = len(куски)
    куски = [к for к in куски if к.lower() not in SMALLCAP_TAGS]
    капитель = len(куски) < всего or any(ч.lower() in SMALLCAP_TAGS for ч in части[1:])
    основы = []
    for кусок in куски:
        i = master.by_name(кусок)
        if i is None or i not in codes:
            return None
        основы.append(codes[i])
    if not основы:
        return None
    return (основы[0], основы[-1], капитель)


def body_in_line(edges, top, x_height, upm, rule=None):
    """Тело знака в строке — крайние чернила в полосе высот группы"""
    rule = rule or SpacingRule()
    выступ = rule.overshoot * x_height
    профиль = ink_profile(edges, -выступ, top + выступ, upm / 256)
    return _profile_body(профиль)


def _profile_body(профиль):
    if профиль is None:
        return None
    левые = [x for x in профиль.left if x is not None]
    правые = [x for x in профиль.right if x is not None]
    if not левые or not правые:
        return None
    return (min(левые), max(правые))


def base_body(code, glyph, master, x_height, cap_height, rule=None):
    """Знак с диакритикой, у которого тело в строке то же, что у основы:
    «ї» — «і», «й» — «и». Ответ — (номер основы, своё тело, тело основы)"""
    rule = rule or SpacingRule()
    upm = float(master.upm)
    код_базы = base_code(code)
    if код_базы is None:
        return None
    база = master.glyph(код_базы)
    if база is None or база == glyph:
        return None
    г = group(code, x_height, cap_height, upm)
    if г == OTHER or г != group(код_базы, x_height, cap_height, upm):
        return None
    верх = cap_height if г == UPPER else x_height
    своё = body_in_line(master.glyphs[glyph].edges, верх, x_height, upm, rule)
    if своё is None:
        return None
    базы = body_in_line(master.glyphs[база].edges, верх, x_height, upm, rule)
    if базы is None:
        return None
    порог = rule.threshold * upm / 1000
    if not abs((своё[1] - своё[0]) - (базы[1] - базы[0])) <= порог:
        return None
    return (база, своё, базы)


def mark_base(name, code, master, codes, among):
    """Имя основы знака с диакритикой среди `among`: по разложению Юникода,
    у знака без кода — по стволу имени с тем же хвостом"""
    def имя_глифа(к):
        i = master.glyph(к)
        return master.name(i) if i is not None else None

    if code is not None:
        к = base_code(code)
        if к is None:
            return None
        имя = имя_глифа(к)
        return имя if имя is not None and имя in among else None
    точка = name.find(".")
    if точка <= 0:
        return None
    ствол = name[:точка]
    if "_" in ствол:
        return None
    глиф = master.by_name(ствол)
    if глиф is None or глиф not in codes:
        return None
    код_основы = base_code(codes[глиф])
    if код_основы is None:
        return None
    имя_основы = имя_глифа(код_основы)
    if имя_основы is None:
        return None
    хвост = name[точка:]
    кандидаты = [имя_основы + хвост]
    метка = next((ч for ч in хвост.split(".") if ч and ч.lower() in SMALLCAP_TAGS), None)
    кандидаты.append(имя_основы + "." + метка if метка is not None else имя_основы)
    return next((к for к in кандидаты if к in among), None)


def out_of_line(rect, top):
    """Знак вне строки — надстрочный или подстрочный: площадью не измерить"""
    if not top > 0:
        return True
    return rect[1] > top * 0.35 or rect[3] < top * 0.68


def white(профиль, advance, глубина):
    """Площадь белого слева и справа с ограничением глубины; строка без
    чернил считается белой ровно на глубину"""
    тело = _profile_body(профиль)
    if тело is None:
        return (0.0, 0.0, 0.0)
    стенка_л, стенка_п = тело
    слева = 0.0
    справа = 0.0
    высота = 0.0
    шаг = профиль.step
    предел_л = стенка_л + глубина
    предел_п = стенка_п - глубина
    for л, п in zip(профиль.left, профиль.right):
        л = min(л if л is not None else INF, предел_л)
        п = max(п if п is not None else -INF, предел_п)
        слева += л * шаг
        справа += (advance - п) * шаг
        высота += шаг
    return (слева, справа, высота)


def white_soft(профиль, advance, rule, upm):
    """Площадь белого слева и справа — мягко (поправка окна, вне исходного
    правила; задачи #1 и #2 на GitHub).

    `white` считает белое от крайней точки вглубь на `depth` полностью, а
    дальше — никак. Так у открытых сторон (С, Л, л, е, A, V) пропадает белое
    сразу за границей, и пары с ними остаются разреженными, а белое за
    бруском засечки считается пробелом целиком, и засечные буквы сходятся
    теснее круглых. Здесь белое от крайней точки весит полностью только на
    `plateau`, дальше вес убывает экспонентой с шагом `tail`; белое глубже
    «конуса» видимости (от чернил соседних строк вглубь с наклоном
    `shelter_slope`) укрыто выступом сверху или снизу — перекладиной,
    засечкой, свесом — и весит `shelter_weight`. Если сторона — прямой штамб
    с короткой засечкой (в средней полосе высоты чернила стоят ровной стенкой
    не дальше `serif_depth` от конца засечки), белое между концом засечки и
    штамбом весит `serif_weight`, а глубина дальше меряется от штамба: глаз
    видит краем буквы штамб, засечку — отчасти. Числа подобраны на 11 хорошо
    расставленных антиквах и гротесках: разброс белого их сторон вокруг
    медианы шрифта — 7,8 % против 10,7 % у жёсткого предела, без перекоса по
    видам сторон; у пяти хорошо расставленных брусковых — 8,8 % против 9,2 %.
    Вес засечки 75 %, а не меньше: при 50 % узкий брусковый шрифт с короткими
    засечками выравнивается так же, но хорошо расставленные шрифты
    сдвигаются заметно больше (у одной из антикв — 43 буквы вместо 24; замеры
    23.10.2026). Строка без чернил считается белой на всю глубину учёта"""
    тело = _profile_body(профиль)
    if тело is None:
        return (0.0, 0.0, 0.0)
    стенка_л, стенка_п = тело
    шаг = профиль.step
    полка = rule.plateau * upm
    хвост = rule.tail * upm
    наклон = rule.shelter_slope * шаг
    укрытое = rule.shelter_weight
    вся = полка + хвост
    засечка_вес = rule.serif_weight
    засечка_до = rule.serif_depth * upm
    ровно = rule.serif_flat * upm

    def вес(d):
        if d == INF:
            return вся
        if d <= полка:
            return d
        return полка + хвост * (1.0 - math.exp(-(d - полка) / хвост))

    def засечка(отступы):
        """Глубина штамба за короткой засечкой, иначе 0"""
        if засечка_вес >= 1.0:
            return 0.0
        n = len(отступы)
        средние = [d for d in отступы[int(0.2 * n):int(0.8 * n) + 1] if d != INF]
        if not средние:
            return 0.0
        c = min(средние)
        if 0 < c <= засечка_до and max(средние) - c <= ровно:
            return c
        return 0.0

    def сторона(отступы):
        c = засечка(отступы)
        if c:
            ядро = [d if d == INF else max(0.0, d - c) for d in отступы]
        else:
            ядро = отступы
        огибающая = list(ядро)
        n = len(огибающая)
        if укрытое < 1.0 and наклон > 0:
            for i in range(1, n):
                v = огибающая[i - 1] + наклон
                if v < огибающая[i]:
                    огибающая[i] = v
            for i in range(n - 2, -1, -1):
                v = огибающая[i + 1] + наклон
                if v < огибающая[i]:
                    огибающая[i] = v
        сумма = 0.0
        for d, dc, e in zip(отступы, ядро, огибающая):
            we = вес(e)
            сумма += we + укрытое * (вес(dc) - we)
            if c:
                сумма += засечка_вес * min(d, c)
        return сумма

    левые = [INF if л is None else max(0.0, л - стенка_л) for л in профиль.left]
    правые = [INF if п is None else max(0.0, стенка_п - п) for п in профиль.right]
    высота = len(левые) * шаг
    слева = стенка_л * высота + сторона(левые) * шаг
    справа = (advance - стенка_п) * высота + сторона(правые) * шаг
    return (слева, справа, высота)


def _min_codes(master):
    кодГлифа = {}
    for код, i in master.cmap.items():
        if i not in кодГлифа or код < кодГлифа[i]:
            кодГлифа[i] = код
    return кодГлифа


class _Measure:
    __slots__ = ("имя", "код", "группа", "группаСправа", "advance", "lsb", "rsb",
                 "белоеСлева", "белоеСправа", "высотаСлева", "высотаСправа", "безКода")


def plan(master, rule=None, looseness=0.0, fixed=frozenset()):
    """Замер и расчёт апрошей по мастеру.

    `looseness` — разрядка в долях: эталон белого у всех групп умножается
    на 1 + looseness (−0,1 — плотнее на десятую, +0,1 — свободнее); 0 —
    исходное правило как есть. `fixed` — имена знаков, которых правило
    не трогает: цель у них — нынешние поля, и их основа для диакритики,
    составных и знаков препинания тоже стоит на месте"""
    rule = rule or SpacingRule()
    upm, капитель, рост = heights(master)
    капитель = max(капитель, рост + 1)
    шаг = upm / 256
    глубина = rule.depth * upm
    выступ = rule.overshoot * рост

    профили = {}
    высотаЗоны = 0.0
    замеры = []

    # обход по глифам: у юникейса один рисунок стоит на двух кодах
    кодГлифа = _min_codes(master)
    обход = [(i, к, к, к, False) for i, к in sorted(кодГлифа.items(), key=lambda п: п[1])]
    for i in range(master.num_glyphs):
        if i in master.codes_by_glyph:
            continue
        основы = name_bases(master.name(i), master, кодГлифа)
        if основы is None:
            continue
        обход.append((i, None, основы[0], основы[1], основы[2]))

    from .geometry import contours_rect
    верхи = []
    for i, _, _, _, кап in обход:
        if кап and not master.component_bases(i):
            r = contours_rect(master.contours(i))
            if r is not None:
                верхи.append(r[3])
    ростКапители = median(верхи) if len(верхи) >= 3 else рост

    def верх(г):
        if г == UPPER:
            return капитель
        if г == SMALLCAP:
            return ростКапители
        return рост

    составные = []
    for i, код, слева, справа, кап in обход:
        знак = master.glyphs[i]
        контуры = знак.contours
        advance = знак.advance
        if skipped(слева, контуры, advance) or skipped(справа, контуры, advance):
            continue
        базы = master.component_bases(i)
        if базы:
            составные.append((i, код, базы))
            continue
        рамка = contours_rect(контуры)
        if рамка is None:
            continue
        группаЛ = SMALLCAP if кап else group(слева, рост, капитель, upm)
        группаП = SMALLCAP if кап else group(справа, рост, капитель, upm)
        if группаЛ == OTHER or группаП == OTHER \
                or out_of_line(рамка, верх(группаЛ)) or out_of_line(рамка, верх(группаП)):
            continue
        lsb = irnd(рамка[0])
        rsb = advance - irnd(рамка[2])

        def замер(г):
            профиль = ink_profile(знак.edges, -выступ, верх(г) + выступ, шаг)
            if профиль is None:
                return None
            if rule.soft:
                л, п, в = white_soft(профиль, float(advance), rule, upm)
            else:
                л, п, в = white(профиль, float(advance), глубина)
            return (профиль, л, п, в) if в > 0 else None

        левый = замер(группаЛ)
        if левый is None:
            continue
        правый = левый if группаП == группаЛ else замер(группаП)
        if правый is None:
            continue
        профили[знак.name] = левый[0]
        высотаЗоны = max(высотаЗоны, левый[3], правый[3])
        з = _Measure()
        з.имя, з.код, з.группа, з.группаСправа = знак.name, код, группаЛ, группаП
        з.advance, з.lsb, з.rsb = advance, lsb, rsb
        з.белоеСлева, з.белоеСправа = левый[1], правый[2]
        з.высотаСлева, з.высотаСправа = левый[3], правый[3]
        з.безКода = код is None
        замеры.append(з)

    # ── эталон: медиана площади белого по группе ──
    эталоны = {}
    for г in (LOWER, UPPER):
        слева = [з.белоеСлева for з in замеры if not з.безКода and з.группа == г]
        справа = [з.белоеСправа for з in замеры if not з.безКода and з.группаСправа == г]
        if not (слева + справа):
            continue
        эталоны[г] = median(слева + справа)
    малые = [з for з in замеры if з.группа == SMALLCAP]
    if len(малые) >= 8:
        эталоны[SMALLCAP] = median([з.белоеСлева for з in малые] + [з.белоеСправа for з in малые])
    elif UPPER in эталоны:
        доля = ростКапители / капитель
        эталоны[SMALLCAP] = эталоны[UPPER] * доля * доля
    if looseness:
        for г in эталоны:
            эталоны[г] *= 1.0 + looseness

    # ── целевые отступы: за раз не дальше полупросвета между штамбами ──
    def полпросвета(коды, y):
        for к in коды:
            i = master.glyph(к)
            if i is None:
                continue
            поля = stem_sides(master, i, y)
            if поля is None:
                continue
            return (поля[0] + поля[1]) / 2
        return None

    предел_строчных = полпросвета([0x6E, 0x43D], рост / 2)
    предел_прописных = полпросвета([0x48, 0x41D], капитель / 2)
    if предел_прописных is None:
        предел_прописных = предел_строчных

    def в_пределе(сдвиг, г):
        предел = предел_прописных if г == UPPER else предел_строчных
        if предел is None:
            return сдвиг
        return min(max(сдвиг, -предел), предел)

    items = []
    for з in замеры:
        цельЛ = эталоны.get(з.группа)
        цельП = эталоны.get(з.группаСправа)
        if цельЛ is None or цельП is None:
            continue
        сдвигЛ = в_пределе((цельЛ - з.белоеСлева) / з.высотаСлева, з.группа)
        сдвигП = в_пределе((цельП - з.белоеСправа) / з.высотаСправа, з.группаСправа)
        новыйL = irnd(float(з.lsb) + сдвигЛ)
        новыйR = irnd(float(з.rsb) + сдвигП)
        if з.имя in fixed:
            новыйL, новыйR = з.lsb, з.rsb
        чернила = з.advance - з.lsb - з.rsb
        items.append(SpacingItem(з.имя, з.код, з.группа, з.advance, з.lsb, з.rsb,
                                 з.белоеСлева, з.белоеСправа, новыйL, новыйR,
                                 новыйL + чернила + новыйR))
    порог = rule.threshold * upm / 1000

    # ── знак с диакритикой — по своей основе ──
    измеренные = {}
    for з in items:
        if з.name not in измеренные:
            измеренные[з.name] = з.copy()
    for и, знак in enumerate(items):
        if знак.name in fixed:
            continue
        имя_основы = mark_base(знак.name, знак.code, master, кодГлифа, измеренные)
        if имя_основы is None:
            continue
        основа = измеренные[имя_основы]
        if основа.group != знак.group:
            continue
        своё = _profile_body(профили.get(знак.name))
        базы = _profile_body(профили.get(основа.name))
        if своё is None or базы is None:
            continue
        ширина = своё[1] - своё[0]
        ширина_базы = базы[1] - базы[0]
        if ширина > ширина_базы + порог:
            items[и].target_lsb = знак.lsb + основа.delta_left
            items[и].target_rsb = знак.rsb + основа.delta_right
            items[и].target_advance = знак.advance + основа.delta_left + основа.delta_right
        elif abs(ширина - ширина_базы) <= порог:
            левое_базы = базы[0] + float(основа.delta_left)
            правое_базы = float(основа.advance) - базы[1] + float(основа.delta_right)
            сдвигЛ = irnd(левое_базы - своё[0])
            сдвигП = irnd(правое_базы - (float(знак.advance) - своё[1]))
            items[и].target_lsb = знак.lsb + сдвигЛ
            items[и].target_rsb = знак.rsb + сдвигП
            items[и].target_advance = знак.advance + сдвигЛ + сдвигП

    # ── составные наследуют метрики базы ──
    по_имени = {з.name: з for з in items}
    for i, код, базы in составные:
        if master.name(i) in fixed:
            continue
        основа = next((по_имени[master.name(б)] for б in базы if master.name(б) in по_имени), None)
        if основа is None:
            continue
        if not float(основа.shift) >= порог:
            continue
        advance = master.advance(i)
        разница = основа.target_advance - основа.advance
        if разница == 0:
            continue
        рамка = contours_rect(master.contours(i))
        lsb = irnd(рамка[0]) if рамка else 0
        rsb = advance - (irnd(рамка[2]) if рамка else 0)
        items.append(SpacingItem(master.name(i), код, основа.group, advance, lsb, rsb,
                                 основа.white_left, основа.white_right,
                                 lsb + основа.delta_left, rsb + основа.delta_right,
                                 advance + разница, derived=True))

    # ── знаки препинания: своя мера, против штамба прямой буквы ──
    items += [з for з in mark_items(master, items, rule.threshold * upm / 1000, рост, капитель)
              if з.name not in fixed]
    return SpacingPlan(items, rule, эталоны, master.upm, профили, высотаЗоны,
                       space_target(master, rule))


def space_target(master, rule=None):
    """Цель по ширине межсловного пробела — доля медианной строчной"""
    rule = rule or SpacingRule()
    пробел = master.glyph(0x20)
    if пробел is None:
        return None
    ширина = master.advance(пробел)
    if ширина <= 0:
        return None
    мед = median(lower_widths(master, LOWER))
    if not мед > 0:
        return None
    цель = rnd(мед * rule.word_gap)
    выбился = float(ширина) - цель > цель * rule.word_gap_slack
    if выбился and rule.word_gap_edge:
        # до края допуска, на единицу внутрь: повторный расчёт его не тронет
        цель = math.floor(цель * (1 + rule.word_gap_slack))
    return SpaceTarget(ширина, int(цель), мед, rule.word_gap, выбился)


def lower_widths(master, г):
    from .geometry import contours_rect
    upm, капитель, рост = heights(master)
    капитель = max(капитель, рост + 1)
    вышло = []
    for код, i in master.cmap.items():
        знак = master.glyphs[i]
        if skipped(код, знак.contours, знак.advance):
            continue
        if group(код, рост, капитель, upm) != г:
            continue
        рамка = contours_rect(знак.contours)
        if рамка is None or out_of_line(рамка, капитель if г == UPPER else рост):
            continue
        вышло.append(float(знак.advance))
    return вышло


# ── знаки препинания ──

class _Norm:
    __slots__ = ("median", "low", "high")

    def __init__(self, м, н, в):
        self.median = м
        self.low = н
        self.high = в

    def target(self, доля):
        return min(max(доля, self.low), self.high)


def _n(*числа):
    return (_Norm(*числа[:3]), _Norm(*числа[3:]))


# слева — поле после буквы, справа — перед буквой; в долях просвета между
# штамбами «nn»: медиана и четверти по замерам выверенных шрифтов
MARK_NORMS = {
    0x2E: _n(0.86, 0.83, 0.99, 0.92, 0.88, 0.99),     # .
    0x2C: _n(0.77, 0.70, 0.88, 0.91, 0.83, 0.98),     # ,
    0x3A: _n(0.99, 0.87, 1.13, 0.93, 0.88, 1.06),     # :
    0x3B: _n(0.88, 0.73, 1.05, 0.93, 0.83, 1.04),     # ;
    0x21: _n(1.06, 0.89, 1.20, 1.04, 0.93, 1.13),     # !
    0x3F: _n(0.74, 0.72, 0.80, 0.80, 0.78, 0.89),     # ?
    0x2026: _n(0.99, 0.95, 1.08, 1.06, 0.97, 1.13),   # …
    0xAB: _n(0.75, 0.67, 0.80, 0.80, 0.76, 0.83),     # «
    0xBB: _n(0.75, 0.72, 0.79, 0.79, 0.74, 0.84),     # »
    0x2039: _n(0.75, 0.67, 0.86, 0.82, 0.78, 0.91),   # ‹
    0x203A: _n(0.76, 0.72, 0.84, 0.80, 0.76, 0.89),   # ›
    0x201C: _n(0.75, 0.68, 0.87, 0.79, 0.74, 0.90),   # “
    0x201D: _n(0.74, 0.68, 0.90, 0.76, 0.72, 0.93),   # ”
    0x2018: _n(0.75, 0.65, 0.94, 0.82, 0.76, 0.92),   # ‘
    0x2019: _n(0.75, 0.69, 0.94, 0.79, 0.74, 0.93),   # ’
    0x22: _n(0.90, 0.76, 1.10, 0.93, 0.81, 1.03),     # "
    0x27: _n(0.86, 0.72, 1.10, 0.85, 0.79, 0.99),     # '
    0x28: _n(0.90, 0.79, 1.03, 0.70, 0.63, 0.79),     # (
    0x29: _n(0.63, 0.57, 0.71, 1.01, 0.83, 1.11),     # )
    0x5B: _n(1.10, 1.01, 1.19, 0.77, 0.69, 0.84),     # [
    0x5D: _n(0.71, 0.66, 0.75, 1.16, 1.06, 1.23),     # ]
    0x7B: _n(0.86, 0.78, 0.95, 0.83, 0.69, 0.90),     # {
    0x7D: _n(0.80, 0.73, 0.89, 0.88, 0.80, 0.95),     # }
    0x2D: _n(0.86, 0.69, 0.91, 0.87, 0.76, 0.93),     # -
    0x2013: _n(0.50, 0.49, 0.86, 0.55, 0.50, 0.93),   # –
    0x2014: _n(0.72, 0.49, 0.90, 0.78, 0.51, 0.94),   # —
    0x2F: _n(0.49, 0.29, 0.60, 0.64, 0.40, 0.71),     # /
    0x2A: _n(0.77, 0.70, 0.87, 0.84, 0.74, 0.89),     # *
    0x2022: _n(1.00, 0.84, 1.26, 1.02, 0.89, 1.30),   # •
    0xB7: _n(0.87, 0.84, 1.09, 0.92, 0.88, 1.06),     # ·
    0x25: _n(0.75, 0.70, 0.95, 0.79, 0.75, 1.01),     # %
    0x26: _n(0.77, 0.74, 0.83, 0.65, 0.51, 0.71),     # &
    0x40: _n(0.87, 0.78, 0.98, 0.88, 0.80, 1.00),     # @
    0x23: _n(0.67, 0.59, 0.77, 0.77, 0.66, 0.90),     # #
    0xA7: _n(0.79, 0.75, 0.86, 0.85, 0.81, 0.88),     # §
}


def stem_sides(master, glyph, y):
    """Поля штамба на высоте y: от начала знака до чернил и от чернил до
    конца ширины"""
    шаг = float(master.upm) / 200
    профиль = ink_profile(master.glyphs[glyph].edges, y - шаг / 2, y + шаг / 2, шаг)
    if профиль is None:
        return None
    слева = профиль.left[0]
    справа = профиль.right[0]
    if слева is None or справа is None:
        return None
    return (слева, float(master.advance(glyph)) - справа)


def mark_items(master, letters, порог, рост, капитель):
    """Апроши знаков препинания — с кодом и их варианты без кода
    («parenleft.case» берёт норму «(» и меряется против «H»)"""
    from .geometry import contours_rect

    def эталон(коды, высота):
        for к in коды:
            i = master.glyph(к)
            if i is None:
                continue
            поля = stem_sides(master, i, высота)
            if поля is None:
                continue
            имя = master.name(i)
            своя = next((з for з in letters if з.name == имя and not з.derived), None)
            if своя is not None and float(своя.shift) >= порог:
                поля = (поля[0] + float(своя.delta_left), поля[1] + float(своя.delta_right))
            return поля
        return None

    строчная = эталон([0x6E, 0x43D, 0x48, 0x41D], рост / 2)
    прописная = эталон([0x48, 0x41D], капитель / 2)
    if прописная is None:
        прописная = строчная
    if строчная is None and прописная is None:
        return []

    основы = {}
    for код in sorted(master.cmap):
        if код in MARK_NORMS:
            основы.setdefault(master.name(master.cmap[код]), код)
    вышло = []
    for i in range(master.num_glyphs):
        имя = master.name(i)
        коды = master.codes_by_glyph.get(i)
        свой_код = next((к for к in коды if к in MARK_NORMS), None) if коды else None
        норма = None
        прописной = False
        if свой_код is not None:
            норма = MARK_NORMS[свой_код]
        elif коды is None and "." in имя:
            точка = имя.index(".")
            основа = имя[:точка]
            if основа in основы:
                норма = MARK_NORMS[основы[основа]]
                хвост = имя[точка:].lower()
                прописной = "case" in хвост or "cap" in хвост
        поля = прописная if прописной else строчная
        if поля is None:
            поля = прописная if прописная is not None else строчная
        if норма is None or поля is None:
            continue
        if master.component_bases(i):
            continue
        advance = master.advance(i)
        рамка = contours_rect(master.contours(i))
        if advance <= 0 or рамка is None:
            continue
        lsb = irnd(рамка[0])
        rsb = advance - irnd(рамка[2])
        просвет = поля[0] + поля[1]
        if not просвет > 0:
            continue
        слева = (поля[1] + float(lsb)) / просвет
        справа = (float(rsb) + поля[0]) / просвет
        предел = просвет / 2

        def поле(доля, н, было, штамб):
            сдвиг = min(max(н.target(доля) * просвет - штамб - float(было), -предел), предел)
            return было + irnd(сдвиг)

        новыйL = поле(слева, норма[0], lsb, поля[1])
        новыйR = поле(справа, норма[1], rsb, поля[0])
        чернила = advance - lsb - rsb
        вышло.append(SpacingItem(имя, свой_код, OTHER, advance, lsb, rsb, 0.0, 0.0,
                                 новыйL, новыйR, новыйL + чернила + новыйR))
    return вышло


def is_digit_name(name):
    """Цифра по имени глифа: «one.tf», «two.tnum», «uni0033.osf»"""
    куски = [к for к in name.split(".") if к]
    основа = куски[0] if куски else name
    if основа in ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"):
        return True
    if основа.startswith("uni003") and len(основа) == 7 and is_number(ord(основа[-1])):
        return True
    return False


def is_number_code(code):
    return _valid_scalar(code) and is_number(code)
