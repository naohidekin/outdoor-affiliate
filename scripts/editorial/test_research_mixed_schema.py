"""Offline strict mixed-research contracts; never normalize or reroll proposals."""
import copy
import json
import unittest

from models import Models, MIXED_RESEARCH_SCHEMA
import test_models as transport_fixture
from test_topic_selection import proposal
from topic_selection import INTENTS, TOPIC_TYPES, TopicSelectionError, select_proposals


def context():
    return {'catalog': [{'id': 'verified-product'}],
            'categories': [{'id': 'camp-howto'}],
            'existingArticles': [{'id': 'known-article', 'slug': 'known'}],
            'editorialSignals': [{'id': 'gsc:one', 'kind': 'gsc'},
                                 {'id': 'public:coleman-care', 'kind': 'public_reference'}]}


class MixedResearchSchemaTests(unittest.TestCase):
    def test_wire_schema_is_strict_and_prompt_names_every_intent_enum(self):
        candidate = proposal('tent-care', 'テントの片付け方は？')
        transport = transport_fixture.Fake(transport_fixture.response({'proposals': [candidate]}))
        source = context()
        before = copy.deepcopy(source)
        result = Models(transport_fixture.ENV, transport).research_mixed(source)
        payload = transport.calls[0][2]
        self.assertEqual({'format': {'type': 'json_schema', 'schema': MIXED_RESEARCH_SCHEMA}}, payload['output_config'])
        self.assertEqual({'proposals': [candidate]}, result)
        self.assertEqual(before, source)
        self.assertEqual(1, len(transport.calls))
        self.assertEqual('claude-sonnet-4-6', payload['model'])
        prompt = payload['messages'][0]['content']
        for value in INTENTS:
            self.assertIn(value, prompt)
        self.assertIn('not free-text', prompt)

    def test_wire_types_enums_and_exact_fields_match_the_local_proposal_contract(self):
        schema = MIXED_RESEARCH_SCHEMA
        self.assertEqual(['proposals'], schema['required'])
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual('array', schema['properties']['proposals']['type'])
        item = schema['properties']['proposals']['items']
        self.assertFalse(item['additionalProperties'])
        self.assertEqual(set(proposal('tent-care', '手順は？')), set(item['required']))
        self.assertEqual(set(item['required']), set(item['properties']))
        fields = item['properties']
        self.assertEqual(INTENTS, set(fields['intent']['enum']))
        self.assertEqual(TOPIC_TYPES, set(fields['topicType']['enum']))
        self.assertEqual({'new', 'existing_update', 'hold'}, set(fields['proposedAction']['enum']))
        self.assertEqual({'not_applicable', 'measured_change', 'seasonal_hypothesis'}, set(fields['needsStatus']['enum']))
        self.assertEqual('integer', fields['priority']['type'])
        for key, value in fields.items():
            if key in ('productIds', 'outline', 'sourceIds', 'overlapArticleIds'):
                self.assertEqual({'type': 'array', 'items': {'type': 'string'}}, value)
            elif key != 'priority':
                self.assertEqual('string', value['type'])
        # Existing Claude wire contracts leave unsupported bounds/conditional
        # rules to the unchanged host validator, never silently strip them.
        def walk(node):
            if isinstance(node, dict):
                self.assertFalse(set(node) & {'minimum', 'maximum', 'minLength', 'maxLength', 'minItems', 'maxItems', 'uniqueItems', 'if', 'then'})
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
        walk(schema)

    def test_japanese_intent_is_rejected_without_normalization_or_second_call(self):
        for intent in ('道具の手入れ手順を具体的に知りたい', '3層の役割を理解してウェア選びに落とし込みたい'):
            candidate = proposal('tent-care', '手順は？', intent=intent)
            raw = {'proposals': [candidate]}
            transport = transport_fixture.Fake(transport_fixture.response(raw))
            budget, artifacts = transport_fixture.Budget(), []
            models = Models(transport_fixture.ENV, transport, budget=budget, artifact_sink=artifacts.append)
            with self.assertRaisesRegex(TopicSelectionError, 'proposal_contract'):
                models.research_mixed(context())
            self.assertEqual(1, len(transport.calls))
            self.assertEqual(1, len(budget.holds))
            self.assertEqual('success', budget.settlements[0][2])
            self.assertEqual(1, len(models.usage))
            self.assertEqual(raw, json.loads(artifacts[0]['content']))

    def test_local_bounds_membership_and_conditional_rules_still_fail_closed(self):
        changes = [
            {'priority': 0}, {'priority': 101}, {'priority': 1.5},
            {'outline': ['短い', '不足']}, {'outline': ['文' * 41, '準備', '保管']},
            {'title': '文' * 81}, {'slug': 'INVALID'},
            {'intent': 'invalid'}, {'topicType': 'invalid'}, {'proposedAction': 'invalid'},
            {'needsStatus': 'invented'}, {'needsStatus': 'seasonal_hypothesis'},
            {'topicType': 'seasonal_problem', 'needsStatus': 'not_applicable'},
            {'categoryId': 'invented'}, {'productIds': ['invented']},
            {'topicType': 'product', 'productIds': []}, {'sourceIds': []},
            {'sourceIds': ['gsc:one', 'gsc:one']},
            {'proposedAction': 'existing_update', 'overlapArticleIds': []},
            {'overlapArticleIds': ['known-article']},
            {'proposedAction': 'existing_update', 'overlapArticleIds': ['invented']},
        ]
        for changeset in changes:
            candidate = proposal('tent-care', '手順は？')
            candidate.update(changeset)
            transport = transport_fixture.Fake(transport_fixture.response({'proposals': [candidate]}))
            with self.subTest(changes=changeset), self.assertRaises(TopicSelectionError):
                Models(transport_fixture.ENV, transport).research_mixed(context())
            self.assertEqual(1, len(transport.calls))

    def test_valid_enums_and_routes_are_preserved_without_inventing_evidence(self):
        for intent in sorted(INTENTS):
            for kind, needs in (('product', 'not_applicable'), ('knowhow', 'not_applicable'),
                                ('seasonal_problem', 'seasonal_hypothesis'),
                                ('seasonal_problem', 'measured_change')):
                candidate = proposal('tent-care', '手順は？', intent=intent, topicType=kind,
                                     needsStatus=needs, productIds=['verified-product'])
                transport = transport_fixture.Fake(transport_fixture.response({'proposals': [candidate]}))
                self.assertEqual({'proposals': [candidate]},
                                 Models(transport_fixture.ENV, transport).research_mixed(context()))
        candidate = proposal('tent-care', '手順は？', sourceIds=['unknown-source'])
        transport = transport_fixture.Fake(transport_fixture.response({'proposals': [candidate]}))
        result = Models(transport_fixture.ENV, transport).research_mixed(context())
        self.assertEqual(['unknown-source'], result['proposals'][0]['sourceIds'])
        selection = select_proposals(result['proposals'], signals=context()['editorialSignals'],
                                     existing=[], queued=[], feed={}, limit=3)
        self.assertEqual('unknown_evidence_id', selection['decisions'][0]['reason'])
        self.assertEqual([], selection['selected'])

    def test_missing_or_extra_fields_are_not_filled_or_discarded(self):
        base = proposal('tent-care', '手順は？')
        candidates = [dict(base, invented='not allowed')]
        for key in ('intent', 'sourceIds', 'productIds', 'needsStatus'):
            missing = copy.deepcopy(base)
            del missing[key]
            candidates.append(missing)
        for candidate in candidates:
            transport = transport_fixture.Fake(transport_fixture.response({'proposals': [candidate]}))
            with self.assertRaisesRegex(TopicSelectionError, 'proposal_fields'):
                Models(transport_fixture.ENV, transport).research_mixed(context())
            self.assertEqual(1, len(transport.calls))


if __name__ == '__main__':
    unittest.main()
