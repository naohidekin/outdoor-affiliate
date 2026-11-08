"""Canonical DOM evidence for unchanged presentation context; never clinical verification."""
import hashlib
from html.parser import HTMLParser
import json
import re
import sys

TEMPLATE_FILES = ('src/app/articles/[slug]/page.tsx', 'src/components/MedicalAdvice.tsx',
                  'src/lib/medicalAdviceData.ts')
VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
BLOCK = {'aside','h3','p','ul','li','div','br'}


def _check(ok):
    if not ok:
        raise ValueError('inherited_advice_context_invalid')


def _space(text):
    return re.sub(r'\s+', ' ', text).strip()


class AdviceParser(HTMLParser):
    def __init__(self, full_page):
        super().__init__(convert_charrefs=True)
        self.full_page, self.stack, self.roots = full_page, [], []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        ignored = any(t in ('script','style','template','noscript') for t, _, _ in self.stack)
        in_reading = any(a.get('id') == 'article-reading-content' for _, a, _ in self.stack)
        scoped = not self.full_page or (in_reading and any(t == 'main' for t, _, _ in self.stack)
                                       and any(t == 'article' for t, _, _ in self.stack))
        target = not ignored and scoped and tag == 'aside' and attributes.get('aria-label') == '医師からのアドバイス'
        parent = self.stack[-1][2] if self.stack else None
        _check(self.full_page or parent is not None or target)
        node = [tag, sorted((k, v if v is not None else '') for k, v in attrs), []] if target or parent is not None else None
        if node is not None:
            _check(len(attributes) == len(attrs))
            if parent is not None:
                parent[2].append(node)
        if target:
            self.roots.append(node)
        if tag not in VOID:
            self.stack.append((tag, attributes, node))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1][2] is not None:
            _check(self.stack[-1][0] == tag)
        index = next((i for i in range(len(self.stack)-1, -1, -1) if self.stack[i][0] == tag), None)
        if index is not None:
            del self.stack[index:]

    def handle_data(self, data):
        _check(self.full_page or not data.strip() or (self.stack and self.stack[-1][2] is not None))
        if self.stack and self.stack[-1][2] is not None:
            children = self.stack[-1][2][2]
            if children and isinstance(children[-1], str):
                children[-1] += data
            else:
                children.append(data)


def advice_evidence(html, full_page=False):
    _check(isinstance(html, str) and 0 < len(html.encode()) <= 8*1024*1024)
    parser = AdviceParser(full_page)
    parser.feed(html)
    parser.close()
    _check(len(parser.roots) == 1 and not any(node is not None for _, _, node in parser.stack))
    tree = parser.roots[0]
    def text(node):
        if isinstance(node, str):
            return node
        body = ''.join(text(child) for child in node[2])
        return '\n' + body + '\n' if node[0] in BLOCK else body
    rendered = '\n'.join(_space(line) for line in text(tree).splitlines() if _space(line))
    _check(bool(rendered))
    canonical = json.dumps(tree, ensure_ascii=False, separators=(',', ':'))
    return {'domSha256': hashlib.sha256(canonical.encode()).hexdigest(), 'text': rendered}


def validate_presentation(value, slug):
    _check(isinstance(value, dict) and set(value) == {'schemaVersion','kind','slug','html','domSha256',
            'renderedText','templateFiles','clinicalReverified','unchanged'})
    _check(value['schemaVersion'] == 1 and value['kind'] == 'unchanged_medical_advice'
           and value['slug'] == slug and value['clinicalReverified'] is False and value['unchanged'] is True)
    _check(isinstance(value['templateFiles'], dict) and set(value['templateFiles']) == set(TEMPLATE_FILES)
           and all(isinstance(v, str) and re.fullmatch(r'[a-f0-9]{64}', v) for v in value['templateFiles'].values()))
    observed = advice_evidence(value['html'])
    _check(value['domSha256'] == observed['domSha256'] and isinstance(value['renderedText'], str)
           and _space(value['renderedText']) == _space(observed['text']))
    return value


if __name__ == '__main__':
    try:
        payload = json.loads(sys.stdin.buffer.read(9*1024*1024))
        result = advice_evidence(payload['html'], payload.get('fullPage') is True)
        print(json.dumps(result, ensure_ascii=False))
    except Exception:
        sys.exit(1)  # Never print page contents, provider errors or credentials.
