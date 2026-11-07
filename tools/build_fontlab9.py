"""Build the public FL9 hybrid, isolated from the FL8 package and settings."""
import base64
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EDITION=ROOT/'editions/fontlab9'
MODULES=['__init__','unicode_props','geometry','model','zero_model','zero','spacing',
         'kerning','options','auto','report','outcome','export','fontlab_bridge',
         'temporary','text_kern','axis_map','automatic_avar','variable_kern','hybrid',
         'fontlab_ui','classic_hybrid_bridge','classic_hybrid','classic_text_preview','classic_hybrid_ui']


def build():
    version=(EDITION/'VERSION').read_text().strip()
    sources={n:(EDITION/'autokerner'/(n+'.py')).read_text() for n in MODULES}
    vendor=base64.b64encode((EDITION/'vendor/fonttools-py.zip').read_bytes()).decode()
    code='''#FLM: Autokerner 9 Hybrid
# -*- coding: utf-8 -*-
# Autokerner 9 Hybrid %s. Copyright 2026 Sasha Pavljenko. MIT.
# Includes fontTools; see FONTTOOLS-LICENSE.txt in the installation archive.
import sys, types, base64, hashlib, tempfile
from pathlib import Path
_VENDOR_ZIP = %r
if 'fontTools' not in sys.modules:
    _data = base64.b64decode(_VENDOR_ZIP)
    _hash = hashlib.sha256(_data).hexdigest()
    _path = Path(tempfile.gettempdir()) / ('autokerner9-fonttools-' + _hash + '.zip')
    if not _path.exists() or hashlib.sha256(_path.read_bytes()).hexdigest() != _hash:
        _path.write_bytes(_data)
    sys.path.insert(0, str(_path))
_SOURCES = %r
for _name, _source in _SOURCES.items():
    _full = 'autokerner9classic' if _name == '__init__' else 'autokerner9classic.' + _name
    _m = types.ModuleType(_full)
    _m.__package__ = 'autokerner9classic'
    _m.__file__ = __file__
    if _name == '__init__': _m.__path__ = []
    sys.modules[_full] = _m
    exec(compile(_source, _full, 'exec'), _m.__dict__)
    if _name != '__init__': setattr(sys.modules['autokerner9classic'], _name, _m)
if not globals().get('_HYBRID_TEST_ONLY'):
    from autokerner9classic.classic_hybrid_ui import main
    main(Path(__file__).resolve().parent / 'hybrid-classic-state')
''' % (version,vendor,sources)
    target=ROOT/'dist/Autokerner9.py';target.parent.mkdir(exist_ok=True)
    compile(code,str(target),'exec');target.write_text(code)
    return target


if __name__=='__main__': print(build())
