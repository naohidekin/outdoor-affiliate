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
from presentation import article_body, social_body


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


def mrkdwn_chunks(text, limit=2600):
    """Prefer line boundaries and never split a rendered Slack link."""
    units = lambda value: len(value.encode('utf-16-le')) // 2
    result, part = [], ''
    for line in text.splitlines(keepends=True):
        if units(part + line) <= limit:
            part += line
            continue
        if part:
            result.append(part)
            part = ''
        # A long prose line can be split, but link markup is atomic.
        for segment in re.split(r'(<https://[^>\n]+>)', line):
            if not segment:
                continue
            pieces = [segment] if units(segment) <= limit else (
                [segment] if segment.startswith('<https://') else chunks(segment, limit))
            for piece in pieces:
                if units(piece) > limit:
                    raise ValueError('presentation_link_too_long')
                if units(part + piece) > limit:
                    result.append(part)
                    part = ''
                part += piece
    if part:
        result.append(part)
    return result


class Slack:
    def __init__(self, config, call=None):
        self.scope = config['slack']
        self.social_posting_enabled = config.get('socialPostingEnabled') is True
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
        secret = r'xox[baprs]-[A-Za-z0-9-]+|xapp-[A-Za-z0-9-]+'
        if re.search(secret, text) or (blocks and re.search(secret, json.dumps(blocks, ensure_ascii=False))):
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
            def same_mrkdwn(expected, observed):
                if not isinstance(observed, str):
                    return False
                # Normalize ampersand transport only. Decoding &lt; to < would
                # turn escaped literal text into an active Slack token.
                def amps(value):
                    return value.replace('&amp;', '&').replace('&amp;', '&')
                return amps(observed) == amps(expected)

            def same(expected, observed):
                if isinstance(expected, dict):
                    if not isinstance(observed, dict):
                        return False
                    ignored = {'block_id', 'emoji'}
                    server_only = {'image_bytes', 'image_height', 'fallback', 'is_animated', 'image_width'} if observed.get('type') == 'image' else set()
                    keys = set(expected) - ignored
                    if keys != set(observed) - ignored - server_only:
                        return False
                    for key in keys:
                        if key == 'text' and expected.get('type') == 'plain_text' and isinstance(expected[key], str):
                            if not isinstance(observed[key], str) or html.unescape(observed[key]) != expected[key]:
                                return False
                        elif key == 'text' and expected.get('type') == 'mrkdwn' and isinstance(expected[key], str):
                            if not same_mrkdwn(expected[key], observed[key]):
                                return False
                        elif not same(expected[key], observed[key]):
                            return False
                    return True
                if isinstance(expected, list):
                    return isinstance(observed, list) and len(expected) == len(observed) and all(
                        same(a, b) for a, b in zip(expected, observed))
                return expected == observed
            if not same(blocks, message.get('blocks')):
                raise ValueError('slack_blocks_mismatch')
        self._receipt(ts, 'verified', data)
        return {'message_ts': ts, 'hash': digest(data), 'verified': True}

    def deliver(self, job, request):
        bundle = job['bundle']
        article = bundle['article']
        social = request.get('kind') == 'social'
        auto_x = False
        if social:
            proposal = job['social']['proposal']
            mode = proposal.get('deliveryMode')
            auto_x = mode == 'auto_x'
            if mode not in (None, 'manual', 'auto_x') or (auto_x and (
                    not isinstance(proposal.get('targetAccountId'), str)
                    or not re.fullmatch(r'[1-9][0-9]{0,19}', proposal['targetAccountId']))):
                raise ValueError('social_delivery_mode_invalid')
            body = social_body(proposal)
        else:
            body = article_body(bundle)
        parts = []
        pieces = mrkdwn_chunks(body)
        for i, part in enumerate(pieces):
            title = ('告知案' if social else '記事本文') + '：' + article['title']
            text = title if len(pieces) == 1 else title + '（{} / {}）'.format(i + 1, len(pieces))
            parts.append(self.post(text, [{'type': 'section', 'text': {'type': 'mrkdwn', 'text': part, 'verbatim': True}}]))
        if job.get('kind') == 'article_revision' and job['revisionContext'].get('productPatches'):
            binding = job['revisionContext']
            names = {p['id']: p['name'] for p in binding['candidateProducts']}
            labels = {'name': '商品名', 'brand': 'ブランド', 'specs': '仕様', 'imageUrl': '商品画像',
                      'affiliateUrl': '楽天の購入先', 'amazonUrl': 'Amazonの購入先', 'price': '参考価格',
                      'description': '商品説明', 'rating': '評価表示', 'availability': '取扱状況', 'yahooUrl': 'Yahooの導線'}
            lines = []
            for change in binding['productPatches']:
                changed = [labels[field] for field in change['fields'] if field in labels]
                if changed:
                    lines.append(names[change['id']] + '：' + '・'.join(changed) + 'を更新')
                    # Show proposed values only. The body supplies clickable purchase links and images;
                    # all specs must remain reviewable even when ProductCard displays only three.
                    def proposed(value):
                        if value is None or value == '':
                            return '記載なし'
                        if isinstance(value, dict):
                            return '／'.join(str(k) + '：' + proposed(v) for k, v in value.items()) or '記載なし'
                        if isinstance(value, list):
                            return '／'.join(proposed(v) for v in value) or '記載なし'
                        return str(value)
                    for field, value in change['fields'].items():
                        if field in ('imageUrl', 'affiliateUrl', 'amazonUrl', 'updatedAt', 'name'):
                            continue
                        if field == 'yahooUrl':
                            lines.append('  Yahooの導線：非表示（商品同一性未確認の検索リンクを外す）')
                        elif field == 'price' and value == 0:
                            lines.append('  参考価格：非表示（確認済みの価格なし）')
                        elif field == 'rating' and value == 0:
                            lines.append('  評価表示：非表示（確認済みの評価なし）')
                        elif field == 'specs' and isinstance(value, dict):
                            lines.extend('  ' + str(key) + '：' + proposed(item) for key, item in value.items())
                            if not value:
                                lines.append('  仕様：記載なし')
                        elif field in labels:
                            lines.append('  ' + labels[field] + '：' + proposed(value))

            for part in chunks('\n'.join(lines)):
                parts.append(self.post('商品カードの変更概要', [{'type': 'section', 'text': {'type': 'plain_text', 'text': part}}]))
        product_names = {p['id']: p['name'] for p in bundle.get('products', [])}
        for image in (proposal.get('images', []) if social else bundle.get('images', [])):
            url = image.get('url')
            if not isinstance(url, str) or not url.startswith('https://'):
                continue
            text = '画像：' + str(product_names.get(image.get('productId'), article['title']))
            parts.append(self.post(text, [{'type': 'image', 'image_url': url, 'alt_text': text}]))
        if job.get('kind') == 'article_revision':
            from inherited_advice import validate_presentation
            inherited = validate_presentation(bundle.get('inheritedPresentationContext'), article['slug'])
            label = '既存の「医師から一言」（変更なし・今回の再検証対象外）'
            for part in chunks(label + '\n' + inherited['renderedText']):
                parts.append(self.post(label, [{'type': 'section', 'text': {'type': 'plain_text', 'text': part, 'emoji': False}}]))
        values = {k: request[k] for k in ('request_id', 'article_id', 'manifest_hash', 'nonce')}
        revision = job.get('kind') == 'article_revision'
        labels = [('approve', '更新を公開する' if revision else 'Xに投稿する' if auto_x else 'この告知案を承認' if social else '公開する'),
                  ('reject', '修正を依頼'), ('hold', '保留')]
        explanation = ('承認した本文・画像をXへ投稿し、記事リンクを返信として自動投稿します。' if auto_x else
                       'Xへの投稿は手動です。' if social else '本文・画像・購入先を確認してから公開を選んでください。')
        if auto_x and not self.social_posting_enabled:
            explanation = ('承認した本文・画像と記事リンク返信が自動投稿の対象です。\n'
                           'X接続の復旧待ちです。承認した内容は保存し、接続確認後に投稿します。')
        if social and proposal.get('approvalNotice'):
            explanation += '\n' + proposal['approvalNotice'] + '\n' + proposal['priorPostUrl']
        if revision:
            binding = job['revisionContext']
            explanation = ('既存記事の更新案です。承認した本文・画像・購入先を反映します。\n'
                           + 'https://camp-gear-lab.com/articles/' + article['slug'] + '\n変更内容: ' + binding['changeSummary'])
        if revision and job['revisionContext'].get('productPatches'):
            explanation += '\n商品カードの修正は、この商品を掲載する他の記事にも反映されます'
        text = article['title'] + '\n' + explanation
        blocks = [{'type': 'section', 'text': {'type': 'plain_text', 'text': text}},
                  {'type': 'actions', 'elements': [{'type': 'button', 'text': {'type': 'plain_text', 'text': label},
                   'action_id': 'camp_review_' + action, 'value': json.dumps(values, separators=(',', ':'))}
                   for action, label in labels]}]
        receipt = self.post(text, blocks)
        parts.append(receipt)
        return parts, receipt['message_ts']

    def notice(self, text):
        return self.post(text)
