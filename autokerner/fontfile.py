"""Готовый файл шрифта: прежний кернинг и запись итога — без FontLab
(для веб-версии и проверок).

Запись повторяет запись в FontLab (`fontlab_bridge`): рисунок знака едет
на сдвиг целиком, ширина — новая, компонент составного едет на сдвиг
составного минус сдвиг своей базы. Вслед за рисунком едут якоря GPOS
(метки, лигатуры, курсив) и каретки лигатур GDEF. Кернинг ставится
отдельным лукапом фичи kern: «заменить» — прежние лукапы kern снимаются с
фичи, «дописать» — новый лукап встаёт рядом с ними. Прочие таблицы и
лукапы не трогаются; таблицы, что хранят готовые ширины (hdmx, LTSH) или
подпись (DSIG), снимаются — после правки они бы лгали.

Только статичные шрифты TrueType (glyf) и CFF; вариативные — через
FontLab.
"""

import copy
import io

from fontTools.misc.roundTools import otRound
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont, TTLibError

from .outcome import MISSING


class UnsupportedFont(ValueError):
    """Файл, который веб-версия не правит: вариативный, коллекция, не шрифт"""

    def __init__(self, reason):
        ValueError.__init__(self, reason)
        self.reason = reason


def open_font(data):
    """TTFont из байтов TTF, OTF, WOFF или WOFF2"""
    try:
        шрифт = TTFont(io.BytesIO(data))
    except TTLibError as ошибка:
        if "collection" in str(ошибка).lower() or data[:4] == b"ttcf":
            raise UnsupportedFont("collection")
        raise UnsupportedFont("not_a_font")
    if "fvar" in шрифт or "CFF2" in шрифт:
        raise UnsupportedFont("variable")
    if "glyf" not in шрифт and "CFF " not in шрифт:
        raise UnsupportedFont("no_outlines")
    return шрифт


def save_font(font):
    """Байты шрифта — в том же виде, что пришёл (TTF/OTF, WOFF, WOFF2)"""
    буфер = io.BytesIO()
    font.save(буфер)
    return буфер.getvalue()


# ── прежний кернинг ──

def _pair_subtables(gpos, теги=("kern",)):
    индексы = set()
    for запись in gpos.FeatureList.FeatureRecord:
        if запись.FeatureTag in теги:
            индексы.update(запись.Feature.LookupListIndex)
    лукапы = []
    for i in sorted(индексы):
        lookup = gpos.LookupList.Lookup[i]
        подтаблицы = []
        for st in lookup.SubTable:
            if lookup.LookupType == 9:
                st = st.ExtSubTable
            if getattr(st, "LookupType", 2) == 2 or lookup.LookupType == 2:
                подтаблицы.append(st)
        лукапы.append(подтаблицы)
    return лукапы


def _xadvance(запись):
    return (getattr(запись, "XAdvance", 0) or 0) if запись is not None else 0


def legacy_pairs(font):
    """Пары старой таблицы kern (формат 0): {(левый, правый): число}. Она
    работает, только пока в GPOS нет своего кернинга"""
    пары = {}
    if "kern" in font:
        for таблица in font["kern"].kernTables:
            if getattr(таблица, "format", 0) == 0:
                пары.update(таблица.kernTable)
    return пары


class FileKerning:
    """Кернинг готового файла по правилам OpenType: лукапы фичи kern
    складываются, внутри лукапа срабатывает первая подтаблица, накрывшая
    пару (формат 1 — если нашлась запись второго знака, формат 2 — всегда,
    когда первый знак в покрытии). Без GPOS — старая таблица kern. Тот же
    вид, что у `fontlab_bridge.OldKerning`: `value`, `has`, `count`, `classes`"""

    def __init__(self, font):
        self.lookups = []
        self.count = 0
        классы = set()
        if "GPOS" in font and font["GPOS"].table.FeatureList:
            for подтаблицы in _pair_subtables(font["GPOS"].table):
                готовые = []
                for st in подтаблицы:
                    покрытие = set(st.Coverage.glyphs)
                    if st.Format == 1:
                        пары = {}
                        for первый, набор in zip(st.Coverage.glyphs, st.PairSet):
                            for запись in набор.PairValueRecord:
                                пары[(первый, запись.SecondGlyph)] = _xadvance(запись.Value1)
                        self.count += len(пары)
                        готовые.append((1, покрытие, пары))
                    else:
                        к1 = st.ClassDef1.classDefs if st.ClassDef1 else {}
                        к2 = st.ClassDef2.classDefs if st.ClassDef2 else {}
                        значения = [[_xadvance(з.Value1) for з in запись.Class2Record]
                                    for запись in st.Class1Record]
                        self.count += sum(1 for ряд in значения for v in ряд if v)
                        классы.update(("l", id(st), к) for к in set(к1.values()))
                        классы.update(("r", id(st), к) for к in set(к2.values()))
                        готовые.append((2, покрытие, (к1, к2, значения)))
                self.lookups.append(готовые)
        if not any(self.lookups) and "kern" in font:
            пары = legacy_pairs(font)
            if пары:
                self.lookups = [[(1, {л for л, _ in пары}, пары)]]
                self.count = len(пары)
        self.classes = len(классы)

    def _find(self, left, right):
        итог, есть = 0, False
        for подтаблицы in self.lookups:
            for вид, покрытие, данные in подтаблицы:
                if left not in покрытие:
                    continue
                if вид == 1:
                    if (left, right) in данные:
                        итог += данные[(left, right)]
                        есть = True
                        break
                    continue
                к1, к2, значения = данные
                v = значения[к1.get(left, 0)][к2.get(right, 0)]
                итог += v
                есть = есть or bool(v)
                break
        return итог, есть

    def value(self, left, right):
        return self._find(left, right)[0]

    def has(self, left, right):
        """Есть ли у пары своё число (хоть парой знаков, хоть классами)"""
        return self._find(left, right)[1]


# ── запись: сдвиги рисунков ──

def _shifts(result, w):
    """Имя → (сдвиг рисунка, ширина) на мастере w; пробел — своей шириной"""
    правки = {}
    for имя, по_мастерам in result.spacing.items():
        место = по_мастерам.get(w)
        if место is not None:
            правки[имя] = (int(round(место[0])), int(round(место[1])))
    return правки


def _write_glyf(font, правки):
    glyf, hmtx = font["glyf"], font["hmtx"]
    сдвиги = {имя: dx for имя, (dx, _) in правки.items() if dx}
    задеты = set()
    for имя in font.getGlyphOrder():
        g = glyf[имя]
        if g.isComposite():
            свой = сдвиги.get(имя, 0)
            for к in g.components:
                база = сдвиги.get(к.glyphName, 0)
                if not свой and not база:
                    continue
                t = getattr(к, "transform", [[1, 0], [0, 1]])
                # база уже уехала сама — вычесть её сдвиг (под преобразованием компонента)
                к.x = otRound(к.x + свой - t[0][0] * база)
                к.y = otRound(к.y - t[0][1] * база)
                задеты.add(имя)
        elif имя in сдвиги and g.numberOfContours > 0:
            g.coordinates.translate((сдвиги[имя], 0))
            задеты.add(имя)
    for имя in font.getGlyphOrder():
        g = glyf[имя]
        if имя in задеты or имя in правки:
            if g.numberOfContours != 0:
                g.recalcBounds(glyf)
            ширина, lsb = hmtx[имя]
            if имя in правки:
                ширина = правки[имя][1]
            # растеризатор ставит рисунок по полю hmtx (фантомные точки), а не
            # по координатам: поле едет на тот же сдвиг, что и точки
            hmtx[имя] = (ширина, lsb + сдвиги.get(имя, 0) if g.numberOfContours != 0 else 0)
    # USE_MY_METRICS: составной берёт ширину компонента — если теперь они
    # разошлись, флаг снимается, иначе растеризатор с хинтами взял бы чужую
    for имя in font.getGlyphOrder():
        g = glyf[имя]
        if not g.isComposite():
            continue
        for к in g.components:
            if к.flags & 0x0200 and hmtx[к.glyphName][0] != hmtx[имя][0]:
                к.flags &= ~0x0200


# операторы Type 2, что очищают стек и могут нести ширину первым числом
_HINTS = ("hstem", "hstemhm", "vstem", "vstemhm")
_STACK_CLEARING = _HINTS + ("hintmask", "cntrmask", "rmoveto", "hmoveto", "vmoveto", "endchar")


def _bias(n):
    return 107 if n < 1240 else (1131 if n < 33900 else 32768)


def _inline(program, локальные, общие, глубина=0):
    """Программа знака с подставленными подпрограммами (без «return»)"""
    if глубина > 10:
        raise ValueError("subroutines too deep")
    вышло = []
    for токен in program:
        if токен in ("callsubr", "callgsubr"):
            номер = вышло.pop()
            набор = локальные if токен == "callsubr" else общие
            sub = набор[номер + _bias(len(набор))]
            sub.decompile()
            тело = list(sub.program)
            if тело and тело[-1] == "return":
                тело = тело[:-1]
            вышло.extend(_inline(тело, локальные, общие, глубина + 1))
        else:
            вышло.append(токен)
    return вышло


def _shift_program(program, dx, ширина, private):
    """Сдвиг на dx и новая ширина прямо в программе: первая вертикальная
    стойка и первое перемещение пера — абсолютные, остальное относительно.
    Хинты остаются. None — если программа нестандартная (seac и т.п.)"""
    вышло, стек = [], []
    ширина_снята = False
    стойка_сдвинута = перо_сдвинуто = False
    i = 0
    while i < len(program):
        т = program[i]
        if not isinstance(т, str):
            стек.append(т)
            i += 1
            continue
        оп = т
        if оп in _STACK_CLEARING and not ширина_снята:
            # ширина — лишнее первое число у первого оператора, чистящего стек
            нужно = {"hmoveto": 1, "vmoveto": 1, "rmoveto": 2, "endchar": 0}.get(оп)
            if нужно is None:
                лишнее = len(стек) % 2 == 1
            else:
                лишнее = len(стек) > нужно
            if лишнее:
                стек = стек[1:]
            ширина_снята = True
        if оп in ("vstem", "vstemhm") or (оп in ("hintmask", "cntrmask") and стек and not стойка_сдвинута):
            if стек and not стойка_сдвинута:
                стек[0] = стек[0] + dx
                стойка_сдвинута = True
        if оп in ("rmoveto", "hmoveto", "vmoveto") and not перо_сдвинуто:
            if оп == "rmoveto":
                стек[0] = стек[0] + dx
            elif оп == "hmoveto":
                стек[0] = стек[0] + dx
            else:
                стек = [dx, стек[0]]
                оп = "rmoveto"
            перо_сдвинуто = True
        if оп == "endchar" and стек:
            return None
        вышло.extend(стек)
        вышло.append(оп)
        стек = []
        if оп in ("hintmask", "cntrmask"):
            i += 1
            вышло.append(program[i])
        i += 1
    if ширина != private.defaultWidthX:
        вышло.insert(0, ширина - private.nominalWidthX)
    return вышло


def _write_cff(font, правки):
    cff = font["CFF "].cff
    td = cff.topDictIndex[0]
    набор = td.CharStrings
    общие = cff.GlobalSubrs
    hmtx = font["hmtx"]
    знаки = font.getGlyphSet()
    for имя, (dx, ширина) in правки.items():
        cs, _ = набор.getItemAndSelector(имя)
        private = cs.private
        локальные = getattr(private, "Subrs", None) or []
        cs.decompile()
        программа = None
        try:
            программа = _shift_program(_inline(list(cs.program), локальные, общие), dx, ширина, private)
        except (ValueError, IndexError, KeyError):
            программа = None
        if программа is None:
            # перерисовать пером: хинты знака теряются, рисунок и ширина верны
            перо = T2CharStringPen(None, знаки)
            знаки[имя].draw(TransformPen(перо, (1, 0, 0, 1, dx, 0)))
            программа = перо.getCharString(private=private, globalSubrs=общие).program
            if ширина != private.defaultWidthX:
                программа.insert(0, ширина - private.nominalWidthX)
        cs.program = программа
        cs.bytecode = None
    знаки = font.getGlyphSet()
    for имя, (dx, ширина) in правки.items():
        границы = BoundsPen(знаки)
        знаки[имя].draw(границы)
        hmtx[имя] = (ширина, otRound(границы.bounds[0]) if границы.bounds else 0)


def _shift_anchors(font, сдвиги):
    """Якоря GPOS и каретки GDEF едут вместе с рисунком своего знака"""
    видел = {}

    def сдвинуть(владелец, якорь, dx):
        if якорь is None or not dx:
            return якорь
        прежний = видел.get(id(якорь))
        if прежний is not None:
            if прежний == владелец:
                return якорь
            якорь = copy.deepcopy(якорь)
        якорь.XCoordinate = otRound(якорь.XCoordinate + dx)
        видел[id(якорь)] = владелец
        return якорь

    if "GPOS" in font and font["GPOS"].table.LookupList:
        for lookup in font["GPOS"].table.LookupList.Lookup:
            for st in lookup.SubTable:
                тип = lookup.LookupType
                if тип == 9:
                    тип, st = st.ExtensionLookupType, st.ExtSubTable
                if тип == 3:
                    for имя, запись in zip(st.Coverage.glyphs, st.EntryExitRecord):
                        dx = сдвиги.get(имя, 0)
                        запись.EntryAnchor = сдвинуть(имя, запись.EntryAnchor, dx)
                        запись.ExitAnchor = сдвинуть(имя, запись.ExitAnchor, dx)
                elif тип in (4, 5, 6):
                    метки = st.Mark1Coverage if тип == 6 else st.MarkCoverage
                    массив = st.Mark1Array if тип == 6 else st.MarkArray
                    for имя, запись in zip(метки.glyphs, массив.MarkRecord):
                        запись.MarkAnchor = сдвинуть(имя, запись.MarkAnchor, сдвиги.get(имя, 0))
                    if тип == 4:
                        for имя, запись in zip(st.BaseCoverage.glyphs, st.BaseArray.BaseRecord):
                            dx = сдвиги.get(имя, 0)
                            запись.BaseAnchor = [сдвинуть(имя, я, dx) for я in запись.BaseAnchor]
                    elif тип == 6:
                        for имя, запись in zip(st.Mark2Coverage.glyphs, st.Mark2Array.Mark2Record):
                            dx = сдвиги.get(имя, 0)
                            запись.Mark2Anchor = [сдвинуть(имя, я, dx) for я in запись.Mark2Anchor]
                    else:
                        for имя, лиг in zip(st.LigatureCoverage.glyphs, st.LigatureArray.LigatureAttach):
                            dx = сдвиги.get(имя, 0)
                            for к in лиг.ComponentRecord:
                                к.LigatureAnchor = [сдвинуть(имя, я, dx) for я in к.LigatureAnchor]
    if "GDEF" in font:
        gdef = font["GDEF"].table
        каретки = getattr(gdef, "LigCaretList", None)
        if каретки is not None:
            for имя, лиг in zip(каретки.Coverage.glyphs, каретки.LigGlyph):
                dx = сдвиги.get(имя, 0)
                if not dx:
                    continue
                for к in лиг.CaretValue:
                    if к.Format in (1, 3):
                        к.Coordinate = otRound(к.Coordinate + dx)


# ── запись: кернинг ──

def _kern_lookup(font, plan, w, pairs=None, rejected=()):
    """Лукап кернинга мастера w: пары знаков первой подтаблицей (они
    перебивают классы), затем классы. `pairs` — {«л|п»: числа} вместо
    плана (для «дописать»: только пары знаков)"""
    from fontTools.otlLib import builder as otl
    карта = font.getReverseGlyphMap()
    имена = set(карта)

    def число(v):
        return otl.buildValue({"XAdvance": int(round(v))})

    свои = plan.pairs if pairs is None else pairs
    пары_знаков = {}
    for ключ, числа in свои.items():
        if ключ in rejected:
            continue
        л, п = ключ.split("|")
        if л in имена and п in имена:
            пары_знаков[(л, п)] = (число(числа[w]), None)
    подтаблицы = []
    if пары_знаков:
        подтаблицы += otl.buildPairPosGlyphs(пары_знаков, карта)
    if pairs is None:
        порядок = lambda знаки: tuple(sorted((з for з in знаки if з in имена), key=карта.get))
        классы = {}
        for ключ, числа in plan.cells.items():
            if not числа[w]:
                continue
            левые = порядок(plan.left_members.get(ключ >> 16, ()))
            правые = порядок(plan.right_members.get(ключ & 0xFFFF, ()))
            if левые and правые:
                классы[(левые, правые)] = (число(числа[w]), None)
        if классы:
            подтаблицы.append(otl.buildPairPosClassesSubtable(классы, карта))
    if not подтаблицы:
        return None
    return otl.buildLookup(подтаблицы)


def _new_gpos(font):
    from fontTools.ttLib import newTable
    from fontTools.ttLib.tables import otTables as ot
    gpos = ot.GPOS()
    gpos.Version = 0x00010000
    gpos.ScriptList = ot.ScriptList()
    gpos.ScriptList.ScriptRecord = []
    gpos.FeatureList = ot.FeatureList()
    gpos.FeatureList.FeatureRecord = []
    gpos.LookupList = ot.LookupList()
    gpos.LookupList.Lookup = []
    таблица = newTable("GPOS")
    таблица.table = gpos
    font["GPOS"] = таблица
    # те же письменности, что у подстановок; иначе — по умолчанию
    письма = []
    if "GSUB" in font and font["GSUB"].table.ScriptList:
        письма = [з.ScriptTag for з in font["GSUB"].table.ScriptList.ScriptRecord]
    for тег in письма or ["DFLT"]:
        запись = ot.ScriptRecord()
        запись.ScriptTag = тег
        запись.Script = ot.Script()
        запись.Script.DefaultLangSys = ot.LangSys()
        запись.Script.DefaultLangSys.ReqFeatureIndex = 0xFFFF
        запись.Script.DefaultLangSys.FeatureIndex = []
        запись.Script.LangSysRecord = []
        gpos.ScriptList.ScriptRecord.append(запись)
    return gpos


def _langsystems(gpos):
    for запись in gpos.ScriptList.ScriptRecord:
        if запись.Script.DefaultLangSys is not None:
            yield запись.Script.DefaultLangSys
        for язык in запись.Script.LangSysRecord:
            yield язык.LangSys


def _has_gpos_kern(font):
    """Есть ли в GPOS свой кернинг (подтаблицы пар в фиче kern)"""
    return "GPOS" in font and bool(font["GPOS"].table.FeatureList) and any(_pair_subtables(font["GPOS"].table))


def _legacy_lookup(font):
    """Старая таблица kern — лукапом GPOS: при «дописать» свой кернинг шрифта
    без GPOS не должен пропасть, когда кернинг переезжает в GPOS"""
    from fontTools.otlLib import builder as otl
    карта = font.getReverseGlyphMap()
    пары = {(л, п): (otl.buildValue({"XAdvance": int(v)}), None)
            for (л, п), v in legacy_pairs(font).items() if v and л in карта and п in карта}
    if not пары:
        return None
    return otl.buildLookup(otl.buildPairPosGlyphs(пары, карта))


def _put_kern(font, lookup, replace):
    """Лукап — в фичу kern всех письменностей. `replace` — прежние лукапы
    kern снимаются с фичи (остаются в списке ничьими). Старая таблица kern
    снимается; при «дописать» её пары переносятся в GPOS, если она работала
    (в GPOS не было своего кернинга)"""
    from fontTools.ttLib.tables import otTables as ot
    лукапы = [lookup]
    if "kern" in font:
        if not replace and not _has_gpos_kern(font):
            старый = _legacy_lookup(font)
            if старый is not None:
                лукапы = [старый, lookup]
        del font["kern"]
    gpos = font["GPOS"].table if "GPOS" in font else _new_gpos(font)
    if gpos.LookupList is None:
        gpos.LookupList = ot.LookupList()
        gpos.LookupList.Lookup = []
    номера = list(range(len(gpos.LookupList.Lookup), len(gpos.LookupList.Lookup) + len(лукапы)))
    gpos.LookupList.Lookup.extend(лукапы)
    gpos.LookupList.LookupCount = len(gpos.LookupList.Lookup)
    записи = [з for з in gpos.FeatureList.FeatureRecord if з.FeatureTag == "kern"]
    for запись in записи:
        запись.Feature.LookupListIndex = номера if replace else запись.Feature.LookupListIndex + номера
        запись.Feature.LookupCount = len(запись.Feature.LookupListIndex)
    if записи:
        return
    # фичи kern не было — завести и подключить ко всем языкам, держа
    # список фич по алфавиту
    запись = ot.FeatureRecord()
    запись.FeatureTag = "kern"
    запись.Feature = ot.Feature()
    запись.Feature.FeatureParams = None
    запись.Feature.LookupListIndex = номера
    запись.Feature.LookupCount = len(номера)
    старые = gpos.FeatureList.FeatureRecord
    новые = sorted(старые + [запись], key=lambda з: з.FeatureTag)
    куда = {id(з): i for i, з in enumerate(новые)}
    перенос = {i: куда[id(з)] for i, з in enumerate(старые)}
    for язык in _langsystems(gpos):
        язык.FeatureIndex = sorted([перенос[i] for i in язык.FeatureIndex] + [куда[id(запись)]])
        язык.FeatureCount = len(язык.FeatureIndex)
        if язык.ReqFeatureIndex != 0xFFFF:
            язык.ReqFeatureIndex = перенос.get(язык.ReqFeatureIndex, язык.ReqFeatureIndex)
    gpos.FeatureList.FeatureRecord = новые
    gpos.FeatureList.FeatureCount = len(новые)


def apply(font, result, w=0, mode=None, pairs=None, rejected=()):
    """Итог расчёта — в шрифт (на месте). `mode` — как пишется кернинг
    (`outcome.WHOLE` или `outcome.MISSING`), `pairs` — пары знаков для
    `MISSING` (`outcome.pair_writes`); `rejected` — пары «л|п», снятые
    пользователем. Ответ — сколько знаков с новыми полями"""
    правки = _shifts(result, w)
    if result.space and w in result.space:
        cmap = font.getBestCmap() or {}
        имя = cmap.get(0x20)
        if имя is not None:
            dx = правки.get(имя, (0, 0))[0]
            правки[имя] = (dx, int(round(result.space[w])))
    if правки:
        if "glyf" in font:
            _write_glyf(font, правки)
        else:
            _write_cff(font, правки)
        _shift_anchors(font, {имя: dx for имя, (dx, _) in правки.items() if dx})
        for тег in ("hdmx", "LTSH", "DSIG"):
            if тег in font:
                del font[тег]
        if "OS/2" in font:
            font["OS/2"].recalcAvgCharWidth(font)
    if result.kern is not None:
        lookup = _kern_lookup(font, result.kern, w, pairs if mode == MISSING else None, rejected)
        if lookup is not None:
            _put_kern(font, lookup, replace=mode != MISSING)
        elif mode != MISSING:
            _put_kern_empty(font)
    return len(правки)


def _put_kern_empty(font):
    """Заменить кернинг пустым: снять прежние лукапы kern с фичи"""
    if "kern" in font:
        del font["kern"]
    if "GPOS" not in font or not font["GPOS"].table.FeatureList:
        return
    for запись in font["GPOS"].table.FeatureList.FeatureRecord:
        if запись.FeatureTag == "kern":
            запись.Feature.LookupListIndex = []
            запись.Feature.LookupCount = 0


# ── сверка записанного ──

def check(source, result, data, kern_after, w=0, names=None):
    """Записанный файл против расчёта: ширины, сдвиги рисунков и кернинг
    каждой пары `names` (по умолчанию — знаков с кодом). Ответ — список
    расхождений [(вид, что, есть, надо)]"""
    from . import otf
    from .geometry import contours_rect
    шрифт = TTFont(io.BytesIO(data))
    после = otf.master_from_font(шрифт)
    кернинг = FileKerning(шрифт)
    плохо = []
    for g in source.glyphs:
        i = после.by_name(g.name)
        if i is None:
            плохо.append(("glyph", g.name, None, None))
            continue
        h = после.glyphs[i]
        dx, ширина = result.spacing.get(g.name, {}).get(w, (0, g.advance))
        if 0x20 in g.codes and w in result.space:
            ширина = result.space[w]
        if h.advance != int(round(ширина)):
            плохо.append(("width", g.name, h.advance, ширина))
        r0, r1 = contours_rect(g.contours), contours_rect(h.contours)
        if r0 and r1 and abs(r1[0] - (r0[0] + dx)) > 0.51:
            плохо.append(("shift", g.name, round(r1[0] - r0[0], 2), dx))
    if result.kern is not None:
        имена = names if names is not None else [g.name for g in source.glyphs if g.codes]
        for л in имена:
            for п in имена:
                надо, есть = kern_after(л, п), кернинг.value(л, п)
                if надо != есть:
                    плохо.append(("kern", л + " " + п, есть, надо))
    return плохо
