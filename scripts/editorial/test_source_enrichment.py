"""Same-job source-only handoff with real SQLite, offline HTML and no models."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ledger import Ledger, fingerprint
import source_enrichment as e
import topic_selection as t
from test_topic_selection import NOW, proposal
from test_topic_selection_fit_sources import fixture_feed, request_from_feed


def pilot(feed, enriched=False):
    ids = ['gsc:one', 'public:thermos-product-parts', 'public:thermos-parts-product']
    if enriched:
        ids += ['public:' + t.SOURCE_IDS[u] for u in t.FIT_EXAMPLES]
    return t.bind_nonproduct_theme(proposal(e.PILOT_SLUG, 'サーモスのパッキンを品番から探すには？',
        categoryId='tumbler', outline=['製品の情報で探す', '部品の情報で探す', '品番と色名とJANで適合例を確認'],
        sourceIds=ids), feed)


def rehash_reference(ref):
    ref['excerptSha256'] = t._sha(ref['excerpt'])
    receipt = {k: ref[k] for k in ('url', 'canonicalUrl', 'checkedAt', 'httpStatus', 'excerpt', 'claimScope')}
    receipt['id'] = ref['id'].removeprefix('public:')
    ref['receiptSha256'] = t._sha(t._canonical(receipt))


class SourceEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'state'
        self.ledger = Ledger(self.root, 'owner')
        self.feed = fixture_feed()
        self.theme = pilot(self.feed)
        self.expanded = pilot(self.feed, True)
        self.job = dict(id=e.PILOT_JOB_ID, week='2026-11-20', theme=self.theme,
            stage='error', bundle=None, revision=None, review=None, astraReview=None,
            approval=None, publication=None, social=None, error={'reason': 'final_review_failed'},
            created_at=NOW.isoformat())
        with self.ledger._tx() as db:
            self.ledger._put(db, self.job, 'fixture')
        self.job = self.ledger.get_job(e.PILOT_JOB_ID)
        self.reader = request_from_feed(self.feed)

    def receipt(self):
        return e.prepare(self.job, self.expanded, self.reader, now=NOW)

    def test_prepare_is_readonly_and_apply_archives_old_contract_and_keeps_held(self):
        before = copy.deepcopy(self.job)
        for name in ('model-budget.json', 'stage-journal.json'):
            (self.root / name).write_text('{"used":17,"knownFailed":true}')
        files = {p.name: p.read_bytes() for p in self.root.glob('*.json')}
        receipt = self.receipt()
        self.assertEqual(before, self.ledger.get_job(e.PILOT_JOB_ID))
        self.assertEqual(receipt, e.validate(self.job, receipt))
        from model_budget import ModelBudget
        from production_schedule import ProductionSchedule
        budget = ModelBudget(self.root, ProductionSchedule())
        budget_id = 'article:' + fingerprint({'slug': self.theme['slug']})
        budget.import_usage([dict(responseId='fixture-prior-actual', articleId=budget_id,
            stage='draft', at=NOW.isoformat(), input=37, output=19)])
        snapshot = budget.inspect(NOW)
        self.assertEqual(1, snapshot['articles'][budget_id]['calls'])
        result = self.ledger.extend_nonproduct_sources(e.PILOT_JOB_ID, receipt)
        self.assertEqual(snapshot, budget.inspect(NOW))
        self.assertEqual('held', result['stage'])
        self.assertEqual('source_enrichment_ready', result['holdReason'])
        self.assertEqual(self.expanded, result['theme'])
        self.assertEqual(before['theme'], result['sourceEnrichments'][0]['previousTheme'])
        self.assertEqual(receipt, result['sourceEnrichments'][0])
        self.assertEqual(files, {p.name: p.read_bytes() for p in self.root.glob('*.json')})
        for key in ('id', 'week', 'created_at', 'approval', 'publication', 'bundle', 'revision'):
            self.assertEqual(before[key], result[key])
        with self.ledger._tx() as db:
            self.assertEqual(1, db.execute('SELECT count(*) FROM jobs').fetchone()[0])
            self.assertEqual(2, db.execute('SELECT count(*) FROM events').fetchone()[0])
            self.assertEqual(0, db.execute('SELECT count(*) FROM requests').fetchone()[0])
        with self.assertRaises(e.SourceEnrichmentError):
            e.apply(self.ledger, e.PILOT_JOB_ID, receipt)

    def test_prepare_rejects_nonpilot_staged_or_approved_jobs_before_http(self):
        cases = []
        for key, value in (('id', 'other'), ('week', None), ('stage', 'review'),
                           ('bundle', {}), ('revision', 'old'), ('approval', {}),
                           ('publication', {}), ('social', {}), ('astraReview', {})):
            cases.append(dict(self.job, **{key: value}))
        bad = copy.deepcopy(self.job); bad['theme']['slug'] = 'other'; cases.append(bad)
        bad = copy.deepcopy(self.job); bad['theme']['productIds'] = ['product']; cases.append(bad)
        for job in cases:
            with self.subTest(job=job.get('id'), stage=job.get('stage')):
                reader = lambda *args: self.fail('HTTP must not run for an ineligible job')
                with self.assertRaises(ValueError):
                    e.prepare(job, self.expanded, reader, now=NOW)

    def test_later_enrichment_preserves_prior_archive_and_same_job(self):
        first = self.ledger.extend_nonproduct_sources(e.PILOT_JOB_ID, self.receipt())
        archive = copy.deepcopy(first['sourceEnrichments'])
        feed = copy.deepcopy(self.feed)
        ref = next(r for r in feed['sources'] if r['id'] == 'public:thermos-product-parts')
        ref['excerpt'] += '\n\n製品の品番は底面のラベルで確認してください。'
        rehash_reference(ref)
        second = e.prepare(first, pilot(feed, True), request_from_feed(feed), now=NOW)
        result = self.ledger.extend_nonproduct_sources(e.PILOT_JOB_ID, second)
        self.assertEqual(archive, result['sourceEnrichments'][:-1])
        self.assertEqual(first['theme'], result['sourceEnrichments'][-1]['previousTheme'])
        self.assertEqual(first['id'], result['id'])
        self.assertEqual(first['week'], result['week'])
        self.assertEqual('held', result['stage'])

    def test_only_four_theme_fields_editable_no_nonpublic_source_or_old_id_drop(self):
        for field, value in (('title', 'changed'), ('slug', 'changed'), ('categoryId', 'tent'),
                             ('productIds', ['fake']), ('priority', 1)):
            theme = copy.deepcopy(self.expanded); theme[field] = value
            with self.assertRaisesRegex(e.SourceEnrichmentError, 'fixed_theme_changed'):
                e.prepare(self.job, theme, self.reader, now=NOW)
        theme = copy.deepcopy(self.expanded); theme['sourceIds'][0] = 'gsc:invented'
        with self.assertRaisesRegex(e.SourceEnrichmentError, 'nonpublic_sources_changed'):
            e.prepare(self.job, theme, self.reader, now=NOW)
        theme = copy.deepcopy(self.expanded)
        theme['sourceIds'].remove('public:thermos-product-parts')
        theme = t.bind_nonproduct_theme(theme, self.feed)
        with self.assertRaisesRegex(e.SourceEnrichmentError, 'old_source_dropped'):
            e.prepare(self.job, theme, self.reader, now=NOW)

    def test_expanded_old_excerpt_preserves_every_original_block_in_order(self):
        feed = copy.deepcopy(self.feed)
        ref = next(r for r in feed['sources'] if r['id'] == 'public:thermos-product-parts')
        ref['excerpt'] += '\n\n製品の品番は底面のラベルで確認してください。'
        rehash_reference(ref)
        theme = pilot(feed, True)
        receipt = e.prepare(self.job, theme, request_from_feed(feed), now=NOW)
        self.assertTrue(receipt['proposedTheme']['nonProductContract']['references'][0]['excerpt'].startswith(
            self.theme['nonProductContract']['references'][0]['excerpt']))
        for replacement in ('original paragraph rewritten', '\n\n'.join(reversed(ref['excerpt'].split('\n\n')))):
            bad = copy.deepcopy(feed)
            badref = next(r for r in bad['sources'] if r['id'] == ref['id'])
            badref['excerpt'] = replacement
            rehash_reference(badref)
            with self.assertRaisesRegex(e.SourceEnrichmentError, 'old_excerpt_changed'):
                e.prepare(self.job, pilot(bad, True), request_from_feed(bad), now=NOW)

    def test_fresh_http_and_complete_recheck_proof_are_required(self):
        def bad_request(url, headers):
            value = self.reader(url, headers)
            value['url'] += '#changed'
            return value
        with self.assertRaises(t.NonproductSourceHold):
            e.prepare(self.job, self.expanded, bad_request, now=NOW)
        receipt = self.receipt()
        for field, value in (('sourceRecheck', {'verified': True}), ('expectedJobHash', 'a' * 64),
                             ('previousTheme', {}), ('week', '2026-11-27')):
            bad = copy.deepcopy(receipt); bad[field] = value
            with self.assertRaises(ValueError): e.validate(self.job, bad)
        for mutate in ('missing', 'hash', 'url', 'time'):
            bad = copy.deepcopy(receipt)
            observations = bad['sourceRecheck']['observations']
            if mutate == 'missing': observations.pop()
            elif mutate == 'hash': observations[-1]['boundExcerptSha256'] = 'f' * 64
            elif mutate == 'url': observations[-1]['url'] += '#wrong'
            else: observations[-1]['checkedAt'] = '2020-01-01T00:00:00+09:00'
            bad['receiptSha256'] = fingerprint({k: v for k, v in bad.items() if k != 'receiptSha256'})
            with self.assertRaises(e.SourceEnrichmentError): e.validate(self.job, bad)

    def test_apply_cas_requests_effects_and_rollback_without_global_effect_block(self):
        receipt = self.receipt()
        for table in ('requests', 'effects'):
            with self.ledger._tx() as db:
                if table == 'requests':
                    db.execute('INSERT INTO requests VALUES (?,?,?,?)', ('fixture', e.PILOT_JOB_ID, 'article', '{}'))
                else:
                    db.execute('INSERT INTO effects VALUES (?,?,?,?)', (e.PILOT_JOB_ID, 'stage', 'failed', '{}'))
            with self.assertRaisesRegex(e.SourceEnrichmentError, 'side_effects'):
                e.apply(self.ledger, e.PILOT_JOB_ID, receipt)
            with self.ledger._tx() as db: db.execute('DELETE FROM ' + table)
            self.assertEqual(self.job, self.ledger.get_job(e.PILOT_JOB_ID))
        with self.ledger._tx() as db:
            db.execute('INSERT INTO effects VALUES (?,?,?,?)', ('unrelated-job', 'publish', 'unknown', '{}'))
        real_put = self.ledger._put
        def fail_after_put(db, job, kind):
            real_put(db, job, kind)
            raise RuntimeError('fixture failure')
        with patch.object(self.ledger, '_put', side_effect=fail_after_put):
            with self.assertRaisesRegex(RuntimeError, 'fixture failure'):
                e.apply(self.ledger, e.PILOT_JOB_ID, receipt)
        self.assertEqual(self.job, self.ledger.get_job(e.PILOT_JOB_ID))
        result = e.apply(self.ledger, e.PILOT_JOB_ID, receipt)
        self.assertEqual('held', result['stage'])
        with self.assertRaises(e.SourceEnrichmentError):
            e.validate(dict(self.job, updated_at='changed'), receipt)


if __name__ == '__main__':
    unittest.main()
