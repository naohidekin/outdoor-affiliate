"""Offline provider contract and fail-closed model tests (Python 3.9 stdlib)."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from models import (Models, ModelError, ModelOutcomeUnknown, WRITER_SCHEMA, REVIEW_SCHEMA,
                    CRITERIA_FIELDS, SOCIAL_SCHEMA, SOCIAL_REVIEW_SCHEMA)
from wise_contract import load_policy
from model_inputs import restore_model_input
from nonproduct_contract_fixture import fixture as nonproduct_fixture


ENV = {"ANTHROPIC_API_KEY": "test-claude-key", "GEMINI_API_KEY": "test-gemini-key"}


def brief():
    return dict(purpose="Help choose", reader="Beginners", conclusion="Choose by use",
                headings=["Choice"], facts=["Weight 2kg"], numbers=["2kg"],
                links=["https://maker.example/tent"], requiredExpressions=["広告"],
                protected=["{{product:tent-a}}"], style="Warm", length="3000-5000",
                cta="Check details", format="guide", externalSafe=True)


def bundle():
    return dict(article={"id": "a1", "title": "Tent", "content": "広告\n## Choice\nWeight 2kg {{product:tent-a}}\n"
                                    "[設営](/articles/setup) [撤収](/articles/pack)\n" + "検証済みの説明です。" * 350,
                         "productIds": ["tent-a"], "slug": "tent-guide", "categoryId": "tent",
                         "excerpt": "用途と重さを確かめて自分に合うテントを選びます。",
                         "metaDescription": "用途と重さを確かめて自分に合うテントを選ぶための調査記事です。" * 2,
                         "faqs": [{"question": "重さは？", "answer": "2kgです。"}] * 3,
                         "tags": ["tent"], "author": "ギア男"},
                products=[{"id": "tent-a", "specs": {"weight": "2kg"}, "imageUrl": "https://images.example/a.jpg"}],
                brief=brief(), references=[{"url": "https://maker.example/tent"}],
                images=[{"productId": "tent-a", "url": "https://images.example/a.jpg"}])


def context():
    b = bundle()
    return dict(catalog=b["products"], references=b["references"], images=b["images"],
                existingArticles=[{'slug': slug} for slug in ('setup', 'pack', 'compare', 'store', 'tent-guide')],
                CLAUDE="Article template: no H1", SKILL="WISE score at least 7.5",
                gsc=[{"query": "winter tent weight", "impressions": 123}],
                season="winter", merchantClicks=[{"productId": "tent-a", "clicks": 8}])


def response(value, gemini=False, raw=None):
    content = raw if raw is not None else json.dumps(value)
    if gemini:
        return {"id": "g-1", "model": "gemini-3.8-flash", "usage": {"prompt_tokens": 31, "completion_tokens": 9},
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    return {"id": "c-1", "model": "claude-sonnet-4-6", "usage": {"input_tokens": 31, "output_tokens": 9},
            "content": [{"type": "text", "text": content}], "stop_reason": "end_turn"}


def writer_response(value):
    return response({"article": {key: copy.deepcopy(value["article"][key]) for key in value["article"] if key != "id"},
                     "brief": copy.deepcopy(value["brief"])})


class Fake:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, copy.deepcopy(headers), copy.deepcopy(payload), timeout))
        value = self.results.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def http(code):
    return HTTPError("https://provider.invalid", code, "test-claude-key SECRET BODY", {}, io.BytesIO(b"secret"))


def prompt_data(prompt):
    raw = prompt.split('Return ONLY a complete JSON object, no fences or commentary.\n', 1)[1]
    return restore_model_input(json.loads(raw))


class Budget:
    def __init__(self, events=None, failure=None, settle_failure=None):
        self.events = events if events is not None else []
        self.failure = failure
        self.settle_failure = settle_failure
        self.holds = []
        self.settlements = []
        self.response_ids = []

    def reserve(self, payload, model):
        self.events.append(('reserve', model))
        if self.failure is not None:
            raise self.failure
        hold = 'hold-%d' % (len(self.holds) + 1)
        self.holds.append((hold, copy.deepcopy(payload), model))
        return hold

    def settle(self, hold, usage=None, outcome='success', response_id=None):
        self.events.append(('settle', hold, outcome))
        self.settlements.append((hold, copy.deepcopy(usage), outcome))
        self.response_ids.append(response_id)
        if self.settle_failure is not None:
            raise self.settle_failure


THEMES = {"themes": [{"slug": "theme-%d" % i, "title": title, "query": title.lower(),
                       "categoryId": "tent", "selectionReason": "Season and verified catalog",
                       "productIds": ["tent-a"], "evidence": {"season": "winter"}}
                      for i, title in enumerate(("Winter tent weight choice", "Rain tent packing tips", "Family tent setup size"))]}
REVIEW = dict(passed=True, score=8.5, facts=True, images=True, affiliate=True, medical=True,
              render=True, evidence={"claim": "model opinion"}, issues=[])
FLAGS = dict(facts=True, images=True, affiliate=True, medical=True, render=True)


class ModelTests(unittest.TestCase):
    def test_budget_reserves_exact_payload_before_request_and_settles_raw_usage(self):
        events = []
        budget = Budget(events)
        sent = []
        def request(url, headers, payload, timeout):
            events.append(('request', payload['model']))
            sent.append(copy.deepcopy(payload))
            return response(THEMES)
        model = Models(ENV, request, budget=budget)
        self.assertEqual(model.research(context()), THEMES)
        self.assertEqual(events, [('reserve', 'claude-sonnet-4-6'), ('request', 'claude-sonnet-4-6'),
                                  ('settle', 'hold-1', 'success')])
        self.assertEqual(budget.holds[0][1], sent[0])
        self.assertEqual(budget.settlements, [('hold-1', {'input_tokens': 31, 'output_tokens': 9}, 'success')])
        self.assertEqual(budget.response_ids, ['c-1'])

    def test_models_send_shorter_lossless_projection_without_changing_host_data(self):
        ctx = context()
        ctx['catalog'][0]['sourceNotes'] = '公称値2kg。条件付きURL https://maker.example/spec を保持。' * 20
        ctx['products'] = copy.deepcopy(ctx['catalog'])
        original = copy.deepcopy(ctx)
        fake = Fake(response(THEMES))
        Models(ENV, fake).research(ctx)
        raw = json.loads(fake.calls[0][2]['messages'][0]['content'].split(
            'Return ONLY a complete JSON object, no fences or commentary.\n', 1)[1])
        self.assertNotEqual(raw, {'context': original})
        self.assertEqual(restore_model_input(raw), {'context': original})
        self.assertLess(len(json.dumps(raw, ensure_ascii=False)),
                        len(json.dumps({'context': original}, ensure_ascii=False)))
        self.assertEqual(ctx, original)

    def test_budget_settles_every_retry_fallback_and_unknown_attempt(self):
        budget = Budget()
        fake = Fake(http(429), http(503), response(THEMES))
        with patch('models.time.sleep'):
            self.assertEqual(Models(ENV, fake, budget=budget).research({}), THEMES)
        self.assertEqual([item[2] for item in budget.holds], ['claude-sonnet-4-6'] * 3)
        self.assertEqual([item[2] for item in budget.settlements], ['failed', 'failed', 'success'])

        budget = Budget()
        fake = Fake(http(404), writer_response(bundle()))
        Models(ENV, fake, budget=budget).draft({}, context())
        self.assertEqual([item[2] for item in budget.holds], ['claude-opus-4-8', 'claude-sonnet-4-6'])
        self.assertEqual([item[2] for item in budget.settlements], ['failed', 'success'])

        for failure, outcome in ((http(500), 'failed'), (TimeoutError('private'), 'unknown'),
                                 (ModelError('parsed transport response invalid'), 'unknown')):
            budget = Budget()
            with self.subTest(failure=type(failure)), self.assertRaises(ModelError):
                Models(ENV, Fake(failure), budget=budget).research({})
            self.assertEqual(budget.settlements, [('hold-1', None, outcome)])

    def test_budget_settles_actual_response_before_provider_validation(self):
        raw = response(THEMES)
        raw.pop('usage')
        budget = Budget()
        with self.assertRaises(ModelError):
            Models(ENV, Fake(raw), budget=budget).research({})
        self.assertEqual(budget.settlements, [('hold-1', None, 'success')])

    def test_budget_hold_propagates_without_transport_or_settlement(self):
        class BudgetHold(RuntimeError):
            pass
        hold = BudgetHold('cap reached')
        budget, fake = Budget(failure=hold), Fake(response(THEMES))
        with self.assertRaises(BudgetHold) as caught:
            Models(ENV, fake, budget=budget).research({})
        self.assertIs(caught.exception, hold)
        self.assertEqual(fake.calls, [])
        self.assertEqual(budget.settlements, [])

    def test_budget_settle_failure_propagates_after_recording_actual_usage(self):
        class BudgetHold(RuntimeError):
            pass
        hold = BudgetHold('settlement failed')
        budget = Budget(settle_failure=hold)
        model = Models(ENV, Fake(response(THEMES)), budget=budget)
        with self.assertRaises(BudgetHold) as caught:
            model.research({})
        self.assertIs(caught.exception, hold)
        self.assertEqual(model.usage[0]['usage'], {'input_tokens': 31, 'output_tokens': 9})

    def test_budget_covers_local_repair_without_bypassing_cap(self):
        b = bundle()
        url = 'https://camp-gear-lab.com/articles/tent'
        b['images'][0]['verified'] = True
        b['publicReadback'] = dict(verified=True, url=url, content=b['article']['content'], images=b['images'])
        budget = Budget()
        fake = Fake(response(dict(text='広告' + 'あ' * 200, replyText=url)),
                    response(dict(text='広告 選び方を確認します。', replyText=url)))
        self.assertEqual(Models(ENV, fake, budget=budget).social(b, url)['text'], '広告 選び方を確認します。')
        self.assertEqual(len(budget.holds), 2)
        self.assertEqual([item[2] for item in budget.settlements], ['success', 'success'])

    def test_transport_without_response_is_outcome_unknown(self):
        model = Models(ENV, Fake(TimeoutError('private transport detail')))
        with self.assertRaisesRegex(ModelOutcomeUnknown, 'Provider outcome unknown'):
            model.research(context())

    def test_response_after_deadline_is_outcome_unknown(self):
        fake = Fake(response(THEMES))
        with patch('models.time.monotonic', side_effect=[0, 0, 181]), \
                self.assertRaises(ModelOutcomeUnknown):
            Models(ENV, fake).research(context())
        self.assertEqual(1, len(fake.calls))

    def test_draft_instruction_prioritizes_provenance_over_template_memoirs(self):
        ctx = context()
        ctx.update(verifiedAuthorFacts=[], CLAUDE='Style template: open with a personal camping mishap.',
                   SKILL='Style template: describe past buying feelings.')
        fake = Fake(writer_response(bundle()))
        Models(ENV, fake).draft({}, ctx)
        self.assertEqual(len(fake.calls), 1)
        prompt = fake.calls[0][2]['messages'][0]['content']
        instruction, data = prompt.split('Return ONLY a complete JSON object, no fences or commentary.\n', 1)
        for phrase in ('Source provenance takes priority over style templates', 'verifiedAuthorFacts is empty',
                       'NO first-person past narrative', 'generic camping mishaps', 'past buying feelings',
                       'third-person research', 'Do not turn these prohibitions into long reader-facing disclaimers'):
            self.assertIn(phrase, instruction)
        self.assertEqual(restore_model_input(json.loads(data))['context'], ctx)

    def test_draft_instruction_requires_verbatim_apparel_variant_disclosure(self):
        ctx = context()
        ctx['apparelApprovalDisclosure'] = {
            'requiredExpressions':['楽天市場は選択式、Amazonは固定です。'],
            'rule':'merchant option states differ'}
        fake = Fake(writer_response(bundle()))
        Models(ENV,fake).draft({},ctx)
        prompt = fake.calls[0][2]['messages'][0]['content']
        instruction,data = prompt.split('Return ONLY a complete JSON object, no fences or commentary.\n',1)
        self.assertIn('include every supplied requiredExpressions string',instruction)
        self.assertIn('do not merge fixed and selectable merchant variants',instruction)
        self.assertEqual(ctx,restore_model_input(json.loads(data))['context'])

    def test_draft_rejects_unknown_self_or_unbound_internal_article_links(self):
        for destination in ('/articles/invented', '/articles/tent-guide', '/articles/setup?fake=1',
                            '/articles/setup#fake', 'https://camp-gear-lab.com/articles/invented'):
            with self.subTest(destination=destination):
                candidate = bundle()
                candidate['article']['content'] = candidate['article']['content'].replace('/articles/pack', destination)
                fake = Fake(writer_response(candidate), writer_response(bundle()))
                with self.assertRaisesRegex(ModelError, 'Unknown or self internal article link'):
                    Models(ENV, fake).draft({}, context())
                self.assertEqual(1, len(fake.calls))
        for existing in (None, [], {}, [{'title': 'No slug'}], [{'slug': 'setup/extra'}]):
            with self.subTest(existing=existing):
                ctx = context()
                ctx['existingArticles'] = existing
                fake = Fake(writer_response(bundle()))
                with self.assertRaisesRegex(ModelError, 'Known existing article slugs required'):
                    Models(ENV, fake).draft({}, ctx)
                self.assertEqual(1, len(fake.calls))

    def test_draft_internal_link_count_uses_actual_markdown_not_code_images_or_unused_definitions(self):
        for fake_link in ('`[撤収](/articles/pack)`', '![撤収](/articles/pack)',
                          '```md\n[撤収](/articles/pack)\n```',
                          '[撤収]: /articles/pack', '![撤収][pack]\n[pack]: /articles/pack'):
            with self.subTest(fake_link=fake_link):
                candidate = bundle()
                candidate['article']['content'] = candidate['article']['content'].replace(
                    '[撤収](/articles/pack)', '\n' + fake_link + '\n')
                fake = Fake(writer_response(candidate))
                with self.assertRaisesRegex(ModelError, 'Two to three distinct internal article links required'):
                    Models(ENV, fake).draft({}, context())
                self.assertEqual(1, len(fake.calls))

    def test_draft_known_inline_and_reference_links_pass_and_duplicate_destinations_count_once(self):
        for links in ('[設営](/articles/setup) [撤収](/articles/pack) [再掲](/articles/setup)',
                      '[設営][setup] [撤収][pack]\n\n[setup]: /articles/setup\n[pack]: /articles/pack',
                      '[設営](https://camp-gear-lab.com/articles/setup) [撤収](/articles/pack)'):
            with self.subTest(links=links):
                candidate = bundle()
                candidate['article']['content'] = candidate['article']['content'].replace(
                    '[設営](/articles/setup) [撤収](/articles/pack)', links)
                fake = Fake(writer_response(candidate))
                self.assertEqual(candidate['article']['content'], Models(ENV, fake).draft({}, context())['article']['content'])
                self.assertEqual(1, len(fake.calls))

    def test_product_guide_prompt_turns_verified_variant_differences_into_purchase_choices(self):
        fake = Fake(writer_response(bundle()))
        Models(ENV, fake).draft({}, context())
        instruction = fake.calls[0][2]['messages'][0]['content']
        for phrase in (
                'sourced Markdown comparison table of official, 楽天 and Amazon color/size/options',
                'when supplied references.apparelBinding confirms them',
                'Include only confirmed channels and exact fixed/selectable variant differences',
                'purchase-option comparison, not a multi-product ranking',
                'without inferring price or availability', 'Lead with concrete purchaser choices',
                'documented specifications and variant discrepancies',
                'One concise research disclosure is enough',
                'do not repeat editorial verification or moral claims in every section',
                'Keep necessary source qualifications beside the relevant claim',
                'without fabricating firsthand experience, scientific explanations, performance or safety claims'):
            self.assertIn(phrase, instruction)
        self.assertEqual(1, len(fake.calls))

    def test_draft_instruction_budgets_japanese_body_and_whole_body_internal_links(self):
        ctx = context()
        ctx['existingArticles'] = [{'slug': slug} for slug in ('setup', 'pack', 'tent-guide')]
        fake = Fake(writer_response(bundle()))
        Models(ENV, fake).draft({'slug': 'tent-guide', 'productIds': ['tent-a']}, ctx)
        instruction = fake.calls[0][2]['messages'][0]['content']
        for phrase in (
                'Japanese character counts (Python len of the decoded article.content string)',
                'NOT tokens, words', 'UTF-8 bytes or JSON escape lengths',
                'guide/how-to body 4000-4700 characters',
                'introduction 300, five existing main sections 700 each, and conclusion 400',
                'adapt the allocation to the supplied structure',
                "reader's stated decision", 'sourced limitations',
                'bounded public primary excerpts, not verified personal experience',
                'Distinguish manufacturer claims', 'safe cold temperatures or survival suitability',
                'does not verify catalog description, price, rating or availability',
                'Unless a supplied excerpt literally supports the claim',
                'a thin shell cannot stop wind', 'average weight excludes size or individual variation',
                'storage dimensions assume ideal packing', 'indoor or high-activity use',
                '1000FP guarantees warmth', 'Missing evidence means 今回の根拠では未確認',
                'not that the manufacturer never states it anywhere',
                'publishes no temperature rating globally',
                'Do not add scientific definitions of denier or fill power unless supplied by the sources',
                'documented weight, storage, pockets and variant choices without inferring performance or safety',
                'including in FAQs and metadata',
                'Do not expose internal field names or values such as apparelClass or optionState',
                'without filler, repeated summaries, new facts or invented examples',
                '2-3 distinct internal Markdown links /articles/slug across the WHOLE article.content',
                'not 2-3 per section', 'exact destinations supplied by context.existingArticles',
                "exclude the current article's slug", 'Repeated destinations count once'):
            self.assertIn(phrase, instruction)
        self.assertEqual(ctx, prompt_data(instruction)['context'])
        self.assertEqual(1, len(fake.calls))

    def test_draft_short_body_with_four_internal_urls_still_fails_without_repair(self):
        candidate = bundle()
        candidate['article']['content'] = (
            candidate['article']['content'][:2200] +
            '\n[比較](/articles/compare) [収納](/articles/store)\n')
        candidate['article']['content'] += '文' * (2308 - len(candidate['article']['content']))
        fake = Fake(writer_response(candidate), writer_response(bundle()))
        model = Models(ENV, fake)
        with self.assertRaisesRegex(ModelError, 'Two to three distinct internal article links required'):
            model.draft({}, context())
        self.assertEqual(1, len(fake.calls))
        self.assertEqual(1, len(model.usage))

    def test_draft_repair_reports_exact_japanese_character_deficit(self):
        for size in (2224, 2308, 2334):
            with self.subTest(size=size):
                short = bundle()
                short['article']['content'] = short['article']['content'][:size]
                fake = Fake(writer_response(short), writer_response(bundle()))
                Models(ENV, fake).draft({}, context())
                instruction = fake.calls[1][2]['messages'][0]['content']
                self.assertIn('Minimum net addition required: ' + str(3000 - size) + ' characters', instruction)
                self.assertIn('minimum net removal required: 0 characters', instruction)
                self.assertIn('aim for the format\'s interior target above', instruction)
                self.assertIn('exact text, occurrence count and order', instruction)
                self.assertIn('Do not duplicate, move or remove', instruction)
                self.assertIn('do not repeat protected literals', instruction)
                self.assertEqual(2, len(fake.calls))

    def test_draft_repairs_length_once_with_pinned_model_context_and_preserved_artifacts(self):
        good = bundle()
        short = copy.deepcopy(good)
        short['article']['content'] = good['article']['content'][:2106]
        first, second = writer_response(short), writer_response(good)
        first['id'], second['id'] = 'draft-short', 'draft-repaired'
        fake, artifacts = Fake(first, second), []
        model = Models(ENV, fake, artifact_sink=artifacts.append)
        theme, ctx = {'productIds': ['tent-a'], 'slug': 'tent-guide'}, context()
        original_theme, original_context = copy.deepcopy(theme), copy.deepcopy(ctx)
        result = model.draft(theme, ctx)
        self.assertEqual(result['article']['content'], good['article']['content'])
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.calls[1][2]['model'], first['model'])
        self.assertEqual([a['responseId'] for a in artifacts], ['draft-short', 'draft-repaired'])
        self.assertEqual([u['responseId'] for u in model.usage], ['draft-short', 'draft-repaired'])
        self.assertEqual(json.loads(artifacts[0]['content'])['article']['content'], short['article']['content'])
        payload = prompt_data(fake.calls[1][2]['messages'][0]['content'])
        self.assertEqual(payload['theme'], original_theme)
        self.assertEqual(payload['context'], original_context)
        self.assertEqual(payload['previousCandidate']['brief'], short['brief'])
        self.assertEqual(payload['validation'], dict(format='guide', actualCharacters=2106, minimum=3000, maximum=5000))
        self.assertEqual((theme, ctx), (original_theme, original_context))
        for phrase in ('guide/how-to body 4000-4700 characters', 'Do not add new facts', 'Do not change brief.format', 'Do not pad', '2106', '3000', '5000'):
            self.assertIn(phrase, fake.calls[1][2]['messages'][0]['content'])
        self.assertNotIn('guide/how-to body 3500-4200', fake.calls[0][2]['messages'][0]['content'])
        self.assertTrue(all(c[0] == 'https://api.anthropic.com/v1/messages' for c in fake.calls))

    def test_draft_length_repair_is_bounded_even_if_second_still_short_or_too_long(self):
        for size in (2106, 2718, 2755, 5100):
            b = bundle()
            b['article']['content'] = b['article']['content'][:2106]
            final = copy.deepcopy(b)
            final['article']['content'] += '文' * max(0, size - len(final['article']['content']))
            fake = Fake(writer_response(b), writer_response(final), writer_response(bundle()))
            model = Models(ENV, fake)
            with self.subTest(size=size), self.assertRaisesRegex(ModelError, 'Article length outside'):
                model.draft({}, context())
            self.assertEqual(len(fake.calls), 2)
            self.assertEqual(len(model.usage), 2)

    def test_draft_nonlength_errors_never_trigger_length_repair(self):
        for mode in ('format', 'links', 'image', 'schema', 'product', 'authorfact'):
            b, ctx = bundle(), context()
            b['article']['content'] = b['article']['content'][:2106]
            if mode == 'format': b['brief']['format'] = 'unknown'
            if mode == 'links': b['article']['content'] = b['article']['content'].replace('[撤収](/articles/pack)', '')
            if mode == 'image': ctx['images'][0]['url'] = 'https://invented.example/image.jpg'
            if mode == 'schema': b['article']['tags'] = 'not a list'
            if mode == 'product': b['article']['content'] += '{{product:ghost}}'
            if mode == 'authorfact': ctx.update(existingArticle={'slug': 'tent-guide'}, verifiedAuthorFacts=['Verified ownership sentence.'])
            fake = Fake(writer_response(b), writer_response(bundle()))
            with self.subTest(mode=mode), self.assertRaises(ModelError):
                Models(ENV, fake).draft({}, ctx)
            self.assertEqual(len(fake.calls), 1)

    def test_draft_repair_cannot_change_identity_brief_or_protected_facts(self):
        for mode in ('slug', 'title', 'categoryId', 'format', 'facts', 'numbers', 'bodyfact', 'literal', 'links',
                     'duplicate_heading', 'reorder_links'):
            first, final = bundle(), bundle()
            first['article']['content'] = first['article']['content'][:2106]
            if mode in ('slug', 'title', 'categoryId'): final['article'][mode] = 'different'
            if mode == 'format': final['brief']['format'] = 'review'
            if mode in ('facts', 'numbers'): final['brief'][mode] = ['invented']
            if mode == 'literal': final['article']['content'] = final['article']['content'].replace('Weight 2kg', 'Mass 2kg')
            if mode == 'bodyfact': final['article']['content'] = final['article']['content'].replace('2kg', '3kg')
            if mode == 'links': final['article']['content'] = final['article']['content'].replace('/articles/pack', '/articles/other')
            if mode == 'duplicate_heading': final['article']['content'] += '\n## Choice\n'
            if mode == 'reorder_links':
                final['article']['content'] = final['article']['content'].replace(
                    '[設営](/articles/setup) [撤収](/articles/pack)', '[撤収](/articles/pack) [設営](/articles/setup)')
            fake = Fake(writer_response(first), writer_response(final), writer_response(bundle()))
            with self.subTest(mode=mode), self.assertRaises(ModelError):
                Models(ENV, fake).draft({}, context())
            self.assertEqual(len(fake.calls), 2)

    def test_draft_long_body_repair_and_repair_provider_failure_never_generate_third_candidate(self):
        good = bundle()
        long = copy.deepcopy(good)
        long['article']['content'] += '説明' * 1000
        fake = Fake(writer_response(long), writer_response(good))
        self.assertEqual(Models(ENV, fake).draft({}, context())['article']['content'], good['article']['content'])
        self.assertEqual(len(fake.calls), 2)
        instruction = fake.calls[1][2]['messages'][0]['content']
        self.assertIn('Minimum net addition required: 0 characters', instruction)
        self.assertIn('minimum net removal required: ' + str(len(long['article']['content']) - 5000) + ' characters', instruction)
        for failure in (http(404), http(500), response(None, raw='not JSON')):
            short = copy.deepcopy(good)
            short['article']['content'] = short['article']['content'][:2106]
            fake = Fake(writer_response(short), failure, writer_response(good))
            with self.subTest(failure=type(failure)), self.assertRaises(ModelError):
                Models(ENV, fake).draft({}, context())
            self.assertEqual(len(fake.calls), 2)
            self.assertEqual(fake.calls[1][2]['model'], 'claude-sonnet-4-6')

    def test_failed_length_repair_preserves_both_real_completion_artifacts_and_usage(self):
        b = bundle()
        b['article']['content'] = b['article']['content'][:2106]
        first, final = writer_response(b), writer_response(b)
        first['id'], final['id'] = 'short-original', 'short-final'
        artifacts, fake = [], Fake(first, final)
        model = Models(ENV, fake, artifact_sink=artifacts.append)
        with self.assertRaisesRegex(ModelError, 'Article length outside'):
            model.draft({}, context())
        self.assertEqual([a['responseId'] for a in artifacts], ['short-original', 'short-final'])
        self.assertEqual([u['responseId'] for u in model.usage], ['short-original', 'short-final'])
        self.assertEqual(len(fake.calls), 2)

    def test_revision_author_literals_lead_writer_prompt_and_paraphrases_still_fail(self):
        facts = ['2020年からスノーピークの焚火台Lを使っています。',
                 '最初の焚き火台はキャプテンスタッグでした。']
        ctx = context()
        ctx.update(verifiedAuthorFacts=facts,
                   existingArticle={'slug': 'tent-guide', 'content': 'LEGACY_CONTEXT' * 4000})
        candidate = bundle()
        candidate['article']['content'] += '\n' + '\n'.join(facts)
        candidate['brief']['protected'].extend(facts)
        fake = Fake(writer_response(candidate))
        result = Models(ENV, fake).draft({}, ctx)
        prompt = fake.calls[0][2]['messages'][0]['content']
        self.assertTrue(prompt.startswith(json.dumps(facts, ensure_ascii=False) + '\n'))
        instruction = prompt[:prompt.index('LEGACY_CONTEXT')]
        for requirement in ('complete verbatim sentence', 'Do not paraphrase',
                            'do not shorten', 'が', 'brief.protected'):
            self.assertIn(requirement, instruction)
        self.assertEqual(result['article']['content'], candidate['article']['content'])
        self.assertEqual(result['brief']['protected'], candidate['brief']['protected'])
        for fact in facts:
            paraphrased = copy.deepcopy(candidate)
            paraphrased['article']['content'] = paraphrased['article']['content'].replace(
                fact, fact[:-1] + 'が、選び方は用途によります。')
            with self.subTest(fact=fact), self.assertRaisesRegex(ModelError, 'Verified author fact removed'):
                Models(ENV, Fake(writer_response(paraphrased))).draft({}, ctx)

    def test_research_rejects_unmeasured_firsthand_title(self):
        themes = copy.deepcopy(THEMES)
        themes['themes'][0]['title'] = '冬のバーナー実測結果'
        with self.assertRaisesRegex(ModelError, 'Unverified firsthand'):
            Models(ENV, Fake(response(themes))).research(context())

    def test_review_medical_flag_means_candidate_check_passed_not_applicability(self):
        false_review = dict(REVIEW, medical=False)
        fake = Fake(response(false_review))
        reviewed = Models(ENV, fake).review(bundle(), FLAGS)
        self.assertFalse(reviewed['medical'])
        self.assertFalse(reviewed['passed'])
        self.assertEqual(len(fake.calls), 1)
        prompt = fake.calls[0][2]['messages'][0]['content']
        for phrase in ('medical=true means you checked the candidate title/body/FAQs',
                       'absence of such claims means medical=true after that actual check',
                       'medical=false means a risk or failed check, never N/A',
                       'apply ONLY to candidate article content', 'never certify inherited clinical accuracy'):
            self.assertIn(phrase, prompt)

    def test_review_accepts_only_bound_nonproduct_affiliate_na_without_claiming_measurement(self):
        contract = nonproduct_fixture()
        checks = dict(facts=True, images=True, medical=True, render=True,
                      affiliate=contract['reviewAffiliateEvidence'])
        reviewed = Models(ENV, Fake(response(REVIEW))).review(contract['bundle'], checks)
        self.assertTrue(reviewed['passed'])
        self.assertFalse(checks['affiliate']['measured'])
        broken = copy.deepcopy(checks)
        broken['affiliate']['provenanceFingerprint'] = '0' * 64
        blocked = Models(ENV, Fake(response(REVIEW))).review(contract['bundle'], broken)
        self.assertFalse(blocked['passed'])
        self.assertIn('Missing independent affiliate evidence', blocked['issues'])

    def test_review_recomputes_postpolish_length_before_any_provider_request(self):
        from models import ARTICLE_LENGTHS
        for format_name, (lower, upper) in ARTICLE_LENGTHS.items():
            for count in (lower - 1, lower, upper, upper + 1):
                with self.subTest(format=format_name, count=count):
                    candidate = bundle()
                    candidate['brief']['format'] = format_name
                    candidate['article']['content'] = '文' * count
                    measurements = dict(format=format_name, contentCharacters=count, minimumCharacters=lower,
                                        maximumCharacters=upper, method='python_len_decoded_article_content')
                    checks = dict(evidence=FLAGS, articleMeasurements=measurements)
                    fake = Fake(response(REVIEW))
                    model = Models(ENV, fake)
                    if lower <= count <= upper:
                        self.assertTrue(model.review(candidate, checks)['passed'])
                        self.assertEqual(1, len(fake.calls))
                        prompt = fake.calls[0][2]['messages'][0]['content']
                        self.assertIn('checks.articleMeasurements is the source of truth', prompt)
                        self.assertEqual(measurements, prompt_data(prompt)['checks']['articleMeasurements'])
                    else:
                        with self.assertRaisesRegex(ModelError, 'Article length outside existing SKILL limits'):
                            model.review(candidate, checks)
                        self.assertEqual([], fake.calls)

    def test_review_rejects_forged_or_invalid_measurements_before_provider_request(self):
        candidate = bundle()
        original = dict(format='guide', contentCharacters=len(candidate['article']['content']),
                        minimumCharacters=3000, maximumCharacters=5000, method='python_len_decoded_article_content')
        for forged in (None, {}, dict(original, contentCharacters=3000), dict(original, format='review'),
                       dict(original, minimumCharacters=2000), dict(original, maximumCharacters=8000),
                       dict(original, method='tokens'), dict(original, extra=True),
                       dict(original, contentCharacters=float(original['contentCharacters']))):
            with self.subTest(forged=forged):
                fake = Fake(response(REVIEW))
                with self.assertRaisesRegex(ModelError, 'Article measurements do not match'):
                    Models(ENV, fake).review(candidate, dict(evidence=FLAGS, articleMeasurements=forged))
                self.assertEqual([], fake.calls)
        for invalid in ({}, dict(candidate, brief={'format': 'unknown'}),
                        dict(candidate, article={'content': None}), dict(candidate, brief={'format': []})):
            with self.subTest(invalid=invalid):
                fake = Fake(response(REVIEW))
                with self.assertRaisesRegex(ModelError, 'Invalid article measurement source'):
                    Models(ENV, fake).review(invalid, dict(evidence=FLAGS, articleMeasurements=original))
                self.assertEqual([], fake.calls)

    def test_review_without_measurements_retains_legacy_direct_call_compatibility(self):
        candidate = bundle()
        candidate['article']['content'] = 'Short legacy fixture'
        fake = Fake(response(REVIEW))
        self.assertTrue(Models(ENV, fake).review(candidate, FLAGS)['passed'])
        self.assertEqual(1, len(fake.calls))

    def test_claude_review_wire_omits_unsupported_bounds_but_local_wise_gate_remains_strict(self):
        policy = load_policy()
        scores = dict(w=2, i=2, s=2, e=2, ai=3, sense=2)
        for kind, schema in (('article', REVIEW_SCHEMA), ('social', SOCIAL_REVIEW_SCHEMA)):
            checks = dict(wisePolicy=policy, reviewKind=kind, evidence=FLAGS)
            if kind == 'article':
                checks['editorialRules'] = policy['text']
            value = dict(REVIEW, wiseScores=scores, criteria=dict.fromkeys(CRITERIA_FIELDS, 8),
                         observations=[], evidence={'summary': 'Synthetic reviewed claims'})
            fake = Fake(response(value))
            self.assertTrue(Models(ENV, fake).review(bundle(), checks)['passed'])
            wire = fake.calls[0][2]['output_config']['format']['schema']
            self.assertEqual(schema, wire)
            self.assertEqual({axis: {'type': 'number'} for axis in scores},
                             wire['properties']['wiseScores']['properties'])
            for axis in scores:
                for bad in (0, 5, True, '3'):
                    with self.subTest(kind=kind, axis=axis, value=bad):
                        fake = Fake(response(dict(value, wiseScores=dict(scores, **{axis: bad}))))
                        with self.assertRaisesRegex(ModelError, 'Complete owner WISE-AS six scores required'):
                            Models(ENV, fake).review(bundle(), checks)
                        self.assertEqual(1, len(fake.calls))
                with self.subTest(kind=kind, floor=axis):
                    low = dict(value, wiseScores=dict(scores, **{axis: scores[axis] - 1}))
                    reviewed = Models(ENV, Fake(response(low))).review(bundle(), checks)
                    self.assertFalse(reviewed['passed'])
                    self.assertIn('Owner WISE-AS floor failed', reviewed['issues'])

    def test_review_http400_schema_failure_is_safe_terminal_and_charged_once(self):
        body = b'{"error":{"type":"invalid_request_error","message":"schema minimum SECRET BODY"}}'
        failure = HTTPError('https://provider.invalid', 400, 'schema SECRET BODY', {}, io.BytesIO(body))
        fake, budget = Fake(failure, response(REVIEW)), Budget()
        model = Models(ENV, fake, budget=budget)
        with patch('models.time.sleep') as sleep:
            with self.assertRaises(ModelError) as caught:
                model.review(bundle(), FLAGS)
            sleep.assert_not_called()
        self.assertEqual('Provider request failed (HTTP 400)', str(caught.exception))
        self.assertEqual(400, caught.exception.status)
        self.assertIsNone(caught.exception.__context__)
        self.assertEqual(1, len(fake.calls))
        self.assertEqual(1, len(budget.holds))
        self.assertEqual([('hold-1', None, 'failed')], budget.settlements)
        self.assertEqual([], model.usage)

    def test_editorial_rubric_requires_all_scores_and_caps_overall_mean(self):
        checks = {'editorialRules': 'WISE Supervisor eleven criteria', 'evidence': FLAGS}
        with self.assertRaises(ModelError):
            Models(ENV, Fake(response(REVIEW))).review(bundle(), checks)
        result = copy.deepcopy(REVIEW)
        result['criteria'] = dict.fromkeys(('wise_w', 'wise_i', 'wise_s', 'wise_e', 'wise_ai', 'wise_sense',
            'affiliate_links', 'comparison_table', 'internal_links', 'faq', 'word_count'), 7)
        result['evidence'] = {'summary': 'Reviewed all claims'}
        result['observations'] = []
        reviewed = Models(ENV, Fake(response(result))).review(bundle(), checks)
        self.assertFalse(reviewed['passed'])
        self.assertEqual(7, reviewed['score'])

    def test_failed_review_keeps_arithmetic_diagnostic_without_grade_reroll(self):
        checks = {'editorialRules': 'WISE Supervisor', 'evidence': FLAGS}
        raw = dict(REVIEW, passed=True, score=7.6,
                   criteria=dict.fromkeys(CRITERIA_FIELDS, 7),
                   evidence={'summary': 'Claims reviewed'}, observations=[])
        provider_artifacts = []
        fake = Fake(response(raw))
        model = Models(ENV, fake, artifact_sink=provider_artifacts.append)
        result = model.review(bundle(), checks)
        diagnostic, = model.review_diagnostics
        self.assertFalse(result['passed'])
        self.assertEqual(7, diagnostic['actualMean'])
        self.assertEqual(7.6, diagnostic['rawScore'])
        self.assertTrue(diagnostic['rawPassed'])
        self.assertFalse(diagnostic['normalizedPassed'])
        self.assertEqual(['overall_score_exceeds_criteria_mean',
                          'model_pass_below_criteria_threshold'], diagnostic['contractIssues'])
        self.assertEqual(1, len(fake.calls))
        self.assertEqual(1, len(provider_artifacts))

    def test_review_reports_provider_pass_with_failing_overall_score(self):
        raw = dict(REVIEW, passed=True, score=7.4,
                   criteria=dict.fromkeys(CRITERIA_FIELDS, 8),
                   evidence={'summary': 'Claims reviewed'}, observations=[])
        model = Models(ENV, Fake(response(raw)))
        self.assertFalse(model.review(bundle(), {'editorialRules': 'rubric', 'evidence': FLAGS})['passed'])
        self.assertEqual(['model_pass_below_score_threshold'],
                         model.review_diagnostics[0]['contractIssues'])

    def test_review_uses_unrounded_criteria_mean_and_keeps_model_issues(self):
        checks = {'editorialRules': 'WISE Supervisor', 'evidence': FLAGS}
        fields = ('wise_w', 'wise_i', 'wise_s', 'wise_e', 'wise_ai', 'wise_sense',
                  'affiliate_links', 'comparison_table', 'internal_links', 'faq', 'word_count')
        low = dict(zip(fields, [8] * 5 + [7] * 6))
        fake = Fake(response(dict(REVIEW, score=7.8, criteria=low, evidence={'summary': 'Reviewed claims'},
                                  observations=['No medical claim'])))
        result = Models(ENV, fake).review(bundle(), checks)
        self.assertEqual(result['score'], 82 / 11)
        self.assertFalse(result['passed'])
        prompt = fake.calls[0][2]['messages'][0]['content']
        for phrase in ('issues must contain ONLY required corrections or blockers', 'observations',
                       'pending future human approval', 'unrounded mean', 'never round 7.4545 up'):
            self.assertIn(phrase, prompt)
        wire = fake.calls[0][2]['output_config']['format']
        self.assertEqual(wire, {'type': 'json_schema', 'schema': REVIEW_SCHEMA})
        self.assertEqual(set(REVIEW_SCHEMA['required']), set(REVIEW_SCHEMA['properties']))
        self.assertEqual(set(REVIEW_SCHEMA['properties']['criteria']['required']), set(CRITERIA_FIELDS))
        for object_schema in (REVIEW_SCHEMA, REVIEW_SCHEMA['properties']['criteria'],
                              REVIEW_SCHEMA['properties']['evidence']):
            self.assertIs(object_schema['additionalProperties'], False)
        self.assertEqual(REVIEW_SCHEMA['properties']['evidence']['required'], ['summary'])
        flat = dict(REVIEW, score=7.8, evidence={'summary': 'Reviewed claims'}, observations=[], **low)
        with self.assertRaisesRegex(ModelError, 'Complete WISE Supervisor scores required'):
            Models(ENV, Fake(response(flat))).review(bundle(), checks)
        high = dict(zip(fields, [8] * 6 + [7] * 5))
        passing = Models(ENV, Fake(response(dict(REVIEW, score=7.8, criteria=high,
                                                  evidence={'summary': 'Reviewed claims'},
                                                  observations=['No medical claim'])))).review(bundle(), checks)
        self.assertTrue(passing['passed'])
        self.assertEqual(passing['issues'], [])
        blocked = Models(ENV, Fake(response(dict(REVIEW, score=7.8, criteria=high,
                                                 evidence={'summary': 'Reviewed claims'}, observations=[],
                                                 issues=['Unsupported claim'])))).review(bundle(), checks)
        self.assertFalse(blocked['passed'])
        self.assertEqual(blocked['issues'], ['Unsupported claim'])

    def test_research_complete_evidence_headers_usage(self):
        ctx = context()
        ctx["longEvidence"] = "z" * 12000 + "END-EVIDENCE"
        fake = Fake(response(THEMES))
        model = Models(ENV, fake)
        self.assertEqual(model.research(ctx), THEMES)
        url, headers, payload, timeout = fake.calls[0]
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertEqual(headers["x-api-key"], ENV["ANTHROPIC_API_KEY"])
        self.assertEqual(payload["model"], "claude-sonnet-4-6")
        self.assertIn("END-EVIDENCE", payload["messages"][0]["content"])
        self.assertLessEqual(timeout, 180)
        self.assertEqual(model.usage, [{"responseId": "c-1", "model": "claude-sonnet-4-6", "input": 31,
                                      "output": 9, "usage": {"input_tokens": 31, "output_tokens": 9}, "actualUSD": None}])

    def test_research_rejects_duplicates_wrong_count_and_existing_title(self):
        for value, ctx in [({"themes": []}, {}), ({"themes": [{"title": "same"}] * 3}, {}),
                           (THEMES, {"existingArticles": [{"title": "Winter tent weight choice"}]})]:
            with self.subTest(value=value):
                with self.assertRaises(ModelError):
                    Models(ENV, Fake(response(value))).research(ctx)

    def test_draft_404_only_fallback_preserves_full_bundle(self):
        fake = Fake(http(404), writer_response(bundle()))
        model = Models(ENV, fake)
        expected = bundle()
        expected['article'].pop('id')
        self.assertEqual(model.draft(THEMES["themes"][0], context()), expected)
        self.assertEqual([c[2]["model"] for c in fake.calls], ["claude-opus-4-8", "claude-sonnet-4-6"])
        self.assertIn("Article template: no H1", fake.calls[-1][2]["messages"][0]["content"])
        self.assertTrue(all(call[2]['output_config']['format']['schema'] == WRITER_SCHEMA for call in fake.calls))

    def test_writer_schema_only_on_writer_and_context_records_copied_exactly(self):
        fake = Fake(writer_response(bundle()))
        ctx = context()
        selected = {'productIds': ['tent-a']}
        result = Models(ENV, fake).draft(selected, ctx)
        self.assertEqual(set(result), {'article', 'brief', 'products', 'references', 'images'})
        for field, source in (('products', 'catalog'), ('references', 'references'), ('images', 'images')):
            self.assertEqual(result[field], ctx[source])
            self.assertIsNot(result[field], ctx[source])
        payload = fake.calls[0][2]
        self.assertIn('Do not create an empty ## FAQ heading', payload['messages'][0]['content'])
        self.assertIn('let the structured article.faqs render', payload['messages'][0]['content'])
        self.assertEqual(payload['output_config'], {'format': {'type': 'json_schema', 'schema': WRITER_SCHEMA}})
        self.assertNotIn('response_format', payload)
        def objects(schema):
            if schema.get('type') == 'object':
                self.assertIs(schema.get('additionalProperties'), False)
            for child in schema.get('properties', {}).values():
                objects(child)
            if isinstance(schema.get('items'), dict):
                objects(schema['items'])
        objects(WRITER_SCHEMA)
        research = Fake(response(THEMES))
        Models(ENV, research).research(context())
        self.assertNotIn('output_config', research.calls[0][2])
        self.assertNotIn('response_format', research.calls[0][2])

    def test_writer_requires_exact_selected_product_ids_and_no_reemitted_records(self):
        payload = {'article': {k: v for k, v in bundle()['article'].items() if k != 'id'}, 'brief': brief()}
        payload['article']['productIds'] = ['ghost']
        with self.assertRaises(ModelError):
            Models(ENV, Fake(response(payload))).draft({'productIds': ['tent-a']}, context())
        payload['article']['productIds'] = ['tent-a']
        payload['products'] = [{'id': 'tent-a', 'price': 0}]
        with self.assertRaisesRegex(ModelError, 'Invalid writer response fields'):
            Models(ENV, Fake(response(payload))).draft({'productIds': ['tent-a']}, context())

    def test_draft_assembles_only_missing_verified_product_cards(self):
        b = bundle()
        original = b['article']['content'].replace('{{product:tent-a}}', '')
        b['article']['content'] = original
        fake = Fake(writer_response(b))
        result = Models(ENV, fake).draft({'productIds': ['tent-a']}, context())
        self.assertEqual(result['article']['content'], original + '\n\n{{product:tent-a}}')
        self.assertIn('{{product:exact-ID}} for every selected product', fake.calls[0][2]['messages'][0]['content'])
        for tag in ('{{product:tent-a}}', '{{comparison:tent-a}}', '{{ranking:tent-a}}'):
            b = bundle()
            b['article']['content'] = b['article']['content'].replace('{{product:tent-a}}', tag)
            result = Models(ENV, Fake(writer_response(b))).draft({}, context())
            self.assertEqual(result['article']['content'], b['article']['content'])
        b = bundle()
        b['article']['content'] = b['article']['content'].replace('{{product:tent-a}}', '`{{product:tent-a}}`')
        result = Models(ENV, Fake(writer_response(b))).draft({}, context())
        self.assertTrue(result['article']['content'].endswith('\n\n{{product:tent-a}}'))

    def test_draft_card_assembly_rejects_unknown_id_and_post_insert_overflow(self):
        b = bundle()
        b['article']['content'] = b['article']['content'].replace('{{product:tent-a}}', '{{product:ghost}}')
        with self.assertRaisesRegex(ModelError, 'Unknown product ID'):
            Models(ENV, Fake(writer_response(b))).draft({}, context())
        b = bundle()
        prefix = '## Choice\n[設営](/articles/setup) [撤収](/articles/pack)\n'
        b['article']['content'] = prefix + '文' * (5000 - len(prefix))
        with self.assertRaisesRegex(ModelError, 'Article length outside'):
            Models(ENV, Fake(writer_response(b), writer_response(b))).draft({}, context())

    def test_overrides_and_nonretry_auth_bad_request(self):
        for status in (400, 401, 500):
            fake = Fake(http(status))
            with self.assertRaises(ModelError) as caught:
                Models(ENV, fake).draft({}, context())
            self.assertEqual(len(fake.calls), 1)
            self.assertNotIn("SECRET", str(caught.exception))
            self.assertNotIn("test-claude-key", str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)
        env = dict(ENV, ARTICLE_WRITER_MODEL="writer", ARTICLE_WRITER_FALLBACK_MODEL="fallback", ARTICLE_REVIEW_MODEL="reviewer")
        fake = Fake(http(404), writer_response(bundle()), response(REVIEW))
        model = Models(env, fake)
        model.draft({}, context())
        model.review(bundle(), FLAGS)
        self.assertEqual([c[2]["model"] for c in fake.calls], ["writer", "fallback", "reviewer"])

    def test_retry_bounded_on_only_429_503(self):
        for code in (429, 503):
            fake = Fake(http(code), http(code), response(THEMES))
            with patch("models.time.sleep"):
                self.assertEqual(Models(ENV, fake).research({}), THEMES)
            self.assertEqual(len(fake.calls), 3)
            fake = Fake(http(code), http(code), http(code), response(THEMES))
            with patch("models.time.sleep"), self.assertRaises(ModelError):
                Models(ENV, fake).research({})
            self.assertEqual(len(fake.calls), 3)

    def test_total_deadline_includes_fallback(self):
        fake = Fake(http(404), writer_response(bundle()))
        with patch("models.time.monotonic", side_effect=[0, 0, 181]), self.assertRaises(ModelError):
            Models(ENV, fake).draft({}, context())
        self.assertEqual(len(fake.calls), 1)

    def test_strict_json_no_fences_trailing_text_nonfinite_or_duplicate_keys(self):
        for raw in ('```json\n{}\n```', '{} trailing', '{"themes":NaN}', '{"themes": [], "themes": []}', '[]'):
            with self.subTest(raw=raw), self.assertRaises(ModelError):
                Models(ENV, Fake(response(None, raw=raw))).research({})

    def test_no_missing_bundle_fields_or_invented_products_references(self):
        mutations = [lambda b: b.pop("brief"), lambda b: b["brief"].pop("facts"),
                     lambda b: b["brief"].update(externalSafe="true"),
                     lambda b: b["article"].update(productIds=["ghost"])]
        for index, mutate in enumerate(mutations):
            b = bundle()
            mutate(b)
            payload = {"article": {k: v for k, v in b["article"].items() if k != 'id'}}
            if 'brief' in b:
                payload['brief'] = b['brief']
            with self.subTest(index=index), self.assertRaises(ModelError):
                Models(ENV, Fake(response(payload))).draft({}, context())
        for field in ('products', 'references', 'images'):
            payload = {'article': {k: v for k, v in bundle()['article'].items() if k != 'id'},
                       'brief': brief(), field: [{'invented': True}]}
            with self.subTest(field=field), self.assertRaisesRegex(ModelError, 'Invalid writer response fields'):
                Models(ENV, Fake(response(payload))).draft({}, context())

    def test_polish_full_brief_source_unchanged_fixed_endpoint_and_usage(self):
        b = brief()
        b["protected"].append("TAIL" * 3000)
        before = copy.deepcopy(b)
        fake = Fake(response({"edits": [{"index": 0, "text": "Polished"}]}, gemini=True))
        model = Models(ENV, fake)
        result = model.polish("Original", b)
        self.assertEqual(result["content"], "Polished")
        self.assertEqual(result["model"], "gemini-3.8-flash")
        self.assertEqual(result["usage"]["output"], 9)
        self.assertEqual(result["usage"]["polishEditsApplied"], 1)
        self.assertEqual(b, before)
        self.assertEqual(fake.calls[0][0], "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
        self.assertEqual(fake.calls[0][1]["Authorization"], "Bearer test-gemini-key")
        self.assertIn("TAIL" * 3000, fake.calls[0][2]["messages"][0]["content"])
        self.assertNotIn('output_config', fake.calls[0][2])

    def test_polish_only_eligible_paragraphs_and_preserves_exact_separators(self):
        source = '## 見出し\n\n直せる文章です。\n \n重量は2kgです。\n\n広告を含む文章。\n\n別の文章です。'
        fake = Fake(response({'edits': [{'index': 1, 'text': '読みやすい文章です。'}]}, gemini=True))
        result = Models(ENV, fake).polish(source, brief())
        self.assertEqual(result['content'], source.replace('直せる文章です。', '読みやすい文章です。'))
        sent = prompt_data(fake.calls[0][2]['messages'][0]['content'])
        self.assertEqual(sent['source'], source)
        self.assertEqual([item['index'] for item in sent['editable']], [1, 4])
        self.assertEqual(result['usage']['polishOutcome'], 'edited')
        empty = Models(ENV, Fake(response({'edits': []}, gemini=True))).polish(source, brief())
        self.assertEqual(empty['content'], source)
        self.assertEqual(empty['usage']['polishOutcome'], 'no_changes')

    def test_polish_rejects_immutable_new_numbers_duplicate_and_malformed_edits(self):
        source = '## 見出し\n\n直せる文章です。\n\n重量は2kgです。'
        bad = [
            {'edits': [{'index': 0, 'text': '見出し変更'}]},
            {'edits': [{'index': 2, 'text': '重量は3kgです。'}]},
            {'edits': [{'index': 1, 'text': '3kgです。'}]},
            {'edits': [{'index': 1, 'text': '直した文。'}, {'index': 1, 'text': '別の文。'}]},
            {'edits': [{'index': True, 'text': '直した文。'}]},
            {'edits': [{'index': 1, 'text': '前半\n\n後半'}]},
            {'content': '全文を書き直した'},
        ]
        for index, value in enumerate(bad):
            with self.subTest(index=index), self.assertRaises(ModelError):
                Models(ENV, Fake(response(value, gemini=True))).polish(source, brief())

    def test_polish_prompt_forbids_fixed_literals_in_eligible_edits_and_collision_still_rejects(self):
        b = brief()
        b['requiredExpressions'].append('使用時と収納時を分けて確認')
        b['protected'].append('用途に合わせて選ぶ')
        source = '## 寸法\n\n使用時と収納時を分けて確認してください。\n\n用途に合わせて選ぶ記事です。\n\n重量は2kgです。\n\n広告\n\n寸法を確かめる文章です。'
        original = copy.deepcopy(b)
        for literal in ('使用時と収納時を分けて確認', '用途に合わせて選ぶ'):
            fake = Fake(response({'edits': [{'index': 5, 'text': 'ツーバーナーの寸法は、必ず' + literal + 'してください。'}]}, gemini=True))
            with self.subTest(literal=literal), self.assertRaisesRegex(ModelError, '^Invalid polish edits$'):
                Models(ENV, fake).polish(source, b)
            self.assertEqual(len(fake.calls), 1)
            prompt = fake.calls[0][2]['messages'][0]['content']
            self.assertIn('Do not introduce ANY exact literal from brief.protected or brief.requiredExpressions', prompt)
            self.assertIn('even if natural', prompt)
            self.assertIn('original locked paragraphs', prompt)
            payload = prompt_data(prompt)
            self.assertEqual(payload['source'], source)
            self.assertEqual(payload['brief'], original)
            self.assertIn(literal, payload['forbiddenExpressions'])
            self.assertEqual(payload['editable'], [{'index': 5, 'text': '寸法を確かめる文章です。'}])
        self.assertEqual(b, original)

    def test_polish_secret_and_external_safe_gate_before_network(self):
        for source, change in [("body", {"externalSafe": False}), ("body", {"externalSafe": 1}),
                               ("body", {"externalSafe": "true"}), ("sk-ant-12345678901234567890", {}),
                               ("Authorization: Bearer abcdef123456", {}), ("body", {"facts": ["api_key=secret"]}),
                               ("body", {"facts": [ENV["ANTHROPIC_API_KEY"]]})]:
            b = brief()
            b.update(change)
            fake = Fake()
            with self.subTest(source=source, change=change), self.assertRaises(ModelError):
                Models(ENV, fake).polish(source, b)
            self.assertEqual(fake.calls, [])

    def test_review_cannot_certify_live_checks_from_model(self):
        for checks in ({}, dict(FLAGS, images=False), dict(FLAGS, affiliate="true"), dict(FLAGS, render=None)):
            result = Models(ENV, Fake(response(REVIEW))).review(bundle(), checks)
            self.assertFalse(result["passed"])
            self.assertTrue(result["issues"])
        result = Models(ENV, Fake(response(REVIEW))).review(bundle(), FLAGS)
        self.assertTrue(result["passed"])
        self.assertEqual(result["evidence"]["checks"], FLAGS)
        for value in (dict(REVIEW, score=7.4), dict(REVIEW, facts=False), dict(REVIEW, issues=["unverified"])):
            self.assertFalse(Models(ENV, Fake(response(value))).review(bundle(), FLAGS)["passed"])

    def test_review_prompt_audits_article_claims_separately_from_catalog_flags(self):
        approved = {'title': 'Approved comparison', 'constraints': ['No indoor use claim']}
        checks = {'evidence': FLAGS, 'approvedTheme': approved}
        fake = Fake(response(REVIEW))
        Models(ENV, fake).review(bundle(), checks)
        prompt = fake.calls[0][2]['messages'][0]['content']
        for phrase in ('catalog product specifications ONLY', 'title', 'metadata', 'FAQs',
                       'checks.approvedTheme', 'Astra constraints', 'reversed', 'fictional anecdotes',
                       'measurement conditions', 'price or availability'):
            self.assertIn(phrase, prompt)
        self.assertIn('No indoor use claim', prompt)
        self.assertNotIn('output_config', fake.calls[0][2])

    def test_social_review_scopes_published_source_and_cannot_override_machine_evidence(self):
        source = bundle()
        source['article']['status'] = 'draft'  # Historical bundle status is not publication state.
        proposal = {'text': '広告 公表仕様の紹介', 'replyText': 'https://camp-gear-lab.com/articles/tent'}
        subject = {'source': source, 'proposal': proposal, 'article': {'content': proposal['text']}}
        checks = {'evidence': FLAGS, 'publicationReadback': {'verified': True},
                  'factualSource': source['article']['content']}
        fake = Fake(response(REVIEW))
        self.assertTrue(Models(ENV, fake).review(subject, checks)['passed'])
        prompt = fake.calls[0][2]['messages'][0]['content']
        for phrase in ('When bundle.proposal is present', 'checks.publicationReadback',
                       'historical source.article.status is not current', 'lack of your own browser is not itself failure',
                       'Missing or contradictory independent evidence must still fail'):
            self.assertIn(phrase, prompt)
        for missing in ('images', 'render'):
            weakened = dict(checks, evidence=dict(FLAGS, **{missing: False}))
            result = Models(ENV, Fake(response(REVIEW))).review(subject, weakened)
            self.assertFalse(result['passed'])
            self.assertFalse(result[missing])
            self.assertIn('Missing independent ' + missing + ' evidence', result['issues'])

    def test_social_requires_public_content_and_images_readback(self):
        b = bundle()
        url = "https://camp-gear-lab.com/articles/tent"
        fake = Fake()
        with self.assertRaises(ModelError):
            Models(ENV, fake).social(b, url)
        self.assertEqual(fake.calls, [])
        b['images'][0]['verified'] = True
        b["publicReadback"] = dict(verified=True, url=url, content=b["article"]["content"], images=b["images"])
        post = dict(text="広告 Gear selection", replyText=url)
        fake = Fake(response(post))
        result = Models(ENV, fake).social(b, url)
        self.assertEqual(result, dict(post, url=url, images=b['images'], platform='x'))
        self.assertIsNot(result['images'], b['images'])
        self.assertIsNot(result['images'][0], b['images'][0])
        self.assertEqual(fake.calls[0][2]['output_config']['format'],
                         {'type': 'json_schema', 'schema': SOCIAL_SCHEMA})
        self.assertEqual(set(SOCIAL_SCHEMA['required']), {'text', 'replyText'})
        self.assertIs(SOCIAL_SCHEMA['additionalProperties'], False)
        prompt = fake.calls[0][2]['messages'][0]['content']
        sent = prompt_data(prompt)
        self.assertEqual(sent['bundle']['article']['content'], b['article']['content'])
        self.assertEqual(sent['bundle']['brief'], b['brief'])
        for constraint in ('160 weighted', 'hard limit 280', 'each non-ASCII', 'friend questions',
                           'unsupported winter performance', 'unknown measurement conditions differ',
                           'warming/insulating gas-can advice'):
            self.assertIn(constraint, prompt)
        for change in ({"text": "広告 " + url}, {"replyText": "no link"}, {"text": "Gear selection"},
                       {"url": "https://other.example"}, {"platform": "threads"}):
            with self.subTest(change=change), self.assertRaises(ModelError):
                Models(ENV, Fake(response(dict(post, **change)))).social(b, url)

    def test_social_weighted_limit_is_enforced_before_polish_without_truncation(self):
        b = bundle()
        url = 'https://camp-gear-lab.com/articles/tent'
        b['images'][0]['verified'] = True
        b['publicReadback'] = dict(verified=True, url=url, content=b['article']['content'], images=b['images'])
        for text, accepted in [('広告' + 'a' * 276, True), ('広告' + 'a' * 277, False),
                               ('広告' + 'あ' * 138, True), ('広告' + 'あ' * 139, False),
                               ('広告' + '🏕' * 138, True), ('広告' + '🏕' * 139, False),
                               ('広告' + 'a' * 217, True), ('', False), ('   ', False)]:
            fake = Fake(response({'text': text, 'replyText': url}), response({'text': text, 'replyText': url}))
            with self.subTest(weight=sum(1 if ord(c) < 128 else 2 for c in text)):
                if accepted:
                    self.assertEqual(Models(ENV, fake).social(b, url)['text'], text)
                else:
                    with self.assertRaises(ModelError):
                        Models(ENV, fake).social(b, url)
                self.assertEqual(len(fake.calls), 1 if accepted else 2)

    def test_social_repairs_one_local_length_and_disclosure_failure_with_original_source(self):
        b = bundle()
        url = 'https://camp-gear-lab.com/articles/tent'
        b['article']['content'] += '\nPR 2kg 公表仕様。'
        b['images'][0]['verified'] = True
        b['publicReadback'] = copy.deepcopy(dict(verified=True, url=url,
            content=b['article']['content'], images=b['images']))
        original = copy.deepcopy(b)
        previous = dict(text='あ' * 200, replyText=url)
        first = response(previous)
        first['id'] = 'attempt-1'
        good = dict(text='広告 PR 公表仕様2kg。用途を確認します。', replyText=url)
        second = response(good)
        second['id'] = 'attempt-2'
        fake = Fake(first, second)
        artifacts = []
        model = Models(ENV, fake, artifact_sink=artifacts.append)
        result = model.social(b, url)
        self.assertEqual(result['text'], good['text'])
        self.assertEqual(b, original)
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual([a['responseId'] for a in artifacts], ['attempt-1', 'attempt-2'])
        prompts = [c[2]['messages'][0]['content'] for c in fake.calls]
        payload = prompt_data(prompts[1])
        self.assertEqual(payload['bundle'], original)
        self.assertEqual(payload['previousCandidate'], previous)
        self.assertEqual(payload['validation']['weightedLength'], 400)
        self.assertEqual(payload['validation']['missingDisclosures'], ['広告', 'PR'])
        self.assertIn('weighted_length_exceeds_280', payload['validation']['reasons'])
        for prompt in prompts:
            for required in ('160 weighted', 'hard limit 280', '1-2', 'Do not summarize every', 'Never truncate'):
                self.assertIn(required, prompt)
        self.assertTrue(all('anthropic.com' in call[0] for call in fake.calls))

    def test_social_repair_is_bounded_and_final_candidate_revalidated(self):
        b = bundle()
        url = 'https://camp-gear-lab.com/articles/tent'
        b['images'][0]['verified'] = True
        b['publicReadback'] = dict(verified=True, url=url, content=b['article']['content'], images=b['images'])
        bad = dict(text='広告' + 'あ' * 200, replyText=url)
        for final in (bad, dict(text='開示なし', replyText=url),
                      dict(text='広告 支持された仕様', replyText=url + '?changed=1')):
            fake = Fake(response(bad), response(final), response(dict(text='広告 本文', replyText=url)))
            with self.subTest(final=final), self.assertRaises(ModelError):
                Models(ENV, fake).social(b, url)
            self.assertEqual(len(fake.calls), 2)

    def test_social_pr_marker_requires_explicit_disclosure_not_product_prefix(self):
        b = bundle()
        url = 'https://camp-gear-lab.com/articles/tent'
        b['article']['content'] += '\nPR'
        b['images'][0]['verified'] = True
        b['publicReadback'] = dict(verified=True, url=url, content=b['article']['content'], images=b['images'])
        fake = Fake(response(dict(text='広告 Product 2kg', replyText=url)),
                    response(dict(text='広告 PR 公表仕様2kg', replyText=url)))
        self.assertEqual(Models(ENV, fake).social(b, url)['text'], '広告 PR 公表仕様2kg')
        self.assertEqual(len(fake.calls), 2)

    def test_social_transport_failure_during_repair_never_starts_third_generation(self):
        b = bundle()
        url = 'https://camp-gear-lab.com/articles/tent'
        b['images'][0]['verified'] = True
        b['publicReadback'] = dict(verified=True, url=url, content=b['article']['content'], images=b['images'])
        for failure in (http(500), TimeoutError('unknown')):
            fake = Fake(response(dict(text='広告' + 'あ' * 200, replyText=url)), failure,
                        response(dict(text='広告 本文', replyText=url)))
            with self.subTest(failure=type(failure)), self.assertRaises(ModelError):
                Models(ENV, fake).social(b, url)
            self.assertEqual(len(fake.calls), 2)

    def test_social_does_not_content_retry_transport_or_unknown_completion(self):
        b = bundle()
        url = 'https://camp-gear-lab.com/articles/tent'
        b['images'][0]['verified'] = True
        b['publicReadback'] = dict(verified=True, url=url, content=b['article']['content'], images=b['images'])
        truncated = response(dict(text='広告 本文', replyText=url))
        truncated['stop_reason'] = 'max_tokens'
        for error in (http(400), http(401), http(500), TimeoutError('unknown'),
                      response(None, raw='not JSON'), truncated):
            fake = Fake(error, response(dict(text='広告 本文', replyText=url)))
            with self.subTest(error=type(error)), self.assertRaises(ModelError):
                Models(ENV, fake).social(b, url)
            self.assertEqual(len(fake.calls), 1)

    def test_social_reply_is_exact_url_and_legacy_three_artifact_shapes_are_rejected(self):
        b = bundle()
        url = 'https://camp-gear-lab.com/articles/tent'
        b['images'][0]['verified'] = True
        b['publicReadback'] = dict(verified=True, url=url, content=b['article']['content'], images=b['images'])
        for reply in ['記事はこちら ' + url, url + ' ', '\n' + url, '[' + url + '](' + url + ')',
                      url + '?changed=1', url + '\nhttps://other.example', url + '\\n', None]:
            with self.subTest(reply=reply), self.assertRaises(ModelError):
                Models(ENV, Fake(response({'text': '広告 本文', 'replyText': reply}))).social(b, url)
        for count in (1, 2, 2):  # Original GS, CB and SOTO URL-array response contract.
            old = dict(text='広告 本文', replyText=url, url=url, platform='x',
                       images=[b['images'][0]['url']] * count)
            with self.subTest(count=count), self.assertRaisesRegex(ModelError, 'Invalid social response fields'):
                Models(ENV, Fake(response(old))).social(b, url)
        for value in ({'text': '広告 本文'}, {'text': 1, 'replyText': url},
                      {'text': '広告 本文', 'replyText': url, 'approved': True}):
            with self.subTest(value=value), self.assertRaises(ModelError):
                Models(ENV, Fake(response(value))).social(b, url)

    def test_social_unverified_source_brief_or_images_never_calls_provider(self):
        url = 'https://camp-gear-lab.com/articles/tent'
        for mode in ('content', 'url', 'verified', 'image', 'image_type', 'brief'):
            b = bundle()
            b['images'][0]['verified'] = True
            b['publicReadback'] = copy.deepcopy(dict(verified=True, url=url,
                content=b['article']['content'], images=b['images']))
            if mode == 'content': b['publicReadback']['content'] = 'different'
            if mode == 'url': b['publicReadback']['url'] += '?different'
            if mode == 'verified': b['publicReadback']['verified'] = 1
            if mode == 'image':
                b['images'][0]['verified'] = False
                b['publicReadback']['images'] = copy.deepcopy(b['images'])
            if mode == 'image_type':
                b['images'] = [b['images'][0]['url']]
                b['publicReadback']['images'] = copy.deepcopy(b['images'])
            if mode == 'brief': b['brief']['externalSafe'] = False
            fake = Fake()
            with self.subTest(mode=mode), self.assertRaises(ModelError):
                Models(ENV, fake).social(b, url)
            self.assertEqual(fake.calls, [])

    def test_social_preserves_each_source_disclosure_in_main_text(self):
        b = bundle()
        url = 'https://camp-gear-lab.com/articles/tent'
        b['article']['content'] = '広告 アフィリエイト PR #ad affiliate sponsored'
        b['images'][0]['verified'] = True
        b['publicReadback'] = dict(verified=True, url=url, content=b['article']['content'], images=b['images'])
        text = b['article']['content'] + ' 公表仕様の調査です。'
        self.assertEqual(Models(ENV, Fake(response({'text': text, 'replyText': url}))).social(b, url)['text'], text)
        for marker in ('広告', 'アフィリエイト', 'PR', '#ad', 'affiliate', 'sponsored'):
            with self.subTest(marker=marker), self.assertRaisesRegex(ModelError, 'disclosure removed'):
                Models(ENV, Fake(response({'text': text.replace(marker, ''), 'replyText': url}),
                                 response({'text': text.replace(marker, ''), 'replyText': url}))).social(b, url)

    def test_truncation_missing_usage_transport_errors_are_sanitized(self):
        truncated = response(THEMES)
        truncated["stop_reason"] = "max_tokens"
        missing_usage = response(THEMES)
        missing_usage.pop("usage")
        for value in (truncated, missing_usage, RuntimeError("SECRET test-claude-key")):
            with self.assertRaises(ModelError) as caught:
                Models(ENV, Fake(value)).research({})
            self.assertNotIn("SECRET", str(caught.exception))

    def test_research_rejects_missing_evidence_and_unknown_product(self):
        for field in ("slug", "categoryId", "query", "productIds", "selectionReason"):
            value = copy.deepcopy(THEMES)
            value["themes"][0].pop(field)
            with self.subTest(field=field), self.assertRaises(ModelError):
                Models(ENV, Fake(response(value))).research(context())
        value = copy.deepcopy(THEMES)
        value["themes"][0]["productIds"] = ["ghost"]
        with self.assertRaises(ModelError):
            Models(ENV, Fake(response(value))).research(context())

    def test_research_excludes_existing_query_even_when_title_differs(self):
        ctx = context()
        ctx["existingArticles"] = [{"title": "Different title", "query": "winter tent weight choice"}]
        with self.assertRaises(ModelError):
            Models(ENV, Fake(response(THEMES))).research(ctx)

    def test_draft_validates_runtime_required_article_shape(self):
        fields = ("slug", "title", "categoryId", "content", "excerpt", "metaDescription", "faqs", "tags", "productIds", "author")
        for field in fields:
            b = bundle()
            b["article"].pop(field)
            with self.subTest(field=field), self.assertRaises(ModelError):
                Models(ENV, Fake(writer_response(b))).draft({}, context())
        for changes in ({"excerpt": "short"}, {"metaDescription": "short"}, {"metaDescription": "x" * 161},
                        {"faqs": []}, {"faqs": [{"question": "q", "answer": ""}] * 3},
                        {"tags": "tent"}, {"author": "other"}, {"content": "x" * 2999}):
            b = bundle()
            b["article"].update(changes)
            with self.subTest(changes=list(changes)), self.assertRaises(ModelError):
                Models(ENV, Fake(writer_response(b))).draft({}, context())

    def test_draft_format_length_links_and_comparison_requirements(self):
        for format_name, lower, upper in (("ranking", 5000, 8000), ("comparison", 5000, 8000),
                                           ("guide", 3000, 5000), ("how-to", 3000, 5000), ("review", 2000, 3500)):
            for size, success in ((lower - 1, False), (lower, True), (upper, True), (upper + 1, False)):
                b = bundle()
                b["brief"]["format"] = format_name
                prefix = "## Choice\n[設営](/articles/setup) [撤収](/articles/pack)\n{{comparison:tent-a}}\n"
                b["article"]["content"] = prefix + "文" * (size - len(prefix))
                with self.subTest(format=format_name, size=size):
                    model = Models(ENV, Fake(writer_response(b), writer_response(b)))
                    if success:
                        self.assertEqual(model.draft({}, context())["article"]["content"], b["article"]["content"])
                    else:
                        with self.assertRaises(ModelError):
                            model.draft({}, context())
        for content in ("## Choice\n" + "文" * 4000,
                        "## Choice\n[a](/articles/a) [a](/articles/a)\n" + "文" * 4000):
            b = bundle()
            b["article"]["content"] = content
            with self.assertRaises(ModelError):
                Models(ENV, Fake(writer_response(b))).draft({}, context())
        b = bundle()
        b["brief"]["format"] = "ranking"
        b["article"]["content"] += "文" * 2000
        with self.assertRaises(ModelError):
            Models(ENV, Fake(writer_response(b))).draft({}, context())

    def test_main_can_replace_images_with_verified_evidence(self):
        ctx = context()
        ctx["images"][0].update(verified=True, sha256="observed", checkedAt="2026-11-03T12:00:00+09:00")
        b = Models(ENV, Fake(writer_response(bundle()))).draft({}, ctx)
        self.assertEqual(b["images"], ctx["images"])

    def test_usage_record_survives_rejected_completion(self):
        fake = Fake(response(None, raw="Not JSON"))
        model = Models(ENV, fake)
        with self.assertRaises(ModelError):
            model.research(context())
        self.assertEqual(model.usage[0]["responseId"], "c-1")
        self.assertEqual(model.usage[0]["input"], 31)

    def test_artifact_sink_captures_invalid_json_before_strict_parse_with_usage(self):
        artifacts = []
        model = Models(ENV, Fake(response(None, raw='not JSON')), artifact_sink=artifacts.append)
        with self.assertRaisesRegex(ModelError, 'Invalid JSON response'):
            model.research(context())
        self.assertEqual(artifacts, [{'responseId': 'c-1', 'model': 'claude-sonnet-4-6',
                                      'content': 'not JSON', 'usage': {'input_tokens': 31, 'output_tokens': 9}}])
        self.assertEqual(model.usage[0]['responseId'], artifacts[0]['responseId'])
        self.assertEqual(model.usage[0]['output'], 9)
        artifacts.clear()
        self.assertEqual(Models(ENV, Fake(response(THEMES)), artifact_sink=artifacts.append).research(context()), THEMES)
        self.assertEqual(artifacts[0]['usage'], {'input_tokens': 31, 'output_tokens': 9})

    def test_artifact_sink_blocks_secret_reflection_and_fails_closed(self):
        artifacts = []
        model = Models(ENV, Fake(response(None, raw='{"leak":"test-claude-key"}')),
                       artifact_sink=artifacts.append)
        with self.assertRaisesRegex(ModelError, 'Sensitive data blocked'):
            model.research(context())
        self.assertEqual(artifacts, [])
        def broken(_):
            raise RuntimeError('SECRET test-claude-key')
        model = Models(ENV, Fake(response(None, raw='not JSON')), artifact_sink=broken)
        with self.assertRaisesRegex(ModelError, '^Model artifact sink failed$') as caught:
            model.research(context())
        self.assertIsNone(caught.exception.__cause__)

    def test_runtime_binds_private_atomic_model_artifact_sink(self):
        from runtime import Runtime
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = root / 'env'
            env.write_text('ANTHROPIC_API_KEY=test-claude-key\n')
            runtime = Runtime({'stateRoot': str(root / 'state'), 'envFile': str(env),
                               'slack': {'user_id': 'U'}}, catalog=object(), slack=object())
            runtime.models.request = Fake(response(None, raw='not JSON'))
            with self.assertRaisesRegex(ModelError, 'Invalid JSON response'):
                runtime._measured_model_call('artifact-test', 'research', 'claude-sonnet-4-6',
                                             lambda: runtime.models.research(context()))
            name = hashlib.sha256(b'c-1').hexdigest() + '.json'
            artifact = root / 'state' / 'model-artifacts' / name
            self.assertTrue(artifact.exists())
            self.assertEqual(artifact.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(artifact.read_text())['content'], 'not JSON')

    def test_malformed_bundle_rejected_with_safe_model_error(self):
        for patcher in (lambda b: b["article"].update(productIds=[{}]),):
            b = bundle()
            patcher(b)
            with self.assertRaises(ModelError):
                Models(ENV, Fake(writer_response(b))).draft({}, context())
        for change in ({'catalog': [None]}, {'images': [{'productId': 'tent-a', 'url': 'https://invented.example/a.jpg'}]}):
            ctx = context()
            ctx.update(change)
            with self.subTest(fields=list(change)), self.assertRaises(ModelError):
                Models(ENV, Fake(writer_response(bundle()))).draft({}, ctx)

    def test_offline_failure_cannot_be_overridden_by_model_or_flags(self):
        for checks in (dict(FLAGS, passed=False), dict(FLAGS, failures=["bad structure"]),
                       {"passed": False, "evidence": FLAGS}):
            self.assertFalse(Models(ENV, Fake(response(REVIEW))).review(bundle(), checks)["passed"])

    def test_draft_cannot_invent_image_verification(self):
        b = bundle()
        b["images"][0]["verified"] = True
        with self.assertRaises(ModelError):
            Models(ENV, Fake(response(b))).draft({}, context())

    def test_retry_budget_is_shared_across_fallback(self):
        fake = Fake(http(429), http(404), http(503), http(429), writer_response(bundle()))
        with patch("models.time.sleep"), self.assertRaises(ModelError):
            Models(ENV, fake).draft({}, context())
        self.assertEqual(len(fake.calls), 4)

    def test_default_urllib_transport_has_same_request_contract(self):
        class LocalResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self):
                return json.dumps(response(THEMES)).encode()
        with patch("models.urlopen", return_value=LocalResponse()) as opener:
            result = Models(ENV).research(context())
        self.assertEqual(result, THEMES)
        request = opener.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("X-api-key"), "test-claude-key")
        self.assertEqual(json.loads(request.data)["model"], "claude-sonnet-4-6")
        self.assertLessEqual(opener.call_args.kwargs["timeout"], 180)

    def test_keys_from_explicit_mapping_only(self):
        fake = Fake()
        with patch.dict("os.environ", ENV), self.assertRaises(ModelError):
            Models({}, fake).research({})
        self.assertEqual(fake.calls, [])



class PurchaseAnchorModelTests(unittest.TestCase):
    def test_raw_or_changed_purchase_anchors_fail_before_polish_or_length_repair(self):
        from test_quality import bundle as qa_bundle
        canonical = qa_bundle()['products'][0]
        bad = ['https://item.rakuten.co.jp/alice00/00brd5003/',
               'https://hb.afl.rakuten.co.jp/ichiba/other-product/',
               canonical['amazonUrl'].replace('camp78-22', 'wrong-22'),
               canonical['amazonUrl'].replace('B012345678', 'B999999999'),
               'www.amazon.co.jp/dp/B012345678/?tag=camp78-22']
        for destination in bad:
            data = bundle()
            # Even a short body must fail this gate before the bounded length repair.
            data['article']['content'] = '広告\n' + destination + '\n<' + destination + '>'
            ctx = context()
            ctx['catalog'][0].update(affiliateUrl=canonical['affiliateUrl'], amazonUrl=canonical['amazonUrl'])
            request = Fake(writer_response(data))
            with self.subTest(destination=destination), self.assertRaisesRegex(ModelError, 'Purchase anchor'):
                Models(ENV, request).draft({'productIds': ['tent-a']}, ctx)
            self.assertEqual(1, len(request.calls))

    def test_exact_routes_and_manufacturer_citation_survive_normal_writer_validation(self):
        from test_quality import bundle as qa_bundle
        canonical = qa_bundle()['products'][0]
        data = bundle()
        data['article']['content'] += ('\n[楽天](' + canonical['affiliateUrl'] + ')'
            + '\n[Amazon](' + canonical['amazonUrl'] + ')\n[公式](https://maker.example/tent)')
        ctx = context()
        ctx['catalog'][0].update(affiliateUrl=canonical['affiliateUrl'], amazonUrl=canonical['amazonUrl'])
        request = Fake(writer_response(data))
        result = Models(ENV, request).draft({'productIds': ['tent-a']}, ctx)
        self.assertEqual(data['article']['content'], result['article']['content'])
        self.assertEqual(1, len(request.calls))
        self.assertIn('Raw merchant reference URLs are evidence only', request.calls[0][2]['messages'][0]['content'])

if __name__ == "__main__":
    unittest.main()
