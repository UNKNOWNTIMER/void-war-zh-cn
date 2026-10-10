"""Bounded 1.5.3 beta rendering corrections. Never writes to the installed game."""
from pathlib import Path
import argparse, collections, hashlib, json, struct
from gm import Engine

ROOT = Path(__file__).parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data',type=Path,default=ROOT/'package/data.win')
parser.add_argument('--report',type=Path,default=ROOT/'audit/layout_patch.json')
args=parser.parse_args();PATH=args.data
e = Engine(PATH)
assert hashlib.sha256(e.b).hexdigest() == 'e0519365fe7fa63fe22ff751c31f3fe018db4b6e396e5d9d12b38d6b0d1bbbea'
b = bytearray(e.b); refs = e.refs.copy()
flags = {p:e.u(p+4)&0xf8000000 for p in refs}
changes=[]; programs=[]
HELPER = 'gml_Script_crewDebug_draw_crew_info'
hc=e.codes[HELPER]
local_ids={e.tables[r]['name']:r for p,r in refs.items() if hc['begin']<=p<hc['end'] and e.tables[r]['instance']==-7}

def patch(p,v,reason):
    if b[p:p+len(v)]==v:return
    b[p:p+len(v)]=v;changes.append({'offset':p,'length':len(v),'reason':reason})

def rid(name,kind='variable',instance=-6):
    ks=e.symbols[(kind,name,instance)]
    if instance==-7 and name in local_ids:return local_ids[name]
    assert ks,(kind,name,instance)
    assert len({e.u(k+8) for k in ks})==1 or kind=='function',(name,ks)
    return ks[0]

class Asm:
    def __init__(self,start):self.start=start;self.v=bytearray();self.refs={};self.ref_flags={};self.labels={};self.fix=[]
    @property
    def pos(self):return self.start+len(self.v)
    def word(self,w):self.v+=struct.pack('<I',w)
    def reference(self,w,name,kind='variable',instance=-6):
        p=self.pos;self.word(w);self.word(0xa0000000 if kind=='variable' else 0)
        self.refs[p]=rid(name,kind,instance)
    def var(self,name,instance=-15):
        inst=-6 if instance==-15 else instance
        op={-5:0xc2,-7:0xc1}.get(instance,0xc0)
        if name in ['argument_count','room_height','room_width']:op=0xc3;inst=-1;instance=-1
        self.reference((op<<24)|0x050000|(instance&65535),name,instance=inst)
    def put(self,name,instance=-7):
        self.reference(0x45550000|(instance&65535),name,instance=-6 if instance==-15 else instance)
    def arg(self,i):self.var('argument'+str(i))
    def setarg(self,i):self.put('argument'+str(i),-15)
    def int(self,n):
        if -32768<=n<=32767:self.word(0x840f0000|(n&65535))
        else:self.word(0xc0020000);self.word(n)
        self.word(0x07520000)
    def float(self,n):self.word(0xc0000000);self.v+=struct.pack('<d',n);self.word(0x07500000)
    def string(self,s):self.word(0xc0060000);self.word(e.S.index(s));self.word(0x07560000)
    def call(self,n,argc,discard=False):
        self.reference(0xd9020000|argc,n,'function',None)
        if discard:self.word(0x9e050000)
    def binary(self,op):self.word((op<<24)|0x550000)
    def truth(self):self.word(0x07450000)
    def cmp(self,kind):self.word(0x15550000|(kind<<8))
    def label(self,n):assert n not in self.labels;self.labels[n]=self.pos
    def branch(self,n,op=0xb6):self.fix.append((len(self.v),n,op));self.word(0)
    def ret(self):self.word(0x9c050000)
    def exit(self):self.word(0x9d020000)
    def finish(self):
        for i,n,op in self.fix:
            t=self.labels[n] if isinstance(n,str) else n
            assert (t-self.start-i)%4==0
            struct.pack_into('<I',self.v,i,(op<<24)|(((t-self.start-i)//4)&0x7fffff))
        return bytes(self.v)
    def install(self,end,reason):
        v=self.finish();assert len(v)<=end-self.start,(reason,len(v),end-self.start)
        programs.append({'begin':self.start,'used':len(v),'end':end,'labels':self.labels,'reason':reason})
        v+=struct.pack('<I',0xb6000001)*((end-self.start-len(v))//4)
        for p in list(refs):
            if self.start<=p<end:refs.pop(p);flags.pop(p)
        for p,r in self.refs.items():
            refs[p]=r
            flags[p]=self.ref_flags.get(p,0xa0000000 if e.tables[r]['kind']=='variable' else 0)
        patch(self.start,v,reason)

# Two former development-only display literals become private, bounded cache keys.
for old,new in [('\nenemyCrew_last_one_alive: ','VW153Cache'),('\ntargetDPSReduction: ','VW153Count'),
                ('\npoisonDamageQueue: ','，。！？；）')]:
    sid=e.S.index(old);p=e.strp[sid];raw=new.encode();cap=e.u(p)
    assert len(raw)<=cap
    patch(p,struct.pack('<I',len(raw))+raw+b'\0'*(cap+1-len(raw)),'Private layout cache key in retired optional debug literal')
    e.S[sid]=new

# These dynamically assembled system bonuses bypass the ordinary language CSV.
# Keep the beta string pointers and use only the padding within their allocation.
system_literals={
    '% Evasion':'%闪避率','no Evasion bonus':'无闪避加成',
    '+{0}% Evasion':'+{0}%闪避率',
    'Door Reinforcement 1':'舱门加固 1','Door Reinforcement 2':'舱门加固 2',
    '+1 Door Reinforcement':'+1 舱门加固','+2 Door Reinforcement':'+2 舱门加固',
    '% charge speed':'%充能速度','+15% charge speed':'+15%充能速度',
    '+30% charge speed':'+30%充能速度',
    'Sensor Strength 1':'感测强度 1','Sensor Strength 2':'感测强度 2',
    'Sensor Strength 3':'感测强度 3','Sensor Strength 4':'感测强度 4',
    '+1 Sensor Level':'+1 感测等级','+2 Sensor Level':'+2 感测等级',
    '% recharge speed':'%充能速度','One shield barrier':'一层护盾',
    'Two shield barriers':'两层护盾','Three shield barriers':'三层护盾',
    'Four shield barriers':'四层护盾','Increased system power':'系统供能增加',
}
for old,new in system_literals.items():
    sid=e.S.index(old);p=e.strp[sid];nextp=e.strp[sid+1];raw=new.encode('utf8')
    assert nextp>p and len(raw)+5<=nextp-p,(old,new,nextp-p)
    patch(p,struct.pack('<I',len(raw))+raw+b'\0'*(nextp-p-4-len(raw)),
          'Translate a dynamically composed system bonus omitted by the language table')
    e.S[sid]=new

# Reuse the optional F3 crew diagnostic body and its original declared locals.
# Normal gameplay retains all state/movement/combat logic. Calls with 0/1 args exit.
# 2 args: portrait name truncation; 5: CJK wrapping; 6: measured dimensions; 8: portrait name drawing.
a=Asm(hc['begin'])
a.var('argument_count');a.int(2);a.cmp(3);a.branch('truncate',0xb7)
a.var('argument_count');a.int(8);a.cmp(3);a.branch('crew',0xb7)
a.var('argument_count');a.int(5);a.cmp(1);a.branch('debug_exit',0xb7)
a.var('argument_count');a.int(6);a.cmp(3);a.branch('normalize_measure',0xb7)
a.branch('cache')
a.label('normalize_measure')
for arg,default in [(1,'lineSep_duBellay'),(2,999999999)]:
    a.arg(arg);a.int(0);a.cmp(3);a.branch('measure_normalized_'+str(arg),0xb8)
    a.var(default,-5) if isinstance(default,str) else a.int(default)
    a.setarg(arg);a.label('measure_normalized_'+str(arg))
a.arg(3);a.call('draw_set_font',1,True)
a.label('cache')
a.string('VW153Cache');a.call('variable_global_exists',1);a.truth();a.branch('existing',0xb7)
a.call('ds_map_create',0);a.put('objIndex')
a.var('objIndex',-7);a.string('VW153Cache');a.call('variable_global_set',2,True)
a.int(0);a.string('VW153Count');a.call('variable_global_set',2,True);a.branch('key')
a.label('existing')
a.string('VW153Cache');a.call('variable_global_get',1);a.put('objIndex')
a.string('VW153Count');a.call('variable_global_get',1);a.int(255);a.cmp(5);a.branch('key',0xb8)
a.var('objIndex',-7);a.call('ds_map_destroy',1,True)
a.call('ds_map_create',0);a.put('objIndex')
a.var('objIndex',-7);a.string('VW153Cache');a.call('variable_global_set',2,True)
a.int(0);a.string('VW153Count');a.call('variable_global_set',2,True)
a.label('key')
a.var('argument_count');a.call('string',1)
a.call('gml_Script_window_is_nativeRes',0);a.call('string',1);a.binary(12)
for arg in [1,2,3,4]:
    a.string(',');a.binary(12);a.arg(arg);a.call('string',1);a.binary(12)
a.string(',');a.binary(12);a.arg(0);a.binary(12);a.put('str3')
a.var('str3',-7);a.var('objIndex',-7);a.call('ds_map_exists',2);a.truth();a.branch('miss',0xb8)
a.var('str3',-7);a.var('objIndex',-7);a.call('ds_map_find_value',2);a.ret()
a.label('miss')
a.var('argument_count');a.int(6);a.cmp(3);a.branch('measure',0xb7)
# Width measured once per character. Existing hard newlines reset the line.
# Append by line to avoid quadratic copying of the entire paragraph.
a.string('');a.put('str');a.string('');a.put('str1');a.int(0);a.put('xPos')
a.int(1);a.put('i');a.arg(0);a.call('string_length',1);a.put('xOff')
a.label('char_loop')
a.var('i',-7);a.var('xOff',-7);a.cmp(2);a.branch('wrap_end',0xb8)
a.var('i',-7);a.arg(0);a.call('string_char_at',2);a.put('str2')
a.var('str2',-7);a.string('\n');a.cmp(3);a.branch('hard_break',0xb7)
a.var('str2',-7);a.call('string_width',1);a.put('yPos')
a.var('xPos',-7);a.var('yPos',-7);a.binary(12);a.arg(1);a.cmp(6);a.branch('soft_break',0xb7)
# Keep common Chinese closing punctuation with the preceding character. Look
# ahead only at a line end; all text and explicit newlines remain unchanged.
a.var('i',-7);a.var('xOff',-7);a.cmp(1);a.branch('append',0xb8)
a.string('，。！？；）');a.var('i',-7);a.int(1);a.binary(12);a.arg(0)
a.call('string_char_at',2);a.call('string_pos',2);a.int(0);a.cmp(6);a.branch('append',0xb8)
a.var('i',-7);a.int(1);a.binary(12);a.arg(0);a.call('string_char_at',2);a.call('string_width',1)
a.var('xPos',-7);a.var('yPos',-7);a.binary(12);a.binary(12);a.arg(1);a.cmp(6);a.branch('append',0xb8)
a.label('soft_break')
a.var('str1',-7);a.string('');a.cmp(4);a.branch('append',0xb8)
a.var('str',-7);a.var('str1',-7);a.binary(12);a.arg(2);a.binary(12);a.put('str')
a.string('');a.put('str1');a.int(0);a.put('xPos')
a.label('append')
a.var('str1',-7);a.var('str2',-7);a.binary(12);a.put('str1')
a.var('xPos',-7);a.var('yPos',-7);a.binary(12);a.put('xPos');a.branch('next_char')
a.label('hard_break')
a.var('str',-7);a.var('str1',-7);a.binary(12);a.string('\n');a.binary(12);a.put('str')
a.string('');a.put('str1');a.int(0);a.put('xPos')
a.label('next_char');a.var('i',-7);a.int(1);a.binary(12);a.put('i');a.branch('char_loop')
a.label('wrap_end');a.var('str',-7);a.var('str1',-7);a.binary(12);a.put('str');a.branch('store')
a.label('measure')
a.arg(3);a.var('fnt_notoSerifSC',-5);a.cmp(3);a.branch('measure_wrap',0xb7)
a.arg(3);a.var('fnt_notoSerifSC_2x',-5);a.cmp(3);a.branch('measure_scale',0xb8)
a.label('measure_wrap')
a.arg(3);a.int(1);a.string('\n');a.arg(2);a.arg(0);a.call(HELPER,5);a.setarg(0)
a.label('measure_scale')
a.call('gml_Script_window_is_nativeRes',0);a.truth();a.branch('measure_builtin',0xb7)
a.arg(3);a.call('gml_Script_font_get_HD',1);a.call('draw_set_font',1,True)
a.arg(2);a.int(2);a.binary(8);a.int(5);a.binary(12);a.setarg(2)
a.arg(1);a.int(2);a.binary(8);a.setarg(1)
a.label('measure_builtin')
a.arg(2);a.arg(1);a.arg(0)
a.arg(4);a.int(1);a.cmp(3);a.branch('measure_width',0xb7)
a.call('string_height_ext',3);a.branch('measure_result')
a.label('measure_width');a.call('string_width_ext',3)
a.label('measure_result');a.put('str')
a.call('gml_Script_window_is_nativeRes',0);a.truth();a.branch('store',0xb7)
a.var('str',-7);a.int(2);a.binary(9);a.call('round',1);a.put('str')
a.label('store')
a.var('str',-7);a.var('str3',-7);a.var('objIndex',-7);a.call('ds_map_add',3,True)
# A nested measurement may have populated the same cache; increment the live count.
a.string('VW153Count');a.call('variable_global_get',1);a.int(1);a.binary(12)
a.string('VW153Count');a.call('variable_global_set',2,True)
a.var('str',-7);a.ret()
a.label('truncate')
a.var('currLanguage',-5);a.int(3);a.cmp(3);a.branch('truncate_original',0xb8)
a.arg(1);a.float(.65);a.binary(9);a.setarg(1)
a.label('truncate_original');a.arg(1);a.arg(0);a.call('gml_Script_scrTruncateString',2);a.ret()
a.label('crew')
a.var('currLanguage',-5);a.int(3);a.cmp(3);a.branch('crew_original',0xb8)
a.var('font_bodyText_sm2',-5);a.call('draw_set_font',1,True)
a.arg(7);a.call('draw_set_halign',1,True);a.arg(6);a.call('draw_set_valign',1,True)
a.int(1)
for _ in range(4):a.arg(5)
a.int(0);a.float(.65);a.float(.65);a.arg(2)
a.arg(1);a.int(3);a.binary(13);a.arg(0)
a.call('draw_text_transformed_color',11,True);a.exit()
a.label('crew_original')
for i in reversed(range(8)):a.arg(i)
a.call('gml_Script_draw_mini_text',8,True);a.exit()
a.label('debug_exit');a.exit()
binding=next(x['p'] for x in e.instructions(HELPER) if x['op']==192 and x['t']==2 and x['arg']==HELPER)
a.install(binding,'Bounded font/resolution/text keyed layout cache, newline-aware CJK wrapper and compact portrait names')

# Both measurement routines use the same text, font, line spacing and HD geometry.
for name,mode in [('gml_Script_string_height_bodyText',0),('gml_Script_string_width_bodyText',1)]:
    c=e.codes[name];stop=next(x['p'] for x in e.instructions(name) if x['op']==192 and x['t']==2 and x['arg']==name)
    q=Asm(c['begin']);q.int(0);q.int(mode)
    for i in reversed(range(4)):q.arg(i)
    q.call(HELPER,6);q.ret();q.install(stop,'Cache dimensions using exactly the same CJK line layout as drawing')

# The legacy drawText path passed sep=0 to draw_text_ext directly, stacking lines.
name='gml_Script_drawText';c=e.codes[name]
stop=next(x['p'] for x in e.instructions(name) if x['op']==192 and x['t']==2 and x['arg']==name)
q=Asm(c['begin']);q.var('font_bodyText',-5);q.int(0);q.int(0);q.var('c_tooltip1',-5)
for i in reversed(range(5)):q.arg(i)
q.call('gml_Script_draw_body_text',9,True);q.exit()
q.install(stop,'Use the standard font-aware body renderer; zero spacing receives the normal default')

# Credits retain the original Latin art fonts for creator names. Translated
# section headings use the language-aware header font instead of Latin-only
# fixed font assets, avoiding missing Chinese glyph rectangles.
for p in [0x9215e8,0x92165c,0x9216b0,0x921858,0x9218b0]:
    q=Asm(p);q.var('font_headerGothic_default',-5)
    q.install(p+8,'Render translated credits headings with the selected language header font')

# Replace the original optional debug rectangle with one wrapping hook and one
# native draw dispatch. Japanese retains its original no-space path.
q=Asm(0x6b695c)
body=q.pos
q.arg(8);q.call('draw_set_font',1,True)
q.arg(8);q.var('fnt_notoSerifSC',-5);q.cmp(3);q.branch('body_wrap',0xb7)
q.arg(8);q.var('fnt_notoSerifSC_2x',-5);q.cmp(3);q.branch('body_ready',0xb8)
q.label('body_wrap');q.arg(8);q.int(1);q.string('\n');q.arg(4);q.arg(2);q.call(HELPER,5);q.setarg(2)
q.label('body_ready');q.call('gml_Script_window_is_nativeRes',0);q.branch(0x6b6734)
native=q.pos
q.arg(8);q.var('fnt_notoSerifSC',-5);q.cmp(3);q.branch('native_cjk',0xb7)
q.arg(8);q.var('fnt_notoSerifSC_2x',-5);q.cmp(3);q.branch('native_jp',0xb8)
q.label('native_cjk');q.call('draw_text_ext',5);q.branch(0x6b6cfc)
q.label('native_jp');q.call('gml_Script_draw_text_ext_noSpace',5);q.branch(0x6b6cfc)
q.install(0x6b6af0,'Avoid a second, quadratic rewrap of already cached Chinese text')
for p,target,length in [(0x6b672c,body,8),(0x6b6cf4,native,8)]:
    q=Asm(p);q.branch(target);q.install(p+length,'Use shared CJK layout cache without changing draw arguments')

# Only the portrait name truncation and drawing calls use the compact-name modes.
crew='gml_Script_anon_gml_Object_oCrewPortrait_Create_0_6408_gml_Object_oCrewPortrait_Create_0'
for x in e.instructions(crew):
    if x['arg'] in ['gml_Script_scrTruncateString','gml_Script_draw_mini_text'] and x['op']==217:
        refs[x['p']]=rid(HELPER,'function',None)
        changes.append({'offset':x['p'],'length':8,'reason':'Center Chinese crew names within the portrait label and truncate at the rendered width'})

# Rewrite the announcement draw method inside its original allocation. Dimension
# cache handles language/font/width/resolution changes; only visible entries draw.
name='gml_Script_anon_gml_Object_oGameStartMessage_Create_0_3359_gml_Object_oGameStartMessage_Create_0'
c=e.codes[name];stop=next(x['p'] for x in e.instructions(name) if x['op']==192 and x['t']==2 and x['arg']==name)
q=Asm(c['begin'])
q.var('dimOpacity',-1);q.call('gml_Script_scrDimScreen',1,True)
q.int(0);q.put('strH');q.var('lineSep_duBellay',-5);q.put('sep')
q.var('shortMessageStr',-1);q.string('');q.cmp(4);q.branch('regular',0xb8)
q.var('font_bodyText',-5);q.int(1);q.int(0);q.var('c_tooltip1',-5)
q.var('textW',-1);q.var('sep',-7);q.var('shortMessageStr',-1)
q.var('room_height');q.int(2);q.binary(9);q.int(50);q.binary(13)
q.var('room_width');q.int(2);q.binary(9)
q.call('gml_Script_draw_body_text',9,True);q.branch('finish')
q.label('regular');q.int(0);q.put('i')
q.label('loop');q.var('i',-7);q.var('gameStartMessages',-5);q.call('array_length',1);q.cmp(1);q.branch('finish',0xb8)
# Copy the original, compiler-specific array and struct access instructions.
def copy_segment(asm,begin,end):
    old=e.b[begin:end];p=asm.pos;asm.v+=old
    for site,r in e.refs.items():
        if begin<=site<end:
            asm.refs[p+site-begin]=r
            asm.ref_flags[p+site-begin]=e.u(site+4)&0xf8000000
qstart=q.pos
copy_segment(q,0xa2b8c0,0xa2b918)
# These local VARI records are the original announcement's declared variables.
# Assign by selecting the same local IDs (which are global name IDs in GMS 2.3).
q.var('font_bodyText',-5);q.var('textW',-1);q.var('sep',-7);q.var('bodyStr',-7)
q.call('gml_Script_string_height_bodyText',4);q.put('bodyH')
q.arg(1);q.var('bodyH',-7);q.binary(12);q.int(35);q.binary(12);q.int(-20);q.cmp(1);q.branch('advance',0xb7)
q.arg(1);q.var('room_height');q.int(20);q.binary(12);q.cmp(6);q.branch('advance',0xb7)
q.var('font_headerGothic_default',-5);q.int(0);q.int(0);q.var('c_tooltip1',-5)
q.var('titleStr',-7);q.arg(1);q.arg(0);q.call('gml_Script_draw_gothic_text',7,True)
q.var('font_bodyText',-5);q.int(0);q.int(0);q.var('c_tooltip1',-5)
q.var('textW',-1);q.var('sep',-7);q.var('bodyStr',-7)
q.arg(1);q.int(35);q.binary(12);q.arg(0);q.call('gml_Script_draw_body_text',9,True)
# Original divider sprite remains referenced by its beta resource ID.
div=next(x for x in e.instructions(name) if x['op']==255 and x['t']==2)
q.var('c_tooltip1',-5);q.int(7);q.var('textW',-1)
q.arg(1);q.int(18);q.binary(13);q.arg(0)
q.word(div['word']);q.word(e.u(div['p']+4));q.call('gml_Script_draw_9slice_color',6,True)
q.label('advance');q.var('bodyH',-7);q.int(85);q.binary(12);q.put('entryH')
q.var('strH',-7);q.var('entryH',-7);q.binary(12);q.put('strH')
q.arg(1);q.var('entryH',-7);q.binary(12);q.setarg(1)
q.var('i',-7);q.int(1);q.binary(12);q.put('i');q.branch('loop')
q.label('finish');q.int(9999999);q.int(0);q.var('strH',-7);q.int(600);q.binary(13)
q.call('clamp',3);q.put('yScroll_max',-1);q.exit()
q.install(stop,'Reuse announcement layout and skip offscreen text while preserving scroll extent and closing behavior')

# The main-menu footer must not cover announcement, settings or credits text.
# Keep the original beta version line and hide only the translation credit.
q=Asm(0x70cbd4)
copy_segment(q,0x70cbd4,0x70cc20)
copy_segment(q,0x70cc20,0x70cc34);q.branch('footer_exit',0xb8)
copy_segment(q,0x70cc38,0x70cc48);q.branch('footer_exit',0xb8)
for object_id in [5197,3661,5529]:
    q.word(0xff02fff5);q.word(object_id)
    q.call('instance_exists',1);q.truth();q.branch('footer_exit',0xb7)
copy_segment(q,0x70cc4c,0x70cc9c)
q.label('footer_exit');q.exit()
q.install(0x70ce2c,'Show translation credit only on the unobscured main menu')

# Rebuild reference chains, keeping each original terminal ID and variable type.
chains=collections.defaultdict(list)
for p,r in refs.items():chains[r].append(p)
for r,t in e.tables.items():
    sites=sorted(chains[r])
    patch(t['countp'],struct.pack('<I',len(sites)),'Reference occurrence count')
    patch(t['firstp'],struct.pack('<I',sites[0]+(4 if t['kind']=='function' else 0) if sites else 0xffffffff),'Reference first occurrence')
    for i,p in enumerate(sites):
        delta=sites[i+1]-p if i+1<len(sites) else t['terminal']
        assert 0<=delta<0x8000000
        patch(p+4,struct.pack('<I',flags[p]|delta),'Reference occurrence link')
assert len(b)==len(e.b)
PATH.write_bytes(b)
v=Engine(PATH);assert v.refs==refs
for p in programs:
    # All branches in new programs resolve to valid decoded instruction starts.
    starts=set();j=p['begin']
    while j<p['end']:
        starts.add(j);w=v.u(j);op=w>>24;t=(w>>16)&15
        sz=12 if op in [192,193,194,195] and t in [0,3] else 8 if ((op in [192,193,194,195] and t in [2,5,6]) or op==217 or (op==69 and t!=15) or(op==255 and t==2)) else 4
        j+=sz
    assert j==p['end']
    for label in p['labels'].values():assert label in starts
report={'status':'PASS_STATIC','input_sha256':hashlib.sha256(e.b).hexdigest(),
        'output_sha256':hashlib.sha256(b).hexdigest(),'size':len(b),
        'reference_count':len(refs),'cache_entries_limit':256,
        'portrait_scale':.65,'portrait_y_adjust':-3,
        'dynamic_system_bonus_literals':len(system_literals),
        'programs':programs,'changes':changes,
        'removed_optional_development_feature':'F3 crew diagnostic overlay; ordinary crew/gameplay behavior is retained',
        'runtime_validation':'pending'}
args.report.parent.mkdir(parents=True,exist_ok=True)
args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
print(json.dumps({k:v for k,v in report.items() if k not in ['programs','changes']},ensure_ascii=False))
