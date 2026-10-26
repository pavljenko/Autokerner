"""Правило апрошей: сколько белого знак впускает в строку своим краем.

Перенос правила апрошей исходной программы (Swift). Метод HT Letterspacer
в её изложении: площадь белого
у края знака меряется в полосе высот его группы (строчные, прописные,
капитель), глубина учёта ограничена, эталон — медиана по этому же шрифту.
Знаки препинания меряются иначе — против штамба прямой буквы; знак с
диакритикой ставится по своей основе; составной едет вместе с базой.
"""

import copy
import math

from .geometry import INF, deskewed, ink_profile, irnd, median, rnd, slant_of
from .unicode_props import base_code, is_letter, is_lowercase, is_number, is_sign, is_uppercase

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
    засечки, serif_flat — допуск ровности штамба (доли кегля).

    robust_heights — сверять рост и капитель с медианой верхов букв
    (`by_letters`, поправка окна, вне исходного правила).

    slant — мерить курсив вдоль угла наклона (поправка окна, вне исходного
    правила): профиль выпрямляется по `italic_angle` мастера.

    cursive — у шрифта рукописного строения мерить белое за входом и
    выходом строчных от тела стороны (`cursive_of`, поправка окна, вне
    исходного правила): cursive_entry — вынос входа над телом, с которого
    он входом считается (доля кегля), cursive_body — доля высоты стороны,
    где ищется тело.

    even_density — разрядка (`looseness` у `plan`) двигает все знаки группы
    одинаково, а порог решает только, выравнивать ли знак (поправка окна,
    вне исходного правила). В исходном правиле разрядка просто умножает
    эталон, и знак сдвигается, только если весь сдвиг больше порога: при
    −10 % строчные уходят на 5–8 единиц, порог 12 — и поджимаются лишь
    выбившиеся знаки, ровный шрифт становится пёстрым.

    figures — пропорциональные цифры по норме своей группы (`figure_items`,
    поправка окна): табличные не трогаются.

    per_side — порог решает за каждую сторону отдельно (поправка окна, вне
    исходного правила): выбилась одна сторона — правится она, вторая стоит.
    В исходном правиле знак, выбившийся одной стороной, ставится по правилу
    целиком, и вторая сторона уходит от дизайнера на 3–8 единиц: в проверке
    порчей стороны, испорченные на 5, после расчёта отличались на 7,9.
    По умолчанию выключено: на 14 хорошо расставленных шрифтах скрипт с
    этим ближе к дизайнеру (4,3 → 3,7 тысячных), но 50 неровных шрифтов
    выравнивает хуже (ровность хуже у 21, лучше у 5; замер 25.10.2026).

    from_zero — расстановка с нуля (`zero`, поправка окна): "auto" — если у
    шрифта нет своей расстановки (`zero.unspaced`: поля нулевые или у всех
    букв одинаковые), True — всегда, False — никогда. Тогда эталон белого
    берётся не из полей шрифта (`_zero_targets`): с букв, которые дизайнер
    расставил сам (`zero.hand_spaced`), иначе угадывается по форме
    (`zero.guess`); side_h — плотность числом, среднее белое у стороны H,
    тысячные кегля (0 — не задана); предел сдвига снят, порог почти нулевой.
    zero_scale — {группа: поправка} к угаданной плотности, которую мастеру
    передал другой мастер (`auto._carry_zero`): тогда ни число, ни свои
    образцы не в счёт."""

    def __init__(self, depth=0.07, overshoot=0.0, threshold=12, word_gap=0.47,
                 word_gap_slack=0.25, word_gap_edge=False, soft=False, plateau=0.03, tail=0.07,
                 shelter_slope=1.0, shelter_weight=0.0, serif_weight=0.75, serif_depth=0.08,
                 serif_flat=0.01, robust_heights=False, slant=False, cursive=False,
                 cursive_entry=0.04, cursive_body=0.6, even_density=False, figures=False,
                 per_side=False, from_zero=False, side_h=0.0, zero_scale=None):
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
        self.robust_heights = robust_heights
        self.slant = slant
        self.cursive = cursive
        self.cursive_entry = cursive_entry
        self.cursive_body = cursive_body
        self.even_density = even_density
        self.figures = figures
        self.per_side = per_side
        self.from_zero = from_zero
        self.side_h = side_h
        self.zero_scale = zero_scale


class SpaceTarget:
    __slots__ = ("advance", "target", "median", "word_gap", "deviating")

    def __init__(self, advance, target, median_, word_gap, deviating):
        self.advance = advance
        self.target = target
        self.median = median_
        self.word_gap = word_gap
        self.deviating = deviating


class SpacingItem:
    """Что правило говорит об одном знаке. `dense_left`, `dense_right` — часть
    сдвига от общей разрядки (`even_density`); знак с ней правится и ниже
    порога (`forced`): разрядка касается всех знаков группы"""
    __slots__ = ("name", "code", "group", "advance", "lsb", "rsb", "white_left", "white_right",
                 "target_lsb", "target_rsb", "target_advance", "derived", "dense_left", "dense_right",
                 "forced")

    def __init__(self, name, code, group, advance, lsb, rsb, white_left, white_right,
                 target_lsb, target_rsb, target_advance, derived=False, dense_left=0, dense_right=0):
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
        self.dense_left = dense_left
        self.dense_right = dense_right
        self.forced = bool(dense_left or dense_right) and (target_lsb != lsb or target_rsb != rsb)

    @property
    def delta_left(self):
        return self.target_lsb - self.lsb

    @property
    def delta_right(self):
        return self.target_rsb - self.rsb

    @property
    def shift(self):
        return max(abs(self.delta_left), abs(self.delta_right))

    def applied(self, порог):
        """Знак правится: выбился за порог, пришёл от правленой базы или
        сдвинут общей разрядкой"""
        return self.derived or self.forced or self.shift >= порог

    def copy(self):
        return SpacingItem(self.name, self.code, self.group, self.advance, self.lsb, self.rsb,
                           self.white_left, self.white_right, self.target_lsb, self.target_rsb,
                           self.target_advance, self.derived, self.dense_left, self.dense_right)


class SpacingPlan:
    def __init__(self, items, rule, targets, upm, profiles, zone_height, space):
        self.items = items
        self.rule = rule
        self.targets = targets
        self.upm = upm
        self.profiles = profiles
        self.zone_height = zone_height
        self.space = space
        self.from_zero = False   # расставлено с нуля (`SpacingRule.from_zero`)
        self.side_h = None       # белое у стороны H, тысячные кегля, если с нуля
        self.side_source = None  # откуда плотность с нуля: "set" — число, "hand" — буквы, "guess" — форма,
                                 # "carried" — поправка от другого мастера
        self.side_letters = ()   # буквы, расставленные дизайнером, если плотность с них
        self.zero_scale = {}     # с нуля: группа → эталон / угаданное (поправка этого мастера)
        self.zero_stem = None    # с нуля: толщина штамба (доля роста) — место мастера на оси веса

    @property
    def threshold_units(self):
        return self.rule.threshold * self.upm / 1000

    @property
    def deviating(self):
        """Знаки, выбившиеся из правила, — от худшего к лучшему; составные
        идут независимо от порога: они заведены только для правленых баз"""
        порог = self.threshold_units
        вышло = [з for з in self.items if з.applied(порог)]
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


# буквы, что стоят верхом на росте строчных и на высоте прописных
_НА_РОСТЕ = "xzvwunmrsнпимтшкгв"
_НА_КАПИТЕЛИ = "HINEZTFLKXMНПИТЕШГЖКМ"


def _median_top(master, буквы):
    """Медиана верхов букв; меньше трёх букв с рисунком — None"""
    from .geometry import contours_rect
    верхи = []
    for ch in буквы:
        i = master.glyph(ord(ch))
        if i is None:
            continue
        r = contours_rect(master.contours(i))
        if r is not None:
            верхи.append(r[3])
    return median(верхи) if len(верхи) >= 3 else None


def by_letters(master, капитель, рост):
    """Поправка окна к высотам (вне исходного правила): высота, что
    разошлась с медианой верхов букв больше допуска, заменяется медианой.
    Исходное правило перемеряет рост по габариту одной «x», а у рукописных
    и акцидентных шрифтов «x» бывает с росчерками вверх и вниз: у шрифта
    в духе Конашевича габарит «x» — 671 при росте 433, и почти все строчные
    оказывались «вне строки» и не мерились (сообщение на TypeDrawers,
    23.10.2026). У обычных шрифтов медиана сходится с прежней высотой в
    пределах допуска, и ничего не меняется"""
    допуск = float(master.upm) * DECLARED_HEIGHT_TOLERANCE
    мера = _median_top(master, _НА_КАПИТЕЛИ)
    if мера is not None and abs(капитель - мера) > допуск:
        капитель = мера
    мера = _median_top(master, _НА_РОСТЕ)
    if мера is not None and abs(рост - мера) > допуск:
        рост = мера
    return капитель, рост


def heights(master, robust=False):
    """Капитель и рост строчных: объявленные, но перемеренные по «H» и «x»,
    если разошлись с рисунком больше 6 % кегля; `robust` — ещё и сверенные
    с медианой верхов букв (`by_letters`).
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
    капитель = капитель if капитель is not None else upm * FALLBACK_CAP_HEIGHT
    рост = рост if рост is not None else upm * FALLBACK_X_HEIGHT
    if robust:
        капитель, рост = by_letters(master, капитель, рост)
    return (upm, капитель, рост)


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


def white_soft(профиль, advance, rule, upm, entry=False):
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
    23.10.2026). `entry` — строчная шрифта рукописного строения
    (`cursive_of`): если засечки нет, а слева вверху выступает вход (справа
    внизу — выход), белое между его концом и телом стороны весит так же,
    как за засечкой, а глубина дальше меряется от тела. Строка без чернил
    считается белой на всю глубину учёта"""
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

    def сторона(отступы, сверху):
        c = засечка(отступы)
        if not c and entry:
            c = body_behind_entry(отступы, rule.cursive_body, rule.cursive_entry * upm, сверху)
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
    слева = стенка_л * высота + сторона(левые, True) * шаг
    справа = (advance - стенка_п) * высота + сторона(правые, False) * шаг
    return (слева, справа, высота)


def body_behind_entry(отступы, доля, вынос, сверху):
    """Глубина тела стороны за входом (вверху, `сверху`) или выходом (внизу):
    тело — нижние `доля` высоты стороны (у выхода — верхние), вход — выступ
    остальной части дальше тела не меньше чем на `вынос`; иначе 0"""
    ряд = отступы if сверху else отступы[::-1]
    граница = int(доля * len(ряд))
    тело = [d for d in ряд[:граница] if d != INF]
    вход = [d for d in ряд[граница:] if d != INF]
    if not тело or not вход:
        return 0.0
    c = min(тело)
    return c if c - min(вход) >= вынос else 0.0


# Буквы со штамбом слева: по ним видно строение шрифта
_ШТАМБОВЫЕ = "nmuirpинпшщцр"


def cursive_of(master, рост, шаг, наклон=0.0, rule=None):
    """Шрифт рукописного строения (поправка окна, вне исходного правила):
    у строчных со штамбом слева (n, m, u, i, r, p, и, н, п, ш, щ, ц, р)
    вверху выступает вход — крючок, дуга, — а низ без засечки. У прямых
    засечка сверху и снизу одна (разница 0), у гротеска её нет; у десяти
    курсивов вход выступает на 68–112 тысячных кегля, у рукописного
    прямого шрифта — на 132 (замер 23.10.2026). Решает медиана разницы
    «вход − низ» по буквам: не меньше `cursive_entry`"""
    rule = rule or SpacingRule()
    upm = float(master.upm)
    разницы = []
    for буква in _ШТАМБОВЫЕ:
        i = master.glyph(ord(буква))
        if i is None or master.component_bases(i):
            continue
        профиль = deskewed(ink_profile(master.glyphs[i].edges, 0.0, рост, шаг), наклон, рост / 2)
        if профиль is None:
            continue
        левые = [INF if л is None else л for л in профиль.left]
        n = len(левые)
        середина = [d for d in левые[int(0.3 * n):int(0.7 * n) + 1] if d != INF]
        if not середина:
            continue
        c = median(середина)
        верх = min([d for d in левые[int(0.75 * n):] if d != INF] or [c])
        низ = min([d for d in левые[:int(0.25 * n) + 1] if d != INF] or [c])
        разницы.append((c - верх) - (c - низ))
    return bool(разницы) and median(разницы) >= rule.cursive_entry * upm


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
    from . import zero
    с_нуля = rule.from_zero is True or (rule.from_zero == "auto" and zero.unspaced(master))
    своё_правило = rule
    if с_нуля:
        # своей расстановки нет: правится каждый знак, как бы мало он ни ушёл
        rule = copy.copy(rule)
        rule.threshold = 0.5
    upm, капитель, рост = heights(master, rule.robust_heights)
    капитель = max(капитель, рост + 1)
    шаг = upm / 256
    глубина = rule.depth * upm
    выступ = rule.overshoot * рост
    # курсив меряется вдоль наклона (`deskewed`): иначе его штамбы дают
    # белое треугольниками, и стороны с наклоном выходят неровными
    наклон = slant_of(getattr(master, "italic_angle", 0.0)) if rule.slant else 0.0
    # у рукописного строения белое за входом строчных — от тела стороны
    рукописный = rule.soft and rule.cursive and cursive_of(master, рост, шаг, наклон, rule)

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
            if наклон:
                профиль = deskewed(профиль, наклон, верх(г) / 2)
            if профиль is None:
                return None
            if rule.soft:
                л, п, в = white_soft(профиль, float(advance), rule, upm, рукописный and г == LOWER)
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
    с_нуля_вышло = None
    if с_нуля:
        с_нуля_вышло = _zero_targets(master, замеры, профили, rule.side_h * upm / 1000.0, рост, капитель,
                                     рукописный, rule.zero_scale)
        if с_нуля_вышло is None:
            # плотность не задать (нет ни букв-образцов, ни форм для угадывания): правило как есть
            с_нуля, rule = False, своё_правило
        else:
            эталоны.update(с_нуля_вышло.targets)
    # без разрядки: по ним решается, выбился ли знак, если разрядка общая
    эталоны_ровно = dict(эталоны)
    if looseness:
        for г in эталоны:
            эталоны[г] *= 1.0 + looseness
    общая = bool(looseness) and rule.even_density
    порог = rule.threshold * upm / 1000

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
        if с_нуля:
            return сдвиг
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
        плотЛ = плотП = 0
        if общая:
            # выравнивание — против эталона без разрядки и только за порогом;
            # разрядка — одна на группу: (цель − цель без разрядки) / высота
            сдвигЛ = в_пределе((эталоны_ровно[з.группа] - з.белоеСлева) / з.высотаСлева, з.группа)
            сдвигП = в_пределе((эталоны_ровно[з.группаСправа] - з.белоеСправа) / з.высотаСправа,
                               з.группаСправа)
            правЛ = abs(irnd(float(з.lsb) + сдвигЛ) - з.lsb)
            правП = abs(irnd(float(з.rsb) + сдвигП) - з.rsb)
            if rule.per_side:
                сдвигЛ = сдвигЛ if правЛ >= порог else 0.0
                сдвигП = сдвигП if правП >= порог else 0.0
            elif max(правЛ, правП) < порог:
                сдвигЛ = сдвигП = 0.0
            плотЛ = irnd((цельЛ - эталоны_ровно[з.группа]) / з.высотаСлева)
            плотП = irnd((цельП - эталоны_ровно[з.группаСправа]) / з.высотаСправа)
            новыйL = irnd(float(з.lsb) + сдвигЛ) + плотЛ
            новыйR = irnd(float(з.rsb) + сдвигП) + плотП
        else:
            сдвигЛ = в_пределе((цельЛ - з.белоеСлева) / з.высотаСлева, з.группа)
            сдвигП = в_пределе((цельП - з.белоеСправа) / з.высотаСправа, з.группаСправа)
            новыйL = irnd(float(з.lsb) + сдвигЛ)
            новыйR = irnd(float(з.rsb) + сдвигП)
            if rule.per_side and max(abs(новыйL - з.lsb), abs(новыйR - з.rsb)) >= порог:
                новыйL = новыйL if abs(новыйL - з.lsb) >= порог else з.lsb
                новыйR = новыйR if abs(новыйR - з.rsb) >= порог else з.rsb
        if з.имя in fixed:
            новыйL, новыйR = з.lsb, з.rsb
            плотЛ = плотП = 0
        чернила = з.advance - з.lsb - з.rsb
        items.append(SpacingItem(з.имя, з.код, з.группа, з.advance, з.lsb, з.rsb,
                                 з.белоеСлева, з.белоеСправа, новыйL, новыйR,
                                 новыйL + чернила + новыйR, dense_left=плотЛ, dense_right=плотП))

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
            items[и].dense_left, items[и].dense_right = основа.dense_left, основа.dense_right
            items[и].forced = основа.forced and (основа.delta_left != 0 or основа.delta_right != 0)
        elif abs(ширина - ширина_базы) <= порог:
            левое_базы = базы[0] + float(основа.delta_left)
            правое_базы = float(основа.advance) - базы[1] + float(основа.delta_right)
            сдвигЛ = irnd(левое_базы - своё[0])
            сдвигП = irnd(правое_базы - (float(знак.advance) - своё[1]))
            items[и].target_lsb = знак.lsb + сдвигЛ
            items[и].target_rsb = знак.rsb + сдвигП
            items[и].target_advance = знак.advance + сдвигЛ + сдвигП
            items[и].dense_left, items[и].dense_right = основа.dense_left, основа.dense_right
            items[и].forced = основа.forced and (сдвигЛ != 0 or сдвигП != 0)

    # ── составные наследуют метрики базы ──
    по_имени = {з.name: з for з in items}
    for i, код, базы in составные:
        if master.name(i) in fixed:
            continue
        основа = next((по_имени[master.name(б)] for б in базы if master.name(б) in по_имени), None)
        if основа is None:
            continue
        if not основа.applied(порог):
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
                                 advance + разница, derived=True, dense_left=основа.dense_left,
                                 dense_right=основа.dense_right))

    # ── цифры — после составных: верхние и дробные индексы из компонентов
    # цифр за ними не едут ──
    if rule.figures:
        items += figure_items(master, rule, эталоны, эталоны_ровно, замеры, шаг, в_пределе, порог,
                              общая, fixed)

    # ── знаки препинания: своя мера, против штамба прямой буквы ──
    items += [з for з in mark_items(master, items, rule.threshold * upm / 1000, рост, капитель, rule, с_нуля)
              if з.name not in fixed]
    ширины = {з.name: з.target_advance for з in items if (общая or с_нуля) and з.applied(порог)}
    план = SpacingPlan(items, rule, эталоны, master.upm, профили, высотаЗоны,
                       space_target(master, rule, ширины))
    план.from_zero = с_нуля
    if с_нуля_вышло is not None:
        план.side_h, план.side_source = с_нуля_вышло.side_h, с_нуля_вышло.source
        план.side_letters = с_нуля_вышло.letters
        план.zero_scale, план.zero_stem = с_нуля_вышло.scale, с_нуля_вышло.stem
    return план


class _ZeroTargets:
    """Эталоны с нуля: `targets` — группа → белое; `source` — "set", "hand"
    или "guess"; `letters` — буквы-образцы; `side_h` — то же как белое у
    стороны H, тысячные кегля; `scale` — группа → эталон / угаданное;
    `stem` — толщина штамба, доля роста (место мастера на оси веса)"""
    __slots__ = ("targets", "source", "letters", "side_h", "scale", "stem")


def _zero_targets(master, замеры, профили, поле, рост, капитель, рукописный, масштаб=None):
    """Эталоны белого шрифту без своей расстановки, по старшинству:

    0. `масштаб` — поправка к угаданному от другого мастера того же шрифта
       (`auto._carry_zero`): число и свои образцы тогда не в счёт;
    1. `поле` (единицы шрифта, 0 — нет) — число из окна: H встаёт со средним
       белым у стороны `поле`, другие группы — с той же поправкой к тому, что
       вышло бы без числа;
    2. буквы, расставленные дизайнером (`zero.hand_spaced`): эталон группы —
       среднее белое их сторон, другая группа — угаданное с той же поправкой.
       Образцы выравниваются со всеми: оставь их как есть — и та же по форме
       буква (h рядом с n) встала бы иначе, чем образец;
    3. угадывание по форме (`zero.guess`): белое на строку полосы, умноженное
       на высоту полосы группы (медиана по буквам).

    Белое мягкой меры растёт с полем линейно (на высоту полосы за единицу).
    None — эталон не задать"""
    from . import zero

    def поле_сейчас(з):
        профиль = профили.get(з.имя)
        if профиль is None:
            return None
        края = [(л + з.advance - п) / 2.0 for л, п in zip(профиль.left, профиль.right) if л is not None]
        return sum(края) / len(края) if края else None

    # прямая буква — мерка числа из окна и его вид в отчёте
    прямая = None
    for к in (0x48, 0x49, 0x4E, 0x41D):
        з = next((з for з in замеры if з.код == к and з.группа == з.группаСправа), None)
        if з is not None and поле_сейчас(з) is not None:
            прямая = з
            break

    # группа правила для прописных и строчных: у юникейса все буквы — в одной
    группа = {}
    for регистр, буквы in (("upper", zero.CAPS), ("lower", zero.SMALL)):
        коды = {ord(с) for с in буквы} | {zero.TWINS[с] for с in буквы if с in zero.TWINS}
        свои = [з.группа for з in замеры if з.код in коды]
        if свои and max(set(свои), key=свои.count) not in группа.values():
            группа[регистр] = max(set(свои), key=свои.count)
    полоса = {}
    for г in группа.values():
        высоты = [в for з in замеры if з.код is not None and з.группа == г for в in (з.высотаСлева, з.высотаСправа)]
        if высоты:
            полоса[г] = median(высоты)

    угадано = {}
    буквы = zero.shapes(master, рост, капитель)
    формы = zero.guess(master, рост, капитель, рукописный, буквы)
    for регистр, г in группа.items():
        if формы.get(регистр) and г in полоса:
            угадано[г] = формы[регистр] * полоса[г]

    вышло = _ZeroTargets()
    вышло.targets, вышло.source, вышло.letters = dict(угадано), "guess", ()
    штамбы = [ф["штамб"] for ф in (буквы["lower"] or буквы["upper"]).values()]
    вышло.stem = median(штамбы) if штамбы else None
    if масштаб and угадано:
        общая = sum(масштаб.values()) / len(масштаб)
        вышло.targets = {г: т * масштаб.get(г, общая) for г, т in угадано.items()}
        вышло.source = "carried"
        поле = 0
    ручные = {} if масштаб else zero.hand_spaced(master)
    своё = {}
    for з in замеры:
        стороны = ручные.get(з.имя)
        if стороны and з.группа == з.группаСправа:
            своё.setdefault(з.группа, []).extend(
                б for б, есть in ((з.белоеСлева, стороны[0]), (з.белоеСправа, стороны[1])) if есть)
    if своё:
        поправки = []
        for г, белые in своё.items():
            вышло.targets[г] = sum(белые) / len(белые)
            if угадано.get(г, 0) > 0:
                поправки.append(вышло.targets[г] / угадано[г])
        if поправки:
            k = sum(поправки) / len(поправки)
            for г in угадано:
                if г not in своё:
                    вышло.targets[г] = угадано[г] * k
        вышло.source = "hand"
        вышло.letters = tuple(sorted(ручные))
    if поле and прямая is not None:
        цель = (прямая.белоеСлева + прямая.белоеСправа) / 2.0 + (поле - поле_сейчас(прямая)) * прямая.высотаСлева
        было = вышло.targets.get(прямая.группа)
        k = цель / было if было and было > 0 else 1.0
        вышло.targets = {г: т * k for г, т in вышло.targets.items()}
        вышло.targets[прямая.группа] = цель
        вышло.source = "set"
    if not вышло.targets:
        return None
    вышло.scale = {г: вышло.targets[г] / у for г, у in угадано.items() if у > 0 and г in вышло.targets}
    вышло.side_h = None
    if прямая is not None and прямая.группа in вышло.targets:
        белое = (прямая.белоеСлева + прямая.белоеСправа) / 2.0
        поле_H = поле_сейчас(прямая) + (вышло.targets[прямая.группа] - белое) / прямая.высотаСлева
        вышло.side_h = поле_H * 1000.0 / master.upm
    return вышло


def space_target(master, rule=None, ширины=None):
    """Цель по ширине межсловного пробела — доля медианной строчной;
    `ширины` — ширины знаков после расчёта (при общей разрядке строчные
    уже, и пробел меряется по ним)"""
    rule = rule or SpacingRule()
    пробел = master.glyph(0x20)
    if пробел is None:
        return None
    ширина = master.advance(пробел)
    if ширина <= 0:
        return None
    мед = median(lower_widths(master, LOWER, rule.robust_heights, ширины))
    if not мед > 0:
        return None
    цель = rnd(мед * rule.word_gap)
    выбился = float(ширина) - цель > цель * rule.word_gap_slack
    if выбился and rule.word_gap_edge:
        # до края допуска, на единицу внутрь: повторный расчёт его не тронет
        цель = math.floor(цель * (1 + rule.word_gap_slack))
    return SpaceTarget(ширина, int(цель), мед, rule.word_gap, выбился)


def lower_widths(master, г, robust=False, ширины=None):
    from .geometry import contours_rect
    upm, капитель, рост = heights(master, robust)
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
        вышло.append(float((ширины or {}).get(знак.name, знак.advance)))
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

# Символы — только для шрифта без своей расстановки (`plan`, с нуля): там их
# нынешние поля ничего не значат. Те же доли просвета «nn», медиана и четверти
# по 139 профессиональным начертаниям (замер 25.10.2026). Знак с кодом из
# символов и знаков препинания, которого нет ни здесь, ни в `MARK_NORMS`,
# ставится по общей норме — медиане всех знаков таблиц
SYMBOL_NORMS = {
    0x2B: _n(0.85, 0.75, 1.01, 0.84, 0.76, 1.00),     # +
    0x2212: _n(0.86, 0.75, 1.03, 0.86, 0.76, 1.01),   # −
    0xD7: _n(0.99, 0.85, 1.12, 0.96, 0.87, 1.11),     # ×
    0xF7: _n(0.84, 0.74, 1.01, 0.85, 0.74, 1.00),     # ÷
    0x3D: _n(0.85, 0.75, 1.03, 0.87, 0.77, 1.03),     # =
    0x2260: _n(0.84, 0.70, 1.05, 0.85, 0.72, 1.06),   # ≠
    0x2248: _n(0.85, 0.69, 1.00, 0.90, 0.72, 1.02),   # ≈
    0x3C: _n(0.86, 0.75, 1.02, 0.88, 0.78, 1.00),     # <
    0x3E: _n(0.89, 0.75, 1.02, 0.86, 0.73, 1.01),     # >
    0x2264: _n(0.79, 0.71, 1.03, 0.88, 0.73, 1.02),   # ≤
    0x2265: _n(0.84, 0.73, 1.03, 0.86, 0.72, 1.02),   # ≥
    0xB1: _n(0.83, 0.74, 0.99, 0.85, 0.75, 0.99),     # ±
    0x7E: _n(0.84, 0.72, 0.99, 0.83, 0.71, 0.97),     # ~
    0x5E: _n(0.83, 0.71, 1.02, 0.84, 0.71, 1.00),     # ^
    0x7C: _n(1.11, 0.98, 1.45, 1.13, 0.99, 1.47),     # |
    0xA6: _n(1.10, 0.98, 1.38, 1.11, 0.99, 1.44),     # ¦
    0x5C: _n(0.61, 0.48, 0.90, 0.62, 0.47, 0.84),     # \
    0xAC: _n(0.86, 0.75, 1.00, 0.87, 0.78, 1.01),     # ¬
    0xB0: _n(0.87, 0.72, 1.02, 0.76, 0.64, 0.90),     # °
    0x2032: _n(0.95, 0.81, 1.11, 0.67, 0.44, 0.79),   # ′
    0x2033: _n(0.95, 0.80, 1.12, 0.73, 0.50, 0.83),   # ″
    0x24: _n(0.75, 0.70, 0.85, 0.79, 0.68, 0.89),     # $
    0x20AC: _n(0.58, 0.50, 0.66, 0.64, 0.51, 0.75),   # €
    0xA3: _n(0.66, 0.55, 0.79, 0.68, 0.55, 0.80),     # £
    0xA5: _n(0.58, 0.48, 0.75, 0.51, 0.27, 0.60),     # ¥
    0xA2: _n(0.83, 0.75, 0.95, 0.79, 0.70, 0.94),     # ¢
    0xA4: _n(0.74, 0.65, 0.87, 0.74, 0.66, 0.87),     # ¤
    0x20BD: _n(0.61, 0.54, 0.70, 0.69, 0.60, 0.80),   # ₽
    0xA9: _n(0.75, 0.68, 0.89, 0.75, 0.66, 0.85),     # ©
    0xAE: _n(0.79, 0.67, 0.92, 0.74, 0.63, 0.85),     # ®
    0x2122: _n(0.76, 0.66, 1.05, 0.77, 0.63, 0.97),   # ™
    0xB6: _n(0.74, 0.62, 0.88, 0.73, 0.55, 1.02),     # ¶
    0x2020: _n(0.79, 0.70, 0.93, 0.73, 0.60, 0.84),   # †
    0x2021: _n(0.72, 0.63, 0.83, 0.74, 0.59, 0.85),   # ‡
    0x2030: _n(0.72, 0.63, 0.87, 0.74, 0.65, 0.82),   # ‰
    0x2116: _n(0.78, 0.58, 1.06, 0.76, 0.65, 0.90),   # №
    0xB9: _n(0.86, 0.75, 1.03, 0.87, 0.68, 1.12),     # ¹
    0xB2: _n(0.69, 0.59, 0.83, 0.71, 0.54, 0.77),     # ²
    0xB3: _n(0.71, 0.62, 0.84, 0.70, 0.56, 0.81),     # ³
    0xBD: _n(0.82, 0.72, 0.90, 0.76, 0.68, 0.89),     # ½
    0xBC: _n(0.84, 0.76, 0.90, 0.79, 0.64, 0.90),     # ¼
    0xBE: _n(0.72, 0.63, 0.84, 0.75, 0.64, 0.86),     # ¾
    0xAA: _n(0.73, 0.64, 0.87, 0.64, 0.50, 0.78),     # ª
    0xBA: _n(0.73, 0.63, 0.87, 0.68, 0.57, 0.78),     # º
    0x2190: _n(0.76, 0.64, 1.05, 0.79, 0.71, 1.13),   # ←
    0x2192: _n(0.76, 0.64, 1.10, 0.80, 0.70, 1.07),   # →
    0x2191: _n(0.99, 0.84, 1.10, 1.02, 0.88, 1.16),   # ↑
    0x2193: _n(0.99, 0.89, 1.17, 1.01, 0.88, 1.14),   # ↓
    0x25CA: _n(0.75, 0.66, 0.86, 0.73, 0.66, 0.87),   # ◊
    0x221E: _n(0.76, 0.66, 0.86, 0.78, 0.68, 0.91),   # ∞
    0x2202: _n(0.71, 0.65, 0.82, 0.75, 0.67, 0.84),   # ∂
    0x2211: _n(0.65, 0.59, 0.79, 0.69, 0.61, 0.79),   # ∑
    0x220F: _n(0.74, 0.63, 0.99, 0.75, 0.66, 0.96),   # ∏
    0x221A: _n(0.66, 0.50, 0.78, 0.48, 0.29, 0.58),   # √
    0x222B: _n(0.50, 0.28, 0.68, 0.53, 0.30, 0.68),   # ∫
    0x201A: _n(0.72, 0.57, 0.84, 0.91, 0.80, 1.00),   # ‚
    0x201E: _n(0.70, 0.60, 0.79, 0.86, 0.76, 0.98),   # „
    0xBF: _n(0.70, 0.60, 0.80, 0.81, 0.73, 0.93),     # ¿
    0xA1: _n(0.92, 0.79, 1.06, 1.00, 0.85, 1.13),     # ¡
    0x5F: _n(0.47, 0.43, 0.50, 0.52, 0.49, 0.55),     # _
    0x60: _n(0.96, 0.67, 1.30, 1.02, 0.79, 1.35),     # `
    0xB4: _n(1.22, 0.93, 1.55, 0.79, 0.48, 1.10),     # ´
    0xA8: _n(0.85, 0.62, 1.18, 0.73, 0.48, 0.94),     # ¨
    0xAF: _n(0.80, 0.48, 1.04, 0.58, 0.39, 0.89),     # ¯
    0xB8: _n(0.84, 0.63, 1.28, 1.07, 0.86, 1.39),     # ¸
    0x2DC: _n(0.83, 0.54, 1.09, 0.64, 0.35, 0.94),    # ˜
    0x2D8: _n(0.93, 0.61, 1.25, 0.70, 0.42, 1.01),    # ˘
    0x2D9: _n(1.29, 0.98, 1.63, 1.05, 0.82, 1.46),    # ˙
    0x2DA: _n(1.05, 0.82, 1.35, 0.93, 0.69, 1.17),    # ˚
    0x2DB: _n(0.97, 0.68, 1.28, 1.06, 0.80, 1.41),    # ˛
    0x2DD: _n(0.93, 0.64, 1.21, 0.53, 0.07, 0.86),    # ˝
}
SYMBOL_DEFAULT = _n(0.79, 0.69, 0.89, 0.77, 0.67, 0.87)
# Общей норме не подлежат знаки со своим устройством: псевдографика и блоки
# смыкаются краями, вертикальные и полноширинные формы — для восточноазиатского
# письма, дробная и косая черта деления заходят на цифры, отдельные акценты (Sk)
# у дизайнеров разбросаны слишком широко
SYMBOL_DEFAULT_SKIP = ((0x2500, 0x259F), (0xFE10, 0xFE1F), (0xFE30, 0xFE4F), (0x3000, 0x303F),
                       (0xFF00, 0xFFEF), (0x2044, 0x2044), (0x2215, 0x2215))


def _default_sign(код):
    """Символ с кодом, которому с нуля годится общая норма (`SYMBOL_DEFAULT`)"""
    import unicodedata
    if not is_sign(код) or any(н <= код <= в for н, в in SYMBOL_DEFAULT_SKIP):
        return False
    return unicodedata.category(chr(код)) != "Sk"


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


def _protruding_sides(master, glyph, поля, верх, rule):
    """Поля прямой буквы для знаков препинания с выступом (поправка окна, вне
    исходного правила): если крайняя точка стороны лежит в середине высоты
    строки (20–80 %) и выступает за штамб дальше короткой засечки
    (`serif_depth`), краем буквы считается она. У рукописного шрифта с
    входящей дугой кончик дуги у n — на 70 % роста и на 155 единиц левее
    штамба, и по штамбу знаки препинания отходили от слов (замер
    23.10.2026). Засечки (даже длинные, на 8–10 % кегля) и входящие штрихи
    курсивов стоят у базовой линии и верха строки — их это не касается"""
    профиль = ink_profile(master.glyphs[glyph].edges, 0, верх, float(master.upm) / 200)
    if профиль is None:
        return поля
    засечка = rule.serif_depth * master.upm
    n = len(профиль.left)

    def край(строки, крайний):
        есть = [(x, i) for i, x in enumerate(строки) if x is not None]
        if not есть:
            return None
        x, i = крайний(есть)
        return x if 0.2 * n <= i <= 0.8 * n else None

    слева, справа = поля
    край_л = край(профиль.left, min)
    край_п = край(профиль.right, max)
    if край_л is not None and слева - край_л > засечка:
        слева = край_л
    if край_п is not None:
        край_п = float(master.advance(glyph)) - край_п
        if справа - край_п > засечка:
            справа = край_п
    return (слева, справа)


def mark_items(master, letters, порог, рост, капитель, rule=None, с_нуля=False):
    """Апроши знаков препинания — с кодом и их варианты без кода
    («parenleft.case» берёт норму «(» и меряется против «H»).

    `с_нуля` — у шрифта нет своей расстановки: нынешние поля знаков ничего
    не значат, поэтому знак встаёт прямо на медиану нормы, без допуска и
    предела; к знакам препинания добавляются символы (`SYMBOL_NORMS`), а
    прочие символы с кодом встают по общей норме (`SYMBOL_DEFAULT`)

    При общей разрядке (у буквы-эталона есть `dense_left`/`dense_right`)
    выбился ли знак, решается против буквы без разрядки, а разрядка
    переходит на знак той же долей просвета: белое «буква + знак» сжимается
    так же, как просвет между штамбами"""
    from .geometry import contours_rect

    def эталон(коды, высота, с_разрядкой=True):
        for к in коды:
            i = master.glyph(к)
            if i is None:
                continue
            поля = stem_sides(master, i, высота)
            if поля is None:
                continue
            if rule is not None and rule.soft:
                поля = _protruding_sides(master, i, поля, 2 * высота, rule)
            имя = master.name(i)
            своя = next((з for з in letters if з.name == имя and not з.derived), None)
            if своя is not None and своя.applied(порог):
                dl, dr = своя.delta_left, своя.delta_right
                if not с_разрядкой:
                    dl -= своя.dense_left
                    dr -= своя.dense_right
                поля = (поля[0] + float(dl), поля[1] + float(dr))
            return поля
        return None

    строчная = эталон([0x6E, 0x43D, 0x48, 0x41D], рост / 2, False)
    прописная = эталон([0x48, 0x41D], капитель / 2, False)
    if прописная is None:
        прописная = строчная
    if строчная is None and прописная is None:
        return []
    строчная_р = эталон([0x6E, 0x43D, 0x48, 0x41D], рост / 2)
    прописная_р = эталон([0x48, 0x41D], капитель / 2)
    if прописная_р is None:
        прописная_р = строчная_р

    нормы = dict(MARK_NORMS)
    if с_нуля:
        нормы.update(SYMBOL_NORMS)
    уже = {з.name for з in letters}
    основы = {}
    for код in sorted(master.cmap):
        if код in нормы:
            основы.setdefault(master.name(master.cmap[код]), код)
    вышло = []
    for i in range(master.num_glyphs):
        имя = master.name(i)
        if имя in уже:
            continue
        коды = master.codes_by_glyph.get(i)
        свой_код = next((к for к in коды if к in нормы), None) if коды else None
        норма = None
        прописной = False
        if свой_код is not None:
            норма = нормы[свой_код]
        elif коды is None and "." in имя:
            точка = имя.index(".")
            основа = имя[:точка]
            if основа in основы:
                норма = нормы[основы[основа]]
                хвост = имя[точка:].lower()
                прописной = "case" in хвост or "cap" in хвост
        elif с_нуля and коды and any(_default_sign(к) for к in коды):
            свой_код = next(к for к in коды if _default_sign(к))
            норма = SYMBOL_DEFAULT
        поля = прописная if прописной else строчная
        поля_р = прописная_р if прописной else строчная_р
        if поля is None:
            поля = прописная if прописная is not None else строчная
            поля_р = прописная_р if прописная_р is not None else строчная_р
        if норма is None or поля is None:
            continue
        # составной знак едет за базой; с нуля базы-символа может не быть в
        # расчёте (½ из .numr и .dnom) — тогда он ставится по норме сам
        if master.component_bases(i) and not с_нуля:
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
            if с_нуля:
                return было + irnd(н.median * просвет - штамб - float(было))
            сдвиг = min(max(н.target(доля) * просвет - штамб - float(было), -предел), предел)
            return было + irnd(сдвиг)

        новыйL = поле(слева, норма[0], lsb, поля[1])
        новыйR = поле(справа, норма[1], rsb, поля[0])
        плотЛ = плотП = 0
        if поля_р is not None and поля_р != поля:
            # разрядка: знак держит свою долю просвета (новую, если правится)
            правится = max(abs(новыйL - lsb), abs(новыйR - rsb)) >= порог
            if not правится:
                новыйL, новыйR = lsb, rsb
            долиЛ = норма[0].target(слева) if правится else слева
            долиП = норма[1].target(справа) if правится else справа
            просвет_р = поля_р[0] + поля_р[1]
            плотЛ = irnd(долиЛ * (просвет_р - просвет) - (поля_р[1] - поля[1]))
            плотП = irnd(долиП * (просвет_р - просвет) - (поля_р[0] - поля[0]))
            новыйL += плотЛ
            новыйR += плотП
        чернила = advance - lsb - rsb
        вышло.append(SpacingItem(имя, свой_код, OTHER, advance, lsb, rsb, 0.0, 0.0,
                                 новыйL, новыйR, новыйL + чернила + новыйR,
                                 dense_left=плотЛ, dense_right=плотП))
    return вышло


def figure_items(master, rule, эталоны, эталоны_ровно, замеры, шаг, в_пределе, порог, общая, fixed):
    """Пропорциональные цифры 0–9 (поправка окна, вне исходного правила):
    белое в полосе от базовой линии до медианы верхов цифр, цель — белое на
    строку той группы, чей рост у цифр: выше середины между ростом и
    капителью — прописных, ниже — строчных (нет такой группы — другой).
    Цифры одной ширины (табличные) не трогаются. В исходном правиле цифры
    не мерятся вовсе, а кернинг файла заменяется целиком — у шрифтов, где
    пары цифр кернились, они расходятся (опыт на 56 шрифтах 24.10.2026:
    ровность цифр 18,7 % против 16,0 % у оригиналов; с этим и кернингом
    пар цифр — 12,2 %)"""
    from .geometry import contours_rect
    цифры = []
    for к in range(0x30, 0x3A):
        i = master.glyph(к)
        if i is None or master.component_bases(i):
            continue
        рамка = contours_rect(master.contours(i))
        if рамка is None or master.advance(i) <= 0:
            continue
        цифры.append((к, i, рамка))
    if len(цифры) < 10 or len({master.advance(i) for _, i, _ in цифры}) == 1:
        return []
    верх = median([р[3] for _, _, р in цифры])
    _, капитель, рост = heights(master, rule.robust_heights)
    г = UPPER if верх >= (рост + капитель) / 2 else LOWER
    if г not in эталоны:
        г = LOWER if г == UPPER else UPPER
    if г not in эталоны:
        return []
    высоты = [з.высотаСлева for з in замеры if з.группа == г]
    if not высоты:
        return []
    высота = median(высоты)
    на_ряд = эталоны[г] / высота
    на_ряд_ровно = эталоны_ровно[г] / высота
    upm = float(master.upm)
    вышло = []
    for к, i, рамка in цифры:
        знак = master.glyphs[i]
        if знак.name in fixed:
            continue
        профиль = ink_profile(знак.edges, 0.0, верх, шаг)
        if профиль is None:
            continue
        л, п, в = white_soft(профиль, float(знак.advance), rule, upm) if rule.soft \
            else white(профиль, float(знак.advance), rule.depth * upm)
        if not в > 0:
            continue
        lsb = irnd(рамка[0])
        rsb = знак.advance - irnd(рамка[2])
        плотЛ = плотП = 0
        if общая:
            новыйL = irnd(float(lsb) + в_пределе(на_ряд_ровно - л / в, г))
            новыйR = irnd(float(rsb) + в_пределе(на_ряд_ровно - п / в, г))
            if rule.per_side:
                новыйL = новыйL if abs(новыйL - lsb) >= порог else lsb
                новыйR = новыйR if abs(новыйR - rsb) >= порог else rsb
            elif max(abs(новыйL - lsb), abs(новыйR - rsb)) < порог:
                новыйL, новыйR = lsb, rsb
            плотЛ = плотП = irnd(на_ряд - на_ряд_ровно)
            новыйL += плотЛ
            новыйR += плотП
        else:
            новыйL = irnd(float(lsb) + в_пределе(на_ряд - л / в, г))
            новыйR = irnd(float(rsb) + в_пределе(на_ряд - п / в, г))
            if rule.per_side and max(abs(новыйL - lsb), abs(новыйR - rsb)) >= порог:
                новыйL = новыйL if abs(новыйL - lsb) >= порог else lsb
                новыйR = новыйR if abs(новыйR - rsb) >= порог else rsb
        чернила = знак.advance - lsb - rsb
        вышло.append(SpacingItem(знак.name, к, OTHER, знак.advance, lsb, rsb, л, п,
                                 новыйL, новыйR, новыйL + чернила + новыйR,
                                 dense_left=плотЛ, dense_right=плотП))
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
