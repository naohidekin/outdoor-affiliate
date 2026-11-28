"""Offline contracts for the one-shot 2026-11-27 owner pool completion."""
import copy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ledger import JST, canonical
from models import Models, ModelOutcomeUnknown
from regular_backfill import backfill
from runtime import Runtime, atomic
from search_demand import classify_topic
from test_models import ENV, Fake, response
from test_runtime import SlackFake
from test_topic_selection import demand_signal, proposal
from test_topic_selection_softshell_sources import collect as source_feed, fixture as source_fixture


NOW = datetime(2026, 11, 27, 10, tzinfo=JST)
PERIOD = '2026-11-27'
FLEECE = ['apparel-montbell-1114881', 'apparel-montbell-1106832']
DOWN = ['apparel-montbell-1101493', 'apparel-montbell-1101606']
PRODUCT_IDS = FLEECE + DOWN


class CatalogFixture:
    def __init__(self, value):
        self.value = value

    def catalog(self):
        return copy.deepcopy(self.value)

    def request(self, *_args, **_kwargs):
        raise AssertionError('network forbidden')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ResearchPoolCompletionTests(unittest.TestCase):
    def setUp(self):
        import research_pool_completion as completion
        self.completion = completion
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        env = base / 'env'
        env.write_text('AMAZON_PARTNER_TAG=camp78-22\n')
        self.config = {
            'stateRoot': str(base / 'state'), 'repo': str(Path(__file__).resolve().parents[2]),
            'envFile': str(env), 'spoolDir': str(base / 'spool'),
            'slack': dict(team_id='T', app_id='A', user_id='owner', channel_id='C', thread_ts='1.1'),
            'generationEnabled': True, 'publicationEnabled': False,
            'productionSchedule': dict(weekday=4, hour=9, effectiveFrom='2026-11-13',
                initialProductionAt='2026-11-08T00:00:00+09:00')}
        Path(self.config['spoolDir']).mkdir()
        self.feed = source_feed(source_fixture())
        self.catalog = self.make_catalog()
        self.signals = self.make_signals()
        self.pinned, self.new = self.make_proposals()
        answer = response({'proposals': copy.deepcopy(self.new)})
        answer['id'] = 'owner-completion-response'
        self.request = Fake(answer)
        self.runtime = Runtime(self.config, models=Models(ENV, self.request),
            catalog=CatalogFixture(self.catalog), slack=SlackFake(),
            publisher=lambda *_: self.fail('publication forbidden'))
        self.owner = {'source': 'codex', 'thread_id': 'thread-fixture',
                      'message_id': 'message-fixture',
                      'text': '不足二案の調査と週三本の通常制作を承認する。'}
        self.write_inputs()
        self.write_source_proofs()
        self.write_history()

    def make_catalog(self):
        names = ('Chameece', 'ClimaAir Light', 'Plasma 1000', 'Light Alpine')
        products = [{'id': pid, 'name': name, 'brand': 'mont-bell',
                     'categoryId': 'wear', 'specs': {'fixture': name},
                     'amazonUrl': 'https://www.amazon.co.jp/dp/' + ('A' * 10),
                     'rakutenUrl': 'https://item.rakuten.co.jp/fixture/' + pid,
                     'yahooUrl': '', 'imageUrl': 'https://images.example/' + pid + '.jpg',
                     'updatedAt': '2026-11-27T00:00:00+09:00'}
                    for pid, name in zip(PRODUCT_IDS, names)]
        articles = [{'id': 'article-%03d' % i, 'slug': 'existing-%03d' % i,
                     'title': '既存キャンプ記事 %03d' % i, 'categoryId': 'camp-howto',
                     'query': '既存キャンプ情報 %03d' % i,
                     'headings': ['既存見出し'], 'excerpt': '既存記事です。'}
                    for i in range(154)]
        return {'products': products, 'articles': articles,
                'categories': [{'id': 'wear'}, {'id': 'camp-howto'}],
                'clicks': [{'productId': DOWN[0], 'clicks': 1}]}

    def make_signals(self):
        topics = [('fleece', 'モンベル フリース Chameece ClimaAir Light 比較'),
                  ('down', 'モンベル Plasma 1000 Light Alpine ダウン 比較'),
                  ('shell', 'ハードシェル ソフトシェル 比較 役割')]
        values = [demand_signal('demand:' + key, classify_topic(text),
                                query_count=2, clicks=3, impressions=30)
                  for key, text in topics]
        values.extend({'id': item['id'], 'kind': 'public_reference', 'url': item['url']}
                      for item in self.feed['sources'])
        return values

    def make_proposals(self):
        common = dict(categoryId='wear', proposedAction='new', overlapArticleIds=[],
            overlapRationale='既存154記事とは読者判断と対象が異なる',
            selectionReason='関連する自サイト需要はproxyであり個別query需要は未確認')
        fleece = proposal('montbell-fleece-pair',
            'ChameeceとClimaAir Lightはどう比較する？', 95, **common,
            title='ChameeceとClimaAir Lightの比較', query='モンベル フリース 比較',
            topicType='product', productIds=FLEECE, sourceIds=['demand:fleece'],
            outline=['違い', '仕様', '選び分け'])
        down = proposal('montbell-down-pair',
            'Plasma 1000とLight Alpineはどう比較する？', 94, **common,
            title='Plasma 1000とLight Alpineの比較', query='モンベル ダウン 比較',
            topicType='product', productIds=DOWN, sourceIds=['demand:down'],
            outline=['違い', '仕様', '選び分け'])
        shell = proposal('hard-soft-shell-roles',
            'ハードシェルとソフトシェルは登山でどう役割を分ける？', 93, **common,
            title='ハードシェルとソフトシェルの役割比較', query='ハードシェル ソフトシェル 比較',
            topicType='knowhow', productIds=[],
            sourceIds=['demand:shell', 'public:montbell-layering',
                       'public:montbell-softshell-roles'],
            outline=['ソフトシェルの役割', 'はっ水性と防水性の違い',
                     '完全防水ハードシェルの別携行', '通気性がない例外'])
        return fleece, [down, shell]

    def paths(self):
        root = self.runtime.root
        return {'marker': root / 'production-attempts' / (PERIOD + '.json'),
                'period_receipt': root / 'period-receipts' / (PERIOD + '.json'),
                'update_proposal': root / 'existing-update-proposals' / (PERIOD + '.json'),
                'context': root / 'research-contexts' / (PERIOD + '.json'),
                'public_feed': root / 'public-sources' / (PERIOD + '.json')}

    def write_inputs(self):
        values = {
            'marker': {'status': 'selection_hold', 'period': PERIOD,
                'holdReason': 'insufficient_qualified_period_pool', 'eligibleCount': 1,
                'unfilled': 2, 'selection': 'hold', 'proposals': [self.pinned],
                'responseId': 'old-research-1'},
            'period_receipt': {'period': PERIOD, 'status': 'hold', 'eligibleCount': 1,
                'unfilled': 2, 'decisions': [{'status': 'hold',
                    'reason': 'insufficient_qualified_period_pool', 'proposal': self.pinned}]},
            'update_proposal': {'period': PERIOD, 'status': 'no_update_proposals', 'proposals': []},
            'context': {'period': PERIOD, 'editorialSignals': self.signals},
            'public_feed': self.feed}
        for key, value in values.items():
            atomic(self.paths()[key], value)

    def write_source_proofs(self, ready=True, products=None, candidate_ids=()):
        products = products or self.catalog['products']
        folder = self.runtime.root / 'planning-completions' / self.completion.SOURCE_FOLDER
        indexed = {item['id']: item for item in products}
        for pid in PRODUCT_IDS:
            checks = {'facts': True, 'images': True, 'affiliate': bool(ready)}
            evidence = {'productId': pid, 'checkedAt': (NOW - timedelta(hours=1)).isoformat(),
                        **checks, 'destinations': [
                            {'channel': channel, 'verified': bool(ready)}
                            for channel in ('amazon', 'rakuten')]}
            value = {'blocked': False, 'productIds': [pid],
                     'products': [copy.deepcopy(indexed[pid])], 'checks': checks,
                     'evidence': {'products': [evidence]}}
            suffix = '-candidate-source.json' if pid in candidate_ids else '-source.json'
            atomic(folder / (pid + suffix), value)

    def write_history(self):
        repair = {'status': 'held', 'repairsUsed': 1, 'maxRepairs': 1,
                  'resultStatus': 'selection_hold', 'manifest': {'period': PERIOD}}
        with self.runtime.ledger._tx() as db:
            db.execute('INSERT INTO meta VALUES (?,?)',
                ('research_response_recovery:v1:' + PERIOD, canonical(repair)))
        for index in range(2):
            with self.runtime.model_budget.scope('research:' + PERIOD, 'research', now=NOW):
                reservation = self.runtime.model_budget.reserve(
                    {'model': 'claude-sonnet-4-6', 'max_tokens': 8, 'messages': []})
                self.runtime.model_budget.settle(reservation,
                    usage={'input_tokens': 1, 'output_tokens': 1},
                    response_id='old-research-%d' % index)
        artifact = {'responseId': 'old-research-1', 'model': 'claude-sonnet-4-6',
                    'usage': {'input_tokens': 1, 'output_tokens': 1},
                    'content': json.dumps({'proposals': [self.pinned]},
                                          ensure_ascii=False)}
        atomic(self.runtime.root / 'model-artifacts' /
               (hashlib.sha256(b'old-research-1').hexdigest() + '.json'), artifact)

    def old_artifact(self):
        return self.runtime.root / 'model-artifacts' / (
            hashlib.sha256(b'old-research-1').hexdigest() + '.json')

    def hashes(self):
        return {key: sha(path) for key, path in self.paths().items()}

    def prepare(self, **kwargs):
        with patch('research_pool_completion.require_fresh_daily_metrics'):
            return self.completion.prepare(self.runtime, owner_instruction=self.owner,
                now=NOW, **self.hashes(), **kwargs)

    def correction(self):
        base = copy.deepcopy(self.catalog['products'][2:])
        candidate = copy.deepcopy(base)
        candidate[1]['amazonUrl'] = 'https://www.amazon.co.jp/dp/' + ('X' * 10)
        candidate[1]['updatedAt'] = '2026-11-27T09:30:00+09:00'
        return {'baseProducts': base, 'candidateProducts': candidate,
                'changeSummary': 'Light AlpineのAmazon候補を検証済みXLへ変更'}

    def execute(self, manifest):
        with patch('research_pool_completion.require_fresh_daily_metrics'), \
                patch('research_pool_completion.collect_primary_sources', return_value=self.feed), \
                patch.object(self.runtime, '_context', return_value={
                    'products': copy.deepcopy(self.catalog['products']),
                    'catalog': copy.deepcopy(self.catalog['products']),
                    'categories': copy.deepcopy(self.catalog['categories']),
                    'existingArticles': copy.deepcopy(self.catalog['articles']),
                    'queuedThemes': [], 'editorialSignals': copy.deepcopy(self.signals)}), \
                patch.object(self.runtime, '_research_context', side_effect=lambda base, **_: {
                    **copy.deepcopy(base), 'editorialSignals': copy.deepcopy(self.signals),
                    'categories': copy.deepcopy(self.catalog['categories'])}):
            return self.completion.execute(self.runtime, manifest,
                owner_grant=self.completion.owner_grant(manifest), now=NOW)

    def snapshot(self):
        return {path: path.read_bytes() for path in self.runtime.root.rglob('*') if path.is_file()}

    def test_prepare_is_readonly_and_source_readiness_fails_before_claim(self):
        before = self.snapshot()
        manifest = self.prepare()
        self.assertEqual(before, self.snapshot())
        self.assertEqual(PRODUCT_IDS, manifest['sourceReadiness']['requiredProductIds'])
        self.assertEqual(FLEECE, manifest['pinnedProposal']['productIds'])
        self.write_source_proofs(ready=False)
        with self.assertRaisesRegex(ValueError, 'source_not_ready|stale_or_incomplete'):
            self.prepare()
        self.assertEqual([], self.request.calls)
        self.assertFalse((self.runtime.root / 'research-pool-completion').exists())

    def test_old_held_artifact_is_exactly_bound_and_tampering_blocks_preclaim(self):
        manifest = self.prepare()
        self.assertEqual('old-research-1', manifest['heldModelArtifact']['responseId'])
        self.assertEqual(sha(self.old_artifact()),
                         manifest['heldModelArtifact']['sha256'])
        original = json.loads(self.old_artifact().read_text())
        changes = [dict(original, model='different-model'),
                   dict(original, usage={'input_tokens': 2, 'output_tokens': 1}),
                   dict(original, content=json.dumps({'proposals': []}))]
        for changed in changes:
            with self.subTest(changed=changed):
                atomic(self.old_artifact(), changed)
                with self.assertRaisesRegex(ValueError, 'old_artifact_binding'):
                    self.prepare()
                self.assertEqual([], self.request.calls)
                self.assertFalse((self.runtime.root / 'research-pool-completion').exists())
                atomic(self.old_artifact(), original)

    def test_source_proof_stale_wrong_product_or_one_channel_never_claims(self):
        folder = self.runtime.root / 'planning-completions' / self.completion.SOURCE_FOLDER
        path = folder / (DOWN[1] + '-source.json')
        original = json.loads(path.read_text())
        mutations = []
        stale = copy.deepcopy(original)
        stale['evidence']['products'][0]['checkedAt'] = (NOW - timedelta(hours=7)).isoformat()
        mutations.append(stale)
        wrong = copy.deepcopy(original)
        wrong['products'][0]['name'] = 'unbound candidate'
        mutations.append(wrong)
        one_channel = copy.deepcopy(original)
        one_channel['evidence']['products'][0]['destinations'][0]['verified'] = False
        mutations.append(one_channel)
        for value in mutations:
            with self.subTest(value=value['evidence']['products'][0]):
                atomic(path, value)
                with self.assertRaisesRegex(ValueError,
                        'source_not_ready|stale_or_incomplete'):
                    self.prepare()
                self.assertEqual([], self.request.calls)
                self.assertFalse((self.runtime.root / 'research-pool-completion').exists())
                atomic(path, original)

    def test_catalog_correction_is_hash_bound_uses_candidate_proof_and_reaches_down_job(self):
        raw = self.correction()
        candidate_products = self.catalog['products'][:2] + raw['candidateProducts']
        self.write_source_proofs(products=candidate_products, candidate_ids={DOWN[1]})
        manifest = self.prepare(catalog_correction=raw)
        bound = manifest['catalogCorrectionContext']
        self.assertEqual(DOWN, [item['id'] for item in bound['baseProducts']])
        patch_row = bound['productPatches'][0]
        self.assertEqual(DOWN[1], patch_row['id'])
        self.assertNotEqual(patch_row['baseHash'], patch_row['candidateHash'])
        result = self.execute(manifest)
        jobs = [job for job in self.runtime.ledger.list_jobs()
                if job['id'] in result['createdJobIds']]
        down = next(job for job in jobs if job['theme']['productIds'] == DOWN)
        self.assertEqual(bound, down['catalogCorrectionContext'])
        self.assertIsNone(down['approval'])
        self.assertIsNone(down['publication'])

    def test_catalog_correction_rejects_live_base_or_candidate_proof_drift(self):
        raw = self.correction()
        candidate_products = self.catalog['products'][:2] + raw['candidateProducts']
        self.write_source_proofs(products=candidate_products, candidate_ids={DOWN[1]})
        manifest = self.prepare(catalog_correction=raw)
        changed = copy.deepcopy(raw)
        changed['changeSummary'] += ' changed'
        with self.assertRaisesRegex(ValueError, 'manifest_changed|owner_grant_required'):
            self.completion.execute(self.runtime, dict(manifest,
                catalogCorrectionContext=changed),
                owner_grant=self.completion.owner_grant(manifest), now=NOW)
        self.assertEqual([], self.request.calls)
        self.catalog['products'][2]['name'] = 'live drift'
        with self.assertRaisesRegex(ValueError, 'catalog baseline changed|manifest_changed'):
            self.execute(manifest)
        self.assertEqual([], self.request.calls)

    def test_backfill_persists_correction_until_its_deferred_slot_is_created(self):
        from catalog_corrections import validated_context
        correction = validated_context(self.correction())
        carries = []
        for index in range(2):
            job = self.runtime.ledger.create_candidate({'slug': 'carry-%d' % index},
                NOW - timedelta(days=7))
            self.runtime.ledger.set_stage(job['id'], 'review')
            carries.append(job)
        themes = [{'slug': 'plain-a', 'productIds': []},
                  {'slug': 'plain-b', 'productIds': []},
                  {'slug': 'down-corrected', 'productIds': DOWN}]
        first = backfill(self.runtime.ledger, PERIOD, themes, NOW,
                         catalog_corrections={'down-corrected': correction})
        self.assertEqual(['plain-a'], [job['theme']['slug'] for job in first])
        for job in carries + first:
            with self.runtime.ledger._tx() as db:
                current = self.runtime.ledger._get(db, job['id'])
                current.update(stage='published', publication={'verified': True})
                self.runtime.ledger._put(db, current, 'fixture_release')
        rest = backfill(self.runtime.ledger, PERIOD, themes, NOW)
        deferred = next(job for job in rest if job['theme']['slug'] == 'down-corrected')
        self.assertEqual(correction, deferred['catalogCorrectionContext'])
        self.assertIsNone(deferred['approval'])
        self.assertIsNone(deferred['publication'])

    def test_clicks_change_is_not_catalog_drift(self):
        manifest = self.prepare()
        self.catalog['clicks'] = [{'productId': DOWN[0], 'clicks': 999999}]
        result = self.execute(manifest)
        self.assertEqual('ready_for_normal_producer', result['status'])
        self.assertEqual(1, len(self.request.calls))

    def test_success_claims_before_call_archives_exact_inputs_and_is_idempotent(self):
        manifest = self.prepare()
        originals = {key: path.read_bytes() for key, path in self.paths().items()}
        observed = []
        original_call = self.runtime._measured_model_call
        def measured(*args, **kwargs):
            with self.runtime.ledger._tx() as db:
                observed.append(json.loads(db.execute('SELECT value FROM meta WHERE key=?',
                    (self.completion.KEY,)).fetchone()[0])['status'])
            return original_call(*args, **kwargs)
        with patch.object(self.runtime, '_measured_model_call', side_effect=measured):
            result = self.execute(manifest)
        self.assertEqual('ready_for_normal_producer', result['status'])
        self.assertEqual(['evidence_ready'], observed)
        self.assertEqual(1, len(self.request.calls))
        archive = self.runtime.root / 'research-pool-completion' / PERIOD
        for key, raw in originals.items():
            self.assertEqual(raw, (archive / ('old-' + key.replace('_', '-') + '.json')).read_bytes())
        self.assertEqual(self.old_artifact().read_bytes(),
                         (archive / 'old-model-artifact.json').read_bytes())
        marker = json.loads(self.paths()['marker'].read_text())
        self.assertEqual([FLEECE, DOWN, []], [item['productIds'] for item in marker['proposals']])
        self.assertEqual(result, self.execute(manifest))
        self.assertEqual(1, len(self.request.calls))
        paid = json.loads((archive / 'paid-context.json').read_text())
        self.assertEqual(154, len(paid['existingArticles']))
        self.assertNotIn('rawQueries', canonical(paid))

    def test_cas_drift_rejects_before_claim_or_model(self):
        manifest = self.prepare()
        atomic(self.paths()['marker'], dict(json.loads(self.paths()['marker'].read_text()), drift=True))
        with self.assertRaisesRegex(ValueError, 'input_drift'):
            self.execute(manifest)
        self.assertEqual([], self.request.calls)
        with self.runtime.ledger._tx() as db:
            self.assertIsNone(db.execute('SELECT value FROM meta WHERE key=?',
                                         (self.completion.KEY,)).fetchone())

    def test_old_period_unknown_does_not_block_but_current_unknown_does(self):
        old = NOW - timedelta(days=7)
        with self.runtime.model_budget.scope('research:2026-11-20', 'research', now=old):
            reservation = self.runtime.model_budget.reserve(
                {'model': 'claude-sonnet-4-6', 'max_tokens': 8, 'messages': []})
            self.runtime.model_budget.settle(reservation, outcome='unknown')
        self.prepare()
        with self.runtime.ledger._tx() as db:
            db.execute("UPDATE model_budget_reservations SET status='unknown', outcome='unknown' "
                       "WHERE response_id='old-research-0'")
        with self.assertRaisesRegex(ValueError, 'unknown_state|settled_research_history'):
            self.prepare()
        self.assertEqual([], self.request.calls)

    def test_period_128_budget_cap_holds_without_provider_request(self):
        for index in range(126):
            with self.runtime.model_budget.scope('maintenance:fixture-%03d' % index,
                                                 'fixture', now=NOW):
                reservation = self.runtime.model_budget.reserve(
                    {'model': 'fixture', 'max_tokens': 1, 'messages': []})
                self.runtime.model_budget.settle(reservation,
                    usage={'input_tokens': 0, 'output_tokens': 0},
                    response_id='fixture-%03d' % index)
        result = self.execute(self.prepare())
        self.assertEqual({'status': 'held', 'reason': 'model_budget_hold',
                          'period': PERIOD, 'retryable': False}, result)
        self.assertEqual([], self.request.calls)

    def test_one_existing_pending_allows_only_two_new_unapproved_jobs(self):
        carry = self.runtime.ledger.create_candidate({'slug': 'old-carry'}, NOW - timedelta(days=7))
        self.runtime.ledger.set_stage(carry['id'], 'review')
        result = self.execute(self.prepare())
        self.assertEqual(2, len(result['createdJobIds']))
        jobs = self.runtime.ledger.list_jobs()
        self.assertEqual(3, len(jobs))
        created = [job for job in jobs if job['id'] in result['createdJobIds']]
        self.assertTrue(all(job['approval'] is None and job['publication'] is None
                            and job['social'] is None for job in created))

    def test_model_unknown_is_consumed_once_and_never_recalled(self):
        self.request.results[0] = ModelOutcomeUnknown('fixture unknown')
        manifest = self.prepare()
        with self.assertRaises(ModelOutcomeUnknown):
            self.execute(manifest)
        self.assertEqual(1, len(self.request.calls))
        with self.assertRaisesRegex(ValueError, 'reconciliation'):
            self.execute(manifest)
        self.assertEqual(1, len(self.request.calls))

    def test_two_directions_that_fail_normal_demand_gate_end_in_terminal_hold(self):
        shell = copy.deepcopy(self.new[1])
        shell['sourceIds'] = ['public:montbell-layering',
                              'public:montbell-softshell-roles']
        answer = response({'proposals': [copy.deepcopy(self.new[0]), shell]})
        answer['id'] = 'completion-selection-shortfall'
        self.request.results[0] = answer
        manifest = self.prepare()
        result = self.execute(manifest)
        self.assertEqual({'status': 'held',
                          'reason': 'insufficient_qualified_period_pool',
                          'period': PERIOD, 'retryable': False}, result)
        self.assertEqual(1, len(self.request.calls))
        self.assertEqual([], self.runtime.ledger.list_jobs())
        with self.assertRaisesRegex(ValueError, 'reconciliation'):
            self.execute(manifest)
        self.assertEqual(1, len(self.request.calls))

    def test_wrong_owner_grant_never_claims_or_calls(self):
        manifest = self.prepare()
        grant = self.completion.owner_grant(manifest)
        grant['authorization'] = 'not-owner-granted'
        with self.assertRaisesRegex(ValueError, 'owner_grant_required'):
            self.completion.execute(self.runtime, manifest, owner_grant=grant, now=NOW)
        self.assertEqual([], self.request.calls)


if __name__ == '__main__':
    unittest.main()
