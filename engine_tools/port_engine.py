"""Port the verified 1.5.2b localization by symbols and bounded physical regions.

Keeps the beta container, beta assets, beta gameplay changes and string pointers.
Does not write the installed game or saves. Every relocated reference is rebuilt.
"""
from pathlib import Path
import bisect,collections,difflib,hashlib,json,struct,sys
from gm import Engine
from engine_paths import inputs
A=inputs()
o=Engine(A.stable_original);f=Engine(A.stable_target);n=Engine(A.beta_original)
inv=json.loads((A.audit_dir/'port_inventory.json').read_text('utf8'));sidmap={int(k):v for k,v in inv['sid_map'].items()}
b=bytearray(n.b);patches=[];pu=lambda x:struct.pack('<I',x&0xffffffff)
old_maxend=max(c['end'] for c in o.codes.values());new_maxend=max(c['end'] for c in n.codes.values())
def patch(p,v,why):
    before=bytes(b[p:p+len(v)])
    if before==v:return
    b[p:p+len(v)]=v;patches.append({'offset':p,'old_hex':before.hex(),'new_hex':v.hex(),'reason':why})
def address(p):
    # Physical correspondence uses pristine ownership, not relocated metadata.
    if p==old_maxend:return new_maxend
    c=o.owner(p);d=n.codes[c['name']]
    assert c['end']-c['begin']==d['end']-d['begin'],('Changed source span',c['name'])
    return d['begin']+p-c['begin']
def rowkey(e,r):
    t=e.tables[r];return(t['kind'],t['name'],t['instance'])
rowmap={}
def symbol(r):
    if r in rowmap:return rowmap[r]
    key=rowkey(o,r);choices=n.symbols[key]
    if len(choices)==1:rowmap[r]=choices[0];return choices[0]
    proven=set()
    for p in o.tables[r]['refs']:
        try:q=address(p)
        except (AssertionError,KeyError):continue
        if q in n.refs and rowkey(n,n.refs[q])==key:proven.add(n.refs[q])
    assert len(proven)==1,('Ambiguous symbol',key,len(choices),len(proven))
    rowmap[r]=proven.pop();return rowmap[r]

def assets(e,tag):
    p=e.C[tag]['data'];rows=[]
    for i in range(e.u(p)):
        q=e.u(p+4+i*4);rows.append((e.SP[e.u(q)],q))
    return rows
asset_maps={}
for kind,tag in [(0,'OBJT'),(1,'SPRT'),(2,'SOND'),(3,'ROOM'),(5,'SCPT'),(6,'SHDR'),(7,'FONT')]:
    aa=assets(o,tag);bb=assets(n,tag);byname={name:i for i,(name,_) in enumerate(bb)}
    asset_maps[kind]={i:byname[name] for i,(name,_) in enumerate(aa) if name in byname}
def asset(value):
    kind=value>>24;idx=value&0xffffff
    assert kind in asset_maps and idx in asset_maps[kind],('Unknown resource',hex(value))
    return(kind<<24)|asset_maps[kind][idx]

ordered=sorted(set(n.strp));limits={p:ordered[i+1] if i+1<len(ordered) else n.C['STRG']['data']+n.C['STRG']['length'] for i,p in enumerate(ordered)}
stringchanges=[]
for item in inv['string_changes']:
    sid=item['beta_sid'];assert sid is not None and n.S[sid]==item['original']
    target=item['target']
    if item['old_sid']==5728:
        assert 'UNKNOWNTIMER' in target
        target=target.replace('1.5.2b','1.5.3 beta').replace('25669267','25749411')
    raw=target.encode('utf8');p=n.strp[sid]
    assert len(raw)+5<=limits[p]-p,('String capacity',sid,target)
    patch(p,pu(len(raw))+raw+b'\0'*(limits[p]-p-4-len(raw)),'Relocated localization STRG '+str(sid))
    stringchanges.append({'sid':sid,'original':item['original'],'target':target})

# Identify physical instruction regions with actual localization changes,
# ignoring the reference-chain distances rebuilt later.
physical=[]
for name,c in o.codes.items():
    start,end=c['begin'],c['end'];changed=False
    for p in range(start,end,4):
        if o.b[p:p+4]==f.b[p:p+4]:continue
        if p-4 in o.refs and p-4 in f.refs and rowkey(o,o.refs[p-4])==rowkey(f,f.refs[p-4]):
            if o.u(p)&0xf8000000==f.u(p)&0xf8000000:continue
        changed=True;break
    if changed:
        d=n.codes[name]
        assert end-start==d['end']-d['begin'],('Beta changed patched code size',name)
        a=o.instructions(name);nn=n.instructions(name)
        assert len(a)==len(nn) and all(x['size']==y['size'] for x,y in zip(a,nn)),('Instruction alignment differs',name)
        # All beta differences here must be encoded resource IDs/VM bookkeeping.
        for x,y in zip(a,nn):
            if x['token']==y['token']:continue
            assert x['word']==y['word'] and x['size']==8 and x['p'] not in o.refs and y['p'] not in n.refs and x['t']==2,('New gameplay change conflicts with localization',name,x,y)
        physical.append((start,end,name))

origins={x['p']:x for _,_,name in physical for x in o.instructions(name)}
new_origins={x['p']:y for _,_,name in physical for x,y in zip(o.instructions(name),n.instructions(name))}
operand_maps=collections.defaultdict(dict)
for p,x in origins.items():
    y=new_origins[p]
    if x['size']==8 and x['p'] not in o.refs and x['t']==2 and x['word']==y['word']:
        owner=o.owner(p)['name'];value=o.u(p+4);other=n.u(y['p']+4)
        if value in operand_maps[owner]:assert operand_maps[owner][value]==other
        operand_maps[owner][value]=other

regions=[]
for start,end,name in sorted(physical):
    if regions and start==regions[-1][1]:regions[-1]=(regions[-1][0],end)
    else:regions.append((start,end))
def selected(p):return any(a<=p<z for a,z in regions)
new_regions=[(address(a),address(z-1)+1) for a,z in regions]
intended={p:r for p,r in n.refs.items() if not any(a<=p<z for a,z in new_regions)}
flags={p:n.u(p+4)&0xf8000000 for p in intended}
for a,z in regions:
    assert address(z-1)-address(a)==z-a-1
    patch(address(a),f.b[a:z],'Copy bounded localization VM region with beta-relative fixups')

visited=set();relocated=[]
for name,c in f.codes.items():
    for x in f.instructions(name):
        p=x['p']
        if p in visited or not selected(p):continue
        visited.add(p);q=address(p);old=origins.get(p)
        unchanged=old is not None and x['word']==old['word'] and x['size']==old['size'] and f.b[p:p+x['size']]==o.b[p:p+x['size']]
        # Preserve beta's resource IDs and compiler bookkeeping at unchanged sites.
        if unchanged:
            y=new_origins[p];patch(q,n.b[y['p']:y['p']+y['size']],'Preserve beta operand at unchanged instruction')
        if p in f.refs:
            nr=symbol(f.refs[p]);intended[q]=nr;flags[q]=f.u(p+4)&0xf8000000
        elif x['t']==6 and x['op'] in {192,193,194,195,132}:
            patch(q+4,pu(sidmap[f.u(p+4)]),'Map VM literal to beta STRG ID')
        elif x['op'] in {182,183,184,186,187}:
            # Preserve exceptional POPENV controls; only real relative addresses relocate.
            if x['word']&0x00ffffff==0xf00000:continue
            target=address(x['arg']);delta=(target-q)//4
            assert (target-q)%4==0 and -0x400000<=delta<0x400000
            patch(q,pu((x['word']&0xff000000)|(delta&0x7fffff)),'Relocate VM branch')
        elif not unchanged and x['size']==8 and x['t']==2:
            value=f.u(p+4)
            if x['op']==255 and x['word']&65535==0xfff5:
                patch(q+4,pu(asset(value)),'Map typed asset reference by resource name')
            elif x['op'] in {192,193,194,195}:
                # A copied array-owner marker may move within its original event.
                owner=o.owner(p)['name'];mapping=operand_maps[owner]
                if value in mapping:patch(q+4,pu(mapping[value]),'Map beta compiler bookkeeping marker')
        relocated.append({'old_address':p,'beta_address':q,'opcode':x['op']})

# Relocated events keep their names/flags but receive beta start/size/entry metadata.
metadata=[]
for name,c in o.codes.items():
    target=f.codes[name]
    if all(c[k]==target[k] for k in ['start','size','offset']):continue
    d=n.codes[name];start=address(target['start']);begin=address(target['begin']);end=address(target['start']+target['size']-1)+1
    patch(d['record']+4,pu(end-start),'Relocated CODE size for '+name)
    patch(d['record']+12,pu(start-d['record']-12),'Relocated CODE start for '+name)
    patch(d['record']+16,pu(begin-start),'Relocated CODE entry for '+name)
    metadata.append({'name':name,'begin':begin,'start':start,'size':end-start})

# All changed TPAGs are blank charge-frame substitutions, by sprite names.
osprites=assets(o,'SPRT');nsprites=assets(n,'SPRT');ns={name:r for name,r in nsprites}
blank_name=osprites[3245][0];blank_page=n.u(ns[blank_name]+88);blank=struct.unpack_from('<11H',n.b,blank_page)
spritechanges=[]
for name,r in osprites:
    nr=ns[name];frames=o.u(r+84)
    assert frames==n.u(nr+84),(name,'frame count')
    for j in range(frames):
        op=o.u(r+88+j*4);fp=f.u(r+88+j*4);np=n.u(nr+88+j*4)
        if op!=fp:
            assert fp==o.u(osprites[3245][1]+88)
            patch(nr+88+j*4,pu(blank_page),'Remove baked Warp lettering from '+name)
            spritechanges.append(name)
        before=o.b[op:op+22];after=f.b[op:op+22]
        if before!=after:
            v=struct.unpack('<11H',after)
            oldblank=struct.unpack_from('<11H',o.b,o.u(osprites[3245][1]+88))
            assert v[:4]==oldblank[:4] and v[10]==oldblank[10]
            patch(np,struct.pack('<11H',*blank[:4],*v[4:10],blank[10]),'Remove baked caption from '+name)
            spritechanges.append(name)

chains={r:[] for r in n.tables}
for p,r in intended.items():chains[r].append(p)
for r,t in n.tables.items():
    sites=sorted(chains[r]);patch(t['countp'],pu(len(sites)),'Rebuild beta symbol count '+t['name'])
    patch(t['firstp'],pu((sites[0]+(4 if t['kind']=='function' else 0)) if sites else 0xffffffff),'Rebuild beta symbol head '+t['name'])
    for i,p in enumerate(sites):
        step=sites[i+1]-p if i+1<len(sites) else t['terminal']
        assert 0<=step<0x8000000
        patch(p+4,pu(flags[p]|step),'Rebuild beta symbol chain '+t['name'])

dest=A.output;dest.write_bytes(b)
check=Engine(dest)
assert check.C==n.C and check.strp==n.strp and len(b)==len(n.b)
assert check.refs==intended
for name,c in check.codes.items():check.instructions(name)
report={'status':'PASS_PORT','input_sha256':hashlib.sha256(n.b).hexdigest(),'output_sha256':hashlib.sha256(b).hexdigest(),
        'strings':len(stringchanges),'physical_code_regions':len(regions),'patched_original_code_segments':len(physical),
        'relocated_instructions':len(relocated),'references':len(intended),'container_size_unchanged':True,
        'beta_original_assets_and_gameplay_preserved':True,'code_metadata':metadata,'sprites':sorted(set(spritechanges)),
        'string_changes':stringchanges,'patches':patches}
(A.audit_dir/'ported_engine.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
print(json.dumps({k:v for k,v in report.items() if k not in ['patches','string_changes','code_metadata','sprites']},ensure_ascii=False))
