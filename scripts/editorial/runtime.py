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

from ledger import (Ledger, canonical, fingerprint, valid_review, valid_astra_review, valid_social_mode,
                    valid_social_images, valid_image_refresh, REFRESH_NOTICE)
from models import Models
from quality import inspect_bundle, inspect_polish
from slack import Slack

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
                 analytics=None, reporter=None, social_publisher=None, social_cards=None, post_auditor=None):
        self.config = config
        self.root = Path(config['stateRoot'])
        if 'productionSchedule' in config and config['productionSchedule'] is None:
            raise ValueError('invalid productionSchedule')
        self.ledger = Ledger(self.root, config['slack']['user_id'],
                             production_schedule=config.get('productionSchedule'),
                             target_account_id=config.get('targetAccountId'))
        self.env = env_file(config['envFile'])
        # Explicit dedicated Gemini settings; keys remain in memory, never copied.
        if config.get('geminiEnvFile'):
            gemini = env_file(config['geminiEnvFile'])
            if gemini.get('GEMINI_API_KEY'):
                self.env['GEMINI_API_KEY'] = gemini['GEMINI_API_KEY']
        def save_model_artifact(artifact):
            name = hashlib.sha256(artifact['responseId'].encode('utf-8')).hexdigest() + '.json'
            atomic(self.root / 'model-artifacts' / name, artifact)
        self.models = models or Models(self.env, artifact_sink=save_model_artifact)
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
        self.post_auditor = post_auditor
        from analytics import Analytics
        from reporting import Reporter
        self.analytics = analytics or Analytics(config)
        self.reporter = reporter or Reporter(config, self.slack, env=self.env)

    def _analytics_context(self):
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
        request = {'action': action, 'bundle': job['bundle'], 'revision': job['revision'], 'approval': bound_approval}
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

    def _context(self):
        data = self.catalog.catalog()
        repo = Path(self.config['repo'])
        from revisions import TARGETS
        data['revisionArticles'] = [copy.deepcopy(a) for a in data.get('articles', []) if a.get('id') in TARGETS]
        data['articles'] = [{k: a.get(k) for k in ('id', 'slug', 'title', 'categoryId', 'productIds', 'status')}
                            for a in data.get('articles', [])]
        data['existingArticles'] = data['articles']
        data['catalog'] = data.get('products', [])
        data['queuedThemes'] = [j['theme'] for j in self.ledger.list_jobs()]
        data['editorialRules'] = '\n'.join((repo / p).read_text() for p in (
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
        return {'catalog': products, 'existingArticles': context['articles'], 'queuedThemes': context['queuedThemes'],
                'merchantClicks': [{'article': k[0], 'store': k[1], 'clicks': n} for k, n in counts.items()],
                'observation': {'start': observed_start.isoformat(), 'end': observed_end.isoformat(),
                                'metric': 'affiliate link clicks only; not purchases, revenue or seasonal trend'},
                'analytics': analytics, 'season': datetime.now(JST).strftime('%Y-%m'),
                'instructions': context['instructions'] + ' Calendar month alone is not seasonal-demand evidence. '
                    'Analytics opportunities with action=improve_existing must improve the existing URL, '
                    'not become a new duplicate article. Missing signals remain unverified.'}

    def produce(self, limit=3):
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
        context = self._context()
        if not current and len(pending) < 3:
            research_attempt = self.root / 'production-attempts' / (week + '.json')
            if research_attempt.exists():
                raise ValueError('weekly_research_requires_reconciliation')
            atomic(research_attempt, {'status': 'in_flight', 'at': stamp()})
            try:
                themes = self.models.research(self._research_context(context))['themes']
                atomic(research_attempt, {'status': 'generated', 'themes': themes, 'at': stamp()})
            finally:
                self._save_usage()
            for theme in themes[:3 - len(pending)]:
                self.ledger.create_candidate(theme, now=now)
            current = [j for j in self.ledger.list_jobs() if j.get('kind') != 'article_revision' and j['week'] == week]
        results = []
        # Pending candidates retain their slot and may resume after a week boundary.
        for job in self.ledger.list_jobs():
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
        gathered.update({'CLAUDE': context['editorialRules'], 'SKILL': (Path(self.config['repo']) / 'SKILL.md').read_text()})
        bundle = self.models.draft(job['theme'], gathered)
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
            bundle['article'].setdefault('createdAt', stamp())
            bundle['article']['updatedAt'] = stamp()
        if corrected:
            bundle['catalogCorrectionContext'] = copy.deepcopy(correction)
            from catalog_corrections import validate_bundle
            validate_bundle(job, bundle)
        if gathered.get('images'):
            bundle['images'] = gathered['images']
        bundle['affiliateConfig'] = {'amazonPartnerTag': self.env.get('AMAZON_PARTNER_TAG', '')}
        # Every acceptance binds the source bundle, then the separately generated polish candidate.
        source = copy.deepcopy(bundle)
        artifacts = self.root / 'research' / 'artifacts' / job['id'] / fingerprint(source)
        atomic(artifacts / 'source.json', {'kind': 'source', 'bundle': source})
        polished = self.models.polish(source['article']['content'], source['brief'])
        atomic(artifacts / 'candidate.json', {'kind': 'candidate', 'candidate': polished})
        preservation = inspect_polish(source['article']['content'], polished['content'])
        if preservation.get('passed') is not True:
            raise ValueError('gemini_protected_content_changed')
        bundle['article']['content'] = polished['content']
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
        final = self.models.review({k: v for k, v in bundle.items() if k not in ('revisionContext', 'catalogCorrectionContext')}, {'evidence': flags, 'structural': checks, 'source': gathered.get('evidence', {}),
                                          'approvedTheme': job['theme'],
                                          'preview': preview, 'polishPreservation': preservation,
                                          'editorialRules': context['editorialRules'],
                                          'medical': medical,
                                          'sourceContent': source['article']['content'],
                                          **({'existingArticle': public_source, 'editorialCorrectionInstructions': binding['editorialCorrectionInstructions'],
                                              'verifiedAuthorFacts': binding['verifiedAuthorFacts']} if revision else {})})
        if final.get('passed') is not True:
            raise ValueError('final_review_failed')
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
        except Exception as error:
            self.ledger.set_stage(job['id'], 'error', {'reason': reason(error), 'at': stamp()})
            atomic(marker, {'status': 'blocked', 'at': stamp(), 'reason': reason(error)})
            return {'id': job['id'], 'status': 'attention', 'reason': reason(error)}
        finally:
            self._save_usage()

    def retry(self, id):
        job = self.ledger.get_job(id)
        if job['stage'] not in ('error', 'held', 'rejected') or job.get('publication') or job.get('approval'):
            raise ValueError('job_not_retryable')
        if job.get('bundle'):
            raise ValueError('existing_draft_requires_version_reconciliation_before_retry')
        self.ledger.set_stage(id, 'draft')
        self.ledger.set_stage(id, 'candidate')
        return {'status': 'candidate', 'id': id, 'sameWeeklySlot': True}

    def research_issues(self, id):
        file = self.root / 'research' / (id + '.json')
        if not file.exists():
            return ''
        products = json.loads(file.read_text()).get('evidence', {}).get('products', [])
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
                details.append(str(p.get('productId')) + ': ' + '; '.join(parts))
        return '\n'.join(details)[:4000]

    def _save_usage(self):
        records = getattr(self.models, 'usage', [])
        if records:
            atomic(self.root / 'usage' / (secrets.token_hex(12) + '.json'), {'at': stamp(), 'calls': records, 'actualInvoiceUsd': None})
            records.clear()

    def deliver(self, id, kind='article'):
        job = self.ledger.get_job(id)
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
        spool = Path(self.config['spoolDir'])
        processed = spool / 'editorial-processed'
        processed.mkdir(mode=0o700, exist_ok=True)
        quarantine = spool / 'editorial-quarantine'
        quarantine.mkdir(mode=0o700, exist_ok=True)
        count = 0
        for path in sorted(spool.glob('*.json'))[:100]:
            if path.is_symlink() or path.stat().st_size > 16384:
                continue
            try:
                event = json.loads(path.read_text())
                if not isinstance(event, dict):
                    raise ValueError('invalid_event')
                event['card_ts'] = event.get('message_ts')
            except (ValueError, UnicodeError):
                path.rename(quarantine / (path.stem + '-' + secrets.token_hex(4) + '.json'))
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
        for job in self.ledger.list_jobs():
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
            provider = lambda request: call(command, request['snapshot'], request['prompt'],
                request['decisionSchema'], timeout=request['budget']['timeout_seconds'])
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
        decisions = self.consume()
        # Separate errors from generic attention notices, and never skip existing gates.
        try:
            audits = self._post_publication_audits()
        except Exception as error:
            audits = [self._post_audit_fault(error)]
        results = []
        for job in self.ledger.list_jobs():
            try:
                if job['stage'] == 'approved' and self.config.get('publicationEnabled'):
                    if ('catalogCorrectionContext' in job
                            and self.config.get('catalogCorrectionsPublicationEnabled') is not True):
                        results.append({'id': job['id'], 'status': 'waiting_auth',
                                        'reason': 'catalog_corrections_publication_disabled'})
                        continue
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
                    self.deliver(job['id'])
                elif job.get('kind') != 'article_revision' and job['stage'] == 'published' and not job.get('social'):
                    marker = self.root / 'social-attempts' / (job['id'] + '.json')
                    if marker.exists():
                        raise ValueError('social_generation_requires_reconciliation')
                    atomic(marker, {'status': 'in_flight', 'at': stamp()})
                    self.make_social(job)
                    atomic(marker, {'status': 'completed', 'at': stamp()})
                elif job['stage'] == 'social_review':
                    self.deliver(job['id'], 'social')
                elif job['stage'] == 'social_approved':
                    if job['social']['proposal'].get('deliveryMode', 'manual') == 'auto_x':
                        if self.config.get('socialPostingEnabled') is True:
                            self.publish_social(job)
                        else:
                            results.append({'id': job['id'], 'status': 'waiting_auth',
                                            'reason': 'social_posting_disabled'})
                    else:
                        raise ValueError('legacy_social_requires_mode_migration')
                elif job['stage'] == 'social_posted':
                    self.notify_social_posted(job)
            except Exception as error:
                results.append({'id': job['id'], 'status': 'attention', 'reason': reason(error)})
        try:
            revision_result = self._produce_requested_revision()
        except Exception as error:
            revision_result = {'status': 'attention', 'reason': reason(error)}
        if revision_result:
            results.append(revision_result)
        now = datetime.now(JST)
        manager_projection = None
        if self._manager_enabled():
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
        atomic(self.root / 'health.json', result)
        attention = [{'id': j['id'], 'title': j['theme'].get('title', j['id']), 'error': j['error']}
                     for j in jobs if j.get('error')]
        attention += [{'id': r.get('id', 'runtime'), 'title': r.get('id', '制作処理'),
                       'error': {'reason': r.get('reason', '確認が必要')}}
                      for r in results if r.get('status') == 'attention']
        if attention:
            result['status'] = 'attention'
            atomic(self.root / 'health.json', result)
            key = hashlib.sha256(canonical(attention).encode()).hexdigest()
            notified = self.root / 'attention' / (key + '.json')
            if not notified.exists():
                atomic(notified, {'status': 'in_flight', 'at': stamp()})
                try:
                    receipt = self.slack.notice('【記事制作の確認事項】\n' + '\n'.join(
                        a['title'] + '\n記事ID: ' + a['id'] + '\n理由: ' + str(a['error'].get('reason', '確認が必要')) +
                        '\n' + self.research_issues(a['id'])
                        for a in attention) + '\n未確認を合格扱いせず保留しています。詳細確認・修正依頼はこのCodexアプリでも受け付けます。')
                    atomic(notified, {'status': 'delivered', 'at': stamp(), 'receipt': receipt})
                except Exception as error:
                    atomic(notified, {'status': 'unknown', 'at': stamp(), 'reason': reason(error)})
            result['attentionDelivery'] = json.loads(notified.read_text())
            atomic(self.root / 'health.json', result)
        self._save_usage()
        return result

    def make_social(self, job):
        publication = job.get('publication') or {}
        proof = publication.get('readback') or {}
        if publication.get('verified') is not True or proof.get('verified') is not True or proof.get('fingerprint') != job['revision']:
            raise ValueError('social_publication_unverified')
        bundle = copy.deepcopy(job['bundle'])
        bundle.pop('catalogCorrectionContext', None)
        bundle.pop('revisionContext', None)
        account = json.loads((Path(self.config['repo']) / 'data/account-config.json').read_text())
        bundle['socialRules'] = {k: account[k] for k in ('tone', 'ngWords', 'linkRules', 'formatting', 'personaGuards') if k in account}
        bundle['socialRules']['approval'] = ('Separate exact-version human approval binds delivery mode and target account. '
            'Only explicitly auto_x proposals may automatically post after approval. Examples are not factual evidence.')
        bundle['publicReadback'] = {'verified': True, 'url': job['publication']['url'],
                                   'content': bundle['article']['content'], 'images': bundle['images']}
        manifest = bundle['article'].get('generationMeta', {}).get('socialCard')
        if manifest and proof.get('socialCard') != manifest:
            raise ValueError('social_card_public_readback_missing')
        proposal = self.models.social(bundle, job['publication']['url'])
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
        polished = self.models.polish(source, bundle['brief'])
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
        if target is not None:
            proposal.update(deliveryMode='auto_x', targetAccountId=target)
        else:
            if self.config.get('socialPostingEnabled') is True:
                raise ValueError('social_target_unconfigured')
            proposal['deliveryMode'] = 'manual'
            proposal.pop('targetAccountId', None)
        valid_social_mode(proposal)
        final = self.models.review({'article': {'content': proposal['text'] + '\n' + proposal['replyText']},
                                    'source': bundle, 'proposal': proposal},
                                   {'reviewKind': 'social', 'evidence': flags, 'publicationReadback': job['publication'],
                                    'independentSocialFormat': {'surface': 'X announcement and URL reply, not the source article browser',
                                        'platform': proposal.get('platform'), 'weightedLength': weighted_length,
                                        'maxWeightedLength': 280, 'formatVerified': format_ok,
                                        'imagesVerified': images_ok, 'urlBindingVerified': url_ok},
                                    'sourceContent': source, 'factualSource': source_text})
        if final.get('passed') is not True:
            raise ValueError('social_review_failed')
        review = dict(final, fingerprint=fingerprint(proposal), evidence=flags,
                      polish={'model': polished['model'], 'validated': True})
        self.ledger.record_social(job['id'], proposal, review)
        self.deliver(job['id'], 'social')

    def hold_social_refresh(self, id, *, expected_social_revision):
        if self.config.get('socialPostingEnabled') is not False:
            raise ValueError('social_refresh_requires_posting_hold')
        return self.ledger.hold_social_refresh(id, expected_social_revision=expected_social_revision)

    def refresh_social_images(self, id, rendered_bundle, *, expected_social_revision,
                              prior_main_readback=None, deliver=False):
        """Operator-only image refresh; no article mutation or X action. Caller holds runtime.flock."""
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
        checks = dict(reviewKind='social', evidence=flags, factualSource=source_text, sourceContent=proposal['text'],
                      publicationReadback={'verified': True, 'url': job['publication']['url'], 'fingerprint': job['revision']},
                      supplementalImageReadback={'verified': True, 'manifest': manifest, 'articleRevision': job['revision']},
                      independentSocialFormat={'surface': 'SNS-only supplemental card, not public article OG',
                          'weightedLength': weighted_length, 'maxWeightedLength': 280, 'formatVerified': format_ok,
                          'imagesVerified': True, 'urlBindingVerified': url_ok})
        # Never send the job, approval, request capabilities, private journal or history to a model.
        model_source = {k: copy.deepcopy(v) for k, v in job['bundle'].items()
                        if k not in ('revisionContext', 'catalogCorrectionContext')}
        final = self.models.review({'article': {'content': text}, 'source': model_source, 'proposal': proposal}, checks)
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

    def notify_social_posted(self, job):
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
        self.slack._call('auth.test', {})
        probe = '設営前に部品を確認します。'
        brief = dict(purpose='校正接続検査', reader='キャンプ初心者', conclusion='部品を確認する',
                     headings=[], facts=['設営前に部品を確認する'], numbers=[], links=[], requiredExpressions=[],
                     protected=[], style='ですます調', length='短文', cta='なし', format='Markdown', externalSafe=True)
        checked = self.models.polish(probe, brief)
        preservation = inspect_polish(probe, checked['content'])
        if preservation.get('passed') is not True:
            raise ValueError('preflight_polish_preservation_failed')
        value = dict(status='ready', slackAuthenticated=True, geminiModel=checked['model'],
                     preservation=preservation, telegramEnabled=False)
        atomic(self.root / 'preflight.json', dict(value, at=stamp()))
        return value

    def prepare_social_handoff(self, job):
        """Respect the established Gearman manual-post route; never revive old X API jobs."""
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
    parser.add_argument('command', choices=('status', 'preflight', 'tick', 'produce', 'deliver', 'retry', 'approve-from-codex', 'approve-social-from-codex', 'report', 'enable-social-autopost', 'refresh-social-images', 'hold-social-refresh', 'request-revisions', 'produce-revisions', 'attach-catalog-correction', 'correct-candidate-theme'))
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
