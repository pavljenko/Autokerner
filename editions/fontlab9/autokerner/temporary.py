"""Owned MCP-only copies. No FontSource/flPackage/fgFont wrappers may escape."""
from contextlib import contextmanager
import json
import re
from pathlib import Path
import uuid

_pending = {}  # A failed close blocks the next copy; never accumulate documents.


def checked(response):
    if response.get('status') in ('error', 'failed') or response.get('success') is False:
        raise RuntimeError(json.dumps(response, ensure_ascii=False))
    return response


@contextmanager
def temporary_font(source_id, master, directory, events=None):
    import fontpr
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ('autokerner9-' + uuid.uuid4().hex + '.vfj')
    current = fontpr.list_fonts()['fonts']
    if _pending or any(re.fullmatch(r'autokerner9-[0-9a-f]{32}', Path(f['file_name']).stem) for f in current):
        raise RuntimeError('Предыдущая временная копия ещё не закрыта; новый расчёт запрещён')
    before = {f['id'] for f in current}
    previous = fontpr.get_active_font().get('id')
    identifier = None
    opened = False
    _pending[str(path)] = None
    try:
        checked(fontpr.save_font(font_id=source_id, path=str(path), format='vfj', overwrite=False))
        data = json.loads(path.read_text(encoding='utf-8'))
        data['font']['defaultMaster'] = master
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        del data
        opened = True  # An error response may still leave a document to clean up.
        checked(fontpr.open_font(path=str(path)))
        matches = [f['id'] for f in fontpr.list_fonts()['fonts']
                   if f['id'] not in before and Path(f['file_name']).stem == path.stem]
        if len(matches) != 1:
            raise RuntimeError('Не удалось однозначно найти временный документ ' + path.name)
        identifier = matches[0]
        _pending[str(path)] = identifier
        if events is not None:
            events.append({'event': 'opened', 'id': identifier, 'file': path.name})
        yield identifier
    finally:
        closed = not opened
        if opened:
            matches = [f['id'] for f in fontpr.list_fonts()['fonts']
                       if f['id'] not in before and Path(f['file_name']).stem == path.stem]
            if identifier is None and len(matches) == 1:
                identifier = matches[0]
                _pending[str(path)] = identifier
                if events is not None:
                    events.append({'event': 'opened', 'id': identifier, 'file': path.name, 'open_error': True})
            if identifier is not None:
                if matches != [identifier]:
                    raise RuntimeError('Временный документ сменил идентификатор; закрытие отменено')
                checked(fontpr.close_font(font_id=identifier, save=False))
                if any(f['id'] == identifier for f in fontpr.list_fonts()['fonts']):
                    raise RuntimeError('FontLab не закрыл временный документ ' + path.name)
                if events is not None:
                    events.append({'event': 'closed', 'id': identifier, 'file': path.name})
                closed = True
            elif not matches:
                # An open error without a new document also requires file cleanup.
                after_ids = {f['id'] for f in fontpr.list_fonts()['fonts']}
                closed = after_ids.issubset(before)
        if closed:
            path.unlink(missing_ok=True)
            _pending.pop(str(path), None)
        if previous in {f['id'] for f in fontpr.list_fonts()['fonts']}:
            checked(fontpr.set_active_font(font_id=previous))
        if not closed:
            raise RuntimeError('Временный документ не закрыт; последующие расчёты заблокированы')


def copy_metrics(identifier, master, names):
    import fontpr
    result = {}
    for name in names:
        row = checked(fontpr.get_glyph_metrics(font_id=identifier, glyph_name=name))
        if row['active_layer_name'] != master:
            raise RuntimeError('Временная копия выбрала другой мастер: ' + str(row['active_layer_name']))
        result[name] = (float(row['lsb']), float(row['rsb']), float(row['advance_width']))
    return result


def _copy_ink_metrics_data(identifier, master, names):
    """Return plain data/error text; never propagate native-wrapper tracebacks."""
    import fontlab as fl
    from .fontlab_bridge import FontSource
    from .geometry import contours_rect
    source = font = package = layer = None
    fonts = []
    result, failure = {}, None
    try:
        fonts = list(fl.AllFonts())
        for candidate in fonts:
            package = fl.flPackage(candidate)
            if package.fgId == identifier:
                font = candidate
                break
            package = None
        candidate = None
        if font is None:
            raise ValueError('Temporary font identifier was not found')
        source = FontSource(font)
        if master not in source.master_names:
            raise ValueError('Temporary font does not contain master ' + str(master))
        models = source.read(masters=[master])
        if len(models) != 1 or models[0].label != master:
            raise ValueError('Temporary font returned a different master')
        model = models[0]
        for name in names:
            index = model.by_name(name)
            layer = source.layer(name, master)
            if index is None or layer is None:
                raise ValueError('Temporary font is missing glyph/layer ' + str(name))
            width = float(layer.advanceWidth)  # Preserve actual fractional width.
            box = contours_rect(model.contours(index))
            left, right = (box[0], width - box[2]) if box is not None else (0., width)
            result[str(name)] = (float(left), float(right), width)
            layer = None
    except Exception as error:
        failure = type(error).__name__ + ': ' + str(error)
        error.__traceback__ = None
    finally:
        layer = None
        try:
            if source is not None:
                source._glyphs.clear()
                source.package = None
                source.font = None
        except Exception as error:
            failure = (failure + '; ' if failure else '') + 'Native reference release failed: ' + str(error)
            error.__traceback__ = None
        source = package = font = None
        candidate = None
        fonts.clear()
    return (None if failure else result), failure


def copy_ink_metrics(identifier, master, names):
    """Full-ink LSB/RSB, including dots/accents, plus actual layer advance.

    get_glyph_metrics may measure a glyph's body rather than its full ink. Keep
    copy_metrics as the legacy API readout; spacing vectors require this basis.
    """
    result, failure = _copy_ink_metrics_data(identifier, master, names)
    if failure:
        raise RuntimeError(failure) from None
    return result
