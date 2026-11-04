"""Offline regression tests for X's repeated terminal photo URL entities."""
import copy
import unittest

from x_readback import exact_x_text


POST_ID = '2117838625681641686'
TOKEN = 'https://t.co/KP6czEL5FU'
MEDIA_KEYS = ['3_2117838614529036288', '3_2117838620484943872']
# The approved body was not supplied: preserve its observed span using a stand-in.
BODY = 'あ' * 163


def photo_post(body=BODY):
    return {
        'id': POST_ID,
        'text': body + ' ' + TOKEN,
        'mediaKeys': MEDIA_KEYS.copy(),
        'urls': [dict(url=TOKEN, start=164, end=187,
                      expanded_url=f'https://x.com/camp_gear_lab/status/{POST_ID}/photo/1',
                      media_key=key) for key in MEDIA_KEYS],
    }


class ExactXTextTests(unittest.TestCase):
    def test_observed_two_image_entity_shape(self):
        self.assertTrue(exact_x_text(photo_post(), BODY))
        post = photo_post()
        post['urls'].reverse()
        self.assertTrue(exact_x_text(post, BODY))

    def test_duplicate_key(self):
        post = photo_post()
        post['urls'][1]['media_key'] = MEDIA_KEYS[0]
        self.assertFalse(exact_x_text(post, BODY))

    def test_unbound_or_malformed_key(self):
        for key in ('3_other', '', None, [], True):
            with self.subTest(key=key):
                post = photo_post()
                post['urls'][1]['media_key'] = key
                self.assertFalse(exact_x_text(post, BODY))

    def test_attachment_keys_must_match_exactly(self):
        for keys in ([], MEDIA_KEYS[:1], MEDIA_KEYS + ['3_extra'],
                     [MEDIA_KEYS[0]] * 2, [MEDIA_KEYS[0], None]):
            with self.subTest(keys=keys):
                post = photo_post()
                post['mediaKeys'] = keys
                self.assertFalse(exact_x_text(post, BODY))

    def test_distinct_url(self):
        for field, value in (('url', 'https://t.co/Other'),
                             ('expanded_url', f'https://x.com/camp_gear_lab/status/{POST_ID}/photo/2')):
            with self.subTest(field=field):
                post = photo_post()
                post['urls'][1][field] = value
                self.assertFalse(exact_x_text(post, BODY))

    def test_different_or_malformed_offsets(self):
        for field, value in (('start', 163), ('end', 188), ('start', 164.0),
                             ('end', 187.0), ('start', True), ('end', None)):
            with self.subTest(field=field, value=value):
                post = photo_post()
                post['urls'][1][field] = value
                self.assertFalse(exact_x_text(post, BODY))

    def test_foreign_post_and_malformed_raw_urls(self):
        valid = photo_post()['urls'][0]['expanded_url']
        for url in (valid.replace(POST_ID, '999'), valid.replace('x.com', 'evil.example'),
                    ' ' + valid, '\n' + valid, valid + '\r', valid + '\x00',
                    valid + '?x=1', valid + '#fragment',
                    valid.replace('x.com', 'x.com\\evil.example'),
                    valid.replace('https:', 'http:'), valid.replace('/photo/1', '/photo/3')):
            with self.subTest(url=url):
                post = photo_post()
                for entity in post['urls']:
                    entity['expanded_url'] = url
                self.assertFalse(exact_x_text(post, BODY))

    def test_only_exact_terminal_suffix(self):
        for text in (BODY + TOKEN, BODY + '  ' + TOKEN, BODY + ' ' + TOKEN + ' ',
                     BODY + ' ' + TOKEN + ' extra', 'edited ' + BODY + ' ' + TOKEN):
            with self.subTest(text=text):
                post = photo_post()
                post['text'] = text
                self.assertFalse(exact_x_text(post, BODY))

    def test_identical_but_wrong_spans(self):
        post = photo_post()
        for entity in post['urls']:
            entity.update(start=163, end=186)
        self.assertFalse(exact_x_text(post, BODY))

    def test_codepoint_and_utf16_offsets(self):
        body = '🏕' + BODY[1:]
        for shift in (0, 1):
            with self.subTest(shift=shift):
                post = photo_post(body)
                for entity in post['urls']:
                    entity.update(start=164 + shift, end=187 + shift)
                self.assertTrue(exact_x_text(post, body))

    def test_malformed_entities(self):
        for entity in (None, [], 'url', {}, {'media_key': MEDIA_KEYS[1]}):
            with self.subTest(entity=entity):
                post = photo_post()
                post['urls'][1] = entity
                self.assertFalse(exact_x_text(post, BODY))

    def test_single_photo_keeps_index_binding(self):
        post = photo_post()
        post['urls'] = post['urls'][:1]
        self.assertTrue(exact_x_text(post, BODY))
        post['urls'][0]['media_key'] = MEDIA_KEYS[1]
        self.assertFalse(exact_x_text(post, BODY))

    def test_exact_text_and_single_shortened_reply(self):
        self.assertTrue(exact_x_text({'text': BODY}, BODY))
        url = 'https://camp-gear-lab.com/articles/test'
        post = dict(id=POST_ID, text=TOKEN, mediaKeys=[], urls=[
            dict(url=TOKEN, expanded_url=url, start=0, end=len(TOKEN))])
        self.assertTrue(exact_x_text(post, url))
        post['urls'].append(copy.deepcopy(post['urls'][0]))
        self.assertFalse(exact_x_text(post, url))


if __name__ == '__main__':
    unittest.main()
