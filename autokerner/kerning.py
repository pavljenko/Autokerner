"""Кернинг: мера пары, матрица всех пар, классы и запись.

Перенос правила кернинга исходной программы (Swift).

Карман пары — насколько ближайший просвет между чернилами (с тенью
выступов) шире габаритного. Закон закрывает долю кармана, своя у каждого
рода пар (буквы, низкие знаки, верхние, средние). Сторож зазора не даёт
чернилам сойтись ближе 25 тысячных кегля. Классы собираются по самим
значениям пар — одни на все мастера, числа по мастерам.

Края знаков хранятся в одинарной точности, как в исходной программе (`Float`):
мера сравнивает их так же, и числа выходят те же до единицы.
"""

import math
from array import array
from operator import and_, itemgetter, sub
from struct import Struct

from .geometry import INF, INT16_MAX, clamp16, contours_rect, f32, ink_profile, irnd, median
from .spacing import SpacingRule, base_body, heights, is_digit_name, is_number_code, stem_sides
from .unicode_props import is_nontext

LETTER, LOW, HIGH, MIDDLE = 0, 1, 2, 3
KINDS = (LETTER, LOW, HIGH, MIDDLE)


class LawPart:
    __slots__ = ("share", "dead_zone", "slope")

    def __init__(self, share, dead_zone, slope):
        self.share = share
        self.dead_zone = dead_zone
        self.slope = slope


# Цифры со знаками внутри чисел: как в правиле, без столкновений, не кернить
FIGURES_RULE, FIGURES_SAFE, FIGURES_OFF = "rule", "safe", "off"
# Обычный карман шрифта: наибольший из пар-образцов (как в правиле) или медиана
NEUTRAL_MAX, NEUTRAL_MEDIAN = "max", "median"


class KernLaw:
    """Закон кернинга: доля кармана, мёртвая зона и
    наклон тени по родам пар; зазор, порог «касания» и порог записи — в
    тысячных кегля"""

    def __init__(self, threshold=10, strength=1.0, clearance=25, figures=FIGURES_RULE,
                 neutral=NEUTRAL_MAX, marks_apart=False, skip_nontext=False):
        self.letters = LawPart(0.45, 40, 3)
        self.low = LawPart(0.40, 0, 1)
        self.high = LawPart(0.48, 0, 1)
        self.middle = LawPart(0.32, 20, 1)
        if strength != 1.0:
            # сила кернинга: какую долю кармана закрывать — у всех родов разом
            for часть in (self.letters, self.low, self.high, self.middle):
                часть.share *= strength
        self.clearance = clearance
        self.touching = 5
        self.threshold = threshold
        # цифры с запятой, точкой и двоеточием (`number_separators`)
        self.figures = figures
        # обычный карман шрифта — наибольший из пар HO, no… или их медиана
        # (`make_context`)
        self.neutral = neutral
        # знаки препинания на разной высоте не заходят друг под друга
        # (`marks_apart`)
        self.marks_apart = marks_apart
        # метки, отдельные акценты и «_» не кернятся (`nontext_glyphs`)
        self.skip_nontext = skip_nontext

    def part(self, kind):
        return (self.letters, self.low, self.high, self.middle)[kind]

    @property
    def slopes(self):
        return sorted({self.letters.slope, self.low.slope, self.high.slope, self.middle.slope})


class KernRule:
    """Правило записи: порог пары и точность класса —
    тысячные кегля, предел именных пар (0 или None — без предела: пишутся
    все пары, что разошлись с классом, и точность не огрубляется)"""

    def __init__(self, threshold=8, visible=10, exception_limit=12000):
        self.threshold = threshold
        self.visible = visible
        self.exception_limit = exception_limit

    @property
    def limit(self):
        return self.exception_limit if self.exception_limit else 1 << 62

    def steps(self):
        """Ступени точности записи: с заданной, затем грубее"""
        ступени = [с for с in PRECISION_STEPS if с[0] >= self.visible]
        if self.visible < PRECISION_STEPS[0][0]:
            ступени = [(self.visible, PRECISION_STEPS[0][1])] + ступени
        return ступени or [PRECISION_STEPS[-1]]


# Ступени записи: точность в тысячных и доля знаков, на которую знаку
# позволено разойтись с классом
PRECISION_STEPS = [(10, 10), (10, 30), (20, 30), (20, 100), (30, 30), (30, 100), (45, 100)]

CLASS_LIMIT = 200


class Grid:
    """Сетка высот: от −0,6 до 1,5 кегельной, шаг — двухсотая"""
    __slots__ = ("low", "high", "step")

    def __init__(self, upm):
        u = float(upm)
        self.low = -0.6 * u
        self.high = 1.5 * u
        self.step = u / 200


def x_height_of(master):
    """Рост строчных для кернинга: объявленный, иначе верх «x», иначе
    половина кегля"""
    if master.x_height and master.x_height > 0:
        return float(master.x_height)
    i = master.glyph(0x78)
    if i is not None:
        верхи = [c.top for c in master.contours(i)]
        if верхи and max(верхи) > 0:
            return max(верхи)
    return float(master.upm) / 2


def _f32_list(values):
    return array("f", values).tolist()


def _shadow(край, наклон, шаг, левый):
    вышло = list(край)
    d = наклон * шаг
    n = len(вышло)
    if n <= 1:
        return вышло
    if левый:
        for i in range(1, n):
            v = вышло[i - 1] + d
            if v < вышло[i]:
                вышло[i] = v
        for i in range(n - 2, -1, -1):
            v = вышло[i + 1] + d
            if v < вышло[i]:
                вышло[i] = v
    else:
        for i in range(1, n):
            v = вышло[i - 1] - d
            if v > вышло[i]:
                вышло[i] = v
        for i in range(n - 2, -1, -1):
            v = вышло[i + 1] - d
            if v > вышло[i]:
                вышло[i] = v
    return вышло


class KernShape:
    """Знак глазами кернинга: края чернил на каждой высоте сетки и тени
    выступов на каждый наклон закона"""
    __slots__ = ("advance", "kind", "left", "right", "L", "R", "SL", "SR", "rows",
                 "ink_low", "ink_high")


def make_shape(edges, advance, grid, рост, law):
    """Форма знака; нет чернил или нулевая ширина — None"""
    if not advance > 0:
        return None
    профиль = ink_profile(edges, grid.low, grid.high, grid.step)
    if профиль is None:
        return None
    слева = [x if x is not None else INF for x in профиль.left]
    справа = [x if x is not None else -INF for x in профиль.right]
    первая = next((i for i, x in enumerate(слева) if x != INF), None)
    if первая is None:
        return None
    последняя = max(i for i, x in enumerate(слева) if x != INF)
    низ = grid.low + (первая + 0.5) * grid.step
    верх = grid.low + (последняя + 0.5) * grid.step
    if верх <= 0.45 * рост:
        вид = LOW
    elif низ >= 0.5 * рост and верх >= 0.9 * рост:
        вид = HIGH
    elif низ >= 0.03 * рост and верх <= 1.15 * рост:
        вид = MIDDLE
    else:
        вид = LETTER
    s = KernShape()
    s.advance = float(advance)
    s.kind = вид
    s.left = min(слева)
    s.right = max(справа)
    s.L = _f32_list(слева)
    s.R = _f32_list(справа)
    s.SL = []
    s.SR = []
    for наклон in law.slopes:
        s.SL.append(_f32_list(_shadow(слева, наклон, grid.step, True)))
        s.SR.append(_f32_list(_shadow(справа, наклон, grid.step, False)))
    s.rows = len(слева)
    s.ink_low = первая
    s.ink_high = последняя
    return s


def empty_shape(like):
    """Знак без чернил той же сетки: пары с ним — ноль"""
    s = KernShape()
    s.advance = like.advance
    s.kind = LETTER
    s.left = 0.0
    s.right = 0.0
    s.rows = like.rows
    s.L = [INF] * like.rows
    s.R = [-INF] * like.rows
    s.SL = [[INF] * like.rows for _ in like.SL]
    s.SR = [[-INF] * like.rows for _ in like.SR]
    s.ink_low = 0
    s.ink_high = like.rows - 1
    return s


def closest(правый_край, левый_край, от, до):
    """Ближайший просвет между правым краем левого знака и левым краем
    правого по строкам от…до — в одинарной точности, как в исходной программе"""
    if от > до:
        return INF
    return f32(min(map(sub, левый_край[от:до + 1], правый_край[от:до + 1])))


def pair_kind(л, п):
    """Род пары: малый знак главнее буквы, низкий и верхний — среднего"""
    for вид in (LOW, HIGH, MIDDLE):
        if л == вид or п == вид:
            return вид
    return LETTER


def usual_gap(shape):
    if shape is None:
        return None
    g = shape.advance + closest(shape.R, shape.L, shape.ink_low, shape.ink_high)
    return g if g != INF else None


def pocket(л, п, law):
    часть = law.part(pair_kind(л.kind, п.kind))
    номер = law.slopes.index(часть.slope)
    сТенью = л.advance + closest(л.SR[номер], п.SL[номер],
                                 min(л.ink_low, п.ink_low), max(л.ink_high, п.ink_high))
    return max(0, сТенью - (л.advance - л.right + п.left))


def raw_gap(л, п):
    сырое = л.advance + closest(л.R, п.L, max(л.ink_low, п.ink_low), min(л.ink_high, п.ink_high))
    return сырое if сырое != INF else None


def floor_of(вид, neutral_pocket):
    return neutral_pocket if вид == LETTER or вид == MIDDLE else 0


def law_value(л, п, часть, номер, пол, upm):
    """Закон кармана без сторожа: сколько закрыть кармана, в единицах
    шрифта; общих высот нет — None"""
    тысячная = float(upm) / 1000
    габарит = л.advance - л.right + п.left
    сТенью = л.advance + closest(л.SR[номер], п.SL[номер],
                                 min(л.ink_low, п.ink_low), max(л.ink_high, п.ink_high))
    if сТенью == INF:
        return None
    карман = max(0, сТенью - габарит) / тысячная
    сверх = max(0, карман - часть.dead_zone)
    if пол > часть.dead_zone:
        колено = пол + 60
        if карман <= пол:
            сверх = 0
        elif карман < колено:
            сверх *= (карман - пол) / (колено - пол)
    return -часть.share * сверх * тысячная


def kernel(л, п, часть, номер, пол, law, upm, обычный, закон=None):
    """Ядро меры: (число, запас до зазора). `закон` — закон кармана, уже
    посчитанный по телу основы"""
    тысячная = float(upm) / 1000
    k = закон if закон is not None else law_value(л, п, часть, номер, пол, upm)
    if k is None:
        return (0, INT16_MAX)
    сырое = л.advance + closest(л.R, п.L, max(л.ink_low, п.ink_low), min(л.ink_high, п.ink_high))
    запас = INT16_MAX
    зазор = law.clearance * тысячная
    if сырое != INF:
        if обычный is not None:
            зазор = max(0, min(зазор, обычный / 2))
        if k < 0:
            k = max(k, min(0, зазор - сырое))
        раздвигать = (обычный if обычный is not None else INF) > law.touching * тысячная
        if раздвигать and сырое < зазор:
            k = max(k, зазор - сырое)
        if раздвигать:
            остаток = сырое + k - зазор
            запас = clamp16(int(max(0, остаток) // 1))
    число = 0 if abs(k) < law.threshold * тысячная else irnd(k)
    if запас != INT16_MAX and сырое != INF:
        запас = clamp16(int(max(0, сырое + float(число) - зазор) // 1))
    return (число, запас)


def clearance_of(law, upm, обычный):
    закон = law.clearance * float(upm) / 1000
    if обычный is None:
        return закон
    return max(0, min(закон, обычный / 2))


class KernContext:
    __slots__ = ("usual_gap", "neutral_pocket")

    def __init__(self, usual_gap_=None, neutral_pocket=0.0):
        self.usual_gap = usual_gap_
        self.neutral_pocket = neutral_pocket


def make_context(master, grid, рост, law, shape_of):
    def форма(код):
        i = master.glyph(код)
        return shape_of(i) if i is not None else None

    обычный = None
    for код in (0x6E, 0x43D, 0x48):
        g = usual_gap(форма(код))
        if g is not None:
            обычный = g
            break
    тысячная = float(master.upm) / 1000
    карманы = []
    for л, п in ((0x48, 0x4F), (0x4F, 0x48), (0x6E, 0x6F), (0x6F, 0x6E),
                 (0x41D, 0x41E), (0x41E, 0x41D), (0x43D, 0x43E), (0x43E, 0x43D)):
        a = форма(л)
        b = форма(п)
        if a is None or b is None:
            continue
        карманы.append(pocket(a, b, law) / тысячная)
    # Пары тише обычного кармана не кернятся. Наибольший из образцов — как в
    # правиле; медиана — поправка окна: у неровных акцидентных форм одна
    # острая O задирала порог для всех пар (замер: 61,6 при медиане 25),
    # и AT, LT оставались без кернинга. Медиана ближе к ручному кернингу
    # на трёх шрифтах с неровными или засечными формами, у ровных — то же
    if not карманы:
        нейтральный = 0.0
    elif getattr(law, "neutral", NEUTRAL_MAX) == NEUTRAL_MEDIAN:
        нейтральный = max(0.0, median(карманы))
    else:
        нейтральный = max(0.0, max(карманы))
    return KernContext(обычный, нейтральный + 5 if нейтральный > 0 else 0)


class KernMatrix:
    """Кернинг всех пар мастера: строка — левый знак пары"""

    def __init__(self, names, coded, digits, values, slack=None, clearance=0.0, collisions=None):
        self.names = names
        self.coded = coded
        self.digits = digits
        self.values = values
        self.slack = slack or []
        self.clearance = clearance
        # цифры, что сходятся через запятую, точку, двоеточие:
        # [(цифра, знак, цифра, на сколько ближе зазора)] от худших
        self.collisions = collisions or []

    @property
    def n(self):
        return len(self.names)


MAXCODE = 1 << 62


def _candidates(master, names):
    коды = master.codes_by_glyph
    кандидаты = []
    if names is not None:
        for имя in names:
            i = master.by_name(имя)
            i = -1 if i is None else i
            код = min(коды[i]) if i >= 0 and i in коды else MAXCODE
            кандидаты.append((i, код, имя))
    else:
        for i in range(master.num_glyphs):
            имя = master.name(i)
            if имя == ".notdef":
                continue
            кандидаты.append((i, min(коды[i]) if i in коды else MAXCODE, имя))
        кандидаты.sort(key=lambda к: (к[1], к[2]))
    return кандидаты


def _code_in_name(кусок):
    """Код из имени вида «uni0306» или «u1F600», иначе None"""
    for приставка, длины in (("uni", (4,)), ("u", (4, 5, 6))):
        хвост = кусок[len(приставка):]
        if кусок.startswith(приставка) and len(хвост) in длины:
            try:
                return int(хвост, 16)
            except ValueError:
                return None
    return None


def nontext_glyphs(master):
    """Знаки, что в тексте не стоят рядом с буквами (`is_nontext`): по
    кодам, а у знаков без кода — по имени основы («acutecomb.case»,
    «uni0306.cap»). Их пары с буквами не встречаются, а кернинг их раздувает
    файл и забивает верх списка правок"""
    коды = master.codes_by_glyph
    вне = set()
    for i, свои in коды.items():
        if свои and all(is_nontext(к) for к in свои):
            вне.add(master.name(i))
    for i in range(master.num_glyphs):
        if i in коды:
            continue
        имя = master.name(i)
        куски = [к for к in имя.split(".")[0].split("_") if к]
        if куски and all(к in вне or is_nontext(_code_in_name(к) or -1) for к in куски):
            вне.add(имя)
    return вне


def matrix_names(master, law):
    """Знаки, которые можно кернить: с чернилами и шириной, по коду, затем
    по имени; с `law.skip_nontext` — без меток, отдельных акцентов и «_»"""
    grid = Grid(master.upm)
    рост = x_height_of(master)
    вне = nontext_glyphs(master) if getattr(law, "skip_nontext", False) else ()
    вышло = []
    for i, _, имя in _candidates(master, None):
        if имя in вне:
            continue
        g = master.glyphs[i]
        if make_shape(g.edges, g.advance, grid, рост, law) is not None:
            вышло.append(имя)
    return вышло


def make_matrix(master, law, names=None, progress=None):
    """Матрица всех пар мастера. `names` — общий
    список знаков на все мастера; знак без формы на этом мастере — пустой"""
    grid = Grid(master.upm)
    рост = x_height_of(master)
    кандидаты = _candidates(master, names)
    кэш = {}

    def форма_глифа(i):
        if i not in кэш:
            g = master.glyphs[i]
            кэш[i] = make_shape(g.edges, g.advance, grid, рост, law)
        return кэш[i]

    формы = [форма_глифа(i) if i >= 0 else None for i, _, _ in кандидаты]
    if names is not None:
        образец = next((ф for ф in формы if ф is not None), None)
        if образец is not None:
            формы = [ф if ф is not None else empty_shape(образец) for ф in формы]

    имена, глифы, скодом, коды, знаки, цифры = [], [], [], [], [], []
    for (i, код, имя), форма in zip(кандидаты, формы):
        if форма is None:
            continue
        имена.append(имя)
        глифы.append(i)
        скодом.append(код != MAXCODE)
        коды.append(код)
        знаки.append(форма)
        цифра = код != MAXCODE and is_number_code(код)
        цифры.append(цифра or is_digit_name(имя))
    n = len(знаки)
    if n == 0:
        return KernMatrix([], [], [], [])

    наклоны = law.slopes
    части = []
    for вид in KINDS:
        часть = law.part(вид)
        части.append((часть, наклоны.index(часть.slope)))
    свойства = make_context(master, grid, рост, law, форма_глифа)
    полы = [floor_of(вид, свойства.neutral_pocket) for вид in KINDS]
    upm = master.upm

    # знак с диакритикой, у которого тело в строке то же, что у основы,
    # кернится законом основы с поправкой на место тела
    индекс = {}
    for j, имя in enumerate(имена):
        индекс.setdefault(имя, j)
    _, капитель, рост_букв = heights(master)
    тела = [-1] * n
    поправки = [0.0] * (n * 2)
    for i in range(n):
        if коды[i] == MAXCODE or глифы[i] < 0:
            continue
        т = base_body(коды[i], глифы[i], master, рост_букв, max(капитель, рост_букв + 1), SpacingRule())
        if т is None:
            continue
        j = индекс.get(master.name(т[0]))
        if j is None or j == i:
            continue
        тела[i] = j
        поправки[i * 2] = (знаки[j].advance - т[2][1]) - (знаки[i].advance - т[1][1])
        поправки[i * 2 + 1] = т[2][0] - т[1][0]

    обычный = свойства.usual_gap
    значения, сторож = _pairs(знаки, цифры, тела, поправки, части, полы, law, upm, обычный, progress)
    _number_marks(значения, сторож, n, знаки, коды, цифры, master, рост, law)
    зазор = clearance_of(law, upm, обычный)
    столкновения = number_separators(значения, сторож, n, знаки, коды, цифры, зазор,
                                     getattr(law, "figures", FIGURES_RULE))
    if getattr(law, "marks_apart", False):
        marks_apart(значения, сторож, n, знаки, зазор, law.threshold * float(upm) / 1000)
    return KernMatrix(имена, скодом, цифры, значения, сторож, зазор,
                      [(имена[a], имена[b], имена[c], г) for a, b, c, г in столкновения])


_F32 = Struct("f")


def _pairs(знаки, цифры, тела, поправки, части, полы, law, upm, обычный, progress=None):
    """Все пары матрицы: `kernel` и `law_value`, развёрнутые в один цикл.

    Числа те же, что у `kernel` пара за парой (сторож —
    `test_kerning.FastLoopTest`): действия и их порядок повторены дословно,
    убраны только вызовы функций и поиски по атрибутам — на шрифте в две
    тысячи знаков это четыре миллиона пар"""
    n = len(знаки)
    значения = [0] * (n * n)
    сторож = [INT16_MAX] * (n * n)
    тысячная = float(upm) / 1000
    зазор = law.clearance * тысячная
    if обычный is not None:
        зазор = max(0, min(зазор, обычный / 2))
    раздвигать = (обычный if обычный is not None else INF) > law.touching * тысячная
    порог = law.threshold * тысячная
    pack, unpack = _F32.pack, _F32.unpack
    род = [[pair_kind(a, b) for b in KINDS] for a in KINDS]
    законы = [(ч.share, ч.dead_zone, номер) for ч, номер in части]
    формы = [(ф.kind, ф.ink_low, ф.ink_high, ф.L, ф.SL, ф.left) for ф in знаки]
    законы_основ = {}
    for л in range(n):
        if progress and л % 32 == 0:
            progress(л, n)
        фл = знаки[л]
        цифра_л = цифры[л]
        вид_л = фл.kind
        род_л = род[вид_л]
        тело_л = тела[л]
        низ_л, верх_л = фл.ink_low, фл.ink_high
        R_л, SR_л = фл.R, фл.SR
        ширина = фл.advance
        габарит_л = ширина - фл.right
        строка = л * n
        for п in range(n):
            if цифра_л and цифры[п]:
                continue
            вид_п, низ_п, верх_п, L_п, SL_п, левый_п = формы[п]
            вид_пары = род_л[вид_п]
            тело_п = тела[п]
            k = None
            if тело_л >= 0 or тело_п >= 0:
                # знак с диакритикой — законом основы; закон пары основ
                # один на все её знаки с метками — считается раз
                а = тело_л if тело_л >= 0 else л
                б = тело_п if тело_п >= 0 else п
                ключ = а * n + б
                if ключ in законы_основ:
                    k = законы_основ[ключ]
                else:
                    вид = род[знаки[а].kind][знаки[б].kind]
                    частьО, номерО = части[вид]
                    k = law_value(знаки[а], знаки[б], частьО, номерО, полы[вид], upm)
                    законы_основ[ключ] = k
                if k is not None:
                    k = k + поправки[л * 2] + поправки[п * 2 + 1]
            if k is None:
                # закон кармана (`law_value`)
                доля, мёртвая, номер = законы[вид_пары]
                от = низ_л if низ_л < низ_п else низ_п
                до = верх_л if верх_л > верх_п else верх_п
                m = min(map(sub, SL_п[номер][от:до + 1], SR_л[номер][от:до + 1]))
                if m == INF:
                    k = None
                else:
                    сТенью = ширина + unpack(pack(m))[0]
                    карман = max(0, сТенью - (габарит_л + левый_п)) / тысячная
                    сверх = max(0, карман - мёртвая)
                    пол = полы[вид_пары]
                    if пол > мёртвая:
                        колено = пол + 60
                        if карман <= пол:
                            сверх = 0
                        elif карман < колено:
                            сверх *= (карман - пол) / (колено - пол)
                    k = -доля * сверх * тысячная
            if k is None:
                continue
            # сторож зазора (`kernel`)
            от = низ_л if низ_л > низ_п else низ_п
            до = верх_л if верх_л < верх_п else верх_п
            if от <= до:
                m = min(map(sub, L_п[от:до + 1], R_л[от:до + 1]))
                сырое = ширина + unpack(pack(m))[0] if m != INF else INF
            else:
                сырое = INF
            запас = INT16_MAX
            if сырое != INF:
                if k < 0:
                    k = max(k, min(0, зазор - сырое))
                if раздвигать and сырое < зазор:
                    k = max(k, зазор - сырое)
            число = 0 if abs(k) < порог else irnd(k)
            if раздвигать and сырое != INF:
                запас = clamp16(int(max(0, сырое + k - зазор) // 1))
                if запас != INT16_MAX:
                    запас = clamp16(int(max(0, сырое + float(число) - зазор) // 1))
            значения[строка + п] = clamp16(число)
            сторож[строка + п] = запас
    return значения, сторож


def adjust_values(matrix, round_to=1, max_tight=None, max_loose=None):
    """Значения пар по выбору пользователя, до сборки классов.

    `round_to` — шаг: число встаёт на кратное шагу в сторону разрядки
    (−13 при шаге 5 — −10, +13 — +15), чтобы округление не сжало пару
    ближе сторожа зазора. `max_tight` — пара не сжимается сильнее этого
    (в единицах шрифта). `max_loose` — сторож зазора не раздвигает пару
    сильнее этого: хвост Q над нижним выносным Д у тестового шрифта давал
    +533. Чернила такой пары сходятся ближе зазора — запас пары ноль, и
    классы её не сжимают"""
    if round_to <= 1 and not max_tight and not max_loose:
        return matrix
    значения, запасы = matrix.values, matrix.slack
    for i, v in enumerate(значения):
        if not v:
            continue
        if round_to > 1:
            v = -((-v) // round_to) * round_to
        if max_tight and v < -max_tight:
            v = -max_tight
        if max_loose and v > max_loose:
            v = max_loose
            if запасы:
                запасы[i] = 0
        значения[i] = clamp16(v)
    return matrix


# Пороги для цифр со знаками: просвет пары (с кернингом) в долях просвета
# между штамбами «nn», верхняя четверть по замерам выверенных шрифтов:
# знак → цифра, цифра → знак
NUMBER_LIMITS = {
    0x2E: (1.25, 1.27), 0x2C: (1.18, 1.30), 0x3A: (1.13, 1.28), 0x3B: (1.13, 1.28),
    0x2D: (1.83, 1.26), 0x2013: (1.76, 1.13), 0x2014: (1.82, 1.28), 0x2F: (1.07, 1.17),
    0x25: (1.12, 1.18), 0x28: (1.29, 1.08), 0x29: (1.06, 1.29),
}


# Знаки внутри чисел: 7,4 · 3.5 · 12:30
NUMBER_SEPARATORS = (0x2C, 0x2E, 0x3A)


def number_separators(значения, запасы, n, знаки, коды, цифры, зазор, mode=FIGURES_RULE):
    """Цифры с запятой, точкой и двоеточием — выбор пользователя, вне
    исходного правила. Правило подтягивает такие пары по одной (у
    тестового шрифта «7,» — −362), и в числе «7,4» цифры через запятую наезжают
    друг на друга.

    `FIGURES_SAFE` — «знак + цифра» не кернится в минус: цифра справа не
    нависает над знаком (у тестового шрифта «,4» было −98, и четвёрка
    накрывала запятую; наборные шрифты эту пару не кернят — между запятой
    и цифрой у них 65–88 тысячных). Затем «цифра + знак» ослабляется ровно
    настолько, чтобы цифры через знак стояли не ближе, чем стояли бы рядом
    без знака (знак не отнимает места у числа), и не ближе зазора, — не
    дальше нуля: знак препинания держится за цифру слева («1917,» остаётся
    подтянутой). Одного зазора мало — замер: «7,4» с ним выходит слипшимся.
    `FIGURES_OFF` — эти пары не кернятся.

    Ответ — оставшиеся столкновения [(цифра, знак, цифра, глубина)] по
    номерам знаков, от худших (глубина — на сколько единиц ближе зазора)"""
    цифрыИ = [i for i in range(n) if цифры[i]]
    знакиИ = [i for i in range(n) if коды[i] in NUMBER_SEPARATORS]
    if not цифрыИ or not знакиИ:
        return []
    сырые = {}

    def сырое(a, b):
        к = a * n + b
        if к not in сырые:
            сырые[к] = raw_gap(знаки[a], знаки[b])
        return сырые[к]

    for р in знакиИ:
        if mode == FIGURES_OFF:
            for ц in цифрыИ:
                for к in (ц * n + р, р * n + ц):
                    значения[к] = 0
            continue
        if mode != FIGURES_SAFE:
            continue
        for ц in цифрыИ:
            if значения[р * n + ц] < 0:
                значения[р * n + ц] = 0
        ширина = знаки[р].advance
        for фаза in (0, 1):
            for л in цифрыИ:
                for п in цифрыИ:
                    г = сырое(л, п)
                    if г is None:
                        continue
                    кл, кп = л * n + р, р * n + п
                    нехватка = max(0.0, зазор - г) - (ширина + значения[кл] + значения[кп])
                    if нехватка <= 0:
                        continue
                    к = кп if фаза == 0 else кл
                    новое = min(0, значения[к] + int(math.ceil(нехватка)))
                    if новое > значения[к]:
                        значения[к] = новое
    # запас до сторожа — ноль у всех пар цифр с этими знаками: класс не
    # вправе поджать их сильнее (иначе сборка классов возвращала «7,» к
    # −166 при −130 по замеру); правленые без режима — не бывает
    if mode in (FIGURES_SAFE, FIGURES_OFF):
        for р in знакиИ:
            for ц in цифрыИ:
                запасы[ц * n + р] = 0
                запасы[р * n + ц] = 0

    вышло = []
    for р in знакиИ:
        ширина = знаки[р].advance
        for л in цифрыИ:
            for п in цифрыИ:
                г = сырое(л, п)
                if г is None:
                    continue
                глубина = зазор - (г + ширина + значения[л * n + р] + значения[р * n + п])
                if глубина > 0:
                    вышло.append((л, р, п, глубина))
    вышло.sort(key=lambda с: -с[3])
    return вышло


def marks_apart(значения, запасы, n, знаки, зазор, порог):
    """Знаки препинания на разной высоте — кавычка и запятая, дефис и
    точка — не заходят друг под друга: поправка окна, вне исходного
    правила. Общих высот у такой пары нет, сторож зазора её не видит, и
    закон кармана тянет её, пока не упрётся тень: у тестового шрифта «’,» —
    −192, запятая встаёт под кавычку. Наборные шрифты держат между ними
    37–85 тысячных. Здесь пара сходится не ближе зазора между рамками
    чернил по горизонтали; раздвигать не раздвигает. Буквы не трогаются:
    кавычка над «л» — дело вкуса, у хороших шрифтов бывает"""
    метки = [i for i in range(n) if знаки[i].kind != LETTER]
    for л in метки:
        фл = знаки[л]
        for п in метки:
            фп = знаки[п]
            if raw_gap(фл, фп) is not None:
                continue
            к = л * n + п
            габарит = фл.advance - фл.right + фп.left
            предел = min(0.0, зазор - габарит)
            v = значения[к]
            if v < предел:
                v = int(math.ceil(предел))
                if abs(v) < порог:
                    v = 0
                значения[к] = v
            if v < 0:
                # класс не вправе поджать пару сильнее
                запасы[к] = clamp16(int(max(0, габарит + v - зазор) // 1))


def _number_marks(значения, запасы, n, знаки, коды, цифры, master, рост, law):
    """Пары «цифра + знак» и «знак + цифра»"""
    эталон = next((master.glyph(к) for к in (0x6E, 0x43D, 0x48) if master.glyph(к) is not None), None)
    if эталон is None:
        return
    поля = stem_sides(master, эталон, рост / 2)
    if поля is None:
        return
    просвет = поля[0] + поля[1]
    if not просвет > 0:
        return
    тысячная = float(master.upm) / 1000
    зазор = law.clearance * тысячная
    цифрыИ = [i for i in range(n) if цифры[i]]
    знакиИ = [i for i in range(n) if коды[i] in NUMBER_LIMITS]

    def подтянуть(л, п, предел):
        сырое = raw_gap(знаки[л], знаки[п])
        сырое = INF if сырое is None else сырое
        пара = сырое if сырое != INF else знаки[л].advance - знаки[л].right + знаки[п].left
        было = float(значения[л * n + п])
        if not (пара + было) / просвет > предел:
            return
        k = предел * просвет - пара
        k = max(k, было - 1.5 * просвет)
        if сырое != INF:
            k = max(k, min(было, зазор - сырое))
        if not k < было:
            return
        число = irnd(k)
        значения[л * n + п] = clamp16(число)
        if сырое != INF:
            запасы[л * n + п] = clamp16(int(max(0, сырое + float(число) - зазор) // 1))

    for ц in цифрыИ:
        for з in знакиИ:
            предел = NUMBER_LIMITS[коды[з]]
            подтянуть(ц, з, предел[1])
            подтянуть(з, ц, предел[0])


# ── классы по значениям ──

def _clusters(ряды, n, допуск, бюджет, тихо, предел, progress=None):
    """Жадная сборка классов в порядке шрифта:
    знак идёт к образцу, с которым у него меньше всего пар, расходящихся
    больше чем на допуск, если таких не больше бюджета; иначе — новый класс.

    Счёт расходящихся пар — кусками, встроенными средствами Python, а
    столбцы, где ряды разнятся, идут вперёд: счёт раньше доходит до порога
    и обрывается. Ответ от этого не меняется — тот, у кого чужих меньше
    порога, досчитывается целиком. `progress(знак, n)` — ход (бросит
    исключение — сборка прервётся)"""
    класс = [-1] * n
    представители = []
    if n == 0:
        return класс, представители
    длина = len(ряды[0])
    ненули = [len(столбец) - столбец.count(0) for столбец in zip(*ряды)]
    порядок = sorted(range(длина), key=lambda j: -ненули[j])
    if длина > 1:
        взять = itemgetter(*порядок)
        ряды = [взять(р) for р in ряды]
    свои = frozenset(range(-допуск, допуск + 1)).__contains__
    куски = [(a, min(a + _CHUNK, длина)) for a in range(0, длина, _CHUNK)]
    for знак in range(n):
        if progress is not None and знак % 64 == 0:
            progress(знак, n)
        ряд = ряды[знак]
        if max(ряд) < тихо and min(ряд) > -тихо:
            continue
        полно = len(представители) >= предел
        нашёлся = -1
        лучше = (1 << 62) if полно else бюджет + 1
        for номер, образец in enumerate(представители):
            база = ряды[образец]
            чужих = 0
            for a, b in куски:
                чужих += (b - a) - sum(map(свои, map(sub, ряд[a:b], база[a:b])))
                if чужих >= лучше:
                    break
            if чужих < лучше:
                нашёлся = номер
                лучше = чужих
                if чужих == 0:
                    break
        if нашёлся < 0:
            нашёлся = len(представители)
            представители.append(знак)
        класс[знак] = нашёлся
    return класс, представители


_CHUNK = 64


class KernGroups:
    def __init__(self, left_class, right_class, left_members, right_members, left_sample, right_sample):
        self.left_class = left_class
        self.right_class = right_class
        self.left_members = left_members
        self.right_members = right_members
        self.left_sample = left_sample
        self.right_sample = right_sample

    @property
    def left_count(self):
        return len(self.left_members)

    @property
    def right_count(self):
        return len(self.right_members)


def group_by_values(матрицы, тихо, допуск, бюджет, progress=None):
    м = матрицы[0]
    n = м.n
    ряды = [[] for _ in range(n)]
    столбцы = [[] for _ in range(n)]
    for матрица in матрицы:
        v = матрица.values
        for л in range(n):
            ряды[л].extend(v[л * n:(л + 1) * n])
        for п in range(n):
            столбцы[п].extend(v[п::n])
    τ = max(1, допуск)
    левые = _clusters(ряды, n, τ, бюджет, тихо, CLASS_LIMIT, progress)
    правые = _clusters(столбцы, n, τ, бюджет, тихо, CLASS_LIMIT, progress)

    def собрать(к):
        класс, представители = к
        классы, состав, образцы = {}, {}, {}
        for номер, представитель in enumerate(представители):
            образцы[номер] = м.names[представитель]
        for знак in range(n):
            if класс[знак] >= 0:
                классы[м.names[знак]] = класс[знак]
                состав.setdefault(класс[знак], []).append(м.names[знак])
        return классы, состав, образцы

    л = собрать(левые)
    п = собрать(правые)
    return KernGroups(л[0], п[0], л[1], п[1], л[2], п[2])


class _Compression:
    __slots__ = ("groups", "left_index", "right_index", "values", "exceptions")


def compress(матрицы, тихо, видно, бюджет, progress=None):
    """Сжатие в классы — общие для всех мастеров, числа по каждому:
    значение класса — медиана его пар на этом мастере"""
    м = матрицы[0]
    n = м.n
    классы = group_by_values(матрицы, тихо, видно - 1, бюджет, progress)
    номерЛ = [классы.left_class.get(имя, -1) for имя in м.names]
    номерП = [классы.right_class.get(имя, -1) for имя in м.names]
    L, R = классы.left_count, классы.right_count
    составЛ = [[] for _ in range(L)]
    составП = [[] for _ in range(R)]
    for i in range(n):
        if номерЛ[i] >= 0:
            составЛ[номерЛ[i]].append(i)
        if номерП[i] >= 0:
            составП[номерП[i]].append(i)
    значения = []
    for мат in матрицы:
        v = мат.values
        ряд_значений = [0] * (L * R)
        for a in range(L):
            строки = [л * n for л in составЛ[a]]
            for b in range(R):
                столбцы = составП[b]
                ряд = sorted(v[с + п] for с in строки for п in столбцы)
                мед = ряд[len(ряд) // 2]
                ряд_значений[a * R + b] = мед if abs(мед) >= тихо else 0
        значения.append(ряд_значений)
    # пара выбилась из класса хоть на одном мастере на точность записи
    свои = frozenset(range(-(видно - 1), видно)).__contains__
    нули = [0] * n
    ряды_классов = [[[зн[a * R + нп] if нп >= 0 else 0 for нп in номерП] for a in range(L)]
                    for зн in значения]
    исключений = 0
    for л in range(n):
        нл = номерЛ[л]
        годны = None
        for w, мат in enumerate(матрицы):
            классы_ряда = ряды_классов[w][нл] if нл >= 0 else нули
            ряд = map(свои, map(sub, мат.values[л * n:(л + 1) * n], классы_ряда))
            годны = list(ряд) if годны is None else list(map(and_, годны, ряд))
        исключений += n - sum(годны)
    с = _Compression()
    с.groups, с.left_index, с.right_index, с.values, с.exceptions = классы, номерЛ, номерП, значения, исключений
    return с


def named_pair(values, classes, slack, half_clearance, digits, coded, видно):
    """Пишется ли пара поимённо и насколько важна: (ярус, вес) или None"""
    нули = False
    сжата = False
    отход = 0
    for w in range(len(values)):
        if digits and classes[w] != 0:
            нули = True
        if slack[w] < INT16_MAX and classes[w] < values[w] - slack[w] - half_clearance[w]:
            сжата = True
        отход = max(отход, abs(values[w] - classes[w]))
    if not (нули or сжата or отход >= видно):
        return None
    return (-1 if нули or сжата else (0 if coded else 1), отход)


class KernPlanVariable:
    """Кернинг на все мастера: классы одни, числа по мастерам.
    `cells` — ключ левый·65536 + правый → числа по мастерам;
    `pairs` — «левый|правый» → числа по мастерам"""

    def __init__(self, weights, left_class, right_class, cells, pairs, precision, truncated,
                 left_members=None, right_members=None):
        self.weights = weights
        self.left_class = left_class
        self.right_class = right_class
        self.cells = cells
        self.pairs = pairs
        self.precision = precision
        self.truncated = truncated
        self.left_members = left_members or {}
        self.right_members = right_members or {}

    def value(self, left, right, w):
        своё = self.pairs.get(left + "|" + right)
        if своё is not None:
            return своё[w]
        л = self.left_class.get(left)
        п = self.right_class.get(right)
        if л is None or п is None:
            return 0
        ячейка = self.cells.get(л << 16 | п)
        return ячейка[w] if ячейка is not None else 0


def plan_variable(матрицы, веса, upm, rule=None, reserved=0, progress=None):
    """Классы на все мастера и числа по мастерам.
    `progress(текст)` — ход (бросит исключение — расчёт прервётся)"""
    rule = rule or KernRule()
    м = матрицы[0]
    if any(мат.names != м.names for мат in матрицы):
        raise ValueError("знаки мастеров разошлись — кернинг по мастерам не сводится")
    n, W = м.n, len(матрицы)
    кегль = float(upm)

    def единицы(тысячные):
        return max(1, irnd(тысячные * кегль / 1000))

    тихо = единицы(rule.threshold)
    выбор = None
    точность = rule.visible
    for ступень in rule.steps():
        точность = max(rule.visible, ступень[0])
        def ход(знак, всего, точность=точность):
            progress("кернинг: классы, точность %g — знак %d из %d" % (точность, знак, всего))

        вариант = compress(матрицы, тихо, единицы(точность), max(4, n * W // ступень[1]),
                           ход if progress is not None else None)
        выбор = вариант
        if вариант.exceptions + reserved <= rule.limit:
            break
    if выбор is None or n == 0:
        return KernPlanVariable(веса, {}, {}, {}, {}, точность, 0)
    видно = единицы(точность)
    R = выбор.groups.right_count
    номерЛ, номерП, зн = выбор.left_index, выбор.right_index, выбор.values
    полузазоров = [int((мат.clearance / 2) // 1) for мат in матрицы]
    исключения = []
    for л in range(n):
        if progress is not None and л % 64 == 0:
            progress("кернинг: пары знаков — знак %d из %d" % (л, n))
        нл = номерЛ[л]
        for п in range(n):
            нп = номерП[п]
            к = л * n + п
            числа = [мат.values[к] for мат in матрицы]
            классы = [зн[w][нл * R + нп] if нл >= 0 and нп >= 0 else 0 for w in range(W)]
            важность = named_pair(числа, классы, [мат.slack[к] for мат in матрицы], полузазоров,
                                  м.digits[л] and м.digits[п], м.coded[л] and м.coded[п], видно)
            if важность is None:
                continue
            исключения.append((м.names[л] + "|" + м.names[п], числа, важность[0], важность[1]))
    исключения.sort(key=lambda и: (и[2], -и[3], и[0]))
    неприкосновенных = 0
    for и in исключения:
        if и[2] >= 0:
            break
        неприкосновенных += 1
    места = max(неприкосновенных, rule.limit - reserved)
    усечено = max(0, len(исключения) - места)
    пары = {и[0]: и[1] for и in исключения[:места]}
    ячейки = {}
    for a in range(выбор.groups.left_count):
        for b in range(R):
            числа = [зн[w][a * R + b] for w in range(W)]
            if any(ч != 0 for ч in числа):
                ячейки[a << 16 | b] = числа
    return KernPlanVariable(веса, выбор.groups.left_class, выбор.groups.right_class, ячейки, пары,
                            точность, усечено, выбор.groups.left_members, выбор.groups.right_members)


def _pair_keys(names, only):
    """Пары имён: все n×n или, с `only`, — хотя бы с одним из `only`"""
    if not only:
        for л in names:
            for п in names:
                yield л, п
        return
    свои = [п for п in names if п in only]
    for л in names:
        for п in (names if л in only else свои):
            yield л, п


def _glyph_pairs(кандидаты, limit):
    кандидаты.sort()
    усечено = 0
    if limit and len(кандидаты) > limit:
        усечено = len(кандидаты) - limit
        кандидаты = кандидаты[:limit]
    return {ключ: числа for _, _, ключ, числа in кандидаты}, усечено


def merge_pairs(plan, names, coded, covered, limit=None, only=None):
    """Пары для «дописать к своему»: из расчёта — только те, у которых в
    шрифте нет своего числа ни на одном мастере (ни парой знаков, ни
    классами); свой кернинг остаётся как был. Пишутся парами знаков.

    `covered(левый, правый)` — есть ли у пары своё число; `coded` — имя →
    есть ли у знака код; `only` — набор имён: пары хотя бы с одним из них.
    Ответ — ({«левый|правый»: [числа по мастерам]}, сколько не влезло в
    предел). Порядок важности — как у записи: пары знаков с кодом, затем
    по наибольшему числу"""
    W = len(plan.weights)
    кандидаты = []
    for л, п in _pair_keys(names, only):
        числа = [plan.value(л, п, w) for w in range(W)]
        if not any(числа) or covered(л, п):
            continue
        ярус = 0 if coded.get(л) and coded.get(п) else 1
        кандидаты.append((ярус, -max(abs(x) for x in числа), л + "|" + п, числа))
    return _glyph_pairs(кандидаты, limit)


def replace_pairs(plan, names, coded, old_value, only, limit=None):
    """Пары для «заменить» у выделенных знаков: каждая пара хотя бы с одним
    из `only`, у которой расчёт расходится с тем, что стоит в шрифте, —
    парой знаков с числами расчёта (и с нулём, если расчёт пару снимает:
    так ноль перебивает прежние классы). Прочий кернинг не трогается.

    `old_value(левый, правый, w)` — число пары в шрифте на мастере w.
    Ответ — как у `merge_pairs`; важнее пары с наибольшей разницей"""
    W = len(plan.weights)
    кандидаты = []
    for л, п in _pair_keys(names, only):
        числа = [plan.value(л, п, w) for w in range(W)]
        было = [old_value(л, п, w) for w in range(W)]
        if числа == было:
            continue
        ярус = 0 if coded.get(л) and coded.get(п) else 1
        разница = max(abs(a - b) for a, b in zip(числа, было))
        кандидаты.append((ярус, -разница, л + "|" + п, числа))
    return _glyph_pairs(кандидаты, limit)


def with_overrides(plan, overrides):
    """План с парами, выставленными рукой поверх (`{«л|п»: [числа]}`) —
    так снятая в окне пара пишется прежним числом"""
    if not overrides:
        return plan
    пары = dict(plan.pairs)
    пары.update(overrides)
    return KernPlanVariable(plan.weights, plan.left_class, plan.right_class, plan.cells, пары,
                            plan.precision, plan.truncated, plan.left_members, plan.right_members)


def estimate_size(plan):
    """Сколько примерно займёт кернинг одного мастера в файле, байт: пары
    знаков ~3 байта, ячейка классов ~2 (замер по выгрузкам трёх шрифтов
    на 180–2800 знаков, 22.10.2026)"""
    return 2000 + 3 * len(plan.pairs) + 2 * len(plan.left_members) * len(plan.right_members)


def class_names(plan, taken=()):
    """Имена классов — по первому знаку: «L_A», «R_O»; занятые имена
    классов шрифта обходятся"""
    def назвать(состав, приставка):
        имена, занято = {}, set(taken)
        for номер, знаки in sorted(состав.items()):
            имя = приставка + (знаки[0] if знаки else str(номер))
            основа, k = имя, 2
            while имя in занято:
                имя = "%s_%d" % (основа, k)
                k += 1
            занято.add(имя)
            имена[номер] = имя
        return имена
    return назвать(plan.left_members, "L_"), назвать(plan.right_members, "R_")
