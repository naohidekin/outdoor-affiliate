"""Offline catalog correction integration; synthetic products and no live providers."""
import copy
import json
import unittest
from unittest.mock import Mock, patch

from ledger import fingerprint
from test_quality import bundle
from test_revision_workflow import baseline, spec
import test_runtime


class CatalogCorrectionRuntimeTests(unittest.TestCase):
    setUp = test_runtime.RuntimeTests.setUp
    tearDown = test_runtime.RuntimeTests.tearDown

    def raw(self):
        products = spec(baseline())['baseProducts']
        after = copy.deepcopy(products)
        after[0].update(name='確認済み商品', updatedAt='2026-11-08T12:00:00+09:00')
        return dict(baseProducts=products, candidateProducts=after, changeSummary='商品名の訂正')

    def candidate(self):
        return self.runtime.ledger.create_candidate(dict(slug='corrected-tent', title='テントおすすめ1選',
            categoryId='tent', productIds=['tent-a']))

    def attach(self):
        job = self.candidate()
        return self.runtime.ledger.attach_catalog_correction(job['id'], self.raw())

    def context(self):
        products = self.raw()['baseProducts']
        return dict(products=products, catalog=copy.deepcopy(products), articles=[], editorialRules='rules')

    def produce(self):
        job = self.attach()
        after = self.raw()['candidateProducts']
        def draft(theme, gathered):
            result = bundle()
            result['products'] = copy.deepcopy(after)
            result['images'][0].update(sha256='a' * 64, size=10)
            result['brief']['externalSafe'] = True
            return result
        self.models.draft = Mock(side_effect=draft)
        self.models.review = Mock(wraps=self.models.review)
        self.runtime.catalog.gather = Mock(wraps=self.runtime.catalog.gather)
        self.runtime._make_article(job, self.context())
        return self.runtime.ledger.get_job(job['id'])

    def qa(self, job):
        return dict(passed=True, issues=[], reviewedBy='Astra', evidence={'independent': True},
                    fingerprint=job['revision'])

    def approve(self, job):
        self.runtime.ledger.record_astra_review(job['id'], job['revision'], self.qa(job))
        self.runtime.deliver(job['id'])
        req = self.slack.deliveries[-1][1]
        event = dict(req['payload'], **self.scope, event_id='approve-correction',
                     action_id='camp_review_approve', card_ts='1793000000.123456')
        return self.runtime.ledger.decide(event, self.scope)

    def test_attachment_same_id_week_and_cap_no_authority(self):
        old = self.candidate()
        self.runtime.ledger.set_stage(old['id'], 'error', {'reason': 'bad product'})
        job = self.runtime.ledger.attach_catalog_correction(old['id'], self.raw())
        self.assertEqual((old['id'], old['week']), (job['id'], job['week']))
        self.assertEqual('candidate', job['stage'])
        self.assertIsNone(job['error'])
        self.assertIsNone(job['approval'])
        for i in range(2):
            self.runtime.ledger.create_candidate({'slug': 'other-' + str(i)})
        with self.assertRaisesRegex(ValueError, 'cap'):
            self.runtime.ledger.create_candidate({'slug': 'fourth'})
        self.assertEqual(3, len(self.runtime.ledger.list_jobs()))
        with self.runtime.ledger._tx() as db:
            self.assertEqual(1, db.execute("SELECT count(*) FROM events WHERE kind='catalog_correction_attached'").fetchone()[0])

    def test_wrong_theme_extra_raw_fields_and_effects_rejected(self):
        job = self.candidate()
        raw = self.raw()
        raw['approval'] = {'action': 'approved'}
        with self.assertRaises(ValueError):
            self.runtime.ledger.attach_catalog_correction(job['id'], raw)
        with self.runtime.ledger._tx() as db:
            altered = self.runtime.ledger._get(db, job['id'])
            altered['theme']['productIds'] = ['other']
            self.runtime.ledger._put(db, altered, 'test')
        with self.assertRaises(ValueError):
            self.runtime.ledger.attach_catalog_correction(job['id'], self.raw())
        with self.runtime.ledger._tx() as db:
            altered['theme']['productIds'] = ['tent-a']
            self.runtime.ledger._put(db, altered, 'test')
            db.execute('INSERT INTO effects VALUES (?,?,?,?)', (job['id'], 'stage', 'failed', '{}'))
        with self.assertRaises(ValueError):
            self.runtime.ledger.attach_catalog_correction(job['id'], self.raw())

    def test_no_public_stage_before_owner_and_private_baseline_not_model_input(self):
        job = self.produce()
        self.assertEqual([], self.writes)
        self.assertEqual([], self.slack.deliveries)
        self.assertEqual('review', job['stage'])
        self.assertIsNone(job['approval'])
        self.assertNotIn('catalogCorrectionContext', self.models.review.call_args.args[0])
        gathered_context = self.runtime.catalog.gather.call_args.args[1]
        self.assertEqual(self.raw()['candidateProducts'], gathered_context['products'])
        self.assertEqual(gathered_context['products'], gathered_context['catalog'])
        self.assertEqual(self.raw()['baseProducts'], self.context()['products'])
        source_files = list((self.runtime.root / 'research' / 'artifacts' / job['id']).glob('*/source.json'))
        self.assertEqual(job['catalogCorrectionContext'], json.loads(source_files[0].read_text())['bundle']['catalogCorrectionContext'])
        self.assertEqual(fingerprint(job['bundle']), job['revision'])

    def test_live_baseline_change_blocks_before_model_or_gather(self):
        job = self.attach()
        context = self.context()
        context['products'][0]['name'] = '競合変更'
        self.models.draft = Mock(side_effect=AssertionError('model must not run'))
        self.runtime.catalog.gather = Mock(side_effect=AssertionError('gather must not run'))
        with self.assertRaises(ValueError):
            self.runtime._make_article(job, context)
        self.models.draft.assert_not_called()
        self.runtime.catalog.gather.assert_not_called()
        self.assertEqual([], self.writes)

    def test_context_omission_injection_and_mutation_fail_closed(self):
        job = self.produce()
        dropped = copy.deepcopy(job['bundle'])
        del dropped['catalogCorrectionContext']
        with self.assertRaises(ValueError):
            self.runtime.ledger.save_bundle(job['id'], dropped)
        injected_job = self.runtime.ledger.create_candidate({'slug': 'injected'})
        with self.assertRaises(ValueError):
            self.runtime.ledger.save_bundle(injected_job['id'], job['bundle'])
        for target in ('job', 'bundle'):
            bad = copy.deepcopy(job)
            obj = bad if target == 'job' else bad['bundle']
            obj['catalogCorrectionContext']['changeSummary'] += '変更'
            bad['revision'] = fingerprint(bad['bundle'])
            with self.assertRaises(ValueError):
                self.runtime.ledger._current(bad)

    def test_astra_qa_required_delivery_and_request_and_no_approval_authority(self):
        job = self.produce()
        self.assertEqual('awaiting_astra_review', self.runtime.deliver(job['id'])['status'])
        with self.assertRaisesRegex(ValueError, 'Astra'):
            self.runtime.ledger.create_request(job['id'])
        bad = self.qa(job)
        bad['fingerprint'] = 'stale'
        with self.assertRaises(ValueError):
            self.runtime.ledger.record_astra_review(job['id'], job['revision'], bad)
        current = self.runtime.ledger.record_astra_review(job['id'], job['revision'], self.qa(job))
        self.assertIsNone(current['approval'])
        self.assertEqual('review', current['stage'])
        self.assertEqual('delivered', self.runtime.deliver(job['id'])['status'])

    def test_owner_approval_covers_context_and_stale_edits_invalidate(self):
        job = self.produce()
        approved = self.approve(job)
        self.assertEqual(fingerprint(approved['bundle']), approved['approval']['revision'])
        changed = copy.deepcopy(job['bundle'])
        changed['article']['content'] += '\n追記'
        saved = self.runtime.ledger.save_bundle(job['id'], changed, expected_revision=job['revision'])
        self.assertIsNone(saved['approval'])
        self.assertIsNone(saved['astraReview'])
        self.assertIsNone(saved['review'])
        with self.runtime.ledger._tx() as db:
            statuses = [json.loads(r[0])['status'] for r in db.execute('SELECT data FROM requests WHERE job_id=?', (job['id'],))]
        self.assertEqual(['invalidated'], statuses)
        with self.assertRaises(ValueError):
            self.runtime.ledger.attach_catalog_correction(job['id'], self.raw())

    def test_approved_tick_dispatches_publish_corrected_once(self):
        self.config['catalogCorrectionsPublicationEnabled'] = True
        job = self.produce()
        self.approve(job)
        self.config['generationEnabled'] = False
        self.runtime.make_social = Mock()
        self.runtime._post_publication_audits = Mock(return_value=[])
        self.runtime.tick()
        self.assertEqual(['publish-corrected'], [a for a, _ in self.writes])
        with self.assertRaises(ValueError):
            self.runtime.ledger.record_astra_review(job['id'], job['revision'], self.qa(job))

    def test_corrected_publication_disabled_by_default_waits_without_claiming_effect(self):
        job = self.produce()
        self.approve(job)
        self.config['generationEnabled'] = False
        self.runtime._post_publication_audits = Mock(return_value=[])
        for value in (None, False, 1, 'true'):
            with self.subTest(value=value):
                if value is None:
                    self.config.pop('catalogCorrectionsPublicationEnabled', None)
                else:
                    self.config['catalogCorrectionsPublicationEnabled'] = value
                result = self.runtime.tick()
                self.assertIn(dict(id=job['id'], status='waiting_auth',
                                   reason='catalog_corrections_publication_disabled'), result['results'])
                self.assertEqual('approved', self.runtime.ledger.get_job(job['id'])['stage'])
                self.assertEqual([], self.writes)
                with self.runtime.ledger._tx() as db:
                    self.assertIsNone(db.execute('SELECT status FROM effects WHERE job_id=?', (job['id'],)).fetchone())
        self.config['catalogCorrectionsPublicationEnabled'] = True
        self.runtime.tick()
        self.assertEqual(['publish-corrected'], [action for action, _ in self.writes])

    def test_cli_attachment_reads_raw_json_only_and_does_not_produce(self):
        from runtime import main
        config_path = self.runtime.root / 'test-config.json'
        config_path.write_text(json.dumps(self.config))
        raw_path = self.runtime.root / 'test-correction.json'
        raw_path.write_text(json.dumps(self.raw()))
        job = self.candidate()
        self.runtime.produce = Mock(side_effect=AssertionError('attachment must not produce'))
        with patch('runtime.Runtime', return_value=self.runtime), patch('runtime.atexit.register'), \
                patch('sys.argv', ['runtime.py', '--config', str(config_path), 'attach-catalog-correction',
                                   '--id', job['id'], '--evidence-file', str(raw_path)]), patch('builtins.print'):
            main()
        saved = self.runtime.ledger.get_job(job['id'])
        self.assertEqual(self.raw()['candidateProducts'], saved['catalogCorrectionContext']['candidateProducts'])
        self.assertIsNone(saved['bundle'])
        self.runtime.produce.assert_not_called()
        self.assertEqual([], self.writes)

    def test_normal_new_article_cannot_receive_astra_qa(self):
        job = self.candidate()
        b = bundle()
        saved = self.runtime.ledger.save_bundle(job['id'], b)
        review = dict(passed=True, score=8.5, fingerprint=saved['revision'],
                      evidence={k: True for k in ('facts', 'images', 'affiliate', 'medical', 'render')},
                      polish={'model': 'gemini-3.8-flash', 'validated': True})
        self.runtime.ledger.record_review(job['id'], saved['revision'], review)
        with self.assertRaises(ValueError):
            self.runtime.ledger.record_astra_review(job['id'], saved['revision'], self.qa(saved))

    def corrected_theme(self, job):
        return dict(job['theme'], title='CB缶対応バーナーの仕様比較', query='CB缶 バーナー 仕様',
                    selectionReason='未確認のM8249対応表現を除き確認済み仕様を比較する')

    def test_theme_correction_preserves_identity_cap_context_and_event(self):
        job = self.attach()
        for i in range(2):
            self.runtime.ledger.create_candidate({'slug': 'cap-' + str(i)})
        self.runtime.ledger.set_stage(job['id'], 'error', {'reason': 'unsupported theme'})
        fixed = self.runtime.ledger.correct_candidate_theme(job['id'], self.corrected_theme(job))
        self.assertEqual((job['id'], job['week']), (fixed['id'], fixed['week']))
        self.assertEqual(job['catalogCorrectionContext'], fixed['catalogCorrectionContext'])
        self.assertEqual('candidate', fixed['stage'])
        self.assertIsNone(fixed['error'])
        self.assertIsNone(fixed['approval'])
        self.assertEqual(3, len(self.runtime.ledger.list_jobs()))
        with self.assertRaisesRegex(ValueError, 'cap'):
            self.runtime.ledger.create_candidate({'slug': 'fourth'})
        with self.runtime.ledger._tx() as db:
            recorded = json.loads(db.execute("SELECT data FROM events WHERE job_id=? AND kind='candidate_theme_corrected'",
                                           (job['id'],)).fetchone()[0])
        self.assertEqual(fixed['theme'], recorded['theme'])

    def test_theme_correction_rejects_all_noneditable_fields_and_missing_identity(self):
        job = self.attach()
        for field, value in (('slug', 'different'), ('categoryId', 'other'), ('productIds', ['other']),
                             ('approval', {'action': 'approved'}), ('week', 'different'),
                             ('catalogCorrectionContext', {})):
            with self.subTest(field=field):
                theme = self.corrected_theme(job)
                theme[field] = value
                with self.assertRaises(ValueError):
                    self.runtime.ledger.correct_candidate_theme(job['id'], theme)
        for field in ('slug', 'categoryId', 'productIds', 'title', 'query', 'selectionReason'):
            with self.subTest(missing=field):
                theme = self.corrected_theme(job)
                del theme[field]
                with self.assertRaises(ValueError):
                    self.runtime.ledger.correct_candidate_theme(job['id'], theme)
        self.assertEqual(job, self.runtime.ledger.get_job(job['id']))

    def test_theme_correction_rejects_staged_revision_and_effect_claims(self):
        job = self.produce()
        with self.assertRaises(ValueError):
            self.runtime.ledger.correct_candidate_theme(job['id'], self.corrected_theme(job))
        revision = self.runtime.ledger.request_revision(spec(baseline()))
        with self.assertRaises(ValueError):
            self.runtime.ledger.correct_candidate_theme(revision['id'], self.corrected_theme(revision))
        candidate = self.runtime.ledger.create_candidate(dict(job['theme'], slug='effect-candidate'))
        with self.runtime.ledger._tx() as db:
            db.execute('INSERT INTO effects VALUES (?,?,?,?)', (candidate['id'], 'stage', 'failed', '{}'))
        with self.assertRaises(ValueError):
            self.runtime.ledger.correct_candidate_theme(candidate['id'], self.corrected_theme(candidate))

    def test_theme_correction_cli_uses_plain_theme_without_producing(self):
        from runtime import main
        job = self.attach()
        config_path = self.runtime.root / 'test-config.json'
        config_path.write_text(json.dumps(self.config))
        theme_path = self.runtime.root / 'test-theme.json'
        theme_path.write_text(json.dumps(self.corrected_theme(job)))
        self.runtime.produce = Mock(side_effect=AssertionError('no production'))
        with patch('runtime.Runtime', return_value=self.runtime), patch('runtime.atexit.register'), \
                patch('sys.argv', ['runtime.py', '--config', str(config_path), 'correct-candidate-theme',
                                   '--id', job['id'], '--evidence-file', str(theme_path)]), patch('builtins.print'):
            main()
        self.assertEqual(self.corrected_theme(job), self.runtime.ledger.get_job(job['id'])['theme'])
        self.runtime.produce.assert_not_called()
        self.assertEqual([], self.writes)

    def test_social_models_receive_only_candidate_products_not_private_baselines(self):
        job = self.produce()
        self.approve(job)
        job = self.runtime.ledger.record_publication(job['id'], job['revision'],
            dict(verified=True, url='https://camp-gear-lab.com/articles/' + job['theme']['slug'],
                 readback={'verified': True, 'fingerprint': job['revision']}))
        before = copy.deepcopy(job)
        self.models.social = Mock(wraps=self.models.social)
        self.runtime.make_social(job)
        social_input = self.models.social.call_args.args[0]
        review_input = self.models.review.call_args.args[0]
        for source in (social_input, review_input['source']):
            self.assertNotIn('catalogCorrectionContext', source)
            self.assertNotIn('baseProducts', json.dumps(source))
            self.assertEqual(self.raw()['candidateProducts'], source['products'])
        self.assertEqual(before, job)
        saved = self.runtime.ledger.get_job(job['id'])
        self.assertEqual(before['bundle'], saved['bundle'])
        self.assertEqual(before['revision'], fingerprint(saved['bundle']))
        self.assertEqual(before['catalogCorrectionContext'], saved['catalogCorrectionContext'])

    def test_social_refresh_review_omits_private_baselines_preserving_published_bundle(self):
        job = self.produce()
        self.approve(job)
        job = self.runtime.ledger.record_publication(job['id'], job['revision'],
            dict(verified=True, url='https://camp-gear-lab.com/articles/' + job['theme']['slug'],
                 readback={'verified': True, 'fingerprint': job['revision']}))
        self.runtime.make_social(job)
        job = self.runtime.ledger.get_job(job['id'])
        image = job['bundle']['images'][0]
        title = job['bundle']['article']['title']
        manifest = dict(url='https://images.example.com/card.png', finalUrl='https://images.example.com/card.png',
                        sha256='b' * 64, size=10, contentType='image/png', width=1200, height=630,
                        templateVersion='lake-sky-social-card-v2',
                        sources=[dict(productId='tent-a', sha256=image['sha256'])],
                        rendererEvidence=dict(contentHash='c' * 64, renderEngine='test', fontFamily='test', layout={},
                            displayText=dict(title=title, heading=title, productNames=['確認済み商品']),
                            sourceCrops=[dict(productId='tent-a', sha256=image['sha256'])]))
        rendered = copy.deepcopy(job['bundle'])
        rendered['article']['generationMeta'] = {'socialCard': manifest}
        rendered['images'].append(dict(manifest, role='social-card', verified=True))
        self.models.review = Mock(return_value=dict(passed=True, score=8.5, model='claude-test'))
        with patch('social_publisher.SocialPublisher._image_bytes', return_value=b'offline'):
            saved = self.runtime.refresh_social_images(job['id'], rendered,
                        expected_social_revision=job['social']['revision'])
        source = self.models.review.call_args.args[0]['source']
        self.assertNotIn('catalogCorrectionContext', source)
        self.assertNotIn('baseProducts', json.dumps(source))
        self.assertEqual(self.raw()['candidateProducts'], source['products'])
        self.assertEqual(job['bundle'], saved['bundle'])
        self.assertEqual(job['revision'], saved['revision'])

    def test_corrected_publisher_bridge_uses_trusted_ledger_env_and_full_bundle(self):
        job = self.produce()
        job = self.approve(job)
        self.config['seoGuardConfig'] = '/synthetic/guard.json'
        self.runtime.env.update(CAMP_EDITORIAL_STATE_ROOT='/wrong/state', CAMP_EDITORIAL_OWNER_ID='wrong')
        response = Mock(returncode=0, stdout=json.dumps({'verified': True}))
        with patch('runtime.subprocess.run', return_value=response) as run:
            self.runtime._publish('publish-corrected', job)
        sent = run.call_args.kwargs
        self.assertEqual(str(self.runtime.root), sent['env']['CAMP_EDITORIAL_STATE_ROOT'])
        self.assertEqual(self.runtime.ledger.owner_id, sent['env']['CAMP_EDITORIAL_OWNER_ID'])
        request = json.loads(sent['input'])
        self.assertEqual(job['bundle'], request['bundle'])
        self.assertEqual(job['revision'], request['revision'])
        self.assertEqual(job['catalogCorrectionContext'], request['bundle']['catalogCorrectionContext'])

    def test_three_corrected_productions_report_astra_wait_without_cards_or_public_stage(self):
        jobs = []
        for i in range(3):
            job = self.runtime.ledger.create_candidate(dict(slug='private-correction-' + str(i),
                title='テントおすすめ1選', categoryId='tent', productIds=['tent-a']))
            jobs.append(self.runtime.ledger.attach_catalog_correction(job['id'], self.raw()))
        def draft(theme, gathered):
            result = bundle()
            result['products'] = copy.deepcopy(self.raw()['candidateProducts'])
            result['brief']['externalSafe'] = True
            return result
        self.models.draft = Mock(side_effect=draft)
        self.models.research = Mock(side_effect=AssertionError('no new themes'))
        self.runtime._context = Mock(return_value=self.context())
        result = self.runtime.produce(limit=3)
        self.assertEqual([dict(id=j['id'], status='awaiting_astra_review') for j in jobs], result['articles'])
        self.assertEqual([], self.slack.deliveries)
        self.assertEqual([], self.writes)
        for job in self.runtime.ledger.list_jobs():
            self.assertEqual('review', job['stage'])
            self.assertIsNone(job.get('astraReview'))
            self.assertIsNone(job['approval'])
        with self.runtime.ledger._tx() as db:
            self.assertEqual(0, db.execute('SELECT count(*) FROM requests').fetchone()[0])
        from reporting import editorial_report
        report = editorial_report(self.runtime.ledger.list_jobs())
        self.assertIn('Astra品質確認待ち（承認カード未送信）: 3件', report)
        self.assertIn('記事の確認待ち（繰越含む）: 0件', report)
        self.assertNotIn('：内容確認待ち', report)

    def test_existing_producer_resumes_same_corrected_candidate(self):
        job = self.attach()
        self.runtime._context = Mock(return_value=self.context())
        self.runtime._make_article = Mock()
        self.models.research = Mock(side_effect=AssertionError('no new research'))
        result = self.runtime.produce(limit=1)
        self.assertEqual(job['id'], result['articles'][0]['id'])
        self.assertEqual(job['id'], self.runtime._make_article.call_args.args[0]['id'])
        self.assertEqual(1, len(self.runtime.ledger.list_jobs()))


if __name__ == '__main__':
    unittest.main()
