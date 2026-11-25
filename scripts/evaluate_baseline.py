import json,time,statistics
from pathlib import Path
import httpx
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'dataset/ground_truth/manifest.json').read_text(encoding='utf-8-sig'))
mapping={'grand_total_mismatch':['invoice_arithmetic_consistency'],'invalid_gstin':['gstin_validation'],'tax_inconsistency':['cgst_sgst_symmetry','tax_rate_arithmetic'],'running_balance_mismatch':['bank_statement_balance_consistency'],'ela_compression_splice':['ela'],'copy_move_clone':['copy_move'],'noise_inconsistency':['noise_inconsistency'],'editing_software_exif':['image_metadata']}
def iou(a,b):
 if a['page']!=b['page']:return 0
 w=max(0,min(a['x']+a['w'],b['x']+b['w'])-max(a['x'],b['x']))
 h=max(0,min(a['y']+a['h'],b['y']+b['h'])-max(a['y'],b['y']))
 return w*h/(a['w']*a['h']+b['w']*b['h']-w*h)
rows=[]
with httpx.Client(base_url='http://127.0.0.1:8000',timeout=60,trust_env=False) as c:
 for sample in manifest['samples']:
  p=root/sample['relative_path']; start=time.perf_counter()
  r=c.post('/analyze',files={'file':(p.name,p.read_bytes())});r.raise_for_status(); jid=r.json()['job_id']
  for _ in range(600):
   j=c.get('/result/'+jid).json()
   if j['status'] in ('completed','failed'):break
   time.sleep(.1)
  assert j['status']=='completed',j['status']
  flags=[f for f in j['findings'] if f['status']=='suspicious']
  expected=[a['code'] for a in sample['expected_anomalies']]
  hits=[code for code in expected if any(f['name'] in mapping[code] for f in flags)]
  dims={p['page']:(p['width'],p['height']) for p in j['pages']}
  compatible=all(dims.get(p['page'])==(p['width'],p['height']) for p in sample['page_dimensions'])
  boxes=[b for f in flags if any(f['name'] in mapping[code] for code in expected) for b in f['boxes']]
  overlaps=[max([iou(a,b) for b in boxes],default=0) for a in sample['known_affected_regions']] if compatible else None
  row=dict(filename=p.name,label=sample['label'],risk_score=j['risk_score'],risk_level=j['risk_level'],coverage=j['coverage'],seconds=round(time.perf_counter()-start,3),expected=expected,hits=hits,flags=[f['name'] for f in flags],region_iou=overlaps,dimensions_match=compatible,findings=j['findings'])
  rows.append(row)
  print(json.dumps({k:v for k,v in row.items() if k!='findings'}),flush=True)
def metrics(pred):
 counts=dict(tp=0,tn=0,fp=0,fn=0,inconclusive=0)
 for r in rows:
  v=pred(r)
  if v is None:counts['inconclusive']+=1;continue
  counts[('tp' if v else 'fn') if r['label']=='tampered' else ('fp' if v else 'tn')]+=1
 t,n,f,m=(counts[k] for k in ('tp','tn','fp','fn'))
 return dict(**counts,precision=t/(t+f) if t+f else None,recall=t/(t+m) if t+m else None,f1=2*t/(2*t+f+m) if 2*t+f+m else None,accuracy=(t+n)/(t+n+f+m) if t+n+f+m else None)
summary=dict(risk=metrics(lambda r:None if r['risk_level']=='inconclusive' else r['risk_level'] in ('medium','high')),any_flag=metrics(lambda r:bool(r['flags'])),expected_hits=sum(len(r['hits']) for r in rows),expected_total=sum(len(r['expected']) for r in rows),median_seconds=statistics.median(r['seconds'] for r in rows),mean_seconds=statistics.mean(r['seconds'] for r in rows),max_seconds=max(r['seconds'] for r in rows))
out=root/'docs/evaluation';out.mkdir(exist_ok=True)
(out/'baseline.json').write_text(json.dumps(dict(summary=summary,rows=rows),indent=2),encoding='utf-8')
print('SUMMARY',json.dumps(summary),flush=True)

