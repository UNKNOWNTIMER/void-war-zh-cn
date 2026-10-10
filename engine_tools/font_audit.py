"""Read-only font coverage audit against the current staged game artifact.

Reads actual FONT and STRG chunk tables from data.win, plus the actual OTF cmap.
Only this script's JSON audit report is written. Does not modify the package.
"""
from pathlib import Path
import argparse,collections,csv,hashlib,json,struct,unicodedata

ROOT=Path(__file__).resolve().parent
OUT=Path(__file__).with_suffix('.json')
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--package-dir',type=Path,default=ROOT/'package')
p.add_argument('--report',type=Path,default=OUT)
args=p.parse_args();PACKAGE=args.package_dir;OUT=args.report
def sha(data):return hashlib.sha256(data).hexdigest()
def jread(path):return json.loads(path.read_text(encoding='utf-8-sig'))
data_path=PACKAGE/'data.win';data=data_path.read_bytes()
u=lambda at:struct.unpack_from('<I',data,at)[0]
h=lambda at:struct.unpack_from('<H',data,at)[0]
assert data[:4]==b'FORM' and u(4)+8==len(data)
chunks={};at=8
while at<len(data):
    tag=data[at:at+4].decode('ascii');size=u(at+4)
    chunks[tag]={'offset':at,'data':at+8,'size':size,'end':at+8+size}
    at+=size+8
assert at==len(data)
strg=chunks['STRG'];string_count=u(strg['data'])
def string(sid):
    assert 0<=sid<string_count
    at=u(strg['data']+4+4*sid);n=u(at)
    assert strg['data']<=at<at+4+n+1<=strg['end'] and data[at+4+n]==0
    return data[at+4:at+4+n].decode('utf-8')
def ptr_string(ptr):
    assert strg['data']<=ptr<strg['end']
    end=data.index(b'\0',ptr,strg['end'])
    return data[ptr:end].decode('utf-8')

records=[];source_inputs=[]
for table in ['functionText','UIText','encounterText']:
    path=PACKAGE/'lang'/f'{table}_zh-Hans';raw=path.read_bytes()
    with path.open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.reader(stream))
    assert all(len(row)==2 for row in rows)
    for key,text in rows[1:]:records.append({'source':table,'key':key,'text':text})
    source_inputs.append({'source':table,'path':str(path),'sha256':sha(raw),'records':len(rows)-1})
# Include every actual Chinese engine literal, including procedural names and UI.
for sid in range(string_count):
    value=string(sid)
    # STRG24355 is only referenced by gml_Object_CJK_test_Create_0. It combines
    # Chinese/Japanese/Korean sample paragraphs for the developer's font test.
    if sid not in {24355,24358} and any(0x3400<=ord(c)<=0x9fff for c in value):
        records.append({'source':'actual_engine_literals','key':f'STRG:{sid}','text':value})
extra_mismatches=[]

usage=collections.Counter();by_source=collections.defaultdict(collections.Counter);examples=collections.defaultdict(list)
for row in records:
    chars=[c for c in row['text'] if not c.isspace()]
    usage.update(chars);by_source[row['source']].update(chars)
    for c in set(chars):
        if len(examples[c])<3:
            examples[c].append({'source':row['source'],'key':row['key'],'text':row['text'][:500]})
required={ord(c) for c in usage}
def missing_detail(code):
    c=chr(code)
    return {'character':c,'codepoint':f'U+{code:04X}','unicode_name':unicodedata.name(c,'UNKNOWN'),
        'total_occurrences':usage[c],'by_source':{s:counts[c] for s,counts in by_source.items() if counts[c]},'examples':examples[c]}
def coverage(points):
    absent=sorted(required-points)
    return {'required_characters':len(required),'covered_characters':len(required&points),'missing_count':len(absent),
        'missing_characters':''.join(map(chr,absent)),'missing_details':[missing_detail(c) for c in absent],
        'by_source':{s:{'required_characters':len(counts),'missing_count':sum(ord(c) not in points for c in counts),
            'missing_characters':''.join(sorted(c for c in counts if ord(c) not in points))} for s,counts in by_source.items()}}

# Actual embedded bitmap glyph records. FONT40/43 are the requested default-mode fonts.
font_chunk=chunks['FONT'];font_count=u(font_chunk['data'])
embedded=[]
for fid in [40,43]:
    p=u(font_chunk['data']+4+fid*4);count=u(p+56)
    assert font_chunk['data']<=p<p+60+count*4<=font_chunk['end']
    glyphs={};empty=[]
    for i in range(count):
        at=u(p+60+i*4)
        assert font_chunk['data']<=at<at+16<=font_chunk['end']
        code,x,y,width,height,advance,left,kern_count=struct.unpack_from('<8H',data,at)
        assert code not in glyphs,('duplicate font glyph',fid,code)
        glyphs[code]={'record_offset':at,'x':x,'y':y,'width':width,'height':height,'advance_raw':advance,'left_raw':left}
        if code in required and (width==0 or height==0):empty.append({'character':chr(code),'codepoint':f'U+{code:04X}',**glyphs[code]})
    points=set(glyphs)
    embedded.append({'font_id':fid,'record_offset':p,
        'font_name':ptr_string(u(p)),'font_family':ptr_string(u(p+4)),
        'glyph_count':count,'cjk_glyph_count':sum(0x3400<=c<=0x9fff for c in points),
        'glyph_record_bounds_valid':True,'duplicate_codepoints':0,'required_glyphs_with_empty_rectangles':empty,
        'coverage':coverage(points)})

# Actual OTF Unicode cmap, including idDelta for nonzero format-4 glyph IDs.
otf_path=PACKAGE/'NotoSerifSC-Black.otf';b=otf_path.read_bytes()
u16=lambda p:struct.unpack_from('>H',b,p)[0]
u32=lambda p:struct.unpack_from('>I',b,p)[0]
tables={b[q:q+4].decode('ascii'):(u32(q+8),u32(q+12)) for q in range(12,12+16*u16(4),16)}
cmap=tables['cmap'][0];points=set();formats=set()
for q in range(cmap+4,cmap+4+8*u16(cmap+2),8):
    platform=u16(q);p=cmap+u32(q+4);fmt=u16(p)
    if platform not in (0,3):continue
    formats.add(fmt)
    if fmt==12:
        for x in range(p+16,p+16+12*u32(p+12),12):
            start,end,glyph=u32(x),u32(x+4),u32(x+8)
            points.update(range(start if glyph else start+1,end+1))
    elif fmt==4:
        n=u16(p+6)//2;ends=p+14;starts=ends+n*2+2;deltas=starts+n*2;ranges=deltas+n*2
        for i in range(n):
            start,end,delta,offset=u16(starts+2*i),u16(ends+2*i),u16(deltas+2*i),u16(ranges+2*i)
            for code in range(start,end+1):
                if offset:
                    glyph=u16(ranges+2*i+offset+2*(code-start))
                    if glyph:glyph=(glyph+delta)&65535
                else:glyph=(code+delta)&65535
                if glyph:points.add(code)
otf={'path':str(otf_path),'sha256':sha(b),'unicode_cmap_formats':sorted(formats),'mapped_codepoints':len(points),'coverage':coverage(points)}
report={'schema':'void-war-full-font-coverage-v1','audit_scope':'All beta translated CSV display values and every actual Chinese engine literal, including procedural names and main menu branding; actual OTF cmap and FONT40/43.',
    'data_win_path':str(data_path),'data_win_sha256':sha(data),'data_win_file_size':len(data),
    'source_inputs':source_inputs,'font_chunk':font_chunk,'embedded_font_count':font_count,
    'character_policy':'Audit translated display values and actual Chinese engine literals; omit Unicode whitespace and the developer-only multilingual CJK_test samples STRG24355/24358. Keep variables, tags, digits and punctuation conservatively.',
    'required_unique_non_whitespace_characters':len(required),'required_characters':''.join(map(chr,sorted(required))),
    'otf':otf,'embedded_fonts':embedded,
    'pass':not extra_mismatches and otf['coverage']['missing_count']==0 and all(f['coverage']['missing_count']==0 and not f['required_glyphs_with_empty_rectangles'] for f in embedded),
    'limitations':['Static glyph availability and bitmap rectangle validity, not an in-game text-layout or visual-quality test.','No assumed dynamic fallback for characters absent from an embedded bitmap font.']}
# Ensure the audit refers to one stable snapshot, not a concurrently changing file.
assert sha(data_path.read_bytes())==report['data_win_sha256'],'data.win changed during audit; rerun after build completes'
for x in source_inputs:
    assert sha(Path(x['path']).read_bytes())==x['sha256'],('source changed during audit',x['path'])
assert sha(otf_path.read_bytes())==otf['sha256'],'font changed during audit'
OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('FULL_FONT_COVERAGE', 'PASS' if report['pass'] else 'FAIL')
print('data_win_sha256',report['data_win_sha256'])
print('required_characters',len(required))
print('OTF_missing',otf['coverage']['missing_count'])
for f in embedded:print('FONT',f['font_id'],f['font_name'],'missing',f['coverage']['missing_count'],f['coverage']['missing_characters'],'empty_rectangles',len(f['required_glyphs_with_empty_rectangles']))
print('report',OUT)
