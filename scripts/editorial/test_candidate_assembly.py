"""Pure candidate assembly contracts; no filesystem, provider, or ledger calls."""
import copy
from datetime import datetime, timedelta
import unittest

from candidate_assembly import assemble_candidate
from ledger import JST
from revisions import validated_context
from test_quality import bundle
from test_revision_workflow import baseline, spec


class CandidateAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(JST)
        base = baseline()
        request = spec(base)
        request['baseProducts'][0]['amazonUrl'] = ''
        request['candidateProducts'][0]['amazonUrl'] = ''
        context = validated_context(request)
        self.job = {
            'id': 'revision-one', 'kind': 'article_revision', 'stage': 'candidate',
            'revisionContext': context, 'approval': None, 'publication': None,
            'review': None, 'bundle': None,
        }
        source = bundle()
        source['article'] = copy.deepcopy(base)
        source['products'] = copy.deepcopy(context['candidateProducts'])
        source['revisionContext'] = copy.deepcopy(context)
        self.source_record = {'kind': 'source', 'bundle': source}
        content = source['article']['content'].replace('調査記事です。', '調査済みの記事です。')
        self.polished = {
            'model': 'gemini-3.8-flash', 'content': content,
            'usage': {'input_tokens': 101, 'output_tokens': 99},
            'responseId': 'gemini-real-response',
        }
        self.candidate_record = {'kind': 'candidate', 'candidate': copy.deepcopy(self.polished)}
        self.polish_stage_output = {
            'polished': copy.deepcopy(self.polished),
            'preservation': {'passed': True, 'failures': []},
        }
        checked = self.now.isoformat()
        products = copy.deepcopy(context['candidateProducts'])
        self.gathered = {
            'checks': {'facts': True, 'images': True, 'affiliate': True},
            'productIds': list(context['targetProductIds']),
            'products': copy.deepcopy(products), 'catalog': copy.deepcopy(products),
            'evidence': {'products': [
                {'productId': product['id'], 'checkedAt': checked} for product in products
            ]},
        }
        self.purchase_evidence = [{
            'productId': products[0]['id'], 'channel': 'amazon', 'status': 'NA',
            'reason': '対象型番の取扱いを確認できない', 'checkedAt': checked,
            'reviewedBy': 'owner',
        }]

    def assemble(self, **changes):
        values = {
            'job': self.job, 'source_record': self.source_record,
            'candidate_record': self.candidate_record, 'gathered': self.gathered,
            'purchase_evidence': self.purchase_evidence,
            'polish_stage_output': self.polish_stage_output,
        }
        values.update(changes)
        return assemble_candidate(**values)

    def test_success_reuses_exact_source_and_polish_without_mutating_inputs(self):
        inputs = copy.deepcopy((self.job, self.source_record, self.candidate_record,
                                self.gathered, self.purchase_evidence, self.polish_stage_output))
        source, final, preservation, polished = self.assemble()
        self.assertEqual(self.source_record['bundle'], source)
        self.assertEqual(self.polished, polished)
        self.assertTrue(preservation['passed'])
        self.assertEqual(self.polished['content'], final['article']['content'])
        self.assertEqual(self.purchase_evidence, final['purchaseEvidence'])
        expected = copy.deepcopy(source)
        expected['article']['content'] = self.polished['content']
        expected['purchaseEvidence'] = copy.deepcopy(self.purchase_evidence)
        self.assertEqual(expected, final)
        self.assertEqual(inputs, (self.job, self.source_record, self.candidate_record,
                                 self.gathered, self.purchase_evidence, self.polish_stage_output))

    def test_rejects_wrong_job_or_changed_source_binding(self):
        for change in (
            lambda job, source: job.update(kind='article'),
            lambda job, source: job['revisionContext']['baseArticle'].update(id='article-002'),
            lambda job, source: job.update(approval={'action': 'approved'}),
            lambda job, source: job.update(publication={'verified': True}),
            lambda job, source: job.update(review={'passed': True}),
            lambda job, source: job.update(bundle={}),
            lambda job, source: source['bundle']['revisionContext'].update(baseHash='0' * 64),
            lambda job, source: source['bundle']['products'][0].update(name='changed'),
        ):
            job, source = copy.deepcopy((self.job, self.source_record))
            change(job, source)
            with self.subTest(job=job), self.assertRaises(ValueError):
                self.assemble(job=job, source_record=source)

    def test_rejects_candidate_not_identical_to_succeeded_polish_output(self):
        changed = copy.deepcopy(self.candidate_record)
        changed['candidate']['usage']['output_tokens'] += 1
        with self.assertRaises(ValueError):
            self.assemble(candidate_record=changed)
        changed = copy.deepcopy(self.candidate_record)
        changed['candidate']['model'] = 'gemini-other'
        stage = copy.deepcopy(self.polish_stage_output)
        stage['polished'] = copy.deepcopy(changed['candidate'])
        with self.assertRaises(ValueError):
            self.assemble(candidate_record=changed, polish_stage_output=stage)
        changed = copy.deepcopy(self.candidate_record)
        changed['candidate']['content'] = changed['candidate']['content'].replace('## 選び方', '## 別見出し')
        stage = copy.deepcopy(self.polish_stage_output)
        stage['polished'] = copy.deepcopy(changed['candidate'])
        with self.assertRaises(ValueError):
            self.assemble(candidate_record=changed, polish_stage_output=stage)

    def test_rejects_invalid_or_incomplete_na_evidence(self):
        mutations = []
        mutations.append(lambda evidence, job: evidence[0].update(extra='x'))
        mutations.append(lambda evidence, job: evidence[0].update(channel='yahoo'))
        mutations.append(lambda evidence, job: evidence[0].update(status='unavailable'))
        mutations.append(lambda evidence, job: evidence[0].update(reason=' '))
        mutations.append(lambda evidence, job: evidence[0].update(reviewedBy=''))
        mutations.append(lambda evidence, job: evidence[0].update(checkedAt='2026-11-15'))
        mutations.append(lambda evidence, job: evidence[0].update(
            checkedAt=(self.now + timedelta(hours=1)).isoformat()))
        mutations.append(lambda evidence, job: evidence.append(copy.deepcopy(evidence[0])))
        mutations.append(lambda evidence, job: evidence.clear())
        mutations.append(lambda evidence, job: evidence.append({
            'productId': job['revisionContext']['targetProductIds'][0], 'channel': 'rakuten',
            'status': 'NA', 'reason': '余分', 'checkedAt': self.now.isoformat(),
            'reviewedBy': 'owner'}))
        for mutate in mutations:
            evidence, job = copy.deepcopy((self.purchase_evidence, self.job))
            mutate(evidence, job)
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                self.assemble(job=job, purchase_evidence=evidence)

    def test_rejects_na_evidence_older_than_six_hours(self):
        evidence = copy.deepcopy(self.purchase_evidence)
        evidence[0]['checkedAt'] = '2020-01-01T00:00:00+09:00'
        with self.assertRaises(ValueError):
            self.assemble(purchase_evidence=evidence)

    def test_rejects_na_for_nonempty_url_or_product_without_remaining_destination(self):
        job = copy.deepcopy(self.job)
        context = job['revisionContext']
        for key in ('baseProducts', 'candidateProducts'):
            context[key][0]['amazonUrl'] = 'https://www.amazon.co.jp/dp/B012345678/?tag=camp78-22'
        source = copy.deepcopy(self.source_record)
        source['bundle']['revisionContext'] = copy.deepcopy(context)
        source['bundle']['products'] = copy.deepcopy(context['candidateProducts'])
        gathered = copy.deepcopy(self.gathered)
        gathered['products'] = copy.deepcopy(context['candidateProducts'])
        gathered['catalog'] = copy.deepcopy(context['candidateProducts'])
        with self.assertRaises(ValueError):
            self.assemble(job=job, source_record=source, gathered=gathered)
        job = copy.deepcopy(self.job)
        context = job['revisionContext']
        for key in ('baseProducts', 'candidateProducts'):
            context[key][0]['affiliateUrl'] = ''
        evidence = copy.deepcopy(self.purchase_evidence)
        evidence.append({
            'productId': evidence[0]['productId'], 'channel': 'rakuten', 'status': 'NA',
            'reason': '取扱いなし', 'checkedAt': self.now.isoformat(), 'reviewedBy': 'owner'})
        source = copy.deepcopy(self.source_record)
        source['bundle']['revisionContext'] = copy.deepcopy(context)
        source['bundle']['products'] = copy.deepcopy(context['candidateProducts'])
        gathered = copy.deepcopy(self.gathered)
        gathered['products'] = copy.deepcopy(context['candidateProducts'])
        gathered['catalog'] = copy.deepcopy(context['candidateProducts'])
        with self.assertRaises(ValueError):
            self.assemble(job=job, source_record=source, gathered=gathered,
                          purchase_evidence=evidence)

    def test_rejects_stale_future_or_wrong_selected_gathered_products(self):
        for change in (
            lambda gathered: gathered['evidence']['products'][0].update(
                checkedAt=(self.now - timedelta(hours=6, seconds=1)).isoformat()),
            lambda gathered: gathered['evidence']['products'][0].update(
                checkedAt=(self.now + timedelta(minutes=1)).isoformat()),
            lambda gathered: gathered['checks'].update(facts=False),
            lambda gathered: gathered.update(productIds=['other']),
            lambda gathered: gathered['products'][0].update(name='other'),
        ):
            gathered = copy.deepcopy(self.gathered)
            change(gathered)
            with self.subTest(gathered=gathered), self.assertRaises(ValueError):
                self.assemble(gathered=gathered)


if __name__ == '__main__':
    unittest.main()
