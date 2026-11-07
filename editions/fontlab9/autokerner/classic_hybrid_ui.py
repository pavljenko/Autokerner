"""Additive FL9 controller over the unmodified Classic 1.0 window.

The Classic calculation method uses a private globals dictionary for run() and,
in authored-text Merge mode, coverage-aware OldKerning. Its source and module
globals are untouched.
"""
import html
import re
import sys
from pathlib import Path
from types import FunctionType

from . import fontlab_ui as classic
from .auto import AutoResult
from .hybrid import SPACING, KERNING
from .options import MERGE, SELECTED
from .report import CONTROL_PAIRS


_TEXT = {
    'engines': ('Движки FontLab 9', 'FontLab 9 engines', 'FontLab-9-Engines'),
    'spacing': ('Апроши', 'Spacing', 'Zurichtung'),
    'kerning': ('Кернинг', 'Kerning', 'Kerning'),
    'compare': ('Сравнить предложения', 'Compare proposals', 'Vorschläge vergleichen'),
    'comparison': ('Сравнение движков', 'Engine comparison', 'Engine-Vergleich'),
    'candidate': ('Показать кандидата', 'Review candidate', 'Kandidat prüfen'),
    'columns': ('Движки / Изменённых знаков / Предложения контрольных пар', 'Engines / Changed glyphs / Proposed control pairs', 'Engines / Geänderte Zeichen / Vorgeschlagene Kontrollpaare'),
    'engine_note': ('Autokerner сохраняет исходный расчёт Classic. Нативные апроши используют настройки FontLab; связанный режим переносит числа, не постоянные связи.',
                    'Autokerner keeps the Classic calculation. Native spacing uses FontLab preferences; linked mode transfers numbers, not persistent links.',
                    'Autokerner behält die Classic-Berechnung. Native Zurichtung nutzt FontLab-Einstellungen; der verknüpfte Modus überträgt Zahlen, keine dauerhaften Verknüpfungen.'),
    'compare_note': ('Один и тот же вход. Числа — предложения, не рейтинг качества. Выберите движки и снова нажмите «Посчитать» для полного просмотра.',
                     'The same input. Values are proposals, not quality scores. Review a candidate to use the full Classic preview and edits.',
                     'Derselbe Eingang. Werte sind Vorschläge, keine Qualitätsnoten. Einen Kandidaten für Classic-Vorschau und Änderungen auswählen.'),
    'text_note': ('Авторская текстовая kern сохраняется. В режиме «Дописать» покрытые пары не предлагаются к изменению. Строка и числовая статистика не воспроизводят текстовую kern — включая простые пары, контекстные правила и подстановки.',
                  'Authored text kern is preserved. In Add mode, covered pairs are not proposed for change. The preview and numeric statistics do not shape text kern, including simple pairs, contextual rules or substitutions.',
                  'Vorhandener kern-Featuretext bleibt erhalten. Im Hinzufügen-Modus werden abgedeckte Paare nicht zur Änderung vorgeschlagen. Vorschau und Zahlen bilden den kern-Featuretext nicht ab, auch keine einfachen Paare, Kontextregeln oder Ersetzungen.'),
    'preserved_pair': ('сохранено, без шейпинга', 'preserved, unshaped', 'erhalten, ohne Shaping'),
    'merge_required': ('Для текстовой kern выберите «Дописать к своему». Замена авторского кода этим маршрутом не выполняется.',
                       'For text kern, choose Add to it. This route does not replace authored feature code.',
                       'Für kern-Featuretext bitte Hinzufügen wählen. Dieser Weg ersetzt keinen vorhandenen Featurecode.'),
    'text_applied': ('Апроши применены; текстовая kern дополнена и проверена. Авторский код сохранён.',
                     'Spacing applied; text kern appended and verified. Authored code preserved.',
                     'Zurichtung angewendet; kern-Featuretext ergänzt und geprüft. Vorhandener Code bleibt erhalten.'),
    'mm_plan': ('Апроши применены; план экспорта текстовой kern подготовлен. Kern исходника не изменена.',
                'Spacing applied; text kerning export plan prepared; source kern unchanged.',
                'Zurichtung angewendet; Exportplan für kern-Featuretext vorbereitet; Quell-Kerning unverändert.'),
    'vf': ('Экспорт VF с текстовой kern…', 'Export VF with text kern…', 'VF mit kern-Featuretext exportieren…'),
    'tt': ('Экспорт TT-мастеров…', 'Export TT masters…', 'TT-Master exportieren…'),
    'export_stale': ('Настройки изменены. Пересчитайте и подготовьте план заново.',
                     'Settings changed. Calculate and prepare the plan again.',
                     'Einstellungen geändert. Bitte erneut berechnen und den Plan vorbereiten.'),
    'export_done': ('Экспорт сохранён: ', 'Export saved: ', 'Export gespeichert: '),
    'exporting': ('Экспортирую последовательно…', 'Exporting sequentially…', 'Exportiere nacheinander…'),
    'busy': ('Дождитесь завершения расчёта или нажмите «Стоп».', 'Wait for calculation or press Stop.', 'Berechnung abwarten oder Stopp drücken.'),
    'unavailable': ('Нет готового сравнения. Нажмите «Сравнить предложения».', 'No comparison yet. Press Compare proposals.', 'Noch kein Vergleich. Vorschläge vergleichen drücken.'),
    'invalid': ('Исходник или настройки изменились. Сравните заново.', 'Source or settings changed. Compare again.', 'Quelle oder Einstellungen geändert. Erneut vergleichen.'),
}


def t(key):
    return _TEXT[key][classic.LANG]


def native_progress(text):
    """Keep Classic translations first; translate only added provider forms."""
    original = str(text)
    translated = classic._tr(text)
    if classic.LANG == 0 or translated != original:
        return translated
    match = re.fullmatch(r'кернинг: (.+), пар (\d+) из (\d+)', original)
    if match:
        label, done, total = match.groups()
        return ('kerning: %s, pairs %s of %s' if classic.LANG == 1
                else 'Kerning: %s, Paare %s von %s') % (label, done, total)
    for prefix, english, german in (('апроши: ', 'spacing: ', 'Zurichtung: '),
                                     ('кернинг: ', 'kerning: ', 'Kerning: ')):
        if original.startswith(prefix):
            return (english if classic.LANG == 1 else german) + original[len(prefix):]
    return translated


def _value(obj, name):
    value = getattr(obj, name)
    return value() if callable(value) else value


def classic_call(window, name, *args, **replacements):
    """No monkeypatch: the original bytecode sees an isolated globals copy."""
    method = getattr(classic.Window, name)
    namespace = dict(method.__globals__)
    namespace.update(replacements)
    function = FunctionType(method.__code__, namespace, method.__name__, method.__defaults__, method.__closure__)
    function.__kwdefaults__ = method.__kwdefaults__
    return function(window, *args)


class Window(classic.Window):
    def __init__(self, source, workdir=None):
        self.workdir = Path(workdir or Path.home()/'.autokerner9-classic')
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._hybrid_connections = []
        self._hybrid_settings_ready = False
        self._disposed = self._close_pending = False
        self._text_session = None
        self._export_stale = True
        self._comparison_requested = False
        self._comparison_results = []
        self._comparison_guard = None
        self._closed = self._closed
        self._tick = self._tick
        self._watch = self._watch
        # VFJ persistence remains additive, before the first fingerprint.
        from .automatic_avar import watch
        self.avar_status = watch(source)
        super().__init__(source)
        self.window.setAttribute(self.QtCore.Qt.WA_DeleteOnClose, False)
        self.window.setWindowTitle(_value(self.window, 'windowTitle') + ' · FontLab 9')

    def _setting(self, key, default):
        if not self._hybrid_settings_ready:
            self.settings = self.QtCore.QSettings('Autokerner', 'Autokerner9Classic')
            self._hybrid_settings_ready = True
        return super()._setting(key, default)

    def _save_settings(self, o=None):
        super()._save_settings(o)
        if hasattr(self, 'spacing_engine'):
            self.settings.setValue('spacing_engine', self.spacing_engine.currentText)
            self.settings.setValue('kerning_engine', self.kerning_engine.currentText)
            self.settings.sync()

    def _connect(self, sender, signal, callback):
        sender.connect(signal, callback)
        self._hybrid_connections.append((sender, signal, callback))

    def _build_settings(self):
        area = super()._build_settings()
        layout = _value(_value(area, 'widget'), 'layout')
        group = self.QtGui.QGroupBox(t('engines'))
        form = self.QtGui.QVBoxLayout(group)
        fields = self.QtGui.QFormLayout()
        self.spacing_engine = self.QtGui.QComboBox(); self.spacing_engine.addItems(SPACING)
        self.kerning_engine = self.QtGui.QComboBox(); self.kerning_engine.addItems(KERNING)
        for widget, key, values in ((self.spacing_engine,'spacing_engine',SPACING), (self.kerning_engine,'kerning_engine',KERNING)):
            saved = str(self._setting(key, 'Autokerner'))
            widget.setCurrentIndex(values.index(saved) if saved in values else 0)
            self._connect(widget, 'currentIndexChanged(int)', self._engine_changed)
        fields.addRow(t('spacing'), self.spacing_engine); fields.addRow(t('kerning'), self.kerning_engine)
        form.addLayout(fields); form.addWidget(self._hint(t('engine_note')))
        self.btn_compare = self._button(t('compare'), self._compare)
        form.addWidget(self.btn_compare)
        layout.insertWidget(max(0, _value(layout, 'count')-1), group)
        return area

    def _build_results(self):
        tabs = super()._build_results()
        self._authored_preview_notes = []
        for page in (self.page_preview, self.page_edits):
            note = self._hint(t('text_note'))
            note.setVisible(self.source.has_kern_feature())
            _value(page, 'layout').addWidget(note)
            self._authored_preview_notes.append(note)
        page = self.QtGui.QWidget(); layout = self.QtGui.QVBoxLayout(page)
        self.comparison_choice = self.QtGui.QComboBox()
        self.btn_review_candidate = self._button(t('candidate'), self._review_candidate)
        layout.addWidget(self._hint(t('compare_note')))
        layout.addWidget(self.comparison_choice); layout.addWidget(self.btn_review_candidate)
        self.comparison_view = self.QtGui.QTextBrowser(); layout.addWidget(self.comparison_view)
        self.page_comparison = page; tabs.addTab(page, t('comparison'))
        return tabs

    def _build(self):
        super()._build()
        self.export_controls = self.QtGui.QWidget()
        row = self.QtGui.QHBoxLayout(self.export_controls)
        self.btn_export_vf = self._button(t('vf'), lambda: self._export_text(False))
        self.btn_export_tt = self._button(t('tt'), lambda: self._export_text(True))
        row.addWidget(self.btn_export_vf); row.addWidget(self.btn_export_tt)
        layout = _value(self.window, 'layout')
        layout.insertWidget(max(0, _value(layout,'count')-1), self.export_controls)
        self.export_controls.hide()

    def _engine_changed(self, *_):
        if not self.filling:
            self._mark_stale()
            self._save_settings()

    def _mark_stale(self):
        self._export_stale = True
        super()._mark_stale()

    def _update_buttons(self):
        super()._update_buttons()
        if hasattr(self, 'btn_compare'): self.btn_compare.setEnabled(not self.busy)
        if hasattr(self, 'btn_review_candidate'): self.btn_review_candidate.setEnabled(not self.busy and bool(self._comparison_results))
        if hasattr(self, 'export_controls'):
            ready = bool(self._text_session and self._text_session.review_plan)
            self.export_controls.setVisible(ready)
            for button in (self.btn_export_vf, self.btn_export_tt): button.setEnabled(ready and not self.busy and not self._export_stale)

    def _begin(self, text, can_stop):
        self.settings_area.setEnabled(False)
        super()._begin(text, can_stop)

    def _end(self):
        super()._end(); self.settings_area.setEnabled(True)
        if self._close_pending: self.dispose()

    def _tick(self):
        if not self._disposed: super()._tick()

    def _progress(self, text):
        super()._progress(native_progress(text))

    def _watch(self):
        if not self._disposed: super()._watch()

    def _calculate(self):
        from .classic_hybrid import calculate
        chosen = (str(self.spacing_engine.currentText), str(self.kerning_engine.currentText))
        pending = []
        def run(models, options=None, fixed=(), progress=None):
            names = [m for m in self.source.master_names if not options.masters or m in options.masters]
            pairs = [chosen]
            if self._comparison_requested:
                if options.spacing or options.space: pairs += [(e, chosen[1]) for e in SPACING if e != chosen[0]]
                if options.kerning: pairs += [(chosen[0],e) for e in KERNING if e != chosen[1]]
            for engines in pairs:
                if progress: progress('%s / %s' % engines)
                result = calculate(self.source, models, master_names=names, options=options,
                                   fixed=fixed, progress=progress, spacing_engine=engines[0],
                                   kerning_engine=engines[1], workdir=self.workdir/'copies')
                pending.append((engines, result))
            return pending[0][1]
        old_result = self.result
        replacements = {'run': run}
        try: factory = self._text_old_factory()
        except Exception as error:
            self._error(error); return
        if factory is not None: replacements['OldKerning'] = factory
        classic_call(self, '_calculate', **replacements)
        if self._disposed: return
        if self.result is not old_result:
            self._calculated_engines = chosen
            self._text_session = None; self._export_stale = True
            # processEvents() may run callbacks; never bless settings that were
            # changed while the unchanged Classic calculation was executing.
            if (self._read_options().to_dict() != self.calc_options.to_dict()
                    or chosen != (str(self.spacing_engine.currentText), str(self.kerning_engine.currentText))):
                self.stale = True
                self._status(t('invalid'))
            if self._comparison_requested:
                self._comparison_results = pending
                self._comparison_guard = (self.source.fingerprint(self.names), self.calc_options.to_dict(), set(self.only or ()), set(self.calc_rejected))
                self._fill_comparison()
            self._update_buttons()

    def _compare(self):
        if self.busy: return
        self._comparison_requested = True
        try: self._calculate()
        finally: self._comparison_requested = False
        if self._comparison_results: self.tabs.setCurrentIndex(self.tabs.indexOf(self.page_comparison))

    def _fill_comparison(self):
        from .classic_text_preview import authored_pair
        self.comparison_choice.clear()
        rows = []
        for engines, result in self._comparison_results:
            name = ' / '.join(engines)
            self.comparison_choice.addItem(name)
            pairs = []
            if result.kern:
                model = self.masters[0]
                for left, right in CONTROL_PAIRS[:12]:
                    li, ri = model.glyph(ord(left)), model.glyph(ord(right))
                    if li is not None and ri is not None:
                        a, b = model.name(li), model.name(ri)
                        pairs.append('%s%s: %s' % (left, right, t('preserved_pair')) if authored_pair(self.old, a, b)
                                     else '%s%s: %g' % (left, right, result.kern.value(a, b, 0)))
            rows.append('<tr><td>%s</td><td>%s</td><td>%s</td></tr>' % (html.escape(name), len(result.spacing), html.escape(' · '.join(pairs))))
        self.comparison_view.setHtml('<p>%s</p><p><b>%s</b></p><table cellpadding="6">%s</table>' % (html.escape(t('compare_note')), html.escape(t('columns')), ''.join(rows)))

    def _review_candidate(self):
        if self.busy or not self._comparison_results: return
        guard = self._comparison_guard
        selection = set(self.source.selected_names() or ()) if self._read_options().glyphs == SELECTED else set()
        if (not guard or self.source.fingerprint(self.names) != guard[0] or self._read_options().to_dict() != guard[1]
                or selection != guard[2] or self.rejected_glyphs != guard[3]):
            self._status(t('invalid')); return
        engines, result = self._comparison_results[max(0,self.comparison_choice.currentIndex)]
        for widget, values, value in ((self.spacing_engine,SPACING,engines[0]), (self.kerning_engine,KERNING,engines[1])):
            widget.blockSignals(True); widget.setCurrentIndex(values.index(value)); widget.blockSignals(False)
        replacements = {'run': lambda *a, **kw: result}
        try: factory = self._text_old_factory()
        except Exception as error:
            self._error(error); return
        if factory is not None: replacements['OldKerning'] = factory
        classic_call(self, '_calculate', **replacements)
        if self._disposed: return
        self._calculated_engines = engines
        self._text_session = None; self._export_stale = True; self._update_buttons()

    def _show_summary(self, banner=None):
        textual = self.source.has_kern_feature()
        for note in getattr(self, '_authored_preview_notes', ()):
            note.setVisible(textual)
        if textual and self.result is not None and self.result.kern is not None:
            from .classic_text_preview import visual_report
            def render(report, info):
                # Classic's destructive-feature warning is inapplicable here.
                return classic.report_html(visual_report(report, self.old, self.masters),
                                           dict(info, kern_feature=False))
            classic_call(self, '_show_summary', banner, report_html=render)
            self.summary_html += '<p><small>%s</small></p>' % html.escape(t('text_note'))
            self.summary.setHtml(self.summary_html)
        else:
            super()._show_summary(banner)

    def _text_old_factory(self):
        options = self._read_options()
        if not options.kerning or options.kern_mode != MERGE or not self.source.has_kern_feature():
            return None
        import fontgate as fg
        import fontpr
        from . import text_kern
        from .hybrid import parameters
        from .classic_text_preview import old_factory
        layout = fg.fgOTLayout(self.source.font)
        prefix, body = layout.get_prefix(), layout.get_feature('kern')
        values = parameters(fontpr.get_font_info(font_id=self.source.package.fgId))
        names = [g.name for g in self.source.font.glyphs]
        masters = [m for m in self.source.master_names if not options.masters or m in options.masters]
        coverages = [text_kern.coverage(text_kern.resolve(prefix, values[m]),
                                        text_kern.resolve(body, values[m]), names) for m in masters]
        return old_factory(classic.OldKerning, coverages)

    def _apply(self):
        textual = self.source.has_kern_feature() and self.result is not None and self.result.kern is not None
        if not textual:
            super()._apply()
            if self.result is not None and self.source.has_kern_feature(): self.info['kern_feature'] = True
            return
        if self.busy or self.stale or self.applied: return
        if self.calc_options.kern_mode != MERGE:
            self._status(t('merge_required')); return
        if self.source.fingerprint(self.names) != self.fingerprint_:
            self.stale = True; self._update_buttons(); self._status(classic.t('font_changed')); return
        self._begin(classic.t('applying'), False)
        snapshot = None
        try:
            spacing = AutoResult(self.result.weights, self.result.spacing, self.result.space, None, self.result.plans)
            if len(self.source.master_names) > 1:
                from .classic_hybrid import prepare_text_plan
                options = type(self.calc_options).from_dict(self.calc_options.to_dict()); options.kerning = False
                counts, snapshot = self.source.apply(spacing, options, self._quiet, masters=self.names, only=self.only)
                bad = classic.check(classic.FontSource(self.source.font), spacing, self.masters, self.names, [])
                if bad: raise RuntimeError('; '.join(bad[:3]))
                session = prepare_text_plan(self.source, self.result, self.names, self.calc_options,
                                            only=self.only, rejected=self.rejected_pairs, workdir=self.workdir/'copies', spacing_applied=True)
                self._text_session = session
                self._export_token = (self.calc_options.to_dict(), self._calculated_engines, set(self.rejected_pairs), set(self.rejected_glyphs))
                self._export_stale = False
                message = t('mm_plan')
            else:
                counts, snapshot = self.source.apply(self.result, self.calc_options, self._quiet,
                    masters=self.names, only=self.only, rejected=set(self.rejected_pairs), old=self.old, writes=self.writes)
                message = t('text_applied')
            self.snapshots.append((snapshot, self.masters, self.names))
            self.applied = True; self.info['kern_feature'] = True
            self._status(message); self._show_summary(html.escape(message))
        except Exception as error:
            if snapshot is not None: self.source.restore(snapshot, self._quiet)
            self._text_session = None; self._export_stale = True
            self._error(error)
        finally: self._end()

    def _revert(self):
        before = len(self.snapshots)
        entry = self.snapshots[-1] if before else None
        super()._revert()
        if self._disposed: return
        if len(self.snapshots) < before:
            # Classic removes the entry before restore(), which may correctly
            # refuse late authored edits. Keep its Undo entry and MM plan until
            # the source actually matches the recorded pre-Apply state.
            try:
                restored = self.source.fingerprint() == entry[0].hybrid_before_token
            except Exception:
                restored = False
            if restored:
                self._text_session = None; self._export_stale = True
            else:
                self.snapshots.append(entry)
            self._update_buttons()

    def _export_text(self, masters):
        if self.busy or not self._text_session or self._export_stale: return
        token = (self._read_options().to_dict(), (str(self.spacing_engine.currentText),str(self.kerning_engine.currentText)), set(self.rejected_pairs),set(self.rejected_glyphs))
        if token != self._export_token:
            self._export_stale = True; self._status(t('export_stale')); self._update_buttons(); return
        path = self.QtGui.QFileDialog.getSaveFileName(self.window,t('tt') if masters else t('vf'),'','*' if masters else '*.ttf')
        if isinstance(path,tuple): path=path[0]
        if not path: return
        self._begin(t('exporting'),False)
        try:
            result = self._text_session.export_masters(str(path)) if masters else self._text_session.export_variable(str(path))
            self._status(t('export_done')+str(result.get('directory',result.get('file',path))))
        except Exception as error: self._error(error)
        finally: self._end()

    def _closed(self, *_):
        if self._disposed: return
        super()._closed()
        if self.busy:
            self._close_pending = True
        else: self.dispose(already_closed=True)

    def dispose(self, already_closed=False):
        if self._disposed: return
        if self.busy: raise RuntimeError(t('busy'))
        self._disposed = True
        self._save_settings()
        for timer, callback in ((self.timer,self._tick),(self.geo_timer,self._watch)):
            timer.stop(); timer.disconnect('timeout()',callback); timer.deleteLater()
        for sender, signal, callback in self._hybrid_connections: sender.disconnect(signal,callback)
        self._hybrid_connections.clear()
        self.window.disconnect('finished(int)',self._closed)
        if not already_closed: self.window.close()
        self.window.deleteLater()
        self._comparison_results.clear(); self._text_session = None
        # The module keeps the closed controller for safe repeated invocation;
        # it must not keep pointers to a subsequently closed font alive.
        self.result = None; self.masters = []; self.snapshots.clear()
        self.source = None


def main(workdir=None):
    from .classic_hybrid_bridge import Source
    from PythonQt import QtGui
    previous = getattr(sys,'_autokerner9_classic_window',None)
    if previous is not None and not previous._disposed: previous.dispose()
    try: source = Source()
    except Exception:
        QtGui.QMessageBox.information(None,classic.t('title'),classic.t('no_font')); return
    window = Window(source,workdir)
    sys._autokerner9_classic_window = window
    window.window.show(); QtGui.QApplication.processEvents(); window.restore_place(); window.window.raise_()
    return window
