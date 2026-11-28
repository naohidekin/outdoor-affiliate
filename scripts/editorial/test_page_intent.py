"""Private page-bound query rows project only controlled, bounded signals."""
import json
import unittest

from page_intent import project_page_intent, validate_page_intent


PERIOD = {'startDate': '2026-10-28', 'endDate': '2026-11-24',
          'dateBasis': 'America/Los_Angeles'}
URL = 'https://camp-gear-lab.com/articles/shell-guide'


class PageIntentTests(unittest.TestCase):
    def test_projects_bounded_controlled_signals_without_raw_query_hashes(self):
        private = 'モンベル ソフトシェル ハードシェル 違い private-person@example.invalid'
        rows = [
            {'url': URL, 'query': private, 'device': 'DESKTOP'},
            {'url': URL, 'query': 'モンベル ソフトシェル 比較', 'device': 'MOBILE'},
            {'url': URL, 'query': 'ソフトシェル 選び方', 'device': 'MOBILE'},
        ]

        evidence = project_page_intent(rows, PERIOD, [URL])[URL]

        self.assertEqual('observed_sample', evidence['status'])
        self.assertEqual(URL, evidence['targetUrl'])
        self.assertEqual(PERIOD, evidence['period'])
        self.assertLessEqual(len(evidence['signals']), 5)
        self.assertEqual(3, evidence['coverage']['observedRowCount'])
        self.assertFalse(evidence['rawQueriesExposed'])
        self.assertFalse(evidence['diagnosis'])
        self.assertFalse(evidence['marketDemand'])
        self.assertEqual('unconnected', evidence['serpEvidence']['status'])
        serialized = json.dumps(evidence, ensure_ascii=False)
        self.assertNotIn(private, serialized)
        self.assertNotIn('private-person', serialized)

    def test_projection_hash_depends_on_controlled_projection_not_raw_wording(self):
        first = project_page_intent([
            {'url': URL, 'query': 'モンベル ソフトシェル 比較 secret-a'}],
            PERIOD, [URL])[URL]
        second = project_page_intent([
            {'url': URL, 'query': 'モンベル ソフトシェル 比較 secret-b'}],
            PERIOD, [URL])[URL]

        self.assertEqual(first['projectionHash'], second['projectionHash'])
        self.assertEqual(first['signals'], second['signals'])

    def test_unobserved_target_is_explicitly_unavailable(self):
        evidence = project_page_intent([], PERIOD, [URL])[URL]

        self.assertEqual('unavailable', evidence['status'])
        self.assertEqual([], evidence['signals'])
        self.assertEqual(0, evidence['coverage']['observedRowCount'])

    def test_validator_binds_observation_to_exact_page_and_period(self):
        evidence = project_page_intent([
            {'url': URL, 'query': 'モンベル ソフトシェル 比較'}],
            PERIOD, [URL])[URL]
        self.assertEqual(evidence, validate_page_intent(
            evidence, target_url=URL, period=PERIOD))
        for changed in ('target', 'period', 'hash'):
            invalid = json.loads(json.dumps(evidence))
            if changed == 'target':
                invalid['targetUrl'] += '-other'
            elif changed == 'period':
                invalid['period']['endDate'] = '2026-11-23'
            else:
                invalid['projectionHash'] = '0' * 64
            with self.assertRaises(ValueError):
                validate_page_intent(invalid, target_url=URL, period=PERIOD)


if __name__ == '__main__':
    unittest.main()
