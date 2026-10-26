"""Окно сценария в FontLab 8.

Раскладка идёт за работой пользователя: слева — что сделать и как
(сверху главное: что считать, затем какие знаки и мастера, ниже правило;
тонкая настройка свёрнута), справа — что выйдет (итог числами, живая
строка, правки с галочками), внизу — ход расчёта и кнопки. Шрифт меняет
только «Применить»; «Вернуть как было» откатывает последнюю запись.

Окно не модальное: пока оно открыто, можно выделять знаки в окне шрифта.
Расчёт идёт в главном потоке — FontLab иначе не даёт трогать шрифт, — а
окно между шагами отвечает (`processEvents`); «Стоп» прерывает расчёт.
Кнопки не реагируют на Enter: Enter в строке поиска не должен записать
шрифт.
"""

import html
import os
import re
import sys
import time
import traceback

from . import EMAIL, SITE_URL, SUPPORT_URL, __version__, export
from .auto import run
from .fontlab_bridge import FontSource, OldKerning
from .geometry import contours_rect, irnd
from .options import (ALL, FIGURES, MERGE, PRESET_NOTES, PRESET_TITLES, PRESETS, REPLACE, SELECTED, Options,
                      preset)
from .kerning import keep_pairs
from .outcome import (DEFAULT_TEXT, MISSING, WHOLE, changed_pairs, kept_glyphs, kern_after, layout,
                      pair_writes, parse_text, size_estimate, spacing_after, write_mode)
from .outcome import SELECTED as SELECTED_PAIRS
from .report import build

_TEXT = {
    "title": ("Автокернер", "Autokerner"),
    "masters_n": ("мастеров: %d", "masters: %d"),
    "glyphs_n": ("знаков: %d", "glyphs: %d"),
    "no_font": ("Откройте шрифт в FontLab и запустите сценарий снова.",
                "Open a font in FontLab and run the script again."),
    # ── слева: что сделать ──
    "sec_what": ("Что сделать", "What to do"),
    "do_spacing": ("Апроши — поля знаков", "Spacing — sidebearings"),
    "do_spacing_tip": ("Левое и правое поле каждого знака по площади белого, на всех мастерах. "
                       "Диакритика и составные знаки идут за своей основой.",
                       "Left and right sidebearings of every glyph by white area, on all masters. "
                       "Accented and composite glyphs follow their base."),
    "do_space": ("Пробел — ширина межсловного", "Word space width"),
    "do_space_tip": ("Ширина пробела — доля средней ширины строчной (см. «Тонкая настройка»). "
                     "Правится, только если пробел заметно шире правила.",
                     "Space width as a share of the median lowercase width (see Fine-tuning). "
                     "Changed only if the space is clearly wider than the rule."),
    "do_kerning": ("Кернинг — классы и пары", "Kerning — classes and pairs"),
    "do_kerning_tip": ("Кернинг считается по новым полям: классы общие на все мастера, числа — свои "
                       "у каждого.", "Kerning is measured with the new sidebearings: classes shared by all "
                       "masters, values per master."),
    "mode_label": ("Свой кернинг шрифта:", "The font's own kerning:"),
    "mode_replace": ("Заменить целиком", "Replace entirely"),
    "mode_merge": ("Дописать к своему", "Add to it"),
    "mode_replace_note": ("Прежние пары и классы кернинга снимаются, ставятся новые.",
                          "Existing kerning pairs and classes are removed, the new ones are written."),
    "mode_merge_note": ("Ваши пары и классы остаются как есть; дописываются пары, которых у вас нет "
                        "(парами знаков). Пустой кернинг пишется целиком.",
                        "Your pairs and classes stay as they are; only pairs you don't have are added "
                        "(as glyph pairs). An empty kerning is written entirely."),
    "sec_where": ("Какие знаки", "Which glyphs"),
    "glyphs_all": ("Все знаки шрифта", "All glyphs"),
    "glyphs_sel": ("Только выделенные в окне шрифта", "Only those selected in the font window"),
    "glyphs_sel_n": ("Только выделенные в окне шрифта (сейчас: %d)",
                     "Only those selected in the font window (now: %d)"),
    "glyphs_sel_tip": ("Поля правятся только у выделенных; кернинг пишется парами знаков с ними, "
                       "прочий не трогается. Выделение читается при нажатии «Посчитать».",
                       "Only the selected glyphs are respaced; kerning is written as glyph pairs with them, "
                       "the rest is left alone. The selection is read when you press Calculate."),
    "keep_formula": ("Не трогать знаки с формулами метрик", "Keep glyphs with metrics formulas"),
    "keep_formula_tip": ("Знаки, у которых поле или ширина заданы формулой FontLab (=H, =n+10): "
                         "правка перебила бы формулу.",
                         "Glyphs whose sidebearing or width is a FontLab formula (=H, =n+10): "
                         "a change would override it."),
    "keep_marked": ("Не трогать знаки с цветной меткой", "Keep glyphs with a color mark"),
    "keep_marked_tip": ("Пометьте цветом (Glyph → Flag) знаки, выверенные рукой, — расчёт не тронет ни их "
                        "поля, ни кернинг: пары с ними останутся как были, и у букв с диакритикой на их "
                        "основе тоже. Если соседи получат новые поля, числа этих пар прежние, а зазор может "
                        "стать другим.",
                        "Flag hand-tuned glyphs with a color (Glyph → Flag) — the calculation leaves both their "
                        "sidebearings and their kerning alone: pairs with them stay as they were, and so do "
                        "those of accented letters built on them. If a neighbour gets new sidebearings, these "
                        "pairs keep their numbers but the gap may look different."),
    "nbsp": ("Неразрывный пробел — шириной как пробел", "No-break space as wide as the space"),
    "nbsp_tip": ("Разная ширина пробела и неразрывного пробела — частая ошибка (её ловит FontBakery).",
                 "Different widths of space and no-break space are a common error (FontBakery checks it)."),
    "sec_masters": ("Мастера", "Masters"),
    "sec_rule": ("Правило", "Rule"),
    "preset": ("Набор:", "Preset:"),
    "custom": ("Свой", "Custom"),
    "custom_note": ("Числа изменены вручную.", "Numbers changed by hand."),
    "fine": ("Тонкая настройка", "Fine-tuning"),
    "sub_spacing": ("Апроши", "Spacing"),
    "looseness": ("Разрядка", "Looseness"),
    "looseness_tip": ("Плотнее (−) или свободнее (+) всё вместе: эталон белого умножается на 1 + доля. "
                      "0 — своя плотность шрифта. Все знаки группы сдвигаются одинаково.",
                      "Tighter (−) or looser (+) overall: the white-area target is scaled by 1 + share. "
                      "0 keeps the font's own colour. All glyphs of a group move alike."),
    "threshold": ("Чувствительность", "Sensitivity"),
    "threshold_tip": ("Знак правится, если поле уходит от правила больше чем на столько тысячных кегля. "
                      "Меньше — правок больше.",
                      "A glyph is changed if a sidebearing is off by more than this many 1/1000 em. "
                      "Smaller — more changes."),
    "word_gap": ("Пробел — доля строчной", "Space — share of lowercase"),
    "word_gap_tip": ("Целевая ширина пробела — эта доля медианной ширины строчной.",
                     "Target space width — this share of the median lowercase width."),
    "space_fit": ("Широкий пробел", "Wide word space"),
    "space_fit_items": ("сузить до края допуска|сузить до нормы", "narrow to the tolerance edge|narrow to the target"),
    "space_fit_tip": ("Пробел шире нормы больше чем на четверть сужается. «До края допуска» — осторожно, пробел "
                      "остаётся на верхней границе допуска. «До нормы» — до самой целевой ширины, как в исходном "
                      "правиле: набор плотнее, хорошо для узких и акцидентных шрифтов.",
                      "A word space more than a quarter wider than the target is narrowed. “To the tolerance edge” is "
                      "cautious: the space stays at the upper edge of the tolerance. “To the target” goes all the way, "
                      "as in the original rule: tighter setting, good for condensed and display faces."),
    "sub_kerning": ("Кернинг", "Kerning"),
    "strength": ("Сила", "Strength"),
    "strength_tip": ("Насколько закрывать «карман» белого между знаками: 100 % — правило, "
                     "больше — пары сильнее.", "How much of the white pocket between glyphs to close: "
                     "100% — the rule, more — stronger pairs."),
    "kthreshold": ("Не кернить меньше", "Skip pairs below"),
    "kthreshold_tip": ("Пары меньше этого (тысячных кегля) не пишутся.",
                       "Pairs smaller than this (1/1000 em) are not written."),
    "clearance": ("Зазор", "Clearance"),
    "clearance_tip": ("Ближе этого (тысячных кегля) чернила пары не сходятся.",
                      "The ink of a pair never comes closer than this (1/1000 em)."),
    "precision": ("Точность классов", "Class precision"),
    "precision_tip": ("Насколько пары класса могут расходиться с точным числом. Тоньше — классов и пар "
                      "больше, файл крупнее.", "How far a class pair may differ from the exact value. "
                      "Finer — more classes and pairs, a bigger file."),
    "limit": ("Предел пар знаков", "Glyph pair limit"),
    "limit_tip": ("Сколько пар знаков (исключений из классов) писать. Считаются всегда все пары; "
                  "предел срабатывает только у больших шрифтов (сотни знаков и больше): тогда пишутся "
                  "самые заметные, а точность классов грубеет.",
                  "How many glyph pairs (class exceptions) to write. All pairs are always measured; "
                  "the limit only matters for big fonts (hundreds of glyphs): then the most visible are "
                  "written and class precision coarsens."),
    "round": ("Округление", "Rounding"),
    "round_tip": ("Значения кратны шагу (округляются в сторону свободнее).",
                  "Values are multiples of the step (rounded toward looser)."),
    "max_tight": ("Не сжимать сильнее", "Never tighter than"),
    "max_tight_tip": ("Самая сильная пара — не больше этого (тысячных кегля); 0 — без предела.",
                      "The strongest pair is capped at this (1/1000 em); 0 — no cap."),
    "max_loose": ("Не раздвигать сильнее", "Never looser than"),
    "max_loose_tip": ("Пара не раздвигается больше этого (тысячных кегля), даже если чернила сходятся "
                      "ближе зазора: иначе хвост Q или дробная черта раздвигают пары на полкегля; "
                      "0 — без предела.",
                      "A pair is never pushed apart by more than this (1/1000 em), even if the ink comes "
                      "closer than the clearance: otherwise a Q tail or a fraction slash can push a pair "
                      "half an em apart; 0 — no cap."),
    "no_limit": ("без предела", "no limit"),
    "figures": ("Цифры с , . :", "Figures with , . :"),
    "figures_items": ("как в правиле|без столкновений (7,4 · 3.5 · 12:30)|не кернить",
                      "as in the rule|no collisions (7,4 · 3.5 · 12:30)|no kerning"),
    "figures_tip": ("Правило подтягивает запятую, точку и двоеточие к цифре по одной паре, и в числах вроде 7,4 "
                    "цифры могут наехать друг на друга через знак. «Без столкновений»: цифра справа не подтягивается "
                    "к знаку и не нависает над ним, а через знак цифры стоят не ближе, чем стояли бы рядом без него, — "
                    "для этого ослабляется пара «цифра + знак» (запятая остаётся у цифры слева: «1917,»). "
                    "«Не кернить» — эти пары не кернятся совсем.",
                    "The rule pulls comma, period and colon to a figure pair by pair, so in numbers like 7,4 the "
                    "figures may run into each other across the mark. “No collisions”: the figure on the right is "
                    "never pulled to the mark or over it, and across the mark the figures are never closer than they "
                    "would be side by side — the figure + mark pair is loosened for that (the comma stays with the "
                    "figure on its left: “1917,”). “No kerning” leaves these pairs unkerned."),
    "per_mille": (" /1000", " /1000"),
    "side_h": ("С нуля: поле H", "From zero: H side"),
    "side_h_tip": ("Если у шрифта нет своей расстановки (поля нулевые или у всех букв одинаковые), скрипт "
                   "расставляет его с нуля. Плотность он берёт с букв-образцов, если вы расставили на глаз "
                   "некоторые из n o h u m i l H O I N U (или п о н и Н О П И): остальные встанут по ним "
                   "(образцы выровняются вместе со всеми). Иначе плотность угадывается по форме букв. Здесь её "
                   "можно задать числом: среднее белое у стороны H, тысячных кегля; «авто» — не задавать. "
                   "У расставленного шрифта это поле ни на что не влияет.",
                   "If the font has no spacing of its own (zero sidebearings, or the same ones on every letter), "
                   "the script spaces it from scratch. It takes the colour from sample letters if you have "
                   "spaced some of n o h u m i l H O I N U by eye: the rest follow them (the samples are "
                   "evened out along with the others). Otherwise the colour is guessed from the letter shapes. "
                   "Here you can set it as "
                   "a number: the average white beside H, in thousandths of the em; “auto” leaves it unset. "
                   "For a spaced font this field does nothing."),
    "auto": ("авто", "auto"),
    "from_zero_on": ("Расставлять с нуля шрифт без своей расстановки", "Space a font with no spacing from scratch"),
    "from_zero_on_tip": ("Шрифт без своей расстановки — поля нулевые или у почти всех букв одинаковые. "
                         "Моноширинные и пиксельные шрифты не трогаются. Снимите галочку, если одинаковые "
                         "поля у вас задуманы.",
                         "A font with no spacing: zero sidebearings, or the same ones on nearly every letter. "
                         "Monospaced and pixel fonts are left alone. Untick if your equal sidebearings are on purpose."),
    "from_zero": ("Своей расстановки у шрифта нет — поля поставлены с нуля. Белое у стороны H: %s "
                  "тысячных кегля (%s). Плотнее или свободнее — в тонкой настройке: «С нуля: поле H» "
                  "или «Разрядка».",
                  "The font has no spacing of its own, so it was spaced from scratch. White beside H: %s "
                  "thousandths of the em (%s). Tighter or looser: Fine-tuning → “From zero: H side” or "
                  "“Looseness”."),
    "side_guessed": ("угадано по форме; точнее — если расставить на глаз n и o и запустить снова",
                     "guessed from the shapes; for more accuracy, space n and o by eye and run again"),
    "side_set": ("задано числом", "set as a number"),
    "side_hand": ("по буквам, расставленным вручную: %s", "from the letters spaced by hand: %s"),
    "reset": ("Сбросить настройки", "Reset settings"),
    # ── справа ──
    "tab_settings": ("Настройки", "Settings"),
    "tab_summary": ("Итог", "Summary"),
    "to_panel": ("Панелью", "As panel"),
    "to_window": ("Окном", "As window"),
    "to_panel_tip": ("Узкой панелью у края окна FontLab. Можно и перетащить окно за шапку к краю окна шрифта, "
                     "панелей FontLab или экрана — оно прилипнет и станет панелью.",
                     "A narrow panel at the edge of the FontLab window. You can also drag the window by its "
                     "title bar to the edge of the font window, FontLab's panels or the screen — it snaps "
                     "and becomes a panel."),
    "to_window_tip": ("Широким окном. Можно и оттащить панель за шапку от края — она станет окном.",
                      "A wide window. You can also drag the panel away from the edge by its title bar."),
    "tab_preview": ("Строка", "Preview"),
    "tab_edits": ("Правки", "Edits"),
    "empty": ("<h2>Как это работает</h2><ol>"
              "<li>Слева выберите, что считать и для каких знаков.</li>"
              "<li><b>Посчитать</b> — расчёт; шрифт не меняется.</li>"
              "<li>Проверьте итог, строку «было / станет» и правки: лишнее можно снять галочкой.</li>"
              "<li><b>Применить</b> — запись в шрифт, на всех выбранных мастерах.</li>"
              "<li><b>Вернуть как было</b> — откат записи, пока окно открыто.</li></ol>"
              "<p>Окно можно не закрывать: выделяйте знаки в окне шрифта и считайте заново.</p>",
              "<h2>How it works</h2><ol>"
              "<li>On the left, choose what to calculate and for which glyphs.</li>"
              "<li><b>Calculate</b> — the font is not touched.</li>"
              "<li>Check the summary, the before/after preview and the edits: untick what you don't want.</li>"
              "<li><b>Apply</b> — writes to the font, on every chosen master.</li>"
              "<li><b>Revert</b> — undoes the write while the window is open.</li></ol>"
              "<p>You can keep the window open: select glyphs in the font window and calculate again.</p>"),
    "what_changes": ("Что изменится", "What changes"),
    "spacing": ("Апроши", "Spacing"),
    "space": ("Пробел", "Word space"),
    "kerning": ("Кернинг", "Kerning"),
    "not_calc": ("не считались", "not calculated"),
    "spacing_cap": ("знаков с новыми полями из %d", "glyphs with new sidebearings of %d"),
    "spacing_none": ("все поля в правиле", "all sidebearings fit the rule"),
    "space_cap": ("единиц, %s", "units, %s"),
    "space_none": ("в правиле — без изменений", "fits the rule — unchanged"),
    "kern_pairs": ("пар", "pairs"),
    "kern_whole": ("заменить целиком", "replace entirely"),
    "kern_whole_n": ("классов %d + %d · пар классов %s · пар знаков %s",
                     "classes %d + %d · class pairs %s · glyph pairs %s"),
    "kern_missing": ("дописать: %s пар знаков, которых в шрифте нет",
                     "add: %s glyph pairs the font doesn't have"),
    "kern_selected": ("заменить у выделенных: %s пар знаков", "replace for selected: %s glyph pairs"),
    "kern_size": ("≈ %s КБ на мастер в файле", "≈ %s KB per master in the file"),
    "notes": ("Обратите внимание", "Please note"),
    "protected": ("Поля не трогаются у %s.", "Sidebearings are kept for %s."),
    "pr_formula": ("%d с формулами метрик", "%d with metrics formulas"),
    "pr_mark": ("%d с меткой", "%d with a mark"),
    "kept_kern": ("Кернинг не тронут у %s знаков с меткой и их диакритики: прежних пар сохранено %s.",
                  "Kerning is kept for %s glyphs with a mark and their accented forms: %s old pairs kept."),
    "pr_selection": ("%d не выделенных", "%d not selected"),
    "pr_rejected": ("%d снятых вами", "%d you unticked"),
    "truncated": ("В предел не влезло пар знаков: %s (самые слабые). Предел — в «Тонкой настройке».",
                  "Glyph pairs over the limit: %s (the weakest). The limit is in Fine-tuning."),
    "kern_feature_will": ("В тексте фич шрифта (панель Features) есть фича kern с прежним кернингом — "
                          "FontLab выгружает её вместо кернинга. «Применить» её снимет "
                          "(«Вернуть как было» вернёт).",
                          "The font's feature code (Features panel) has a kern feature with the old "
                          "kerning — FontLab exports it instead of the kerning. Apply removes it "
                          "(Revert brings it back)."),
    "subset": ("Кернинг пишется на %d мастера из %d: классы у них будут свои, не как у остальных. "
               "Для вариативного шрифта надёжнее считать все мастера сразу.",
               "Kerning is written to %d of %d masters: their classes will differ from the others. "
               "For a variable font, calculating all masters at once is safer."),
    "collisions": ("В числах цифры наезжают друг на друга через запятую, точку или двоеточие: %s "
                   "(сочетаний: %d). Исправит «Тонкая настройка» → «Цифры с , . :» → «без столкновений».",
                   "In numbers the figures run into each other across a comma, period or colon: %s "
                   "(%d combinations). Fix: Fine-tuning → “Figures with , . :” → “no collisions”."),
    "tip_save": ("Откат работает, пока окно открыто; надёжнее — сохранить шрифт перед применением.",
                 "Revert works while the window is open; saving the font before applying is safer."),
    "control": ("Контрольные пары", "Control pairs"),
    "biggest": ("Крупнейшие правки полей", "Largest sidebearing changes"),
    "changes": ("Крупнейшие изменения пар", "Largest pair changes"),
    "glyph": ("Знак", "Glyph"),
    "master": ("Мастер", "Master"),
    "lsb": ("Левое", "Left"),
    "rsb": ("Правое", "Right"),
    "width": ("Ширина", "Width"),
    "pair": ("Пара", "Pair"),
    "before": ("Было", "Before"),
    "after": ("Станет", "After"),
    "now": ("Сейчас", "Now"),
    "applied_banner": ("✓ Записано в шрифт: знаков %d, пар классов %s, пар знаков %s. Сверка: %s.",
                       "✓ Written to the font: glyphs %d, class pairs %s, glyph pairs %s. Check: %s."),
    "reverted_banner": ("↺ Возвращено как было. Итог ниже снова можно применить.",
                        "↺ Reverted. The result below can be applied again."),
    "cancel": ("Отмена", "Cancel"),
    # строка
    "preview_empty": ("Нажмите «Посчитать» — здесь будет строка «как сейчас / как станет».",
                      "Press Calculate — the before/after line will appear here."),
    "preview_kern": ("с кернингом", "with kerning"),
    "preview_hint": ("Сверху — как сейчас, снизу — как станет; синим — знаки с новыми полями. "
                     "«/имя» — знак по имени: /A/V/period.",
                     "Top — now, bottom — after; blue — glyphs with new sidebearings. "
                     "“/name” — a glyph by name: /A/V/period."),
    # правки
    "search": ("Найти знак: символ или имя", "Find a glyph: character or name"),
    "edits_glyphs": ("Поля знаков: %d", "Sidebearings: %d"),
    "edits_pairs_top": ("Пары кернинга: %d крупнейших изменений", "Kerning pairs: %d largest changes"),
    "edits_pairs_glyph": ("Пары кернинга с «%s»: %d", "Kerning pairs with “%s”: %d"),
    "edits_pairs_none": ("Знак «%s» не найден", "Glyph “%s” not found"),
    "edits_hint": ("Снятая галочкой пара останется как в шрифте. Снятый знак не правится — "
                   "нажмите «Посчитать», чтобы учесть (кернинг пересчитается под его поля).",
                   "An unticked pair stays as in the font. An unticked glyph is not respaced — "
                   "press Calculate to take it into account (kerning is re-measured)."),
    "kept": ("как есть", "kept"),
    "counting_pairs": ("считаю пары мастера…", "finding the master's pairs…"),
    # кнопки и ход
    "calc": ("Посчитать", "Calculate"),
    "stop": ("Стоп", "Stop"),
    "apply": ("Применить", "Apply"),
    "revert": ("Вернуть как было", "Revert"),
    "save": ("Сохранить отчёт…", "Save report…"),
    "close": ("Закрыть", "Close"),
    "ready": ("Выберите, что считать, и нажмите «Посчитать». Шрифт не изменится до «Применить».",
              "Choose what to calculate and press Calculate. The font is not touched until Apply."),
    "progress": ("Считаю…", "Calculating…"),
    "stopped": ("Остановлено. Шрифт не менялся.", "Stopped. The font was not changed."),
    "stopped_kept": ("Остановлено. Шрифт не менялся; итог прошлого расчёта остаётся в силе.",
                     "Stopped. The font was not changed; the previous result still stands."),
    "nothing": ("Ничего не выбрано: отметьте апроши, пробел или кернинг.",
                "Nothing chosen: tick spacing, word space or kerning."),
    "no_masters": ("Не выбран ни один мастер.", "No master chosen."),
    "sel_unknown": ("Не удалось узнать выделение в окне шрифта.", "Could not read the font window selection."),
    "sel_empty": ("В окне шрифта ничего не выделено.", "Nothing is selected in the font window."),
    "done_calc": ("Посчитано за %.0f с. Проверьте итог и нажмите «Применить».",
                  "Calculated in %.0f s. Check the summary and press Apply."),
    "stale": ("Настройки изменились — нажмите «Посчитать», чтобы обновить итог.",
              "Settings changed — press Calculate to update the result."),
    "stale_glyphs": ("Снятые знаки учтутся после «Посчитать».", "Unticked glyphs take effect after Calculate."),
    "font_changed": ("Шрифт изменился после расчёта — посчитайте заново.",
                     "The font changed after the calculation — calculate again."),
    "applying": ("Записываю…", "Writing…"),
    "done_apply": ("Записано: знаков %d, пар классов %s, пар знаков %s. Сверка: %s.",
                   "Written: glyphs %d, class pairs %s, glyph pairs %s. Check: %s."),
    "check_ok": ("всё сходится", "all matches"),
    "check_bad": ("расхождений %d — первые: %s", "%d differences — first: %s"),
    "panels": ("Панели Kerning, Classes и Features сами не обновляются — закройте и откройте их.",
               "The Kerning, Classes and Features panels don't refresh by themselves — reopen them."),
    "revert_q": ("Вернуть шрифт к состоянию до последней записи? Правки кернинга, сделанные после "
                 "неё вручную, пропадут.", "Revert the font to its state before the last write? "
                 "Kerning edits made by hand after it will be lost."),
    "reverting": ("Возвращаю…", "Reverting…"),
    "done_revert": ("Возвращено как было. Сверка: %s.", "Reverted. Check: %s."),
    "lost_zero": (" Пары с классом и нулём (%d) FontLab не хранит — они не вернулись.",
                  " Class pairs with zero (%d) are not kept by FontLab — they were not restored."),
    "save_title": ("Папка для отчёта", "Folder for the report"),
    "saved": ("Сохранено файлов: %d — в «%s».", "Saved %d files to “%s”."),
    "error": ("Ошибка", "Error"),
    "report_bug": ("Сообщить об ошибке", "Report a bug"),
    "report_bug_tip": ("Скопировать адрес автора: %s", "Copy the author's address: %s"),
    "email_copied": ("Адрес %s скопирован.\n\nНапишите, что случилось: какой шрифт (если можно — приложите "
                     "его), что нажимали и что увидели. Снимок окна очень помогает.",
                     "The address %s is copied.\n\nPlease describe what happened: which font (attach it if you "
                     "can), what you pressed and what you saw. A screenshot helps a lot."),
    "site_tip": ("Сайт автора: %s", "The author's site: %s"),
    "free": ("Бесплатно и с открытым кодом ·", "Free and open source ·"),
    "support": ("Поддержать автора ♥", "Support the author ♥"),
    "support_tip": ("Сценарий бесплатный и таким останется. Поддержка — по желанию: она помогает находить "
                    "время на исправления и новые возможности.",
                    "The script is free and will stay free. Support is voluntary: it helps to find time for "
                    "fixes and new features."),
    "support_after": ("Если сценарий сэкономил вам время, автора можно поддержать — по желанию.",
                      "If the script saved you time, you can support the author — if you wish."),
    "diff_width": ("%s/%s: ширина %d вместо %d", "%s/%s: width %d instead of %d"),
    "diff_shift": ("%s/%s: рисунок сдвинут на %.2f вместо %d", "%s/%s: outline moved by %.2f instead of %d"),
    "diff_kern": ("%s %s/%s: кернинг %s вместо %s", "%s %s/%s: kerning %s instead of %s"),
    "diff_offset": ("%s/%s: рисунок на %.2f в стороне", "%s/%s: outline off by %.2f"),
    "diff_pairs": ("%s: пар кернинга не сходится %d", "%s: %d kerning pairs differ"),
    "diff_classes": ("%s: классы кернинга не те", "%s: kerning classes differ"),
    "choosing_pairs": ("кернинг: подбираю пары", "kerning: choosing pairs"),
}

# Окно по-немецки: отдельный словарь, чтобы пары _TEXT шли в веб-версию как есть
_TEXT_DE = {
    "title": "Autokerner",
    "masters_n": "Master: %d",
    "glyphs_n": "Glyphen: %d",
    "no_font": "Öffnen Sie eine Schrift in FontLab und starten Sie das Skript erneut.",
    # ── слева: что сделать ──
    "sec_what": "Was ändern",
    "do_spacing": "Zurichtung – Vor- und Nachbreiten",
    "do_spacing_tip": "Vor- und Nachbreite jeder Glyphe nach der Weißfläche, auf allen Mastern. "
                      "Akzentbuchstaben und zusammengesetzte Glyphen folgen ihrer Grundform.",
    "do_space": "Wortabstand – Breite des Leerzeichens",
    "do_space_tip": "Breite des Leerzeichens als Anteil am Median der Kleinbuchstabenbreiten (siehe "
                    "„Feineinstellung“). Geändert nur, wenn das Leerzeichen deutlich breiter ist als die Regel.",
    "do_kerning": "Kerning – Klassen und Paare",
    "do_kerning_tip": "Das Kerning wird mit den neuen Vor- und Nachbreiten gemessen: Klassen gemeinsam für "
                      "alle Master, Werte je Master.",
    "mode_label": "Eigenes Kerning der Schrift:",
    "mode_replace": "Ganz ersetzen",
    "mode_merge": "Ergänzen",
    "mode_replace_note": "Bisherige Kerningpaare und -klassen werden entfernt, die neuen geschrieben.",
    "mode_merge_note": "Ihre Paare und Klassen bleiben, wie sie sind; nur fehlende Paare kommen hinzu "
                       "(als Glyphenpaare). Ein leeres Kerning wird vollständig geschrieben.",
    "sec_where": "Welche Glyphen",
    "glyphs_all": "Alle Glyphen",
    "glyphs_sel": "Nur die im Schriftfenster ausgewählten",
    "glyphs_sel_n": "Nur die im Schriftfenster ausgewählten (jetzt: %d)",
    "glyphs_sel_tip": "Nur die ausgewählten Glyphen werden zugerichtet; das Kerning wird als Glyphenpaare mit "
                      "ihnen geschrieben, das übrige bleibt unberührt. Die Auswahl wird beim Klick auf "
                      "„Berechnen“ gelesen.",
    "keep_formula": "Glyphen mit Metrikformeln nicht ändern",
    "keep_formula_tip": "Glyphen, deren Vorbreite, Nachbreite oder Breite eine FontLab-Formel ist (=H, =n+10): "
                        "Eine Änderung würde die Formel überschreiben.",
    "keep_marked": "Glyphen mit Farbmarkierung nicht ändern",
    "keep_marked_tip": "Markieren Sie von Hand abgestimmte Glyphen farbig (Glyph → Flag) – die Berechnung lässt "
                       "dann ihre Vor- und Nachbreiten und ihr Kerning unberührt: Paare mit ihnen bleiben, wie sie "
                       "waren, ebenso die der Akzentbuchstaben auf ihrer Grundlage. Bekommt ein Nachbar neue Vor- "
                       "und Nachbreiten, behalten diese Paare ihre Werte, der Abstand kann aber anders wirken.",
    "nbsp": "Geschütztes Leerzeichen wie Wortabstand",
    "nbsp_tip": "Unterschiedliche Breiten von Leerzeichen und geschütztem Leerzeichen sind ein häufiger Fehler "
                "(FontBakery prüft das).",
    "sec_masters": "Master",
    "sec_rule": "Regel",
    "preset": "Vorgabe:",
    "custom": "Eigene",
    "custom_note": "Werte von Hand geändert.",
    "fine": "Feineinstellung",
    "sub_spacing": "Zurichtung",
    "looseness": "Laufweite",
    "looseness_tip": "Insgesamt enger (−) oder weiter (+): Der Zielwert der Weißfläche wird mit 1 + Anteil "
                     "multipliziert. 0 behält den Grauwert der Schrift. Alle Glyphen einer Gruppe verschieben "
                     "sich gleich.",
    "threshold": "Empfindlichkeit",
    "threshold_tip": "Eine Glyphe wird geändert, wenn eine Vor- oder Nachbreite um mehr als so viele "
                     "Tausendstel Geviert von der Regel abweicht. Kleiner – mehr Änderungen.",
    "word_gap": "Wortabstand – Anteil",
    "word_gap_tip": "Zielbreite des Leerzeichens – dieser Anteil am Median der Kleinbuchstabenbreiten.",
    "space_fit": "Breiter Wortabstand",
    "space_fit_items": "bis zum Toleranzrand|bis zum Zielwert",
    "space_fit_tip": "Ein Leerzeichen, das um mehr als ein Viertel breiter ist als der Zielwert, wird verengt. "
                     "„Bis zum Toleranzrand“ ist vorsichtig: Das Leerzeichen bleibt am oberen Rand der "
                     "Toleranz. „Bis zum Zielwert“ geht ganz bis zur Zielbreite, wie in der ursprünglichen "
                     "Regel: ein dichterer Satz, gut für schmale Schriften und Akzidenzschriften.",
    "sub_kerning": "Kerning",
    "strength": "Stärke",
    "strength_tip": "Wie viel der weißen „Tasche“ zwischen den Glyphen geschlossen wird: 100 % – die Regel, "
                    "mehr – stärkere Paare.",
    "kthreshold": "Paare erst ab",
    "kthreshold_tip": "Paare unter diesem Wert (Tausendstel Geviert) werden nicht geschrieben.",
    "clearance": "Mindestabstand",
    "clearance_tip": "Die Formen eines Paares kommen sich nie näher als dieser Wert (Tausendstel Geviert).",
    "precision": "Klassengenauigkeit",
    "precision_tip": "Wie weit ein Klassenpaar vom genauen Wert abweichen darf. Feiner – mehr Klassen und "
                     "Paare, größere Datei.",
    "limit": "Höchstzahl Glyphenpaare",
    "limit_tip": "Wie viele Glyphenpaare (Ausnahmen von den Klassen) geschrieben werden. Gemessen werden immer "
                 "alle Paare; die Grenze greift nur bei großen Schriften (Hunderte Glyphen und mehr): Dann "
                 "werden die auffälligsten geschrieben, und die Klassengenauigkeit wird gröber.",
    "round": "Rundung",
    "round_tip": "Werte sind Vielfache der Schrittweite (gerundet in Richtung weiter).",
    "max_tight": "Nie enger als",
    "max_tight_tip": "Das stärkste Paar wird auf diesen Wert begrenzt (Tausendstel Geviert); 0 – ohne Grenze.",
    "max_loose": "Nie weiter als",
    "max_loose_tip": "Ein Paar wird nie um mehr als diesen Wert (Tausendstel Geviert) auseinandergerückt, auch "
                     "wenn sich die Formen näher kommen als der Mindestabstand: Sonst könnten der Schwanz des Q "
                     "oder ein Bruchstrich ein Paar um ein halbes Geviert auseinanderschieben; 0 – ohne Grenze.",
    "no_limit": "ohne Grenze",
    "figures": "Ziffern mit , . :",
    "figures_items": "wie in der Regel|ohne Kollision (7,4 · 3.5 · 12:30)|ohne Kerning",
    "figures_tip": "Die Regel zieht Komma, Punkt und Doppelpunkt paarweise an eine Ziffer heran, sodass in "
                   "Zahlen wie 7,4 die Ziffern über das Zeichen hinweg ineinanderlaufen können. „Ohne "
                   "Kollision“: Die rechte Ziffer wird nie an das Zeichen oder darüber gezogen, und über "
                   "das Zeichen hinweg stehen die Ziffern nie enger als direkt nebeneinander – dafür wird das "
                   "Paar Ziffer + Zeichen gelockert (das Komma bleibt bei der Ziffer links: „1917,“). „Ohne "
                   "Kerning“ lässt diese Paare ungekernt.",
    "per_mille": " /1000",
    "side_h": "Von Grund auf: H-Seite",
    "side_h_tip": "Hat die Schrift keine eigene Zurichtung (Vor- und Nachbreiten null oder bei allen "
                  "Buchstaben gleich), richtet das Skript sie von Grund auf zu. Den Grauwert nimmt es von "
                  "Musterbuchstaben, wenn Sie einige von n o h u m i l H O I N U nach Augenmaß zugerichtet "
                  "haben: Die übrigen folgen ihnen (die Muster werden mit den anderen ausgeglichen). Sonst wird "
                  "der Grauwert aus den Buchstabenformen geschätzt. Hier lässt er sich als Zahl setzen: das "
                  "mittlere Weiß neben H, in Tausendstel Geviert; „auto“ – nicht gesetzt. Bei einer "
                  "zugerichteten Schrift hat dieses Feld keine Wirkung.",
    "auto": "auto",
    "from_zero_on": "Schrift ohne Zurichtung von Grund auf zurichten",
    "from_zero_on_tip": "Eine Schrift ohne Zurichtung: Vor- und Nachbreiten null oder bei fast allen "
                        "Buchstaben gleich. Dicktengleiche und Pixelschriften bleiben unberührt. Entfernen Sie "
                        "das Häkchen, wenn Ihre gleichen Vor- und Nachbreiten Absicht sind.",
    "from_zero": "Die Schrift hat keine eigene Zurichtung, deshalb wurde sie von Grund auf zugerichtet. Weiß "
                 "neben H: %s Tausendstel Geviert (%s). Enger oder weiter: „Feineinstellung“ → „Von Grund "
                 "auf: H-Seite“ oder „Laufweite“.",
    "side_guessed": "aus den Formen geschätzt; genauer, wenn Sie n und o nach Augenmaß zurichten und neu "
                    "berechnen",
    "side_set": "als Zahl gesetzt",
    "side_hand": "nach den von Hand zugerichteten Buchstaben: %s",
    "reset": "Einstellungen zurücksetzen",
    # ── справа ──
    "tab_settings": "Einstellungen",
    "tab_summary": "Übersicht",
    "to_panel": "Als Panel",
    "to_window": "Als Fenster",
    "to_panel_tip": "Als schmales Panel am Rand des FontLab-Fensters. Sie können das Fenster auch an der "
                    "Titelleiste an den Rand des Schriftfensters, der FontLab-Panels oder des Bildschirms "
                    "ziehen – es rastet ein und wird zum Panel.",
    "to_window_tip": "Als breites Fenster. Sie können das Panel auch an der Titelleiste vom Rand wegziehen.",
    "tab_preview": "Vorschau",
    "tab_edits": "Änderungen",
    "empty": "<h2>So funktioniert es</h2><ol>"
             "<li>Wählen Sie links, was berechnet werden soll und für welche Glyphen.</li>"
             "<li><b>Berechnen</b> – die Schrift bleibt unverändert.</li>"
             "<li>Prüfen Sie die Übersicht, die Vorschau „jetzt / nachher“ und die Änderungen: Was Sie nicht "
             "wollen, wählen Sie ab.</li>"
             "<li><b>Anwenden</b> – schreibt in die Schrift, auf allen gewählten Mastern.</li>"
             "<li><b>Rückgängig</b> – nimmt das Schreiben zurück, solange das Fenster offen ist.</li></ol>"
             "<p>Das Fenster kann offen bleiben: Wählen Sie Glyphen im Schriftfenster aus und berechnen Sie "
             "neu.</p>",
    "what_changes": "Was sich ändert",
    "spacing": "Zurichtung",
    "space": "Wortabstand",
    "kerning": "Kerning",
    "not_calc": "nicht berechnet",
    "spacing_cap": "Glyphen mit neuen Vor- und Nachbreiten von %d",
    "spacing_none": "alle Vor- und Nachbreiten passen zur Regel",
    "space_cap": "Einheiten, %s",
    "space_none": "passt zur Regel – unverändert",
    "kern_pairs": "Paare",
    "kern_whole": "ganz ersetzen",
    "kern_whole_n": "Klassen %d + %d · Klassenpaare %s · Glyphenpaare %s",
    "kern_missing": "ergänzen: %s Glyphenpaare, die der Schrift fehlen",
    "kern_selected": "für Ausgewählte ersetzen: %s Glyphenpaare",
    "kern_size": "≈ %s KB je Master in der Datei",
    "notes": "Bitte beachten",
    "protected": "Vor- und Nachbreiten bleiben unverändert bei %s.",
    "pr_formula": "%d mit Metrikformeln",
    "pr_mark": "%d mit Markierung",
    "kept_kern": "Kerning unverändert bei %s markierten Glyphen und ihren Akzentformen: %s bisherige Paare "
                 "erhalten.",
    "pr_selection": "%d nicht ausgewählten",
    "pr_rejected": "%d von Ihnen abgewählten",
    "truncated": "Glyphenpaare über der Grenze: %s (die schwächsten). Die Grenze steht in der "
                 "„Feineinstellung“.",
    "kern_feature_will": "Der Feature-Code der Schrift (Panel Features) enthält ein kern-Feature mit dem "
                         "bisherigen Kerning – FontLab exportiert es anstelle des Kernings. „Anwenden“ entfernt "
                         "es („Rückgängig“ stellt es wieder her).",
    "subset": "Das Kerning wird auf %d von %d Mastern geschrieben; deren Klassen weichen dann von den übrigen "
              "ab. Bei einer variablen Schrift ist es sicherer, alle Master auf einmal zu berechnen.",
    "collisions": "In Zahlen laufen die Ziffern über Komma, Punkt oder Doppelpunkt ineinander: %s "
                  "(%d Kombinationen). Abhilfe: „Feineinstellung“ → „Ziffern mit , . :“ → „ohne Kollision“.",
    "tip_save": "„Rückgängig“ wirkt, solange das Fenster offen ist; sicherer ist es, die Schrift vor dem "
                "Anwenden zu speichern.",
    "control": "Kontrollpaare",
    "biggest": "Größte Änderungen der Vor- und Nachbreiten",
    "changes": "Größte Paaränderungen",
    "glyph": "Glyphe",
    "master": "Master",
    "lsb": "Vorbreite",
    "rsb": "Nachbreite",
    "width": "Breite",
    "pair": "Paar",
    "before": "Vorher",
    "after": "Nachher",
    "now": "Jetzt",
    "applied_banner": "✓ In die Schrift geschrieben: Glyphen %d, Klassenpaare %s, Glyphenpaare %s. Prüfung: %s.",
    "reverted_banner": "↺ Rückgängig gemacht. Das Ergebnis unten kann erneut angewendet werden.",
    "cancel": "Abbrechen",
    # строка
    "preview_empty": "Klicken Sie auf „Berechnen“ – hier erscheint die Zeile „jetzt / nachher“.",
    "preview_kern": "mit Kerning",
    "preview_hint": "Oben – jetzt, unten – nachher; blau – Glyphen mit neuen Vor- und Nachbreiten. "
                    "„/name“ – eine Glyphe nach Namen: /A/V/period.",
    # правки
    "search": "Glyphe suchen: Zeichen oder Name",
    "edits_glyphs": "Vor- und Nachbreiten: %d",
    "edits_pairs_top": "Kerningpaare: %d größte Änderungen",
    "edits_pairs_glyph": "Kerningpaare mit „%s“: %d",
    "edits_pairs_none": "Glyphe „%s“ nicht gefunden",
    "edits_hint": "Ein abgewähltes Paar bleibt, wie es in der Schrift ist. Eine abgewählte Glyphe wird nicht "
                  "zugerichtet – klicken Sie auf „Berechnen“, um das zu berücksichtigen (das Kerning wird neu "
                  "gemessen).",
    "kept": "unverändert",
    "counting_pairs": "Paare des Masters werden gesucht…",
    # кнопки и ход
    "calc": "Berechnen",
    "stop": "Stopp",
    "apply": "Anwenden",
    "revert": "Rückgängig",
    "save": "Bericht speichern…",
    "close": "Schließen",
    "ready": "Wählen Sie, was berechnet werden soll, und klicken Sie auf „Berechnen“. Die Schrift bleibt bis "
             "„Anwenden“ unverändert.",
    "progress": "Wird berechnet…",
    "stopped": "Angehalten. Die Schrift wurde nicht geändert.",
    "stopped_kept": "Angehalten. Die Schrift wurde nicht geändert; das vorige Ergebnis gilt weiter.",
    "nothing": "Nichts gewählt: Haken Sie Zurichtung, Wortabstand oder Kerning an.",
    "no_masters": "Kein Master gewählt.",
    "sel_unknown": "Die Auswahl im Schriftfenster konnte nicht gelesen werden.",
    "sel_empty": "Im Schriftfenster ist nichts ausgewählt.",
    "done_calc": "Berechnet in %.0f s. Prüfen Sie die Übersicht und klicken Sie auf „Anwenden“.",
    "stale": "Einstellungen geändert – klicken Sie auf „Berechnen“, um das Ergebnis zu aktualisieren.",
    "stale_glyphs": "Abgewählte Glyphen wirken nach „Berechnen“.",
    "font_changed": "Die Schrift hat sich nach der Berechnung geändert – bitte neu berechnen.",
    "applying": "Wird geschrieben…",
    "done_apply": "Geschrieben: Glyphen %d, Klassenpaare %s, Glyphenpaare %s. Prüfung: %s.",
    "check_ok": "alles stimmt",
    "check_bad": "%d Abweichungen – die ersten: %s",
    "panels": "Die Panels Kerning, Classes und Features aktualisieren sich nicht von selbst – schließen und "
              "öffnen Sie sie neu.",
    "revert_q": "Die Schrift auf den Stand vor dem letzten Schreiben zurücksetzen? Danach von Hand "
                "vorgenommene Kerningänderungen gehen verloren.",
    "reverting": "Wird zurückgesetzt…",
    "done_revert": "Rückgängig gemacht. Prüfung: %s.",
    "lost_zero": " Klassenpaare mit null (%d) speichert FontLab nicht – sie wurden nicht wiederhergestellt.",
    "save_title": "Ordner für den Bericht",
    "saved": "%d Dateien in „%s“ gespeichert.",
    "error": "Fehler",
    "report_bug": "Fehler melden",
    "report_bug_tip": "Adresse des Autors kopieren: %s",
    "email_copied": "Die Adresse %s ist kopiert.\n\nBitte beschreiben Sie, was passiert ist: welche Schrift "
                    "(hängen Sie sie wenn möglich an), was Sie geklickt und was Sie gesehen haben. Ein "
                    "Bildschirmfoto hilft sehr.",
    "site_tip": "Website des Autors: %s",
    "free": "Kostenlos und quelloffen ·",
    "support": "Den Autor unterstützen ♥",
    "support_tip": "Das Skript ist kostenlos und bleibt es. Unterstützung ist freiwillig: Sie hilft, Zeit für "
                   "Korrekturen und neue Funktionen zu finden.",
    "support_after": "Wenn Ihnen das Skript Zeit gespart hat, können Sie den Autor unterstützen – freiwillig.",
    "diff_width": "%s/%s: Breite %d statt %d",
    "diff_shift": "%s/%s: Kontur um %.2f statt %d verschoben",
    "diff_kern": "%s %s/%s: Kerning %s statt %s",
    "diff_offset": "%s/%s: Kontur um %.2f versetzt",
    "diff_pairs": "%s: %d Kerningpaare weichen ab",
    "diff_classes": "%s: Kerningklassen weichen ab",
    "choosing_pairs": "Kerning: Paare werden ausgewählt",
}

# Наборы правила по-немецки: (название, пояснение)
_PRESET_DE = {
    "default": ("Text – Standardregel", "Für Fließtext und die meisten Schriften."),
    "display": ("Display – enger, stärkeres Kerning",
                "Für große Schriftgrade: Laufweite −8 %, stärkeres Kerning, kleinerer Mindestabstand, feinere "
                "Klassen, Paare ohne Grenze – größere Datei."),
    "light": ("Leichtes Kerning – kleine Datei",
              "Nur sichtbare Paare, Werte in Fünferschritten, bis zu 3 000 Glyphenpaare – für das Web und "
              "kleine Dateien."),
}

_LANGS = ("ru", "en", "de")


def _lang():
    """Язык окна — по языку интерфейса системы: русский — по-русски,
    немецкий — по-немецки, любой другой — по-английски.
    AUTOKERNER_LANG=ru|en|de — для проверки"""
    свой = os.environ.get("AUTOKERNER_LANG", "").lower()
    if свой in _LANGS:
        return _LANGS.index(свой)
    try:
        from PythonQt import QtCore
        локаль = QtCore.QLocale.system()
        языки = локаль.uiLanguages
        if callable(языки):
            языки = языки()
        первый = (str(языки[0]) if языки else str(локаль.name())).lower()
        return 0 if первый.startswith("ru") else 2 if первый.startswith("de") else 1
    except Exception:
        return 1


LANG = _lang()


def t(key):
    return _TEXT_DE[key] if LANG == 2 else _TEXT[key][LANG]


def preset_title(key):
    return _PRESET_DE[key][0] if LANG == 2 else PRESET_TITLES[key][LANG]


def preset_note(key):
    return _PRESET_DE[key][1] if LANG == 2 else PRESET_NOTES[key][LANG]


def support_url():
    """Страница скрипта с кнопкой «Поддержать» — на языке окна (немецкой
    страницы у сайта нет — английская)"""
    return SUPPORT_URL + ("" if LANG == 0 else "?lang=en")


# Сообщения о ходе и ошибки идут из расчёта и моста по-русски; окно на
# английском и немецком переводит их здесь
_TR_EN = [(re.compile(шаблон), замена) for шаблон, замена in (
    (r"^читаю мастер (\d+) из (\d+): знак (\d+) из (\d+)$", r"reading master \1 of \2: glyph \3 of \4"),
    (r"^апроши: мастер (\d+) из (\d+)$", r"spacing: master \1 of \2"),
    (r"^кернинг: мастер (\d+) из (\d+), знак (\d+) из (\d+)$", r"kerning: master \1 of \2, glyph \3 of \4"),
    (r"^кернинг: мастер (\d+) из (\d+)$", r"kerning: master \1 of \2"),
    (r"^кернинг: классы на все мастера$", r"kerning: classes for all masters"),
    (r"^кернинг: классы, точность ([\d.]+) — знак (\d+) из (\d+)$",
     r"kerning: classes, precision \1 — glyph \2 of \3"),
    (r"^кернинг: пары знаков — знак (\d+) из (\d+)$", r"kerning: glyph pairs — glyph \1 of \2"),
    (r"^кернинг: снимок прежнего$", r"kerning: saving the current kerning"),
    (r"^кернинг: подбираю пары$", r"kerning: choosing pairs"),
    (r"^кернинг: снимаю прежний$", r"kerning: removing the old kerning"),
    (r"^возвращаю поля$", r"restoring sidebearings"),
    (r"^возвращаю кернинг$", r"restoring kerning"),
    (r"^Нет открытого шрифта$", r"No font is open"),
    (r"^компоненты «(.+)» ссылаются по кругу$", r"components of “\1” refer to each other in a loop"),
    (r"^знаки мастеров разошлись — кернинг по мастерам не сводится$",
     r"the masters have different glyph sets — kerning cannot be combined across them"),
)]

_TR_DE = [(re.compile(шаблон), замена) for шаблон, замена in (
    (r"^читаю мастер (\d+) из (\d+): знак (\d+) из (\d+)$", r"Master \1 von \2 wird gelesen: Glyphe \3 von \4"),
    (r"^апроши: мастер (\d+) из (\d+)$", r"Zurichtung: Master \1 von \2"),
    (r"^кернинг: мастер (\d+) из (\d+), знак (\d+) из (\d+)$", r"Kerning: Master \1 von \2, Glyphe \3 von \4"),
    (r"^кернинг: мастер (\d+) из (\d+)$", r"Kerning: Master \1 von \2"),
    (r"^кернинг: классы на все мастера$", r"Kerning: Klassen für alle Master"),
    (r"^кернинг: классы, точность ([\d.]+) — знак (\d+) из (\d+)$",
     r"Kerning: Klassen, Genauigkeit \1 – Glyphe \2 von \3"),
    (r"^кернинг: пары знаков — знак (\d+) из (\d+)$", r"Kerning: Glyphenpaare – Glyphe \1 von \2"),
    (r"^кернинг: снимок прежнего$", r"Kerning: bisheriges Kerning wird gesichert"),
    (r"^кернинг: подбираю пары$", r"Kerning: Paare werden ausgewählt"),
    (r"^кернинг: снимаю прежний$", r"Kerning: bisheriges Kerning wird entfernt"),
    (r"^возвращаю поля$", r"Vor- und Nachbreiten werden wiederhergestellt"),
    (r"^возвращаю кернинг$", r"Kerning wird wiederhergestellt"),
    (r"^Нет открытого шрифта$", r"Keine Schrift geöffnet"),
    (r"^компоненты «(.+)» ссылаются по кругу$", r"Die Komponenten von „\1“ verweisen im Kreis aufeinander"),
    (r"^знаки мастеров разошлись — кернинг по мастерам не сводится$",
     r"Die Master haben unterschiedliche Glyphensätze – das Kerning lässt sich nicht über alle Master "
     r"zusammenführen"),
)]


def _tr(текст):
    """Сообщение расчёта на языке окна"""
    текст = str(текст)
    if LANG == 0:
        return текст
    for шаблон, замена in (_TR_DE if LANG == 2 else _TR_EN):
        if шаблон.match(текст):
            return шаблон.sub(замена, текст)
    return текст


def _e(x):
    return html.escape(str(x))


def _num(x):
    return ("%d" % x) if float(x).is_integer() else ("%.1f" % x)


def _n(x):
    """Число с разрядами: 12 000 / 12,000"""
    текст = "{:,}".format(int(x))
    return текст if LANG == 1 else текст.replace(",", " ")


def _table(head, rows):
    h = ["<table cellspacing=0 cellpadding=4 border=1 width='100%'><tr>"]
    h += ["<th align=left>%s</th>" % _e(x) for x in head]
    h.append("</tr>")
    for ряд in rows:
        h.append("<tr>" + "".join("<td>%s</td>" % x for x in ряд) + "</tr>")
    h.append("</table>")
    return "".join(h)


def _was(было, стало):
    if было == стало:
        return _num(стало)
    return "%s → <b>%s</b>" % (_num(было), _num(стало))


def _card(заголовок, крупно, *подписи):
    return ("<td valign=top><small>%s</small><br>"
            "<span style='font-size:17pt; font-weight:600'>%s</span><br><small>%s</small></td>"
            % (_e(заголовок), крупно, "<br>".join(_e(п) for п in подписи)))


def report_html(report, info):
    """Итог для вкладки «Итог»: сверху три карточки «что изменится»
    (апроши, пробел, кернинг), под ними — что важно знать, ниже — таблицы
    для тех, кто хочет подробностей"""
    h = []
    if info.get("banner"):
        h.append("<p><b>%s</b></p><hr>" % info["banner"])
    h.append("<h2>%s</h2>" % _e(t("what_changes")))
    карточки = []
    if not info["spacing"]:
        карточки.append(_card(t("spacing"), "—", t("not_calc")))
    elif report.spacing_glyphs:
        карточки.append(_card(t("spacing"), _n(report.spacing_glyphs), t("spacing_cap") % report.glyphs))
    else:
        карточки.append(_card(t("spacing"), "0", t("spacing_none")))
    if not info["space"]:
        карточки.append(_card(t("space"), "—", t("not_calc")))
    elif report.space:
        m, было, стало = report.space[0]
        карточки.append(_card(t("space"), _was(было, стало),
                       t("space_cap") % (m + (" …" if len(report.space) > 1 else ""))))
    else:
        карточки.append(_card(t("space"), "—", t("space_none")))
    a = report.kern_after
    if not a:
        карточки.append(_card(t("kerning"), "—", t("not_calc")))
    else:
        было = report.kern_before[0][1] if report.kern_before else 0
        вид = info["mode"]
        размер = t("kern_size") % _n(max(1, info["size"] // 1000))
        if вид == WHOLE:
            крупно = "%s → <b>%s</b> %s" % (_n(было), _n(a["cells"] + a["pairs"]), _e(t("kern_pairs")))
            карточки.append(_card(t("kerning"), крупно, t("kern_whole"), t("kern_whole_n") % (
                a["left"], a["right"], _n(a["cells"]), _n(a["pairs"])), размер))
        elif вид == MISSING:
            крупно = "%s → <b>%s</b> %s" % (_n(было), _n(было + info["writes"]), _e(t("kern_pairs")))
            карточки.append(_card(t("kerning"), крупно, t("kern_missing") % _n(info["writes"]), размер))
        else:
            карточки.append(_card(t("kerning"), _n(info["writes"]), t("kern_selected") % _n(info["writes"]),
                           размер))
    # в широком окне карточки в ряд, в узкой панели — столбиком
    if info.get("narrow"):
        h.append("<table width='100%%' cellpadding=6>%s</table>" % "".join(
            "<tr>%s</tr>" % к for к in карточки))
    else:
        h.append("<table width='100%%' cellpadding=6><tr>%s</tr></table>" % "".join(
            к.replace("<td ", "<td width='33%' ", 1) for к in карточки))

    заметки = []
    if info.get("from_zero"):
        поля = " · ".join(("%s %s" % (имя, _n(round(поле)) if поле is not None else "—")
                           if len(info["from_zero"]) > 1 else (_n(round(поле)) if поле is not None else "—"))
                          for имя, поле, _откуда, _буквы in info["from_zero"])
        _имя, _поле, откуда, буквы = info["from_zero"][0]
        заметки.append(_e(t("from_zero") % (поля, t("side_set") if откуда == "set" else
                                             t("side_hand") % " ".join(буквы) if откуда == "hand" else
                                             t("side_guessed"))))
    if info.get("collisions"):
        примеры, всего = info["collisions"]
        заметки.append(_e(t("collisions") % (" · ".join(примеры), всего)))
    pr = info.get("protected") or {}
    части = [t(ключ) % pr[причина] for причина, ключ in (
        ("formula", "pr_formula"), ("mark", "pr_mark"), ("selection", "pr_selection"),
        ("rejected", "pr_rejected")) if pr.get(причина)]
    if части:
        заметки.append(_e(t("protected") % ", ".join(части)))
    if info.get("kept"):
        заметки.append(_e(t("kept_kern") % (_n(info["kept"][0]), _n(info["kept"][1]))))
    if info.get("truncated"):
        заметки.append(_e(t("truncated") % _n(info["truncated"])))
    if info.get("kern_feature"):
        заметки.append(_e(t("kern_feature_will")))
    if info.get("subset") and info["mode"] == WHOLE:
        заметки.append(_e(t("subset") % info["subset"]))
    заметки.append("<i>%s</i>" % _e(t("tip_save")))
    h.append("<h3>%s</h3><ul>%s</ul>" % (_e(t("notes")), "".join("<li>%s</li>" % з for з in заметки)))

    if report.control:
        h.append("<h3>%s</h3>" % _e(t("control")))
        h.append(_table([t("pair")] + report.masters,
                        [[_e(текст)] + [_was(б, с) for б, с in ряд] for текст, ряд in report.control]))
    if report.spacing:
        h.append("<h3>%s</h3>" % _e(t("biggest")))
        h.append(_table([t("glyph"), t("master"), t("lsb"), t("rsb"), t("width")],
                        [[_e(п.name), _e(п.master), _was(п.lsb, п.new_lsb), _was(п.rsb, п.new_rsb),
                          _was(п.advance, п.new_advance)] for п in report.spacing[:20]]))
    if report.pair_changes:
        h.append("<h3>%s</h3>" % _e(t("changes")))
        h.append(_table([t("pair"), t("master"), t("before"), t("after")],
                        [[_e(л + " " + п), _e(m), _num(было), "<b>%s</b>" % _num(стало)]
                         for л, п, m, было, стало in report.pair_changes]))
    return "".join(h)


def check(source, result, before, masters, after):
    """Сверка записанного обратным чтением: поля, пробел и каждая пара
    знаков на каждом мастере против `after[w](л, п)`. Ответ — расхождения
    текстом"""
    после = source.read(masters=masters)
    плохо = []
    for w, (до, стало) in enumerate(zip(before, после)):
        for g in до.glyphs:
            i = стало.by_name(g.name)
            if i is None:
                continue
            h = стало.glyphs[i]
            место = result.spacing.get(g.name, {}).get(w)
            dx, ширина = место if место is not None else (0, g.advance)
            if g.codes and 0x20 in g.codes and w in result.space:
                ширина = result.space[w]
            if h.advance != ширина:
                плохо.append(t("diff_width") % (g.name, до.label, h.advance, ширина))
            r0, r1 = contours_rect(g.contours), contours_rect(h.contours)
            if r0 is not None and r1 is not None and abs(r1[0] - (r0[0] + dx)) > 0.01:
                плохо.append(t("diff_shift") % (g.name, до.label, r1[0] - r0[0], dx))
        if result.kern is None:
            continue
        сейчас = OldKerning(*source.kerning_now(masters[w]))
        имена = [g.name for g in стало.glyphs]
        for л in имена:
            for п in имена:
                надо = after[w](л, п)
                есть = сейчас.value(л, п)
                if есть != надо:
                    плохо.append(t("diff_kern") % (л, п, до.label, _num(есть), _num(надо)))
    return плохо


def check_restored(source, снимок, before, masters):
    """Сверка после «Вернуть как было»: ширины и положение рисунка как до
    записи, кернинг — те же пары и классы"""
    после = source.read(masters=masters)
    плохо = []
    for до, стало in zip(before, после):
        for g in до.glyphs:
            i = стало.by_name(g.name)
            if i is None:
                continue
            h = стало.glyphs[i]
            if h.advance != g.advance:
                плохо.append(t("diff_width") % (g.name, до.label, h.advance, g.advance))
            r0, r1 = contours_rect(g.contours), contours_rect(h.contours)
            if r0 is not None and r1 is not None and abs(r1[0] - r0[0]) > 0.01:
                плохо.append(t("diff_offset") % (g.name, до.label, r1[0] - r0[0]))
    for m, (пары, классы) in снимок.kerning.items():
        есть_пары, есть_классы = source.kerning_now(m)
        ждём = {(л, лк, п, пк, float(ч)) for л, лк, п, пк, ч in пары if not ((лк or пк) and not ч)}
        есть = {(л, лк, п, пк, float(ч)) for л, лк, п, пк, ч in есть_пары}
        if ждём != есть:
            плохо.append(t("diff_pairs") % (m, len(ждём ^ есть)))
        if {к: (sorted(з), с) for к, (з, с) in классы.items()} != \
                {к: (sorted(з), с) for к, (з, с) in есть_классы.items()}:
            плохо.append(t("diff_classes") % m)
    return плохо


class _Stop(Exception):
    pass


# Списки выбора: значение → подпись
_PRECISION = [5, 10, 20, 30, 45]
_LIMITS = [3000, 12000, 30000, 100000, 0]
_ROUNDS = [1, 5, 10]
_PRESET_KEYS = ["default", "display", "light", "custom"]
_RULE_FIELDS = ("looseness", "spacing_threshold", "word_gap", "space_edge", "kern_strength", "kern_threshold",
                "kern_clearance", "kern_precision", "kern_limit", "kern_round", "kern_max_tight",
                "kern_max_loose", "kern_figures")
WINDOW, PANEL = "window", "panel"
_SNAP = 24              # ближе этого к краю — окно прилипает и становится панелью
_PANEL_WIDTH = 400


class Window:
    def __init__(self, source):
        from PythonQt import QtCore, QtGui
        self.QtCore, self.QtGui = QtCore, QtGui
        self.source = source
        self.settings = QtCore.QSettings("Autokerner", "Autokerner")
        self.options = Options.from_json(self._setting("options", ""))
        self.busy = False
        self.stop = False
        self.filling = False
        self.stale = False
        self.applied = False
        self.result = None
        self.rejected_glyphs = set()
        self.calc_rejected = set()
        self.rejected_pairs = set()
        self.snapshots = []
        self._top_pairs = {}
        self._after_masters = {}
        self._banner = None
        # формат и места окна: широкое окно или узкая панель у края
        # (`self.mode` — другое: как пишется кернинг)
        self.form = WINDOW
        self._panel_width = self._int_setting("panel_width", _PANEL_WIDTH)
        self._window_geo = None
        self._ignore_until = 0.0
        self._last = self._settled_geo = None
        self._pending = False
        self._stable = 0
        self._build()
        self._fill(self.options)
        self._update_selection()
        self.summary.setHtml(t("empty"))
        self._status(t("ready"))
        self._update_buttons()
        # число выделенных в окне шрифта — живое, пока окно открыто
        self.timer = QtCore.QTimer()
        self.timer.setInterval(1500)
        self.timer.connect("timeout()", self._tick)
        self.timer.start()
        # прилипание к краям: следить, куда окно перетащили
        self.geo_timer = QtCore.QTimer()
        self.geo_timer.setInterval(250)
        self.geo_timer.connect("timeout()", self._watch)
        self.geo_timer.start()

    # ── настройки между запусками ──

    def _setting(self, ключ, иначе):
        try:
            v = self.settings.value(ключ)
        except Exception:
            v = None
        return иначе if v is None or v == "" else v

    def _int_setting(self, ключ, иначе):
        try:
            return int(self._setting(ключ, иначе))
        except (TypeError, ValueError):
            return иначе

    def _save_settings(self, o=None):
        try:
            self.settings.setValue("options", (o or self._read_options()).to_json())
            self.settings.setValue("text", self.preview_text.text)
            self.settings.setValue("mode", self.form)
            self.settings.setValue("panel_width", str(self._panel_width))
            if self.form == WINDOW:
                self._window_geo = self._frame()
            if self._window_geo:
                self.settings.setValue("window_geo", ",".join(str(int(v)) for v in self._window_geo))
            self.settings.sync()
        except Exception:
            pass

    # ── сборка окна ──

    def _build(self):
        QtCore, QtGui = self.QtCore, self.QtGui
        окно = self.window = QtGui.QDialog()
        окно.setWindowTitle("%s %s — %s" % (t("title"), __version__, self.source.name))
        # плавает над окнами FontLab, как его панели: щелчок в окне шрифта
        # (выделить знаки) не прячет его под главное окно
        окно.setWindowFlags(окно.windowFlags() | QtCore.Qt.Tool)
        окно.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        try:
            экран = QtGui.QApplication.desktop().availableGeometry(окно)
            окно.resize(min(1180, int(экран.width() * 0.85)), min(820, int(экран.height() * 0.85)))
        except Exception:
            окно.resize(1100, 760)
        главный = QtGui.QVBoxLayout(окно)

        # шапка: шрифт крупно, под ним — сколько мастеров и знаков; справа —
        # формат: широкое окно или узкая панель у края
        знаков = len(list(self.source.font.glyphs))
        ряд = QtGui.QHBoxLayout()
        шапка = QtGui.QLabel("<span style='font-size:16pt; font-weight:600'>%s</span><br>"
                             "<span style='color:gray'>%s · %s</span>" % (
                                 _e(self.source.name), _e(t("masters_n") % len(self.source.master_names)),
                                 _e(t("glyphs_n") % знаков)))
        ряд.addWidget(шапка, 1)
        # формат — значком без подписи (подпись — во всплывающей подсказке)
        self.btn_mode = self._button("", self._toggle_mode)
        self.btn_mode.setIconSize(QtCore.QSize(16, 16))
        ряд.addWidget(self.btn_mode, 0, QtCore.Qt.AlignTop)
        главный.addLayout(ряд)

        self.main_split = QtGui.QSplitter(QtCore.Qt.Horizontal)
        self.settings_area = self._build_settings()
        self.main_split.addWidget(self.settings_area)
        self.main_split.addWidget(self._build_results())
        self.main_split.setStretchFactor(0, 0)
        self.main_split.setStretchFactor(1, 1)
        self.main_split.setSizes([380, 800])
        главный.addWidget(self.main_split, 1)

        # ход и кнопки
        self.status = QtGui.QLabel("")
        self.status.setWordWrap(True)
        # всегда HTML: строки хода экранированы (_e), иначе в простом тексте
        # видно «&#x27;» вместо апострофа
        self.status.setTextFormat(QtCore.Qt.RichText)
        главный.addWidget(self.status)
        self.bar = QtGui.QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setMaximumHeight(8)
        self.bar.setTextVisible(False)
        self.bar.hide()
        главный.addWidget(self.bar)
        self.button_grid = QtGui.QGridLayout()
        self.btn_save = self._button(t("save"), self._save)
        self.btn_revert = self._button(t("revert"), self._revert)
        self.btn_stop = self._button(t("stop"), self._stop_clicked)
        self.btn_calc = self._button(t("calc"), self._calculate)
        self.btn_apply = self._button(t("apply"), self._apply)
        self.btn_close = self._button(t("close"), lambda *_: окно.close())
        self.btn_stop.hide()
        главный.addLayout(self.button_grid)

        # самое тихое — внизу: связь с автором и какая это версия
        низ = QtGui.QHBoxLayout()
        низ.setSpacing(2)
        низ.addWidget(self._link(self._icon("globe"), "", self._open_site,
                                 t("site_tip") % SITE_URL.split("//")[-1]))
        низ.addWidget(self._link(self._icon("mail"), t("report_bug"), self._copy_email,
                                 t("report_bug_tip") % EMAIL))
        низ.addStretch(1)
        низ.addWidget(self._note(t("free")))
        низ.addWidget(self._link(None, t("support"), self._open_support, t("support_tip")))
        главный.addLayout(низ)
        self._narrow = None
        self._relayout(False)
        окно.connect("finished(int)", self._closed)

    def _button(self, текст, действие):
        кнопка = self.QtGui.QPushButton(текст)
        кнопка.setAutoDefault(False)
        кнопка.setDefault(False)
        кнопка.clicked.connect(lambda *_: действие())
        return кнопка

    def _link(self, значок, текст, действие, подсказка=None):
        """Тихая кнопка-ссылка: серый мелкий текст, значок, рука-указатель"""
        QtCore, QtGui = self.QtCore, self.QtGui
        кнопка = QtGui.QPushButton(текст)
        кнопка.setFlat(True)
        кнопка.setAutoDefault(False)
        кнопка.setDefault(False)
        кнопка.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        кнопка.setStyleSheet("QPushButton { color: gray; font-size: 11px; border: none; padding: 2px 4px; "
                             "text-align: left; } QPushButton:hover { color: palette(link); }")
        if значок is not None:
            кнопка.setIcon(значок)
            кнопка.setIconSize(QtCore.QSize(14, 14))
        if подсказка:
            кнопка.setToolTip(подсказка)
        кнопка.clicked.connect(lambda *_: действие())
        return кнопка

    def _icon(self, вид):
        """Значок, нарисованный здесь же (без файлов): конверт, земной шар, панель или окно"""
        QtCore, QtGui = self.QtCore, self.QtGui
        картинка = QtGui.QPixmap(28, 28)
        картинка.fill(QtGui.QColor(0, 0, 0, 0))
        кисть = QtGui.QPainter(картинка)
        кисть.setRenderHint(QtGui.QPainter.Antialiasing)
        перо = QtGui.QPen(QtGui.QColor(140, 140, 140))
        перо.setWidthF(2.2)
        кисть.setPen(перо)
        if вид == "mail":
            кисть.drawRoundedRect(QtCore.QRectF(3, 6, 22, 16), 2.5, 2.5)
            кисть.drawLine(QtCore.QPointF(4, 8), QtCore.QPointF(14, 15.5))
            кисть.drawLine(QtCore.QPointF(14, 15.5), QtCore.QPointF(24, 8))
        elif вид == "panel":
            # окно с узкой колонкой справа — «сделать панелью»
            кисть.drawRoundedRect(QtCore.QRectF(3, 5, 22, 18), 2.5, 2.5)
            кисть.fillRect(QtCore.QRectF(17, 5, 8, 18), QtGui.QColor(140, 140, 140))
        elif вид == "window":
            # широкое окно с шапкой — «сделать окном»
            кисть.drawRoundedRect(QtCore.QRectF(3, 5, 22, 18), 2.5, 2.5)
            кисть.drawLine(QtCore.QPointF(3, 10), QtCore.QPointF(25, 10))
        else:
            кисть.drawEllipse(QtCore.QRectF(3.5, 3.5, 21, 21))
            кисть.drawEllipse(QtCore.QRectF(9.5, 3.5, 9, 21))
            кисть.drawLine(QtCore.QPointF(4, 14), QtCore.QPointF(24, 14))
            кисть.drawLine(QtCore.QPointF(6, 9), QtCore.QPointF(22, 9))
            кисть.drawLine(QtCore.QPointF(6, 19), QtCore.QPointF(22, 19))
        кисть.end()
        return QtGui.QIcon(картинка)

    def _copy_email(self):
        QtGui = self.QtGui
        QtGui.QApplication.clipboard().setText(EMAIL)
        окно = QtGui.QMessageBox(self.window)
        окно.setWindowTitle(t("report_bug"))
        окно.setText(t("email_copied") % EMAIL)
        окно.exec_()

    def _open_url(self, адрес):
        self.QtGui.QDesktopServices.openUrl(self.QtCore.QUrl(адрес))

    def _open_site(self):
        self._open_url(SITE_URL)

    def _open_support(self):
        self._open_url(support_url())

    def _note(self, текст):
        """Серая мелкая подпись в одну строку (для нижней строки окна)"""
        метка = self.QtGui.QLabel(текст)
        метка.setStyleSheet("color: gray; font-size: 11px;")
        return метка

    def _hint(self, текст):
        метка = self.QtGui.QLabel(текст)
        метка.setWordWrap(True)
        метка.setStyleSheet("color: gray; font-size: 11px;")
        return метка

    def _check(self, текст, подсказка=None):
        галка = self.QtGui.QCheckBox(текст)
        if подсказка:
            галка.setToolTip(подсказка)
        галка.connect("toggled(bool)", self._changed)
        return галка

    def _radio(self, текст, подсказка=None):
        кнопка = self.QtGui.QRadioButton(текст)
        if подсказка:
            кнопка.setToolTip(подсказка)
        кнопка.connect("toggled(bool)", self._changed)
        return кнопка

    def _spin(self, lo, hi, суффикс, подсказка, особое=None):
        поле = self.QtGui.QSpinBox()
        поле.setRange(lo, hi)
        поле.setSuffix(суффикс)
        поле.setToolTip(подсказка)
        if особое:
            поле.setSpecialValueText(особое)
        поле.connect("valueChanged(int)", self._changed)
        return поле

    def _combo(self, подписи, подсказка):
        список = self.QtGui.QComboBox()
        список.addItems(подписи)
        список.setToolTip(подсказка)
        список.connect("currentIndexChanged(int)", self._changed)
        return список

    def _build_settings(self):
        QtCore, QtGui = self.QtCore, self.QtGui
        лист = QtGui.QWidget()
        столбец = QtGui.QVBoxLayout(лист)

        # 1. что сделать — главное решение
        блок = QtGui.QGroupBox(t("sec_what"))
        с = QtGui.QVBoxLayout(блок)
        self.cb_spacing = self._check(t("do_spacing"), t("do_spacing_tip"))
        self.cb_space = self._check(t("do_space"), t("do_space_tip"))
        self.cb_kerning = self._check(t("do_kerning"), t("do_kerning_tip"))
        for галка in (self.cb_spacing, self.cb_space, self.cb_kerning):
            с.addWidget(галка)
        self.mode_box = QtGui.QWidget()
        р = QtGui.QVBoxLayout(self.mode_box)
        р.setContentsMargins(22, 2, 0, 0)
        р.addWidget(QtGui.QLabel(t("mode_label")))
        self.rb_replace = self._radio(t("mode_replace"))
        self.rb_merge = self._radio(t("mode_merge"))
        р.addWidget(self.rb_replace)
        р.addWidget(self.rb_merge)
        self.mode_note = self._hint(t("mode_merge_note"))
        # высота — под длинную подсказку: при смене режима блоки ниже не прыгают
        self.mode_note.setMinimumHeight(self.mode_note.sizeHint.height() + 4)
        self.mode_note.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        р.addWidget(self.mode_note)
        с.addWidget(self.mode_box)
        столбец.addWidget(блок)

        # 2. какие знаки
        блок = QtGui.QGroupBox(t("sec_where"))
        с = QtGui.QVBoxLayout(блок)
        self.rb_all = self._radio(t("glyphs_all"))
        self.rb_sel = self._radio(t("glyphs_sel"), t("glyphs_sel_tip"))
        с.addWidget(self.rb_all)
        с.addWidget(self.rb_sel)
        self.cb_formula = self._check(t("keep_formula"), t("keep_formula_tip"))
        self.cb_marked = self._check(t("keep_marked"), t("keep_marked_tip"))
        self.cb_nbsp = self._check(t("nbsp"), t("nbsp_tip"))
        for галка in (self.cb_formula, self.cb_marked, self.cb_nbsp):
            с.addWidget(галка)
        столбец.addWidget(блок)

        # 3. мастера — только если их больше одного; флажки в две колонки
        # (щелчок по имени тоже ставит флажок, в отличие от списка)
        self.master_checks = []
        if len(self.source.master_names) > 1:
            блок = QtGui.QGroupBox(t("sec_masters"))
            сетка = QtGui.QGridLayout(блок)
            половина = (len(self.source.master_names) + 1) // 2
            for n, имя in enumerate(self.source.master_names):
                галка = self._check(имя)
                сетка.addWidget(галка, n % половина, n // половина)
                self.master_checks.append(галка)
            столбец.addWidget(блок)

        # 4. правило: набор сверху, тонкая настройка свёрнута
        блок = QtGui.QGroupBox(t("sec_rule"))
        с = QtGui.QVBoxLayout(блок)
        ряд = QtGui.QHBoxLayout()
        ряд.addWidget(QtGui.QLabel(t("preset")))
        self.preset = QtGui.QComboBox()
        self.preset.addItems([preset_title(к) for к in _PRESET_KEYS[:-1]] + [t("custom")])
        self.preset.connect("currentIndexChanged(int)", self._preset_chosen)
        ряд.addWidget(self.preset, 1)
        с.addLayout(ряд)
        self.preset_note = self._hint("")
        с.addWidget(self.preset_note)
        self.fine_button = QtGui.QPushButton("▸ " + t("fine"))
        self.fine_button.setFlat(True)
        self.fine_button.setAutoDefault(False)
        self.fine_button.setStyleSheet("text-align: left; font-weight: 600;")
        self.fine_button.clicked.connect(lambda *_: self._toggle_fine())
        с.addWidget(self.fine_button)
        self.fine = QtGui.QWidget()
        тонко = QtGui.QVBoxLayout(self.fine)
        тонко.setContentsMargins(8, 0, 0, 0)
        тонко.addWidget(self._subtitle(t("sub_spacing")))
        ф = QtGui.QFormLayout()
        self.sp_looseness = self._spin(-30, 30, " %", t("looseness_tip"))
        self.sp_threshold = self._spin(2, 60, t("per_mille"), t("threshold_tip"))
        self.sp_word_gap = self._spin(25, 80, " %", t("word_gap_tip"))
        self.co_space_fit = self._combo(t("space_fit_items").split("|"), t("space_fit_tip"))
        self.sp_side_h = self._spin(0, 300, t("per_mille"), t("side_h_tip"), t("auto"))
        self.cb_from_zero = self._check(t("from_zero_on"), t("from_zero_on_tip"))
        ф.addRow(t("looseness"), self.sp_looseness)
        ф.addRow(t("threshold"), self.sp_threshold)
        ф.addRow(t("word_gap"), self.sp_word_gap)
        ф.addRow(t("space_fit"), self.co_space_fit)
        ф.addRow(t("side_h"), self.sp_side_h)
        тонко.addLayout(ф)
        тонко.addWidget(self.cb_from_zero)
        тонко.addWidget(self._subtitle(t("sub_kerning")))
        ф = QtGui.QFormLayout()
        self.sp_strength = self._spin(30, 200, " %", t("strength_tip"))
        self.sp_kthreshold = self._spin(1, 40, t("per_mille"), t("kthreshold_tip"))
        self.sp_clearance = self._spin(0, 80, t("per_mille"), t("clearance_tip"))
        self.co_precision = self._combo(["%d%s" % (x, t("per_mille")) for x in _PRECISION], t("precision_tip"))
        self.co_limit = self._combo([_n(x) if x else t("no_limit") for x in _LIMITS], t("limit_tip"))
        self.co_round = self._combo(["%d" % x for x in _ROUNDS], t("round_tip"))
        self.co_figures = self._combo(t("figures_items").split("|"), t("figures_tip"))
        self.sp_max_tight = self._spin(0, 400, t("per_mille"), t("max_tight_tip"), t("no_limit"))
        self.sp_max_loose = self._spin(0, 400, t("per_mille"), t("max_loose_tip"), t("no_limit"))
        ф.addRow(t("strength"), self.sp_strength)
        ф.addRow(t("kthreshold"), self.sp_kthreshold)
        ф.addRow(t("clearance"), self.sp_clearance)
        ф.addRow(t("figures"), self.co_figures)
        ф.addRow(t("precision"), self.co_precision)
        ф.addRow(t("limit"), self.co_limit)
        ф.addRow(t("round"), self.co_round)
        ф.addRow(t("max_tight"), self.sp_max_tight)
        ф.addRow(t("max_loose"), self.sp_max_loose)
        тонко.addLayout(ф)
        сброс = self._button(t("reset"), self._reset)
        тонко.addWidget(сброс)
        с.addWidget(self.fine)
        self.fine.hide()
        столбец.addWidget(блок)
        столбец.addStretch(1)

        прокрутка = QtGui.QScrollArea()
        прокрутка.setWidget(лист)
        прокрутка.setWidgetResizable(True)
        прокрутка.setMinimumWidth(350)
        return прокрутка

    def _subtitle(self, текст):
        метка = self.QtGui.QLabel(текст)
        метка.setStyleSheet("font-weight: 600; margin-top: 6px;")
        return метка

    def _build_results(self):
        QtCore, QtGui = self.QtCore, self.QtGui
        self.tabs = QtGui.QTabWidget()

        # итог
        self.summary = QtGui.QTextBrowser()
        self.summary.setOpenExternalLinks(True)
        self.tabs.addTab(self.summary, t("tab_summary"))

        # живая строка
        лист = self.page_preview = QtGui.QWidget()
        с = QtGui.QVBoxLayout(лист)
        self.preview_grid = QtGui.QGridLayout()
        self.preview_text = QtGui.QLineEdit(self._setting("text", DEFAULT_TEXT))
        self.preview_text.connect("textChanged(QString)", lambda *_: self._draw_preview())
        self.preview_master = QtGui.QComboBox()
        self.preview_master.hide()
        self.preview_master.connect("currentIndexChanged(int)", lambda *_: self._draw_preview())
        self.preview_size = QtGui.QSpinBox()
        self.preview_size.setRange(16, 200)
        self.preview_size.setValue(48)
        self.preview_size.setSuffix(" px")
        self.preview_size.connect("valueChanged(int)", lambda *_: self._draw_preview())
        self.preview_kern = QtGui.QCheckBox(t("preview_kern"))
        self.preview_kern.setChecked(True)
        self.preview_kern.connect("toggled(bool)", lambda *_: self._draw_preview())
        с.addLayout(self.preview_grid)
        self.preview_area = QtGui.QScrollArea()
        self.preview_label = QtGui.QLabel(t("preview_empty"))
        self.preview_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        self.preview_label.setMargin(12)
        self.preview_area.setWidget(self.preview_label)
        self.preview_area.setWidgetResizable(True)
        с.addWidget(self.preview_area, 1)
        с.addWidget(self._hint(t("preview_hint")))
        self.tabs.addTab(лист, t("tab_preview"))

        # правки
        лист = self.page_edits = QtGui.QWidget()
        с = QtGui.QVBoxLayout(лист)
        ряд = QtGui.QHBoxLayout()
        self.search = QtGui.QLineEdit()
        self.search.setPlaceholderText(t("search"))
        self.search.connect("textChanged(QString)", lambda *_: self._fill_edits())
        ряд.addWidget(self.search, 1)
        self.edits_master = QtGui.QComboBox()
        self.edits_master.hide()
        self.edits_master.connect("currentIndexChanged(int)", lambda *_: self._fill_edits())
        ряд.addWidget(self.edits_master)
        с.addLayout(ряд)
        делитель = self.edits_split = QtGui.QSplitter(QtCore.Qt.Horizontal)
        левая = QtGui.QWidget()
        л = QtGui.QVBoxLayout(левая)
        л.setContentsMargins(0, 0, 0, 0)
        self.glyphs_title = self._subtitle("")
        л.addWidget(self.glyphs_title)
        self.glyphs_table = self._table([" ", t("glyph"), t("lsb"), t("rsb"), t("width")])
        self.glyphs_table.connect("itemChanged(QTableWidgetItem*)", self._glyph_ticked)
        л.addWidget(self.glyphs_table)
        правая = QtGui.QWidget()
        п = QtGui.QVBoxLayout(правая)
        п.setContentsMargins(0, 0, 0, 0)
        self.pairs_title = self._subtitle("")
        п.addWidget(self.pairs_title)
        self.pairs_table = self._table([" ", t("pair"), t("now"), t("after")])
        self.pairs_table.connect("itemChanged(QTableWidgetItem*)", self._pair_ticked)
        п.addWidget(self.pairs_table)
        делитель.addWidget(левая)
        делитель.addWidget(правая)
        делитель.setSizes([400, 400])
        с.addWidget(делитель, 1)
        с.addWidget(self._hint(t("edits_hint")))
        self.tabs.addTab(лист, t("tab_edits"))
        self.tabs.connect("currentChanged(int)", lambda *_: self._tab_shown())
        self._glyph_rows = []
        self._pair_rows = []
        return self.tabs

    def _table(self, заголовки):
        QtGui = self.QtGui
        таблица = QtGui.QTableWidget()
        таблица.setColumnCount(len(заголовки))
        таблица.setHorizontalHeaderLabels(заголовки)
        таблица.verticalHeader().hide()
        таблица.setEditTriggers(QtGui.QAbstractItemView.NoEditTriggers)
        таблица.setSelectionMode(QtGui.QAbstractItemView.NoSelection)
        таблица.horizontalHeader().setStretchLastSection(True)
        return таблица

    # ── настройки ⇄ окно ──

    def _fill(self, o):
        self.filling = True
        try:
            self.cb_spacing.setChecked(bool(o.spacing))
            self.cb_space.setChecked(bool(o.space))
            self.cb_kerning.setChecked(bool(o.kerning))
            self.rb_merge.setChecked(o.kern_mode == MERGE)
            self.rb_replace.setChecked(o.kern_mode != MERGE)
            self.rb_sel.setChecked(o.glyphs == SELECTED)
            self.rb_all.setChecked(o.glyphs != SELECTED)
            self.cb_formula.setChecked(bool(o.keep_metric_keys))
            self.cb_marked.setChecked(bool(o.keep_marked))
            self.cb_nbsp.setChecked(bool(o.nbsp_follows_space))
            выбраны = set(o.masters or []) & set(self.source.master_names)
            for галка, имя in zip(self.master_checks, self.source.master_names):
                галка.setChecked(not выбраны or имя in выбраны)
            self.sp_looseness.setValue(int(o.looseness))
            self.sp_threshold.setValue(int(o.spacing_threshold))
            self.sp_word_gap.setValue(int(o.word_gap))
            self.co_space_fit.setCurrentIndex(0 if o.space_edge else 1)
            self.sp_side_h.setValue(int(o.spacing_side_h or 0))
            self.cb_from_zero.setChecked(bool(o.spacing_from_zero))
            self.sp_strength.setValue(int(o.kern_strength))
            self.sp_kthreshold.setValue(int(o.kern_threshold))
            self.sp_clearance.setValue(int(o.kern_clearance))
            self.co_precision.setCurrentIndex(self._index(_PRECISION, o.kern_precision, 1))
            self.co_limit.setCurrentIndex(self._index(_LIMITS, o.kern_limit, 1))
            self.co_round.setCurrentIndex(self._index(_ROUNDS, o.kern_round, 0))
            self.sp_max_tight.setValue(int(o.kern_max_tight))
            self.sp_max_loose.setValue(int(o.kern_max_loose))
            self.co_figures.setCurrentIndex(self._index(list(FIGURES), o.kern_figures, 0))
            self.preset.setCurrentIndex(_PRESET_KEYS.index(self._preset_of(o)))
        finally:
            self.filling = False
        self._sync_enabled()

    @staticmethod
    def _index(значения, значение, иначе):
        return значения.index(значение) if значение in значения else иначе

    def _read_options(self):
        o = Options()
        o.spacing = self.cb_spacing.isChecked()
        o.space = self.cb_space.isChecked()
        o.kerning = self.cb_kerning.isChecked()
        o.kern_mode = MERGE if self.rb_merge.isChecked() else REPLACE
        o.glyphs = SELECTED if self.rb_sel.isChecked() else ALL
        o.keep_metric_keys = self.cb_formula.isChecked()
        o.keep_marked = self.cb_marked.isChecked()
        o.nbsp_follows_space = self.cb_nbsp.isChecked()
        выбраны = [имя for галка, имя in zip(self.master_checks, self.source.master_names)
                   if галка.isChecked()]
        o.masters = None if not self.master_checks or len(выбраны) == len(self.source.master_names) \
            else выбраны
        o.looseness = self.sp_looseness.value
        o.spacing_threshold = self.sp_threshold.value
        o.word_gap = self.sp_word_gap.value
        o.space_edge = self.co_space_fit.currentIndex != 1
        o.spacing_side_h = self.sp_side_h.value
        o.spacing_from_zero = self.cb_from_zero.isChecked()
        o.kern_strength = self.sp_strength.value
        o.kern_threshold = self.sp_kthreshold.value
        o.kern_clearance = self.sp_clearance.value
        o.kern_precision = _PRECISION[max(0, self.co_precision.currentIndex)]
        o.kern_limit = _LIMITS[max(0, self.co_limit.currentIndex)]
        o.kern_round = _ROUNDS[max(0, self.co_round.currentIndex)]
        o.kern_max_tight = self.sp_max_tight.value
        o.kern_max_loose = self.sp_max_loose.value
        o.kern_figures = FIGURES[max(0, self.co_figures.currentIndex)]
        return o

    @staticmethod
    def _preset_of(o):
        for ключ in PRESETS:
            if all(getattr(preset(ключ, o), поле) == getattr(o, поле) for поле in _RULE_FIELDS):
                return ключ
        return "custom"

    def _sync_enabled(self):
        """Зависимые настройки гаснут вместе со своим главным пунктом;
        подсказки под режимом и набором — по выбранному"""
        апроши, пробел, кернинг = (self.cb_spacing.isChecked(), self.cb_space.isChecked(),
                                   self.cb_kerning.isChecked())
        self.mode_box.setEnabled(кернинг)
        self.mode_note.setText(t("mode_merge_note") if self.rb_merge.isChecked() else t("mode_replace_note"))
        self.cb_nbsp.setEnabled(пробел)
        for поле in (self.sp_looseness, self.sp_threshold, self.sp_side_h, self.cb_from_zero):
            поле.setEnabled(апроши)
        self.sp_word_gap.setEnabled(пробел)
        self.co_space_fit.setEnabled(пробел)
        for поле in (self.sp_strength, self.sp_kthreshold, self.sp_clearance, self.co_figures,
                     self.co_precision, self.co_limit, self.co_round, self.sp_max_tight, self.sp_max_loose):
            поле.setEnabled(кернинг)
        ключ = _PRESET_KEYS[max(0, self.preset.currentIndex)]
        self.preset_note.setText(preset_note(ключ) if ключ in PRESET_NOTES else t("custom_note"))

    def _changed(self, *_):
        if self.filling:
            return
        self.filling = True
        try:
            self.preset.setCurrentIndex(_PRESET_KEYS.index(self._preset_of(self._read_options())))
        finally:
            self.filling = False
        self._sync_enabled()
        if self.rb_sel.isChecked():
            self._update_selection()
        self._mark_stale()

    def _preset_chosen(self, *_):
        if self.filling:
            return
        ключ = _PRESET_KEYS[max(0, self.preset.currentIndex)]
        if ключ != "custom":
            self._fill(preset(ключ, self._read_options()))
        self._sync_enabled()
        self._mark_stale()

    def _reset(self):
        self._fill(Options())
        self._mark_stale()

    def _toggle_fine(self):
        видно = not self.fine.isVisible()
        self.fine.setVisible(видно)
        self.fine_button.setText(("▾ " if видно else "▸ ") + t("fine"))

    def _update_selection(self):
        выбраны = self.source.selected_names()
        self.rb_sel.setText(t("glyphs_sel_n") % len(выбраны) if выбраны is not None else t("glyphs_sel"))

    def _tick(self):
        """Раз в полторы секунды: число выделенных знаков и перенос строки
        под новую ширину окна"""
        if not self.busy and self.window.isVisible():
            try:
                self._update_selection()
                if self._on(self.page_preview) and self.result is not None and \
                        self.preview_area.viewport().width != getattr(self, "_preview_width", None):
                    self._draw_preview()
            except Exception:
                self.timer.stop()

    def _mark_stale(self):
        if self.result is not None and not self.applied and not self.stale:
            self.stale = True
            self._status(t("stale"))
        self._update_buttons()

    # ── окно и панель ──

    def _relayout(self, narrow):
        """Раскладка под формат. В окне — настройки слева, итог справа,
        кнопки в ряд; в узкой панели — всё одним столбцом: настройки
        первой вкладкой, таблицы правок одна под другой, кнопки в два ряда"""
        QtCore = self.QtCore
        if narrow == self._narrow:
            return
        self._narrow = narrow
        if narrow:
            self.tabs.insertTab(0, self.settings_area, t("tab_settings"))
            if self.result is None:
                self.tabs.setCurrentIndex(0)
            self.edits_split.setOrientation(QtCore.Qt.Vertical)
        else:
            i = self.tabs.indexOf(self.settings_area)
            if i >= 0:
                self.tabs.removeTab(i)
            self.main_split.insertWidget(0, self.settings_area)
            self.settings_area.show()
            self.main_split.setSizes([380, 800])
            self.edits_split.setOrientation(QtCore.Qt.Horizontal)
        self._grid(self.preview_grid, [
            (self.preview_text, 0, 0, 1, 4), (self.preview_size, 1, 0, 1, 1),
            (self.preview_kern, 1, 1, 1, 1), (self.preview_master, 1, 2, 1, 1)] if narrow else [
            (self.preview_text, 0, 0, 1, 1), (self.preview_master, 0, 1, 1, 1),
            (self.preview_size, 0, 2, 1, 1), (self.preview_kern, 0, 3, 1, 1)],
            [3] if narrow else [0])
        # кнопка следующего шага — рядом с «Стоп»; в панели «Закрыть» не нужна:
        # у панели крестик в шапке
        self._grid(self.button_grid, [
            (self.btn_stop, 0, 0, 1, 1), (self.btn_calc, 0, 1, 1, 1), (self.btn_apply, 0, 2, 1, 1),
            (self.btn_save, 1, 1, 1, 1), (self.btn_revert, 1, 2, 1, 1)] if narrow else [
            (self.btn_save, 0, 0, 1, 1), (self.btn_revert, 0, 1, 1, 1), (self.btn_stop, 0, 3, 1, 1),
            (self.btn_calc, 0, 4, 1, 1), (self.btn_apply, 0, 5, 1, 1), (self.btn_close, 0, 6, 1, 1)],
            [1, 2] if narrow else [2])
        self.btn_close.setVisible(not narrow)
        self.btn_mode.setIcon(self._icon("window" if narrow else "panel"))
        self.btn_mode.setAccessibleName(t("to_window") if narrow else t("to_panel"))
        self.btn_mode.setToolTip(t("to_window_tip") if narrow else t("to_panel_tip"))
        if self.result is not None and getattr(self, "report", None) is not None:
            self._show_summary(self._banner)
        self._tab_shown()

    @staticmethod
    def _grid(сетка, места, растянуть):
        for виджет, *_ in места:
            сетка.removeWidget(виджет)
        for c in range(8):
            сетка.setColumnStretch(c, 0)
        for виджет, r, c, rs, cs in места:
            сетка.addWidget(виджет, r, c, rs, cs)
        for c in растянуть:
            сетка.setColumnStretch(c, 1)

    def _frame(self):
        g = self.window.frameGeometry
        return (g.x(), g.y(), g.width(), g.height())

    def _title_height(self):
        return max(0, self.window.frameGeometry.height() - self.window.geometry.height())

    def _edges(self):
        """Края, к которым прилипает панель: (x, сторона, верх, высота).
        Сторона «left» — панель встаёт справа от края, «right» — слева.
        Края экрана, окон шрифта и колонок панелей FontLab"""
        QtGui = self.QtGui
        края = []
        try:
            э = QtGui.QApplication.desktop().availableGeometry(self.window)
            края += [(э.x(), "left", э.y(), э.height()), (э.x() + э.width(), "right", э.y(), э.height())]
        except Exception:
            pass
        for w in QtGui.QApplication.topLevelWidgets():
            try:
                if not w.isVisible() or type(w).__name__ not in ("YFrameWindow", "YDock", "ToolbarPanel"):
                    continue
                g = w.frameGeometry
                края += [(g.x() + g.width(), "left", g.y(), g.height()), (g.x(), "right", g.y(), g.height())]
            except Exception:
                continue
        return [к for к in края if к[3] >= 300]

    def _snap_target(self, x, y, w, h):
        лучший = None
        for край, сторона, верх, высота in self._edges():
            if min(y + h, верх + высота) - max(y, верх) < min(h, высота) / 2:
                continue
            d = abs(x - край) if сторона == "left" else abs(x + w - край)
            if d <= _SNAP and (лучший is None or d < лучший[0]):
                лучший = (d, край, сторона, верх, высота)
        return лучший[1:] if лучший else None

    def _default_dock(self):
        """Куда встаёт панель по кнопке: слева от правой колонки панелей
        FontLab, иначе у правого края окна шрифта, иначе у края экрана"""
        QtGui = self.QtGui
        колонки, окна = [], []
        for w in QtGui.QApplication.topLevelWidgets():
            try:
                if not w.isVisible():
                    continue
                g = w.frameGeometry
                if type(w).__name__ == "YDock" and g.height() >= 300:
                    колонки.append((g.x(), "right", g.y(), g.height()))
                elif type(w).__name__ == "YFrameWindow":
                    окна.append((g.width() * g.height(), (g.x() + g.width(), "right", g.y(), g.height())))
            except Exception:
                continue
        if колонки:
            return max(колонки)
        if окна:
            return max(окна)[1]
        края = [к for к in self._edges() if к[1] == "right"]
        return края[0] if края else None

    def _place(self, x, y, w, высота):
        """Поставить окно: рамка — от (x, y), высота — вся, с шапкой.
        Раскладка пересчитывается сперва: иначе Qt держит минимум прежней
        (у широкого окна он больше, и панель выходила шире)"""
        self._ignore_until = time.time() + 0.8
        try:
            self.window.layout().activate()
        except Exception:
            pass
        self.window.resize(int(w), int(max(300, высота - self._title_height())))
        self.window.move(int(x), int(y))

    def _dock(self, цель):
        if цель is None:
            return
        край, сторона, верх, высота = цель
        w = self._panel_width
        self._place(край if сторона == "left" else край - w, верх, w, высота)

    def _set_mode(self, mode, цель=None, с_места=False):
        """Сменить формат. Панель встаёт к `цели` (по умолчанию — у правой
        колонки FontLab); окно — на прежнее место или, если его оттащили
        от края, туда, где отпустили"""
        if mode == PANEL and self.form == WINDOW:
            self._window_geo = self._frame()
        x, y = self._frame()[:2]
        self.form = mode
        self._relayout(mode == PANEL)
        if mode == PANEL:
            self._dock(цель or self._default_dock())
        else:
            geo = self._window_geo or (x, y, 1100, 760)
            if с_места:
                geo = (x, y, geo[2], geo[3])
            try:
                э = self.QtGui.QApplication.desktop().availableGeometry(self.window)
                w, h = min(geo[2], э.width()), min(geo[3], э.height())
                x = max(э.x(), min(geo[0], э.x() + э.width() - w))
                y = max(э.y(), min(geo[1], э.y() + э.height() - h))
                self._place(x, y, w, h)
            except Exception:
                self._place(geo[0], geo[1], geo[2], geo[3])
        self._save_settings()

    def _toggle_mode(self):
        if not self.busy:
            self._set_mode(WINDOW if self.form == PANEL else PANEL)

    def _watch(self):
        """Раз в четверть секунды: окно перетащили и отпустили? У края —
        прилипнуть панелью; панель оттащили от края — снова окно.
        Размер, изменённый руками, запоминается"""
        try:
            if self.busy or not self.window.isVisible():
                return
            сейчас = self._frame()
            if time.time() < self._ignore_until:
                self._last = self._settled_geo = сейчас
                return
            if сейчас != self._last:
                self._last, self._pending, self._stable = сейчас, True, 0
                return
            if not self._pending:
                return
            # отпустили — окно стоит три такта (¾ с). Кнопку мыши не спросить:
            # после перетаскивания за шапку Qt считает её нажатой до щелчка
            self._stable += 1
            if self._stable < 3:
                return
            self._pending = False
            прежний, self._settled_geo = self._settled_geo, сейчас
            if прежний is None:
                return
            if сейчас[2:] != прежний[2:]:
                if self.form == PANEL:
                    self._panel_width = сейчас[2]
                return
            цель = self._snap_target(*сейчас)
            if цель is not None:
                if self.form == WINDOW:
                    self._set_mode(PANEL, цель)
                else:
                    self._dock(цель)
            elif self.form == PANEL:
                self._set_mode(WINDOW, с_места=True)
        except Exception:
            self.geo_timer.stop()

    def restore_place(self):
        """После показа: прежний формат и место (если окно было — на экране).
        Формат читается первым: смена места его перезаписывает"""
        формат = self._setting("mode", WINDOW)
        try:
            g = [int(v) for v in str(self._setting("window_geo", "")).split(",")]
            if len(g) == 4:
                self._window_geo = tuple(g)
                self._set_mode(WINDOW, с_места=False)
        except (TypeError, ValueError):
            pass
        if формат == PANEL:
            self._set_mode(PANEL)

    # ── кнопки и ход ──

    def _status(self, текст):
        self.status.setText(текст)

    def _update_buttons(self):
        есть = self.result is not None
        свежий = есть and not self.stale and not self.applied and self.rejected_glyphs == self.calc_rejected
        self.btn_calc.setEnabled(not self.busy)
        self.btn_apply.setEnabled(not self.busy and свежий)
        # следующий шаг выделен: до расчёта — «Посчитать», после — «Применить»
        for кнопка, главная in ((self.btn_calc, not свежий), (self.btn_apply, свежий)):
            шрифт = кнопка.font
            шрифт.setBold(главная)
            кнопка.setFont(шрифт)
        self.btn_save.setEnabled(not self.busy and есть)
        self.btn_revert.setEnabled(not self.busy and bool(self.snapshots))
        self.btn_close.setEnabled(not self.busy)
        self.btn_mode.setEnabled(not self.busy)

    def _begin(self, текст, можно_стоп):
        self.busy = True
        self.stop = False
        self.bar.show()
        self.btn_stop.setVisible(можно_стоп)
        self.btn_stop.setEnabled(можно_стоп)
        self._status(текст)
        self._update_buttons()
        self.QtGui.QApplication.processEvents()

    def _end(self):
        self.busy = False
        self.bar.hide()
        self.btn_stop.hide()
        self._update_buttons()

    def _progress(self, текст):
        if self.stop:
            raise _Stop()
        self._status(_e(_tr(текст)))
        self.QtGui.QApplication.processEvents()

    def _quiet(self, текст):
        """Ход записи: без «Стоп» — запись нельзя бросить на полпути"""
        self._status(_e(_tr(текст)))
        self.QtGui.QApplication.processEvents()

    def _stop_clicked(self):
        self.stop = True

    def _closed(self, *_):
        self.stop = True
        self.timer.stop()
        self.geo_timer.stop()
        self._save_settings()

    def _error(self, ошибка):
        self._status("<b>%s:</b> %s" % (_e(t("error")), _e(_tr(ошибка))))
        traceback.print_exc()

    # ── расчёт ──

    def _calculate(self):
        if self.busy:
            return
        o = self._read_options()
        if not (o.spacing or o.space or o.kerning):
            return self._status(t("nothing"))
        names = [m for m in self.source.master_names if not o.masters or m in o.masters]
        if not names:
            return self._status(t("no_masters"))
        выбраны = None
        if o.glyphs == SELECTED:
            выбраны = self.source.selected_names()
            if выбраны is None:
                return self._status(t("sel_unknown"))
            if not выбраны:
                return self._status(t("sel_empty"))
            self.rb_sel.setText(t("glyphs_sel_n") % len(выбраны))
        self._save_settings(o)
        self._begin(t("progress"), True)
        try:
            начало = time.time()
            защищены = self.source.protected(o, names, выбраны)
            fixed = set(защищены) | self.rejected_glyphs
            мастера = self.source.read(progress=self._progress, masters=names)
            отпечаток = self.source.fingerprint(names)
            итог = run(мастера, options=o, fixed=fixed, progress=self._progress)
            self._progress(t("progress"))
            old = [OldKerning(*self.source.kerning_now(m)) for m in names]
            # кернинг знаков с меткой (и их диакритики) остаётся прежним
            свои = kept_glyphs(мастера[0], self.source.marked_names()) if o.keep_marked else set()
            if свои and итог.kern is not None:
                итог.kern = keep_pairs(итог.kern, свои, [g.name for g in мастера[0].glyphs], old)
            only = set(выбраны) if выбраны else None
            вид = write_mode(o, old, only) if итог.kern is not None else None
            writes = None
            if вид in (MISSING, SELECTED_PAIRS):
                self._progress(t("choosing_pairs"))
                writes = pair_writes(итог.kern, [g.name for g in мастера[0].glyphs],
                                     {g.name: bool(g.codes) for g in мастера[0].glyphs},
                                     old, вид, o.kern_limit or None, only)
            # итог готов — только теперь он заменяет прежний
            self.result, self.masters, self.names, self.old = итог, мастера, names, old
            self.calc_options, self.only, self.mode, self.writes = o, only, вид, writes
            self.fingerprint_ = отпечаток
            self.calc_rejected = set(self.rejected_glyphs)
            self.stale = self.applied = False
            self._top_pairs, self._after_masters = {}, {}
            причины = {}
            for причина in защищены.values():
                причины[причина] = причины.get(причина, 0) + 1
            причины["rejected"] = len(self.rejected_glyphs - set(защищены))
            self.info = {
                "spacing": o.spacing, "space": o.space, "mode": вид, "protected": причины,
                "kept": (len(свои), итог.kern.kept_pairs) if свои and итог.kern is not None else None,
                "writes": len(writes[0]) if writes else 0,
                "truncated": writes[1] if writes else (итог.kern.truncated if итог.kern else 0),
                "size": size_estimate(итог.kern, вид, writes[0] if writes else None) if итог.kern else 0,
                "kern_feature": итог.kern is not None and self.source.has_kern_feature(),
                "subset": (len(names), len(self.source.master_names))
                if len(names) < len(self.source.master_names) else None,
                "collisions": self._collisions(итог, мастера[0]),
                "from_zero": [(names[k], план.side_h, план.side_source, план.side_letters)
                              for k, план in enumerate(итог.plans or [])
                              if getattr(план, "from_zero", False) and k < len(names)],
            }
            self.report = build(мастера, итог, old, after=self._after)
            self._show_summary()
            for список in (self.preview_master, self.edits_master):
                список.blockSignals(True)
                список.clear()
                список.addItems(names)
                список.setVisible(len(names) > 1)
                список.blockSignals(False)
            self._status(t("done_calc") % (time.time() - начало))
            self._tab_shown(сброс=True)
        except _Stop:
            self._status(t("stopped_kept") if self.result is not None and not self.applied
                         else t("stopped"))
        except Exception as ошибка:
            self._error(ошибка)
        finally:
            self._end()

    @staticmethod
    def _collisions(итог, мастер):
        """Цифры, что сходятся через знак: (примеры «7,4», всего) или None"""
        if not итог.collisions:
            return None

        def символ(имя):
            i = мастер.by_name(имя)
            коды = мастер.glyphs[i].codes if i is not None else []
            return chr(коды[0]) if коды else "/" + имя

        примеры = []
        for л, р, п, _ in итог.collisions:
            текст = символ(л) + символ(р) + символ(п)
            if текст not in примеры:
                примеры.append(текст)
            if len(примеры) == 4:
                break
        return примеры, len(итог.collisions)

    def _show_summary(self, banner=None):
        self._banner = banner
        info = dict(self.info)
        info["banner"] = banner
        info["narrow"] = self._narrow
        self.summary_html = report_html(self.report, info)
        self.summary.setHtml(self.summary_html)

    def _after(self, w, rejected=True):
        """Число пары после записи на мастере w"""
        if self.result.kern is None:
            return self.old[w].value
        return kern_after(self.result.kern, self.old[w], w, self.mode, self.only,
                          self.rejected_pairs if rejected else (), self.writes[0] if self.writes else None)

    def _after_master(self, w):
        m = self._after_masters.get(w)
        if m is None:
            правки = spacing_after(self.result, w)
            мастер = self.masters[w]
            i = мастер.glyph(0x20)
            if w in self.result.space and i is not None:
                правки[мастер.name(i)] = (0, self.result.space[w])
            m = self._after_masters[w] = мастер.with_metrics(правки, round_points=False)
        return m

    # ── живая строка ──

    def _on(self, страница):
        return self.tabs.currentIndex == self.tabs.indexOf(страница)

    def _tab_shown(self, сброс=False):
        if сброс and self._on(self.settings_area):
            # в панели после расчёта — сразу к итогу
            self.tabs.setCurrentIndex(self.tabs.indexOf(self.summary))
        if self._on(self.page_preview):
            self._draw_preview()
        elif self._on(self.page_edits):
            self._fill_edits()
        if сброс and self._on(self.summary):
            self.summary.verticalScrollBar().setValue(0)

    def _path(self, path, glyph, x0, base, scale):
        QtCore = self.QtCore

        def P(p):
            return QtCore.QPointF(x0 + p[0] * scale, base - p[1] * scale)

        for контур in glyph.contours:
            for к in контур.commands:
                вид = к[0]
                if вид == "moveTo":
                    path.moveTo(P(к[1]))
                elif вид == "lineTo":
                    path.lineTo(P(к[1]))
                elif вид == "curveTo":
                    path.cubicTo(P(к[1]), P(к[2]), P(к[3]))
                elif вид == "qCurveTo":
                    вне, конец = к[1], к[2]
                    if конец is None:
                        # контур из одних внеконтурных точек: начало — середина последней и первой
                        конец = ((вне[-1][0] + вне[0][0]) / 2, (вне[-1][1] + вне[0][1]) / 2)
                        path.moveTo(P(конец))
                    for n, точка in enumerate(вне):
                        дальше = конец if n == len(вне) - 1 else (
                            (точка[0] + вне[n + 1][0]) / 2, (точка[1] + вне[n + 1][1]) / 2)
                        path.quadTo(P(точка), P(дальше))
                elif вид == "closePath":
                    path.closeSubpath()

    def _draw_preview(self):
        """Строка «сейчас / станет»: текст переносится по словам под ширину
        вкладки, и у каждого куска две строки — как сейчас и как станет,
        одна под другой, чтобы сравнивать глазами"""
        if not self._on(self.page_preview):
            return
        QtCore, QtGui = self.QtCore, self.QtGui
        if self.result is None:
            self.preview_label.setPixmap(QtGui.QPixmap())
            self.preview_label.setText(t("preview_empty"))
            return
        w = max(0, self.preview_master.currentIndex)
        до, после = self.masters[w], self._after_master(w)
        имена = parse_text(self.preview_text.text, до)
        с_кернингом = self.preview_kern.isChecked()
        строки = [(t("now"), до, self.old[w].value if с_кернингом else None, False),
                  (t("after"), после, self._after(w) if с_кернингом else None, True)]
        кегль = self.preview_size.value
        масштаб = кегль / float(до.upm)
        поле_подписи, отступ = 70, 16
        self._preview_width = self.preview_area.viewport().width
        доступно = max(200, self._preview_width - поле_подписи - 2 * отступ - 8)

        # слова — по пробелу; кусок растёт, пока обе строки влезают
        i = до.glyph(0x20)
        пробел = до.name(i) if i is not None else None
        слова, слово = [], []
        for имя in имена:
            слово.append(имя)
            if имя == пробел:
                слова.append(слово)
                слово = []
        if слово:
            слова.append(слово)

        def ширина(кусок):
            return max(layout(кусок, м, к)[1] for _, м, к, _ in строки) * масштаб

        куски, кусок = [], []
        for слово in слова:
            if кусок and ширина(кусок + слово) > доступно:
                куски.append(кусок)
                кусок = []
            кусок = кусок + слово
        if кусок or not куски:
            куски.append(кусок)

        шаг = int(кегль * 1.35)
        промежуток = int(кегль * 0.6)
        высота = 2 * отступ + len(куски) * (2 * шаг + промежуток)
        во_всю = int(max([ширина(к) for к in куски] + [доступно])) + поле_подписи + 2 * отступ
        картинка = QtGui.QPixmap(min(во_всю, 16000), min(высота, 16000))
        картинка.fill(QtGui.QColor(255, 255, 255))
        кисть = QtGui.QPainter(картинка)
        кисть.setRenderHint(QtGui.QPainter.Antialiasing)
        правленые = set(spacing_after(self.result, w))
        if w in self.result.space and пробел is not None:
            правленые.add(пробел)
        верх = отступ
        for кусок in куски:
            for n, (подпись, м, кернинг, отмечать) in enumerate(строки):
                база = верх + n * шаг + кегль * 0.95
                кисть.setPen(QtGui.QColor(150, 150, 150))
                кисть.drawText(QtCore.QPointF(отступ, база), подпись)
                обычные, свои = QtGui.QPainterPath(), QtGui.QPainterPath()
                for путь in (обычные, свои):
                    путь.setFillRule(QtCore.Qt.WindingFill)
                for имя, x in layout(кусок, м, кернинг)[0]:
                    знак = м.glyphs[м.by_name(имя)]
                    self._path(свои if отмечать and имя in правленые else обычные, знак,
                               отступ + поле_подписи + x * масштаб, база, масштаб)
                кисть.fillPath(обычные, QtGui.QBrush(QtGui.QColor(20, 20, 20)))
                кисть.fillPath(свои, QtGui.QBrush(QtGui.QColor(30, 90, 200)))
            верх += 2 * шаг + промежуток
            кисть.setPen(QtGui.QColor(225, 225, 225))
            кисть.drawLine(отступ, верх - промежуток // 2, картинка.width() - отступ, верх - промежуток // 2)
        кисть.end()
        self.preview_label.setText("")
        self.preview_label.setPixmap(картинка)

    # ── правки ──

    def _find_glyph(self, запрос):
        m = self.masters[0]
        if m.by_name(запрос) is not None:
            return запрос
        if len(запрос) == 1 and m.glyph(ord(запрос)) is not None:
            return m.name(m.glyph(ord(запрос)))
        return None

    def _fill_edits(self):
        if not self._on(self.page_edits) or self.result is None:
            return
        w = max(0, self.edits_master.currentIndex)
        запрос = self.search.text.strip()
        знак = self._find_glyph(запрос) if запрос else None
        self._fill_glyphs(w, запрос, знак)
        self._fill_pairs(w, запрос, знак)

    def _row(self, таблица, r, галка, ячейки):
        QtCore, QtGui = self.QtCore, self.QtGui
        пункт = QtGui.QTableWidgetItem("")
        пункт.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
        пункт.setCheckState(QtCore.Qt.Checked if галка else QtCore.Qt.Unchecked)
        таблица.setItem(r, 0, пункт)
        for c, текст in enumerate(ячейки):
            таблица.setItem(r, c + 1, QtGui.QTableWidgetItem(текст))

    def _label(self, имя):
        """Знак для таблицы: символ, если есть код, и имя"""
        g = self.masters[0].glyphs[self.masters[0].by_name(имя)]
        код = g.codes[0] if g.codes else None
        if код is None or код <= 0x20 or 0x7F <= код < 0xA0 or код == 0xA0:
            return имя
        return "%s  %s" % (chr(код), имя)

    def _pair_label(self, л, п):
        """Пара для таблицы: «To   T o» — символами, затем именами"""
        m = self.masters[0]
        символы = []
        for имя in (л, п):
            g = m.glyphs[m.by_name(имя)]
            код = g.codes[0] if g.codes else None
            символы.append(chr(код) if код is not None and код > 0x20 and not 0x7F <= код <= 0xA0 else "/" + имя)
        return "%s    %s %s" % ("".join(символы), л, п)

    def _fill_glyphs(self, w, запрос, знак):
        м = self.masters[w]
        ряды = []
        for имя, по_мастерам in self.result.spacing.items():
            место = по_мастерам.get(w)
            i = м.by_name(имя)
            if место is None or i is None:
                continue
            dx, ширина = место
            было = м.advance(i)
            r = contours_rect(м.contours(i))
            if r is None:
                # пустой знак (пробелы): полей нет, только ширина
                ряды.append((abs(ширина - было), имя, True, None, None, (было, ширина)))
                continue
            лев, прав = irnd(r[0]), было - irnd(r[2])
            ряды.append((max(abs(dx), abs(ширина - было - dx)), имя, True,
                         (лев, лев + dx), (прав, прав + ширина - было - dx), (было, ширина)))
        ряды.sort(key=lambda р: (-р[0], р[1]))
        снятые = [(0, имя, False, None, None, None) for имя in sorted(self.rejected_glyphs)
                  if имя not in self.result.spacing]
        ряды = снятые + ряды
        if запрос:
            ряды = [р for р in ряды if р[1] == знак or запрос.lower() in р[1].lower()]
        таблица = self.glyphs_table
        таблица.blockSignals(True)
        таблица.setRowCount(len(ряды))
        self._glyph_rows = []
        for n, (_, имя, _, лев, прав, шир) in enumerate(ряды):
            if шир is None:
                ячейки = [self._label(имя), t("kept"), "", ""]
            else:
                ячейки = [self._label(имя)] + ["—" if пара is None else (
                    "%s → %s" % (_num(пара[0]), _num(пара[1])) if пара[0] != пара[1] else _num(пара[0]))
                    for пара in (лев, прав, шир)]
            self._row(таблица, n, имя not in self.rejected_glyphs, ячейки)
            self._glyph_rows.append(имя)
        таблица.resizeColumnsToContents()
        таблица.blockSignals(False)
        self.glyphs_title.setText(t("edits_glyphs") % len(ряды))

    def _fill_pairs(self, w, запрос, знак):
        до = self.old[w].value
        после = self._after(w, rejected=False)
        if запрос and знак is None:
            ряды = []
            заголовок = t("edits_pairs_none") % запрос
        elif знак is not None:
            ряды = changed_pairs([g.name for g in self.masters[0].glyphs], до, после, glyph=знак)
            заголовок = t("edits_pairs_glyph") % (знак, len(ряды))
        else:
            ряды = self._top_pairs.get(w)
            if ряды is None:
                прежний = self.status.text
                self._quiet(t("counting_pairs"))
                кодовые = [g.name for g in self.masters[0].glyphs if g.codes]
                ряды = self._top_pairs[w] = changed_pairs(кодовые, до, после, top=300)
                self._status(прежний)
            заголовок = t("edits_pairs_top") % len(ряды)
        таблица = self.pairs_table
        таблица.blockSignals(True)
        таблица.setRowCount(len(ряды))
        self._pair_rows = []
        for n, (л, п, было, стало) in enumerate(ряды):
            ключ = л + "|" + п
            self._row(таблица, n, ключ not in self.rejected_pairs,
                      [self._pair_label(л, п), _num(было), _num(стало)])
            self._pair_rows.append(ключ)
        таблица.resizeColumnsToContents()
        таблица.blockSignals(False)
        self.pairs_title.setText(заголовок)

    def _glyph_ticked(self, пункт):
        if пункт.column() != 0 or пункт.row() >= len(self._glyph_rows):
            return
        имя = self._glyph_rows[пункт.row()]
        if пункт.checkState() == self.QtCore.Qt.Checked:
            self.rejected_glyphs.discard(имя)
        else:
            self.rejected_glyphs.add(имя)
        if self.rejected_glyphs != self.calc_rejected and not self.applied:
            self._status(t("stale_glyphs"))
        self._update_buttons()

    def _pair_ticked(self, пункт):
        if пункт.column() != 0 or пункт.row() >= len(self._pair_rows):
            return
        ключ = self._pair_rows[пункт.row()]
        if пункт.checkState() == self.QtCore.Qt.Checked:
            self.rejected_pairs.discard(ключ)
        else:
            self.rejected_pairs.add(ключ)

    # ── запись, откат, сохранение ──

    def _apply(self):
        if self.busy or self.result is None or self.stale or self.applied:
            return
        if self.source.fingerprint(self.names) != self.fingerprint_:
            self.stale = True
            self._update_buttons()
            return self._status(t("font_changed"))
        self._begin(t("applying"), False)
        try:
            после = [self._after(w) for w in range(len(self.names))]
            записано, снимок = self.source.apply(
                self.result, self.calc_options, self._quiet, masters=self.names, only=self.only,
                rejected=set(self.rejected_pairs), old=self.old, writes=self.writes)
            self.snapshots.append((снимок, self.masters, self.names))
            self.applied = True
            self._quiet(t("applying"))
            плохо = check(FontSource(self.source.font), self.result, self.masters, self.names, после)
            сверка = t("check_ok") if not плохо else t("check_bad") % (len(плохо), "; ".join(плохо[:3]))
            текст = t("done_apply") % (записано["glyphs"], _n(записано["cells"]), _n(записано["pairs"]),
                                       сверка)
            self._status(_e(текст + " " + t("panels")))
            self.info["kern_feature"] = False
            # после удачной записи — одна тихая строка о поддержке, без окон
            self._show_summary(_e(t("applied_banner") % (
                записано["glyphs"], _n(записано["cells"]), _n(записано["pairs"]), сверка))
                + "<br><small><a href='%s'>%s</a></small>" % (_e(support_url()), _e(t("support_after"))))
        except Exception as ошибка:
            self._error(ошибка)
        finally:
            self._end()

    def _revert(self):
        if self.busy or not self.snapshots:
            return
        QtGui = self.QtGui
        вопрос = QtGui.QMessageBox(self.window)
        вопрос.setWindowTitle(t("revert"))
        вопрос.setText(t("revert_q"))
        да = вопрос.addButton(t("revert"), QtGui.QMessageBox.AcceptRole)
        нет = вопрос.addButton(t("cancel"), QtGui.QMessageBox.RejectRole)
        вопрос.setDefaultButton(нет)
        вопрос.exec_()
        if вопрос.clickedButton() != да:
            return
        снимок, до, names = self.snapshots.pop()
        self._begin(t("reverting"), False)
        try:
            self.source.restore(снимок, self._quiet)
            плохо = check_restored(FontSource(self.source.font), снимок, до, names)
            сверка = t("check_ok") if not плохо else t("check_bad") % (len(плохо), "; ".join(плохо[:3]))
            текст = t("done_revert") % сверка
            if снимок.lost_zero_pairs:
                текст += t("lost_zero") % снимок.lost_zero_pairs
            self._status(_e(текст + " " + t("panels")))
            # итог расчёта относился к шрифту до записи — он снова верен
            if self.result is not None and self.masters is до:
                self.applied = False
                self.info["kern_feature"] = снимок.kern_feature is not None
                self._show_summary(_e(t("reverted_banner")))
        except Exception as ошибка:
            self._error(ошибка)
        finally:
            self._end()

    def _save(self):
        if self.busy or self.result is None:
            return
        try:
            папка = os.path.dirname(self.source.font.path or "") or os.path.expanduser("~/Desktop")
        except Exception:
            папка = os.path.expanduser("~/Desktop")
        папка = self.QtGui.QFileDialog.getExistingDirectory(self.window, t("save_title"), папка)
        if not папка:
            return
        try:
            файлы = export.save(папка, self.source.name or "font", self.summary_html, self.report,
                                self.result, self.names, self.writes[0] if self.writes else None)
            self._status(_e(t("saved") % (len(файлы), папка)))
        except Exception as ошибка:
            self._error(ошибка)


def main():
    from PythonQt import QtGui
    try:
        source = FontSource()
    except Exception:
        QtGui.QMessageBox.information(None, t("title"), t("no_font"))
        return
    # прежнее окно сценария — закрыть; новое держать, пока открыто
    прежнее = getattr(sys, "_autokerner_window", None)
    if прежнее is not None:
        try:
            прежнее.window.close()
        except Exception:
            pass
    окно = Window(source)
    sys._autokerner_window = окно
    окно.window.show()
    QtGui.QApplication.processEvents()
    окно.restore_place()
    окно.window.raise_()
