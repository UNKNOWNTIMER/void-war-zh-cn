"""Apply reviewed Chinese random gossip and fix the beta's missing-table fallback.

Only the hash-bound staged resource is written. Never touches the installed game.
No original English dialogue is distributed with this tool.
"""
from pathlib import Path
import argparse, collections, hashlib, json, re, struct
from gm import Engine

ROOT=Path(__file__).resolve().parent
LAYOUT_SHA='8c3e88e79881fb9430717c7262308b35fd3842f9b0e1e7123b559beb8a97bf4d'
POOLS={'generic':33,'TECHNO':51,'BLOOD':44,'WAR':28}
METHOD='gml_Script_anon_gml_Object_oTxtMerchantGossip_Create_0_2422_gml_Object_oTxtMerchantGossip_Create_0'

def apply(path, translations, report):
    e=Engine(path);before=hashlib.sha256(e.b).hexdigest()
    assert before==LAYOUT_SHA,'Input is not the supported layout stage; no write'
    values=json.loads(translations.read_text('utf8'))
    expected=set();counts={}
    for suffix,count in POOLS.items():
        ids=[e.u(x['p']+4) for x in e.instructions('gml_Script_scrMerchantGossipPool_'+suffix)
             if x['op']==192 and x['t']==6]
        assert len(ids)==count and len(set(ids))==count,(suffix,len(ids))
        counts[suffix]=len(ids);expected.update(map(str,ids))
    assert set(values)==expected and len(values)==156,'Missing or extra reviewed pool entry'
    b=bytearray(e.b)
    for sid,text in values.items():
        i=int(sid);p=e.strp[i];end=e.strp[i+1];raw=text.encode('utf8')
        assert p<end and len(raw)+5<=end-p,('Translation exceeds its original record',sid)
        assert text.strip() and re.search('[\u3400-\u9fff]',text)
        assert not re.search(r'[A-Za-z]{3,}',text),('Unexpected English prose',sid)
        # Preserve all other resource offsets and the original randomized pool.
        b[p:end]=struct.pack('<I',len(raw))+raw+b'\0'*(end-p-4-len(raw))
    # The original beta already resolves dynamic tags for English fallback.
    # Direct the false branch to that same fallback for missing localization in
    # other languages, rather than displaying an ERROR sentence. The conditional
    # still consumes its boolean, so the VM stack and all reference chains remain.
    branch=next(x for x in e.instructions(METHOD) if x['p']==0x9d4798)
    assert branch['op']==184 and branch['arg']==0x9d47cc and branch['size']==4
    struct.pack_into('<I',b,branch['p'],0xb8000001)
    assert len(b)==len(e.b)
    path.write_bytes(b);v=Engine(path)
    assert v.refs==e.refs and v.C==e.C
    assert all(v.S[int(i)]==s for i,s in values.items())
    ins=v.instructions(METHOD)
    assert next(x['arg'] for x in ins if x['p']==branch['p'])==branch['p']+4
    result={'status':'PASS','input_sha256':before,'output_sha256':hashlib.sha256(b).hexdigest(),
            'reviewed_dialogues':len(values),'pools':counts,'gameplay_pool_order_and_weights_preserved':True,
            'reference_chains_preserved':True,'resource_offsets_preserved':True,
            'fallback':'Resolve the existing random line and its dynamic tags when a localization table lacks that entry',
            'english_prose_remaining_in_active_pools':0}
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,default=ROOT/'package/data.win')
    p.add_argument('--translations',type=Path,default=ROOT/'gossip_zh.json')
    p.add_argument('--report',type=Path,default=ROOT/'audit/gossip_patch.json')
    a=p.parse_args();apply(a.data,a.translations,a.report)
