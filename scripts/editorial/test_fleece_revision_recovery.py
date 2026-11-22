"""Bounded permutation repair and one pinned fleece retry; offline only."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ledger import fingerprint
from models import Models, ModelError
from runtime import Runtime
from revisions import validated_context
from test_models import ENV, Fake, bundle, context, writer_response, response
from test_revision_workflow import baseline, spec

JOB = 'revision-4cefcebe89527e18972d37b9'
KEY = 'stage_journal:v1:ce6912a4dcb976bca06d653bbc391430a8476c544f2057f9674555481a427db7'
IDS = ['fleece-tnf-na62650', 'fleece-montbell-1114881']


def fixture():
    b = baseline(id='3082b43c-a612-4ae0-926e-8bd86c6ab84e',
                 slug='autumn-camp-classic-fleece-comparison')
    b['productIds'] = IDS[:]
    binding = validated_context(spec(b))
    job = dict(id=JOB, kind='article_revision', stage='error', theme={
        'slug': b['slug'], 'productIds': IDS[:]}, revisionContext=binding,
        error={'reason': 'Article product IDs do not match supplied products'},
        bundle=None, approval=None, publication=None, review=None)
    record = dict(jobId=JOB, stage='draft', stageKey=KEY, status='failed',
                  attempts=1, maxAttempts=2, failureType='ModelError',
                  responseReceiptCount=1, missingUsage=False,
                  usageBatches=[{'records':[{'responseId':'msg_011ChJjEpHjigbh9kQyLV1Lo'}]}])
    return job, record


class ProductOrderTests(unittest.TestCase):
    def values(self):
        b, c = bundle(), context()
        c['catalog'].append(dict(c['catalog'][0], id='tent-b'))
        b['article']['productIds'] = ['tent-b', 'tent-a']
        b['article']['content'] += '\n\n{{product:tent-b}}\n\n{{comparison:tent-b,tent-a}}'
        b['brief']['format'] = 'comparison'
        return b, c

    def test_permutation_reaches_existing_length_repair_without_body_rewrite(self):
        b, c = self.values()
        original = b['article']['content']
        added = '\n\n' + '根拠の範囲で選び方を確認します。' * 110
        fake = Fake(writer_response(b), response({'insertions':[
            {'after':'{{comparison:tent-b,tent-a}}', 'text':added}]}))
        out = Models(ENV, fake).draft({'productIds':['tent-a','tent-b']}, c)
        self.assertEqual(['tent-a','tent-b'], out['article']['productIds'])
        self.assertEqual(original + added, out['article']['content'])
        self.assertEqual(b['brief'], out['brief'])
        self.assertEqual(2, len(fake.calls))

    def test_nonpermutations_fail_before_length_repair(self):
        for ids in (['tent-a','tent-a'], ['tent-a'], ['tent-a','unknown'],
                    ['tent-a','tent-b','unknown']):
            with self.subTest(ids=ids):
                b, c = self.values(); b['article']['productIds'] = ids
                fake = Fake(writer_response(b))
                with self.assertRaises(ModelError):
                    Models(ENV, fake).draft({'productIds':['tent-a','tent-b']}, c)
                self.assertEqual(1, len(fake.calls))

    def test_exact_fleece_comparison_cannot_be_reclassified_as_guide(self):
        b, c = self.values()
        for product, pid in zip(c['catalog'], IDS): product['id'] = pid
        b['article']['productIds'] = IDS[:]
        b['article']['slug'] = 'autumn-camp-classic-fleece-comparison'
        b['article']['content'] = b['article']['content'].replace('tent-a', IDS[0]).replace('tent-b', IDS[1])
        b['brief']['format'] = 'guide'
        c['existingArticle'] = {'slug':b['article']['slug']}
        fake = Fake(writer_response(b))
        with self.assertRaisesRegex(ModelError, 'Fleece revision must remain comparison'):
            Models(ENV, fake).draft({'productIds':IDS[:]}, c)
        self.assertEqual(1, len(fake.calls))


class FleeceEligibilityTests(unittest.TestCase):
    def test_exact_scope_only(self):
        job, record = fixture()
        # Synthetic context replaces only the pinned digest, not any gate logic.
        with patch('fleece_revision_recovery.CONTEXT_SHA', fingerprint(job['revisionContext'])):
            Runtime.validate_corrected_retry(job, 'draft', KEY, [record])
            cases = [dict(job, id='other'), dict(job, error={'reason':'provider error'}),
                     dict(job, review={}), dict(job, approval={}), dict(job, stage='candidate')]
            for bad in cases:
                with self.subTest(job=bad), self.assertRaises(ValueError):
                    Runtime.validate_corrected_retry(bad, 'draft', KEY, [record])
            for changes in ({'attempts':2}, {'status':'unknown'}, {'status':'in_flight'},
                            {'maxAttempts':3}, {'successorKey':'used'}, {'predecessorKey':'prior'},
                            {'failureType':'OtherError'}, {'responseReceiptCount':0}, {'missingUsage':True}):
                with self.subTest(changes=changes), self.assertRaises(Exception):
                    Runtime.validate_corrected_retry(job, 'draft', KEY, [dict(record, **changes)])
            bad = copy.deepcopy(job); bad['theme']['productIds'].reverse()
            with self.assertRaises(ValueError):
                Runtime.validate_corrected_retry(bad, 'draft', KEY, [record])
            with self.assertRaises(ValueError):
                Runtime.validate_corrected_retry(job, 'draft', 'wrong-key', [record])

    def test_pinned_source_and_artifact_are_required(self):
        from fleece_revision_recovery import load_proof, RESPONSE
        job, record = fixture()
        source = {'theme': job['theme'], 'productIds': IDS,
                  'catalog':job['revisionContext']['candidateProducts']}
        artifact = dict(responseId=RESPONSE, model='claude-opus-4-8', content=json.dumps({
            'article':{'productIds':IDS[::-1]}, 'brief':{'format':'comparison'}}))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'model-artifacts').mkdir(); (root/'research').mkdir()
            ap = root/'model-artifacts'/(hashlib.sha256(RESPONSE.encode()).hexdigest()+'.json')
            sp = root/'research'/(JOB+'.json')
            ap.write_text(json.dumps(artifact)); sp.write_text(json.dumps(source))
            with patch('fleece_revision_recovery.ARTIFACT_SHA',hashlib.sha256(ap.read_bytes()).hexdigest()), \
                 patch('fleece_revision_recovery.SOURCE_SHA',hashlib.sha256(sp.read_bytes()).hexdigest()), \
                 patch('fleece_revision_recovery.CONTEXT_SHA', fingerprint(job['revisionContext'])):
                proof = load_proof(root, job, KEY)
                self.assertEqual(KEY, proof['oldStageKey'])
                self.assertEqual(RESPONSE, proof['responseId'])
                old_source, old_artifact = sp.read_bytes(), ap.read_bytes()
                for path, old in ((sp, old_source), (ap, old_artifact)):
                    path.write_text('{}')
                    with self.assertRaises(ValueError): load_proof(root, job, KEY)
                    path.write_bytes(old)
                ap.unlink(); ap.symlink_to(sp)
                with self.assertRaises(ValueError): load_proof(root, job, KEY)


class FleeceRuntimeRetryTests(unittest.TestCase):
    def setUp(self):
        import test_revision_workflow as workflow
        workflow.RevisionWorkflowTests.setUp(self)
        self.config['executionPolicy'] = {'mode':'deterministic', 'suspended':False}

    def tearDown(self):
        import test_revision_workflow as workflow
        workflow.RevisionWorkflowTests.tearDown(self)

    def test_one_pinned_recovery_preserves_parent_usage_budget_and_blocks_repeat(self):
        import fleece_revision_recovery as f
        from runtime import atomic
        job, _ = fixture()
        with self.runtime.ledger._tx() as db:
            db.execute('INSERT INTO jobs VALUES (?,?)',(JOB,json.dumps(job)))
        old_inputs = {'dependencies':{'prompt':'old'}, 'schemaVersion':1}
        new_inputs = {'dependencies':{'prompt':'new'}, 'schemaVersion':1}
        with self.assertRaises(ModelError):
            self.runtime.stage_journal.run(JOB, 'draft', old_inputs,
                lambda: (_ for _ in ()).throw(ModelError(f.REASON)))
        old_key = self.runtime.stage_journal.key(JOB, 'draft', old_inputs)
        self.runtime.stage_journal.record_usage(JOB, 'draft', old_key, [{'responseId':f.RESPONSE, 'usage':{}}])
        old = copy.deepcopy(self.runtime.stage_journal.status(job_id=JOB)['records'][0])
        marker = self.runtime.root/'revision-production-attempts'/(JOB+'.json')
        atomic(marker, {'status':'blocked','reason':f.REASON})
        original_marker = marker.read_bytes()
        artifact = {'responseId':f.RESPONSE,'model':'claude-opus-4-8','content':json.dumps({
            'article':{'productIds':IDS[::-1]},'brief':{'format':'comparison'}})}
        source = {'theme':job['theme'],'productIds':IDS,
                  'catalog':job['revisionContext']['candidateProducts']}
        ap = self.runtime.root/'model-artifacts'/(hashlib.sha256(f.RESPONSE.encode()).hexdigest()+'.json')
        sp = self.runtime.root/'research'/(JOB+'.json')
        atomic(ap, artifact); atomic(sp, source)
        with self.runtime.ledger._tx() as db:
            budget_before = db.execute('SELECT * FROM model_budget_reservations').fetchall()
        self.runtime._context = Mock(return_value={})
        def make_article(current, context):
            return self.runtime._run_model_stage(current,'draft',new_inputs,
                lambda: {'status':'awaiting_astra_review'},'claude-opus-4-8')
        self.runtime._make_article = Mock(side_effect=make_article)
        with patch.object(f,'OLD_KEY',old_key), patch.object(f,'CONTEXT_SHA',fingerprint(job['revisionContext'])), \
             patch.object(f,'ARTIFACT_SHA',hashlib.sha256(ap.read_bytes()).hexdigest()), \
             patch.object(f,'SOURCE_SHA',hashlib.sha256(sp.read_bytes()).hexdigest()):
            result = self.runtime.retry_corrected_stage(JOB,'draft',old_key)
            self.assertEqual('completed',result['status'])
            records = self.runtime.stage_journal.status(job_id=JOB)['records']
            parent = next(r for r in records if r['stageKey']==old_key)
            child = next(r for r in records if r.get('predecessorKey')==old_key)
            self.assertEqual((2,2,1),(child['attempts'],child['maxAttempts'],child['inheritedAttempts']))
            for key,value in old.items():
                if key!='updatedAt': self.assertEqual(value,parent[key],key)
            receipt_path = self.runtime.root/'revision-stage-retries'/JOB/(hashlib.sha256(old_key.encode()).hexdigest()+'.json')
            proof = json.loads(receipt_path.read_text())['recoveryEvidence']
            self.assertEqual(old_key,proof['oldStageKey'])
            self.assertFalse(proof['savedWriterReused'])
            with self.assertRaises(Exception): self.runtime.retry_corrected_stage(JOB,'draft',old_key)
        self.runtime._make_article.assert_called_once()
        self.assertEqual(original_marker,marker.read_bytes())
        saved = self.runtime.ledger.get_job(JOB)
        self.assertIsNone(saved['approval']); self.assertIsNone(saved['publication'])
        with self.runtime.ledger._tx() as db:
            self.assertEqual(budget_before,db.execute('SELECT * FROM model_budget_reservations').fetchall())


if __name__ == '__main__': unittest.main()
