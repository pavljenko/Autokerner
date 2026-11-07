"""Что окажется в шрифте после записи — для живой строки, таблиц правок и
самой записи. Без FontLab: на вход — итог расчёта, мастера и прежний
кернинг (`fontlab_bridge.OldKerning` или любой объект с `value`, `has`,
`count`).
"""

from .kerning import estimate_size, merge_pairs, replace_pairs
from .options import MERGE, REPLACE

# Как пишется кернинг
WHOLE = "whole"          # прежний снимается, ставятся классы и пары расчёта
MISSING = "missing"      # дописать: пары расчёта, у которых в шрифте нет своего числа
SELECTED = "selected"    # заменить пары с выделенными знаками, прочее не трогать

DEFAULT_TEXT = "AVATAR Type, Tokyo LTV «Ау» Wavy ТАУ ГОРА Учёт: Тётя «Гугл» 7,4 rv."


def kept_glyphs(master, marked):
    """Знаки, чей кернинг не трогается: помеченные цветом и те, что идут за
    помеченной базой, — буква с диакритикой по Юникоду (Á за A) и составной
    знак, чей первый компонент помечен. Так принято кернить диакритику —
    одним классом с базой; поля её и так едут за базой"""
    from .unicode_props import base_code
    помечены = set(marked)
    вышло = set(помечены)
    if not помечены:
        return вышло
    по_коду = {код: master.name(i) for код, i in master.cmap.items()}
    for i, знак in enumerate(master.glyphs):
        if знак.name in вышло:
            continue
        if any(по_коду.get(base_code(код)) in помечены for код in знак.codes):
            вышло.add(знак.name)
            continue
        базы = master.component_bases(i)
        if базы and master.name(базы[0]) in помечены:
            вышло.add(знак.name)
    return вышло


def write_mode(options, old, only=None):
    """Как пишется кернинг: `WHOLE`, `MISSING` или `SELECTED`.

    Дописывать не к чему, если кернинга нет ни на одном мастере, — тогда
    пишется целиком (классами, а не тысячами пар знаков)"""
    if only:
        return MISSING if options.kern_mode == MERGE else SELECTED
    if options.kern_mode == MERGE and any(k.count for k in old):
        return MISSING
    return WHOLE


def kern_after(plan, old, w, mode, only=None, rejected=(), writes=None):
    """Число пары после записи на мастере w: `value(левый, правый)`.
    `old` — прежний кернинг этого мастера; `rejected` — пары «л|п», снятые
    в окне (остаются как были); `writes` — пары, которые запишутся в
    режимах `MISSING` и `SELECTED` (`pair_writes`): с ними ответ точен и
    тогда, когда часть пар не влезла в предел"""
    def value(левый, правый):
        ключ = левый + "|" + правый
        if rejected and ключ in rejected:
            return old.value(левый, правый)
        if writes is not None:
            числа = writes.get(ключ)
            return числа[w] if числа is not None else old.value(левый, правый)
        if only and левый not in only and правый not in only:
            return old.value(левый, правый)
        if mode == MISSING and old.has(левый, правый):
            return old.value(левый, правый)
        return plan.value(левый, правый, w)
    return value


def pair_writes(plan, names, coded, old, mode, limit=None, only=None, rejected=()):
    """Пары знаков, которые запишутся в режимах `MISSING` и `SELECTED`:
    ({«л|п»: [числа по мастерам]}, сколько не влезло в предел).
    `names` и `coded` — знаки шрифта по порядку и есть ли у них код;
    `old` — прежний кернинг по мастерам"""
    only = set(only) if only else None
    if mode == MISSING:
        пары, усечено = merge_pairs(plan, names, coded, lambda л, п: any(k.has(л, п) for k in old),
                                    limit, only)
    else:
        пары, усечено = replace_pairs(plan, names, coded, lambda л, п, w: old[w].value(л, п),
                                      only, limit)
    for к in rejected:
        пары.pop(к, None)
    return пары, усечено


def size_estimate(plan, mode, pairs=None):
    """Сколько примерно займёт записанный кернинг одного мастера, байт"""
    if mode == WHOLE:
        return estimate_size(plan)
    return 3 * len(pairs or ())


def changed_pairs(names, before, after, top=300, glyph=None):
    """Пары, у которых число меняется: [(левый, правый, было, станет)] от
    крупных изменений. `glyph` — только пары с этим знаком (все, без
    предела); иначе — `top` крупнейших среди `names`"""
    вышло = []
    if glyph is not None:
        ключи = [(glyph, п) for п in names] + [(л, glyph) for л in names if л != glyph]
    else:
        ключи = ((л, п) for л in names for п in names)
    for л, п in ключи:
        было, стало = before(л, п), after(л, п)
        if было != стало:
            вышло.append((-abs(стало - было), л, п, было, стало))
            if glyph is None and len(вышло) > top * 8:
                вышло.sort()
                del вышло[top:]
    вышло.sort()
    if glyph is None:
        del вышло[top:]
    return [(л, п, было, стало) for _, л, п, было, стало in вышло]


def parse_text(text, master):
    """Строка — в имена знаков мастера. «/имя» — знак по имени (до пробела
    или следующей «/»), «//» — сама косая; символ без знака пропускается"""
    имена = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] != "/" and not text[i + 1].isspace():
            j = i + 1
            while j < n and text[j] != "/" and not text[j].isspace():
                j += 1
            имя = text[i + 1:j]
            if master.by_name(имя) is not None:
                имена.append(имя)
            i = j + 1 if j < n and text[j].isspace() else j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            i += 1
        k = master.glyph(ord(c))
        if k is not None:
            имена.append(master.name(k))
        i += 1
    return имена


def layout(names, master, kern=None):
    """Места знаков строки: [(имя, x)] и ширина строки. `kern(л, п)` —
    кернинг пары (None — без кернинга)"""
    места = []
    x = 0
    прежний = None
    for имя in names:
        i = master.by_name(имя)
        if i is None:
            continue
        if прежний is not None and kern is not None:
            x += kern(прежний, имя)
        места.append((имя, x))
        x += master.advance(i)
        прежний = имя
    return места, x


def spacing_after(result, w, rejected=()):
    """Правки полей мастера w после записи: имя → (сдвиг, ширина), без
    снятых в окне знаков"""
    вышло = {}
    for имя, по_мастерам in result.spacing.items():
        место = по_мастерам.get(w)
        if место is not None and имя not in rejected:
            вышло[имя] = место
    return вышло


__all__ = ["WHOLE", "MISSING", "SELECTED", "REPLACE", "MERGE", "DEFAULT_TEXT", "write_mode",
           "kern_after", "pair_writes", "size_estimate", "changed_pairs", "parse_text", "layout",
           "spacing_after"]
