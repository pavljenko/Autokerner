"""Геометрия контуров: габариты, ломаные, профиль чернил.

Перенос исходной программы (Swift). Числа отсюда идут в поля и
кернинг, поэтому порядок действий повторён дословно: другой порядок даёт
другие последние биты, а на границе порога — другое решение.

Контур — список вызовов пера в виде fontTools:
    ("moveTo", (x, y)), ("lineTo", (x, y)), ("curveTo", p1, p2, p3),
    ("qCurveTo", [вне...], конец или None), ("closePath",), ("endPath",)
"""

import math
import struct

INF = float("inf")


# ── округления как в Swift ──

def rnd(x):
    """`Double.rounded()` Swift: половина — от нуля (у Python `round` — к чётному)"""
    if x != x or x in (INF, -INF):
        return x
    if x < 0:
        return -rnd(-x)
    f = math.floor(x)
    return f + 1 if x - f >= 0.5 else f


def irnd(x):
    """`Int(x.rounded())`"""
    return int(rnd(x))


def f32(x):
    """`Float(x)`: двойная точность в одинарную, к ближайшему"""
    return struct.unpack("f", struct.pack("f", x))[0]


def clamp16(x):
    """`Int16(clamping:)`"""
    return -32768 if x < -32768 else (32767 if x > 32767 else int(x))


INT16_MAX = 32767


def median(values):
    """Медиана: у чётного ряда — среднее двух серединных"""
    if not values:
        return 0.0
    ряд = sorted(values)
    середина = len(ряд) // 2
    if len(ряд) % 2 == 1:
        return ряд[середина]
    return (ряд[середина - 1] + ряд[середина]) / 2


# ── габарит: зеркало BoundsPen (fontTools.misc.bezierTools) ──

EPSILON = 1e-10


def _solve_quadratic(a, b, c):
    if abs(a) < EPSILON:
        return [] if abs(b) < EPSILON else [-c / b]
    DD = b * b - 4.0 * a * c
    if not DD >= 0.0:
        return []
    rDD = math.sqrt(DD)
    return [(-b + rDD) / 2.0 / a, (-b - rDD) / 2.0 / a]


def _bounds_of(points):
    if not points:
        return (0.0, 0.0, 0.0, 0.0)
    x0, y0 = points[0]
    xMin, yMin, xMax, yMax = x0, y0, x0, y0
    for x, y in points[1:]:
        xMin = min(xMin, x)
        yMin = min(yMin, y)
        xMax = max(xMax, x)
        yMax = max(yMax, y)
    return (xMin, yMin, xMax, yMax)


def _cubic_bounds(p1, p2, p3, p4):
    dx, dy = p1
    cx = (p2[0] - dx) * 3.0
    cy = (p2[1] - dy) * 3.0
    bx = (p3[0] - p2[0]) * 3.0 - cx
    by = (p3[1] - p2[1]) * 3.0 - cy
    ax = p4[0] - dx - cx - bx
    ay = p4[1] - dy - cy - by
    xRoots = [t for t in _solve_quadratic(ax * 3.0, bx * 2.0, cx) if 0 <= t < 1]
    yRoots = [t for t in _solve_quadratic(ay * 3.0, by * 2.0, cy) if 0 <= t < 1]
    точки = [(ax * t * t * t + bx * t * t + cx * t + dx,
              ay * t * t * t + by * t * t + cy * t + dy) for t in xRoots + yRoots]
    точки.append(p1)
    точки.append(p4)
    return _bounds_of(точки)


def _quadratic_bounds(p1, p2, p3):
    cx, cy = p1
    bx = (p2[0] - cx) * 2.0
    by = (p2[1] - cy) * 2.0
    ax = p3[0] - cx - bx
    ay = p3[1] - cy - by
    корни = []
    if ax * 2.0 != 0:
        корни.append(-bx / (ax * 2.0))
    if ay * 2.0 != 0:
        корни.append(-by / (ay * 2.0))
    точки = [(ax * t * t + bx * t + cx, ay * t * t + by * t + cy)
             for t in корни if 0 <= t < 1]
    точки.append(p1)
    точки.append(p3)
    return _bounds_of(точки)


def _contains(r, p):
    return r[0] <= p[0] <= r[2] and r[1] <= p[1] <= r[3]


def _union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _updated(r, p):
    return (min(r[0], p[0]), min(r[1], p[1]), max(r[2], p[0]), max(r[3], p[1]))


def _unfold_quad(вне, конец, перо):
    """Свёрнутый ряд внеконтурных точек — в отдельные квадратичные сегменты"""
    if not вне:
        return []
    сегменты = []
    for i in range(len(вне) - 1):
        a, b = вне[i], вне[i + 1]
        сегменты.append((a, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)))
    сегменты.append((вне[-1], конец if конец is not None else перо))
    return сегменты


def command_points(команда):
    вид = команда[0]
    if вид in ("moveTo", "lineTo"):
        return [команда[1]]
    if вид == "curveTo":
        return [команда[1], команда[2], команда[3]]
    if вид == "qCurveTo":
        return list(команда[1]) + ([команда[2]] if команда[2] is not None else [])
    return []


def contour_bounds(commands):
    """Габарит контура: начало входит лениво,
    края кривой считаются, только если управляющая точка вышла за рамку"""
    рамка = None
    начало = None
    перо = (0.0, 0.0)

    for команда in commands:
        вид = команда[0]
        if вид == "moveTo":
            начало = команда[1]
            перо = команда[1]
        elif вид == "lineTo":
            if начало is not None:
                рамка = _updated(рамка, начало) if рамка else (начало[0], начало[1], начало[0], начало[1])
                начало = None
            p = команда[1]
            рамка = _updated(рамка, p) if рамка else (p[0], p[1], p[0], p[1])
            перо = p
        elif вид == "curveTo":
            if начало is not None:
                рамка = _updated(рамка, начало) if рамка else (начало[0], начало[1], начало[0], начало[1])
                начало = None
            b1, b2, p = команда[1], команда[2], команда[3]
            рамка = _updated(рамка, p) if рамка else (p[0], p[1], p[0], p[1])
            if рамка is not None and (not _contains(рамка, b1) or not _contains(рамка, b2)):
                рамка = _union(рамка, _cubic_bounds(перо, b1, b2, p))
            перо = p
        elif вид == "qCurveTo":
            if начало is not None:
                рамка = _updated(рамка, начало) if рамка else (начало[0], начало[1], начало[0], начало[1])
                начало = None
            for b, p in _unfold_quad(команда[1], команда[2], перо):
                рамка = _updated(рамка, p) if рамка else (p[0], p[1], p[0], p[1])
                if рамка is not None and not _contains(рамка, b):
                    рамка = _union(рамка, _quadratic_bounds(перо, b, p))
                перо = p
    if рамка is None:
        точки = [т for к in commands for т in command_points(к)]
        return _bounds_of(точки)
    return рамка


class Contour:
    """Контур с габаритом: `xMin, yMin, xMax, yMax`"""
    __slots__ = ("commands", "rect")

    def __init__(self, commands, rect=None):
        self.commands = commands
        self.rect = rect if rect is not None else contour_bounds(commands)

    @property
    def top(self):
        return self.rect[3]


def _closed_offcurve(текущий):
    """Контур TrueType из одних внеконтурных точек (круглая точка, «о»)
    приходит одним qCurveTo без начала и конца. Начало — середина между
    последней и первой точками; без него контур начинался бы из (0, 0) и
    поле знака мерилось бы до начала координат"""
    if not текущий or текущий[0][0] != "qCurveTo" or текущий[0][2] is not None or len(текущий[0][1]) < 2:
        return текущий
    вне = текущий[0][1]
    старт = ((вне[-1][0] + вне[0][0]) / 2, (вне[-1][1] + вне[0][1]) / 2)
    return [("moveTo", старт), ("qCurveTo", list(вне), старт)] + текущий[1:]


def split_contours(commands):
    """Поток вызовов пера — в контуры: по
    closePath / endPath; хвост без закрывающей команды отбрасывается"""
    вышло = []
    текущий = []
    for команда in commands:
        текущий.append(команда)
        if команда[0] in ("closePath", "endPath"):
            if any(command_points(к) for к in текущий):
                вышло.append(Contour(_closed_offcurve(текущий)))
            текущий = []
    return вышло


def contours_rect(contours):
    """Габарит всех контуров; пусто — None"""
    if not contours:
        return None
    r = contours[0].rect
    for c in contours[1:]:
        r = _union(r, c.rect)
    return r


def shift_commands(commands, dx):
    """Вызовы пера, сдвинутые по x"""
    def т(p):
        return (p[0] + dx, p[1])
    вышло = []
    for к in commands:
        вид = к[0]
        if вид in ("moveTo", "lineTo"):
            вышло.append((вид, т(к[1])))
        elif вид == "curveTo":
            вышло.append((вид, т(к[1]), т(к[2]), т(к[3])))
        elif вид == "qCurveTo":
            вышло.append((вид, [т(p) for p in к[1]], т(к[2]) if к[2] is not None else None))
        else:
            вышло.append(к)
    return вышло


def shift_contours(contours, dx):
    if dx == 0:
        return contours
    return [Contour(shift_commands(c.commands, dx)) for c in contours]


def ot_round(v):
    """`fontTools.misc.roundTools.otRound`: половина — вверх"""
    return int(math.floor(v + 0.5))


def round_contours(contours, dx):
    """Контуры, сдвинутые по x и с точками на целых — как их перерисовывает
    `T2CharStringPen(roundTolerance=0.5)` поверх `TransformPen`"""
    def т(p):
        return (float(ot_round(p[0] + dx)), float(ot_round(p[1])))
    вышло = []
    for c in contours:
        команды = []
        for к in c.commands:
            вид = к[0]
            if вид in ("moveTo", "lineTo"):
                команды.append((вид, т(к[1])))
            elif вид == "curveTo":
                команды.append((вид, т(к[1]), т(к[2]), т(к[3])))
            elif вид == "qCurveTo":
                команды.append((вид, [т(p) for p in к[1]], т(к[2]) if к[2] is not None else None))
            else:
                команды.append(к)
        вышло.append(Contour(команды))
    return вышло


# ── ломаные: кривые по 16 шагов ──

def polygons(contours):
    вышло = []
    for контур in contours:
        точки = []
        перо = None
        старт = None

        def кубик(p0, a, b, c):
            for ш in range(1, 17):
                t = ш / 16
                u = 1 - t
                точки.append((
                    u * u * u * p0[0] + 3 * u * u * t * a[0] + 3 * u * t * t * b[0] + t * t * t * c[0],
                    u * u * u * p0[1] + 3 * u * u * t * a[1] + 3 * u * t * t * b[1] + t * t * t * c[1]))

        for команда in контур.commands:
            вид = команда[0]
            if вид == "moveTo":
                p = команда[1]
                точки.append(p)
                перо = p
                старт = p
            elif вид == "lineTo":
                p = команда[1]
                точки.append(p)
                перо = p
            elif вид == "curveTo":
                if перо is not None:
                    кубик(перо, команда[1], команда[2], команда[3])
                перо = команда[3]
            elif вид == "qCurveTo":
                вне, конец = команда[1], команда[2]
                p0 = перо if перо is not None else (старт if старт is not None else (0.0, 0.0))
                сегменты = []
                for н, ctrl in enumerate(вне):
                    if н == len(вне) - 1:
                        фин = конец if конец is not None else старт
                    else:
                        фин = ((ctrl[0] + вне[н + 1][0]) / 2, (ctrl[1] + вне[н + 1][1]) / 2)
                    if фин is not None:
                        сегменты.append((ctrl, фин))
                for ctrl, фин in сегменты:
                    кубик(p0,
                          (p0[0] + 2.0 / 3 * (ctrl[0] - p0[0]), p0[1] + 2.0 / 3 * (ctrl[1] - p0[1])),
                          (фин[0] + 2.0 / 3 * (ctrl[0] - фин[0]), фин[1] + 2.0 / 3 * (ctrl[1] - фин[1])),
                          фин)
                    p0 = фин
                перо = p0
            elif вид in ("closePath", "endPath"):
                if точки:
                    вышло.append(точки)
                    точки = []
        if точки:
            вышло.append(точки)
    return вышло


def polygon_edges(polys):
    """Рёбра ломаных с непустым ходом по высоте: (низ, верх, ax, ay, bx, by).
    Ломаных нет вовсе — None: профиля у такого знака нет"""
    if not polys:
        return None
    рёбра = []
    for полигон in polys:
        n = len(полигон)
        for i in range(n):
            a = полигон[i]
            b = полигон[(i + 1) % n]
            if a[1] == b[1]:
                continue
            рёбра.append((min(a[1], b[1]), max(a[1], b[1]), a[0], a[1], b[0], b[1]))
    return рёбра


class InkProfile:
    """Профиль чернил: на каждой строке сетки — крайние x рисунка;
    None — на этой высоте чернил нет"""
    __slots__ = ("low", "step", "left", "right")

    def __init__(self, low, step, left, right):
        self.low = low
        self.step = step
        self.left = left
        self.right = right

    @property
    def count(self):
        return len(self.left)


def ink_profile(edges, low, high, step):
    """Снять профиль в полосе `[low, high]`. Тот же ответ, что построчный
    обход всех рёбер в Swift, но обход идёт по рёбрам: строка y пересекает
    ребро, если низ ≤ y < верх (то же условие `(a.y <= y) != (b.y <= y)`)"""
    if not (step > 0 and high > low) or edges is None:
        return None
    строк = max(1, int(math.ceil((high - low) / step)))
    слева = [None] * строк
    справа = [None] * строк
    for низ, верх, ax, ay, bx, by in edges:
        # первая строка, чья высота не ниже низа ребра
        r = int(math.floor((низ - low) / step - 0.5))
        if r < 0:
            r = 0
        while r < строк and low + (r + 0.5) * step < низ:
            r += 1
        while r > 0 and low + (r - 1 + 0.5) * step >= низ:
            r -= 1
        while r < строк:
            y = low + (r + 0.5) * step
            if y >= верх:
                break
            t = (y - ay) / (by - ay)
            x = ax + (bx - ax) * t
            л = слева[r]
            if л is None:
                слева[r] = x
                справа[r] = x
            else:
                if x < л:
                    слева[r] = x
                if x > справа[r]:
                    справа[r] = x
            r += 1
    return InkProfile(low, step, слева, справа)


def slant_of(italic_angle):
    """Сдвиг по x на единицу высоты у курсива: тангенс наклона вправо"""
    if not italic_angle:
        return 0.0
    return math.tan(math.radians(-float(italic_angle)))


def deskewed(профиль, сдвиг, y0=0.0):
    """Профиль курсива, выпрямленный по углу наклона: строка на высоте y
    сдвинута на −(y − y0)·сдвиг. Просвет двух знаков в одной строке не
    меняется, меняются крайние точки и тени — как у прямого рисунка"""
    if профиль is None or not сдвиг:
        return профиль
    слева, справа = [], []
    for i, (л, п) in enumerate(zip(профиль.left, профиль.right)):
        dx = (профиль.low + (i + 0.5) * профиль.step - y0) * сдвиг
        слева.append(None if л is None else л - dx)
        справа.append(None if п is None else п - dx)
    return InkProfile(профиль.low, профиль.step, слева, справа)
