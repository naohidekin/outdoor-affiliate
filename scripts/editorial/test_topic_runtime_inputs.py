import json
from pathlib import Path
import unittest

from runtime import Runtime


def facets(text):
    return {'garments': ['fleece'] if 'フリース' in text else [],
            'brands': [text.casefold()] if text else []}


class TopicRuntimeInputTests(unittest.TestCase):
    def test_wear_and_brand_choices_are_not_cut_off_by_the_catalog_prefix(self):
        gear = [{'id': 'a' + str(n), 'name': 'バーナー', 'brand': 'SOTO', 'categoryId': 'burner'}
                for n in range(70)]
        wear = [{'id': 'z1', 'name': 'フリース', 'brand': 'mont-bell', 'categoryId': 'wear'},
                {'id': 'z2', 'name': 'フリース', 'brand': 'patagonia', 'categoryId': 'wear'}]
        supplied = Runtime._planning_products(gear + wear, facets)
        self.assertEqual(60, len(supplied))
        self.assertTrue({'z1', 'z2'} <= {row['id'] for row in supplied})
        self.assertEqual(len(supplied), len({row['id'] for row in supplied}))

    def test_brand_coverage_is_context_only_and_never_invents_missing_products(self):
        supplied = Runtime._planning_products([{'id': 'a', 'name': 'フリース',
                                               'brand': 'mont-bell', 'categoryId': 'wear'}], facets)
        self.assertEqual(['a'], [row['id'] for row in supplied])

    def test_explicit_empty_compact_index_does_not_leak_the_full_context(self):
        rt = Runtime.__new__(Runtime)
        rt.config = {'repo': str(Path(__file__).resolve().parents[2])}
        rt._analytics_context = lambda: {'status': 'ok', 'evidence': {}}
        context = {'products': [], 'articles': [{'id': 'old', 'content': 'BODY_CANARY'}],
                   'clicks': [], 'queuedThemes': [], 'categories': [],
                   'apparelPolicy': {'status': 'bound'}, 'instructions': 'supplied'}
        result = rt._research_context(context, feed={'sources': [], 'illustrations': []}, existing_summaries=[])
        self.assertEqual([], result['existingArticles'])
        self.assertNotIn('BODY_CANARY', json.dumps(result))
        self.assertEqual(3, result['topicSelectionPolicy']['maxNewArticles'])
        self.assertEqual(0, result['topicSelectionPolicy']['extraResearchCalls'])
        self.assertEqual(60, result['catalogCoverage']['maxProvidedProducts'])

    def test_real_projection_supplies_demand_once_and_not_private_queries(self):
        from search_demand import project_search_demand
        period = {'startDate': '2026-10-23', 'endDate': '2026-11-19', 'dateBasis': 'America/Los_Angeles'}
        demand = project_search_demand([{'query': '冬 フリース 比較 PRIVATE_QUERY_CANARY',
                                         'clicks': 4, 'impressions': 100, 'ctr': 0.04, 'position': 8}], period)
        analytics = {'status': 'ok', 'evidence': {'current': {
            **period, 'status': 'ok', 'pages': [], 'searchDemand': demand}}}
        rt = Runtime.__new__(Runtime)
        rt.config = {'repo': str(Path(__file__).resolve().parents[2])}
        rt._analytics_context = lambda: analytics
        context = {'products': [], 'articles': [], 'clicks': [], 'queuedThemes': [], 'categories': [],
                   'apparelPolicy': {'status': 'bound'}, 'instructions': 'supplied'}
        result = rt._research_context(context, feed={'sources': [], 'illustrations': []}, existing_summaries=[])
        self.assertNotIn('PRIVATE_QUERY_CANARY', json.dumps(result))
        self.assertNotIn('groups', result['analytics']['evidence']['current']['searchDemand'])
        self.assertEqual(1, len([s for s in result['editorialSignals'] if s['kind'] == 'own_site_query_demand']))
        self.assertEqual(1, len(analytics['evidence']['current']['searchDemand']['groups']))
        projected = next(s for s in result['editorialSignals'] if s['kind'] == 'own_site_query_demand')
        self.assertEqual('preferred_context_round_robin_then_global_v1', projected['coverage']['selectionPolicy'])
        self.assertEqual(1, projected['coverage']['exportedApparelGroupCount'])


if __name__ == '__main__':
    unittest.main()
