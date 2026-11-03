"""Slack-only article delivery through the existing authenticated receiver."""
import hashlib
import html
import json
import os
import re
import secrets
import subprocess
import time
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def chunks(text, limit=2600):
    # Count UTF-16 units, as Slack does; avoid splitting a Unicode character.
    result, part, count = [], '', 0
    for char in text:
        units = len(char.encode('utf-16-le')) // 2
        if count + units > limit:
            result.append(part)
            part, count = '', 0
        part += char
        count += units
    if part:
        result.append(part)
    return result


class Slack:
    def __init__(self, config, call=None):
        self.scope = config['slack']
        self.node = config.get('node', 'node')
        self._call = call or self._node_call
        self._next_post = 0
        self.state_root = Path(config['stateRoot']) if config.get('stateRoot') else None

    def _receipt(self, ts, status, data):
        if self.state_root is None:
            return
        folder = self.state_root / 'slack-outbound'
        folder.mkdir(mode=0o700, exist_ok=True)
        temporary = folder / (ts + '.' + secrets.token_hex(8))
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as out:
            json.dump({'status': status, 'message_ts': ts, 'expected': data}, out, ensure_ascii=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, folder / (ts + '.json'))

    def _node_call(self, method, data):
        try:
            r = subprocess.run([self.node, str(Path(__file__).with_name('slack-api.mjs'))],
                               input=json.dumps({'method': method, 'data': data, 'scope': self.scope}),
                               text=True, capture_output=True, timeout=65)
            value = json.loads(r.stdout)
            if r.returncode or value.get('ok') is not True:
                raise ValueError('slack_delivery_unverified')
            return value
        except (subprocess.SubprocessError, OSError, ValueError):
            raise ValueError('slack_delivery_unverified') from None

    def post(self, text, blocks=None):
        if re.search(r'xox[baprs]-[A-Za-z0-9-]+|xapp-[A-Za-z0-9-]+', text):
            raise ValueError('secret_in_slack_text')
        data = {'channel': self.scope['channel_id'], 'thread_ts': self.scope['thread_ts'],
                'text': text, 'parse': 'none', 'unfurl_links': False, 'unfurl_media': False,
                'link_names': False, 'mrkdwn': False}
        if blocks:
            data['blocks'] = blocks
        time.sleep(max(0, self._next_post - time.monotonic()))
        self._next_post = time.monotonic() + 1.1
        sent = self._call('chat.postMessage', data)
        ts = sent.get('ts', '')
        if not re.fullmatch(r'\d{10}\.\d{1,6}', ts) or sent.get('channel') != self.scope['channel_id']:
            raise ValueError('slack_send_result_unknown')
        self._receipt(ts, 'sent_unverified', data)
        observed = self._call('conversations.replies', {'channel': self.scope['channel_id'],
            'ts': self.scope['thread_ts'], 'oldest': ts, 'latest': ts, 'inclusive': True, 'limit': 100})
        message = next((m for m in observed.get('messages', []) if m.get('ts') == ts), None)
        if not message or message.get('thread_ts') != self.scope['thread_ts']:
            raise ValueError('slack_readback_missing')
        # Slack normalizes fallback newlines and entity-encodes visible text.
        normalize = lambda t: str(t).replace('\n', ' ')
        if normalize(html.unescape(str(message.get('text')))) != normalize(text):
            raise ValueError('slack_readback_mismatch')
        if blocks:
            def stable(v, observed=False):
                if isinstance(v, dict):
                    ignored = {'block_id', 'emoji'}
                    if observed and v.get('type') == 'image':
                        ignored |= {'image_bytes', 'image_height', 'fallback', 'is_animated', 'image_width'}
                    return {k: (html.unescape(x) if observed and v.get('type') == 'plain_text'
                                and k == 'text' and isinstance(x, str) else stable(x, observed))
                            for k, x in v.items() if k not in ignored}
                return [stable(x, observed) for x in v] if isinstance(v, list) else v
            if stable(message.get('blocks'), observed=True) != stable(blocks):
                raise ValueError('slack_blocks_mismatch')
        self._receipt(ts, 'verified', data)
        return {'message_ts': ts, 'hash': digest(data), 'verified': True}

    def deliver(self, job, request):
        bundle = job['bundle']
        article = bundle['article']
        social = request.get('kind') == 'social'
        if social:
            proposal = job['social']['proposal']
            body = ('【SNS告知案】\n' + proposal['text'] + '\n\nリンク用返信:\n' + proposal['replyText'])
        else:
            body = ('【記事全文】' + article['title'] + '\n記事ID: ' + job['id'] +
                    '\n版: ' + job['revision'] + '\n\n' + article['content'] + '\n\nFAQ\n' +
                    '\n'.join(q['question'] + '\n' + q['answer'] for q in article.get('faqs', [])))
            body += '\n\n掲載商品・購入先\n' + '\n'.join(
                str(p.get('name', p.get('id'))) + '\n' + '\n'.join(
                    name + ': ' + p[key] for name, key in (('楽天', 'affiliateUrl'), ('Amazon', 'amazonUrl'), ('Yahoo', 'yahooUrl')) if p.get(key))
                for p in bundle.get('products', []))
        parts = []
        for i, part in enumerate(chunks(body)):
            text = '[{} / {}] {}'.format(job['id'], i + 1, part)
            parts.append(self.post(text, [{'type': 'section', 'text': {'type': 'plain_text', 'text': text}}]))
        for image in (proposal.get('images', []) if social else bundle.get('images', [])):
            url = image.get('url')
            if not isinstance(url, str) or not url.startswith('https://'):
                continue
            text = '記事画像 / ' + str(image.get('productId', article['title']))
            parts.append(self.post(text, [{'type': 'image', 'image_url': url, 'alt_text': text}]))
        values = {k: request[k] for k in ('request_id', 'article_id', 'manifest_hash', 'nonce')}
        labels = [('approve', 'この告知案の配信を承認' if social else 'この版の記事公開を承認'),
                  ('reject', '修正依頼'), ('hold', '保留')]
        text = ('【SNS承認】' if social else '【記事のGO待ち】') + article['title']
        text += '\n記事ID: ' + job['id'] + '\n対象版: ' + request['manifest_hash']
        review = (job.get('social', {}).get('review', {}) if social else job.get('review', {})) or {}
        text += '\n審査: ' + str(review.get('model', '上位モデル')) + ' / ' + str(review.get('score', '確認済み')) + '点'
        text += '\n全文・商品・画像・購入導線・表示確認済み\n'
        if not social:
            text += '選定理由: ' + str(job.get('theme', {}).get('selectionReason', '台帳の候補選定結果'))[:300] + '\n'
            text += 'ご確認: 結論・実体験表現・掲載商品・画像が意図に合っているか。\n'
        text += ('記事公開の承認とは別です。承認後もXへの投稿は手動です。' if social else '承認した本文・画像・商品・リンクを公開します。')
        text += '\n修正内容はこのCodexアプリへ記事IDを添えて伝えられます。'
        blocks = [{'type': 'section', 'text': {'type': 'plain_text', 'text': text}},
                  {'type': 'actions', 'elements': [{'type': 'button', 'text': {'type': 'plain_text', 'text': label},
                   'action_id': 'camp_review_' + action, 'value': json.dumps(values, separators=(',', ':'))}
                   for action, label in labels]}]
        receipt = self.post(text, blocks)
        parts.append(receipt)
        return parts, receipt['message_ts']

    def notice(self, text):
        return self.post(text)
