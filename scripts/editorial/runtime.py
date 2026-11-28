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
                    valid_social_images, valid_image_refresh, owned_article_social_image,
                    REFRESH_NOTICE)
from models import Models, ARTICLE_LENGTHS, article_review_schema
from review_scoring import VERSION as ARTICLE_SCORING_VERSION, article_applicability
from wise_contract import load_policy, require_current_review
from social_policy_compat import require_approved_social_review
from quality import inspect_bundle, inspect_polish
from materials_guide_contract import (FIELD as MATERIALS_GUIDE_FIELD,
                                     bind_materials_guide_contract)
from slack import Slack
from attention_presentation import attention_text
from dispatcher import (DeterministicDispatcher, buffer_social_eligible,
                        buffer_social_outstanding, buffer_social_start,
                        execution_policy, social_feature_enabled)
from stage_journal import StageBlocked, StageJournal, StageUnknown
from model_budget import BudgetHold, ModelBudget
from daily_metrics import collect_daily_metrics, daily_metrics_due, require_fresh_daily_metrics
from topic_selection import (bind_nonproduct_theme, collect_primary_sources, editorial_context,
                             editorial_signals, gather_nonproduct, mixed_period,
                             nonproduct_affiliate_review, reverify_bound_public_sources,
                             select_proposals, NonproductSourceHold, ResearchProposalsRejected, TOPIC_TYPES)

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


def normalize_revision_social_card(bundle):
    """Drop only a prior generated card before rebuilding revision presentation."""
    result = copy.deepcopy(bundle)
    metadata = result['article'].get('generationMeta')
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError('social_card_previous_evidence_invalid')
    manifest = (metadata or {}).get('socialCard') if isinstance(metadata, dict) else None
    cards = [image for image in result.get('images', [])
             if isinstance(image, dict) and image.get('role') == 'social-card']
    if manifest is None:
        if cards:
            raise ValueError('social_card_previous_evidence_invalid')
        return result
    result['article']['generationMeta'] = dict(metadata)
    fields = ('url', 'sha256', 'size', 'contentType')
    if (not isinstance(manifest, dict) or any(not manifest.get(field) for field in fields)
            or len(cards) != 1 or cards[0].get('verified') is not True
            or any(cards[0].get(field) != manifest[field] for field in fields)):
        raise ValueError('social_card_previous_evidence_invalid')
    result['article']['generationMeta'].pop('socialCard', None)
    result['images'].remove(cards[0])
    return result


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
    status = getattr(error, 'status', None)
    if type(status) is int and 100 <= status <= 599:
        return 'provider_http_' + str(status)
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
                 social_cards=None, post_auditor=None, clock=None):
        self.clock = clock or (lambda: datetime.now(JST))
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
        # Deterministic feedback is evidence for the next planning call, never an
        # approval or a reason to launch another manager on unchanged metrics.
        from reporting import read_snapshot
        feedback = read_snapshot(self.root / 'seo-feedback' / 'latest.json')
        if isinstance(feedback, dict) and isinstance(feedback.get('rows'), list):
            planning_rows = (feedback['planningRows']
                             if isinstance(feedback.get('planningRows'), list)
                             else feedback['rows'])
            context['priorPublicationFeedback'] = {
                'summary': feedback.get('summary'),
                'rows': [{key: row.get(key) for key in
                          ('jobId', 'revision', 'targetUrl', 'status', 'reason',
                           'workflow', 'measurement', 'sourceEvidence')}
                         for row in planning_rows[:3] if isinstance(row, dict)],
                'causalAttribution': False,
            }
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
                # The improvement export needs the selected URLs, not two full
                # copies of every topic facet and query/page candidate. Keep the
                # canonical metrics/context untouched and disclose the projection.
                evidence = copy.deepcopy(context.get('evidence') or {})
                urls = {p.get('url') for p in options}
                paths_selected = {urlsplit(url).path for url in urls if isinstance(url, str)}
                for label in ('current', 'previous'):
                    value = evidence.get(label)
                    if not isinstance(value, dict):
                        continue
                    for field in ('pages', 'candidates'):
                        value[field] = [row for row in value.get(field, []) if row.get('url') in urls]
                    demand = value.get('searchDemand')
                    if isinstance(demand, dict):
                        demand['groups'] = []
                        demand['groupProjection'] = 'omitted_from_existing_improvement_export'
                if isinstance(evidence.get('ga4'), dict):
                    evidence['ga4']['landingPages'] = [row for row in evidence['ga4'].get('landingPages', [])
                                                       if row.get('path') in paths_selected]
                queue.update(evidence=evidence, evidenceProjection='selected_improvement_urls_only',
                             canonicalEvidenceSha256=fingerprint(context.get('evidence')))
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

    def _refresh_seo_feedback(self, jobs, context, now):
        """Persist owner-readable analysis and version evidence without AI calls."""
        from seo_feedback import build_feedback
        from analytics import build_report
        from reporting import read_snapshot
        source = Path(self.config['seoStateRoot']) / 'metrics' / 'latest.json'
        metrics_snapshot = read_snapshot(source)
        projection = build_feedback(jobs, self.root, context, now,
                                    owner_id=self.config['slack']['user_id'],
                                    metrics_snapshot=metrics_snapshot)
        path = self.root / 'seo-feedback' / 'latest.json'
        prior = read_snapshot(path)
        if not prior or prior.get('semanticSha256') != projection['semanticSha256']:
            atomic(path, projection)
        report = build_report(metrics_snapshot, kind='weekly', jobs=jobs, now=now)
        current = {'schemaVersion': 1, 'collectedAt': context.get('collectedAt'),
                   'title': report['title'], 'text': report['text'],
                   'feedback': projection['summary'],
                   'feedbackSemanticSha256': projection['semanticSha256']}
        report_path = self.root / 'analytics' / 'seo' / 'latest.json'
        if read_snapshot(report_path) != current:
            atomic(report_path, current)
        return {'status': 'updated', 'summary': projection['summary'],
                'semanticSha256': projection['semanticSha256'],
                'analysisCollectedAt': context.get('collectedAt')}

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
        if action in ('publish-corrected', 'check-corrected'):
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
            error = ValueError('catalog_correction_readiness_unavailable'
                               if action == 'check-corrected' else 'publication_result_unknown')
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
            error = failure({**safe_publication_diagnostic(value.get('diagnostic')),
                             'exitCode': result.returncode})
            if value.get('error') == 'publisher_prewrite_failed' and value.get('mutationAttempted') is False:
                error = ValueError('publication_prewrite_failed')
                error.publication_prewrite = True
                error.diagnostic = safe_publication_diagnostic(value.get('diagnostic'))
            raise error
        return value

    def _catalog_correction_readiness(self, job):
        from catalog_corrections import publication_dependency_hash
        from reporting import read_snapshot
        from ledger import timestamp
        now = self.clock()
        dependency = publication_dependency_hash(job, self.ledger.list_jobs())
        path = self.root / 'catalog-correction-readiness' / (job['revision'] + '.json')
        prior = read_snapshot(path)
        if (prior and prior.get('revision') == job['revision']
                and prior.get('dependencyHash') == dependency
                and prior.get('result', {}).get('ready') is False):
            try:
                age = now - timestamp(prior.get('checkedAt'))
                if timedelta(0) <= age < timedelta(minutes=30):
                    return prior['result']
            except (TypeError, ValueError):
                pass
        result = self.publisher('check-corrected', job)
        if (not isinstance(result, dict) or type(result.get('ready')) is not bool
                or result.get('ready') is False and result.get('reason') not in
                ('affected_article_correction_required', 'correction_readiness_unavailable')):
            result = {'ready': False, 'reason': 'correction_readiness_unavailable'}
        if result['ready'] is False:
            atomic(path, {'revision': job['revision'], 'dependencyHash': dependency,
                          'checkedAt': now.isoformat(), 'result': result})
        return result

    def _notify_independent_hold(self, job, status):
        if status not in ('blocked', 'failed', 'unknown', 'budget_hold', 'stale'):
            return
        path = self.root / 'independent-review-notices' / (job['revision'] + '.json')
        if path.exists():
            return
        atomic(path, {'status': 'claimed', 'jobId': job['id'],
                      'revision': job['revision'], 'qualityStatus': status, 'at': stamp()})
        try:
            result = self.slack.notice(
                '【記事の品質確認で保留】' + job['theme'].get('title', job['id'])
                + '\n状態：' + status
                + '\n独立品質確認が完了していません。原因の詳細は実行記録との照合が必要です。'
                + '\n品質基準・予算上限は変更せず、公開前で保留します。記事とSNSの承認は別々です。')
            atomic(path, {'status': 'completed', 'jobId': job['id'],
                          'revision': job['revision'], 'qualityStatus': status, 'result': result})
        except Exception:
            # The durable claim prevents blind resend after uncertain delivery.
            pass

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
        from revisions import TARGETS, validate_context
        revision_ids = set(TARGETS)
        for job in self.ledger.list_jobs():
            if (job.get('kind') == 'article_revision' and job.get('stage') == 'candidate'
                    and (job.get('revisionContext') or {}).get('analysisBinding')):
                revision_ids.add(validate_context(job['revisionContext'])['baseArticle']['id'])
        data['revisionArticles'] = [copy.deepcopy(a) for a in data.get('articles', []) if a.get('id') in revision_ids]
        data['articles'] = [{k: a.get(k) for k in ('id', 'slug', 'title', 'categoryId', 'productIds', 'status')}
                            for a in data.get('articles', [])]
        data['existingArticles'] = data['articles']
        data['catalog'] = data.get('products', [])
        data['queuedThemes'] = [j['theme'] for j in self.ledger.list_jobs()]
        from editorial_learning import load_editorial_learnings
        data['editorialLearnings'] = load_editorial_learnings(self.root)
        policy = load_policy(repo)
        data['wisePolicy'] = policy
        data['editorialRules'] = policy['text'] + '\n\n' + '\n'.join((repo / p).read_text() for p in (
            'CLAUDE.md', 'SKILL.md', 'docs/writing-style.md', 'docs/author-gear.md'))
        data['instructions'] = ('Three distinct new articles, verified existing catalog products. '
            'Prioritize observed Rakuten opportunities, keep Amazon routes. Avoid medical, drugs, emergency '
            'and child safety advice; those require a separate physician evidence review. '
            'Every theme must include slug, title, categoryId, productIds, query and selectionReason.')
        from supplemental_topics import apparel_policy, load_batch
        manifest = load_batch(self.config.get('supplementalApparelBatchManifest'))
        data['apparelPolicy'] = apparel_policy(manifest)
        data['instructions'] += (' Apply the bound apparel policy to apparel candidates; missing '
                                 'identity, image, affiliate or Amazon evidence is a hold. '
                                 'Prioritize owner-requested autumn/winter apparel directions among '
                                 'verified eligible products; source evidence and duplication rules '
                                 'override preference.')
        return data

    @staticmethod
    def _planning_products(products, classify_topic, limit=60):
        """Keep verified apparel/brand alternatives visible within the existing input cap."""
        wear, other = {}, []
        for product in sorted(products, key=lambda item: str(item.get('id', ''))):
            apparel = (product.get('categoryId') == 'wear'
                       or bool(classify_topic(str(product.get('name', ''))).get('garments')))
            if apparel:
                brands = classify_topic(str(product.get('brand', ''))).get('brands') or []
                brand = brands[0] if brands else str(product.get('brand', '')).casefold()
                wear.setdefault(brand, []).append(product)
            else:
                other.append(product)
        apparel = []
        while any(wear.values()):
            for brand in sorted(wear):
                if wear[brand]:
                    apparel.append(wear[brand].pop(0))
        first = apparel[:limit // 2] + other[:limit // 2]
        seen = {product['id'] for product in first}
        return (first + [product for product in apparel + other if product['id'] not in seen])[:limit]

    def _research_context(self, context, feed=None, existing_summaries=None):
        from catalog import _model, MAKERS
        from supplemental_topics import apparel_policy, load_batch
        eligible = [p for p in context['products'] if _model(p) and p.get('brand', '').casefold() in MAKERS
                    and p.get('imageUrl') and p.get('affiliateUrl') and p.get('amazonUrl')]
        if feed is not None:
            from search_demand import classify_topic
            planning_products = self._planning_products(eligible, classify_topic)
        else:
            planning_products = eligible[:60]
        products = [{k: p.get(k) for k in ('id', 'name', 'brand', 'categoryId', 'specs')} for p in planning_products]
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
        owner_apparel_policy = context.get('apparelPolicy') or apparel_policy(
            load_batch(self.config.get('supplementalApparelBatchManifest')))
        result = {'wisePolicy': load_policy(self.config['repo']), 'apparelPolicy': owner_apparel_policy,
                'catalog': products, 'existingArticles': (existing_summaries if existing_summaries is not None else context['articles']),
                'categories': [{key: item.get(key) for key in ('id', 'name')}
                               for item in context.get('categories', [])
                               if isinstance(item, dict) and item.get('id')],
                'queuedThemes': context['queuedThemes'],
                'merchantClicks': [{'article': k[0], 'store': k[1], 'clicks': n} for k, n in counts.items()],
                'observation': {'start': observed_start.isoformat(), 'end': observed_end.isoformat(),
                                'metric': 'affiliate link clicks only; not purchases, revenue or seasonal trend'},
                'analytics': analytics, 'season': datetime.now(JST).strftime('%Y-%m'),
                'instructions': context['instructions'] + ' Calendar month alone is not seasonal-demand evidence. '
                    'Analytics opportunities with action=improve_existing must improve the existing URL, '
                    'not become a new duplicate article. Missing signals remain unverified.'}
        if feed is not None:
            result['instructions'] = ('Propose at most nine mixed editorial candidates across product, '
                'seasonal_problem and knowhow. Product topics require verified catalog products; the other '
                'genres may use products only when needed and otherwise require verified public references. '
                'For every candidate provide reader question, intent, outline, priority, source IDs, '
                'selection rationale and structured overlap action. Existing article summaries contain '
                'title/slug/known query/excerpt/headings only. Deterministic code checks the complete article '
                'index. Avoid medical, survival, emergency and child-safety advice. Ordinary seasonal '
                'clothing comfort and product choice may be covered within verified factual sources. ')
            result['editorialSignals'] = editorial_signals(analytics, feed)
            # Demand details are provided once under their selectable evidence IDs.
            # Previous-only groups are not eligible current demand and never imply zero.
            result['analytics'] = copy.deepcopy(analytics)
            for name in ('current', 'previous'):
                source = result['analytics'].get('evidence', {}).get(name)
                if isinstance(source, dict) and isinstance(source.get('searchDemand'), dict):
                    demand = source['searchDemand']
                    groups = demand.pop('groups', [])
                    demand.update(groupCount=len(groups) if isinstance(groups, list) else None, groupDetails='editorialSignals',
                                  omittedPreviousGroups='unknown_not_zero')
            result['publicSources'] = copy.deepcopy(feed.get('sources', []))
            result['externalTrend'] = {'status': 'unconnected', 'records': [],
                                       'limitations': 'No external trend inference or Google Trends claim'}
            result['instructions'] += ('Own-site GSC/GA4 signals are not market demand; '
                'seasonal_problem is a hypothesis unless an explicit measured comparison evidence ID is supplied. '
                'Prioritize the owner-requested seasonal problems, apparel choices and meaningful brand comparisons '
                'when relevant search evidence supports them. Cite topic-matching search demand IDs; an unrelated '
                'high-traffic page is not evidence. Explain a distinct reader decision and usable conclusion, '
                'not just an available source. Route small component-care, isolated label checks and parts lookup '
                'to an appropriate existing article section/FAQ with proposedAction=existing_update; if a suitable '
                'target is unknown, hold instead of inventing a target or stretching the topic. '
                'Do not propose a new article whose reader decision is already covered by an existing section or FAQ. '
                'Programmatic verified demand and distinctness outrank your ordinal priority; no genre quota. '
                'Missing market search volume and external trends remain unknown.')
            result['topicSelectionPolicy'] = {
                'version': 'relevant-search-demand-v2', 'maxNewArticles': 3,
                'preference': ['seasonal_problem', 'apparel_choice', 'brand_comparison'],
                'narrowTopicRoute': 'existing_update_or_hold',
                'rawSearchQueriesProvided': False, 'extraResearchCalls': 0,
            }
            result['catalogCoverage'] = {'eligibleProducts': len(eligible), 'providedProducts': len(products),
                'maxProvidedProducts': 60, 'truncated': len(eligible) > len(products),
                'policy': 'bounded_apparel_brand_coverage_not_an_article_quota'}
            apparel_products = [product for product in planning_products if product.get('categoryId') == 'wear'
                                or classify_topic(str(product.get('name', ''))).get('garments')]
            apparel_brands = sorted({brand for product in apparel_products for brand in
                (classify_topic(str(product.get('brand', ''))).get('brands')
                 or [str(product.get('brand', '')).casefold()])})
            result['catalogCoverage'].update(providedApparelProducts=len(apparel_products),
                providedApparelBrands=apparel_brands,
                brandComparisonReadiness=('multiple_catalog_brands_available' if len(apparel_brands) >= 2
                                         else 'insufficient_apparel_brand_coverage'),
                qualification='planning_inventory_only_final_primary_image_and_merchant_checks_still_required')
        return result

    @staticmethod
    def _apparel_variant_disclosures(gathered):
        products = {product.get('id'):product.get('name') for product in gathered.get('products',[])
                    if isinstance(product,dict)}
        labels = {'rakuten':'楽天市場','amazon':'Amazon'}
        disclosures = []
        for evidence in (gathered.get('evidence') or {}).get('products',[]):
            if not isinstance(evidence,dict): continue
            states = {}
            for destination in evidence.get('destinations',[]):
                binding = destination.get('apparelBinding') if isinstance(destination,dict) else None
                channel = destination.get('channel') if isinstance(destination,dict) else None
                state = binding.get('merchantOptionState') if isinstance(binding,dict) else None
                if channel in labels and state in ('fixed','selectable'):
                    states[channel] = state
            if set(states.values()) != {'fixed','selectable'}:
                continue
            details = '、'.join(labels[channel]+'は'+('カラー・サイズ選択式' if state == 'selectable'
                                  else '初期選択で確認したバリエーション')
                               for channel,state in sorted(states.items()))
            name = products.get(evidence.get('productId')) or evidence.get('productId') or '対象商品'
            disclosures.append(f'{name}について、この記事のリンク先で確認した選択内容は販売先で異なります。{details}です。'
                               'これは各販売先の全選択肢を示すものではありません。購入画面でカラー・サイズと選択肢を確認してください。')
        return list(dict.fromkeys(disclosures))

    def produce(self, limit=3):
        from regular_backfill import backfill, load_selection, pending as is_pending
        self._require_running()
        if not self.config.get('generationEnabled'):
            return {'status': 'disabled'}
        now = datetime.now(JST)
        week = self.ledger.production_schedule.period_key(now)
        if week is None:
            return {'status': 'idle', 'articles': []}
        current = [j for j in self.ledger.list_jobs() if j.get('kind') not in
                   ('article_revision', 'supplemental_article') and j['week'] == week]
        pending = [j for j in self.ledger.list_jobs() if is_pending(j)]
        candidates = any(j.get('kind') not in ('article_revision', 'supplemental_article')
                         and j['stage'] == 'candidate' for j in pending)
        if not candidates and (len(current) >= 3 or len(pending) >= 3):
            return {'status': 'idle', 'articles': []}
        saved_themes = load_selection(self.root, week)
        if current and saved_themes is None and not candidates:
            return {'status': 'idle', 'articles': []}
        new_research = not current and saved_themes is None and len(pending) < 3
        if new_research and self.config.get('dailyMetricsEnabled') is True and not daily_metrics_due(now):
            # Before the collector's normal start, wait for fresh research inputs.
            # Candidates selected previously can still proceed.
            if not candidates:
                return {'status': 'waiting', 'reason': 'daily_metrics_not_due', 'articles': []}
            new_research = False
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
            research_repair = None
            research_repair_kind = None
            if research_attempt.exists():
                try:
                    prior_attempt = json.loads(research_attempt.read_text())
                except (OSError, ValueError):
                    prior_attempt = None
                if isinstance(prior_attempt, dict) and prior_attempt.get('status') == 'budget_hold':
                    return {'status': 'blocked', 'reason': 'model_budget_hold', 'articles': [],
                            'retryable': prior_attempt.get('retryable') is True}
                if isinstance(prior_attempt, dict) and prior_attempt.get('status') == 'research_contract_rejected':
                    return {'status': 'blocked', 'reason': 'research_contract_rejected',
                            'articles': [], 'retryable': False}
                if isinstance(prior_attempt, dict) and prior_attempt.get('status') == 'selection_hold':
                    return {'status': 'blocked', 'reason': prior_attempt.get('holdReason'),
                            'articles': [], 'eligibleCount': prior_attempt.get('eligibleCount'),
                            'unfilled': prior_attempt.get('unfilled')}
                if (isinstance(prior_attempt, dict)
                        and prior_attempt.get('status') == 'budget_hold_after_request'):
                    return {'status': 'blocked', 'reason': 'weekly_research_requires_reconciliation',
                            'articles': [], 'retryable': False}
                if isinstance(prior_attempt, dict) and prior_attempt.get('status') == 'retry_ready':
                    if prior_attempt.get('researchResponseRecoveryKey'):
                        from research_response_recovery import consume
                        research_repair = consume(self, week, prior_attempt)
                        research_repair_kind = 'response'
                    else:
                        from research_contract_recovery import consume
                        research_repair = consume(self, week, prior_attempt)
                        research_repair_kind = 'legacy_contract'
                else:
                    raise ValueError('weekly_research_requires_reconciliation')
            atomic(research_attempt, {'status': 'in_flight', 'at': stamp()})
            try:
                if mixed_period(week):
                    raw_articles = self.catalog.catalog().get('articles', [])
                    from topic_index import build_article_index, compact_article_summaries
                    existing_index = build_article_index(raw_articles)
                    feed = collect_primary_sources(
                        self.catalog.request, period=week,
                        output_path=self.root / 'public-sources' / (week + '.json'), now=now)
                    research_context = self._research_context(
                        context, feed=feed, existing_summaries=compact_article_summaries(existing_index))
                    # Preserve the exact, secret-checked context before the API
                    # boundary; a later repair must not erase the first input.
                    public_checker = self.models if isinstance(self.models, Models) else Models(self.env)
                    public_checker._safe_public(research_context)
                    snapshot = self.root / 'research-contexts' / (week + '.json')
                    if snapshot.exists():
                        prior_context = json.loads(snapshot.read_text())
                        public_checker._safe_public(prior_context)
                        atomic(snapshot.with_name(week + '-' + fingerprint(prior_context) + '.json'), prior_context)
                    atomic(snapshot, research_context)
                    research_result = self._measured_model_call(
                        'research:' + week, 'research', 'claude-sonnet-4-6',
                        (lambda: self.models.research_mixed(research_context,
                            repair_feedback=research_repair['feedback']))
                        if research_repair_kind == 'response'
                        else (lambda: self.models.research_mixed(research_context)))
                    proposals = research_result['proposals']
                    research_metadata = {key: copy.deepcopy(research_result[key]) for key in
                        ('contractRejections', 'rawProposalCount', 'responseId') if key in research_result}
                    research_metadata['researchContextSha256'] = fingerprint(research_context)
                    selection = select_proposals(
                        proposals, signals=research_context['editorialSignals'],
                        existing=existing_index, queued=context['queuedThemes'],
                        feed=feed, limit=3)
                    themes = [bind_nonproduct_theme(theme, feed) for theme in selection['selected']]
                    genre_coverage = {}
                    qualified_reasons = {'deterministic_priority_with_soft_variety',
                                         'deterministic_relevant_need_rank',
                                         'insufficient_qualified_period_pool', 'period_selection_limit'}
                    for genre in sorted(TOPIC_TYPES):
                        rows = [decision for decision in selection['decisions']
                                if decision['proposal']['topicType'] == genre]
                        qualified = sum(decision['status'] == 'selected'
                                        or decision['reason'] in qualified_reasons for decision in rows)
                        genre_coverage[genre] = {'proposals': len(rows), 'qualified': qualified,
                            'selected': sum(decision['status'] == 'selected' for decision in rows),
                            'rejectionReasons': sorted({decision['reason'] for decision in rows
                                                       if decision['status'] != 'selected'}),
                            'unavailableReason': ('no_proposal' if not rows else
                                'no_qualified_evidence' if not qualified else None)}
                    receipt = {'schemaVersion': 1, 'period': week, 'at': stamp(),
                               'selectionPolicy': 'relevant-search-demand-v2',
                               'existingIndex': {'articleCount': len(existing_index),
                                   'fingerprint': fingerprint(existing_index),
                                   'fullBodyCount': sum(row['bodyCoverage'] == 'full' for row in existing_index),
                                   'modelProjection': 'bounded_summaries_only'},
                               'status': selection['status'], 'holdReason': selection['holdReason'],
                               'eligibleCount': selection['eligibleCount'], 'unfilled': selection['unfilled'],
                               'proposalCount': len(proposals), 'decisions': selection['decisions'],
                               'selectedSlugs': [theme['slug'] for theme in themes],
                               'sourceIds': [signal['id'] for signal in research_context['editorialSignals']],
                               'genreCoverage': genre_coverage, **research_metadata}
                    atomic(self.root / 'period-receipts' / (week + '.json'), receipt)
                    updates = [decision for decision in selection['decisions']
                               if decision['status'] == 'existing_update']
                    indexed = {row['id']: row for row in existing_index}
                    updates = [{**decision, 'baseArticleBinding': {
                        key: indexed[decision['existingArticleId']].get(key) for key in
                        ('id', 'slug', 'updatedAt', 'contentSha256', 'faqsSha256')},
                        'nextStep': 'prepare_existing_revision_with_fresh_sources_and_separate_owner_approval'}
                        for decision in updates if decision.get('existingArticleId') in indexed]
                    atomic(self.root / 'existing-update-proposals' / (week + '.json'),
                           {'schemaVersion': 1, 'period': week, 'private': True,
                            'selectionPolicy': 'relevant-search-demand-v2',
                            'status': 'awaiting_existing_update_planning' if updates else 'no_update_proposals',
                            'publication': 'prohibited', 'proposals': updates})
                    atomic(research_attempt, {
                        'status': ('selection_hold' if selection['status'] == 'hold' else 'generated'),
                        'period': week, 'themes': themes,
                        'proposals': proposals, 'selection': selection['status'],
                        'holdReason': selection['holdReason'],
                        'eligibleCount': selection['eligibleCount'],
                        'unfilled': selection['unfilled'], 'at': stamp(), **research_metadata})
                else:
                    themes = self._measured_model_call(
                        'research:' + week, 'research', 'claude-sonnet-4-6',
                        lambda: self.models.research(self._research_context(context)))['themes']
                    atomic(research_attempt, {'status': 'generated', 'period': week,
                                              'themes': themes, 'at': stamp()})
            except BudgetHold as hold:
                requested = self.model_budget.has_request_reservation(
                    hold.article_id, hold.stage, hold.period_key)
                if research_repair:
                    with self.ledger._tx() as db:
                        requested = db.execute('SELECT count(*) FROM model_budget_reservations '
                            'WHERE article_id=? AND stage=? AND period_key=?',
                            ('research:' + week, 'research', week)).fetchone()[0] > 1
                    atomic(research_attempt, {'status': 'repair_held', 'period': week,
                        'reason': 'model_budget_hold', 'retryable': False,
                        'requestMayHaveOccurred': requested})
                    return {'status': 'blocked', 'reason': 'weekly_research_requires_reconciliation',
                            'articles': [], 'retryable': False}
                atomic(research_attempt, {
                    'status': 'budget_hold_after_request' if requested else 'budget_hold', 'at': stamp(),
                    'reason': hold.reason_code, 'budgetScope': hold.budget_scope,
                    'stage': hold.stage, 'eventId': hold.event_id,
                    'retryable': not requested, 'transportReservation': requested,
                    'requestMayHaveOccurred': requested,
                    'requestOccurred': None if requested else False})
                return {'status': 'blocked',
                        'reason': ('weekly_research_requires_reconciliation' if requested
                                   else 'model_budget_hold'),
                        'articles': [], 'retryable': not requested}
            except Exception as error:
                if isinstance(error, ResearchProposalsRejected) and not research_repair:
                    rejected_marker = {'status': 'research_contract_rejected', 'period': week,
                        'at': stamp(), 'reason': str(error), 'retryable': False,
                        'requestOccurred': True, 'responseId': error.response_id,
                        'rawProposalCount': error.count, 'contractRejections': error.rejections,
                        'researchContextSha256': fingerprint(research_context)}
                    atomic(research_attempt, rejected_marker)
                    if self.config.get('researchResponseRecoveryEnabled') is True:
                        from research_response_recovery import arm_runtime
                        arm_runtime(self, week, rejected_marker, now=now)
                        return {'status': 'blocked', 'reason': 'research_contract_repair_ready',
                                'articles': [], 'retryable': True}
                    return {'status': 'blocked', 'reason': 'research_contract_rejected',
                            'articles': [], 'retryable': False}
                if isinstance(error, ResearchProposalsRejected) and research_repair_kind == 'response':
                    atomic(research_attempt, {'status': 'repair_held', 'period': week,
                        'failureType': type(error).__name__, 'reason': 'proposal_contract',
                        'retryable': False, 'requestOccurred': True,
                        'responseId': error.response_id, 'rawProposalCount': error.count,
                        'contractRejections': error.rejections})
                    return {'status': 'blocked', 'reason': 'research_contract_repair_exhausted',
                            'articles': [], 'retryable': False}
                if research_repair:
                    atomic(research_attempt, {'status': 'repair_held', 'period': week,
                        'failureType': type(error).__name__,
                        'reason': 'proposal_contract' if str(error) == 'proposal_contract' else type(error).__name__,
                        'retryable': False})
                raise
            finally:
                try:
                    self._save_usage()
                finally:
                    if research_repair:
                        if research_repair_kind == 'response':
                            from research_response_recovery import finish
                            finish(self, json.loads(research_attempt.read_text()), week)
                        else:
                            from research_contract_recovery import finish
                            finish(self, json.loads(research_attempt.read_text()))
            if mixed_period(week) and selection['status'] == 'hold':
                return {'status': 'blocked', 'reason': selection['holdReason'], 'articles': [],
                        'eligibleCount': selection['eligibleCount'], 'unfilled': selection['unfilled']}
            saved_themes = themes
        if saved_themes is not None:
            backfill(self.ledger, week, saved_themes, now)
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
            if job.get('kind') in ('article_revision', 'supplemental_article') or job['stage'] not in ('candidate',) or len(results) >= limit:
                continue
            try:
                delivery = self._make_article(job, context)
                status = ('awaiting_astra_review' if 'catalogCorrectionContext' in job
                          and isinstance(delivery, dict) and delivery.get('status') == 'awaiting_astra_review'
                          else 'awaiting_approval')
                results.append({'id': job['id'], 'status': status})
            except Exception as error:
                self.ledger.set_stage(job['id'],
                    'held' if isinstance(error, NonproductSourceHold) else 'error',
                    {'reason': reason(error), 'at': stamp()})
                results.append({'id': job['id'], 'status': 'blocked', 'reason': reason(error)})
            finally:
                self._save_usage()
        return {'status': 'completed', 'articles': results}

    def _supplemental_manifest(self):
        from supplemental_topics import load_batch
        from supplemental_reselection import effective_manifest
        return effective_manifest(self.ledger, load_batch(self.config.get('supplementalApparelBatchManifest')))

    def supplemental_due(self, now):
        if self.config.get('supplementalApparelEnabled') is not True:
            return False
        manifest = self._supplemental_manifest()
        not_before = datetime.fromisoformat(manifest['notBefore'])
        active = self.ledger.active_supplemental_jobs(manifest['batchId'])
        complete = len(active) >= manifest['maxArticles']
        if now.astimezone(JST) < not_before or complete:
            return False
        candidates = any(job.get('kind') == 'supplemental_article'
                         and job.get('batchId') == manifest['batchId']
                         and job.get('stage') == 'candidate' for job in active)
        if candidates:
            return True
        marker = self.root / 'supplemental-batches' / (manifest['batchId'] + '.json')
        try:
            saved = json.loads(marker.read_text())
            due = datetime.fromisoformat(saved['nextSourceCheckAt'])
            from supplemental_topics import batch_fingerprint
            if (saved.get('manifestFingerprint') == batch_fingerprint(manifest)
                    and due.tzinfo is not None and now.astimezone(JST) < due.astimezone(JST)):
                return False
        except (OSError, KeyError, TypeError, ValueError):
            pass
        return True

    def _supplemental_health(self, now):
        if self.config.get('supplementalApparelEnabled') is not True:
            return {'status': 'disabled'}
        manifest = self._supplemental_manifest()
        not_before = datetime.fromisoformat(manifest['notBefore'])
        ids = [job['id'] for job in self.ledger.list_jobs()
               if job.get('kind') == 'supplemental_article'
               and job.get('batchId') == manifest['batchId']]
        calls = 0
        if ids:
            with sqlite3.connect(self.ledger.db_path) as db:
                calls = db.execute('SELECT count(*) FROM model_budget_reservations WHERE article_id IN ('
                                   + ','.join('?' for _ in ids) + ')', ids).fetchone()[0]
        base = {'batchId': manifest['batchId'], 'notBefore': manifest['notBefore'],
                'maxArticles': manifest['maxArticles'], 'batchCallCap': manifest['batchCallCap'],
                'modelCallsUsed': int(calls),
                'modelCallsRemaining': manifest['batchCallCap'] - int(calls)}
        if now.astimezone(JST) < not_before:
            return dict(base, status='awaiting_start', ready=0, held=3)
        marker = self.root / 'supplemental-batches' / (manifest['batchId'] + '.json')
        try:
            value = json.loads(marker.read_text())
            slots = value.get('slots') if isinstance(value.get('slots'), list) else []
            return dict(base, status=value.get('status', 'source_hold'),
                        ready=sum(slot.get('status') == 'ready' for slot in slots),
                        held=sum(slot.get('status') != 'ready' for slot in slots),
                        nextSourceCheckAt=value.get('nextSourceCheckAt'),
                        sourceStateFingerprint=value.get('sourceStateFingerprint'))
        except (OSError, ValueError, TypeError):
            return dict(base, status='awaiting_source_check', ready=0, held=3)

    def produce_supplemental(self, limit=1, job_id=None, now=None):
        """Resolve and progress at most one independently verified supplemental slot."""
        self._require_running()
        if (self.config.get('generationEnabled') is not True
                or self.config.get('supplementalApparelEnabled') is not True):
            return {'status': 'disabled', 'articles': []}
        now = now or datetime.now(JST)
        manifest = self._supplemental_manifest()
        not_before = datetime.fromisoformat(manifest['notBefore'])
        if now.astimezone(JST) < not_before:
            return {'status': 'not_due', 'articles': []}
        config = self.model_budget.config
        if config['article']['calls'] > 32 or config['period']['calls'] > 128:
            raise ValueError('supplemental_model_budget_bounds_required')
        marker_path = self.root / 'supplemental-batches' / (manifest['batchId'] + '.json')
        prior = None
        try:
            prior = json.loads(marker_path.read_text())
        except (OSError, ValueError):
            pass
        context = self._context()
        from supplemental_topics import resolve_batch
        jobs = self.ledger.list_jobs()
        other_themes = [job['theme'] for job in jobs
                        if (job.get('kind') != 'supplemental_article'
                            or job.get('batchId') != manifest['batchId'])]
        resolved = resolve_batch(manifest, context, other_themes, now)
        active = self.ledger.active_supplemental_jobs(manifest['batchId'], jobs)
        bound = {job.get('batchSlot'): job for job in active}
        state = {'schemaVersion': 1, 'batchId': manifest['batchId'],
                 'manifestFingerprint': resolved['manifestFingerprint'],
                 'sourceStateFingerprint': resolved['stateFingerprint'],
                 'status': resolved['status'], 'batchCallCap': manifest['batchCallCap'],
                 'slots': [{key: slot.get(key) for key in
                            ('slot', 'status', 'reason', 'sourceBinding')}
                           for slot in resolved['slots']],
                 'articleIds': {str(slot): job['id'] for slot, job in bound.items()},
                 'observedAt': now.astimezone(JST).isoformat(),
                 'nextSourceCheckAt': (now.astimezone(JST) + timedelta(hours=1)).isoformat(),
                 'notification': prior.get('notification') if isinstance(prior, dict) else None}
        changed = (not isinstance(prior, dict)
                   or prior.get('manifestFingerprint') != resolved['manifestFingerprint']
                   or prior.get('sourceStateFingerprint') != resolved['stateFingerprint'])
        if changed:
            labels = {'catalog_product_not_verified':'商品情報の確認待ち',
                      'missing_required_destination':'購入先の確認待ち',
                      'apparel_identity_invalid':'商品仕様の確認待ち',
                      'duplicate_theme':'既存記事との重複確認待ち',
                      'category_mismatch':'掲載分類の確認待ち',
                      'theme_not_registered':'記事企画の確認待ち'}
            missing = [f'{slot["slot"]}枠目: '+labels.get(slot.get('reason'),'確認待ち')
                       for slot in resolved['slots'] if slot['status'] != 'ready']
            try:
                from usage_cost_report import usage_cost_summary
                period = self.ledger.production_schedule.period_key(now)
                cost = usage_cost_summary(self.root,self.config,kind='production',
                    period_key=period,now=now,article_ids=sorted(job['id'] for job in jobs
                        if job.get('kind') == 'supplemental_article' and job.get('batchId') == manifest['batchId']),
                    batch_call_cap=manifest['batchCallCap'],article_since=manifest['notBefore'])
            except Exception:
                cost = '追加batchの使用量・費用・予算残量: 未取得'
            text = ('【追加ウェア記事・参照状態】\n準備済み: '
                    + str(resolved['readyCount'])+'/3\n保留: '+(', '.join(missing) or 'なし')
                    +'\n確認済み事実: 上記の情報・購入先・画像証跡が未確認の枠だけ停止しています。'
                    +'\n原因判断: 未確認証跡による停止は確定、証跡が揃わない根本原因は未確定です。'
                    +'\n次の対応: 未確認の商品情報・購入先・画像を確認し、確認済みの枠だけ順次進めます。'
                    +'\n品質基準・予算上限・本人承認条件は変更しません。\n\n'+cost)
            state['notification'] = {'status': 'in_flight', 'stateFingerprint': resolved['stateFingerprint']}
            atomic(marker_path, state)
            try:
                receipt = self.slack.notice(text)
                state['notification'] = {'status': 'delivered',
                    'stateFingerprint': resolved['stateFingerprint'], 'receipt': receipt}
            except Exception:
                state['notification'] = {'status': 'unknown',
                    'stateFingerprint': resolved['stateFingerprint']}
            atomic(marker_path, state)
        else:
            atomic(marker_path, state)
        # Existing jobs resume first; a new slot is created only when the global cap permits it.
        retry = getattr(self, '_explicit_stage_retry', None)
        corrected_id = (retry['jobId'] if retry and retry.get('corrected')
                        and retry['jobId'] == job_id else None)
        candidates = [job for job in active if job.get('kind') == 'supplemental_article'
                      and job.get('batchId') == manifest['batchId']
                      and (job['stage'] == 'candidate'
                           or (job['id'] == corrected_id and job['stage'] == 'error'))]
        if job_id:
            candidates = [job for job in candidates if job['id'] == job_id]
        if not candidates and not job_id:
            pending = [job for job in jobs if job.get('kind') != 'article_revision'
                       and not job.get('publication') and job['stage'] != 'rejected']
            if len(pending) < 3:
                ready = next((slot for slot in resolved['slots']
                              if slot['status'] == 'ready' and slot['slot'] not in bound), None)
                if ready:
                    candidates = [self.ledger.create_supplemental_candidate(
                        ready['theme'], manifest['batchId'], ready['slot'], ready['sourceBinding'],
                        social_eligible_period=manifest['socialEligiblePeriod'], now=now)]
                    state['articleIds'][str(ready['slot'])] = candidates[0]['id']
                    atomic(marker_path, state)
        results = []
        for job in candidates[:min(limit, 1)]:
            current = next((slot for slot in resolved['slots']
                            if slot['slot'] == job['batchSlot']), None)
            if (not current or current['status'] != 'ready'
                    or current['sourceBinding'] != job['sourceBinding']
                    or (job['id'] == corrected_id and current['theme'] != job['theme'])):
                results.append({'id': job['id'], 'status': 'source_hold'})
                continue
            try:
                self._make_article(job, context)
                results.append({'id': job['id'], 'status': 'awaiting_approval'})
            except Exception as error:
                self.ledger.set_stage(job['id'], 'error', {'reason': reason(error), 'at': stamp()})
                results.append({'id': job['id'], 'status': 'blocked', 'reason': reason(error)})
            finally:
                self._save_usage()
        return {'status': 'completed' if results else resolved['status'], 'articles': results,
                'batchId': manifest['batchId']}

    def _make_article(self, job, context):
        self._require_running()
        self.ledger.assert_not_owner_held(job['id'])
        context = self._wise_context(context)
        revision = job.get('kind') == 'article_revision'
        corrected = 'catalogCorrectionContext' in job
        nonproduct = (not revision and not corrected and job.get('theme', {}).get('productIds') == []
                      and mixed_period(job.get('week')))
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
            if binding.get('analysisBinding') is not None:
                from existing_update_preparation import public_revision_reference
                reference = public_revision_reference(base)
                checker = self.models if isinstance(self.models, Models) else Models(self.env)
                checker._safe_public(reference)
                if self._medical(base).get('passed') is not True:
                    raise ValueError('routine_public_reference_requires_upper_editor')
                gathered['publicRevisionReference'] = reference
                intent = binding['analysisBinding']['metricsReceipt']['intentEvidence']
                if intent.get('status') == 'observed_sample':
                    gathered['analysisIntentObservation'] = copy.deepcopy(intent)
        elif nonproduct:
            gathered = gather_nonproduct(job['theme'], context)
            source_recheck = reverify_bound_public_sources(
                self.catalog.request, gathered['references'])
            atomic(self.root / 'source-rechecks' / job['id'] /
                   (job['theme']['nonProductContract']['sourceReceiptSha256'] + '.json'),
                   {'jobId': job['id'], 'sourceReceiptSha256':
                    job['theme']['nonProductContract']['sourceReceiptSha256'], **source_recheck})
            if self.social_cards is None:
                from social_cards import SocialCards
                self.social_cards = SocialCards(self.config, self.env, self.catalog)
            contract = job['theme']['nonProductContract']
            image = self.social_cards.build_editorial_illustration(
                job['theme'], gathered['references'], contract['sourceReceiptSha256'])
            gathered['images'] = [image]
            gathered['checks']['images'] = True
            gathered['evidence']['ownedIllustrations'] = [image]
        else:
            gathered = self.catalog.gather(job['theme'], context)
        gathered['editorialLearnings'] = copy.deepcopy(context.get('editorialLearnings', []))
        variant_disclosures = self._apparel_variant_disclosures(gathered)
        if variant_disclosures:
            gathered['apparelApprovalDisclosure'] = {
                'requiredExpressions':variant_disclosures,
                'rule':'merchant option states differ; never claim identical color or size'}
        atomic(self.root / 'research' / (job['id'] + '.json'), gathered)
        source_ready = (gathered.get('checks', {}).get('facts') is True
                        and gathered.get('checks', {}).get('images') is True
                        and ((nonproduct and gathered.get('checks', {}).get('affiliate') == 'not_applicable'
                              and gathered.get('commercialRoute', {}).get('status') == 'not_applicable')
                             or (not nonproduct and gathered.get('checks', {}).get('affiliate') is True)))
        if not source_ready:
            raise ValueError('source_product_image_or_affiliate_verification_incomplete')
        if self.config.get('prewriteDisplayGateEnabled') is True and not nonproduct:
            from publication_display_gate import build_prewrite_plan
            plan = build_prewrite_plan(job, gathered)
            if plan['status'] == 'correction_required':
                path = self.root / 'display-correction-proposals' / job['id'] / (plan['sourceFingerprint'] + '.json')
                if not path.exists():
                    atomic(path, plan)
                raise ValueError('prewrite_display_correction_required')
        if not nonproduct:
            from purchase_evidence import require_prewrite_purchase_evidence
            require_prewrite_purchase_evidence(gathered, datetime.now(JST))
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
        local = (getattr(self, '_explicit_stage_retry', None) or {}).get('savedOutputLocalRevalidation')
        if local is not None:
            local.bind(job, gathered, draft_inputs)
        bundle = self._run_model_stage(job, 'draft', draft_inputs,
            lambda: self.models.draft(job['theme'], gathered),
            self._model_routes()['draft']['requested'])
        if MATERIALS_GUIDE_FIELD in bundle:
            raise ValueError('model_materials_guide_contract_not_allowed')
        if any(text not in bundle.get('article',{}).get('content','') for text in variant_disclosures):
            raise ValueError('apparel_variant_disclosure_missing')
        if variant_disclosures:
            for field in ('requiredExpressions','protected'):
                bundle['brief'][field] = list(dict.fromkeys(
                    bundle['brief'].get(field,[])+variant_disclosures))
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
        if nonproduct:
            bundle['article'].setdefault('generationMeta', {})['editorialContext'] = editorial_context(
                job['theme'], gathered['images'])
            bundle['article']['eyecatch'] = gathered['images'][0]['url']
            bundle['commercialRoute'] = {'status': 'not_applicable',
                                         'reason': 'verified_nonproduct_article',
                                         'verifiedBy': 'deterministic_contract_v1'}
        if corrected:
            bundle['catalogCorrectionContext'] = copy.deepcopy(correction)
            from catalog_corrections import validate_bundle
            validate_bundle(job, bundle)
        if gathered.get('images'):
            bundle['images'] = gathered['images']
            if revision:
                bundle['article'].setdefault('generationMeta', {})
                bundle['article']['generationMeta'] = dict(bundle['article'].get('generationMeta') or {})
                bundle['article']['generationMeta'].pop('socialCard', None)
        if not nonproduct:
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
        if any(text not in polished.get('content','') for text in variant_disclosures):
            raise ValueError('apparel_variant_disclosure_changed')
        atomic(artifacts / 'candidate.json', {'kind': 'candidate', 'candidate': polished})
        bundle['article']['content'] = polished['content']
        return self._finish_article_review(job, context, gathered, bundle, source,
                                           preservation, polished, source_dependencies)

    def _finish_article_review(self, job, context, gathered, bundle, source,
                               preservation, polished, source_dependencies):
        self._require_running()
        self.ledger.assert_not_owner_held(job['id'])
        context = self._wise_context(context)
        revision = job.get('kind') == 'article_revision'
        corrected = 'catalogCorrectionContext' in job
        binding = job.get('revisionContext') or {}
        public_source = ({k: copy.deepcopy(binding['baseArticle'].get(k))
                          for k in ('title', 'slug', 'categoryId', 'productIds')}
                         if revision else None)
        nonproduct = bundle.get('article', {}).get('productIds') == []
        bind_materials_guide_contract(job, gathered, bundle)
        bundle['articleReviewScoring'] = {'version': ARTICLE_SCORING_VERSION}
        scoring_contract = {'version': ARTICLE_SCORING_VERSION,
                            'applicability': article_applicability(bundle),
                            'wireSchema': article_review_schema(bundle)}
        if self.config.get('socialCardsEnabled') is True and not nonproduct:
            if self.social_cards is None:
                from social_cards import SocialCards
                self.social_cards = SocialCards(self.config, self.env, self.catalog)
            if revision:
                bundle = normalize_revision_social_card(bundle)
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
        flags = {k: evidence.get(k) is True for k in ('facts', 'images')}
        flags['affiliate'] = (nonproduct_affiliate_review(bundle) if nonproduct
                              else evidence.get('affiliate') is True)
        medical = self._medical(bundle['article'])
        if revision:
            medical.update(scope='candidate_article_only', inheritedClinicalReverified=False)
        click_results = preview.get('clicksVerified', {})
        if nonproduct:
            clicks_ok = (click_results == {'desktop': [], 'mobile': []}
                         and preview.get('sponsoredCtaCount') == {'desktop': 0, 'mobile': 0}
                         and preview.get('allAnchorsVerified') is True)
        else:
            clicks_ok = bool(click_results.get('desktop')) and bool(click_results.get('mobile')) if isinstance(click_results, dict) else click_results is True
        flags.update(medical=medical['passed'], render=preview.get('passed') is True and clicks_ok)
        verification_revision = verification_sha = verification_projection = None
        if (revision or corrected) and self.config.get('independentReviewEnabled') is True:
            from article_verification_receipt import build as build_verification_receipt
            from article_verification_receipt import projection as project_verification_receipt
            from article_verification_receipt import write_once as write_verification_receipt
            from article_verification_receipt import write_source_once as write_verification_source
            selected_product_ids = set(bundle['article'].get('productIds', []))
            verification_source = {
                'normalizedSource': copy.deepcopy(source_dependencies),
                'products': [copy.deepcopy(item) for item in bundle.get('products', [])
                             if item.get('id') in selected_product_ids],
                'references': copy.deepcopy(bundle.get('references', [])),
                'images': [copy.deepcopy(item) for item in bundle.get('images', [])
                           if item.get('productId') in selected_product_ids],
            }
            source_sha = fingerprint(verification_source)
            source_path = (self.root / 'article-verification-sources' / job['id'] /
                           (source_sha + '.json'))
            if write_verification_source(source_path, verification_source) != source_sha:
                raise ValueError('article_verification_source_write_mismatch')
            verification_receipt = build_verification_receipt(
                job, bundle, gathered, preview, medical, checks, verification_source,
                self.catalog.request)
            verification_revision = fingerprint(bundle)
            verification_path = (self.root / 'article-verification-receipts' / job['id'] /
                                 (verification_revision + '.json'))
            verification_sha = write_verification_receipt(verification_path, verification_receipt)
            verification_projection = project_verification_receipt(
                verification_receipt, job['id'], verification_revision)
        model_flags = dict(flags)
        if nonproduct:
            # The reviewer schema remains boolean; the persisted ledger evidence below
            # retains the typed not-applicable contract instead of claiming a merchant pass.
            model_flags['affiliate'] = True
        review_bundle = {k: v for k, v in bundle.items()
                         if k not in ('revisionContext', 'catalogCorrectionContext')}
        review_checks = {'evidence': model_flags, 'structural': checks,
                         'articleMeasurements': {
                             'format': bundle['brief']['format'],
                             'contentCharacters': len(bundle['article']['content']),
                             'minimumCharacters': ARTICLE_LENGTHS[bundle['brief']['format']][0],
                             'maximumCharacters': ARTICLE_LENGTHS[bundle['brief']['format']][1],
                             'method': 'python_len_decoded_article_content'},
                         'source': gathered.get('evidence', {}),
                         'approvedTheme': job['theme'],
                         'preview': preview, 'polishPreservation': (dict(preservation, selection=copy.deepcopy(polished['polishSelection']))
                             if 'polishSelection' in polished else preservation),
                         'editorialRules': context['editorialRules'],
                         'wisePolicy': context['wisePolicy'],
                         'articleScoringContract': scoring_contract,
                         'medical': medical,
                         'sourceContent': source['article']['content'],
                         **({'existingArticle': public_source,
                             'editorialCorrectionInstructions': binding['editorialCorrectionInstructions'],
                             'verifiedAuthorFacts': binding['verifiedAuthorFacts']} if revision else {})}
        if verification_projection is not None:
            review_checks['programVerification'] = verification_projection
        review_inputs = {
            'bundle': self._source_dependencies(review_bundle),
            'checks': self._review_dependencies(review_checks),
            'dependencies': {'verifiedSource': source_dependencies,
                             'routes': self._model_routes(),
                             'qualityFlags': model_flags,
                             'structural': checks,
                             'renderer': self._review_dependencies(preview),
                             'editorialRules': context['editorialRules']},
            'articleScoringContract': scoring_contract,
            'schemaVersion': {'stage': 3, 'input': 'bundle+live-checks+scoring-contract', 'output': 'final-review'},
        }
        if verification_projection is not None:
            review_inputs['dependencies']['programVerificationReceiptSha256'] = verification_sha
        def review_operation():
            candidate = self.models.review(review_bundle, review_checks)
            if candidate.get('passed') is not True:
                raise ValueError('final_review_failed')
            return candidate
        final = self._run_model_stage(job, 'final_review', review_inputs, review_operation,
                                      self._model_routes()['final_review']['requested'])
        job = self.ledger.save_bundle(job['id'], bundle)
        if verification_revision is not None and job['revision'] != verification_revision:
            raise ValueError('article_verification_receipt_revision_changed')
        review = dict(final, fingerprint=job['revision'], evidence=flags,
                      polish={'model': polished['model'], 'validated': True})
        if verification_sha is not None:
            review['programVerification'] = {'schemaVersion': 1,
                'kind': 'article_verification_receipt_v1',
                'revision': job['revision'], 'receiptSha256': verification_sha,
                'sourceDependenciesSha256': source_sha}
        if 'polishSelection' in polished:
            review['polish']['selection'] = copy.deepcopy(polished['polishSelection'])
        if revision:
            review.update(medicalScope='candidate_article_only', inheritedClinicalReverified=False)
            inherited = bundle['inheritedPresentationContext']
            if inherited['kind'] == 'unchanged_medical_advice':
                review['inheritedAdviceDomSha256'] = inherited['domSha256']
            else:
                review['inheritedAdviceApplicability'] = 'not_applicable'
        self.ledger.record_review(job['id'], job['revision'], review)
        if (revision or corrected) and self.config.get('independentReviewEnabled') is True:
            from independent_article_review import ensure_review
            ensure_review(self, self.ledger.get_job(job['id']))
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
            valid_review(job.get('review'), job['revision'], job.get('bundle'))
            restored = self.ledger.set_stage(id, 'review')
            return {'status': restored['stage'], 'id': id, 'sameWeeklySlot': True,
                    'checkpoint': 'review'}
        self.ledger.set_stage(id, 'draft')
        self.ledger.set_stage(id, 'candidate')
        with self.ledger._tx() as db:
            db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',
                       ('runtime_retry_candidate', id))
        return {'status': 'candidate', 'id': id, 'sameWeeklySlot': True}

    def resume_revision_review_after_purchase_na(self, id, evidence, operator_reference):
        from revision_purchase_na_resume import resume
        return resume(self, id, evidence, operator_reference)

    def retry_revision_source_hold(self, id, expected_spec_hash, owner_grant, *,
                                   expected_current_period, now=None):
        """Explicit one-time recovery for a revision stopped before model work."""
        from revision_source_hold_recovery import execute
        return execute(self, id, expected_spec_hash, owner_grant,
                       expected_current_period=expected_current_period, now=now)

    def prepare_revision_source_hold_retry(self, id, expected_spec_hash, owner_grant, *,
                                           expected_current_period, now=None):
        """Read-only preflight for the exact source-hold recovery claim."""
        from revision_source_hold_recovery import prepare
        return prepare(self, id, expected_spec_hash, owner_grant,
                       expected_current_period=expected_current_period, now=now)

    def prepare_revision_catalog_amendment(self, id, owner_grant, *,
                                           expected_current_period, now=None):
        """Read-only preflight for the one authorized burner catalog amendment."""
        from revision_catalog_amendment import prepare
        return prepare(self, id, owner_grant,
                       expected_current_period=expected_current_period, now=now)

    def resume_revision_after_catalog_amendment(self, id, owner_grant, *,
                                                expected_current_period, now=None):
        """Apply the exact amendment and enter the ordinary revision pipeline once."""
        from revision_catalog_amendment import execute
        return execute(self, id, owner_grant,
                       expected_current_period=expected_current_period, now=now)

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
            return (self.produce_supplemental(limit=1, job_id=id)
                    if job.get('kind') == 'supplemental_article' else self.produce(limit=1))
        finally:
            self._explicit_stage_retry = None

    @staticmethod
    def validate_corrected_retry(job, stage, input_key, records, *, reselection_receipt=None):
        """Read-only eligibility check shared by operator planning and execution."""
        revision_retry = False
        fleece_retry = False
        if job.get('kind') == 'article_revision':
            from revisions import validate_context
            from fleece_revision_recovery import eligible as fleece_eligible
            binding = validate_context(job.get('revisionContext'))
            revision_retry = (
                (job.get('error') or {}).get('reason') == 'Article length outside existing SKILL limits'
                and job.get('review') is None
                and job.get('theme', {}).get('slug') == binding['baseArticle']['slug']
                and job.get('theme', {}).get('productIds') == binding['targetProductIds'])
            fleece_retry = fleece_eligible(job, input_key, binding)
            revision_retry = revision_retry or fleece_retry
        allowed_errors = {
            'apparel-2026-11-16': {
                'Two to three distinct internal article links required',
                'Article length outside existing SKILL limits',
            },
            'apparel-2026-11-22': {
                'Unknown or self internal article link',
            },
        }
        batch_id = job.get('batchId')
        reselection_retry = False
        if reselection_receipt is not None:
            from supplemental_reselection import BATCH, SKIN
            plan = reselection_receipt.get('plan') or {}
            reselection_retry = (
                reselection_receipt.get('status') == 'applied'
                and fingerprint(plan) == reselection_receipt.get('planSha256')
                and reselection_receipt.get('newJobId') == job.get('id')
                and job.get('id') != SKIN and batch_id == BATCH
                and plan.get('oldJobId') == SKIN and plan.get('slot') == 2
                and job.get('batchSlot') == 2 and job.get('budgetArticleId') == SKIN
                and job.get('replacesJobId') == SKIN
                and job.get('theme') == (plan.get('replacement') or {}).get('theme')
                and job.get('sourceBinding') == (plan.get('replacement') or {}).get('sourceBinding')
                and job.get('review') is None
                and (job.get('error') or {}).get('reason') == 'Unknown or self internal article link')
        # One authorized prompt-change recovery; never authorize this error for
        # a whole batch. The old failed lineage still owns its remaining attempt.
        prompt_change_retry = (
            batch_id == 'winter-depth-2026-11-22'
            and job.get('id') == 'article-b1059cbd51d84cee93adbdc6'
            and input_key == 'stage_journal:v1:aa5d8885296281a0a41b548269e72fe7d44a44e47797cdd5c20bc505d80d6710'
            and (job.get('error') or {}).get('reason') == 'exact failed stage inputs changed')
        if prompt_change_retry:
            try:
                prompt_hash = hashlib.sha256(Path(__file__).with_name('models.py').read_bytes()).hexdigest()
            except OSError:
                raise ValueError('prompt_change_recovery_inputs_unavailable') from None
            if prompt_hash != '144fcbca061d8ebd8be8c67c8241a40b53c0ba1f27dc1d52f885c88eb081bf44':
                raise ValueError('prompt_change_recovery_inputs_changed')
        if (stage != 'draft' or (not revision_retry and (job.get('kind') != 'supplemental_article'
                or (not prompt_change_retry and not reselection_retry and (batch_id not in allowed_errors
                    or (job.get('error') or {}).get('reason') not in allowed_errors[batch_id]))
                or job.get('batchCallCap') != 96)) or job.get('stage') != 'error'
                or any(job.get(field) is not None for field in ('bundle', 'approval', 'publication'))):
            raise ValueError('job_not_corrected_stage_retryable')
        record = next((r for r in records if r.get('stageKey') == input_key), None)
        if (len(records) != 1 or record is None or record.get('jobId') != job['id']
                or record.get('stage') != stage or record.get('status') != 'failed'
                or record.get('attempts') != 1 or record.get('maxAttempts') != 2
                or record.get('successorKey') or record.get('predecessorKey')):
            raise StageBlocked('exact corrected failed stage retry unavailable', stage_key=input_key)
        if fleece_retry:
            if (record.get('failureType') != 'ModelError' or record.get('responseReceiptCount') != 1
                    or record.get('missingUsage') is not False):
                raise ValueError('fleece_recovery_old_response_changed')

    def retry_saved_reselection_draft(self, id, input_key):
        from reselection_saved_draft import SavedOutputLocalRevalidation
        return self.retry_corrected_stage(id, 'draft', input_key,
            saved_output_local_revalidation=SavedOutputLocalRevalidation(self, id, input_key))

    def retry_corrected_stage(self, id, stage, input_key, *, saved_output_local_revalidation=None):
        """Operator-only recovery of an explicitly eligible remaining draft.

        Caller holds runtime.flock. Keep error until the existing producer saves
        a reviewed bundle: a crash or source hold cannot enqueue a fresh attempt.
        """
        self._require_running()
        job = self.ledger.get_job(id)
        from supplemental_reselection import corrected_link_retry_receipt
        with sqlite3.connect(self.ledger.db_path) as db:
            reselection = corrected_link_retry_receipt(db, self.ledger.list_jobs(), job)
        self.validate_corrected_retry(job, stage, input_key,
            self.stage_journal.status(job_id=id, stage=stage)['records'],
            **({'reselection_receipt': reselection} if reselection is not None else {}))
        if job.get('kind') == 'article_revision':
            return self._retry_revision_stage(job, stage, input_key, corrected=True)
        if job.get('batchId') == 'apparel-2026-11-22':
            raise ValueError('local_contract_revalidation_required')
        if saved_output_local_revalidation is not None:
            from reselection_saved_draft import SavedOutputLocalRevalidation
            if (not isinstance(saved_output_local_revalidation, SavedOutputLocalRevalidation)
                    or reselection is None or stage != 'draft'
                    or saved_output_local_revalidation.runtime is not self
                    or saved_output_local_revalidation.id != id or saved_output_local_revalidation.key != input_key):
                raise ValueError('saved_output_local_revalidation_scope')
            saved_output_local_revalidation.claim()
        self._explicit_stage_retry = {'jobId': id, 'stage': stage,
                                      'inputKey': input_key, 'corrected': True}
        if saved_output_local_revalidation is not None:
            self._explicit_stage_retry['savedOutputLocalRevalidation'] = saved_output_local_revalidation
        try:
            return self.produce_supplemental(limit=1, job_id=id)
        finally:
            self._explicit_stage_retry = None
            current = self.ledger.get_job(id)
            if not current.get('bundle'):
                detail = dict(current.get('error') or job['error'])
                if current.get('error') and current['error'] != job['error']:
                    detail['originalFailure'] = copy.deepcopy(job['error'])
                detail['correctedRetry'] = 'no_review_progress_requires_explicit_recovery'
                self.ledger.set_stage(id, 'error', detail)
            if saved_output_local_revalidation is not None:
                saved_output_local_revalidation.finish(bool(current.get('bundle')))
            self._save_usage()

    def _revision_manager_blocks(self, raw, job):
        import revisions
        try:
            record = json.loads(raw)
        except (ValueError, TypeError):
            return True
        if not isinstance(record, dict) or not isinstance(record.get('status'), str):
            return True
        if record['status'] in ('evaluating', 'executing'):
            return True
        if record['status'] != 'requires_reconciliation':
            return False
        action = record.get('action')
        if not isinstance(action, dict):
            return True
        ids = [action[k] for k in ('job_id', 'jobId') if k in action]
        if (not ids or any(not isinstance(i, str) or not i.strip() for i in ids)
                or len(set(ids)) != 1):
            return True
        base = job['revisionContext']['baseArticle']
        if ids[0] in (job['id'], base['id'], base['slug']):
            return True
        try:
            related = self.ledger.get_job(ids[0])
        except (ValueError, TypeError):
            return True
        if not isinstance(related, dict) or not related:
            return True  # An unresolvable target is not proof of unrelated scope.
        if related.get('kind') == 'article_revision':
            try:
                article = revisions.validate_context(related.get('revisionContext'))['baseArticle']
            except (ValueError, TypeError, KeyError):
                return True
            return article['id'] == base['id'] or article['slug'] == base['slug']
        theme = related.get('theme')
        if not isinstance(theme, dict) or not isinstance(theme.get('slug'), str) or not theme['slug']:
            return True
        return related['id'] == base['id'] or theme['slug'] == base['slug']

    def _retry_revision_stage(self, job, stage, input_key, *, corrected=False):
        recovery_proof = {}
        if corrected:
            records = self.stage_journal.status(job_id=job['id'])['records']
            self.validate_corrected_retry(job, stage, input_key,
                [r for r in records if r.get('stage') == stage])
            from fleece_revision_recovery import JOB as FLEECE_JOB, load_proof, require_old_response
            if job['id'] == FLEECE_JOB:
                # Exact paid response/source proof is retained in the finite retry receipt.
                with sqlite3.connect(self.ledger.db_path) as db:
                    row = db.execute('SELECT value FROM meta WHERE key=?', (input_key,)).fetchone()
                if row is None:
                    raise ValueError('fleece_recovery_old_response_changed')
                require_old_response(json.loads(row[0]))
                recovery_proof = {'recoveryEvidence': load_proof(self.root, job, input_key)}
            with sqlite3.connect(self.ledger.db_path) as db:
                effects = db.execute("SELECT 1 FROM effects WHERE job_id=? AND status IN ('in_flight','unknown')",
                                     (job['id'],)).fetchone()
                manager = db.execute("SELECT value FROM meta WHERE key LIKE 'editorial_manager:%'").fetchall()
            if (effects or any(self._revision_manager_blocks(row[0], job) for row in manager)
                    or any(r.get('status') in ('in_flight', 'unknown') for r in records)):
                raise ValueError('revision_retry_requires_reconciliation')
            with sqlite3.connect(self.ledger.db_path) as db:
                if (db.execute('SELECT 1 FROM requests WHERE job_id=?', (job['id'],)).fetchone()
                        or db.execute("SELECT 1 FROM model_budget_reservations WHERE article_id IN (?,?) "
                                      "AND status IN ('reserved','in_flight','unknown')",
                                      (job['id'], self._budget_article_id(job['id']))).fetchone()):
                    raise ValueError('revision_retry_requires_reconciliation')
        marker = self.root / 'revision-production-attempts' / (job['id'] + '.json')
        try:
            if marker.is_symlink() or marker.stat().st_mode & 0o777 != 0o600:
                raise ValueError()
            receipt = json.loads(marker.read_text())
            if not isinstance(receipt, dict) or receipt.get('status') != 'blocked':
                raise ValueError()
            expected_reason = (job['error']['reason'] if recovery_proof
                               else 'Article length outside existing SKILL limits')
            if corrected and receipt.get('reason') != expected_reason:
                raise ValueError()
        except (OSError, ValueError, TypeError):
            raise ValueError('revision_production_requires_reconciliation') from None
        retry_marker = (self.root / 'revision-stage-retries' / job['id'] /
                        (hashlib.sha256(input_key.encode()).hexdigest() + '.json'))
        if retry_marker.exists() or (corrected and retry_marker.is_symlink()):
            raise ValueError('revision_stage_retry_requires_reconciliation')
        atomic(retry_marker, {'status': 'in_flight', 'at': stamp(),
                              'stage': stage, 'inputKey': input_key, **recovery_proof})
        self._explicit_stage_retry = {'jobId': job['id'], 'stage': stage,
                                      'inputKey': input_key}
        if corrected:
            self._explicit_stage_retry['corrected'] = True
        else:
            self.ledger.set_stage(job['id'], 'draft')
            self.ledger.set_stage(job['id'], 'candidate')
        try:
            current = self.ledger.get_job(job['id'])
            delivery = self._make_article(current, self._context())
            atomic(retry_marker, {'status': 'completed', 'at': stamp(),
                                  'stage': stage, 'inputKey': input_key, **recovery_proof})
            status = ('awaiting_astra_review' if isinstance(delivery, dict)
                      and delivery.get('status') == 'awaiting_astra_review'
                      else 'awaiting_approval')
            return {'status': 'completed', 'articles': [{'id': job['id'], 'status': status}]}
        except StageUnknown as error:
            detail = {'reason': reason(error), 'at': stamp()}
            if corrected:
                detail['originalFailure'] = copy.deepcopy(job['error'])
            self.ledger.set_stage(job['id'], 'error', detail)
            atomic(retry_marker, {'status': 'unknown', 'at': stamp(),
                                  'stage': stage, 'inputKey': input_key, **recovery_proof})
            return {'status': 'attention', 'reason': reason(error)}
        except Exception as error:
            detail = {'reason': reason(error), 'at': stamp()}
            if corrected:
                detail['originalFailure'] = copy.deepcopy(job['error'])
            self.ledger.set_stage(job['id'], 'error', detail)
            atomic(retry_marker, {'status': 'blocked', 'at': stamp(),
                                  'stage': stage, 'inputKey': input_key,
                                  'reason': reason(error), **recovery_proof})
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
            for name in ('models.py', 'quality.py', 'review_scoring.py', 'writing_prompts.py')
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
        for image in evidence.get('ownedIllustrations', []) if isinstance(evidence, dict) else []:
            if isinstance(image, dict):
                image.pop('checkedAt', None)
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
        self.ledger.assert_not_owner_held(job['id'])
        key = self.stage_journal.key(job['id'], stage, inputs)
        cache_only = getattr(self, '_cache_only_stage_keys', None)
        cached_stage = isinstance(cache_only, dict) and stage in cache_only
        if cached_stage:
            records = self.stage_journal.status(job_id=job['id'], stage=stage)['records']
            if key != cache_only[stage] or not any(
                    item.get('stageKey') == key and item.get('status') == 'succeeded'
                    for item in records):
                raise StageBlocked('exact paid stage cache required after render recovery',
                                   stage_key=key, status='changed')
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
                if key != retry['inputKey'] and not retry.get('corrected'):
                    raise StageBlocked('exact failed stage inputs changed', stage_key=key,
                                       status='changed')
                explicit_retry = True
        start = len(getattr(self.models, 'usage', []))
        called = False
        reason_name = 'explicit_retry' if explicit_retry else 'initial'
        def measured():
            nonlocal called
            if cached_stage:
                raise StageBlocked('paid stage model call forbidden during render recovery',
                                   stage_key=key, status='changed')
            called = True
            with self.model_budget.scope(self._budget_article_id(job['id']), stage):
                return operation()
        try:
            if explicit_retry and retry and retry.get('savedOutputLocalRevalidation') is not None:
                try:
                    return self.stage_journal.retry_corrected_failed(job['id'], stage, retry['inputKey'], inputs,
                        retry['savedOutputLocalRevalidation'].operation)
                finally:
                    self._explicit_stage_retry = None
            if explicit_retry and retry and retry.get('corrected'):
                return self.stage_journal.retry_corrected_failed(
                    job['id'], stage, retry['inputKey'], inputs, measured)
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
        diagnostics = vars(self.models).get('review_diagnostics', [])
        while diagnostics:
            record = diagnostics[0]
            response_id = record.get('responseId') if isinstance(record, dict) else None
            if not isinstance(response_id, str) or not response_id:
                raise ValueError('review diagnostic response id required')
            name = hashlib.sha256(response_id.encode('utf-8')).hexdigest() + '.json'
            atomic(self.root / 'review-diagnostics' / name, record)
            del diagnostics[0]

    def _budget_article_id(self, job_id):
        """A new revision of the same public URL must share its article budget."""
        try:
            job = self.ledger.get_job(job_id)
        except (KeyError, ValueError):
            return job_id
        if job.get('kind') == 'supplemental_article':
            from supplemental_reselection import budget_article_id
            self.ledger.active_supplemental_jobs(job['batchId'])
            return budget_article_id(self.ledger, job)
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
        self.ledger.assert_not_owner_held(id)
        if kind == 'social' and not self._social_review_allowed(id):
            raise ValueError('social_review_disabled')
        job = self.ledger.get_job(id)
        target = job if kind == 'article' else job.get('social', {})
        require_current_review(target.get('bundle') if kind == 'article' else target.get('proposal'),
                               target.get('review'), self.config.get('repo'))
        if kind == 'article' and (job.get('kind') == 'article_revision' or 'catalogCorrectionContext' in job):
            quality_result = None
            if self.config.get('independentReviewEnabled') is True:
                from independent_article_review import ensure_review
                quality_result = ensure_review(self, job)
                self._notify_independent_hold(job, quality_result.get('status'))
                job = self.ledger.get_job(id)
            try:
                self.ledger._current(job)
                valid_review(job.get('review'), job['revision'], job.get('bundle'))
                valid_astra_review(job.get('astraReview'), job['revision'])
            except ValueError:
                return {'status': 'awaiting_astra_review', 'deferred': True,
                        **({'qualityStatus': quality_result.get('status')}
                           if isinstance(quality_result, dict) else {})}
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

    def _prepare_existing_improvement(self, now):
        """One deterministic preparation per period, never an extra AI manager."""
        if self.config.get('existingImprovementsEnabled') is not True:
            return {'status': 'disabled'}
        if self.config.get('generationEnabled') is not True:
            return {'status': 'waiting_generation'}
        if not self.ledger.production_schedule.is_due(now):
            return {'status': 'not_due'}
        # A cached receipt avoids repeated catalog/source reads on unchanged ticks.
        period = self.ledger.production_schedule.period_key(now)
        prior = self.ledger.existing_improvement_receipt(period)
        if prior is not None:
            return prior
        if not daily_metrics_due(now):
            return {'status': 'waiting_daily_metrics'}
        try:
            from daily_metrics import require_fresh_daily_metrics
            require_fresh_daily_metrics(self.config, now=now)
        except ValueError:
            return {'status': 'waiting_daily_metrics'}
        from existing_update_preparation import prepare_existing_update
        return prepare_existing_update(self, self.analytics.load_context(now=now),
                                       self.catalog.catalog(), now=now)

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
        try:
            existing_improvement = self._prepare_existing_improvement(now)
        except Exception:
            existing_improvement = {'status': 'requires_reconciliation',
                                    'reason': 'existing_improvement_preparation_unavailable'}
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
        if (existing_improvement.get('status') == 'requires_reconciliation'
                or 'source_verification_failed' in existing_improvement.get('sourceHoldReasons', [])):
            results.append({'id': 'existing-improvement', 'status': 'attention',
                            'reason': 'existing_improvement_preparation_requires_attention'})
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
                    if job.get('kind') == 'article_revision' or 'catalogCorrectionContext' in job:
                        valid_astra_review(job.get('astraReview'), job['revision'])
                    if ('catalogCorrectionContext' in job
                            and self.config.get('catalogCorrectionsPublicationEnabled') is not True):
                        results.append({'id': job['id'], 'status': 'waiting_auth',
                                        'reason': 'catalog_corrections_publication_disabled'})
                        continue
                    if 'catalogCorrectionContext' in job:
                        readiness = self._catalog_correction_readiness(job)
                        if not isinstance(readiness, dict) or readiness.get('ready') is not True:
                            unavailable = (not isinstance(readiness, dict) or
                                           readiness.get('reason') != 'affected_article_correction_required')
                            results.append({'id': job['id'],
                                            'status': 'attention' if unavailable else 'waiting_dependency',
                                            'reason': 'correction_readiness_unavailable' if unavailable
                                            else 'affected_article_correction_required'})
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
                        prewrite = getattr(error, 'publication_prewrite', False) is True
                        self.ledger.finish_effect(job['id'], 'publish', {'status': 'failed' if prewrite else 'unknown',
                            'reason': 'publication_prewrite_failed' if prewrite else 'publication_requires_reconciliation',
                            **({'diagnostic': diagnostic} if diagnostic else {})})
                        raise
                    self.slack.notice('【公開確認済み】' + job['bundle']['article']['title'] + '\n' + result['url'])
                elif job['stage'] == 'review':
                    if dispatch is not None and ('deliver', job['id'], 'article') not in actions:
                        continue
                    delivered = self.deliver(job['id'])
                    if isinstance(delivered, dict) and delivered.get('qualityStatus') in (
                            'blocked', 'failed', 'unknown', 'budget_hold', 'stale'):
                        results.append({'id': job['id'], 'status': 'attention',
                                        'reason': 'independent_quality_review_' + delivered['qualityStatus']})
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
            supplemental_action = next((action for action in dispatch['actions']
                                        if action['kind'] == 'produce_supplemental'), None)
            if supplemental_action is not None:
                try:
                    results.append({'supplementalProduction': self.produce_supplemental(
                        limit=1, job_id=supplemental_action.get('jobId'), now=now)})
                except Exception as error:
                    results.append({'status': 'attention', 'reason': reason(error),
                                    'supplementalProduction': {'status': 'blocked',
                                                               'reason': reason(error)}})
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
        seo_feedback = {'status': 'unconfigured'}
        if self.config.get('seoStateRoot'):
            try:
                context = self._analytics_context()
                seo_feedback = self._refresh_seo_feedback(jobs, context, now)
            except Exception:
                results.append({'analytics': {'status': 'unavailable'}, 'status': 'attention',
                                'reason': 'seo_feedback_unavailable'})
                seo_feedback = {'status': 'unavailable'}
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
                  'existingImprovement': existing_improvement,
                  'seoFeedback': seo_feedback,
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
        result['supplementalApparel'] = self._supplemental_health(now)
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
                                                         period_key=period, now=now),
                    buffer_posting_enabled=self.config.get('bufferPostingEnabled') is True)
            except Exception:
                result['productionVerification'] = {'status': 'requires_reconciliation'}
            if result['productionVerification']['status'] in ('requires_reconciliation', 'blocked'):
                result['status'] = 'attention'
        if self.config.get('supplementalApparelEnabled') is True:
            try:
                from supplemental_verification import verify_supplemental_batch
                from usage_cost_report import usage_cost_summary
                manifest = self._supplemental_manifest()
                batch_jobs = [job for job in jobs if job.get('kind') == 'supplemental_article'
                              and job.get('batchId') == manifest['batchId']]
                marker = self.root/'supplemental-batches'/(manifest['batchId']+'.json')
                try: source_state = json.loads(marker.read_text())
                except (OSError,ValueError): source_state = None
                period = self.ledger.production_schedule.period_key(now)
                result['supplementalVerification'] = verify_supplemental_batch(
                    self.root,jobs,manifest['batchId'],self.config['slack'],self.slack.notice,
                    now=now,not_before=manifest['notBefore'],source_state=source_state,
                    cost_text=lambda:usage_cost_summary(self.root,self.config,kind='production',
                        period_key=period,now=now,
                        article_ids=sorted(job['id'] for job in batch_jobs),
                        batch_call_cap=manifest['batchCallCap'],
                        article_since=manifest['notBefore']))
            except Exception:
                result['supplementalVerification'] = {'status':'requires_reconciliation'}
            if result['supplementalVerification']['status'] in (
                    'blocked','source_hold','requires_reconciliation'):
                result['status'] = 'attention'
        if (any((job.get('error') or {}).get('reason') == 'model_budget_hold' for job in jobs)
                or any(result['modelBudget']['eventsByStatus'].get(status, 0)
                       for status in ('in_flight', 'unknown'))):
            result['status'] = 'attention'
        atomic(self.root / 'health.json', result)
        handled_ids = set(result.get('productionVerification', {}).get('handledAttentionJobIds', []))
        handled_ids.update(result.get('supplementalVerification', {}).get(
            'handledAttentionJobIds', []))
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
        # Keep validation failures in health/articles; do not ask the owner to debug them.
        from attention_presentation import INTERNAL_REASONS
        attention = [item for item in attention
                     if (item.get('error') or {}).get('reason') not in INTERNAL_REASONS]
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
        self.ledger.assert_not_owner_held(job['id'])
        if not social_feature_enabled(self.config, 'socialGenerationEnabled'):
            raise ValueError('social_generation_disabled')
        buffer_start = buffer_social_start(self.config)
        buffer_image_route = None
        if buffer_start is not None:
            if not buffer_social_eligible(job, self.config):
                raise ValueError('buffer_social_period_ineligible')
            if not self._social_audit_success(job):
                raise ValueError('buffer_social_requires_successful_public_audit')
            buffer_image_route = self._valid_buffer_social_card(job)
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
        elif (isinstance(buffer_image_route, dict)
              and buffer_image_route.get('kind') == 'owned_article_image'):
            proposal['images'] = [copy.deepcopy(buffer_image_route['image'])]
            proposal['supplementalArticleImage'] = copy.deepcopy(buffer_image_route['binding'])
        # The announcement receives its own prose polish and final review.
        source = proposal['text']
        polished = self._measured_model_call(
            job['id'], 'social', self._model_routes()['polish']['requested'],
            lambda: self.models.polish(source, bundle['brief'], article=False))
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
                bundle = job.get('bundle') or {}
                nonproduct = bundle.get('article', {}).get('productIds') == []
                valid_checks = False
                if isinstance(checks, list) and checks:
                    na = {check.get('name') for check in checks
                          if isinstance(check, dict) and check.get('status') == 'not_applicable'}
                    valid_checks = all(
                        isinstance(check, dict) and isinstance(check.get('name'), str) and check['name']
                        and (check.get('status') == 'passed'
                             or (nonproduct and check.get('status') == 'not_applicable'
                                 and check.get('name') in {'desktop.merchant', 'mobile.merchant'}
                                 and check.get('reason') == 'verified_nonproduct_article'))
                        for check in checks)
                    if nonproduct:
                        from topic_selection import validate_nonproduct_bundle
                        validate_nonproduct_bundle(bundle)
                        valid_checks = valid_checks and na == {'desktop.merchant', 'mobile.merchant'}
                    else:
                        valid_checks = valid_checks and not na
                if (audit.get('schemaVersion') == 1
                        and audit.get('status') == 'success' and audit.get('id') == job.get('id')
                        and audit.get('revision') == job.get('revision')
                        and audit.get('auditKey') == key
                        and audit.get('publication') == publication
                        and result.get('passed') is True and result.get('status') == 'passed'
                        and result.get('issues') == [] and valid_checks):
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
        if manifest is None:
            try:
                image, binding = owned_article_social_image(job)
            except (KeyError, TypeError, ValueError):
                raise ValueError('buffer_social_card_binding_invalid') from None
            return {'kind': 'owned_article_image', 'image': image, 'binding': binding}
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
        self.ledger.assert_not_owner_held(id)
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
        self.ledger.assert_not_owner_held(id)
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
        self.ledger.assert_not_owner_held(job['id'])
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
        self.ledger.assert_not_owner_held(job['id'])
        now = (self.clock() if (self.config.get('buffer') or {}).get('dailyRootLimit') == 3
               else now or self.clock())
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
        before = self._buffer_request_snapshot(social['revision'])
        if before.get('phase') == 'deferred':
            from buffer_publisher import deferred_result
            waiting = deferred_result(before, now)
            if waiting:
                return waiting
        if self.buffer_publisher is None:
            buffer_env = dict(self.env)
            path = self.config.get('bufferEnvFile')
            if path:
                candidate = Path(path)
                if candidate.is_file() and not candidate.is_symlink():
                    buffer_env.update(env_file(candidate))
            from buffer_publisher import BufferPublisher
            self.buffer_publisher = BufferPublisher(self.config, buffer_env, fetcher=self.catalog, clock=self.clock)
        schedule = social.get('bufferSchedule') or {}
        if (before.get('pending')
                or before.get('phase') not in (None, 'deferred', 'scheduled', 'verified')
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
        if result.get('status') == 'deferred' and result.get('verified') is False:
            from buffer_publisher import deferred_result
            if (current['stage'] != 'social_approved' or after.get('phase') != 'deferred'
                    or deferred_result(after, now) != result):
                raise ValueError('buffer_publication_requires_reconciliation')
            return result
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
                'pending': copy.deepcopy(state.get('pending')),
                'revision': revision, 'result': copy.deepcopy(state.get('result'))}

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
        self.ledger.assert_not_owner_held(job['id'])
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
            self._model_routes()['polish']['requested'], lambda: self.models.polish(probe, brief, article=False))
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
        self.ledger.assert_not_owner_held(job['id'])
        require_approved_social_review(job, self.config['slack']['user_id'], self.config.get('repo'))
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
