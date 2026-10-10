"""Audit the frozen archive and delta without dumping private local paths."""
import argparse
import gzip
import hashlib
import json
import marshal
from pathlib import Path
import struct
import types
from PyInstaller.archive.readers import CArchiveReader
from payload_format import PAYLOAD_FILES, ORIGINAL_FILES, read_header, sha

def audit(exe, original, forbidden):
    exe=Path(exe);original=Path(original);archive=CArchiveReader(str(exe))
    expected={'payload/'+p for p in PAYLOAD_FILES}|{'payload/payload.json','payload/engine.delta.gz'}
    members={p.replace('\\','/'):p for p in archive.toc}
    assert {p for p in members if p.startswith('payload/')}==expected
    assets={'assets/logo-source.png','assets/installer_logo.png','assets/installer.ico'}
    assert {p for p in members if p.startswith('assets/')}==assets
    assert not any(p.casefold().endswith(('.sav','/data.win')) or p.casefold()=='data.win' for p in members)
    m=json.loads(archive.extract(members['payload/payload.json']))
    for item in m['files']:
        assert hashlib.sha256(archive.extract(members['payload/'+item['path']])).hexdigest()==item['sha256']
    compressed=archive.extract(members['payload/engine.delta.gz'])
    assert hashlib.sha256(compressed).hexdigest()==m['delta_sha256']
    import io
    a=(original/'data.win').read_bytes();replacement=0
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as f:
        header=read_header(f);assert header==m['delta']
        for _ in range(header['segments']):
            x,n=struct.unpack('<QI',f.read(12));digest=f.read(32);new=f.read(n)
            assert digest==hashlib.sha256(a[x:x+n]).digest()
            assert len(new)==n and all(old!=newbyte for old,newbyte in zip(a[x:x+n],new))
            replacement+=n
        assert not f.read(1)
    # Inspect decoded member contents and recursively inspect PYZ code constants.
    # This catches developer paths hidden inside compressed executable archives.
    private=[value.encode('utf8') for value in forbidden]+[value.encode('utf-16le') for value in forbidden]
    checked=0
    def inspect_bytes(blob,label):
        nonlocal checked
        checked+=1
        assert not any(token.lower() in blob.lower() for token in private),('Private marker in public artifact',label)
    def inspect_code(code):
        inspect_bytes(code.co_filename.encode('utf8'),'code filename')
        for c in code.co_consts:
            if isinstance(c,types.CodeType):inspect_code(c)
            elif isinstance(c,str):inspect_bytes(c.encode('utf8'),'code string')
            elif isinstance(c,bytes):inspect_bytes(c,'code bytes')
    for normalized,key in members.items():
        if normalized=='PYZ.pyz':
            pyz=archive.open_embedded_archive(key)
            for name in pyz.toc:
                value=pyz.extract(name)
                if isinstance(value,types.CodeType):inspect_code(value)
                elif isinstance(value,bytes):inspect_bytes(value,name)
        else:
            blob=archive.extract(key)
            if isinstance(blob,bytes):inspect_bytes(blob,normalized)
    original_hashes={sha(original/p) for p in ORIGINAL_FILES}
    assert not any(hashlib.sha256(archive.extract(key)).hexdigest() in original_hashes
                   for key in archive.toc if isinstance(archive.extract(key),bytes))
    return {'status':'PASS','exe_sha256':sha(exe),'exe_bytes':exe.stat().st_size,
            'public_payload_files':sorted(expected),'public_art_assets':sorted(assets),'engine_replacement_segments':header['segments'],
            'replacement_bytes_only':replacement,'unchanged_original_context_bytes_in_delta':0,
            'full_original_engine_or_original_csv_members':0,'save_file_members':0,
            'private_marker_matches':0,'decoded_blobs_or_code_constants_checked':checked,
            'scope':'Whitelist, exact difference bytes, original-resource hashes and supplied private markers; not a general proof against every possible identifying string.'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--exe',type=Path,required=True)
    p.add_argument('--original-dir',type=Path,required=True);p.add_argument('--forbid',action='append',default=[])
    p.add_argument('--report',type=Path,required=True);args=p.parse_args()
    result=audit(args.exe,args.original_dir,args.forbid);args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
