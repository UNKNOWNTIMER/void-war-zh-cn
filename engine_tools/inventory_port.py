"""Inventory the semantic port before altering the beta resource copy."""
from pathlib import Path
import collections,difflib,hashlib,json,sys
from gm import Engine
from engine_paths import inputs
A=inputs()
old=Engine(A.stable_original);final=Engine(A.stable_target);beta=Engine(A.beta_original)
sm=difflib.SequenceMatcher(None,old.S,beta.S,autojunk=False)
sidmap={a+i:b+i for a,b,n in sm.get_matching_blocks() for i in range(n)}
str_changes=[]
for sid,(before,after) in enumerate(zip(old.S,final.S)):
    if before==after:continue
    to=sidmap.get(sid)
    str_changes.append({'old_sid':sid,'beta_sid':to,'original':before,'target':after})
def compare(ins,e):
    if ins['t']==6 and ins['op'] in {192,193,194,195,132}:return(ins['word'],'STRG',e.u(ins['p']+4))
    if ins['op'] in {182,183,184,186,187}:return(ins['word'],)
    return ins['token']
modified=[];conflicts=[]
for name,c in old.codes.items():
    a=old.instructions(name);f=final.instructions(name)
    if [compare(x,old) for x in a]==[compare(x,final) for x in f]:continue
    if name not in beta.codes:
        conflicts.append({'name':name,'reason':'code name absent'});continue
    n=beta.instructions(name)
    same=len(a)==len(n) and all(x['token']==y['token'] for x,y in zip(a,n))
    record={'name':name,'old_bytes':c['end']-c['begin'],'beta_bytes':beta.codes[name]['end']-beta.codes[name]['begin'],
            'old_instructions':len(a),'beta_instructions':len(n),'source_semantics_equal':same}
    modified.append(record)
    if not same:
        opcodes=difflib.SequenceMatcher(None,[x['token'] for x in a],[x['token'] for x in n],autojunk=False).get_opcodes()
        record['deltas']=[{'type':tag,'old':[(hex(x['p']),x['arg']) for x in a[i:j]],
                          'beta':[(hex(x['p']),x['arg']) for x in n[k:l]]} for tag,i,j,k,l in opcodes if tag!='equal']
        conflicts.append(record)
counts={tag:sum(x!=y for x,y in zip(old.b[c['data']:c['data']+c['length']],final.b[c['data']:c['data']+c['length']])) for tag,c in old.C.items()}
report={'old_sha256':hashlib.sha256(old.b).hexdigest(),'final_old_sha256':hashlib.sha256(final.b).hexdigest(),
        'beta_original_sha256':hashlib.sha256(beta.b).hexdigest(),'changed_bytes_by_chunk':counts,
        'string_changes':str_changes,'unmapped_changed_strings':[x for x in str_changes if x['beta_sid'] is None],
        'sid_map':sidmap,'modified_code':modified,'conflicts':conflicts}
(A.audit_dir/'port_inventory.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
sys.stdout.reconfigure(encoding='utf8')
print(json.dumps({'changed_chunks':{k:v for k,v in counts.items() if v},'changed_strings':len(str_changes),
                  'unmapped_strings':report['unmapped_changed_strings'],'modified_codes':len(modified),'conflicts':conflicts},ensure_ascii=False))
