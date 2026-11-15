"""Offline daily GA4/GSC collection lifecycle."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from daily_metrics import collect_daily_metrics, require_fresh_daily_metrics

JST = timezone(timedelta(hours=9))


def snapshot(day='2026-11-20'):
    return {'schemaVersion':1, 'collectionKind':'daily',
            'collectedAt':day+'T08:05:00+09:00', 'operationTimezone':'Asia/Tokyo',
            'current':{'status':'ok','startDate':'2026-10-20','endDate':'2026-11-16',
                       'settledThrough':'2026-11-16','dateBasis':'America/Los_Angeles'},
            'previous':{'status':'ok','startDate':'2026-09-22','endDate':'2026-10-19',
                        'settledThrough':'2026-11-16','dateBasis':'America/Los_Angeles'},
            'ga4':{'status':'ok','startDate':'2026-10-20','endDate':'2026-11-16',
                   'dateBasis':'Asia/Tokyo','landingPages':[],'aiReferrals':[]},
            'previousGa4':{'status':'ok','startDate':'2026-09-22','endDate':'2026-10-19',
                           'dateBasis':'Asia/Tokyo','landingPages':[],'aiReferrals':[]}}


class DailyMetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); base=Path(self.tmp.name)
        self.config={'stateRoot':str(base/'state'),'seoStateRoot':str(base/'seo'),
                     'seoRepo':str(base/'repo'),'dailyMetricsEnabled':True,'node':'node'}
        self.now=datetime(2026,11,20,8,5,tzinfo=JST); self.calls=[]
    def tearDown(self): self.tmp.cleanup()
    def runner(self,*args,**kwargs):
        self.calls.append((args,kwargs))
        return type('Result',(),{'returncode':0,'stdout':json.dumps(snapshot()),'stderr':''})()

    def test_after_eight_runs_once_and_writes_valid_latest_atomically(self):
        first=collect_daily_metrics(self.config,{},now=self.now,runner=self.runner)
        second=collect_daily_metrics(self.config,{},now=self.now,runner=self.runner)
        self.assertEqual('success',first['status']);self.assertEqual('already_success',second['status'])
        self.assertEqual(1,len(self.calls))
        latest=Path(self.config['seoStateRoot'])/'metrics/latest.json'
        self.assertEqual(snapshot(),json.loads(latest.read_text()))
        self.assertEqual(0o600,latest.stat().st_mode & 0o777)
        self.assertEqual('fresh',require_fresh_daily_metrics(self.config,self.now)['status'])

    def test_same_day_snapshot_mutation_is_rejected_by_receipt_hash(self):
        collect_daily_metrics(self.config,{},now=self.now,runner=self.runner)
        latest=Path(self.config['seoStateRoot'])/'metrics/latest.json'
        changed=json.loads(latest.read_text());changed['current']['summary']={'clicks':999}
        latest.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError,'daily_metrics_not_fresh'):
            require_fresh_daily_metrics(self.config,self.now)

    def test_before_eight_is_not_due_and_creates_nothing(self):
        result=collect_daily_metrics(self.config,{},now=self.now.replace(hour=7,minute=59),runner=self.runner)
        self.assertEqual('not_due',result['status']);self.assertEqual([],self.calls)
        self.assertFalse(Path(self.config['stateRoot']).exists())

    def test_failure_preserves_last_good_never_retries_same_day_but_next_day_can(self):
        latest=Path(self.config['seoStateRoot'])/'metrics/latest.json';latest.parent.mkdir(parents=True)
        latest.write_text(json.dumps({'last':'good'}));before=latest.read_bytes()
        def failed(*args,**kwargs):
            self.calls.append(1);return type('Result',(),{'returncode':1,'stdout':'{"error":"safe"}','stderr':'RAW'})()
        first=collect_daily_metrics(self.config,{},now=self.now,runner=failed)
        second=collect_daily_metrics(self.config,{},now=self.now,runner=failed)
        third=collect_daily_metrics(self.config,{},now=self.now+timedelta(days=1),runner=failed)
        self.assertEqual(('failed','already_failed','failed'),(first['status'],second['status'],third['status']))
        self.assertEqual(2,len(self.calls));self.assertEqual(before,latest.read_bytes())
        self.assertNotIn('RAW',json.dumps(first))

    def test_invalid_snapshot_fails_closed_without_replacing_last_good(self):
        latest=Path(self.config['seoStateRoot'])/'metrics/latest.json';latest.parent.mkdir(parents=True)
        latest.write_text('{"last":"good"}');before=latest.read_bytes()
        bad=snapshot();bad['ga4']['status']='unavailable'
        def runner(*args,**kwargs):
            return type('Result',(),{'returncode':0,'stdout':json.dumps(bad),'stderr':''})()
        self.assertEqual('failed',collect_daily_metrics(self.config,{},now=self.now,runner=runner)['status'])
        self.assertEqual(before,latest.read_bytes())
        with self.assertRaisesRegex(ValueError,'daily_metrics_not_fresh'):
            require_fresh_daily_metrics(self.config,self.now)

    def test_partial_days_future_collection_and_invalid_timezone_are_rejected(self):
        variants=[]
        partial=snapshot();partial['current']['startDate']='2026-10-21';variants.append(partial)
        future=snapshot();future['collectedAt']='2026-11-20T08:06:00+09:00';variants.append(future)
        zone=snapshot();zone['ga4']['dateBasis']='not/a-zone';variants.append(zone)
        gsc_zone=snapshot();gsc_zone['current']['dateBasis']='Asia/Tokyo';variants.append(gsc_zone)
        mixed=snapshot();mixed['previousGa4']['dateBasis']='America/Los_Angeles';variants.append(mixed)
        for index,bad in enumerate(variants):
            with self.subTest(index=index),tempfile.TemporaryDirectory() as folder:
                config=dict(self.config,stateRoot=str(Path(folder)/'state'),seoStateRoot=str(Path(folder)/'seo'))
                def runner(*args,**kwargs):
                    return type('Result',(),{'returncode':0,'stdout':json.dumps(bad),'stderr':''})()
                self.assertEqual('failed',collect_daily_metrics(config,{},now=self.now,runner=runner)['status'])
                self.assertFalse((Path(config['seoStateRoot'])/'metrics/latest.json').exists())

    def test_fresh_collection_rejects_old_current_period_or_end_before_settled(self):
        behind=snapshot();behind['current'].update(startDate='2026-10-19',endDate='2026-11-15',
                                                  settledThrough='2026-11-16')
        behind['ga4'].update(startDate='2026-10-19',endDate='2026-11-15')
        behind['previous'].update(startDate='2026-09-21',endDate='2026-10-18')
        behind['previousGa4'].update(startDate='2026-09-21',endDate='2026-10-18')
        old=snapshot();old['current'].update(startDate='2026-09-20',endDate='2026-10-17',
                                            settledThrough='2026-10-17')
        old['ga4'].update(startDate='2026-09-20',endDate='2026-10-17')
        old['previous'].update(startDate='2026-08-23',endDate='2026-09-19')
        old['previousGa4'].update(startDate='2026-08-23',endDate='2026-09-19')
        for index,bad in enumerate((behind,old)):
            with self.subTest(index=index),tempfile.TemporaryDirectory() as folder:
                config=dict(self.config,stateRoot=str(Path(folder)/'state'),seoStateRoot=str(Path(folder)/'seo'))
                def runner(*args,**kwargs):
                    return type('Result',(),{'returncode':0,'stdout':json.dumps(bad),'stderr':''})()
                self.assertEqual('failed',collect_daily_metrics(config,{},now=self.now,runner=runner)['status'])


if __name__=='__main__': unittest.main()
