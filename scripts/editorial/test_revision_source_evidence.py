"""Scoped evidence adapter: synthetic clocks/Catalog, no providers or ledger writes."""
import copy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import Mock, patch

from catalog import Catalog
from ledger import fingerprint
from purchase_evidence import require_prewrite_purchase_evidence
from revision_source_evidence import (RevisionSourceEvidence, ARTICLE, SLUG, TNF,
                                      MONTBELL, OFFICIAL_HINTS)
from revisions import validated_context

NOW = datetime(2026, 11, 23, 9, tzinfo=timezone(timedelta(hours=9)))


def fixture():
    products = [dict(id=pid, name=model, brand=brand, categoryId='fleece',
                     updatedAt='2026-11-22T00:00:00+09:00',
                     specs={'model': model, 'gender': "Men's", 'apparelClass': 'fleece',
                            'optionState': 'selectable'},
                     imageUrl='https://maker.example/' + model + '.jpg',
                     affiliateUrl='https://item.rakuten.co.jp/shop/' + model + '/',
                     amazonUrl='' if pid == TNF else 'https://www.amazon.co.jp/dp/B0G75V4CC5')
                for pid, model, brand in ((TNF, 'NA62650', 'THE NORTH FACE'),
                                          (MONTBELL, '1114881', 'mont-bell'))]
    base = dict(id=ARTICLE, slug=SLUG, title='Existing fleece comparison', status='published', categoryId='fleece',
                content='Existing four-product comparison', productIds=['columbia', 'patagonia', TNF, MONTBELL],
                createdAt='2026-10-15T00:00:00+09:00', updatedAt='2026-10-15T00:00:00+09:00',
                publishedAt='2026-10-15T00:00:00+09:00')
    binding = validated_context(dict(baseArticle=base, changeSummary='Two verified products',
        editorialCorrectionInstructions='Keep theme, align title/table/FAQ to two products',
        verifiedAuthorFacts=[], targetProductIds=[TNF, MONTBELL],
        productRemovalReasons={'columbia': 'Unverified primary source', 'patagonia': 'Unverified primary source'},
        baseProducts=products, candidateProducts=copy.deepcopy(products)))
    return binding, dict(articles=[base], products=products, categories=[])


def gathered(binding, now):
    products = copy.deepcopy(binding['candidateProducts'])
    details = []
    for p in products:
        ds = [dict(channel=ch, url=p[field], finalUrl=p[field], verified=True, checkedAt=now.isoformat())
              for ch, field in (('rakuten', 'affiliateUrl'), ('amazon', 'amazonUrl')) if p[field]]
        details.append(dict(productId=p['id'], facts=True, images=True, affiliate=True,
                            checkedAt=now.isoformat(), destinations=ds, claims=[]))
    return dict(products=products, catalog=copy.deepcopy(products), productIds=[TNF, MONTBELL],
                checks=dict(facts=True, images=True, affiliate=True), blocked=False,
                evidence=dict(products=details), images=[], references=[], existingArticles=[])


class RevisionSourceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.binding, self.live = fixture()
        self.now = NOW
        self.historical = gathered(self.binding, NOW - timedelta(minutes=30))
        self.fresh = gathered(self.binding, NOW)
        self.author = dict(kind='source_data', actor='Astra', reference='private/Astra-review.json#receipt',
            revisionContextFingerprint=fingerprint(self.binding),
            officialHintsFingerprint=fingerprint(OFFICIAL_HINTS),
            sourceDataFingerprint=fingerprint(self.historical),
            reviewedAt=(NOW - timedelta(minutes=20)).isoformat(),
            expiresAt=(NOW + timedelta(hours=1)).isoformat(),
            purchaseEvidence=[dict(productId=TNF, channel='amazon', status='NA',
                reason='Observed primary title/alt does not bind exact NA62650; not a stock claim',
                checkedAt=(NOW - timedelta(minutes=30)).isoformat(), reviewedBy='Astra')])
        self.catalog = Catalog({}, fetcher=Mock(side_effect=AssertionError('network forbidden')),
                               source_hints={'unrelated': ['https://maker.example/kept']})
        self.record = Mock()
        self.theme = dict(slug=SLUG, categoryId='fleece', productIds=[TNF, MONTBELL])
        self.writer = Mock()

    def adapter(self, **changes):
        args = dict(context_fingerprint=fingerprint(self.binding), official_hints=OFFICIAL_HINTS,
                    source_data=self.historical, author_evidence=self.author, record=self.record,
                    clock=lambda: self.now)
        args.update(changes)
        return RevisionSourceEvidence(self.catalog, self.binding, **args)

    def run_gather(self, adapter=None, **changes):
        adapter = adapter or self.adapter()
        with patch.object(Catalog, 'gather_revision', autospec=True,
                          side_effect=lambda *args: copy.deepcopy(self.fresh)) as call:
            result = adapter.gather_revision(changes.get('theme', self.theme),
                changes.get('catalog', self.live), changes.get('binding', self.binding))
            return result, call

    def test_fresh_each_time_preserves_historical_author_time_and_records_both(self):
        original = copy.deepcopy((self.historical, self.author, self.live, self.binding))
        adapter = self.adapter()
        result, call = self.run_gather(adapter)
        self.assertEqual(1, call.call_count)
        self.assertIsNot(call.call_args.args[0], self.catalog)
        self.assertEqual(OFFICIAL_HINTS[TNF], call.call_args.args[0].source_hints[TNF])
        self.assertNotIn(TNF, self.catalog.source_hints)
        self.assertEqual('Astra', result['revisionSourceEvidence']['actor'])
        self.assertEqual('source_data', result['revisionSourceEvidence']['recordType'])
        self.assertFalse(result['revisionSourceEvidence']['amazonRefetched'])
        self.assertEqual(self.author['purchaseEvidence'][0]['checkedAt'],
                         result['revisionSourceEvidence']['authorEvidence']['purchaseEvidence'][0]['checkedAt'])
        self.assertEqual(NOW.isoformat(), result['purchaseEvidence'][0]['checkedAt'])
        self.assertEqual(original, (self.historical, self.author, self.live, self.binding))
        require_prewrite_purchase_evidence(result, NOW)
        self.record.assert_called_once_with(result['revisionSourceEvidence'])
        self.now += timedelta(minutes=2)
        self.fresh = gathered(self.binding, self.now)
        again, second = self.run_gather(adapter)
        self.assertEqual(1, second.call_count)
        self.assertNotEqual(result['purchaseEvidence'], again['purchaseEvidence'])
        self.assertEqual(2, self.record.call_count)

    def test_ordinary_catalog_gather_revision_still_collects_each_product(self):
        parts = []
        for p, d in zip(self.fresh['products'], self.fresh['evidence']['products']):
            part = dict(self.fresh, products=[p], catalog=[p], evidence={'products': [d]},
                        categories=[], merchantClicks=[])
            parts.append(part)
        with patch.object(Catalog, 'gather', autospec=True, side_effect=parts) as gather:
            result = self.adapter().gather_revision(self.theme, self.live, self.binding)
        self.assertEqual(2, gather.call_count)
        self.assertEqual([[TNF], [MONTBELL]], [c.args[1]['productIds'] for c in gather.call_args_list])
        self.assertEqual(self.fresh['products'], result['products'])

    def test_expired_or_wrong_author_bindings_rejected_before_get(self):
        cases = [('actor', 'Codex'), ('kind', 'article_approval'), ('reference', ''),
                 ('revisionContextFingerprint', '0' * 64), ('officialHintsFingerprint', '0' * 64),
                 ('sourceDataFingerprint', '0' * 64),
                 ('expiresAt', NOW.isoformat()),
                 ('reviewedAt', (NOW + timedelta(seconds=1)).isoformat()),
                 ('expiresAt', (NOW + timedelta(hours=8)).isoformat())]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                a = dict(self.author, **{key: value})
                with self.assertRaises(ValueError):
                    self.adapter(author_evidence=a)
        self.catalog.fetcher.assert_not_called()

    def test_missing_record_wrong_hints_and_fingerprint_refused(self):
        for args in ({'record': None}, {'official_hints': {TNF: ['https://evil.example/']}},
                     {'context_fingerprint': '0' * 64}, {'source_data': dict(self.historical, products=[])}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.adapter(**args)

    def test_same_ids_cannot_authorize_a_different_model_gender_or_class(self):
        for field, value in (('model', 'NA62650X'), ('gender', "Women's"),
                             ('apparelClass', 'down')):
            with self.subTest(field=field):
                binding = copy.deepcopy(self.binding)
                binding['candidateProducts'][0]['specs'][field] = value
                binding['candidateProducts'][0]['updatedAt'] = NOW.isoformat()
                raw = {k: v for k, v in binding.items() if k not in ('kind', 'baseHash', 'productPatches')}
                binding = validated_context(raw)
                with self.assertRaises(ValueError):
                    RevisionSourceEvidence(self.catalog, binding,
                        context_fingerprint=fingerprint(binding), official_hints=OFFICIAL_HINTS,
                        source_data=gathered(binding, NOW), author_evidence=self.author,
                        record=self.record, clock=lambda: NOW)

    def test_stale_na_wrong_channel_reviewer_and_future_checked_at_refused(self):
        for changes in ({'checkedAt': (NOW - timedelta(hours=7)).isoformat()},
                        {'checkedAt': NOW.isoformat()}, {'channel': 'rakuten'},
                        {'reviewedBy': 'Codex'}, {'productId': MONTBELL}, {'status': 'PASS'}):
            a = copy.deepcopy(self.author); a['purchaseEvidence'][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.adapter(author_evidence=a)

    def test_candidate_or_base_drift_and_other_theme_stop_before_gather(self):
        adapter = self.adapter()
        changed = copy.deepcopy(self.binding); changed['candidateProducts'][0]['amazonUrl'] = 'https://www.amazon.co.jp/dp/B0G4R45GHD'
        live = copy.deepcopy(self.live); live['articles'][0]['content'] += ' changed'
        product_live = copy.deepcopy(self.live); product_live['products'][0]['name'] += ' changed'
        for changes in ({'binding': changed}, {'catalog': live}, {'catalog': product_live},
                        {'theme': dict(self.theme, productIds=[MONTBELL, TNF])}):
            with self.subTest(changes=changes), patch.object(Catalog, 'gather_revision') as call:
                with self.assertRaises(ValueError):
                    adapter.gather_revision(changes.get('theme', self.theme),
                        changes.get('catalog', self.live), changes.get('binding', self.binding))
                call.assert_not_called()

    def test_missing_alternative_and_both_channels_na_cannot_be_authorized(self):
        self.binding['candidateProducts'][0]['affiliateUrl'] = ''
        self.binding['candidateProducts'][0]['updatedAt'] = NOW.isoformat()
        raw = {k: v for k, v in self.binding.items() if k not in ('kind', 'baseHash', 'productPatches')}
        self.binding = validated_context(raw)
        self.historical = gathered(self.binding, NOW - timedelta(minutes=30))
        self.author.update(revisionContextFingerprint=fingerprint(self.binding),
                           sourceDataFingerprint=fingerprint(self.historical))
        with self.assertRaises(ValueError): self.adapter()

    def test_failure_stale_proof_or_destination_mismatch_never_reaches_writer(self):
        def mutate(case):
            f = copy.deepcopy(self.fresh)
            if case == 'facts': f['checks']['facts'] = False
            elif case == 'blocked': f['blocked'] = True
            elif case == 'rows': f['products'][0]['name'] += 'other'
            elif case == 'old': f = copy.deepcopy(self.historical)
            elif case == 'missing': f['evidence']['products'][1]['destinations'].pop()
            elif case == 'unverified': f['evidence']['products'][0]['destinations'][0]['verified'] = False
            elif case == 'wrong_url': f['evidence']['products'][0]['destinations'][0]['url'] += 'other'
            elif case == 'duplicate': f['evidence']['products'][0]['destinations'] *= 2
            elif case == 'existing_na': f['purchaseEvidence'] = self.author['purchaseEvidence']
            elif case == 'future': f['evidence']['products'][0]['checkedAt'] = (NOW + timedelta(seconds=1)).isoformat()
            return f
        for case in ('facts', 'blocked', 'rows', 'old', 'missing', 'unverified',
                     'wrong_url', 'duplicate', 'existing_na', 'future'):
            with self.subTest(case=case):
                with patch.object(Catalog, 'gather_revision', return_value=mutate(case)):
                    with self.assertRaises(ValueError):
                        self.writer(self.adapter().gather_revision(self.theme, self.live, self.binding))
        self.writer.assert_not_called(); self.record.assert_not_called()

    def test_expiry_during_get_and_get_or_record_failure_propagate(self):
        def expired(*args):
            self.now += timedelta(hours=2)
            return self.fresh
        adapter = self.adapter()
        with patch.object(Catalog, 'gather_revision', side_effect=expired):
            with self.assertRaises(ValueError): adapter.gather_revision(self.theme, self.live, self.binding)
        self.record.assert_not_called()
        self.now = NOW
        for failed in ('get', 'record'):
            with self.subTest(failed=failed):
                self.record.side_effect = OSError('record unavailable') if failed == 'record' else None
                with patch.object(Catalog, 'gather_revision',
                                  side_effect=OSError('GET failed') if failed == 'get' else None,
                                  return_value=self.fresh):
                    with self.assertRaises(OSError):
                        self.writer(self.adapter().gather_revision(self.theme, self.live, self.binding))
        self.writer.assert_not_called()

    def test_explicit_record_rejection_stops_writer(self):
        self.record.return_value = False
        with self.assertRaisesRegex(ValueError, 'record_failed'):
            self.writer(self.run_gather()[0])
        self.writer.assert_not_called()

    def test_runtime_request_and_normal_revision_producer_validate_na_before_writer(self):
        import test_runtime
        from models import ModelError
        harness = test_runtime.RuntimeTests()
        harness.setUp()
        try:
            self.now = test_runtime.LegacyFixtureDateTime.now(NOW.tzinfo)
            self.historical = gathered(self.binding, self.now - timedelta(minutes=30))
            self.fresh = gathered(self.binding, self.now)
            self.author.update(sourceDataFingerprint=fingerprint(self.historical),
                reviewedAt=(self.now - timedelta(minutes=20)).isoformat(),
                expiresAt=(self.now + timedelta(hours=1)).isoformat())
            self.author['purchaseEvidence'][0]['checkedAt'] = (self.now - timedelta(minutes=30)).isoformat()
            self.catalog.catalog = Mock(return_value=copy.deepcopy(self.live))
            rt = harness.runtime
            rt.config['executionPolicy'] = {'mode': 'deterministic', 'suspended': False}
            rt.catalog = self.adapter()
            context = rt._context()
            context.update(copy.deepcopy(self.live), revisionArticles=copy.deepcopy(self.live['articles']))
            rt._context = Mock(return_value=context)
            def writer(theme, source):
                require_prewrite_purchase_evidence(source, self.now)
                self.assertEqual(1, len(source['purchaseEvidence']))
                self.assertEqual('Astra', source['purchaseEvidence'][0]['reviewedBy'])
                self.assertTrue(self.record.called)
                raise ModelError('offline writer boundary reached')
            harness.models.draft = Mock(side_effect=writer)
            raw = {k: v for k, v in self.binding.items() if k not in ('kind', 'baseHash', 'productPatches')}
            request = rt.request_revisions([raw])
            self.assertEqual('queued', request['status'])
            with patch.object(Catalog, 'gather_revision', return_value=self.fresh):
                result = rt._produce_requested_revision()
            self.assertEqual('offline writer boundary reached', result['reason'])
            harness.models.draft.assert_called_once()
            saved = rt.ledger.get_job(request['jobs'][0]['id'])
            self.assertEqual('error', saved['stage'])
            self.assertIsNone(saved['approval']); self.assertIsNone(saved['publication'])
        finally:
            harness.tearDown()
            harness.doCleanups()


if __name__ == '__main__':
    unittest.main()
