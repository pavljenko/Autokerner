"""Additive FL9 source adapter; the stable Classic bridge stays unchanged."""
from .auto import AutoResult
from .fontlab_bridge import FontSource, OldKerning
from .options import Options, REPLACE
from .hybrid import state_data, stable, parameters
from . import text_kern


class Source(FontSource):
    def fingerprint(self, masters=None):
        # Use the base reader here: state_data itself calls fingerprint.
        import hashlib
        return hashlib.sha256(stable(canonical_state(
            state_data(FontSource(self.font), self.master_names[0]))).encode('utf-8')).hexdigest()

    def apply(self, result, options=None, progress=None, masters=None, only=None,
              rejected=(), old=None, writes=None):
        selected = list(masters or self.master_names)
        token = self.fingerprint()
        if result.kern is not None and self.has_kern_feature():
            if (options or Options()).kern_mode == REPLACE:
                raise RuntimeError('Text kern is authored code. Choose Add to existing to preserve it; Replace is available for visual kerning tables.')
            if len(selected) != 1:
                raise RuntimeError('Text kern across masters requires the MM/VF export plan.')
            counts, snapshot = self._apply_text(result, options or Options(), progress,
                                                selected, only, rejected)
        else:
            counts, snapshot = super().apply(result, options, progress, selected,
                                              only, rejected, old, writes)
        snapshot.hybrid_undo_token = self.fingerprint()
        snapshot.hybrid_before_token = token
        return counts, snapshot

    def _apply_text(self, result, options, progress, masters, only, rejected):
        import fontgate as fg
        import fontpr
        layout = fg.fgOTLayout(self.font)
        original, prefix = layout.get_feature('kern'), layout.get_prefix()
        names = [g.name for g in self.font.glyphs]
        values = parameters(fontpr.get_font_info(font_id=self.package.fgId))[masters[0]]
        covered = text_kern.coverage(text_kern.resolve(prefix, values),
                                     text_kern.resolve(original, values), names)
        old = OldKerning(*self.kerning_now(masters[0]))
        pairs = {}
        rejected = set(rejected)
        for a in names:
            for b in names:
                key = a + '|' + b
                if (key in rejected or (only is not None and not {a,b} & set(only))
                        or covered.has(a,b) or old.has(a,b)):
                    continue
                value = round(result.kern.value(a,b,0))
                if value:
                    pairs[key] = value
        if options.kern_limit:
            pairs = dict(sorted(pairs.items(), key=lambda p:(-abs(p[1]), p[0]))[:options.kern_limit])
        lines = ['  pos \\%s \\%s %d;' % (*key.split('|'), value)
                 for key,value in sorted(pairs.items())]
        merged = text_kern.append_rules(prefix, original, names, lines,
                        lambda code:text_kern.resolve(code, values)) if lines else original
        # All parsing/compilation is complete BEFORE any source mutation.
        spacing = AutoResult(result.weights, result.spacing, result.space, None, result.plans)
        counts, snapshot = super().apply(spacing, options, progress, masters)
        snapshot.kern_feature = original
        try:
            layout.set_feature('kern', merged)
            if layout.get_feature('kern') != merged:
                raise RuntimeError('Text kern readback differs from the prepared code.')
        except Exception:
            self._restore_exact(snapshot, progress)
            raise
        counts.update(pairs=len(pairs), mode='missing', hybrid_text=True)
        self._refresh()
        return counts, snapshot

    def _restore_exact(self, snapshot, progress=None):
        super().restore(snapshot, progress)
        if snapshot.kern_feature is not None:
            import fontgate as fg
            layout = fg.fgOTLayout(self.font)
            layout.set_feature('kern', snapshot.kern_feature)
            if layout.get_feature('kern') != snapshot.kern_feature:
                raise RuntimeError('Original text kern was not restored exactly.')
        self._refresh()

    def restore(self, snapshot, progress=None):
        expected = getattr(snapshot, 'hybrid_undo_token', None)
        if expected is not None and self.fingerprint() != expected:
            raise RuntimeError('The font changed after Apply. Undo preserves those edits; recalculate first.')
        self._restore_exact(snapshot, progress)
        original = getattr(snapshot, 'hybrid_before_token', None)
        if original is not None and self.fingerprint() != original:
            raise RuntimeError('Undo readback differs from the original source.')


def canonical_state(value):
    """IEEE negative zero is the same coordinate, not a source edit."""
    if isinstance(value, float) and value == 0:
        return 0.0
    if isinstance(value, (list, tuple)):
        return [canonical_state(item) for item in value]
    if isinstance(value, dict):
        normalized = {key:canonical_state(item) for key,item in value.items()}
        # FontLab serializes this dictionary as a list, and recreating the
        # identical classes may reverse that list. Values/members remain guarded.
        if isinstance(normalized.get('kerningClasses'), list):
            normalized['kerningClasses'] = sorted(normalized['kerningClasses'], key=stable)
        return normalized
    return value
