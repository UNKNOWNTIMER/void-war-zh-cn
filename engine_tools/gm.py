"""Read-only structural GameMaker VM parser plus a bounded relocation model."""
from pathlib import Path
import bisect, collections, json, struct

OP={7:'conv',8:'mul',9:'div',10:'rem',11:'mod',12:'add',13:'sub',14:'and',15:'or',16:'xor',17:'neg',18:'not',19:'shl',20:'shr',21:'cmp',69:'pop',134:'dup',156:'ret',157:'exit',158:'popz',182:'b',183:'bt',184:'bf',186:'pushenv',187:'popenv',192:'push',193:'pushloc',194:'pushglb',195:'pushbltn',132:'pushi',217:'call',153:'callv',255:'break'}
class Engine:
    def __init__(self,path):
        self.path=Path(path);self.b=self.path.read_bytes();self.C={};p=8
        assert self.b[:4]==b'FORM' and self.u(4)+8==len(self.b)
        while p<len(self.b):
            tag=self.b[p:p+4].decode('ascii');n=self.u(p+4)
            self.C[tag]={'offset':p,'data':p+8,'length':n};p+=n+8
        assert p==len(self.b)
        p=self.C['STRG']['data'];self.strp=[self.u(p+4+i*4) for i in range(self.u(p))]
        self.S=[self.b[q+4:q+4+self.u(q)].decode('utf8') for q in self.strp]
        self.SP={q+4:s for q,s in zip(self.strp,self.S)}
        self.tables={};self.refs={}
        def add(record,kind,name,instance,countp,firstp):
            count=self.u(countp);q=self.u(firstp)-(4 if kind=='function' else 0);sites=[]
            for _ in range(count):
                assert self.C['CODE']['data']<=q<self.C['CODE']['data']+self.C['CODE']['length']-4
                assert q not in self.refs
                sites.append(q);self.refs[q]=record;q+=self.u(q+4)&0x07ffffff
            self.tables[record]={'kind':kind,'name':name,'instance':instance,'countp':countp,'firstp':firstp,
                                 'refs':sites,'terminal':self.u(sites[-1]+4)&0x07ffffff if sites else 0}
        p=self.C['VARI']['data']+12
        while p+20<=self.C['VARI']['data']+self.C['VARI']['length'] and self.u(p) in self.SP:
            add(p,'variable',self.SP[self.u(p)],self.i(p+4),p+12,p+16);p+=20
        p=self.C['FUNC']['data']
        for i in range(self.u(p)):
            q=p+4+i*12;add(q,'function',self.SP[self.u(q)],None,q+4,q+8)
        self.symbols=collections.defaultdict(list)
        for k,r in self.tables.items():self.symbols[(r['kind'],r['name'],r['instance'])].append(k)
        p=self.C['CODE']['data'];self.codes={};groups=collections.defaultdict(list)
        for i in range(self.u(p)):
            q=self.u(p+4+i*4);name=self.SP[self.u(q)];start=q+12+self.i(q+12)
            code={'name':name,'record':q,'start':start,'offset':self.u(q+16),'size':self.u(q+4)}
            assert name not in self.codes
            self.codes[name]=code;groups[start].append(code)
        for start,group in groups.items():
            offsets=sorted(set(c['offset'] for c in group));size=max(c['size'] for c in group)
            for c in group:
                i=offsets.index(c['offset']);c['begin']=start+c['offset'];c['end']=start+(offsets[i+1] if i+1<len(offsets) else size)
        self.intervals=sorted((c['begin'],c['end'],name) for name,c in self.codes.items())
        self.starts=[v[0] for v in self.intervals]

    def u(self,p):return struct.unpack_from('<I',self.b,p)[0]
    def i(self,p):return struct.unpack_from('<i',self.b,p)[0]
    def owner(self,p):
        q=bisect.bisect_right(self.starts,p)-1
        begin,end,name=self.intervals[q];assert begin<=p<end,(p,begin,end)
        return self.codes[name]
    def instructions(self,name):
        c=self.codes[name];p=c['begin'];out=[]
        while p<c['end']:
            w=self.u(p);op=w>>24;t=(w>>16)&15;sz=4;arg=None;token=(w,)
            if op in {192,193,194,195,132}:
                if t in {0,3}:sz=12;arg=struct.unpack_from('<d' if t==0 else '<q',self.b,p+4)[0];token=(w,self.b[p+4:p+12])
                elif t in {2,5,6}:
                    sz=8;arg=self.i(p+4)
                    if t==6:arg=self.S[self.u(p+4)];token=(w,'STRG',arg)
                    elif p in self.refs:
                        r=self.tables[self.refs[p]];arg=r['name'];token=(w,r['kind'],r['name'],r['instance'])
                    else:token=(w,self.u(p+4))
                elif t==15:arg=(w&65535)-65536 if w&32768 else w&65535
            elif op==69 and t!=15 or op==217 or op==255 and t==2:
                sz=8
                if p in self.refs:
                    r=self.tables[self.refs[p]];arg=r['name'];token=(w,r['kind'],r['name'],r['instance'])
                else:arg=self.i(p+4);token=(w,self.u(p+4))
            elif op in {182,183,184,186,187}:
                delta=w&0x7fffff
                if delta&0x400000:delta-=0x800000
                arg=p+delta*4;token=(op,)
            out.append({'p':p,'word':w,'op':op,'t':t,'size':sz,'arg':arg,'token':token})
            p+=sz
        assert p==c['end'],(name,hex(p),hex(c['end']))
        return out
    def dis(self,name):
        rows=[]
        for a in self.instructions(name):
            word=a['word'];arg=a['arg'];op=a['op']
            if op==21:arg={1:'LT',2:'LTE',3:'EQ',4:'NEQ',5:'GTE',6:'GT'}.get((word>>8)&255,'?')
            if isinstance(arg,str):arg=json.dumps(arg,ensure_ascii=False)
            if op in {182,183,184,186,187}:arg=hex(arg)
            rows.append(f"{a['p']:08x} {OP.get(op,hex(op))}.{a['t']} {'' if arg is None else arg}")
        return '\n'.join(rows)

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--data',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);ap.add_argument('patterns',nargs='+');a=ap.parse_args()
    e=Engine(a.data);result={n:e.dis(n) for n in e.codes if any(s in n for s in a.patterns)}
    a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'codes':len(result),'report':str(a.out)},ensure_ascii=False))
