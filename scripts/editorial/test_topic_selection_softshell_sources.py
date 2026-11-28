"""Offline Montbell softshell role source and narrow non-product scope contracts."""
import copy
import tempfile
from pathlib import Path
import unittest

import topic_selection as topics
from test_topic_selection import NOW, proposal
from test_topic_selection_expanded_sources import ExpandedPrimarySourceTests


SOFT = topics.MONTBELL_SOFTSHELL_URL
LAYERING = topics.MONTBELL_LAYERING_URL


def fixture():
    value = ExpandedPrimarySourceTests()
    value.setUp()
    return value


def collect(value):
    with tempfile.TemporaryDirectory() as directory:
        return topics.collect_primary_sources(value.request, period='2026-11-20',
            output_path=Path(directory) / 'sources.json', now=NOW)


def candidate(**updates):
    value = proposal('montbell-shell-roles',
        'ハードシェルとソフトシェルは登山でどう役割を分ける？',
        title='モンベルのハードシェルとソフトシェル｜登山での役割',
        outline=['ソフトシェルの役割', 'はっ水性と防水性の違い',
                 '完全防水ハードシェルの別携行', '通気性がない例外'],
        sourceIds=['demand:shell', 'public:montbell-layering',
                   'public:montbell-softshell-roles'])
    value.update(updates)
    return value


class SoftshellPrimarySourceTests(unittest.TestCase):
    def test_visible_three_paragraph_excerpt_binds_exact_scope_id_and_family(self):
        value = fixture()
        feed = collect(value)
        reference = next(item for item in feed['sources'] if item['url'] == SOFT)
        self.assertEqual('\n\n'.join(value.blocks[SOFT]), reference['excerpt'])
        self.assertLessEqual(len(reference['excerpt']), 500)
        self.assertEqual(('public:montbell-softshell-roles', 'softshell-roles-only',
                          'softshell-roles-only', 'layering'),
                         (reference['id'], reference['scope'], reference['claimScope'],
                          topics._scope_family(reference['scope'])))
        self.assertEqual(('ソフトシェル', '防水性', '通気性'), topics.SOURCE_KEYWORDS[SOFT])
        self.assertEqual('verified', topics.reverify_bound_public_sources(
            value.request, [reference], now=NOW)['status'])

    def test_hidden_script_missing_duplicate_or_changed_claim_never_qualifies(self):
        blocks = fixture().blocks[SOFT]
        visible = lambda rows: '<main>' + ''.join('<p>' + row + '</p>' for row in rows) + '</main>'
        self.assertEqual('\n\n'.join(blocks), topics.softshell_roles_excerpt(visible(blocks)))
        same_paragraph = '<main><p>' + '<br>'.join(blocks) + '</p></main>'
        self.assertEqual(''.join(blocks), topics.softshell_roles_excerpt(same_paragraph))
        hidden_duplicate = (visible(blocks).replace('</main>', '') +
            '<p hidden>' + blocks[0] + '</p><p aria-hidden="true">' + blocks[1] +
            '</p><p style="display:none">' + blocks[2] + '</p></main>')
        self.assertEqual('\n\n'.join(blocks), topics.softshell_roles_excerpt(hidden_duplicate))
        for index in range(3):
            with self.subTest(missing=index):
                self.assertIsNone(topics.softshell_roles_excerpt(
                    visible([block for i, block in enumerate(blocks) if i != index])))
        self.assertIsNone(topics.softshell_roles_excerpt(
            '<main><script>' + '</script><script>'.join(blocks) + '</script></main>'))
        self.assertIsNone(topics.softshell_roles_excerpt(visible(blocks + [blocks[1]])))
        for old, new in (('ストレッチ性', '運動性'), ('完全防水', '防水'),
                         ('通気性はありません', '通気性があります')):
            with self.subTest(changed=old):
                self.assertIsNone(topics.softshell_roles_excerpt(
                    visible([block.replace(old, new) for block in blocks])))

    def test_fresh_recheck_rejects_changed_bound_claim(self):
        value = fixture()
        reference = next(item for item in collect(value)['sources'] if item['url'] == SOFT)
        value.blocks[SOFT][-1] = value.blocks[SOFT][-1].replace(
            '通気性はありません', '通気性があります')
        with self.assertRaisesRegex(topics.NonproductSourceHold, 'recheck_changed'):
            topics.reverify_bound_public_sources(value.request, [reference], now=NOW)

    def test_primary_shell_role_topic_requires_both_layering_sources(self):
        feed = collect(fixture())
        theme = candidate()
        self.assertEqual(['layering-concept-only', 'softshell-roles-only'],
                         topics.allowed_claim_scopes(theme))
        bound = topics.bind_nonproduct_theme(theme, feed)
        references = bound['nonProductContract']['references']
        self.assertEqual({'public:montbell-layering', 'public:montbell-softshell-roles'},
                         {item['id'] for item in references})
        self.assertEqual({'layering'}, {topics._scope_family(item['scope']) for item in references})
        self.assertEqual(['layering-concept-only', 'softshell-roles-only'],
                         bound['nonProductContract']['allowedClaimScopes'])

        for missing in ('public:montbell-layering', 'public:montbell-softshell-roles'):
            with self.subTest(missing=missing), self.assertRaisesRegex(
                    topics.TopicSelectionError, 'scope_mismatch'):
                topics.bind_nonproduct_theme(dict(theme,
                    sourceIds=[item for item in theme['sourceIds'] if item != missing]), feed)

        unrelated = dict(theme, sourceIds=theme['sourceIds'] + ['public:coleman-care'])
        with self.assertRaisesRegex(topics.TopicSelectionError, 'scope_mismatch'):
            topics.bind_nonproduct_theme(unrelated, feed)

    def test_outline_cannot_grant_scope_or_expand_into_other_claim_families(self):
        feed = collect(fixture())
        outline_only = candidate(title='登山ジャケットの違い',
            readerQuestion='登山ジャケットはどう違う？')
        self.assertEqual([], topics.allowed_claim_scopes(outline_only))
        with self.assertRaisesRegex(topics.TopicSelectionError, 'scope_mismatch'):
            topics.bind_nonproduct_theme(outline_only, feed)

        for extra in ('テントの乾燥と保管', '一般的なウエアの手入れ'):
            with self.subTest(extra=extra), self.assertRaisesRegex(
                    topics.TopicSelectionError, 'scope_mismatch'):
                topics.bind_nonproduct_theme(dict(candidate(),
                    outline=candidate()['outline'] + [extra]), feed)

    def test_safety_temperature_product_recommendation_and_fake_experience_are_rejected(self):
        feed = collect(fixture())
        for extra in ('登山の安全を保証する', '対応温度と気温別の判断',
                      '個別モデルのおすすめランキング', '実測して使った体験'):
            bad = candidate(outline=candidate()['outline'] + [extra])
            with self.subTest(extra=extra):
                self.assertEqual([], topics.allowed_claim_scopes(bad))
                with self.assertRaisesRegex(topics.TopicSelectionError, 'scope_mismatch'):
                    topics.bind_nonproduct_theme(bad, feed)

    def test_receipt_scope_excerpt_and_required_reference_deletion_fail_closed(self):
        feed = collect(fixture())
        bound = topics.bind_nonproduct_theme(candidate(), feed)
        for change in ('scope', 'excerpt', 'delete'):
            bad = copy.deepcopy(bound)
            if change == 'scope':
                bad['nonProductContract']['references'][-1]['scope'] = 'camp-care'
            elif change == 'excerpt':
                bad['nonProductContract']['references'][-1]['excerpt'] += '架空の使用体験'
            else:
                removed = bad['nonProductContract']['references'].pop()
                bad['sourceIds'].remove(removed['id'])
                bad['nonProductContract']['sourceReceiptSha256'] = topics._sha(topics._canonical(
                    [item['receiptSha256'] for item in bad['nonProductContract']['references']]))
            with self.subTest(change=change), self.assertRaises(topics.TopicSelectionError):
                topics.validate_nonproduct_contract(bad)


if __name__ == '__main__':
    unittest.main()
