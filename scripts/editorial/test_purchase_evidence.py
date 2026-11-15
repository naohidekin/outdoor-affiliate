"""Pure purchase evidence attachment contracts; no I/O or inferred evidence."""
import copy
from datetime import datetime, timedelta, timezone
import unittest

from purchase_evidence import validate_purchase_evidence


AMAZON = 'https://www.amazon.co.jp/dp/B012345678?tag=owner-22'
RAKUTEN = 'https://hb.afl.rakuten.co.jp/ichiba/owner/shop'


class PurchaseEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 15, 10, 0, tzinfo=timezone(timedelta(hours=9)))
        self.bundle = {'article': {'title': 'Approved'}, 'products': [{
            'id': 'p1', 'amazonUrl': '', 'affiliateUrl': RAKUTEN,
        }]}
        self.evidence = [{'productId': 'p1', 'channel': 'amazon', 'status': 'NA',
                          'reason': '型番一致の取扱いを確認できない',
                          'checkedAt': (self.now - timedelta(hours=2)).isoformat(),
                          'reviewedBy': 'owner'}]

    def test_returns_copy_with_exact_provided_evidence_only(self):
        inputs = copy.deepcopy((self.bundle, self.evidence))
        result = validate_purchase_evidence(self.bundle, self.evidence, self.now)
        expected = copy.deepcopy(self.bundle)
        expected['purchaseEvidence'] = copy.deepcopy(self.evidence)
        self.assertEqual(expected, result)
        self.assertEqual(inputs, (self.bundle, self.evidence))

    def test_rejects_stale_future_naive_duplicate_wrong_or_incomplete_evidence(self):
        variants = []
        for checked_at in ((self.now - timedelta(hours=6, seconds=1)).isoformat(),
                           (self.now + timedelta(seconds=1)).isoformat(), '2026-11-15T09:00:00'):
            value = copy.deepcopy(self.evidence)
            value[0]['checkedAt'] = checked_at
            variants.append(value)
        variants.extend((self.evidence * 2, [], [dict(self.evidence[0], productId='other')],
                         [dict(self.evidence[0], extra='invented')]))
        for evidence in variants:
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                validate_purchase_evidence(self.bundle, evidence, self.now)

    def test_rejects_na_for_present_url_or_without_verified_other_destination(self):
        present = copy.deepcopy(self.bundle)
        present['products'][0]['amazonUrl'] = AMAZON
        missing_other = copy.deepcopy(self.bundle)
        missing_other['products'][0]['affiliateUrl'] = ''
        wrong_other = copy.deepcopy(self.bundle)
        wrong_other['products'][0]['affiliateUrl'] = 'https://evil.example/product'
        for bundle in (present, missing_other, wrong_other, dict(self.bundle, purchaseEvidence=[])):
            with self.subTest(bundle=bundle), self.assertRaises(ValueError):
                validate_purchase_evidence(bundle, self.evidence, self.now)


if __name__ == '__main__':
    unittest.main()
