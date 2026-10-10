"""Independent execution of the assembled helper, using actual VM words/refs.

This catches operand ordering, branches, argument counts, cache lifetime and
stack balance before the separate real-game screenshots/performance tests.
"""
from pathlib import Path
import argparse,collections,json,math,struct
from gm import Engine
R=Path(__file__).parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data',type=Path,default=R/'package/data.win')
parser.add_argument('--report',type=Path,default=R/'audit/layout_vm_tests.json')
cli_options=parser.parse_args();e=Engine(cli_options.data)
name='gml_Script_crewDebug_draw_crew_info';start=e.codes[name]['begin']
class VM:
    def __init__(self):
        self.globals={'fnt_notoSerifSC':40,'fnt_notoSerifSC_2x':43,'font_bodyText_sm2':40,'lineSep_duBellay':18,'currLanguage':3}
        self.maps={};self.mid=0;self.font=40;self.native=True;self.calls=collections.Counter();self.draws=[]
        self.advance={}
        for fid in [40,43]:
            p=e.u(e.C['FONT']['data']+4+fid*4)
            self.advance[fid]={}
            for i in range(e.u(p+56)):
                q=e.u(p+60+i*4);c,x,y,w,h,advance,left,kern=struct.unpack_from('<8H',e.b,q)
                # The runner loads 12pt/24pt OTF fonts with font_add. Embedded
                # CJK fonts use a compact, shared texture and scale=4, so raw
                # bitmap advances alone are not dynamic-font pixel widths.
                self.advance[fid][chr(c)]=advance*(4 if fid==40 else 8)
    def width(self,s):return max((sum(self.advance[self.font].get(c,0) for c in line) for line in s.split('\n')),default=0)
    def call(self,n,args):
        self.calls[n]+=1
        if n==name:return self.run(args)
        if n=='string':return str(args[0]) if isinstance(args[0],str) else ('1' if args[0] is True else '0' if args[0] is False else f'{args[0]:g}')
        if n=='gml_Script_window_is_nativeRes':return self.native
        if n=='variable_global_exists':return args[0] in self.globals
        if n=='variable_global_get':return self.globals[args[0]]
        if n=='variable_global_set':self.globals[args[0]]=args[1];return 0
        if n=='ds_map_create':self.mid+=1;self.maps[self.mid]={};return self.mid
        if n=='ds_map_destroy':del self.maps[args[0]];return 0
        if n=='ds_map_exists':return args[1] in self.maps[args[0]]
        if n=='ds_map_find_value':return self.maps[args[0]][args[1]]
        if n=='ds_map_add':
            assert args[1] not in self.maps[args[0]],'Duplicate key; key or cache logic is wrong'
            self.maps[args[0]][args[1]]=args[2];return 0
        if n=='draw_set_font':self.font=args[0];return 0
        if n in ['draw_set_halign','draw_set_valign']:return 0
        if n=='string_length':return len(args[0])
        if n=='string_char_at':return args[0][int(args[1])-1]
        if n=='string_pos':return args[1].find(args[0])+1
        if n=='string_width':return self.width(args[0])
        if n=='round':return math.floor(args[0]+.5)
        if n=='gml_Script_font_get_HD':return 43 if args[0]==40 else args[0]
        if n in ['string_width_ext','string_height_ext']:
            lines=args[0].split('\n')
            return max(map(self.width,lines),default=0) if 'width' in n else (18 if self.font==40 else 36)+(len(lines)-1)*args[1]
        if n=='gml_Script_scrTruncateString':
            s,w=args
            if self.width(s)<=w:return s
            while s and self.width(s+'...')>w:s=s[:-1]
            return s+'...'
        if n in ['draw_text_transformed_color','gml_Script_draw_mini_text']:
            self.draws.append((n,args));return 0
        raise AssertionError((n,args))
    def run(self,args):
        args=list(args);stack=[];local={};p=start;steps=0
        while True:
            steps+=1;assert steps<1000000,'Infinite loop'
            w=e.u(p);op=w>>24;t=(w>>16)&15;nextp=p+4
            if op in [192,193,194,195,132]:
                if p in e.refs:
                    r=e.tables[e.refs[p]];n=r['name'];inst=(w&65535)-65536 if w&32768 else w&65535
                    if n=='argument_count':v=len(args)
                    elif inst==-15:v=args[int(n.removeprefix('argument'))]
                    elif inst==-5:v=self.globals[n]
                    elif inst==-7:v=local[n]
                    else:raise AssertionError((p,n,inst))
                    nextp=p+8
                elif t==15:v=(w&65535)-65536 if w&32768 else w&65535
                elif t==2:v=e.i(p+4);nextp=p+8
                elif t==6:v=e.S[e.u(p+4)];nextp=p+8
                elif t==0:v=struct.unpack_from('<d',e.b,p+4)[0];nextp=p+12
                else:raise AssertionError((op,t,p))
                stack.append(v)
            elif op==7:assert stack
            elif op==69:
                n=e.tables[e.refs[p]]['name'];inst=(w&65535)-65536 if w&32768 else w&65535;v=stack.pop()
                if inst==-15:args[int(n.removeprefix('argument'))]=v
                elif inst==-7:local[n]=v
                else:raise AssertionError((n,inst))
                nextp=p+8
            elif op==217:
                n=e.tables[e.refs[p]]['name'];argv=[stack.pop() for _ in range(w&65535)]
                stack.append(self.call(n,argv));nextp=p+8
            elif op==158:stack.pop()
            elif op in [8,9,12,13,21]:
                right=stack.pop();left=stack.pop()
                if op==8:v=left*right
                elif op==9:v=left/right
                elif op==12:v=left+right
                elif op==13:v=left-right
                else:v={1:lambda:left<right,2:lambda:left<=right,3:lambda:left==right,4:lambda:left!=right,5:lambda:left>=right,6:lambda:left>right}[(w>>8)&255]()
                stack.append(v)
            elif op in [182,183,184]:
                take=True if op==182 else bool(stack.pop())==(op==183)
                delta=w&0x7fffff;delta=delta-0x800000 if delta&0x400000 else delta
                if take:nextp=p+delta*4
            elif op==156:
                v=stack.pop();assert not stack,('Unbalanced return',p,stack);return v
            elif op==157:assert not stack,('Unbalanced exit',p,stack);return None
            else:raise AssertionError((hex(p),hex(w)))
            p=nextp

vm=VM();cases=0
for text,width,font in [('发动机可以提高闪避率。',60,40),('传感器\n显示敌方状态\n\n能量：1',78,40),('',80,40),('abcdef超长词语'+('测试'*100),96,40),('公告\n'+('测试 '*200),100,43),('测试',1,40)]:
    vm.font=font;wrapped=vm.run([text,width,'\n',1,font]);cases+=1
    assert wrapped.replace('\n','')==text.replace('\n','')
    assert all(vm.width(line)<=width or len(line)==1 for line in wrapped.split('\n'))
    hits=vm.calls['string_width'];assert vm.run([text,width,'\n',1,font])==wrapped;assert vm.calls['string_width']==hits;cases+=1
    assert wrapped.count('\n')>=text.count('\n')
for native in [True,False,True]:
    vm.native=native
    h=vm.run(['测试\n测试',0,100,40,0,0]);w=vm.run(['测试\n测试',0,100,40,1,0]);cases+=2
    assert h==36 and w==32,(h,w,native)
    before=vm.calls['string_height_ext'];assert vm.run(['测试\n测试',0,100,40,0,0])==h
    assert vm.calls['string_height_ext']==before;cases+=1
vm.font=40
for txt in ['中文测试。更多文本，后续内容！','（测试内容）测试完毕。','中文测试？中文说明；']:
    wrapped=vm.run([txt,60,'\n',1,40]);cases+=1
    assert wrapped.replace('\n','')==txt
    assert all(not line.startswith(('，','。','！','？','；','）')) for line in wrapped.split('\n') if line)
    assert all(vm.width(line)<=60 for line in wrapped.split('\n'))
for i in range(520):vm.font=40;vm.run(['船员 '+str(i),80,'\n',1,40])
assert len(vm.maps)==1 and max(map(len,vm.maps.values()))<=256;cases+=1
vm.native=True;vm.font=40;strn=vm.run(['船员姓名测试',30]);vm.run([20,26,strn,0,999,0xffffff,0,1]);cases+=1
draw,args=vm.draws[-1];assert draw=='draw_text_transformed_color' and args[0:2]==[20,23] and args[3:6]==[.65,.65,0]
assert vm.width(strn)*.65<=30
vm.globals['currLanguage']=0;vm.run([20,26,'English',0,999,0xffffff,0,1]);assert vm.draws[-1][0]=='gml_Script_draw_mini_text';cases+=1
assert vm.run([0]) is None;cases+=1
report={'status':'PASS','cases':cases,'actual_bytecode_executed':True,'width_model':'Size-scaled embedded advances; real OTF rasterization is tested in-game.',
        'cache_hit_avoids_character_measurement':True,'newline_preservation':True,
        'cache_lifetime_and_resolution_keys':True,'stack_balance_all_returns':True,
        'limitation':'A VM model is not the GameMaker runner; separate real-game testing remains required.'}
cli_options.report.parent.mkdir(parents=True,exist_ok=True)
cli_options.report.write_text(json.dumps(report,indent=2),'utf8');print(json.dumps(report))
