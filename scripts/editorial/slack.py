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
        if social:
            proposal = job['social']['proposal']
            body = social_body(proposal)
        else:
            body = article_body(bundle)
        parts = []
        pieces = mrkdwn_chunks(body)
        for i, part in enumerate(pieces):
            title = ('告知案' if social else '記事本文') + '：' + article['title']
            text = title if len(pieces) == 1 else title + '（{} / {}）'.format(i + 1, len(pieces))
            parts.append(self.post(text, [{'type': 'section', 'text': {'type': 'mrkdwn', 'text': part, 'verbatim': True}}]))
        product_names = {p['id']: p['name'] for p in bundle.get('products', [])}
        for image in (proposal.get('images', []) if social else bundle.get('images', [])):
            url = image.get('url')
            if not isinstance(url, str) or not url.startswith('https://'):
                continue
            text = '画像：' + str(product_names.get(image.get('productId'), article['title']))
            parts.append(self.post(text, [{'type': 'image', 'image_url': url, 'alt_text': text}]))
        values = {k: request[k] for k in ('request_id', 'article_id', 'manifest_hash', 'nonce')}
        labels = [('approve', 'この告知案を承認' if social else '公開する'),
                  ('reject', '修正を依頼'), ('hold', '保留')]
        text = article['title'] + ('\nXへの投稿は手動です。' if social else '\n本文・画像・購入先を確認してから公開を選んでください。')
        blocks = [{'type': 'section', 'text': {'type': 'plain_text', 'text': text}},
                  {'type': 'actions', 'elements': [{'type': 'button', 'text': {'type': 'plain_text', 'text': label},
                   'action_id': 'camp_review_' + action, 'value': json.dumps(values, separators=(',', ':'))}
                   for action, label in labels]}]
        receipt = self.post(text, blocks)
        parts.append(receipt)
        return parts, receipt['message_ts']

    def notice(self, text):
        return self.post(text)
