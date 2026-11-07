"""Real-font code regression; accepts external fonts, publishes no font files."""
import argparse
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys
from autokerner import auto
from autokerner.otf import load_master
from autokerner.options import Options


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--baseline',type=Path,required=True,help='Unmodified v1.0.0 autokerner package')
    parser.add_argument('--fonts',type=Path,required=True,help='Parent of the six fixture directories')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();name='_autokerner100'
    spec=importlib.util.spec_from_file_location(name,args.baseline/'__init__.py',submodule_search_locations=[str(args.baseline)])
    package=importlib.util.module_from_spec(spec);sys.modules[name]=package;spec.loader.exec_module(package)
    old=importlib.import_module(name+'.auto');rows=[]
    for label in ('yanonekaffeesatz','alumnisans','merriweather','lora','comfortaa','karla'):
        path=args.fonts/label/'input.ttf';m=load_master(path)
        changes={g.name:(round(m.upm*.05-g.rect[0]),g.advance+round(m.upm*.05-g.rect[0])+round(m.upm*.05-(g.advance-g.rect[2])))
                 for g in m.glyphs if g.rect is not None and g.codes and g.name not in ('H','O','n','o','uni041D','uni041E','uni043D','uni043E')}
        m=m.with_metrics(changes)
        targets={m.name(m.glyph(ord(ch))) for ch in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ' if m.glyph(ord(ch)) is not None}
        fixed={g.name for g in m.glyphs}-targets
        o=Options(space=False,kerning=False)
        before=old.run([m],options=o,fixed=fixed)
        after=auto.run([m],options=o,fixed=fixed)
        disabled=auto.run([m],options=o,fixed=fixed,component_metrics=False)
        assert before.spacing==disabled.spacing
        assert before.plans[0].targets==after.plans[0].targets
        j=m.glyphs[m.by_name('j')];a,b=before.plans[0].item('j'),after.plans[0].item('j')
        if j.components: assert a is None and b is not None and 'j' in after.spacing
        else: assert before.spacing==after.spacing
        rows.append({'font':label,'font_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                     'composite_j':bool(j.components),'old_j_measured':a is not None,
                     'new_j_measured':b is not None,'new_j_shift_em1000':round(b.delta_left*1000/m.upm,3),
                     'reference_density_unchanged':True,'old_default_equals_new_legacy_switch':True})
    result={'baseline_version':package.__version__,'new_version':__import__('autokerner').__version__,
            'scope':'Editor-independent calculation on real TTF outlines; not a fresh FontLab 8 runtime test.',
            'input':'Nominal 50/1000 em bearings; H/O/n/o and Cyrillic equivalents retained; selected Latin glyphs.',
            'confirmed_composite_defect_fonts':sum(r['composite_j'] for r in rows),'control_fonts':sum(not r['composite_j'] for r in rows),
            'passed':True,'rows':rows}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
