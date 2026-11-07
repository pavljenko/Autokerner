"""Reproducible installation archives; no test fonts or private reference data."""
from pathlib import Path
import hashlib,sys,zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from autokerner import __version__

def package():
    dest=ROOT/'dist'/'release';dest.mkdir(exist_ok=True)
    bundles={
        f'autokerner-v{__version__}.zip':{
            'Autokerner.py':ROOT/'dist/Autokerner.py',
            'README.md':ROOT/'docs/install-fontlab8.md','README.ru.md':ROOT/'docs/install-fontlab8.ru.md',
            'docs/validation/README.md':ROOT/'docs/validation/README.md',
            'docs/validation/composite-1.0.1.json':ROOT/'docs/validation/composite-1.0.1.json',
            'CHANGELOG.md':ROOT/'CHANGELOG.md','LICENSE':ROOT/'LICENSE'},
        f'autokerner-web-v{__version__}.zip':{
            'autokerner-article.html':ROOT/'dist/web/autokerner-article.html',
            'preview.html':ROOT/'dist/web/preview.html',
            'README.md':ROOT/'README.md','README.ru.md':ROOT/'README.ru.md',
            'LICENSE':ROOT/'LICENSE'}}
    hybrid_version=(ROOT/'editions/fontlab9/VERSION').read_text().strip()
    bundles[f'autokerner-fontlab9-v{hybrid_version}.zip']={
        'Autokerner9.py':ROOT/'dist/Autokerner9.py',
        'README.md':ROOT/'docs/install-fontlab9.md',
        'README.ru.md':ROOT/'docs/install-fontlab9.ru.md',
        'LICENSE':ROOT/'LICENSE',
        'FONTTOOLS-LICENSE.txt':ROOT/'editions/fontlab9/vendor/FONTTOOLS-LICENSE.txt',
        'resources/Autokerner9-compatible-TT.fl_profile':ROOT/'editions/fontlab9/resources/Autokerner9-compatible-TT.fl_profile',
        'docs/validation/README.md':ROOT/'docs/validation/README.md'}
    bundles[f'autokerner-fontlab9-slides-v{hybrid_version}.zip']={
        'fontlab9.html':ROOT/'docs/slides/fontlab9.html',
        **{f'{i:02d}.png':ROOT/f'docs/images/fontlab9/{i:02d}.png' for i in range(1,7)}}
    for filename,files in bundles.items():
        with zipfile.ZipFile(dest/filename,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
            for name,path in sorted(files.items()):
                info=zipfile.ZipInfo(name,(2026,11,7,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
                z.writestr(info,path.read_bytes())
        with zipfile.ZipFile(dest/filename) as z:
            assert z.testzip() is None
            for name,path in files.items():assert z.read(name)==path.read_bytes()
    script=dest/'Autokerner.py';script.write_bytes((ROOT/'dist/Autokerner.py').read_bytes())
    hybrid=dest/'Autokerner9.py';hybrid.write_bytes((ROOT/'dist/Autokerner9.py').read_bytes())
    paths=[script,hybrid]+[dest/n for n in sorted(bundles)]
    (dest/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in paths))
    for edition,selected in {
        'fontlab8':[script,dest/f'autokerner-v{__version__}.zip',dest/f'autokerner-web-v{__version__}.zip'],
        'fontlab9':[hybrid,dest/f'autokerner-fontlab9-v{hybrid_version}.zip',dest/f'autokerner-fontlab9-slides-v{hybrid_version}.zip']
    }.items():
        (dest/f'SHA256SUMS-{edition}.txt').write_text(''.join(
            hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in selected))
    return dest

if __name__=='__main__':print(package())
