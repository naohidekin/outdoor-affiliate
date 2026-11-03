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

from ledger import Ledger, canonical, fingerprint, valid_review, valid_social_mode
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


class Runtime:
    def __init__(self, config, models=None, catalog=None, slack=None, renderer=None, publisher=None,
                 analytics=None, reporter=None, social_publisher=None):
        self.config = config
        self.root = Path(config['stateRoot'])
        self.ledger = Ledger(self.root, config['slack']['user_id'])
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
        self.social_publisher = social_publisher
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
        except (ValueError, IndexError):
            raise ValueError('render_preview_unavailable') from None
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
        command = [self.config.get('node', 'node'), str(Path(__file__).with_name('publish.mjs'))]
        approval = job.get('approval')
        bound_approval = None if not approval else {
            'revision': approval['revision'], 'approverId': approval['user_id'],
            'evidence': {'requestId': approval['request_id'], 'approvedAt': approval['at'],
                         'source': approval.get('source', 'authenticated-slack-receiver')}}
        request = {'action': action, 'bundle': job['bundle'], 'revision': job['revision'], 'approval': bound_approval}
        result = subprocess.run(command, input=json.dumps(request), env=child_env,
                                capture_output=True, text=True, timeout=180, cwd=self.config['repo'])
        try:
            value = json.loads(result.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise ValueError('publication_result_unknown') from None
        if result.returncode or value.get('error'):
            raise ValueError('publication_result_unknown')
        return value

    def _context(self):
        data = self.catalog.catalog()
        repo = Path(self.config['repo'])
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
        week = (now.date() - timedelta(days=now.weekday())).isoformat()
        current = [j for j in self.ledger.list_jobs() if j['week'] == week]
        pending = [j for j in self.ledger.list_jobs() if not j['publication'] and j['stage'] != 'rejected']
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
                self.ledger.create_candidate(theme)
            current = [j for j in self.ledger.list_jobs() if j['week'] == week]
        results = []
        # Pending candidates retain their slot and may resume after a week boundary.
        for job in self.ledger.list_jobs():
            if job['stage'] not in ('candidate',) or len(results) >= limit:
                continue
            try:
                self._make_article(job, context)
                results.append({'id': job['id'], 'status': 'awaiting_approval'})
            except Exception as error:
                self.ledger.set_stage(job['id'], 'error', {'reason': reason(error), 'at': stamp()})
                results.append({'id': job['id'], 'status': 'blocked', 'reason': reason(error)})
            finally:
                self._save_usage()
        return {'status': 'completed', 'articles': results}

    def _make_article(self, job, context):
        gathered = self.catalog.gather(job['theme'], context)
        atomic(self.root / 'research' / (job['id'] + '.json'), gathered)
        if not all(gathered.get('checks', {}).get(k) is True for k in ('facts', 'images', 'affiliate')):
            raise ValueError('source_product_image_or_affiliate_verification_incomplete')
        gathered.update({'CLAUDE': context['editorialRules'], 'SKILL': (Path(self.config['repo']) / 'SKILL.md').read_text()})
        bundle = self.models.draft(job['theme'], gathered)
        bundle['article'].update(id=job['id'], slug=job['theme']['slug'], status='draft',
            publishedAt=None, scheduledPublishDate=None, autoGenerated=True)
        bundle['article'].setdefault('createdAt', stamp())
        bundle['article']['updatedAt'] = stamp()
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
        checks = inspect_bundle(bundle)
        if checks.get('passed') is not True:
            raise ValueError('article_structure_or_affiliate_failed')
        evidence = gathered.get('checks', {})
        preview = self.renderer(bundle, job)
        flags = {k: evidence.get(k) is True for k in ('facts', 'images', 'affiliate')}
        medical = self._medical(bundle['article'])
        click_results = preview.get('clicksVerified', {})
        clicks_ok = bool(click_results.get('desktop')) and bool(click_results.get('mobile')) if isinstance(click_results, dict) else click_results is True
        flags.update(medical=medical['passed'], render=preview.get('passed') is True and clicks_ok)
        final = self.models.review(bundle, {'evidence': flags, 'structural': checks, 'source': gathered.get('evidence', {}),
                                          'approvedTheme': job['theme'],
                                          'preview': preview, 'polishPreservation': preservation,
                                          'editorialRules': context['editorialRules'],
                                          'medical': medical,
                                          'sourceContent': source['article']['content']})
        if final.get('passed') is not True:
            raise ValueError('final_review_failed')
        job = self.ledger.save_bundle(job['id'], bundle)
        review = dict(final, fingerprint=job['revision'], evidence=flags,
                      polish={'model': polished['model'], 'validated': True})
        self.ledger.record_review(job['id'], job['revision'], review)
        # Persist an invisible draft, never publish while waiting for a person.
        self.publisher('stage', self.ledger.get_job(job['id']))
        self.deliver(job['id'])

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

    def tick(self):
        decisions = self.consume()
        results = []
        for job in self.ledger.list_jobs():
            try:
                if job['stage'] == 'approved' and self.config.get('publicationEnabled'):
                    if not self.ledger.claim_effect(job['id'], 'publish'):
                        continue
                    try:
                        result = self.publisher('publish', job)
                        self.ledger.record_publication(job['id'], job['revision'], result)
                        self.ledger.finish_effect(job['id'], 'publish', {'status': 'success', **result})
                    except Exception:
                        self.ledger.finish_effect(job['id'], 'publish', {'status': 'unknown', 'reason': 'publication_requires_reconciliation'})
                        raise
                    self.slack.notice('【公開確認済み】' + job['bundle']['article']['title'] + '\n' + result['url'])
                elif job['stage'] == 'review':
                    self.deliver(job['id'])
                elif job['stage'] == 'published' and not job.get('social'):
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
        now = datetime.now(JST)
        if self.config.get('generationEnabled') and (now.weekday() > 2 or now.weekday() == 2 and now.hour >= 9):
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
        result = {'status': 'attention' if report_attention or any(r.get('status') == 'attention' for r in results) else 'completed',
                  'at': stamp(), 'decisions': decisions, 'results': results,
                  'articles': [dict({k: j[k] for k in ('id', 'theme', 'stage', 'revision', 'error')},
                      review={k: (j.get('review') or {}).get(k) for k in ('model', 'score', 'passed')},
                      approval={'action': 'approved' if j.get('approval') else None},
                      publication=j.get('publication'),
                      social={'status': j['stage'] if j.get('social') else None,
                              'deliveryMode': ((j.get('social') or {}).get('proposal') or {}).get('deliveryMode', 'manual'),
                              'publication': self._social_publication_summary(j)}) for j in jobs],
                  'reports': reports, 'reportAttention': report_attention,
                  'telegramEnabled': False, 'publicationEnabled': bool(self.config.get('publicationEnabled'))}
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
        account = json.loads((Path(self.config['repo']) / 'data/account-config.json').read_text())
        bundle['socialRules'] = {k: account[k] for k in ('tone', 'ngWords', 'linkRules', 'formatting', 'personaGuards') if k in account}
        bundle['socialRules']['approval'] = ('Separate exact-version human approval binds delivery mode and target account. '
            'Only explicitly auto_x proposals may automatically post after approval. Examples are not factual evidence.')
        bundle['publicReadback'] = {'verified': True, 'url': job['publication']['url'],
                                   'content': bundle['article']['content'], 'images': bundle['images']}
        proposal = self.models.social(bundle, job['publication']['url'])
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
    parser.add_argument('command', choices=('status', 'preflight', 'tick', 'produce', 'deliver', 'retry', 'approve-from-codex', 'report', 'enable-social-autopost'))
    parser.add_argument('--target-account-id')
    parser.add_argument('--kind', choices=('weekly', 'monthly', 'editorial'))
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
        elif args.command == 'produce':
            value = runtime.produce(args.limit)
        elif args.command == 'retry':
            value = runtime.retry(args.id)
        elif args.command == 'deliver':
            value = runtime.deliver(args.id)
        elif args.command == 'report':
            if not args.kind:
                raise ValueError('report_kind_required')
            value = runtime.reporter.send(args.kind, jobs=runtime.ledger.list_jobs(), manual=True)
        elif args.command == 'enable-social-autopost':
            if not args.id or not args.target_account_id:
                raise ValueError('article_and_target_account_required')
            job = runtime.enable_social_autopost(args.id, args.target_account_id)
            value = {'status': job['stage'], 'articleId': job['id'], 'revision': job['social']['revision'], 'posted': False}
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
