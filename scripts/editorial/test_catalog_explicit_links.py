"""Exact owner-specified navigation context, bounded before any writer/fetch."""
import copy
import unittest
from unittest.mock import Mock

from catalog import Catalog, CatalogError
from test_catalog import products, response


class ExplicitArticleLinksTests(unittest.TestCase):
    def setUp(self):
        self.articles = [dict(id=str(i), slug='article-' + str(i), title='Title ' + str(i),
                             categoryId='stove', status='published', content='DO_NOT_COPY', excerpt='summary')
                         for i in range(10)]
        self.articles[0]['productIds'] = ['p0']
        self.catalog = dict(products=products(), articles=self.articles)
        self.fetch = Mock(return_value=response(''))
        self.client = Catalog({}, self.fetch)
        self.theme = dict(slug='new-guide', productIds=['p0'], selectionReason='Link /articles/article-8 , /articles/article-9 .')

    def test_explicit_tail_links_prioritize_five_identity_only_summaries(self):
        result = self.client.gather(self.theme, self.catalog)
        self.assertEqual(['article-8', 'article-9', 'article-0', 'article-1', 'article-2'],
                         [a['slug'] for a in result['existingArticles']])
        self.assertEqual(5, len(result['existingArticles']))
        self.assertTrue(all(set(a) == {'id', 'slug', 'title', 'categoryId', 'excerpt'} for a in result['existingArticles']))
        self.assertNotIn('DO_NOT_COPY', str(result['existingArticles']))

    def test_unknown_self_unpublished_wrong_category_or_duplicate_target_holds_before_fetch(self):
        for case in ('unknown', 'self', 'unpublished', 'category', 'ambiguous'):
            source = copy.deepcopy(self.catalog); theme = dict(self.theme, selectionReason='Link /articles/article-8 .')
            if case == 'unknown': theme['selectionReason'] = 'Link /articles/not-real .'
            elif case == 'self': theme['slug'] = 'article-8'
            elif case == 'unpublished': source['articles'][8]['status'] = 'draft'
            elif case == 'category': source['articles'][8]['categoryId'] = 'other'
            else: source['articles'].append(dict(source['articles'][8], id='duplicate'))
            self.fetch.reset_mock()
            with self.subTest(case=case), self.assertRaises(CatalogError): self.client.gather(theme, source)
            self.fetch.assert_not_called()

    def test_malformed_query_fragment_nested_path_and_four_unique_links_hold(self):
        for paths in ('/articles/', '/articles/article-8?q=1', '/articles/article-8#x', '/articles/article-8/child',
                      '/articles/article-8 /articles/article-9 /articles/article-7 /articles/article-6'):
            with self.subTest(paths=paths), self.assertRaises(CatalogError):
                self.client.gather(dict(self.theme, selectionReason=paths), self.catalog)
        self.fetch.assert_not_called()

    def test_repeated_explicit_links_deduplicate_and_legacy_order_stays_identical(self):
        reason = '/articles/article-8 /articles/article-8 /articles/article-9'
        result = self.client.gather(dict(self.theme, selectionReason=reason), self.catalog)
        self.assertEqual(['article-8', 'article-9'], [a['slug'] for a in result['existingArticles'][:2]])
        for reason in ('No explicit navigation', None):
            result = self.client.gather(dict(self.theme, selectionReason=reason), self.catalog)
            self.assertEqual(['article-' + str(i) for i in range(5)], [a['slug'] for a in result['existingArticles']])


if __name__ == '__main__':
    unittest.main()
