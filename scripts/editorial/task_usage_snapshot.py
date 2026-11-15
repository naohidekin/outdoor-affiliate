"""Registered-task numeric metadata collector. Never reads session logs or credentials."""
import argparse
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import shlex
import sqlite3
import subprocess
from urllib.parse import quote
from reporting import _atomic

JST=timezone(timedelta(hours=9))


def capture(source,history,registered,now=None):
 now=now or datetime.now(JST)
 if now.tzinfo is None:raise ValueError('aware timestamp required')
 now=now.astimezone(JST)
 start=(now-timedelta(days=(now.weekday()-4)%7)).replace(hour=9,minute=0,second=0,microsecond=0)
 if now<start:start-=timedelta(days=7)
 period=start.date().isoformat()
 if not registered or len(registered)>32:raise ValueError('bounded registered task ids required')
 mains=[i for i,role in registered.items() if role=='main']
 if len(mains)!=1 or any(role not in ('main','helper') for role in registered.values()):raise ValueError('one registered task and its helpers required')
 source=Path(source)
 if source.is_symlink() or not source.is_file():raise ValueError('task metadata unavailable')
 with sqlite3.connect('file:'+quote(str(source),safe='/')+'?mode=ro',uri=True) as db:
  db.execute('PRAGMA query_only=ON')
  if not {'id','tokens_used','source'} <= {x[1] for x in db.execute('PRAGMA table_info(threads)')}:raise ValueError('task metadata schema unavailable')
  counters={i:db.execute('SELECT tokens_used,source FROM threads WHERE id=?',(i,)).fetchone() for i in registered}
  for identifier,role in registered.items():
   if role=='helper' and counters[identifier] is not None:
    try:parent=json.loads(counters[identifier][1])['subagent']['thread_spawn']['parent_thread_id']
    except (ValueError,TypeError,KeyError):raise ValueError('helper parent attribution unavailable')
    if parent!=mains[0]:raise ValueError('helper belongs to another task')
 history=Path(history);history.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
 output=[]
 with sqlite3.connect(history) as db:
  db.execute('CREATE TABLE IF NOT EXISTS task_usage_samples(period TEXT,id TEXT,baseline INTEGER,baseline_at TEXT,last INTEGER,last_at TEXT,decreased INTEGER,PRIMARY KEY(period,id))')
  for identifier,role in registered.items():
   row=counters[identifier];counter=row[0] if row else None
   item={'id':identifier,'role':role,'counter':counter,'periodBaseline':None,'delta':None,'baselineAt':None,'coveragePartial':True,'status':'missing'}
   if type(counter) is int and counter>=0:
    prior=db.execute('SELECT baseline,baseline_at,last,last_at,decreased FROM task_usage_samples WHERE period=? AND id=?',(period,identifier)).fetchone()
    if prior is None:
     db.execute('INSERT INTO task_usage_samples VALUES (?,?,?,?,?,?,?)',(period,identifier,counter,now.isoformat(),counter,now.isoformat(),0))
     item.update(periodBaseline=counter,baselineAt=now.isoformat(),status='baseline_only')
    else:
     baseline,at,last,last_at,decreased=prior;decreased=bool(decreased or counter<last or counter<baseline)
     item.update(periodBaseline=baseline,baselineAt=at,delta=None if decreased else counter-baseline,status='counter_decreased' if decreased else 'observed_difference')
     db.execute('UPDATE task_usage_samples SET last=?,last_at=?,decreased=? WHERE period=? AND id=?',(counter,now.isoformat(),int(decreased),period,identifier))
   output.append(item)
 history.chmod(0o600)
 return {'source':'codex_local_thread_counters','unit':'local_cumulative_token_counter','observedAt':now.isoformat(),
  'periodKey':period,'scope':'registered_camp_task_threads_only','taskAttribution':True,'threads':output,
  'subscriptionPercent':None,'attributionOverlapUnknown':True,
  'limitations':['入力・出力・キャッシュ内訳と課金単位は未確認','親と補助agentの重複関係が不明なため合算しない','初回計測以前の週次消費は復元できない','サブスク枠への換算率は未取得']}


def sync_to_macpro(value):
 # Fixed destination, payload is JSON stdin: no shell interpolation of data.
 script="""import json,sys,pathlib,os
v=json.loads(sys.stdin.read(2097153));assert v.get('scope')=='registered_camp_task_threads_only'
r=pathlib.Path.home()/'Library/Application Support/CampGearLabCodex/editorial/task-usage'
r.mkdir(mode=0o700,parents=True,exist_ok=True)
p=r/'codex-task.json';t=r/('codex-task.'+str(os.getpid())+'.tmp')
t.write_text(json.dumps(v,ensure_ascii=False)+'\\n');t.chmod(0o600);t.replace(p)
"""
 result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','macpro','python3 -c '+shlex.quote(script)],
  input=json.dumps(value,ensure_ascii=False),text=True,capture_output=True,timeout=30)
 if result.returncode:raise ValueError('task usage snapshot sync unavailable')


if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--history',required=True);p.add_argument('--output',required=True);p.add_argument('--thread',action='append',required=True);p.add_argument('--sync',action='store_true');a=p.parse_args()
 registered=dict(x.split(':',1) for x in a.thread)
 if len(registered)!=len(a.thread):raise ValueError('duplicate registered task id')
 value=capture(a.source,a.history,registered);_atomic(Path(a.output),value)
 try:
  if a.sync:sync_to_macpro(value)
  print(json.dumps({'status':'synced' if a.sync else 'saved','periodKey':value['periodKey'],'threads':len(value['threads'])}))
 except Exception:
  print(json.dumps({'status':'saved_local_sync_pending','periodKey':value['periodKey']}));raise SystemExit(1)
