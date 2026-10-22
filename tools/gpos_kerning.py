"""Кернинг готового файла по правилам OpenType — для сверки выгрузки.

    kern = GposKerning(TTFont(путь)); kern.value("A", "V")

Лукапы фичи kern складываются; внутри лукапа срабатывает первая
подтаблица, накрывшая пару (формат 1 — если нашлась запись второго знака,
формат 2 — всегда, когда первый знак в покрытии).
"""


class GposKerning:
    def __init__(self, font):
        self.lookups = []
        if "GPOS" not in font:
            return
        gpos = font["GPOS"].table
        индексы = set()
        for запись in gpos.FeatureList.FeatureRecord:
            if запись.FeatureTag == "kern":
                индексы.update(запись.Feature.LookupListIndex)
        for i in sorted(индексы):
            lookup = gpos.LookupList.Lookup[i]
            подтаблицы = []
            for st in lookup.SubTable:
                if lookup.LookupType == 9:
                    st = st.ExtSubTable
                if st.LookupType if hasattr(st, "LookupType") else None:
                    pass
                подтаблицы.append(self._prepare(st))
            self.lookups.append(подтаблицы)

    @staticmethod
    def _prepare(st):
        покрытие = set(st.Coverage.glyphs)
        if st.Format == 1:
            пары = {}
            for первый, набор in zip(st.Coverage.glyphs, st.PairSet):
                for запись in набор.PairValueRecord:
                    v = запись.Value1.XAdvance if запись.Value1 is not None and hasattr(запись.Value1, "XAdvance") else 0
                    пары[(первый, запись.SecondGlyph)] = v or 0
            return (1, покрытие, пары)
        классы1 = st.ClassDef1.classDefs if st.ClassDef1 else {}
        классы2 = st.ClassDef2.classDefs if st.ClassDef2 else {}
        значения = []
        for запись in st.Class1Record:
            ряд = []
            for з in запись.Class2Record:
                v = з.Value1.XAdvance if з.Value1 is not None and hasattr(з.Value1, "XAdvance") else 0
                ряд.append(v or 0)
            значения.append(ряд)
        return (2, покрытие, (классы1, классы2, значения))

    def value(self, left, right):
        итог = 0
        for подтаблицы in self.lookups:
            for вид, покрытие, данные in подтаблицы:
                if left not in покрытие:
                    continue
                if вид == 1:
                    if (left, right) in данные:
                        итог += данные[(left, right)]
                        break
                    continue
                классы1, классы2, значения = данные
                итог += значения[классы1.get(left, 0)][классы2.get(right, 0)]
                break
        return итог
