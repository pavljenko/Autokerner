"""Мост к FontLab 8: мастера открытого шрифта — в расчёт, итог — обратно.

Чтение: знаки в порядке шрифта, коды, на каждом мастере — ширина, рисунок
и компоненты. Запись: сдвиг рисунка и ширина по мастерам, пробел, кернинг
(прежний снимается целиком, ставятся классы и пары расчёта). После записи —
сверка обратным чтением.

Только этот модуль знает API FontLab (`fontlab`, `fontgate`, PythonQt);
расчёт о FontLab не знает ничего. Что выяснено замером в FontLab 8.4.3:

- `flLayer.getContours()` отдаёт контуры фигур без их преобразований: у
  составного ударение приходит на месте базового знака, а сдвиг общей
  фигуры живёт в `flShape.transform`, не в точках. Видимый рисунок —
  фигуры слоя, каждая под своим преобразованием; компонент
  (`shapeData.componentGlyph`) — видимый рисунок базового знака того же
  мастера под преобразованием компонента;
- `flLayer.applyTransform` двигает весь слой: точки (или преобразование
  общей фигуры), компоненты и якоря;
- класс кернинга со стороной заводит только
  `fgKerning.addGroup(имя, знаки, kernMode='KernLeft'|'KernRight')`, и у
  каждого мастера классы свои — заводить в кернинге каждого;
  присваивание групп (как в TypeRig) в 8.4.3 не работает, а запись
  `fgGlyph.kerningLeft` и замена `fgKerning.groups` целиком роняют FontLab;
- пары знаков с нулём держит только `setPlainPairs` (`set` с нулём пару не
  заводит), пары классов — `set(((имя, True), (имя, True)), число)`;
- `fgKerning.clear()` снимает пары мастера и классы кернинга (здесь не
  зовётся: снимаем по одному, чтобы не задеть прочие классы);
- `fgFont.kerning` и печать `fgLayer` вешают FontLab (бесконечная рекурсия
  внутри него) — не трогать;
- выгрузка берёт кернинг из фичи kern текста фич, если она есть (FontLab
  кладёт туда прежний кернинг, открывая OTF/TTF) — запись её снимает;
- панели Kerning, Classes и Features сами не перечитываются — после записи
  их надо закрыть и открыть (Window → Panels).
"""

from .geometry import split_contours
from .kerning import class_names, with_overrides
from .model import Glyph, Master
from .options import Options


def _api():
    import fontlab
    import fontgate
    return fontlab, fontgate


def _qt():
    from PythonQt import QtGui
    return QtGui


def _xy(p):
    if hasattr(p, "x") and callable(p.x):
        return (float(p.x()), float(p.y()))
    return (float(p[0]), float(p[1]))


class _Pen:
    """Перо, собирающее вызовы в вид fontTools"""

    def __init__(self):
        self.commands = []

    def moveTo(self, p):
        self.commands.append(("moveTo", _xy(p)))

    def lineTo(self, p):
        self.commands.append(("lineTo", _xy(p)))

    def curveTo(self, *точки):
        точки = [_xy(p) for p in точки]
        for i in range(0, len(точки) - 2, 3):
            self.commands.append(("curveTo", точки[i], точки[i + 1], точки[i + 2]))

    def qCurveTo(self, *точки):
        вне = [_xy(p) for p in точки[:-1]]
        конец = точки[-1]
        self.commands.append(("qCurveTo", вне, _xy(конец) if конец is not None else None))

    def closePath(self):
        self.commands.append(("closePath",))

    def endPath(self):
        self.commands.append(("endPath",))

    def addComponent(self, name, transform):
        pass


def _matrix(t):
    return (t.m11(), t.m12(), t.m21(), t.m22(), t.dx(), t.dy())


def _transform(commands, m):
    """Вызовы пера под преобразованием (m11, m12, m21, m22, dx, dy)"""
    if m == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0):
        return list(commands)
    a, b, c, d, e, f = m

    def т(p):
        return (a * p[0] + c * p[1] + e, b * p[0] + d * p[1] + f)

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


class FontSource:
    """Открытый в FontLab шрифт: мастера для расчёта, «было» и запись"""

    def __init__(self, font=None):
        fl, _ = _api()
        self.font = font or fl.CurrentFont()
        if self.font is None:
            raise RuntimeError("Нет открытого шрифта")
        self.package = fl.flPackage(self.font)
        self.master_names = list(self.package.masters)
        self.upm = int(round(self.package.upm))
        self._glyphs = {}

    @property
    def name(self):
        try:
            return self.font.info.familyName or ""
        except Exception:
            return ""

    # ── слои ──

    def _flglyph(self, имя):
        """flGlyph знака; знака нет в шрифте (компонент ссылается на
        удалённый знак) — None"""
        fl, _ = _api()
        if имя not in self._glyphs:
            g = self.font[имя]
            self._glyphs[имя] = fl.flGlyph(g, self.font) if g is not None else None
        return self._glyphs[имя]

    def layer(self, имя, master):
        flg = self._flglyph(имя)
        if flg is None:
            return None
        слой = flg.getLayerByName(master)
        if слой is None:
            for л in flg.layers:
                if л.name == master:
                    return л
        return слой

    def _drawn(self, имя, master, память, глубина=0):
        """Видимый рисунок знака на мастере: (вызовы пера, компоненты)"""
        ключ = (имя, master)
        if ключ in память:
            return память[ключ]
        if глубина > 16:
            raise RuntimeError("компоненты «%s» ссылаются по кругу" % имя)
        слой = self.layer(имя, master)
        команды, компоненты = [], []
        if слой is not None:
            for фигура in слой.shapes:
                база = фигура.shapeData.componentGlyph if фигура.isComponent else ""
                if база:
                    компоненты.append(база)
                    свои = self._drawn(база, master, память, глубина + 1)[0]
                else:
                    перо = _Pen()
                    # FontLab отдаёт None вместо контура у фигур без рисунка
                    # (сообщение на TypeDrawers 23.10.2026): их пропускаем
                    for контур in фигура.getContours() or ():
                        if контур is not None:
                            контур.draw(перо)
                    свои = перо.commands
                команды += _transform(свои, _matrix(фигура.transform))
        память[ключ] = (команды, компоненты)
        return память[ключ]

    def master_heights(self, master):
        """Рост строчных и прописных мастера"""
        return self._master_values(master)[:2]

    def master_italic_angle(self, master):
        """Угол наклона курсива мастера, как в post.italicAngle (−12 у
        курсива с наклоном вправо); 0 — прямой"""
        return self._master_values(master)[2]

    def _master_values(self, master):
        p = self.package
        прежний = p.master
        try:
            if прежний != master:
                p.setMaster(master)
            return (p.xHeight_value or None, p.capsHeight_value or None,
                    float(getattr(p, "italicAngle_value", 0.0) or 0.0))
        finally:
            if p.master != прежний:
                p.setMaster(прежний)

    # ── какие знаки трогать ──

    def selected_names(self):
        """Знаки, выделенные в окне шрифта; None — не узнать. Новый API
        FontLab 8 выделения не отдаёт, его знает прежний модуль `FL` (так
        же делает TypeRig); номера знаков у него те же, что у fgFont, —
        если это тот же шрифт, что сверяется по числу и именам знаков"""
        try:
            import FL as legacy
            шрифт = legacy.fl.font
            знаки = list(self.font.glyphs)
            if шрифт is None or len(шрифт) != len(знаки):
                return None
            выбраны = []
            for i, g in enumerate(знаки):
                if legacy.fl.Selected(i):
                    if шрифт[i].name != g.name:
                        return None
                    выбраны.append(g.name)
            return выбраны
        except Exception:
            return None

    def marked_names(self):
        """Знаки с цветной меткой (`flGlyph.mark` не ноль)"""
        return [g.name for g in self.font.glyphs if self._flglyph(g.name).mark]

    def metric_key_names(self, masters=None):
        """Знаки с формулой метрик FontLab («=H», «=n+10») хоть на одном из
        мастеров: их поля ведёт формула, правка её бы перебила"""
        вышло = []
        for g in self.font.glyphs:
            for m in masters or self.master_names:
                слой = self.layer(g.name, m)
                if слой is not None and (слой.metricsLeft or слой.metricsRight or слой.metricsWidth):
                    вышло.append(g.name)
                    break
        return вышло

    def protected(self, options, masters=None, selected=None):
        """Знаки, которых правка полей не касается: имя → причина
        ('selection' | 'mark' | 'formula'). `selected` — выделенные
        (нужны, если выбраны «только выделенные»)"""
        вышло = {}
        if options.keep_metric_keys:
            for имя in self.metric_key_names(masters):
                вышло[имя] = "formula"
        if options.keep_marked:
            for имя in self.marked_names():
                вышло[имя] = "mark"
        if selected is not None:
            выбраны = set(selected)
            for g in self.font.glyphs:
                if g.name not in выбраны:
                    вышло.setdefault(g.name, "selection")
        return вышло

    # ── чтение ──

    def read(self, progress=None, round_shifted=False, masters=None):
        """Мастера для расчёта (`model.Master`), по порядку мастеров шрифта.

        `round_shifted` — мерить правленые знаки с точками на целых, как их
        пишет исходная программа в файл OTF. В FontLab сдвиг на целое точек не
        округляет, и мера по умолчанию видит то, что окажется в шрифте; у
        квадратичных контуров FontLab ещё и отдаёт серединные точки явно
        (131,5), и округлять их значило бы менять рисунок.

        `masters` — имена мастеров для расчёта (по умолчанию все)"""
        say = progress or (lambda текст: None)
        знаки = list(self.font.glyphs)
        имена_мастеров = list(masters or self.master_names)
        мастера = []
        for номер_мастера, m in enumerate(имена_мастеров):
            память = {}
            набор = []
            for номер, g in enumerate(знаки):
                if номер % 100 == 0:
                    say("читаю мастер %d из %d: знак %d из %d" % (
                        номер_мастера + 1, len(имена_мастеров), номер, len(знаки)))
                коды = [int(к) for к in g.unicodes]
                слой = self.layer(g.name, m)
                if слой is None:
                    набор.append(Glyph(g.name, коды, 0, []))
                    continue
                команды, компоненты = self._drawn(g.name, m, память)
                набор.append(Glyph(g.name, коды, int(round(слой.advanceWidth)),
                                   split_contours(команды), компоненты))
            рост, капитель, наклон = self._master_values(m)
            мастера.append(Master(self.upm, набор, рост, капитель, label=m,
                                  weight=float(номер_мастера), round_shifted=round_shifted,
                                  italic_angle=наклон))
        return мастера

    def fingerprint(self, masters=None):
        """Слепок шрифта для проверки «не правили ли после расчёта»: имена
        знаков, ширины на мастерах, число пар кернинга"""
        имена, ширины = [], []
        for g in self.font.glyphs:
            имена.append(g.name)
            for m in masters or self.master_names:
                слой = self.layer(g.name, m)
                ширины.append(слой.advanceWidth if слой is not None else None)
        пары = [len(self.package.kerning(m).keys()) for m in masters or self.master_names]
        return (tuple(имена), tuple(ширины), tuple(пары))

    def kerning_now(self, master):
        """Кернинг мастера как есть: (пары, классы).
        Пары — [(левый, левый_класс?, правый, правый_класс?, число)],
        классы — имя → (знаки, сторона: 'KernLeft' | 'KernRight' | 'KernBothSide')"""
        kern = self.package.kerning(master)
        пары = []
        for пара, число in kern.items():
            л, п = пара.left, пара.right
            пары.append((л.id, л.mode == "groupMode", п.id, п.mode == "groupMode", float(число)))
        классы = {}
        for имя, (знаки, сторона) in kern.groups.asDict().items():
            классы[имя] = (list(знаки), сторона)
        return пары, классы

    # ── запись ──

    def apply(self, result, options=None, progress=None, masters=None, only=None,
              rejected=(), old=None, writes=None):
        """Записать итог в шрифт.

        `masters` — имена мастеров в порядке расчёта (по умолчанию все);
        `only` — выделенные знаки: кернинг тогда пишется парами знаков с
        ними, прочий не трогается; `rejected` — пары «л|п», снятые в окне,
        остаются как были; `old` — прежний кернинг мастеров (`OldKerning`,
        по умолчанию читается); `writes` — уже подобранные пары знаков
        (`outcome.pair_writes`), если кернинг пишется парами.

        Ответ — (что записано числами, снимок для «Вернуть как было»)"""
        from .outcome import WHOLE, pair_writes, write_mode
        QtGui = _qt()
        o = options or Options()
        say = progress or (lambda текст: None)
        masters = list(masters or self.master_names)
        снимок = Snapshot(masters)
        записано = {"glyphs": 0, "space": 0, "pairs": 0, "cells": 0, "classes": 0,
                    "kern_feature": False, "truncated": 0, "mode": None}
        for w, m in enumerate(masters):
            say("апроши: мастер %d из %d" % (w + 1, len(masters)))
            записано["glyphs"] += self._apply_spacing(result, w, m, QtGui, снимок)
            if w in result.space:
                for g in self.font.glyphs:
                    if 0x20 in list(g.unicodes):
                        слой = self.layer(g.name, m)
                        if слой is not None:
                            снимок.layers.setdefault((g.name, m), (слой.advanceWidth, 0))
                            слой.advanceWidth = result.space[w]
                            записано["space"] += 1
                        break
        if result.kern is not None:
            say("кернинг: снимок прежнего")
            for m in masters:
                снимок.kerning[m] = self.kerning_now(m)
            if self.has_kern_feature():
                _, fg = _api()
                снимок.kern_feature = fg.fgOTLayout(self.font).get_feature("kern")
            if old is None:
                old = [OldKerning(*снимок.kerning[m]) for m in masters]
            вид = write_mode(o, old, only)
            записано["mode"] = вид
            записано["kern_feature"] = self.drop_kern_feature()
            if вид == WHOLE:
                план = result.kern
                if rejected:
                    план = with_overrides(план, {к: [old[w].value(*к.split("|"))
                                                     for w in range(len(masters))]
                                                 for к in rejected})
                self._write_whole(план, masters, записано, say)
            else:
                if writes is None:
                    знаки = list(self.font.glyphs)
                    say("кернинг: подбираю пары")
                    пары, усечено = pair_writes(result.kern, [g.name for g in знаки],
                                                {g.name: bool(list(g.unicodes)) for g in знаки},
                                                old, вид, o.kern_limit or None, only, rejected)
                else:
                    пары, усечено = writes
                    пары = {к: ч for к, ч in пары.items() if к not in rejected}
                записано["truncated"] = усечено
                for w, m in enumerate(masters):
                    say("кернинг: мастер %d из %d" % (w + 1, len(masters)))
                    ряд = [((к.split("|")[0], к.split("|")[1]), float(числа[w]))
                           for к, числа in sorted(пары.items())]
                    if ряд:
                        self.package.kerning(m).setPlainPairs(ряд)
                    записано["pairs"] += len(ряд)
        self._refresh()
        return записано, снимок

    def _write_whole(self, план, masters, записано, say):
        """Прежний кернинг мастеров снимается, ставятся классы и пары плана"""
        say("кернинг: снимаю прежний")
        self.clear_kerning(masters)
        занято = set()
        try:
            занято = {г[1] for г in self.package.getAllGroups()}
        except Exception:
            pass
        имена_л, имена_п = class_names(план, занято)
        записано["classes"] = len(имена_л) + len(имена_п)
        for w, m in enumerate(masters):
            say("кернинг: мастер %d из %d" % (w + 1, len(masters)))
            kern = self.package.kerning(m)
            # классы — у каждого мастера свои (замер на вариативном шрифте: заведённые
            # в первом мастере другие не видят, и их пары классов пропадали)
            есть = set(kern.groups.keys())
            for номер, знаки in sorted(план.left_members.items()):
                if имена_л[номер] not in есть:
                    kern.addGroup(имена_л[номер], list(знаки), kernMode="KernLeft")
            for номер, знаки in sorted(план.right_members.items()):
                if имена_п[номер] not in есть:
                    kern.addGroup(имена_п[номер], list(знаки), kernMode="KernRight")
            for ключ, числа in план.cells.items():
                if числа[w]:
                    kern.set(((имена_л[ключ >> 16], True), (имена_п[ключ & 0xFFFF], True)),
                             float(числа[w]))
                    записано["cells"] += 1
            пары = []
            for ключ, числа in план.pairs.items():
                л, п = ключ.split("|")
                пары.append(((л, п), float(числа[w])))
            if пары:
                kern.setPlainPairs(пары)
            записано["pairs"] += len(пары)

    def _refresh(self):
        self.package.update()
        try:
            # без этого панели «Kerning» и «Classes» показывают прежнее
            fl, _ = _api()
            fl.flItems.notifyPackageContentUpdated(self.package.id)
            fl.Update()
        except Exception:
            pass

    def _apply_spacing(self, result, w, m, QtGui, снимок):
        """Поля на мастере: рисунок едет на dx, ширина — новая. Компонент
        составного едет на сдвиг составного минус то, на что его увёл
        свой базовый знак, — как запись составных TrueType в исходной программе.
        Что было — в `снимок`"""
        сдвиги = {}
        for имя, по_мастерам in result.spacing.items():
            место = по_мастерам.get(w)
            if место is not None and место[0]:
                сдвиги[имя] = место[0]
        # компоненты: снимок до любой правки — сдвиг слоя их тоже двигает
        составные = []
        if сдвиги:
            for g in self.font.glyphs:
                слой = self.layer(g.name, m)
                if слой is None:
                    continue
                свои = [(н, ф) for н, ф in enumerate(слой.shapes) if ф.isComponent]
                if not свои:
                    continue
                if g.name in сдвиги or any(ф.shapeData.componentGlyph in сдвиги for _, ф in свои):
                    снимок.components[(g.name, m)] = [(н, _matrix(ф.transform)) for н, ф in свои]
                    составные.append((слой, свои))
        правлено = 0
        for имя, по_мастерам in result.spacing.items():
            место = по_мастерам.get(w)
            if место is None:
                continue
            dx, ширина = место
            слой = self.layer(имя, m)
            if слой is None:
                continue
            снимок.layers[(имя, m)] = (слой.advanceWidth, dx)
            if dx:
                слой.applyTransform(QtGui.QTransform(1, 0, 0, 1, dx, 0))
            слой.advanceWidth = ширина
            правлено += 1
        # база уже уехала сама — вычесть её сдвиг
        for слой, свои in составные:
            for _, фигура in свои:
                свой = сдвиги.get(фигура.shapeData.componentGlyph, 0)
                if not свой:
                    continue
                t = фигура.transform
                фигура.transform = QtGui.QTransform(t.m11(), t.m12(), t.m21(), t.m22(),
                                                    t.dx() - t.m11() * свой, t.dy() - t.m12() * свой)
        return правлено

    def restore(self, снимок, progress=None):
        """«Вернуть как было»: рисунок назад на тот же сдвиг, прежние ширины
        и преобразования компонентов, прежний кернинг (пары, классы со
        сторонами) и фича kern текста фич"""
        QtGui = _qt()
        say = progress or (lambda текст: None)
        say("возвращаю поля")
        for (имя, m), (ширина, dx) in снимок.layers.items():
            слой = self.layer(имя, m)
            if слой is None:
                continue
            if dx:
                слой.applyTransform(QtGui.QTransform(1, 0, 0, 1, -dx, 0))
            слой.advanceWidth = ширина
        for (имя, m), свои in снимок.components.items():
            слой = self.layer(имя, m)
            if слой is None:
                continue
            фигуры = list(слой.shapes)
            for н, t in свои:
                if н < len(фигуры) and фигуры[н].isComponent:
                    фигуры[н].transform = QtGui.QTransform(*t)
        if снимок.kerning:
            say("возвращаю кернинг")
            self.clear_kerning(list(снимок.kerning))
            for m, (пары, классы) in снимок.kerning.items():
                kern = self.package.kerning(m)
                for имя, (знаки, сторона) in классы.items():
                    kern.addGroup(имя, list(знаки), kernMode=сторона)
                простые = []
                for л, лк, п, пк, число in пары:
                    if лк or пк:
                        kern.set(((л, лк), (п, пк)), число)
                    else:
                        простые.append(((л, п), число))
                if простые:
                    kern.setPlainPairs(простые)
        if снимок.kern_feature is not None and not self.has_kern_feature():
            _, fg = _api()
            fg.fgOTLayout(self.font).set_feature("kern", снимок.kern_feature)
        self._refresh()

    def has_kern_feature(self):
        """Есть ли фича kern в тексте фич шрифта"""
        _, fg = _api()
        try:
            return "kern" in list(fg.fgOTLayout(self.font).keys())
        except Exception:
            return False

    def drop_kern_feature(self):
        """Снять фичу kern из текста фич шрифта. FontLab, открыв OTF/TTF,
        кладёт туда прежний кернинг текстом, и выгрузка берёт его, а не
        кернинг шрифта: замер 22.10.2026 — после записи выгруженный файл
        нёс прежний кернинг во всех 35 721 паре тестового шрифта, без фичи — новый
        до единицы. Без неё FontLab собирает kern из кернинга сам"""
        _, fg = _api()
        фичи = fg.fgOTLayout(self.font)
        if "kern" in list(фичи.keys()):
            фичи.remove("kern")
            return True
        return False

    def clear_kerning(self, masters=None):
        """Снять кернинг мастеров (по умолчанию всех): пары по одной, затем
        классы кернинга. Не `fgKerning.clear()`: прочие классы шрифта
        (классы фич OpenType) остаются как были"""
        masters = list(masters or self.master_names)
        for m in masters:
            kern = self.package.kerning(m)
            for пара in kern.keys():
                л, п = пара.left, пара.right
                kern.remove(((л.id, л.mode == "groupMode"), (п.id, п.mode == "groupMode")))
        for m in masters:
            kern = self.package.kerning(m)
            for имя in list(kern.groups.keys()):
                kern.deleteGroup(имя)

    class_names = staticmethod(class_names)


class Snapshot:
    """Как было до записи — для «Вернуть как было».

    `layers` — (знак, мастер) → (прежняя ширина, сдвиг рисунка при записи);
    `components` — (знак, мастер) → [(номер фигуры, преобразование)];
    `kerning` — мастер → (пары, классы) как `FontSource.kerning_now`;
    `kern_feature` — текст фичи kern, если она была"""

    def __init__(self, masters):
        self.masters = list(masters)
        self.layers = {}
        self.components = {}
        self.kerning = {}
        self.kern_feature = None

    @property
    def lost_zero_pairs(self):
        """Пары с классом и нулём: FontLab их не заводит (`set` с нулём пары
        не ставит), при возврате они пропадут — число для предупреждения"""
        return sum(1 for пары, _ in self.kerning.values()
                   for л, лк, п, пк, число in пары if (лк or пк) and not число)


class OldKerning:
    """Кернинг, как он стоит в шрифте, — чтобы назвать «было» любой пары.
    Порядок поиска как в UFO и при выдаче OpenType: знак–знак, знак–класс,
    класс–знак, класс–класс"""

    def __init__(self, пары, классы):
        self.pairs = {}
        for л, лк, п, пк, число in пары:
            self.pairs[(л, лк, п, пк)] = число
        self.left = {}
        self.right = {}
        for имя, (знаки, сторона) in классы.items():
            for знак in знаки:
                if сторона in ("KernLeft", "KernBothSide"):
                    self.left.setdefault(знак, имя)
                if сторона in ("KernRight", "KernBothSide"):
                    self.right.setdefault(знак, имя)
        self.count = len(пары)
        self.classes = len(классы)

    def has(self, left, right):
        """Есть ли у пары своё число (хоть парой знаков, хоть классами)"""
        p = self.pairs
        if (left, False, right, False) in p:
            return True
        кл, кп = self.left.get(left), self.right.get(right)
        return ((кп is not None and (left, False, кп, True) in p)
                or (кл is not None and (кл, True, right, False) in p)
                or (кл is not None and кп is not None and (кл, True, кп, True) in p))

    def value(self, left, right):
        p = self.pairs
        v = p.get((left, False, right, False))
        if v is not None:
            return v
        кп = self.right.get(right)
        if кп is not None:
            v = p.get((left, False, кп, True))
            if v is not None:
                return v
        кл = self.left.get(left)
        if кл is not None:
            v = p.get((кл, True, right, False))
            if v is not None:
                return v
            if кп is not None:
                v = p.get((кл, True, кп, True))
                if v is not None:
                    return v
        return 0.0
