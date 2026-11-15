"""Source-supplied NA metadata follows the same writer/polish/review boundaries."""
import copy
import json
from datetime import datetime
import unittest
from unittest.mock import patch

from runtime import JST
from test_quality import bundle
import test_runtime


class PurchaseEvidenceRuntimeTests(unittest.TestCase):
    setUp = test_runtime.RuntimeTests.setUp
    tearDown = test_runtime.RuntimeTests.tearDown

    def test_verified_source_na_is_bound_before_polish_and_owner_review(self):
        candidate = bundle()
        product = candidate['products'][0]
        product['amazonUrl'] = ''
        evidence = [{'productId': product['id'], 'channel': 'amazon', 'status': 'NA',
                     'reason': '購入先商品の同一性を確認できないため非表示',
                     'reviewedBy': 'Astra', 'checkedAt': datetime.now(JST).isoformat()}]
        gathered = {'catalog': candidate['products'], 'references': candidate['references'],
                    'images': candidate['images'], 'purchaseEvidence': evidence,
                    'checks': {key: True for key in ('facts', 'images', 'affiliate')}}
        with patch.object(self.runtime.catalog, 'gather', return_value=gathered), \
                patch.object(self.models, 'draft', return_value=copy.deepcopy(candidate)), \
                patch.object(self.models, 'review', wraps=self.models.review) as review:
            self.runtime.produce(limit=1)
        job = next(j for j in self.runtime.ledger.list_jobs() if j.get('bundle'))
        self.assertEqual('review', job['stage'])
        self.assertIsNone(job['approval'])
        self.assertEqual(evidence, job['bundle']['purchaseEvidence'])
        self.assertEqual(evidence, review.call_args.args[0]['purchaseEvidence'])
        sources = list((self.runtime.root / 'research/artifacts' / job['id']).glob('*/source.json'))
        self.assertEqual(1, len(sources))
        self.assertEqual(evidence, json.loads(sources[0].read_text())['bundle']['purchaseEvidence'])


if __name__ == '__main__':
    unittest.main()
