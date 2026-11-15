"""Single-host, Slack-first production runner. No Telegram fallback."""
import argparse
import atexit
import copy
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import sys
import time
from urllib.parse import urlsplit

from ledger import (Ledger, canonical, fingerprint, valid_review, valid_astra_review, valid_social_mode,
                    valid_social_images, valid_image_refresh, REFRESH_NOTICE)
from models import Models
from wise_contract import load_policy, require_current_review
from quality import inspect_bundle, inspect_polish
from slack import Slack
from attention_presentation import attention_text
from dispatcher import (DeterministicDispatcher, buffer_social_eligible,
                        buffer_social_outstanding, buffer_social_start,
                        execution_policy, social_feature_enabled)
from stage_journal import StageBlocked, StageJournal, StageUnknown
from model_budget import ModelBudget
from daily_metrics import collect_daily_metrics, require_fresh_daily_metrics

JST = timezone(timedelta(hours=9))


def stamp():
    return datetime.now(JST).isoformat()


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + secrets.token_hex(8))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        json.dump(value, out, ensure_ascii=False, allow_nan=False)
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def env_file(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        match = re.match(r'^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$', line)
        if match:
            key, value = match.groups()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '\"\'':
                value = value[1:-1]
            result[key] = value
    return result


def reason(error):
    text = str(error)
    return text if re.fullmatch(r'[A-Za-z0-9_ .:/-]{1,180}', text) else type(error).__name__


def safe_publication_diagnostic(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    phases = {'input_environment', 'dependency_setup', 'execution', 'product_updates', 'article_update',
              'article_readback', 'cache_revalidation', 'public_readback', 'image_readback', 'subprocess'}
    operations = {'db_read_articles', 'db_read_products', 'db_patch_articles', 'db_patch_products'}
    if isinstance(value.get('phase'), str) and value.get('phase') in phases:
        result['phase'] = value['phase']
    if isinstance(value.get('operation'), str) and value.get('operation') in operations:
        result['operation'] = value['operation']
    if type(value.get('httpStatus')) is int and 100 <= value['httpStatus'] <= 599:
        result['httpStatus'] = value['httpStatus']
    if isinstance(value.get('dbCode'), str) and re.fullmatch(r'[A-Z0-9]{5}', value['dbCode']):
        result['dbCode'] = value['dbCode']
    if type(value.get('exitCode')) is int and -128 <= value['exitCode'] <= 255:
        result['exitCode'] = value['exitCode']
    if value.get('timedOut') is True:
        result['timedOut'] = True
    return result


class Runtime:
    def __init__(self, config, models=None, catalog=None, slack=None, renderer=None, publisher=None,
                 analytics=None, reporter=None, social_publisher=None, buffer_publisher=None,
                 social_cards=None, post_auditor=None):
        self.execution_policy = execution_policy(config)
        for feature in ('socialGenerationEnabled', 'socialReviewEnabled'):
            social_feature_enabled(config, feature)
        buffer_social_start(config)
        self.config = config
        self.root = Path(config['stateRoot'])
        if 'productionSchedule' in config and config['productionSchedule'] is None:
            raise ValueError('invalid productionSchedule')
        self.ledger = Ledger(self.root, config['slack']['user_id'],
                             production_schedule=config.get('productionSchedule'),
                             target_account_id=config.get('targetAccountId'))
        self.stage_journal = StageJournal(self.ledger)
        self._usage_response_ids = set()
        self._saved_usage_response_ids = set()
        self.env = env_file(config['envFile'])
        # Explicit dedicated Gemini settings; keys remain in memory, never copied.
        if config.get('geminiEnvFile'):
            gemini = env_file(config['geminiEnvFile'])
            if gemini.get('GEMINI_API_KEY'):
                self.env['GEMINI_API_KEY'] = gemini['GEMINI_API_KEY']
        def save_model_artifact(artifact):
            name = hashlib.sha256(artifact['responseId'].encode('utf-8')).hexdigest() + '.json'
            atomic(self.root / 'model-artifacts' / name, artifact)
        self.model_budget = ModelBudget(self.root, self.ledger.production_schedule,
                                        config.get('modelBudget'))
        self.models = models or Models(self.env, artifact_sink=save_model_artifact,
                                       budget=self.model_budget)
        if isinstance(self.models, Models):
            self.models.budget = self.model_budget
        if catalog is None:
            from catalog import Catalog
            catalog = Catalog(self.env, source_hints=config.get('sourceHints', {}),
                              source_notices=config.get('sourceNotices', {}))
        self.catalog = catalog
        self.slack = slack or Slack(config)
        self.renderer = renderer or self._render
        self.publisher = publisher or self._publish
        self.social_cards = social_cards
        self.social_publisher = social_publisher
        self.buffer_publisher = buffer_publisher
        self.post_auditor = post_auditor
        from analytics import Analytics
        from reporting import Reporter
        self.analytics = analytics or Analytics(config)
        self.reporter = reporter or Reporter(config, self.slack, env=self.env)

    def _require_running(self):
        self.execution_policy = execution_policy(self.config)
        if self.execution_policy is not None and self.execution_policy.suspended:
            raise ValueError('execution_suspended')

    def _analytics_context(self):
        self._require_running()
        context = self.analytics.load_context()
        if self.config.get('seoStateRoot'):
            # Export a separate, bounded input for Astra. Never replace the SEO
            # backlog, experiment queue or canonical metrics snapshot.
            options = [p for p in context.get('opportunities', []) if p.get('action') == 'improve_existing'][:3] if context.get('status') == 'ok' else []
            queue = {'schemaVersion': 1, 'status': context.get('status'), 'collectedAt': context.get('collectedAt'),
                     'evidence': context.get('evidence'), 'provenance': context.get('provenance'),
                     'opportunities': options, 'uncertainty': context.get('uncertainty', [])[:12],
                     'instructions': 'Improve these existing pages; do not create duplicate articles. '
                         'Seasonality and cannibalization need independent review; clicks are not purchases.'}
            if len(canonical(queue).encode()) > 65536:
                queue = {'schemaVersion': 1, 'status': 'unavailable', 'collectedAt': None,
                         'opportunities': [], 'uncertainty': ['Bounded improvement input exceeded size limit']}
            analytics_root = Path(self.config.get('analyticsRoot') or self.root / 'analytics')
            paths = [analytics_root / 'improvements' / 'latest.json',
                     Path(self.config['seoStateRoot']) / 'editorial-insights' / 'latest.json']
            for path in paths:
                try:
                    same = json.loads(path.read_text()) == queue
                except (OSError, ValueError):
                    same = False
                if not same:
                    atomic(path, queue)
        return context

    def _render(self, bundle, job):
        self._require_running()
        output = self.root / 'previews' / job['id'] / fingerprint(bundle)
        output.mkdir(mode=0o700, parents=True, exist_ok=True)
        result = subprocess.run([self.config.get('node', 'node'), str(Path(__file__).with_name('render-preview.mjs'))],
            input=json.dumps({'bundle': bundle, 'repo': self.config['repo'], 'outputDir': str(output)}),
            capture_output=True, text=True, timeout=300)
        try:
            value = json.loads(result.stdout.strip().splitlines()[-1])
            if not isinstance(value, dict):
                raise ValueError('render_result_object_required')
        except (ValueError, IndexError):
            atomic(output / 'result.json', {'passed': False, 'reason': 'render_preview_unavailable',
                                            'returncode': result.returncode})
            raise ValueError('render_preview_unavailable') from None
        atomic(output / 'result.json', value)
        if result.returncode or value.get('passed') is not True:
            raise ValueError('render_preview_failed')
        return value

    def _medical(self, article):
        self._require_running()
        module = (Path(self.config['repo']) / 'src/lib/medical-review-gate.mjs').as_uri()
        script = 'import {readFileSync} from "node:fs"; const m=await import(process.argv[1]); console.log(JSON.stringify(m.detectMedicalRisks(readFileSync(0,"utf8"))));'
        checked = subprocess.run([self.config.get('node', 'node'), '--input-type=module', '-e', script, module],
            input=article.get('title', '') + '\n' + article['content'] + '\n' + json.dumps(article.get('faqs', []), ensure_ascii=False),
            capture_output=True, text=True, timeout=20)
        if checked.returncode:
            raise ValueError('medical_gate_unavailable')
        risks = json.loads(checked.stdout)
        return {'passed': not risks, 'risks': risks}

    def _publish(self, action, job):
        self._require_running()
        require_current_review(job.get('bundle'), job.get('review'), self.config['repo'])
        child_env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'TZ', 'TMPDIR')}
        child_env.update(self.env)
        child_env['SEO_GUARD_CONFIG'] = self.config['seoGuardConfig']
        if action == 'publish-corrected':
            child_env['CAMP_EDITORIAL_STATE_ROOT'] = str(self.root)
            child_env['CAMP_EDITORIAL_OWNER_ID'] = self.config['slack']['user_id']
        command = [self.config.get('node', 'node'), str(Path(__file__).with_name('publish.mjs'))]
        approval = job.get('approval')
        bound_approval = None if not approval else {
            'revision': approval['revision'], 'approverId': approval['user_id'],
            'evidence': {'requestId': approval['request_id'], 'approvedAt': approval['at'],
                         'source': approval.get('source', 'authenticated-slack-receiver')}}
        request = {'action': action, 'bundle': job['bundle'], 'revision': job['revision'], 'approval': bound_approval,
                   'review': {key: job['review'].get(key) for key in
                              ('passed', 'wisePolicy', 'wiseScores', 'fingerprint')}}
        def failure(diagnostic):
            error = ValueError('publication_result_unknown')
            error.diagnostic = safe_publication_diagnostic(diagnostic)
            return error
        try:
            result = subprocess.run(command, input=json.dumps(request), env=child_env,
                                    capture_output=True, text=True, timeout=180, cwd=self.config['repo'])
        except subprocess.TimeoutExpired:
            raise failure({'phase': 'subprocess', 'timedOut': True}) from None
        try:
            value = json.loads(result.stdout.strip().splitlines()[-1])
            if not isinstance(value, dict):
                raise ValueError('invalid publisher result')
        except (ValueError, IndexError):
            raise failure({'phase': 'subprocess', 'exitCode': result.returncode}) from None
        if result.returncode or value.get('error'):
            raise failure({**safe_publication_diagnostic(value.get('diagnostic')),
                           'exitCode': result.returncode})
        return value

    def _wise_context(self, context):
        context = copy.deepcopy(context)
        policy = load_policy(self.config['repo'])
        context['wisePolicy'] = policy
        if policy['text'] not in context.get('editorialRules', ''):
            context['editorialRules'] = policy['text'] + '\n\n' + context.get('editorialRules', '')
        return context

    def _context(self):
        self._require_running()
        data = self.catalog.catalog()
        repo = Path(self.config['repo'])
        from revisions import TARGETS
        data['revisionArticles'] = [copy.deepcopy(a) for a in data.get('articles', []) if a.get('id') in TARGETS]
        data['articles'] = [{k: a.get(k) for k in ('id', 'slug', 'title', 'categoryId', 'productIds', 'status')}
                            for a in data.get('articles', [])]
        data['existingArticles'] = data['articles']
        data['catalog'] = data.get('products', [])
        data['queuedThemes'] = [j['theme'] for j in self.ledger.list_jobs()]
        policy = load_policy(repo)
        data['wisePolicy'] = policy
        data['editorialRules'] = policy['text'] + '\n\n' + '\n'.join((repo / p).read_text() for p in (
            'CLAUDE.md', 'SKILL.md', 'docs/writing-style.md', 'docs/author-gear.md'))
        data['instructions'] = ('Three distinct new articles, verified existing catalog products. '
            'Prioritize observed Rakuten opportunities, keep Amazon routes. Avoid medical, drugs, emergency '
            'and child safety advice; those require a separate physician evidence review. '
            'Every theme must include slug, title, categoryId, productIds, query and selectionReason.')
        return data

    def _research_context(self, context):
        from catalog import _model, MAKERS
        eligible = [p for p in context['products'] if _model(p) and p.get('brand', '').casefold() in MAKERS
                    and p.get('imageUrl') and p.get('affiliateUrl') and p.get('amazonUrl')]
        products = [{k: p.get(k) for k in ('id', 'name', 'brand', 'categoryId', 'specs')} for p in eligible[:60]]
        counts = {}
        observed_end = datetime.now(JST)
        observed_start = observed_end - timedelta(days=28)
        for click in context.get('clicks', []):
            try:
                at = datetime.fromisoformat(str(click.get('clickedAt', '')).replace('Z', '+00:00'))
                if at.tzinfo is None or not observed_start <= at <= observed_end:
                    continue
            except ValueError:
                continue
            key = (click.get('pagePath', click.get('page_path', '')), click.get('store', 'unknown'))
            counts[key] = counts.get(key, 0) + 1
        analytics = self._analytics_context()
        return {'wisePolicy': load_policy(self.config['repo']), 'catalog': products, 'existingArticles': context['articles'], 'queuedThemes': context['queuedThemes'],
                'merchantClicks': [{'article': k[0], 'store': k[1], 'clicks': n} for k, n in counts.items()],
                'observation': {'start': observed_start.isoformat(), 'end': observed_end.isoformat(),
                                'metric': 'affiliate link clicks only; not purchases, revenue or seasonal trend'},
                'analytics': analytics, 'season': datetime.now(JST).strftime('%Y-%m'),
                'instructions': context['instructions'] + ' Calendar month alone is not seasonal-demand evidence. '
                    'Analytics opportunities with action=improve_existing must improve the existing URL, '
                    'not become a new duplicate article. Missing signals remain unverified.'}

    def produce(self, limit=3):
        self._require_running()
        if not self.config.get('generationEnabled'):
            return {'status': 'disabled'}
        now = datetime.now(JST)
        week = self.ledger.production_schedule.period_key(now)
        if week is None:
            return {'status': 'idle', 'articles': []}
        current = [j for j in self.ledger.list_jobs() if j.get('kind') != 'article_revision' and j['week'] == week]
        pending = [j for j in self.ledger.list_jobs() if j.get('kind') != 'article_revision' and not j['publication'] and j['stage'] != 'rejected']
        if not any(j['stage'] == 'candidate' for j in pending) and (current or len(pending) >= 3):
            return {'status': 'idle', 'articles': []}
        new_research = not current and len(pending) < 3
        if new_research:
            try:
                require_fresh_daily_metrics(self.config, now)
            except ValueError:
                if not any(job.get('stage') == 'candidate' for job in pending):
                    raise
                new_research = False
        context = self._context()
        if new_research:
            research_attempt = self.root / 'production-attempts' / (week + '.json')
            if research_attempt.exists():
                raise ValueError('weekly_research_requires_reconciliation')
            atomic(research_attempt, {'status': 'in_flight', 'at': stamp()})
            try:
                themes = self._measured_model_call(
                    'research:' + week, 'research', 'claude-sonnet-4-6',
                    lambda: self.models.research(self._research_context(context)))['themes']
                atomic(research_attempt, {'status': 'generated', 'themes': themes, 'at': stamp()})
            finally:
                self._save_usage()
            for theme in themes[:3 - len(pending)]:
                self.ledger.create_candidate(theme, now=now)
            current = [j for j in self.ledger.list_jobs() if j.get('kind') != 'article_revision' and j['week'] == week]
        results = []
        with self.ledger._tx() as db:
            row = db.execute('SELECT value FROM meta WHERE key=?',
                             ('runtime_retry_candidate',)).fetchone()
            preferred = row[0] if row else None
            if row:
                db.execute('DELETE FROM meta WHERE key=?', ('runtime_retry_candidate',))
        ordered_jobs = self.ledger.list_jobs()
        if preferred:
            ordered_jobs.sort(key=lambda item: item['id'] != preferred)
        # Pending candidates retain their slot and may resume after a week boundary.
        for job in ordered_jobs:
            if job.get('kind') == 'article_revision' or job['stage'] not in ('candidate',) or len(results) >= limit:
                continue
            try:
                delivery = self._make_article(job, context)
                status = ('awaiting_astra_review' if 'catalogCorrectionContext' in job
                          and isinstance(delivery, dict) and delivery.get('status') == 'awaiting_astra_review'
                          else 'awaiting_approval')
                results.append({'id': job['id'], 'status': status})
            except Exception as error:
                self.ledger.set_stage(job['id'], 'error', {'reason': reason(error), 'at': stamp()})
                results.append({'id': job['id'], 'status': 'blocked', 'reason': reason(error)})
            finally:
                self._save_usage()
        return {'status': 'completed', 'articles': results}

    def _make_article(self, job, context):
        self._require_running()
        context = self._wise_context(context)
        revision = job.get('kind') == 'article_revision'
        corrected = 'catalogCorrectionContext' in job
        if corrected:
            from catalog_corrections import validate_context, validate_live_context
            correction = validate_context(job['catalogCorrectionContext'])
            validate_live_context(correction, context['products'])
            context = copy.deepcopy(context)
            candidates = {p['id']: p for p in correction['candidateProducts']}
            context['products'] = [copy.deepcopy(candidates.get(p['id'], p)) for p in context['products']]
            context['catalog'] = copy.deepcopy(context['products'])
        if revision:
            from revisions import validate_context
            binding = validate_context(job['revisionContext'])
            base = binding['baseArticle']
            live = next((a for a in context.get('revisionArticles', context.get('articles', [])) if a.get('id') == base['id']), None)
            if live is None or fingerprint(live) != binding['baseHash']:
                raise ValueError('revision_live_baseline_changed')
            live_products = {p['id']: p for p in context['products']}
            if any(live_products.get(p['id']) != p for p in binding['baseProducts']):
                raise ValueError('revision_live_product_baseline_changed')
            gathered = self.catalog.gather_revision(job['theme'], context, binding)
            # Legacy prose stays private in the immutable CAS baseline; models receive identity only.
            public_source = {k: copy.deepcopy(base.get(k)) for k in ('title', 'slug', 'categoryId', 'productIds')}
            gathered['existingArticles'] = [
                {k: copy.deepcopy(a.get(k)) for k in ('id', 'title', 'slug', 'categoryId')}
                for a in gathered.get('existingArticles', [])]
            gathered.update(existingArticle=public_source,
                            editorialCorrectionInstructions=binding['editorialCorrectionInstructions'],
                            verifiedAuthorFacts=copy.deepcopy(binding['verifiedAuthorFacts']))
        else:
            gathered = self.catalog.gather(job['theme'], context)
        atomic(self.root / 'research' / (job['id'] + '.json'), gathered)
        if not all(gathered.get('checks', {}).get(k) is True for k in ('facts', 'images', 'affiliate')):
            raise ValueError('source_product_image_or_affiliate_verification_incomplete')
        if self.config.get('prewriteDisplayGateEnabled') is True:
            from publication_display_gate import build_prewrite_plan
            plan = build_prewrite_plan(job, gathered)
            if plan['status'] == 'correction_required':
                path = self.root / 'display-correction-proposals' / job['id'] / (plan['sourceFingerprint'] + '.json')
                if not path.exists():
                    atomic(path, plan)
                raise ValueError('prewrite_display_correction_required')
        gathered.update({'wisePolicy': context['wisePolicy'], 'CLAUDE': context['editorialRules'], 'SKILL': (Path(self.config['repo']) / 'SKILL.md').read_text()})
        source_dependencies = self._source_dependencies(gathered)
        draft_inputs = {
            'theme': copy.deepcopy(job['theme']),
            'dependencies': {
                'source': source_dependencies,
                'routes': self._model_routes(),
                'revisionContext': copy.deepcopy(job.get('revisionContext')),
                'catalogCorrectionContext': copy.deepcopy(job.get('catalogCorrectionContext')),
            },
            'schemaVersion': {'stage': 1, 'input': 'theme+verified-source', 'output': 'article+brief'},
        }
        bundle = self._run_model_stage(job, 'draft', draft_inputs,
            lambda: self.models.draft(job['theme'], gathered),
            self._model_routes()['draft']['requested'])
        if revision:
            from revisions import EDIT_FIELDS, validate_revision_bundle
            draft = bundle['article']
            article = copy.deepcopy(base)
            article.update({key: draft[key] for key in EDIT_FIELDS})
            article.update(author=draft['author'], productIds=list(binding['targetProductIds']))
            bundle.update(article=article, revisionContext=copy.deepcopy(binding))
            validate_revision_bundle(job, bundle, require_presentation=False)
            bundle['brief']['protected'] = list(dict.fromkeys(bundle['brief'].get('protected', []) + binding['verifiedAuthorFacts']))
        else:
            bundle['article'].update(id=job['id'], slug=job['theme']['slug'], status='draft',
                publishedAt=None, scheduledPublishDate=None, autoGenerated=True)
            bundle['article'].setdefault('createdAt', job['created_at'])
            bundle['article']['updatedAt'] = bundle['article']['createdAt']
        if corrected:
            bundle['catalogCorrectionContext'] = copy.deepcopy(correction)
            from catalog_corrections import validate_bundle
            validate_bundle(job, bundle)
        if gathered.get('images'):
            bundle['images'] = gathered['images']
        bundle['affiliateConfig'] = {'amazonPartnerTag': self.env.get('AMAZON_PARTNER_TAG', '')}
        if bundle.get('purchaseEvidence'):
            raise ValueError('model_purchase_evidence_not_source_bound')
        bundle['wisePolicy'] = context['wisePolicy']['id']
        bundle['brief']['style'] += '\n' + context['wisePolicy']['text']
        if gathered.get('purchaseEvidence'):
            from purchase_evidence import validate_purchase_evidence
            bundle.pop('purchaseEvidence', None)
            bundle = validate_purchase_evidence(bundle, gathered['purchaseEvidence'], datetime.now(JST))
        # Every acceptance binds the source bundle, then the separately generated polish candidate.
        source = copy.deepcopy(bundle)
        artifacts = self.root / 'research' / 'artifacts' / job['id'] / fingerprint(source)
        atomic(artifacts / 'source.json', {'kind': 'source', 'bundle': source})
        polish_inputs = {
            'content': source['article']['content'], 'brief': copy.deepcopy(source['brief']),
            'dependencies': {'sourceBundle': self._source_dependencies(source),
                             'verifiedSource': source_dependencies,
                             'routes': self._model_routes()},
            'schemaVersion': {'stage': 1, 'input': 'exact-source+brief', 'output': 'polish+preservation'},
        }
        def polish_operation():
            candidate = self.models.polish(source['article']['content'], source['brief'])
            checked = inspect_polish(source['article']['content'], candidate['content'])
            if checked.get('passed') is not True:
                raise ValueError('gemini_protected_content_changed')
            return {'polished': candidate, 'preservation': checked}
        polished_stage = self._run_model_stage(job, 'polish', polish_inputs, polish_operation,
                                               self._model_routes()['polish']['requested'])
        polished, preservation = polished_stage['polished'], polished_stage['preservation']
        atomic(artifacts / 'candidate.json', {'kind': 'candidate', 'candidate': polished})
        bundle['article']['content'] = polished['content']
        return self._finish_article_review(job, context, gathered, bundle, source,
                                           preservation, polished, source_dependencies)

    def _finish_article_review(self, job, context, gathered, bundle, source,
                               preservation, polished, source_dependencies):
        self._require_running()
        context = self._wise_context(context)
        revision = job.get('kind') == 'article_revision'
        corrected = 'catalogCorrectionContext' in job
        binding = job.get('revisionContext') or {}
        public_source = ({k: copy.deepcopy(binding['baseArticle'].get(k))
                          for k in ('title', 'slug', 'categoryId', 'productIds')}
                         if revision else None)
        if self.config.get('socialCardsEnabled') is True:
            if self.social_cards is None:
                from social_cards import SocialCards
                self.social_cards = SocialCards(self.config, self.env, self.catalog)
            if revision:
                bundle['article'].setdefault('generationMeta', {})
                bundle['article']['generationMeta'] = dict(bundle['article'].get('generationMeta') or {})
                bundle['article']['generationMeta'].pop('socialCard', None)
            bundle = self.social_cards.build(bundle)
            manifest = bundle.get('article', {}).get('generationMeta', {}).get('socialCard') or {}
            cards = [i for i in bundle.get('images', []) if i.get('role') == 'social-card']
            if manifest.get('width') != 1200 or manifest.get('height') != 630 or len(cards) != 1 or cards[0].get('verified') is not True or any(not manifest.get(k) or cards[0].get(k) != manifest[k] for k in ('url', 'sha256', 'size', 'contentType')):
                raise ValueError('social_card_evidence_missing')
        checks = inspect_bundle({k: v for k, v in bundle.items() if k not in ('revisionContext', 'catalogCorrectionContext')})
        if checks.get('passed') is not True:
            raise ValueError('article_structure_or_affiliate_failed')
        evidence = gathered.get('checks', {})
        preview = self.renderer(bundle, job)
        if revision:
            from inherited_advice import validate_presentation
            inherited = validate_presentation(preview.get('inheritedPresentationContext'), bundle['article']['slug'])
            bundle['inheritedPresentationContext'] = copy.deepcopy(inherited)
        flags = {k: evidence.get(k) is True for k in ('facts', 'images', 'affiliate')}
        medical = self._medical(bundle['article'])
        if revision:
            medical.update(scope='candidate_article_only', inheritedClinicalReverified=False)
        click_results = preview.get('clicksVerified', {})
        clicks_ok = bool(click_results.get('desktop')) and bool(click_results.get('mobile')) if isinstance(click_results, dict) else click_results is True
        flags.update(medical=medical['passed'], render=preview.get('passed') is True and clicks_ok)
        review_bundle = {k: v for k, v in bundle.items()
                         if k not in ('revisionContext', 'catalogCorrectionContext')}
        review_checks = {'evidence': flags, 'structural': checks,
                         'source': gathered.get('evidence', {}),
                         'approvedTheme': job['theme'],
                         'preview': preview, 'polishPreservation': preservation,
                         'editorialRules': context['editorialRules'],
                         'wisePolicy': context['wisePolicy'],
                         'medical': medical,
                         'sourceContent': source['article']['content'],
                         **({'existingArticle': public_source,
                             'editorialCorrectionInstructions': binding['editorialCorrectionInstructions'],
                             'verifiedAuthorFacts': binding['verifiedAuthorFacts']} if revision else {})}
        review_inputs = {
            'bundle': self._source_dependencies(review_bundle),
            'checks': self._review_dependencies(review_checks),
            'dependencies': {'verifiedSource': source_dependencies,
                             'routes': self._model_routes(),
                             'qualityFlags': flags,
                             'structural': checks,
                             'renderer': self._review_dependencies(preview),
                             'editorialRules': context['editorialRules']},
            'schemaVersion': {'stage': 1, 'input': 'bundle+live-checks', 'output': 'final-review'},
        }
        def review_operation():
            candidate = self.models.review(review_bundle, review_checks)
            if candidate.get('passed') is not True:
                raise ValueError('final_review_failed')
            return candidate
        final = self._run_model_stage(job, 'final_review', review_inputs, review_operation,
                                      self._model_routes()['final_review']['requested'])
        job = self.ledger.save_bundle(job['id'], bundle)
        review = dict(final, fingerprint=job['revision'], evidence=flags,
                      polish={'model': polished['model'], 'validated': True})
        if revision:
            review.update(medicalScope='candidate_article_only', inheritedClinicalReverified=False,
                          inheritedAdviceDomSha256=bundle['inheritedPresentationContext']['domSha256'])
        self.ledger.record_review(job['id'], job['revision'], review)
        # Persist an invisible draft, never publish while waiting for a person.
        if not revision and not corrected:
            self.publisher('stage', self.ledger.get_job(job['id']))
        return self.deliver(job['id'])

    def request_revisions(self, specifications):
        self._require_running()
        from revisions import validated_context
        if not isinstance(specifications, list) or not 1 <= len(specifications) <= 3:
            raise ValueError('one_to_three_revision_specifications_required')
        bindings = [validated_context(spec) for spec in specifications]
        if len({b['baseArticle']['id'] for b in bindings}) != len(bindings):
            raise ValueError('duplicate_revision_target')
        catalog = self.catalog.catalog()
        live = catalog['articles']
        for binding in bindings:
            current = next((a for a in live if a['id'] == binding['baseArticle']['id']), None)
            if fingerprint(current) != binding['baseHash']:
                raise ValueError('revision_live_baseline_changed')
        live_products = {p['id']: p for p in catalog['products']}
        for binding in bindings:
            if any(live_products.get(p['id']) != p for p in binding['baseProducts']):
                raise ValueError('revision_live_product_baseline_changed')
        jobs = [self.ledger.request_revision(spec) for spec in specifications]
        return {'status': 'queued', 'jobs': [{'id': j['id'], 'targetId': j['revisionContext']['baseArticle']['id'],
                                             'stage': j['stage']} for j in sorted(jobs, key=lambda j:j['priority'])]}

    def _produce_requested_revision(self):
        self._require_running()
        pending = [j for j in self.ledger.list_jobs() if j.get('kind') == 'article_revision'
                   and j['stage'] == 'candidate']
        if not pending or not self.config.get('generationEnabled'):
            return None
        job = min(pending, key=lambda j:j['priority'])
        marker = self.root / 'revision-production-attempts' / (job['id'] + '.json')
        if marker.exists():
            self.ledger.set_stage(job['id'], 'error', {'reason': 'revision_production_requires_reconciliation', 'at': stamp()})
            return {'id': job['id'], 'status': 'attention', 'reason': 'revision_production_requires_reconciliation'}
        atomic(marker, {'status': 'in_flight', 'at': stamp()})
        try:
            delivery = self._make_article(job, self._context())
            atomic(marker, {'status': 'completed', 'at': stamp()})
            status = 'awaiting_astra_review' if isinstance(delivery, dict) and delivery.get('status') == 'awaiting_astra_review' else 'awaiting_approval'
            return {'id': job['id'], 'status': status}
        except StageUnknown as error:
            self.ledger.set_stage(job['id'], 'error', {'reason': reason(error), 'at': stamp()})
            atomic(marker, {'status': 'unknown', 'at': stamp(), 'reason': reason(error)})
            return {'id': job['id'], 'status': 'attention', 'reason': reason(error)}
        except Exception as error:
            self.ledger.set_stage(job['id'], 'error', {'reason': reason(error), 'at': stamp()})
            atomic(marker, {'status': 'blocked', 'at': stamp(), 'reason': reason(error)})
            return {'id': job['id'], 'status': 'attention', 'reason': reason(error)}
        finally:
            self._save_usage()

    def retry(self, id):
        self._require_running()
        job = self.ledger.get_job(id)
        if job['stage'] not in ('error', 'held', 'rejected') or job.get('publication') or job.get('approval'):
            raise ValueError('job_not_retryable')
        if job.get('bundle'):
            with sqlite3.connect(self.ledger.db_path) as db:
                unresolved = db.execute(
                    "SELECT 1 FROM effects WHERE job_id=? AND status IN ('in_flight','unknown')",
                    (id,)).fetchone()
                requests = [json.loads(row[0]) for row in db.execute(
                    'SELECT data FROM requests WHERE job_id=?', (id,)).fetchall()]
            if unresolved:
                raise ValueError('effect_requires_reconciliation')
            if any(request.get('status') == 'created' and
                   (self.root / 'deliveries' / (request['request_id'] + '.json')).exists()
                   for request in requests):
                raise ValueError('delivery_requires_reconciliation')
            self.ledger._current(job)
            valid_review(job.get('review'), job['revision'])
            restored = self.ledger.set_stage(id, 'review')
            return {'status': restored['stage'], 'id': id, 'sameWeeklySlot': True,
                    'checkpoint': 'review'}
        self.ledger.set_stage(id, 'draft')
        self.ledger.set_stage(id, 'candidate')
        with self.ledger._tx() as db:
            db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',
                       ('runtime_retry_candidate', id))
        return {'status': 'candidate', 'id': id, 'sameWeeklySlot': True}

    def retry_stage(self, id, stage, input_key):
        """Explicitly execute the one remaining attempt for an exact failed input."""
        self._require_running()
        if stage not in ('draft', 'polish', 'final_review'):
            raise ValueError('stage_not_retryable')
        job = self.ledger.get_job(id)
        if (job['stage'] != 'error' or job.get('bundle') or job.get('publication')
                or job.get('approval')):
            raise ValueError('job_not_stage_retryable')
        records = self.stage_journal.status(job_id=id, stage=stage)['records']
        record = next((item for item in records if item.get('stageKey') == input_key), None)
        if (record is None or record.get('status') != 'failed'
                or record.get('attempts', 0) >= record.get('maxAttempts', 0)):
            raise StageBlocked('exact failed stage retry unavailable', stage_key=input_key)
        if job.get('kind') == 'article_revision':
            return self._retry_revision_stage(job, stage, input_key)
        self._explicit_stage_retry = {'jobId': id, 'stage': stage, 'inputKey': input_key}
        self.ledger.set_stage(id, 'draft')
        self.ledger.set_stage(id, 'candidate')
        with self.ledger._tx() as db:
            db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',
                       ('runtime_retry_candidate', id))
        try:
            return self.produce(limit=1)
        finally:
            self._explicit_stage_retry = None

    def _retry_revision_stage(self, job, stage, input_key):
        marker = self.root / 'revision-production-attempts' / (job['id'] + '.json')
        try:
            if marker.is_symlink() or marker.stat().st_mode & 0o777 != 0o600:
                raise ValueError()
            receipt = json.loads(marker.read_text())
            if not isinstance(receipt, dict) or receipt.get('status') != 'blocked':
                raise ValueError()
        except (OSError, ValueError, TypeError):
            raise ValueError('revision_production_requires_reconciliation') from None
        retry_marker = (self.root / 'revision-stage-retries' / job['id'] /
                        (hashlib.sha256(input_key.encode()).hexdigest() + '.json'))
        if retry_marker.exists():
            raise ValueError('revision_stage_retry_requires_reconciliation')
        atomic(retry_marker, {'status': 'in_flight', 'at': stamp(),
                              'stage': stage, 'inputKey': input_key})
        self._explicit_stage_retry = {'jobId': job['id'], 'stage': stage,
                                      'inputKey': input_key}
        self.ledger.set_stage(job['id'], 'draft')
        self.ledger.set_stage(job['id'], 'candidate')
        try:
            current = self.ledger.get_job(job['id'])
            delivery = self._make_article(current, self._context())
            atomic(retry_marker, {'status': 'completed', 'at': stamp(),
                                  'stage': stage, 'inputKey': input_key})
            status = ('awaiting_astra_review' if isinstance(delivery, dict)
                      and delivery.get('status') == 'awaiting_astra_review'
                      else 'awaiting_approval')
            return {'status': 'completed', 'articles': [{'id': job['id'], 'status': status}]}
        except StageUnknown as error:
            self.ledger.set_stage(job['id'], 'error', {'reason': reason(error), 'at': stamp()})
            atomic(retry_marker, {'status': 'unknown', 'at': stamp(),
                                  'stage': stage, 'inputKey': input_key})
            return {'status': 'attention', 'reason': reason(error)}
        except Exception as error:
            self.ledger.set_stage(job['id'], 'error', {'reason': reason(error), 'at': stamp()})
            atomic(retry_marker, {'status': 'blocked', 'at': stamp(),
                                  'stage': stage, 'inputKey': input_key,
                                  'reason': reason(error)})
            return {'status': 'attention', 'reason': reason(error)}
        finally:
            self._explicit_stage_retry = None
            self._save_usage()

    def research_issues(self, id):
        file = self.root / 'research' / (id + '.json')
        if not file.exists():
            return ''
        research = json.loads(file.read_text())
        products = research.get('evidence', {}).get('products', [])
        names = {p.get('id'): p.get('name') for p in research.get('products', []) if isinstance(p, dict)}
        details = []
        for p in products:
            missing = [str(c.get('field')) for c in p.get('claims', []) if c.get('verified') is not True]
            stores = [str(d.get('channel')) for d in p.get('destinations', []) if d.get('verified') is not True]
            parts = (['仕様: ' + '・'.join(missing)] if missing else [])
            if p.get('images') is not True:
                parts.append('商品画像の同一性未確認')
            if stores:
                parts.append('購入先未確認: ' + '・'.join(stores))
            if p.get('issues'):
                parts.append(' / '.join(p['issues']))
            if parts:
                details.append(str(names.get(p.get('productId')) or '掲載商品') + ': ' + '; '.join(parts))
        return '\n'.join(details)[:4000]

    def _model_routes(self):
        routes = {
            'draft': {
                'requested': self.env.get('ARTICLE_WRITER_MODEL') or 'claude-opus-4-8',
                'fallback': self.env.get('ARTICLE_WRITER_FALLBACK_MODEL') or 'claude-sonnet-4-6',
            },
            'polish': {'requested': 'gemini-3.8-flash', 'fallback': None},
            'final_review': {
                'requested': self.env.get('ARTICLE_REVIEW_MODEL') or 'claude-sonnet-4-6',
                'fallback': None,
            },
            'research': {'requested': 'claude-sonnet-4-6', 'fallback': None},
            'social': {'requested': 'claude-sonnet-4-6', 'fallback': None},
        }
        routes['implementationHashes'] = {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ('models.py', 'quality.py')
        }
        return routes

    @staticmethod
    def _source_dependencies(value):
        """Remove only known observation clocks after the source was re-gathered."""
        result = copy.deepcopy(value)
        for item in result.get('references', []) if isinstance(result, dict) else []:
            if isinstance(item, dict):
                item.pop('checkedAt', None)
        for item in result.get('images', []) if isinstance(result, dict) else []:
            if isinstance(item, dict):
                item.pop('checkedAt', None)
        evidence = result.get('evidence', {}) if isinstance(result, dict) else {}
        for product in evidence.get('products', []) if isinstance(evidence, dict) else []:
            if not isinstance(product, dict):
                continue
            product.pop('checkedAt', None)
            for field in ('claims', 'destinations'):
                for item in product.get(field, []):
                    if isinstance(item, dict):
                        item.pop('checkedAt', None)
        return result

    @staticmethod
    def _review_dependencies(value):
        """Exclude only renderer-local files and renderer observation clocks."""
        result = copy.deepcopy(value)
        preview = result.get('preview') if isinstance(result, dict) and 'preview' in result else result
        if isinstance(preview, dict):
            for key in ('desktop', 'mobile', 'path', 'outputDir'):
                if isinstance(preview.get(key), str):
                    preview.pop(key, None)
            for key in ('checkedAt', 'generatedAt', 'observedAt'):
                preview.pop(key, None)
        if isinstance(result, dict) and isinstance(result.get('source'), dict):
            wrapped = Runtime._source_dependencies({'evidence': result['source']})
            result['source'] = wrapped['evidence']
        return result

    def _usage_slice(self, start, *, article_id, stage, reason, requested_model):
        measured = []
        for record in getattr(self.models, 'usage', [])[start:]:
            response_id = record.get('responseId') if isinstance(record, dict) else None
            if response_id and response_id in self._usage_response_ids:
                continue
            if response_id:
                self._usage_response_ids.add(response_id)
            if isinstance(record, dict):
                record.update(articleId=article_id, stage=stage, reason=reason,
                              requestedModel=requested_model,
                              actualModel=record.get('model'))
                measured.append(copy.deepcopy(record))
        return measured

    def _measured_model_call(self, article_id, stage, requested_model, operation,
                             *, reason='initial'):
        self._require_running()
        start = len(getattr(self.models, 'usage', []))
        try:
            with self.model_budget.scope(self._budget_article_id(article_id), stage):
                return operation()
        finally:
            self._usage_slice(start, article_id=article_id, stage=stage, reason=reason,
                              requested_model=requested_model)
            self._flush_budget_notifications()

    def _run_model_stage(self, job, stage, inputs, operation, requested_model,
                         *, explicit_retry=False):
        self._require_running()
        key = self.stage_journal.key(job['id'], stage, inputs)
        retry = getattr(self, '_explicit_stage_retry', None)
        if retry and retry['jobId'] == job['id']:
            order = ('draft', 'polish', 'final_review')
            target = retry['stage']
            if order.index(stage) < order.index(target):
                exact = next((item for item in self.stage_journal.status(
                    job_id=job['id'], stage=stage)['records']
                    if item.get('stageKey') == key and item.get('status') == 'succeeded'), None)
                if exact is None:
                    raise StageBlocked('prior stage inputs changed before explicit retry',
                                       stage_key=key, status='changed')
            elif stage == target:
                if key != retry['inputKey']:
                    raise StageBlocked('exact failed stage inputs changed', stage_key=key,
                                       status='changed')
                explicit_retry = True
        start = len(getattr(self.models, 'usage', []))
        called = False
        reason_name = 'explicit_retry' if explicit_retry else 'initial'
        def measured():
            nonlocal called
            called = True
            with self.model_budget.scope(self._budget_article_id(job['id']), stage):
                return operation()
        try:
            if explicit_retry:
                return self.stage_journal.retry_failed(job['id'], stage, inputs, measured)
            return self.stage_journal.run(job['id'], stage, inputs, measured, max_attempts=2)
        finally:
            if called:
                records = self._usage_slice(start, article_id=job['id'], stage=stage,
                                            reason=reason_name,
                                            requested_model=requested_model)
                receipt_fields = {'responseId', 'model', 'requestedModel', 'actualModel',
                                  'input', 'output', 'usage', 'actualUSD', 'actualInvoiceUsd'}
                receipts = [{name: value for name, value in record.items()
                             if name in receipt_fields} for record in records]
                self.stage_journal.record_usage(job['id'], stage, key, receipts,
                                                reason=reason_name)
                if explicit_retry and getattr(self, '_explicit_stage_retry', None):
                    self._explicit_stage_retry = None
                self._flush_budget_notifications()

    def _save_usage(self):
        records = getattr(self.models, 'usage', [])
        if records:
            unique = []
            for record in records:
                response_id = record.get('responseId') if isinstance(record, dict) else None
                if response_id and response_id in self._saved_usage_response_ids:
                    continue
                if response_id:
                    self._saved_usage_response_ids.add(response_id)
                unique.append(record)
            if unique:
                atomic(self.root / 'usage' / (secrets.token_hex(12) + '.json'),
                       {'at': stamp(), 'calls': unique, 'actualInvoiceUsd': None})
            records.clear()

    def _budget_article_id(self, job_id):
        """A new revision of the same public URL must share its article budget."""
        try:
            job = self.ledger.get_job(job_id)
        except (KeyError, ValueError):
            return job_id
        slug = ((job.get('revisionContext') or {}).get('baseArticle') or {}).get('slug')
        slug = slug or (job.get('theme') or {}).get('slug')
        return 'article:' + fingerprint({'slug': slug}) if isinstance(slug, str) and slug else job_id

    def _flush_budget_notifications(self):
        """Claim once before sending; unknown delivery never triggers blind resend."""
        self._require_running()
        for event in self.model_budget.pending_events():
            if not self.model_budget.claim_event(event['id']):
                continue
            verified = False
            try:
                heading = '【AI予算の警告】' if event.get('level') == 'warning' else '【AI予算到達・工程保留】'
                titles = {self._budget_article_id(j['id']): j['theme'].get('title', j['id'])
                          for j in self.ledger.list_jobs()}
                text = (heading + '\n対象：' + str(titles.get(event.get('articleId'), event.get('articleId')) or '制作週全体') +
                        '\n制作週：' + str(event.get('periodKey')) +
                        '\n発生日時：' + str(event.get('createdAt')) + '\n工程：' + str(event.get('stage')) +
                        '\n判定：' + str(event.get('budgetScope')) + ' / ' + str(event.get('dimension')) +
                        ' ' + str(event.get('projected')) + '（上限 ' + str(event.get('cap')) + '）' +
                        '\n品質基準・記事とSNSの別承認は維持します。' +
                        '\n利用記録と残工程を確認して再評価してください。自動増枠・再試行はしません。' +
                        '\n予算はトークンの実測・保守的予約に基づく制御で、実請求額ではありません。')
                text += ('\n原因（確定）：設定された予算制限により工程を保留しました。'
                         if event.get('level') == 'hold' else
                         '\n原因（確定）：予算の警告しきい値に達しました。品質確認は省略しません。')
                if event.get('periodKey') == self.config.get('productionVerificationPeriod'):
                    self._save_usage()
                    try:
                        from usage_cost_report import usage_cost_summary
                        text += '\n\n' + usage_cost_summary(self.root, self.config, kind='production',
                                                             period_key=event['periodKey'])
                    except Exception:
                        text += '\nこのタスクの利用量・概算費用・予算残量は集計できませんでした。確認が必要です。'
                receipt = self.slack.notice(text)
                verified = isinstance(receipt, dict) and receipt.get('verified') is True
            except Exception:
                pass
            self.model_budget.finish_event(event['id'], verified=verified)

    def _budgeted_manager_call(self, command, request):
        from manager_cli import call
        with self.model_budget.scope('maintenance:manager', 'manager'):
            reservation = self.model_budget.reserve({
                'max_tokens': request['budget']['max_output_tokens'],
                'messages': [{'role': 'user', 'content': canonical(request)}]}, model='gpt-6-astra')
            try:
                response = call(command, request['snapshot'], request['prompt'],
                    request['decisionSchema'], timeout=request['budget']['timeout_seconds'])
            except Exception:
                self.model_budget.settle(reservation, outcome='unknown')
                raise
            else:
                self.model_budget.settle(reservation, usage=response.get('usage'), outcome='success')
                return response
            finally:
                self._flush_budget_notifications()

    def _social_review_allowed(self, job_id):
        if not social_feature_enabled(self.config, 'socialReviewEnabled'):
            return False
        if buffer_social_start(self.config) is None:
            return True
        job = self.ledger.get_job(job_id)
        proposal = ((job.get('social') or {}).get('proposal') or {})
        return (proposal.get('deliveryMode') == 'buffer_x'
                and buffer_social_eligible(job, self.config))

    def deliver(self, id, kind='article'):
        self._require_running()
        if kind == 'social' and not self._social_review_allowed(id):
            raise ValueError('social_review_disabled')
        job = self.ledger.get_job(id)
        target = job if kind == 'article' else job.get('social', {})
        require_current_review(target.get('bundle') if kind == 'article' else target.get('proposal'),
                               target.get('review'), self.config.get('repo'))
        if kind == 'article' and (job.get('kind') == 'article_revision' or 'catalogCorrectionContext' in job):
            try:
                self.ledger._current(job)
                valid_review(job.get('review'), job['revision'])
                valid_astra_review(job.get('astraReview'), job['revision'])
            except ValueError:
                return {'status': 'awaiting_astra_review', 'deferred': True}
        with sqlite3.connect(self.ledger.db_path) as db:
            rows = db.execute('SELECT data FROM requests WHERE job_id=? AND kind=? ORDER BY rowid DESC', (id, kind)).fetchall()
        active = next((json.loads(row[0]) for row in rows if json.loads(row[0])['status'] in ('created', 'delivered')), None)
        if active and active['status'] == 'delivered':
            if datetime.fromisoformat(active['expires_at']) > datetime.now(JST):
                return {'status': 'already_delivered'}
            active = None
        req = active or self.ledger.create_request(id, kind)
        marker = self.root / 'deliveries' / (req['request_id'] + '.json')
        if marker.exists():
            raise ValueError('delivery_requires_reconciliation')
        atomic(marker, {'status': 'in_flight', 'at': stamp(), 'request_id': req['request_id']})
        parts, card = self.slack.deliver(job, req)
        self.ledger.mark_delivered(req['request_id'], {'scope': self.config['slack'], 'parts': parts}, card)
        atomic(marker, {'status': 'delivered', 'at': stamp(), 'card_ts': card, 'parts': parts})
        return {'status': 'delivered', 'card_ts': card}

    def consume(self):
        self._require_running()
        consume_social = social_feature_enabled(self.config, 'socialReviewEnabled')
        buffer_rollout = buffer_social_start(self.config) is not None
        spool = Path(self.config['spoolDir'])
        processed = spool / 'editorial-processed'
        processed.mkdir(mode=0o700, exist_ok=True)
        quarantine = spool / 'editorial-quarantine'
        quarantine.mkdir(mode=0o700, exist_ok=True)
        count = 0
        for path in sorted(spool.glob('*.json'))[:1000]:
            if count >= 100:
                break
            if path.is_symlink() or path.stat().st_size > 16384:
                continue
            try:
                event = json.loads(path.read_text())
                if not isinstance(event, dict):
                    raise ValueError('invalid_event')
                event['card_ts'] = event.get('message_ts')
            except (ValueError, UnicodeError):
                if buffer_rollout:
                    continue  # Unknown legacy SNS spool remains byte-for-byte untouched.
                if not consume_social:
                    continue  # Unknown kind stays untouched in article-only mode.
                path.rename(quarantine / (path.stem + '-' + secrets.token_hex(4) + '.json'))
                continue
            with self.ledger._tx() as db:
                row = db.execute('SELECT job_id,kind,data FROM requests WHERE id=?',
                                 (event.get('request_id'),)).fetchone()
                if row and row[1] == 'social' and buffer_rollout:
                    job = self.ledger._get(db, row[0])
                    request = json.loads(row[2])
                    social = job.get('social') or {}
                    proposal = social.get('proposal') or {}
                    if (not buffer_social_eligible(job, self.config)
                            or proposal.get('deliveryMode') != 'buffer_x'
                            or request.get('manifest_hash') != social.get('revision')
                            or request.get('status') != 'delivered'):
                        continue
                elif row is None and buffer_rollout:
                    continue
            if not consume_social:
                with self.ledger._tx() as db:
                    row = db.execute('SELECT kind FROM requests WHERE id=?',
                                     (event.get('request_id'),)).fetchone()
                if row is None or row[0] != 'article':
                    continue
            try:
                self.ledger.decide(event, self.config['slack'])
                count += 1
            except ValueError:
                pass  # Old review-only requests never become publication authority.
            target = processed / path.name
            if not target.exists():
                path.rename(target)
        return count

    @staticmethod
    def _post_audit_message(job, audit):
        labels = {'success': '解消', 'failed': '不一致', 'unverified': '確認不能',
                  'requires_reconciliation': '確認不能'}
        # Only fixed, human-readable explanations cross the Slack boundary.
        reasons = {
            'missing_image': '公開ページの商品画像を確認できませんでした',
            'post_audit_check_unavailable': '公開後の確認処理を完了できませんでした',
            'public_content_mismatch': '公開本文が承認した内容と一致しません',
            'public_title_mismatch': '公開タイトルが承認した内容と一致しません',
            'image_mismatch': '公開画像が確認済みの画像と一致しません',
            'merchant_identity_mismatch': '購入先の商品が記事の商品と一致しません',
            'external_403_captcha': '購入先のアクセス制限により確認できませんでした',
            'browser_unavailable': '画面表示の確認を完了できませんでした',
            'render_unverified': 'パソコン・スマートフォンの表示を確認できませんでした',
            'invalid_publication_binding': '公開URLと承認記事の対応を確認できませんでした',
            'publication_body_hash_mismatch': '公開記録の本文が承認本文と一致しません',
            'public_response_binding_mismatch': '公開ページの応答またはURLが想定と一致しません',
            'public_html_unavailable': '公開ページのHTMLを確認できませんでした',
            'public_get_unavailable': '公開ページに接続できませんでした',
            'approved_body_hash_mismatch': '公開本文が承認した内容と一致しません',
            'approved_prose_mismatch': '本文が承認内容と一致しません',
            'visible_product_image_not_rendered': '公開画面に商品画像が表示されていません',
            'approved_product_image_not_rendered': '承認した商品画像が公開画面に表示されていません',
            'social_manifest_mismatch': 'SNS用画像の承認記録が一致しません',
            'social_metadata_mismatch': '公開ページのSNS見出し画像が承認画像と一致しません',
            'product_image_proof_missing': '商品の確認済み画像の記録が不足しています',
            'approved_image_proof_invalid': '承認画像の確認記録が不完全です',
            'approved_image_bytes_mismatch': '公開画像が承認画像と一致しません',
            'public_image_get_unavailable': '公開画像を取得できませんでした',
            'viewport_evidence_missing': '画面表示の確認記録が不足しています',
            'browser_timeout_or_unavailable': '画面表示の確認が時間切れ、または実行不能でした',
            'approved_merchant_url_missing': '承認した購入先URLがありません',
            'affiliate_account_binding_missing': '購入リンクの紹介先設定を確認できませんでした',
            'affiliate_account_or_route_mismatch': '購入リンクの紹介先または経路が一致しません',
            'approved_product_model_or_brand_missing': '商品の型番またはブランドの確認情報が不足しています',
            'merchant_variant_evidence_conflicting': '販売ページのサイズ表記が混在し、商品を確定できません',
            'merchant_model_evidence_missing': '販売ページに型番の確認情報がなく、同一性を確定できません',
            'merchant_html_unavailable': '購入先の商品ページを確認できませんでした（アクセス制限など）',
            'merchant_challenge_unverified': '購入先のアクセス制限により確認できませんでした',
            'merchant_destination_or_product_identity_mismatch': '購入先の商品または型番が一致しません',
            'merchant_get_unavailable': '購入先に接続できませんでした',
            'audit_unavailable': '公開後の確認処理を完了できませんでした',
            'audit_timeout_or_unavailable': '公開後の確認が時間切れ、または実行不能でした',
            'audit_input_or_transport_unavailable': '確認データの受け渡しを完了できませんでした',
        }
        status = audit['status']
        lines = ['【公開後監査】' + job['bundle']['article']['title'], job['publication']['url'],
                 '結果: ' + labels.get(status, '確認不能')]
        if status != 'success':
            checked = audit.get('result', {})
            checks = checked.get('checks')
            issues = ([c for c in checks if isinstance(c, dict) and c.get('status') != 'passed']
                      if isinstance(checks, list) and checks else checked.get('issues') or [])
            if not isinstance(issues, list):
                issues = []
            explanations = []
            for issue in issues:
                code = issue.get('code', issue.get('reason')) if isinstance(issue, dict) else issue
                name = issue.get('name', '') if isinstance(issue, dict) else ''
                if isinstance(code, str) and ': ' in code:
                    name, code = code.split(': ', 1)
                message = reasons.get(code, '確認項目の詳細はCodexで確認してください') if isinstance(code, str) else '確認項目の詳細はCodexで確認してください'
                destination = re.fullmatch(r'destination\.(\d{1,3})\.(amazon|rakuten)', str(name))
                image = re.fullmatch(r'(image|product_image_binding)\.(\d{1,3})', str(name))
                products = job['bundle'].get('products', [])
                product = None
                prefix = ''
                if destination:
                    index = int(destination[1])
                    product = products[index] if index < len(products) else None
                    prefix = 'Amazon' if destination[2] == 'amazon' else '楽天'
                elif image:
                    index = int(image[2])
                    if image[1] == 'product_image_binding':
                        product = products[index] if index < len(products) else None
                    else:
                        images = job['bundle'].get('images', [])
                        proof = images[index] if index < len(images) else {}
                        product = next((p for p in products if p.get('id') == proof.get('productId')), None)
                    prefix = '画像'
                elif name in ('desktop', 'mobile'):
                    prefix = 'パソコン表示' if name == 'desktop' else 'スマートフォン表示'
                if product:
                    title = re.sub(r'\s+', ' ', str(product.get('name', '商品')))[:80]
                    title = title.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    prefix = title + '／' + prefix
                if prefix:
                    message = prefix + ': ' + message
                if message not in explanations:
                    explanations.append(message)
            lines.extend('・' + message for message in explanations[:5])
            if audit.get('nextAttemptAt'):
                lines.append('30分後に再確認します。')
            else:
                lines.append('Codexで確認・対応が必要です。')
        return '\n'.join(lines)

    def _post_audit_notice(self, job, key, audit):
        """Separate delivery journal: an unknown Slack effect never auto-resends."""
        path = self.root / 'post-audit-notifications' / (key + '.json')
        saved = json.loads(path.read_text()) if path.exists() else {}
        if saved and saved.get('status') != 'verified':
            if saved.get('status') != 'requires_reconciliation':
                saved.update(status='requires_reconciliation', action='Verify Slack delivery before clearing this marker')
                atomic(path, saved)
            return saved['status']
        outcome = audit['status']
        if saved.get('outcome') == outcome or (not saved and outcome == 'success'):
            return saved.get('status', 'not_needed')
        marker = {'status': 'in_flight', 'at': stamp(), 'outcome': outcome, 'auditKey': key}
        atomic(path, marker)
        try:
            receipt = self.slack.notice(self._post_audit_message(job, audit))
            if not isinstance(receipt, dict) or receipt.get('verified') is not True:
                raise ValueError('post_audit_notice_delivery_unknown')
            marker.update(status='verified', receipt=receipt, at=stamp())
        except Exception as error:
            marker.update(status='requires_reconciliation', reason=reason(error),
                          action='Verify Slack delivery before clearing this marker')
        atomic(path, marker)
        return marker['status']

    def _post_audit_fault(self, error, job_id=None):
        """One global fault notice until operator reconciliation; never expose raw errors."""
        notification = 'requires_reconciliation'
        path = self.root / 'post-audit-notifications' / 'engine-fault.json'
        try:
            if path.exists():
                saved = json.loads(path.read_text())
                notification = 'verified' if saved.get('status') == 'verified' else 'requires_reconciliation'
            else:
                atomic(path, {'status': 'in_flight', 'at': stamp()})
                try:
                    receipt = self.slack.notice('【公開後監査】確認不能\n監査の記録または処理に問題があり、一部の記事を確認できませんでした。\nCodexで監査記録と通知状況を確認してください。')
                    if not isinstance(receipt, dict) or receipt.get('verified') is not True:
                        raise ValueError('post_audit_fault_delivery_unknown')
                    atomic(path, {'status': 'verified', 'at': stamp(), 'receipt': receipt})
                    notification = 'verified'
                except Exception:
                    atomic(path, {'status': 'unknown', 'at': stamp()})
        except Exception:
            pass  # Broken notification storage also needs manual reconciliation, never a blind send.
        return {'id': job_id, 'status': 'requires_reconciliation', 'reason': reason(error),
                'action': 'Inspect private post-publication audit receipts and notification markers',
                'notificationStatus': notification}

    def _post_publication_audits(self):
        """Caller holds runtime.flock. Read-only checks never mutate ledger authority."""
        self._require_running()
        if self.config.get('postPublicationAuditEnabled') is not True:
            return []
        def scope_date(value):
            if not isinstance(value, str):
                raise ValueError('post_audit_scope_date_required')
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError('post_audit_scope_date_requires_timezone')
            return parsed.astimezone(JST)
        cutoff = scope_date(self.config.get('postPublicationAuditSince'))
        backfill = self.config.get('postPublicationAuditBackfillIds', [])
        if not isinstance(backfill, list) or any(not isinstance(id, str) or not id.strip() for id in backfill):
            raise ValueError('post_audit_backfill_ids_invalid')
        summaries = []
        attempted = False
        now = datetime.now(JST)
        from publication_selection import latest_published_jobs
        from record_reconciliation import project_reconciliations
        projected = project_reconciliations(self.root)
        reconciled = {item['sourceIdentity'].get('path'): item
                      for item in projected['reconciledSources']
                      if item['recordType'] == 'post_publication_audit'}
        jobs = latest_published_jobs(self.ledger.list_jobs(), on_invalid=lambda error, versions:
            summaries.extend(self._post_audit_fault(error, item['id']) for item in versions))
        for job in jobs:
            try:
                publication = job.get('publication') or {}
                readback = publication.get('readback') or {}
                if (publication.get('verified') is not True or readback.get('verified') is not True
                        or readback.get('fingerprint') != job.get('revision')
                        or publication.get('revision') != job.get('revision')):
                    continue
                # Explicit IDs authorize historical backfill without widening rollout scope.
                if job['id'] not in backfill and scope_date(publication.get('at')) < cutoff:
                    continue
                # Actual publication metadata is separate from the immutable source bundle.
                key = fingerprint({'id': job['id'], 'revision': job['revision'], 'publication': publication})
                path = self.root / 'post-publication-audits' / (key + '.json')
                audit = json.loads(path.read_text()) if path.exists() else {
                    'schemaVersion': 1, 'id': job['id'], 'revision': job['revision'],
                    'publication': publication, 'auditKey': key, 'status': 'pending', 'attempts': []}
                closure = reconciled.get('post-publication-audits/' + path.name)
                if closure and closure['jobId'] == job['id'] and closure['revision'] == job['revision']:
                    proof = next((p for p in closure['proofs']
                                  if p['kind'] == 'same_version_audit_passed'), None)
                    if proof:
                        summaries.append({'id': job['id'], 'revision': job['revision'],
                            'auditKey': key, 'status': 'success', 'resolution': 'evidence_reconciled',
                            'observedAt': proof['observedAt'], 'evidence': proof['evidenceIdentity'],
                            'attempts': len(audit['attempts']), 'receipt': str(path),
                            'nextAttemptAt': None, 'notificationStatus': 'not_needed'})
                        continue
                if audit['status'] == 'in_flight':
                    audit.update(status='requires_reconciliation',
                                 action='Inspect interrupted audit evidence; explicitly reconcile before another check')
                    atomic(path, audit)
                due = audit['status'] == 'pending' or (
                    audit['status'] in ('failed', 'unverified') and len(audit['attempts']) < 3
                    and datetime.fromisoformat(audit['nextAttemptAt']) <= now)
                if due and not attempted:
                    attempted = True
                    audit.update(status='in_flight', startedAt=stamp())
                    atomic(path, audit)
                    try:
                        if self.post_auditor is None:
                            from post_publication_audit import PostPublicationAudit
                            # A catalog injection bypasses the killable production deadline.
                            self.post_auditor = PostPublicationAudit(self.config, self.env)
                        checked = self.post_auditor.check(copy.deepcopy(job))
                        if not isinstance(checked, dict) or type(checked.get('passed')) is not bool:
                            raise ValueError('post_audit_result_invalid')
                        # Validate serializability before writing the completed receipt.
                        checked = json.loads(json.dumps(checked, allow_nan=False))
                        reported = checked.get('status')
                        unverified = (reported not in (None, 'passed', 'success', 'failed')
                                      or checked.get('verified') is False
                                      or reported == 'failed' and checked['passed'])
                        status = 'unverified' if unverified else ('success' if checked['passed'] else 'failed')
                    except Exception as error:
                        checked = {'passed': False, 'status': 'unverified',
                                   'issues': [{'code': 'post_audit_check_unavailable', 'reason': reason(error)}]}
                        status = 'unverified'
                    audit['attempts'].append({'at': stamp(), 'status': status, 'result': checked})
                    audit.update(status=status, result=checked, completedAt=stamp(),
                                 nextAttemptAt=(now + timedelta(minutes=30)).isoformat() if status != 'success' and len(audit['attempts']) < 3 else None,
                                 action='' if status == 'success' else
                                     ('Inspect audit evidence; automatic recheck in 30 minutes' if len(audit['attempts']) < 3
                                      else 'Inspect audit evidence and correct or reconcile manually; retry limit reached'))
                    atomic(path, audit)
                notification = self._post_audit_notice(job, key, audit) if audit['status'] != 'pending' else 'not_needed'
                summaries.append({k: audit.get(k) for k in
                                  ('id', 'auditKey', 'revision', 'status', 'result', 'nextAttemptAt', 'action')})
                summaries[-1].update(attempts=len(audit['attempts']), receipt=str(path), notificationStatus=notification)
            except Exception as error:
                summaries.append(self._post_audit_fault(error, job.get('id')))
        return summaries

    def _manager_enabled(self):
        options = self.config.get('editorialManager')
        return options is not None and (not isinstance(options, dict)
                                       or options.get('enabled', False) is not False)

    def _queue_manager_work(self, plan, snapshot):
        """Queue a bounded human work order; never change a job or execute a retry."""
        from manager import semantic_key, expectations
        if (plan.action not in ('improve_existing', 'investigate_sources', 'reconcile_unknown')
                or plan.state_fingerprint != semantic_key(snapshot)):
            return {'status': 'blocked'}
        target = next((j for j in snapshot['jobs'] if j['id'] == plan.job_id), None)
        if plan.expectations != expectations(target):
            return {'status': 'blocked'}
        opportunity = None
        if plan.target_url is not None:
            opportunity = next((o for o in snapshot['metrics']['opportunities'] if o['url'] == plan.target_url), None)
            if plan.action != 'improve_existing' or target is not None or opportunity is None:
                return {'status': 'blocked'}
        elif target is None:
            return {'status': 'blocked'}
        order = dict(action=plan.action, jobId=plan.job_id, targetUrl=plan.target_url,
                     revision=plan.revision, stateFingerprint=plan.state_fingerprint,
                     status='human_needed', expectations=copy.deepcopy(plan.expectations))
        if opportunity is not None:
            order['opportunity'] = copy.deepcopy(opportunity)
        if target is not None:
            order['observedStatus'] = {k: target.get(k) for k in
                ('stage', 'errorCode', 'bundleCurrent', 'reviewPassed', 'published', 'socialPosted')}
            order['effects'] = [dict(e) for e in snapshot['effects'] if e['jobId'] == plan.job_id][:10]
        if len(canonical(order).encode()) > 16000:
            return {'status': 'blocked'}
        key = 'editorial_manager_work:' + fingerprint([plan.state_fingerprint, plan.action,
                                                       plan.job_id, plan.target_url, plan.revision])
        with self.ledger._tx() as db:
            if db.execute('SELECT 1 FROM meta WHERE key=?', (key,)).fetchone():
                return {'status': 'completed'}
            if db.execute("SELECT count(*) FROM meta WHERE key LIKE 'editorial_manager_work:%'").fetchone()[0] >= 100:
                return {'status': 'blocked'}
            if target is not None:
                current = self.ledger._get(db, plan.job_id)
                if current.get('revision') != plan.revision or current['stage'] != target['stage']:
                    return {'status': 'blocked'}
            db.execute('INSERT INTO meta VALUES (?,?)', (key, canonical(order)))
            self.ledger._event(db, plan.job_id, 'manager_work_order', order)
        return {'status': 'completed'}

    def _evaluate_manager(self, now):
        """Called inside the CLI runtime.flock; no nested runtime lock or fallback."""
        self._require_running()
        from dataclasses import asdict
        from manager import Manager, Budget
        from manager_cli import call
        options = self.config.get('editorialManager')
        if not isinstance(options, dict):
            return {'enabled': True, 'status': 'unconfigured', 'budget': None,
                    'callsUsed': 0, 'pendingActionCount': 0, 'pendingActions': []}
        budget = None
        provider = None
        try:
            if not isinstance(options, dict) or options.get('enabled') is not True:
                raise ValueError('invalid_manager_configuration')
            budget = Budget(**options['budget'])
            command = options['command']
            if not isinstance(command, list) or not command or not all(isinstance(v, str) and v for v in command):
                raise ValueError('invalid_manager_command')
            provider = lambda request: self._budgeted_manager_call(command, request)
        except (KeyError, TypeError, ValueError):
            pass
        try:
            receipt = Manager(self.root, budget=budget).evaluate_locked(self, provider, now=now,
                handlers={action: self._queue_manager_work for action in
                          ('improve_existing', 'investigate_sources', 'reconcile_unknown')})
        except Exception:
            receipt = {'status': 'requires_reconciliation'}
        # No summary, raw model body, command, attachment or transport output in health.
        projection = {k: receipt[k] for k in ('status', 'receiptStatus', 'stateFingerprint', 'reason',
            'errorCode', 'requestedModel', 'actualModel', 'usage', 'actualInvoiceUsd', 'costMissing',
            'usdCapEnforced', 'routeAssurance') if k in receipt}
        projection.update(enabled=True, budget=asdict(budget) if budget else None)
        with sqlite3.connect(self.ledger.db_path) as db:
            period = self.ledger.production_schedule.period_key(now) or 'inactive'
            row = db.execute('SELECT value FROM meta WHERE key=?', ('editorial_manager_calls:' + period,)).fetchone()
            projection['callsUsed'] = int(row[0]) if row else 0
            rows = db.execute("SELECT value FROM meta WHERE key LIKE 'editorial_manager_work:%' ORDER BY key LIMIT 100").fetchall()
        pending = [json.loads(row[0]) for row in rows if json.loads(row[0]).get('status') == 'human_needed']
        projection['pendingActionCount'] = len(pending)
        projection['pendingActions'] = [{k: item.get(k) for k in
            ('action', 'jobId', 'targetUrl', 'revision', 'stateFingerprint', 'status')} for item in pending[:20]]
        return projection

    def tick(self):
        self.execution_policy = execution_policy(self.config)
        if self.execution_policy is not None and self.execution_policy.suspended:
            return {'status': 'suspended', 'mode': 'deterministic'}
        decisions = self.consume()
        now = datetime.now(JST)
        try:
            daily_metrics = collect_daily_metrics(self.config, self.env, now=now)
        except Exception:
            daily_metrics = {'status': 'failed', 'reason': 'daily_metrics_collection_failed'}
        dispatch = (DeterministicDispatcher(self).plan(now)
                    if self.execution_policy is not None else None)
        actions = {(action['kind'], action.get('jobId'), action.get('deliveryKind'))
                   for action in (dispatch or {}).get('actions', [])}
        # Separate errors from generic attention notices, and never skip existing gates.
        try:
            audits = self._post_publication_audits()
        except Exception as error:
            audits = [self._post_audit_fault(error)]
        results = []
        if daily_metrics.get('status') in ('failed','already_failed','requires_reconciliation'):
            results.append({'id':'daily-metrics','status':'attention',
                            'reason':'daily_metrics_collection_failed'})
        if dispatch is not None:
            results.extend({'id': item.get('jobId') or 'deterministic-dispatch',
                            'status': 'attention', 'reason': item['reason']}
                           for item in dispatch.get('blocked', []))
        for job in self.ledger.list_jobs():
            try:
                if job['stage'] == 'approved' and self.config.get('publicationEnabled'):
                    if dispatch is not None and ('publish', job['id'], None) not in actions:
                        continue
                    if ('catalogCorrectionContext' in job
                            and self.config.get('catalogCorrectionsPublicationEnabled') is not True):
                        results.append({'id': job['id'], 'status': 'waiting_auth',
                                        'reason': 'catalog_corrections_publication_disabled'})
                        continue
                    require_current_review(job.get('bundle'), job.get('review'), self.config['repo'])
                    if not self.ledger.claim_effect(job['id'], 'publish'):
                        continue
                    try:
                        result = self.publisher('publish-corrected' if 'catalogCorrectionContext' in job else
                                                'publish-revision' if job.get('kind') == 'article_revision' else 'publish', job)
                        self.ledger.record_publication(job['id'], job['revision'], result)
                        self.ledger.finish_effect(job['id'], 'publish', {'status': 'success', **result})
                    except Exception as error:
                        diagnostic = safe_publication_diagnostic(getattr(error, 'diagnostic', None))
                        self.ledger.finish_effect(job['id'], 'publish', {'status': 'unknown', 'reason': 'publication_requires_reconciliation',
                            **({'diagnostic': diagnostic} if diagnostic else {})})
                        raise
                    self.slack.notice('【公開確認済み】' + job['bundle']['article']['title'] + '\n' + result['url'])
                elif job['stage'] == 'review':
                    if dispatch is not None and ('deliver', job['id'], 'article') not in actions:
                        continue
                    self.deliver(job['id'])
                elif job.get('kind') != 'article_revision' and job['stage'] == 'published' and not job.get('social'):
                    if dispatch is not None and ('make_social', job['id'], None) not in actions:
                        continue
                    marker = self.root / 'social-attempts' / (job['id'] + '.json')
                    if marker.exists():
                        raise ValueError('social_generation_requires_reconciliation')
                    atomic(marker, {'status': 'in_flight', 'at': stamp()})
                    self.make_social(job)
                    atomic(marker, {'status': 'completed', 'at': stamp()})
                elif job['stage'] == 'social_review':
                    if dispatch is not None and ('deliver', job['id'], 'social') not in actions:
                        continue
                    self.deliver(job['id'], 'social')
                elif job['stage'] == 'social_approved':
                    mode = job['social']['proposal'].get('deliveryMode', 'manual')
                    action = 'publish_buffer_social' if mode == 'buffer_x' else 'publish_social'
                    if dispatch is not None and (action, job['id'], None) not in actions:
                        continue
                    if mode == 'buffer_x':
                        if self.config.get('bufferPostingEnabled') is True:
                            self.publish_buffer_social(job, now=now)
                        else:
                            results.append({'id': job['id'], 'status': 'waiting_auth',
                                            'reason': 'buffer_posting_disabled'})
                    elif mode == 'auto_x':
                        if self.config.get('socialPostingEnabled') is True:
                            self.publish_social(job)
                        else:
                            results.append({'id': job['id'], 'status': 'waiting_auth',
                                            'reason': 'social_posting_disabled'})
                    else:
                        raise ValueError('legacy_social_requires_mode_migration')
                elif job['stage'] == 'social_scheduled':
                    if self._buffer_scheduled_notice_status(job) != 'verified':
                        results.append({'id': job['id'], 'status': 'attention',
                                        'reason': 'buffer_schedule_notice_requires_reconciliation'})
                    if dispatch is not None and ('publish_buffer_social', job['id'], None) not in actions:
                        continue
                    self.publish_buffer_social(job, now=now)
                elif job['stage'] == 'social_posted':
                    if dispatch is not None and ('notify_social', job['id'], None) not in actions:
                        continue
                    self.notify_social_posted(job)
            except Exception as error:
                results.append({'id': job['id'], 'status': 'attention', 'reason': reason(error)})
        try:
            revision_result = (self._produce_requested_revision()
                               if dispatch is None or any(action[0] == 'produce_revision' for action in actions)
                               else None)
        except Exception as error:
            revision_result = {'status': 'attention', 'reason': reason(error)}
        if revision_result:
            results.append(revision_result)
        manager_projection = None
        if dispatch is not None:
            production_action = next((action for action in dispatch['actions']
                                      if action['kind'] == 'produce'), None)
            if production_action is not None:
                try:
                    results.append({'production': self.produce(limit=1)})
                except Exception as error:
                    results.append({'status': 'attention', 'reason': reason(error),
                                    'production': {'status': 'blocked', 'reason': reason(error)}})
        elif self._manager_enabled():
            try:
                manager_projection = self._evaluate_manager(now)
            except Exception:
                manager_projection = {'enabled': True, 'status': 'requires_reconciliation',
                                      'budget': None, 'pendingActions': []}
            effective = manager_projection.get('receiptStatus', manager_projection['status'])
            if effective not in ('completed', 'busy') or manager_projection.get('pendingActionCount', 0):
                results.append({'id': 'editorial-manager', 'status': 'attention',
                                'reason': 'editorial_manager_requires_attention'})
        elif not revision_result and self.config.get('generationEnabled') and self.ledger.production_schedule.is_due(now):
            try:
                results.append({'production': self.produce(limit=1)})
            except Exception as error:
                results.append({'status': 'attention', 'reason': reason(error),
                                'production': {'status': 'blocked', 'reason': reason(error)}})
        jobs = self.ledger.list_jobs()
        if self.config.get('seoStateRoot'):
            try:
                self._analytics_context()
            except Exception:
                results.append({'analytics': {'status': 'unavailable'}})
        reports = []
        if self.config.get('reportsEnabled') is True:
            try:
                reports = self.reporter.tick(jobs=jobs, now=now)
            except Exception:
                reports = [{'kind': 'reports', 'status': 'requires_reconciliation'}]
        report_attention = any(r.get('status') == 'requires_reconciliation' for r in reports)
        try:
            from index_tracking import track_publications
            index_tracking = track_publications(jobs, self.root, self.env, self.config, now, atomic)
        except Exception:
            index_tracking = [{'error': 'index_tracking_unavailable'}]
        audit_attention = any(a.get('status') in ('failed', 'unverified', 'requires_reconciliation')
                              or a.get('notificationStatus') == 'requires_reconciliation' for a in audits)
        result = {'status': 'attention' if audit_attention or report_attention or any(r.get('status') == 'attention' for r in results) else 'completed',
                  'at': stamp(), 'decisions': decisions, 'results': results,
                  'dailyMetrics': daily_metrics,
                  'articles': [dict({k: j[k] for k in ('id', 'theme', 'stage', 'revision', 'error')},
                      review={k: (j.get('review') or {}).get(k) for k in ('model', 'score', 'passed')},
                      approval={'action': 'approved' if j.get('approval') else None},
                      publication=j.get('publication'),
                      social={'status': j['stage'] if j.get('social') else None,
                              'deliveryMode': ((j.get('social') or {}).get('proposal') or {}).get('deliveryMode', 'manual'),
                              'publication': self._social_publication_summary(j)}) for j in jobs],
                  'reports': reports, 'reportAttention': report_attention,
                  'indexTracking': index_tracking, 'postPublicationAudits': audits, 'postPublicationAuditEnabled': self.config.get('postPublicationAuditEnabled') is True,
                  'telegramEnabled': False, 'publicationEnabled': bool(self.config.get('publicationEnabled'))}
        if manager_projection is not None:
            result['manager'] = manager_projection
        if dispatch is not None:
            result['dispatch'] = dispatch
        self._flush_budget_notifications()
        result['modelBudget'] = self.model_budget.inspect()
        if self.config.get('productionVerificationPeriod'):
            try:
                from production_verification import verify_period
                from usage_cost_report import usage_cost_summary
                period = self.config['productionVerificationPeriod']
                result['productionVerification'] = verify_period(self.root, jobs, period,
                    self.config['slack'], self.slack.notice, now=now, results=results,
                    cost_text=lambda: usage_cost_summary(self.root, self.config, kind='production',
                                                         period_key=period, now=now))
            except Exception:
                result['productionVerification'] = {'status': 'requires_reconciliation'}
            if result['productionVerification']['status'] in ('requires_reconciliation', 'blocked'):
                result['status'] = 'attention'
        if (any((job.get('error') or {}).get('reason') == 'model_budget_hold' for job in jobs)
                or any(result['modelBudget']['eventsByStatus'].get(status, 0)
                       for status in ('in_flight', 'unknown'))):
            result['status'] = 'attention'
        atomic(self.root / 'health.json', result)
        handled_ids = set(result.get('productionVerification', {}).get('handledAttentionJobIds', []))
        handled_reasons = set(result.get('productionVerification', {}).get('handledGlobalReasons', []))
        attention = [{'id': j['id'], 'title': j['theme'].get('title', j['id']), 'error': j['error']}
                     for j in jobs if j.get('error') and j['error'].get('reason') != 'model_budget_hold'
                     and j['id'] not in handled_ids]
        titles = {j['id']: j['theme'].get('title', '記事制作の処理') for j in jobs}
        attention += [{'id': r.get('id', 'runtime'), 'title': titles.get(r.get('id'), '記事制作の管理処理'),
                       'error': {'reason': r.get('reason', '確認が必要')}}
                      for r in results if r.get('status') == 'attention'
                      and r.get('reason') != 'model_budget_hold'
                      and r.get('reason') not in handled_reasons
                      and r.get('id') not in handled_ids]
        if attention:
            result['status'] = 'attention'
            atomic(self.root / 'health.json', result)
            key = hashlib.sha256(canonical(attention).encode()).hexdigest()
            notified = self.root / 'attention' / (key + '.json')
            if not notified.exists():
                atomic(notified, {'status': 'in_flight', 'at': stamp()})
                try:
                    receipt = self.slack.notice(attention_text(attention, self.config.get('slack', {}),
                        {a['id']: self.research_issues(a['id']) for a in attention}))
                    atomic(notified, {'status': 'delivered', 'at': stamp(), 'receipt': receipt})
                except Exception as error:
                    atomic(notified, {'status': 'unknown', 'at': stamp(), 'reason': reason(error)})
            result['attentionDelivery'] = json.loads(notified.read_text())
            atomic(self.root / 'health.json', result)
        self._save_usage()
        return result

    def make_social(self, job):
        self._require_running()
        if not social_feature_enabled(self.config, 'socialGenerationEnabled'):
            raise ValueError('social_generation_disabled')
        buffer_start = buffer_social_start(self.config)
        if buffer_start is not None:
            if not buffer_social_eligible(job, self.config):
                raise ValueError('buffer_social_period_ineligible')
            if not self._social_audit_success(job):
                raise ValueError('buffer_social_requires_successful_public_audit')
            self._valid_buffer_social_card(job)
            if buffer_social_outstanding(self.ledger.list_jobs()) >= 3:
                raise ValueError('buffer_social_outstanding_cap')
            settings = self.config.get('buffer')
            if not isinstance(settings, dict):
                raise ValueError('buffer_binding_unconfigured')
            required = {key: settings.get(key) for key in
                        ('organizationId', 'channelId', 'xAccountId', 'schedulingPolicy')}
            if (not all(isinstance(value, str) and value for value in required.values())
                    or required['schedulingPolicy'] != 'next_available_slot'):
                raise ValueError('buffer_binding_unconfigured')
        publication = job.get('publication') or {}
        proof = publication.get('readback') or {}
        if publication.get('verified') is not True or proof.get('verified') is not True or proof.get('fingerprint') != job['revision']:
            raise ValueError('social_publication_unverified')
        bundle = copy.deepcopy(job['bundle'])
        bundle.pop('catalogCorrectionContext', None)
        bundle.pop('revisionContext', None)
        account = json.loads((Path(self.config['repo']) / 'data/account-config.json').read_text())
        bundle['socialRules'] = {k: account[k] for k in ('tone', 'ngWords', 'linkRules', 'formatting', 'personaGuards') if k in account}
        policy = load_policy(self.config['repo'])
        bundle['socialRules']['wisePolicy'] = policy
        bundle['brief']['style'] += '\n' + policy['text']
        bundle['socialRules']['approval'] = ('Separate exact-version human approval binds delivery mode and target account. '
            'Only the explicitly bound delivery mode may run after approval. Examples are not factual evidence.')
        bundle['publicReadback'] = {'verified': True, 'url': job['publication']['url'],
                                   'content': bundle['article']['content'], 'images': bundle['images']}
        manifest = bundle['article'].get('generationMeta', {}).get('socialCard')
        if manifest and proof.get('socialCard') != manifest:
            raise ValueError('social_card_public_readback_missing')
        proposal = self._measured_model_call(
            job['id'], 'social', self._model_routes()['social']['requested'],
            lambda: self.models.social(bundle, job['publication']['url']))
        cards = [i for i in bundle['images'] if i.get('role') == 'social-card']
        if bundle['article'].get('generationMeta', {}).get('socialCard'):
            manifest = bundle['article']['generationMeta']['socialCard']
            if len(cards) != 1 or any(cards[0].get(k) != manifest.get(k) for k in ('url', 'sha256', 'size')) or cards[0].get('verified') is not True:
                raise ValueError('social_card_evidence_missing')
            proposal['images'] = copy.deepcopy(cards)
        elif cards:
            raise ValueError('social_card_manifest_missing')
        # The announcement receives its own prose polish and final review.
        source = proposal['text']
        polished = self._measured_model_call(
            job['id'], 'social', self._model_routes()['polish']['requested'],
            lambda: self.models.polish(source, bundle['brief']))
        if not inspect_polish(source, polished['content'])['passed']:
            raise ValueError('social_polish_changed_protected_content')
        proposal['text'] = polished['content']
        text = proposal['text'] + '\n' + proposal['replyText']
        source_text = bundle['article']['content']
        images_ok = all(i in bundle['images'] and i.get('verified') is True for i in proposal.get('images', []))
        links = re.findall(r'https?://[^\s<>]+', text)
        numbers_ok = set(re.findall(r'\d+(?:\.\d+)?', proposal['text'])) <= set(re.findall(r'\d+(?:\.\d+)?', source_text))
        url_ok = proposal.get('url') == publication['url'] and links == [publication['url']] and not re.search(r'https?://', proposal['text'])
        no_medical = self._medical({'content': text})['passed']
        weighted_length = sum(1 if ord(c) < 128 else 2 for c in proposal['text'])
        format_ok = proposal.get('platform') == 'x' and bool(proposal['text'].strip()) and weighted_length <= 280
        prohibited = [word for values in account.get('ngWords', {}).values() for word in values]
        format_ok = format_ok and not any(word in proposal['text'] for word in prohibited)
        if str(account.get('formatting', {}).get('hashtagCount', '')).startswith('0'):
            format_ok = format_ok and '#' not in proposal['text']
        flags = dict(facts=numbers_ok and job['review']['evidence']['facts'], images=images_ok,
                     affiliate=url_ok, medical=no_medical and job['review']['evidence']['medical'], render=format_ok)
        if not all(flags.values()):
            raise ValueError('social_source_image_url_or_format_failed')
        target = self.config.get('targetAccountId')
        if buffer_start is not None:
            proposal.update(deliveryMode='buffer_x', targetAccountIdX=required['xAccountId'],
                            buffer={'organizationId': required['organizationId'],
                                    'channelId': required['channelId'],
                                    'schedulingPolicy': 'next_available_slot'})
            proposal.pop('targetAccountId', None)
            proposal.pop('dueAt', None)
            proposal.pop('scheduledAt', None)
        elif target is not None:
            proposal.update(deliveryMode='auto_x', targetAccountId=target)
        else:
            if self.config.get('socialPostingEnabled') is True:
                raise ValueError('social_target_unconfigured')
            proposal['deliveryMode'] = 'manual'
            proposal.pop('targetAccountId', None)
        proposal['wisePolicy'] = policy['id']
        valid_social_mode(proposal)
        final = self._measured_model_call(
            job['id'], 'social', self._model_routes()['final_review']['requested'],
            lambda: self.models.review(
                {'article': {'content': proposal['text'] + '\n' + proposal['replyText']},
                 'source': bundle, 'proposal': proposal},
                {'reviewKind': 'social', 'evidence': flags, 'wisePolicy': policy,
                 'publicationReadback': job['publication'],
                 'independentSocialFormat': {
                     'surface': 'X announcement and URL reply, not the source article browser',
                     'platform': proposal.get('platform'), 'weightedLength': weighted_length,
                     'maxWeightedLength': 280, 'formatVerified': format_ok,
                     'imagesVerified': images_ok, 'urlBindingVerified': url_ok},
                 'sourceContent': source, 'factualSource': source_text}))
        if final.get('passed') is not True:
            raise ValueError('social_review_failed')
        review = dict(final, fingerprint=fingerprint(proposal), evidence=flags,
                      polish={'model': polished['model'], 'validated': True})
        self.ledger.record_social(job['id'], proposal, review)
        if social_feature_enabled(self.config, 'socialReviewEnabled'):
            self.deliver(job['id'], 'social')

    def _social_audit_success(self, job):
        """Read only an exact cached public-audit success or valid same-version closure."""
        publication = job.get('publication') or {}
        key = fingerprint({'id': job.get('id'), 'revision': job.get('revision'),
                           'publication': publication})
        relative = 'post-publication-audits/' + key + '.json'
        path = self.root / relative
        if path.exists() and not path.is_symlink():
            try:
                audit = json.loads(path.read_text())
                result = audit.get('result') or {}
                checks = result.get('checks')
                if (audit.get('schemaVersion') == 1
                        and audit.get('status') == 'success' and audit.get('id') == job.get('id')
                        and audit.get('revision') == job.get('revision')
                        and audit.get('auditKey') == key
                        and audit.get('publication') == publication
                        and result.get('passed') is True and result.get('status') == 'passed'
                        and result.get('issues') == [] and isinstance(checks, list) and checks
                        and all(isinstance(check, dict) and isinstance(check.get('name'), str)
                                and check['name'] and check.get('status') == 'passed'
                                for check in checks)):
                    return True
            except (OSError, ValueError):
                return False
        try:
            from record_reconciliation import project_reconciliations
            projected = project_reconciliations(self.root)
        except Exception:
            return False
        for item in projected.get('reconciledSources', []):
            if (item.get('recordType') == 'post_publication_audit'
                    and (item.get('sourceIdentity') or {}).get('path') == relative
                    and item.get('jobId') == job.get('id')
                    and item.get('revision') == job.get('revision')
                    and any(proof.get('kind') == 'same_version_audit_passed'
                            for proof in item.get('proofs', []))):
                return True
        return False

    @staticmethod
    def _valid_buffer_social_card(job):
        bundle = job.get('bundle') or {}
        article = bundle.get('article') or {}
        manifest = (article.get('generationMeta') or {}).get('socialCard')
        images = bundle.get('images')
        if not isinstance(manifest, dict) or not isinstance(images, list):
            raise ValueError('buffer_social_card_binding_invalid')
        digest = manifest.get('sha256')
        url = manifest.get('url')
        matches = [image for image in images if isinstance(image, dict)
                   and image.get('role') == 'social-card']
        try:
            parsed = urlsplit(url)
            valid = (len(matches) == 1 and re.fullmatch(r'[a-f0-9]{64}', digest or '')
                     and type(manifest.get('size')) is int and manifest['size'] > 0
                     and manifest.get('contentType') == 'image/png'
                     and manifest.get('finalUrl') == url
                     and parsed.scheme == 'https' and bool(parsed.hostname)
                     and not parsed.query and not parsed.fragment
                     and parsed.path.endswith('/' + digest[:2] + '/' + digest + '.png')
                     and matches[0].get('verified') is True
                     and all(matches[0].get(key) == manifest.get(key)
                             for key in ('url', 'sha256', 'size', 'contentType')))
        except (AttributeError, TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError('buffer_social_card_binding_invalid')
        return manifest

    def hold_social_refresh(self, id, *, expected_social_revision):
        self._require_running()
        if self.config.get('socialPostingEnabled') is not False:
            raise ValueError('social_refresh_requires_posting_hold')
        return self.ledger.hold_social_refresh(id, expected_social_revision=expected_social_revision)

    def refresh_social_images(self, id, rendered_bundle, *, expected_social_revision,
                              prior_main_readback=None, deliver=False):
        """Operator-only image refresh; no article mutation or X action. Caller holds runtime.flock."""
        self._require_running()
        job = self.ledger.get_job(id)
        old = job.get('social') or {}
        if old.get('revision') != expected_social_revision or old.get('publication'):
            raise ValueError('social_revision_conflict_or_posted')
        valid_review(old.get('review'), old['revision'])
        manifest = copy.deepcopy(rendered_bundle.get('article', {}).get('generationMeta', {}).get('socialCard'))
        if not manifest:
            raise ValueError('supplemental_manifest_required')
        expected = copy.deepcopy(job['bundle'])
        if (expected['article'].get('generationMeta') or {}).get('socialCard'):
            raise ValueError('existing_article_card_requires_separate_workflow')
        expected['article'].setdefault('generationMeta', {})['socialCard'] = manifest
        card = dict(manifest, role='social-card', verified=True)
        expected['images'].append(card)
        if expected != rendered_bundle:
            raise ValueError('supplemental_bundle_changed_article_or_sources')
        proposal = copy.deepcopy(old['proposal'])
        proposal.update(images=[card], supplementalCard=dict(articleId=id, articleRevision=job['revision'], manifest=manifest))
        if prior_main_readback is not None:
            if self.config.get('socialPostingEnabled') is not False or job['stage'] != 'social_held':
                raise ValueError('partial_social_refresh_requires_posting_hold')
            main_id = prior_main_readback.get('id', '')
            if not re.fullmatch(r'[1-9][0-9]{0,19}', main_id):
                raise ValueError('prior_main_id_invalid')
            proposal.update(approvalNotice=REFRESH_NOTICE, priorPostUrl='https://x.com/i/web/status/' + main_id)
        valid_social_mode(proposal)
        valid_social_images(job, proposal)
        # Byte readback is storage/image evidence only, never an article OG claim.
        from social_publisher import SocialPublisher
        reader = SocialPublisher(self.config, self.env, fetcher=self.catalog)
        reader._image_bytes(card)
        for source in manifest['sources']:
            image = next(i for i in job['bundle']['images'] if i.get('productId') == source['productId']
                         and i.get('sha256') == source['sha256'] and i.get('verified') is True)
            reader._image_bytes(image)
        account = json.loads((Path(self.config['repo']) / 'data/account-config.json').read_text())
        text = proposal['text'] + '\n' + proposal['replyText']
        source_text = job['bundle']['article']['content']
        weighted_length = sum(1 if ord(c) < 128 else 2 for c in proposal['text'])
        links = re.findall(r'https?://[^\s<>]+', text)
        url_ok = proposal.get('url') == job['publication']['url'] == proposal['replyText'] and links == [proposal['replyText']]
        numbers_ok = set(re.findall(r'\d+(?:\.\d+)?', proposal['text'])) <= set(re.findall(r'\d+(?:\.\d+)?', source_text))
        prohibited = [word for values in account.get('ngWords', {}).values() for word in values]
        format_ok = (proposal.get('platform') == 'x' and bool(proposal['text'].strip()) and weighted_length <= 280
                     and not any(word in proposal['text'] for word in prohibited))
        if str(account.get('formatting', {}).get('hashtagCount', '')).startswith('0'):
            format_ok = format_ok and '#' not in proposal['text']
        flags = dict(facts=numbers_ok and job['review']['evidence']['facts'], images=True, affiliate=url_ok,
                     medical=self._medical({'content': text})['passed'] and job['review']['evidence']['medical'], render=format_ok)
        if not all(flags.values()):
            raise ValueError('social_source_image_url_or_format_failed')
        policy = load_policy(self.config['repo'])
        proposal['wisePolicy'] = policy['id']
        checks = dict(reviewKind='social', wisePolicy=policy, evidence=flags, factualSource=source_text, sourceContent=proposal['text'],
                      publicationReadback={'verified': True, 'url': job['publication']['url'], 'fingerprint': job['revision']},
                      supplementalImageReadback={'verified': True, 'manifest': manifest, 'articleRevision': job['revision']},
                      independentSocialFormat={'surface': 'SNS-only supplemental card, not public article OG',
                          'weightedLength': weighted_length, 'maxWeightedLength': 280, 'formatVerified': format_ok,
                          'imagesVerified': True, 'urlBindingVerified': url_ok})
        # Never send the job, approval, request capabilities, private journal or history to a model.
        model_source = {k: copy.deepcopy(v) for k, v in job['bundle'].items()
                        if k not in ('revisionContext', 'catalogCorrectionContext')}
        final = self._measured_model_call(id, 'social_image_review',
            self._model_routes()['final_review']['requested'], lambda: self.models.review(
                {'article': {'content': text}, 'source': model_source, 'proposal': proposal}, checks))
        review = dict(final, fingerprint=fingerprint(proposal), evidence=flags, polish=copy.deepcopy(old['review']['polish']),
                      imageRefresh=dict(kind='image_only', fromRevision=old['revision'], toRevision=fingerprint(proposal), modelRerun=True),
                      polishReuse=dict(kind='unchanged_text', fromRevision=old['revision'],
                                       textHash=fingerprint(old['proposal']['text']), originalPolish=copy.deepcopy(old['review']['polish'])))
        valid_review(review, fingerprint(proposal))
        valid_image_refresh(old, proposal, review)
        result = self.ledger.refresh_social_images(id, proposal, review, expected_social_revision=expected_social_revision,
                                                   prior_main_readback=prior_main_readback)
        if deliver:
            self.deliver(id, 'social')
        return result

    def enable_social_autopost(self, id, target_id):
        self._require_running()
        if target_id != self.config.get('targetAccountId'):
            raise ValueError('social_target_mismatch')
        return self.ledger.enable_social_autopost(id, target_id)

    @staticmethod
    def _social_publication_summary(job):
        publication = (job.get('social') or {}).get('publication')
        if not publication:
            return None
        return {'verified': publication.get('verified') is True, 'at': publication.get('at'),
                'mainUrl': publication.get('mainUrl'), 'replyUrl': publication.get('replyUrl')}

    def publish_social(self, job):
        """The publisher journal owns X retries; do not globally claim a social effect."""
        self._require_running()
        if self.config.get('socialPostingEnabled') is not True:
            raise ValueError('social_posting_disabled')
        current = self.ledger.get_job(job['id'])
        social = current.get('social') or {}
        proposal = social.get('proposal') or {}
        valid_social_mode(proposal)
        if (current['stage'] != 'social_approved' or proposal.get('deliveryMode') != 'auto_x'
                or proposal.get('targetAccountId') != self.config.get('targetAccountId')
                or fingerprint(proposal) != social.get('revision')):
            raise ValueError('approved_auto_x_target_required')
        valid_review(social.get('review'), social['revision'])
        approval = social.get('approval') or {}
        if (approval.get('action') != 'approved' or approval.get('revision') != social['revision']
                or approval.get('user_id') != self.config['slack']['user_id']):
            raise ValueError('current_social_owner_approval_required')
        if self.social_publisher is None:
            from social_publisher import SocialPublisher
            self.social_publisher = SocialPublisher(self.config, self.env, fetcher=self.catalog)
        evidence = self.social_publisher.publish(current)
        if not isinstance(evidence, dict) or evidence.get('verified') is not True:
            raise ValueError('social_publication_requires_reconciliation')
        posted = self.ledger.record_social_publication(current['id'], social['revision'], evidence)
        self.notify_social_posted(posted)
        return posted

    def publish_buffer_social(self, job, *, now=None):
        """Schedule or verify one exact approved Buffer proposal; direct X stays disabled."""
        self._require_running()
        now = now or datetime.now(JST)
        if self.config.get('bufferPostingEnabled') is not True:
            raise ValueError('buffer_posting_disabled')
        if self.config.get('socialPostingEnabled') is not False:
            raise ValueError('direct_x_must_remain_disabled')
        current = self.ledger.get_job(job['id'])
        if not self._social_audit_success(current):
            raise ValueError('buffer_social_requires_successful_public_audit')
        self._valid_buffer_social_card(current)
        social = current.get('social') or {}
        proposal = social.get('proposal') or {}
        valid_social_mode(proposal)
        settings = self.config.get('buffer') or {}
        expected = {'organizationId': settings.get('organizationId'),
                    'channelId': settings.get('channelId'),
                    'schedulingPolicy': 'next_available_slot'}
        if (current.get('stage') not in ('social_approved', 'social_scheduled')
                or proposal.get('deliveryMode') != 'buffer_x'
                or proposal.get('buffer') != expected
                or proposal.get('targetAccountIdX') != settings.get('xAccountId')
                or fingerprint(proposal) != social.get('revision')):
            raise ValueError('approved_buffer_target_required')
        valid_review(social.get('review'), social['revision'])
        approval = social.get('approval') or {}
        if (approval.get('action') != 'approved' or approval.get('revision') != social['revision']
                or approval.get('user_id') != self.config['slack']['user_id']):
            raise ValueError('current_social_owner_approval_required')
        if self.buffer_publisher is None:
            buffer_env = dict(self.env)
            path = self.config.get('bufferEnvFile')
            if path:
                candidate = Path(path)
                if candidate.is_file() and not candidate.is_symlink():
                    buffer_env.update(env_file(candidate))
            from buffer_publisher import BufferPublisher
            self.buffer_publisher = BufferPublisher(self.config, buffer_env, fetcher=self.catalog)
        before = self._buffer_request_snapshot(social['revision'])
        schedule = social.get('bufferSchedule') or {}
        if (before.get('pending')
                or before.get('phase') not in (None, 'scheduled', 'verified')
                or current.get('stage') == 'social_scheduled'
                and before.get('phase') not in ('scheduled', 'verified')
                or current.get('stage') == 'social_scheduled'
                and (schedule.get('nextCheckAt') is None or schedule.get('duePolls', 0) >= 3)
                and before.get('phase') != 'verified'):
            raise ValueError('buffer_publication_requires_reconciliation')
        maximum = (settings.get('maxBufferRequestsPerPost', 18)
                   if type(settings.get('maxBufferRequestsPerPost', 18)) is int else 18)
        allowance = max(0, maximum - before['requestCount'])
        period = self.ledger.production_schedule.period_key(now)
        if period is None:
            raise ValueError('buffer_budget_period_unavailable')
        hold = (self.ledger.reserve_buffer_requests(period, allowance, now=now)
                if allowance else None)
        result = None
        caught = None
        try:
            result = self.buffer_publisher.schedule_or_check(current, now=now)
        except Exception as error:
            caught = error
        after = self._buffer_request_snapshot(social['revision'])
        actual = after['requestCount'] - before['requestCount']
        if actual < 0 or hold is None and actual:
            raise ValueError('buffer_request_budget_requires_reconciliation')
        if hold is not None:
            if actual == 0:
                self.ledger.cancel_buffer_request_reservation(hold, now=now)
            else:
                windows = after.get('rateLimits')
                if not isinstance(windows, list) or {item.get('window') for item in windows} != {
                        900, 86400, 2592000}:
                    raise ValueError('buffer_request_budget_requires_reconciliation')
                observation = {
                    'requestCount': actual, 'observedAt': now.isoformat(),
                    'rateLimitWindows': [{
                        'windowSeconds': item['window'], 'limit': item['quota'],
                        'remaining': item['remaining'],
                        'resetAt': (now + timedelta(seconds=item['resetAfter'])).isoformat(),
                    } for item in windows],
                }
                reason_text = str(caught) if caught is not None else str((result or {}).get('reason', ''))
                if reason_text in ('buffer_rate_limited', 'buffer_rate_limit_429'):
                    observation['statusCode'] = 429
                    if isinstance(after.get('retryAfter'), int):
                        observation['retryAfterSeconds'] = after['retryAfter']
                self.ledger.settle_buffer_requests(
                    hold, observation,
                    outcome='failed' if caught is not None or (result or {}).get('status') == 'unverified'
                    else 'success', now=now)
        if caught is not None:
            raise caught
        if not isinstance(result, dict):
            raise ValueError('buffer_publication_requires_reconciliation')
        if result.get('status') in ('scheduled', 'pending') and result.get('verified') is False:
            interval = settings.get('duePollIntervalSeconds', 1800)
            scheduled = self.ledger.record_buffer_social_schedule(
                current['id'], social['revision'], result, now=now,
                poll_interval_seconds=interval,
                max_due_polls=settings.get('maxDuePolls', 3))
            if result.get('status') == 'scheduled':
                self._notify_buffer_scheduled(scheduled)
            return scheduled
        if result.get('status') == 'verified' and result.get('verified') is True:
            posted = self.ledger.record_buffer_social_publication(
                current['id'], social['revision'], result)
            self.notify_social_posted(posted)
            return posted
        raise ValueError('buffer_publication_requires_reconciliation')

    def _buffer_request_snapshot(self, revision):
        marker = self.root / 'buffer-publications' / (revision + '.json')
        if not marker.exists():
            return {'requestCount': 0, 'rateLimits': [], 'retryAfter': None,
                    'phase': None, 'pending': None}
        if marker.is_symlink() or marker.stat().st_mode & 0o777 != 0o600:
            raise ValueError('buffer_request_budget_requires_reconciliation')
        try:
            state = json.loads(marker.read_text())
        except (OSError, ValueError):
            raise ValueError('buffer_request_budget_requires_reconciliation') from None
        if state.get('revision') != revision or type(state.get('bufferRequests', 0)) is not int:
            raise ValueError('buffer_request_budget_requires_reconciliation')
        return {'requestCount': state.get('bufferRequests', 0),
                'rateLimits': copy.deepcopy(state.get('sharedRateLimits', [])),
                'retryAfter': state.get('retryAfter'), 'phase': state.get('phase'),
                'pending': copy.deepcopy(state.get('pending'))}

    def _notify_buffer_scheduled(self, job):
        social = job.get('social') or {}
        schedule = social.get('bufferSchedule') or {}
        revision = social.get('revision')
        binding = {'revision': revision, 'bufferPostId': schedule.get('bufferPostId'),
                   'dueAt': schedule.get('dueAt')}
        path = self.root / 'buffer-scheduled-notices' / (str(revision) + '.json')
        if path.exists():
            saved = json.loads(path.read_text())
            if saved.get('binding') != binding:
                raise ValueError('buffer_schedule_notice_conflict')
            return saved.get('status', 'requires_reconciliation')
        due = datetime.fromisoformat(schedule['dueAt'].replace('Z', '+00:00')).astimezone(JST)
        text = ('【Buffer予約確認済み】' + job['bundle']['article']['title'] + '\n'
                + 'Bufferの次の空き枠: ' + due.strftime('%Y-%m-%d %H:%M JST'))
        marker = {'status': 'in_flight', 'at': stamp(), 'binding': binding,
                  'textHash': hashlib.sha256(text.encode('utf-8')).hexdigest()}
        atomic(path, marker)
        try:
            receipt = self.slack.notice(text)
            if not isinstance(receipt, dict) or receipt.get('verified') is not True:
                raise ValueError('buffer_schedule_notice_unknown')
            marker.update(status='verified', receipt=receipt, at=stamp())
        except Exception:
            marker.update(status='requires_reconciliation', at=stamp())
        atomic(path, marker)
        return marker['status']

    def _buffer_scheduled_notice_status(self, job):
        revision = (job.get('social') or {}).get('revision')
        path = self.root / 'buffer-scheduled-notices' / (str(revision) + '.json')
        try:
            value = json.loads(path.read_text())
        except (OSError, ValueError):
            return 'requires_reconciliation'
        return 'verified' if value.get('status') == 'verified' else 'requires_reconciliation'

    def notify_social_posted(self, job):
        self._require_running()
        publication = (job.get('social') or {}).get('publication') or {}
        if job.get('stage') != 'social_posted' or publication.get('verified') is not True:
            raise ValueError('social_posted_readback_required')
        folder = self.root / 'social-posted-notices'
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        marker = folder / (job['social']['revision'] + '.json')
        try:
            fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            saved = json.loads(marker.read_text())
            if saved.get('status') == 'verified':
                return {'status': 'already_delivered'}
            raise ValueError('social_posted_notice_requires_reconciliation')
        with os.fdopen(fd, 'w') as out:
            json.dump({'status': 'in_flight', 'at': stamp()}, out)
            out.flush()
            os.fsync(out.fileno())
        directory = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        receipt = self.slack.notice('【X投稿確認済み】' + job['bundle']['article']['title'] + '\n' +
                                    publication['mainUrl'] + '\n記事リンクの返信: ' + publication['replyUrl'])
        if not isinstance(receipt, dict) or receipt.get('verified') is not True:
            raise ValueError('social_posted_notice_requires_reconciliation')
        atomic(marker, {'status': 'verified', 'at': stamp(), 'receipt': receipt})
        return {'status': 'delivered'}

    def preflight(self):
        self._require_running()
        self.slack._call('auth.test', {})
        probe = '設営前に部品を確認します。'
        brief = dict(purpose='校正接続検査', reader='キャンプ初心者', conclusion='部品を確認する',
                     headings=[], facts=['設営前に部品を確認する'], numbers=[], links=[], requiredExpressions=[],
                     protected=[], style='ですます調', length='短文', cta='なし', format='Markdown', externalSafe=True)
        checked = self._measured_model_call('maintenance:preflight', 'preflight',
            self._model_routes()['polish']['requested'], lambda: self.models.polish(probe, brief))
        preservation = inspect_polish(probe, checked['content'])
        if preservation.get('passed') is not True:
            raise ValueError('preflight_polish_preservation_failed')
        value = dict(status='ready', slackAuthenticated=True, geminiModel=checked['model'],
                     preservation=preservation, telegramEnabled=False)
        atomic(self.root / 'preflight.json', dict(value, at=stamp()))
        return value

    def prepare_social_handoff(self, job):
        """Respect the established Gearman manual-post route; never revive old X API jobs."""
        self._require_running()
        require_current_review((job.get('social') or {}).get('proposal'),
                               (job.get('social') or {}).get('review'), self.config.get('repo'))
        if job['social']['proposal'].get('deliveryMode', 'manual') != 'manual':
            raise ValueError('automatic_social_cannot_use_manual_handoff')
        marker = self.root / 'social-outbox' / (job['social']['revision'] + '.json')
        if marker.exists():
            return
        proposal = job['social']['proposal']
        atomic(marker, {'status': 'approved_manual_post_pending', 'article_id': job['id'],
                        'revision': job['social']['revision'], 'proposal': proposal,
                        'approval': job['social']['approval'], 'at': stamp()})
        self.slack.notice('【SNS原稿承認済み・投稿待ち】' + job['bundle']['article']['title'] +
                          '\nギア男の既存運用は手動投稿です。自動投稿・予約はしていません。' +
                          '\nこのCodexアプリで記事IDを指定して投稿を依頼するか、上の原稿を利用できます。' +
                          '\n記事ID: ' + job['id'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('command', choices=('status', 'preflight', 'tick', 'produce', 'deliver', 'retry', 'approve-from-codex', 'approve-social-from-codex', 'approve-social-from-slack-message', 'report', 'enable-social-autopost', 'refresh-social-images', 'hold-social-refresh', 'request-revisions', 'produce-revisions', 'attach-catalog-correction', 'correct-candidate-theme'))
    parser.add_argument('--card-bundle')
    parser.add_argument('--prior-main-readback')
    parser.add_argument('--deliver', action='store_true')
    parser.add_argument('--target-account-id')
    parser.add_argument('--kind', choices=('weekly', 'monthly', 'editorial', 'article', 'social'))
    parser.add_argument('--id')
    parser.add_argument('--limit', type=int, default=3)
    parser.add_argument('--revision')
    parser.add_argument('--evidence-file')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    policy = execution_policy(config)
    if policy is not None and policy.suspended and args.command != 'status':
        print(json.dumps({'status': 'suspended', 'mode': 'deterministic'}))
        return
    runtime = Runtime(config)
    atexit.register(runtime._save_usage)
    with (runtime.root / 'runtime.flock').open('a') as lease:
        os.chmod(lease.name, 0o600)
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'status': 'busy'}))
            return
        if args.command == 'preflight':
            value = runtime.preflight()
        elif args.command == 'status':
            value = {'status': 'ready', 'jobs': [{k: j[k] for k in ('id', 'week', 'stage', 'revision', 'error')} for j in runtime.ledger.list_jobs()],
                     'keys': {k: bool(runtime.env.get(k)) for k in ('ANTHROPIC_API_KEY', 'GEMINI_API_KEY')}, 'telegramEnabled': False}
        elif args.command == 'correct-candidate-theme':
            if not args.id or not args.evidence_file:
                raise ValueError('article_id_and_corrected_theme_file_required')
            job = runtime.ledger.correct_candidate_theme(args.id, json.loads(Path(args.evidence_file).read_text()))
            value = {'status': job['stage'], 'articleId': job['id'], 'published': False}
        elif args.command == 'attach-catalog-correction':
            if not args.id or not args.evidence_file:
                raise ValueError('article_id_and_catalog_correction_file_required')
            job = runtime.ledger.attach_catalog_correction(args.id, json.loads(Path(args.evidence_file).read_text()))
            value = {'status': job['stage'], 'articleId': job['id'], 'published': False}
        elif args.command == 'request-revisions':
            if not args.evidence_file:
                raise ValueError('revision_specifications_file_required')
            value = runtime.request_revisions(json.loads(Path(args.evidence_file).read_text())['revisions'])
        elif args.command == 'produce-revisions':
            value = runtime._produce_requested_revision() or {'status': 'idle'}
        elif args.command == 'produce':
            value = runtime.produce(args.limit)
        elif args.command == 'retry':
            value = runtime.retry(args.id)
        elif args.command == 'deliver':
            if args.kind not in (None, 'article', 'social'):
                raise ValueError('delivery_kind_required')
            value = runtime.deliver(args.id, args.kind or 'article')
        elif args.command == 'report':
            if args.kind not in ('weekly', 'monthly', 'editorial'):
                raise ValueError('report_kind_required')
            value = runtime.reporter.send(args.kind, jobs=runtime.ledger.list_jobs(), manual=True)
        elif args.command == 'hold-social-refresh':
            if not args.id or not args.revision:
                raise ValueError('article_and_social_revision_required')
            job = runtime.hold_social_refresh(args.id, expected_social_revision=args.revision)
            value = {'status': job['stage'], 'articleId': job['id'], 'revision': job['social']['revision'], 'posted': False}
        elif args.command == 'refresh-social-images':
            if not args.id or not args.revision or not args.card_bundle:
                raise ValueError('article_social_revision_and_card_bundle_required')
            prior = json.loads(Path(args.prior_main_readback).read_text()) if args.prior_main_readback else None
            job = runtime.refresh_social_images(args.id, json.loads(Path(args.card_bundle).read_text()),
                expected_social_revision=args.revision, prior_main_readback=prior, deliver=args.deliver)
            value = {'status': job['stage'], 'articleId': job['id'], 'revision': job['social']['revision'], 'posted': False}
        elif args.command == 'enable-social-autopost':
            if not args.id or not args.target_account_id:
                raise ValueError('article_and_target_account_required')
            job = runtime.enable_social_autopost(args.id, args.target_account_id)
            value = {'status': job['stage'], 'articleId': job['id'], 'revision': job['social']['revision'], 'posted': False}
        elif args.command == 'approve-social-from-slack-message':
            if not args.evidence_file:
                raise ValueError('original_slack_owner_evidence_required')
            from slack_social_approval import approve_social_from_slack_message
            evidence = json.loads(Path(args.evidence_file).read_text())
            jobs = approve_social_from_slack_message(runtime.ledger, evidence, config['slack'])
            value = {'status': 'social_approved', 'article_ids': [j['id'] for j in jobs], 'posted': False}
        elif args.command == 'approve-social-from-codex':
            if not args.id or not args.revision or not args.evidence_file:
                raise ValueError('article_id_social_revision_and_user_message_evidence_required')
            evidence = json.loads(Path(args.evidence_file).read_text())
            job = runtime.ledger.approve_social_from_codex(args.id, args.revision, config['slack']['user_id'], evidence)
            value = {'status': job['stage'], 'article_id': job['id'], 'revision': job['social']['revision'], 'posted': False}
        elif args.command == 'approve-from-codex':
            if not args.id or not args.revision or not args.evidence_file:
                raise ValueError('article_id_revision_and_user_message_evidence_required')
            evidence = json.loads(Path(args.evidence_file).read_text())
            job = runtime.ledger.approve_from_codex(args.id, args.revision, config['slack']['user_id'], evidence)
            value = {'status': 'approved', 'article_id': job['id'], 'revision': job['revision'], 'published': False}
        else:
            value = runtime.tick()
        runtime._save_usage()
        print(json.dumps(value, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'blocked', 'reason': reason(error)}))
        sys.exit(1)
