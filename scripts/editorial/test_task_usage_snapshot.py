import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from task_usage_snapshot import capture

JST=timezone(timedelta(hours=9))
class TaskUsageTests(unittest.TestCase):
 def test_other_task_helper_cannot_be_attributed_to_main(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);source=root/'app.sqlite'
   with sqlite3.connect(source) as db:
    db.execute('CREATE TABLE threads(id TEXT,tokens_used INTEGER,source TEXT)')
    db.executemany('INSERT INTO threads VALUES (?,?,?)',[
      ('main',10,'vscode'),('helper',99,json.dumps({'subagent':{'thread_spawn':{'parent_thread_id':'OTHER'}}}))])
   with self.assertRaisesRegex(ValueError,'another task'):
    capture(source,root/'history.sqlite',{'main':'main','helper':'helper'},datetime(2026,11,20,10,tzinfo=JST))
 def test_exact_registered_threads_only_partial_baseline_and_numeric_delta(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);dbpath=root/'app.sqlite';history=root/'history.sqlite'
   with sqlite3.connect(dbpath) as db:
    db.execute('CREATE TABLE threads(id TEXT PRIMARY KEY,tokens_used INTEGER,source TEXT)')
    db.executemany('INSERT INTO threads(id,tokens_used) VALUES (?,?)',[('main',100),('other-task',999999)])
   now=datetime(2026,11,20,10,tzinfo=JST)
   first=capture(dbpath,history,{'main':'main'},now)
   self.assertIsNone(first['threads'][0]['delta'])
   with sqlite3.connect(dbpath) as db:db.execute('UPDATE threads SET tokens_used=150 WHERE id=?',('main',))
   second=capture(dbpath,history,{'main':'main'},now+timedelta(hours=1))
   self.assertEqual(50,second['threads'][0]['delta']);self.assertEqual(1,len(second['threads']))
   self.assertIsNone(second['subscriptionPercent']);self.assertTrue(second['threads'][0]['coveragePartial'])
   nextweek=capture(dbpath,history,{'main':'main'},now+timedelta(days=7))
   self.assertIsNone(nextweek['threads'][0]['delta'])
 def test_counter_decrease_is_not_zero_usage(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);dbpath=root/'app.sqlite';history=root/'history.sqlite'
   with sqlite3.connect(dbpath) as db:db.execute('CREATE TABLE threads(id TEXT,tokens_used INTEGER,source TEXT)');db.execute('INSERT INTO threads(id,tokens_used) VALUES (?,?)',('main',100))
   now=datetime(2026,11,20,10,tzinfo=JST);capture(dbpath,history,{'main':'main'},now)
   with sqlite3.connect(dbpath) as db:db.execute('UPDATE threads SET tokens_used=10')
   result=capture(dbpath,history,{'main':'main'},now+timedelta(hours=1))
   self.assertIsNone(result['threads'][0]['delta']);self.assertEqual('counter_decreased',result['threads'][0]['status'])
