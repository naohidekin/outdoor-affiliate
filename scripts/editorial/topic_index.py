"""Local article coverage index; only compact summaries cross the model boundary."""
import hashlib
import json
import re

MAX_ARTICLES = 2000
MAX_CONTENT = 200000


def build_article_index(articles):
    if not isinstance(articles, list) or len(articles) > MAX_ARTICLES:
        raise ValueError('topic_article_index_overflow')
    result, seen = [], set()
    for article in articles:
        if not isinstance(article, dict) or not isinstance(article.get('id'), str):
            raise ValueError('topic_article_identity_required')
        if article['id'] in seen:
            raise ValueError('topic_article_identity_duplicate')
        seen.add(article['id'])
        content = article.get('content')
        if content is not None and (not isinstance(content, str) or len(content) > MAX_CONTENT):
            raise ValueError('topic_article_content_overflow')
        text = content or ''
        # Fenced examples must not masquerade as covered article headings.
        text = re.sub(r'(?ms)^(`{3,}|~{3,})[^\n]*\n.*?^\1\s*$', '', text)
        matches = list(re.finditer(r'(?m)^#{2,6}\s+(.+?)\s*#*\s*$', text))
        sections = []
        if matches and text[:matches[0].start()].strip():
            sections.append({'heading': '', 'text': text[:matches[0].start()].strip()})
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            sections.append({'heading': match.group(1), 'text': text[match.end():end].strip()})
        if not matches and text.strip():
            sections.append({'heading': '', 'text': text.strip()})
        faqs = article.get('faqs') or []
        if not isinstance(faqs, list):
            raise ValueError('topic_article_faq_invalid')
        faqs = [{'question': item['question'], 'answer': item.get('answer', '')}
                for item in faqs if isinstance(item, dict) and isinstance(item.get('question'), str)
                and isinstance(item.get('answer', ''), str)]
        conclusion = '\n'.join(section['text'] for section in sections
                               if re.search(r'まとめ|結論|さいご|最後に|おわり', section['heading']))
        result.append({**{key: article.get(key) for key in
                          ('id', 'slug', 'title', 'query', 'excerpt', 'categoryId', 'status', 'updatedAt')},
                       'headings': [match.group(1) for match in matches], 'sections': sections,
                       'faqQuestions': [faq['question'] for faq in faqs], 'faqs': faqs,
                       'conclusion': conclusion,
                       'contentSha256': hashlib.sha256(content.encode()).hexdigest() if isinstance(content, str) else None,
                       'faqsSha256': hashlib.sha256(json.dumps(faqs, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                       'bodyCoverage': 'full' if isinstance(content, str) else 'summary_only'})
    return result


def compact_article_summaries(index):
    return [{**{key: (row.get(key)[:300] if isinstance(row.get(key), str) else row.get(key))
                for key in ('id', 'slug', 'title', 'query', 'excerpt')},
             'headings': [str(heading)[:80] for heading in row.get('headings', [])[:8]]}
            for row in index]
