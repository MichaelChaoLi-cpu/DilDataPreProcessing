"""Scan raw WM yaml to classify how each non-clean dataset can supply received_anc.
Read-only. Emits /tmp/anc_plan.json with per-dataset recovery method."""
import yaml, os, re, json
import pandas as pd, pyarrow.parquet as pq

PQ="MICS-WM/data/WM/processed_data/wm_merged.parquet"
df=pd.read_parquet(PQ,columns=['dataset_name','received_anc'])
# clean = has base yes/no (max<=2 ignoring sentinels).  Use: has received_anc & <=2 non-sentinel share high
clean = set(json.load(open("/tmp/anc_yncol.json")))   # 153 datasets with a verified yes/no column
targets = sorted(set(df.dataset_name.unique()) - clean)   # everything needing recovery

YES=re.compile(r'^\s*(yes|s[ií]|oui|sim|да|بل[یه]|hai|ndiyo|evet|jah)\b',re.I)
NO =re.compile(r'^\s*(no|non|n[ãa]o|нет|hapana|hay[ıi]r|خیر)\b',re.I)
ANC=re.compile(r'(antenatal|ante-natal|prenatal|pre-natal|pr[ée]natal|prenatale?|antenatale?|антенатал|дород|soins pr[ée]|control prenatal|chequeo prenatal|cuidado prenatal|aten\w+ prenatal)',re.I)
# main "received/consulted/sought" ANC (not a sub-item)
RECV=re.compile(r'(receiv|reçu|recibi|consult|consult[oó]|seek|sought|tuvo|atenci[oó]n prenatal recib|check|chequeo|control prenatal|soins pr[ée]natals au cours|cuidado prenatal)',re.I)
SUBITEM=re.compile(r'(weigh|pes[oa]|iron|fer|folate|folic|tetan|blood|sang|urine|orin|pressure|presi[oó]n|hiv|sida|vih|test|prueba|ultrason|azucar|sugar|sifili|syphil|counsel|information|training|entrena|medic|paludism|malaria|azucar|number|times|no of|month|week|weight|height)',re.I)
PROV=re.compile(r'(doctor|m[ée]decin|physician|nurse|infirmi|midwife|sage-?femme|matron|obstetric|gyn|tba|accoucheuse|traditional|traditionnel|comadron|partera|relative|friend|parent|ami|famille|community health|agent de sant[ée]|chw|auxiliar|health worker|personnel|profesional|skilled|trabajador)',re.I)
NONECOL=re.compile(r'(no one|nobody|no ?body|personne|nadie|ninguno|ningu[eé]m|aucun|pas de|n.a vu personne|none|no recib|did ?n.?t|no fue|sin atenci|no prenatal|not receiv)',re.I)

def _f(k):
    try: return float(k)
    except (TypeError,ValueError): return None
def _vl(d):
    out={}
    for k,v in (d or {}).items():
        fk=_f(k)
        if fk is not None: out[fk]=str(v)
    return out
def raw_cols(ds):
    p=f"MICS-WM/data/WM/raw/{ds}/wm.yaml"
    if not os.path.exists(p): return None
    ry=yaml.safe_load(open(p)); L=ry.get('columns',ry) if isinstance(ry,dict) else ry
    return L

def yn_codes(vl):
    yes=[float(k) for k,v in vl.items() if YES.match(str(v))]
    no =[float(k) for k,v in vl.items() if NO.match(str(v))]
    return yes,no

plan={}
for ds in targets:
    L=raw_cols(ds)
    if L is None: plan[ds]={'method':'NONE','reason':'no raw yaml'}; continue
    cols=[]
    for c in L:
        cols.append({'col':c.get('column_in_raw_sav'),
                     'lab':(c.get('column_label_in_english') or c.get('column_label_in_raw_sav') or ''),
                     'vl':_vl(c.get('value_labels'))})
    # 1) DIRECT single yes/no main ANC question
    BADDIR=re.compile(r'(otro|other|autre|prevenir|prevent|pr[ée]venir|utiliz|used|seguro|SBS|no fue|conocim|knowledge|sabe c)',re.I)
    NAMEOK=re.compile(r'^(mn1|mn2)$',re.I)
    direct=None
    for c in cols:
        if ANC.search(c['lab']) and RECV.search(c['lab']) and not SUBITEM.search(c['lab']) and not PROV.search(c['lab']) and not BADDIR.search(c['lab']):
            yes,no=yn_codes(c['vl'])
            if yes and no and NAMEOK.match(c['col'] or ''):
                direct=c; break
    if direct:
        yes,no=yn_codes(direct['vl'])
        plan[ds]={'method':'DIRECT','col':direct['col'],'lab':direct['lab'],'yes':yes,'no':no}
        continue
    # 2) SINGLE-column provider list (value labels list providers + a 'no one')
    single=None
    for c in cols:
        if ANC.search(c['lab']) and not SUBITEM.search(c['lab']):
            labs=list(c['vl'].values())
            provvals=[float(k) for k,v in c['vl'].items() if PROV.search(v)]
            nonevals=[float(k) for k,v in c['vl'].items() if NONECOL.search(v)]
            if len(provvals)>=2 and nonevals:
                single={'col':c['col'],'lab':c['lab'],'prov':provvals,'none':nonevals,'vl':c['vl']}; break
    if single:
        plan[ds]={'method':'SINGLE','col':single['col'],'lab':single['lab'],'prov':single['prov'],'none':single['none']}
        continue
    # 3) CHECKBOX: provider-name yes/no cols + a none col
    prov_cols=[]; none_cols=[]
    for c in cols:
        if ANC.search(c['lab']) or re.match(r'^mn2[a-z]?\d?$',c['col'] or '',re.I):
            yes,no=yn_codes(c['vl'])
            if not (yes and no):  # some checkbox labelled only Yes; treat 1=yes
                if not c['vl']: yes=[1.0]
            if NONECOL.search(c['lab']): none_cols.append({'col':c['col'],'lab':c['lab'],'yes':yes or [1.0]})
            elif PROV.search(c['lab']): prov_cols.append({'col':c['col'],'lab':c['lab'],'yes':yes or [1.0]})
    if prov_cols:
        plan[ds]={'method':'CHECKBOX','prov_cols':prov_cols,'none_cols':none_cols}
        continue
    # nothing
    anc_labels=[(c['col'],c['lab'][:45]) for c in cols if ANC.search(c['lab'])][:8]
    plan[ds]={'method':'NONE','anc_cols':anc_labels}

json.dump(plan,open('/tmp/anc_plan.json','w'),indent=1)
from collections import Counter
cnt=Counter(p['method'] for p in plan.values())
print("targets(non-clean):",len(targets),"| methods:",dict(cnt))
for m in ['DIRECT','SINGLE','CHECKBOX','NONE']:
    print(f"\n===== {m} =====")
    for ds,p in plan.items():
        if p['method']!=m: continue
        if m=='DIRECT': print(f"  {ds:52} {p['col']:8} {p['lab'][:45]!r}")
        elif m=='SINGLE': print(f"  {ds:52} {p['col']:8} prov={p['prov']} none={p['none']}")
        elif m=='CHECKBOX': print(f"  {ds:52} prov={[c['col'] for c in p['prov_cols']]} none={[c['col'] for c in p['none_cols']]}")
        else: print(f"  {ds:52} anc_cols={p['anc_cols']}")
