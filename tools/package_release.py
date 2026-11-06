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
            'README.md':ROOT/'README.md','README.ru.md':ROOT/'README.ru.md',
            'CHANGELOG.md':ROOT/'CHANGELOG.md','LICENSE':ROOT/'LICENSE'},
        f'autokerner-web-v{__version__}.zip':{
            'autokerner-article.html':ROOT/'dist/web/autokerner-article.html',
            'preview.html':ROOT/'dist/web/preview.html',
            'README.md':ROOT/'README.md','README.ru.md':ROOT/'README.ru.md',
            'LICENSE':ROOT/'LICENSE'}}
    for filename,files in bundles.items():
        with zipfile.ZipFile(dest/filename,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
            for name,path in sorted(files.items()):
                info=zipfile.ZipInfo(name,(2026,11,6,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
                z.writestr(info,path.read_bytes())
        with zipfile.ZipFile(dest/filename) as z:
            assert z.testzip() is None
            for name,path in files.items():assert z.read(name)==path.read_bytes()
    script=dest/'Autokerner.py';script.write_bytes((ROOT/'dist/Autokerner.py').read_bytes())
    paths=[script]+[dest/n for n in sorted(bundles)]
    (dest/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in paths))
    return dest

if __name__=='__main__':print(package())
