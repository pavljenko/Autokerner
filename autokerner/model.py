"""Шрифт на одном мастере — то, что расчёту нужно знать о нём.

Расчёт не знает, откуда пришёл шрифт: из файла (fontTools, `otf.py`) или
из открытого в FontLab (`fontlab_bridge.py`). Оба наполняют одно и то же:
знаки в порядке шрифта, коды, ширины, контуры (вызовами пера) и ссылки на
компоненты.
"""

from .geometry import Contour, contours_rect, polygon_edges, polygons, round_contours, shift_contours


class Glyph:
    """Знак мастера.

    `contours` — рисунок целиком, составные раскрыты (`Contour`);
    `components` — имена знаков, из которых собран составной, по порядку;
    у простого знака пусто. Составной не судится правилом апрошей: он едет
    вместе с базой (как составные TrueType в исходной программе)."""
    __slots__ = ("name", "codes", "advance", "contours", "components", "_edges")

    def __init__(self, name, codes, advance, contours, components=()):
        self.name = name
        self.codes = sorted(codes)
        self.advance = int(advance)
        self.contours = contours
        self.components = list(components)
        self._edges = False

    @property
    def edges(self):
        """Рёбра ломаных рисунка — общие на все замеры знака"""
        if self._edges is False:
            self._edges = polygon_edges(polygons(self.contours))
        return self._edges

    @property
    def rect(self):
        return contours_rect(self.contours)


class Master:
    """Мастер шрифта: знаки в порядке шрифта и общие числа.

    `x_height` и `cap_height` — объявленные высоты (OS/2 или поля мастера);
    None — не заданы. `weight` — число, под которым мастер идёт в итоге
    (вес OS/2 или номер мастера), `label` — имя мастера для отчёта.
    `round_shifted` — правленый знак встаёт точками на целые (`with_metrics`).
    `italic_angle` — угол наклона курсива в градусах, как в post.italicAngle
    (отрицательный — наклон вправо); 0 — прямой."""

    def __init__(self, upm, glyphs, x_height=None, cap_height=None, label="", weight=0.0,
                 round_shifted=True, italic_angle=0.0):
        self.upm = int(upm)
        self.glyphs = list(glyphs)
        self.x_height = x_height or None
        self.cap_height = cap_height or None
        self.label = label
        self.weight = weight
        self.round_shifted = round_shifted
        self.italic_angle = float(italic_angle or 0.0)
        self.index = {}
        for i, g in enumerate(self.glyphs):
            self.index.setdefault(g.name, i)
        # код → номер знака; код у двух знаков — за первым, как в cmap
        self.cmap = {}
        for i, g in enumerate(self.glyphs):
            for код in g.codes:
                self.cmap.setdefault(код, i)
        коды = {}
        for код, i in self.cmap.items():
            коды.setdefault(i, []).append(код)
        self.codes_by_glyph = {i: sorted(к) for i, к in коды.items()}

    @property
    def num_glyphs(self):
        return len(self.glyphs)

    def glyph(self, code):
        """Номер знака по коду; None — нет"""
        return self.cmap.get(code)

    def name(self, i):
        return self.glyphs[i].name

    def by_name(self, name):
        return self.index.get(name)

    def contours(self, i):
        return self.glyphs[i].contours

    def advance(self, i):
        return self.glyphs[i].advance

    def component_bases(self, i):
        """Номера знаков-компонентов составного; пусто — простой"""
        вышло = []
        for имя in self.glyphs[i].components:
            j = self.index.get(имя)
            if j is not None:
                вышло.append(j)
        return вышло

    def with_metrics(self, changes, round_points=None):
        """Мастер, переписанный с новыми полями: `changes` — имя →
        (сдвиг рисунка, ширина). Рисунок едет на сдвиг целиком — так его
        переписывает запись исходной программы, и так же мерит кернинг.

        `round_points` — точки правленого знака встают на целые, как в
        исходной программе: знак CFF она перерисовывает пером fontTools с
        `roundTolerance=0.5` (сдвиг или новая ширина), и мера кернинга
        видит уже округлённый рисунок. Без этого пары с правлеными знаками
        расходились с эталоном на единицу (замер 22.10.2026). У TrueType
        точки и так целые, а составной едет ссылками — без округления.
        None — как задано мастеру"""
        if not changes:
            return self
        if round_points is None:
            round_points = self.round_shifted
        знаки = []
        for g in self.glyphs:
            правка = changes.get(g.name)
            if правка is None:
                знаки.append(g)
                continue
            dx, ширина = правка
            if round_points and (dx != 0 or ширина != g.advance):
                контуры = round_contours(g.contours, dx)
            else:
                контуры = shift_contours(g.contours, dx)
            знаки.append(Glyph(g.name, g.codes, ширина, контуры, g.components))
        return Master(self.upm, знаки, self.x_height, self.cap_height, self.label, self.weight,
                      self.round_shifted, self.italic_angle)


__all__ = ["Contour", "Glyph", "Master"]
