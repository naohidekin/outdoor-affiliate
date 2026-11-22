"""Reject accessory destinations for the existing six heater body records.

This is a negative guard only. Passing it supplies no positive product proof;
the catalogue's existing exact brand/model, channel and affiliate checks remain.
"""
import re
from urllib.parse import urlsplit


BODY_IDS = frozenset({
    'heater-koizumi-electric-blanket', 'heater-yamazen-electric-blanket',
    'heater-corona-fh-cpf25a', 'stove-paseco-wkh3100s',
    'stove-alpaca-ts77nc', 'stove-toyotomi-rb251',
})
KNOWN_ACCESSORIES = {
    ('item.rakuten.co.jp', '/paseco/reflector/'),
    ('item.rakuten.co.jp', '/minatodenk/mt-0025081/'),
}


def is_accessory_destination(product_id, title, final_url):
    if product_id not in BODY_IDS:
        return False
    url = urlsplit(final_url)
    if (url.hostname, url.path.rstrip('/') + '/') in KNOWN_ACCESSORIES:
        return True
    # A supplied bag is distinct from a listing whose main item IS the bag.
    # Removing only the explicit bundle phrase cannot create positive proof.
    text = re.sub(r'(?:専用)?(?:収納)?(?:バッグ|ケース|反射板)(?:付き|付属|付|同梱)', '', title)
    if re.search(r'反射板|リフレクター|ストーブバッグ|収納(?:バッグ|ケース)|替え?芯|交換芯|'
                 r'本体(?:なし|別売)|本体は付属しません|本体を含まない|'
                 r'reflector|replacement\s+wick|carrying\s+(?:bag|case)|case\s+only', text, re.I):
        return True
    return bool(re.search(r'(?:専用|対応機種|対応モデル|適合機種)[\s　:：()（）-]*'
                          r'(?:バッグ|ケース)|(?:バッグ|ケース)[\s　()（）]*'
                          r'(?:専用|対応機種|対応モデル|適合機種)', text))
