"""Strict X text comparison for approved posts and their URL replies."""
import re
from urllib.parse import urlsplit


def exact_x_text(post, expected):
    """Accept only exact text, an exact shortened reply URL, or a bound terminal photo URL.

    Entity offsets are checked as either code points or UTF-16 code units,
    only after the entire visible text is proven to be the expected text plus
    one terminal token. Other edits and unbound media remain mismatches.
    """
    if not isinstance(post, dict) or not isinstance(expected, str):
        return False
    actual = post.get('text')
    if actual == expected:
        return True
    urls = post.get('urls')
    media_keys = post.get('mediaKeys')
    post_id = post.get('id')
    if (not isinstance(actual, str) or not isinstance(urls, list) or not urls
            or not isinstance(media_keys, list) or not isinstance(post_id, str)
            or re.fullmatch(r'[1-9][0-9]{0,19}', post_id) is None):
        return False
    link = urls[0]
    if not isinstance(link, dict) or not isinstance(link.get('url'), str) or not isinstance(link.get('expanded_url'), str):
        return False
    start, end = link.get('start'), link.get('end')
    if (not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int)
            or isinstance(end, bool) or start < 0 or end <= start):
        return False
    token = link['url']
    if re.fullmatch(r'https://t\.co/[A-Za-z0-9]+', token) is None:
        return False
    expanded_url = link['expanded_url']
    if any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7f or char == '\\'
           for char in expanded_url):
        return False
    if actual == token:
        prefix = ''
    elif actual == expected + ' ' + token:
        prefix = expected + ' '
    else:
        return False
    try:
        cp_span = (len(prefix), len(actual))
        utf16_span = (len(prefix.encode('utf-16-le')) // 2, len(actual.encode('utf-16-le')) // 2)
    except UnicodeEncodeError:
        return False
    if (start, end) not in (cp_span, utf16_span):
        return False
    if len(urls) == 1 and prefix == '' and link['expanded_url'] == expected and not media_keys:
        return True  # Exact public-URL reply shortened to t.co.
    if not (media_keys and all(isinstance(k, str) and k for k in media_keys)
            and prefix == expected + ' '):
        return False
    if len(urls) > 1:
        # X can repeat one terminal photo URL for each attached image.
        # Only accept a complete, one-to-one binding of that identical span.
        keys = []
        for entity in urls:
            if (not isinstance(entity, dict)
                    or any(type(entity.get(field)) is not type(link[field])
                           or entity.get(field) != link[field]
                           for field in ('url', 'expanded_url', 'start', 'end'))
                    or not isinstance(entity.get('media_key'), str)):
                return False
            keys.append(entity['media_key'])
        if (len(keys) != len(media_keys) or len(set(keys)) != len(keys)
                or set(keys) != set(media_keys)):
            return False
    try:
        photo = urlsplit(link['expanded_url'])
        match = re.fullmatch(r'/(?:[A-Za-z0-9_]{1,15}|i/web)/status/' + re.escape(post_id)
                             + r'/photo/([1-4])', photo.path)
        return (photo.scheme == 'https' and photo.hostname in ('x.com', 'www.x.com', 'twitter.com', 'www.twitter.com')
                and not photo.username and not photo.password and photo.port is None
                and not photo.query and not photo.fragment and match is not None
                and int(match[1]) <= len(media_keys)
                and (len(urls) > 1 or link.get('media_key') == media_keys[int(match[1]) - 1]))
    except ValueError:
        return False
