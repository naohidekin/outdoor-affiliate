"""Offline synthetic contracts, not verification of live manufacturer products."""
import copy
import json
import unittest

from apparel_identity import ApparelIdentityError, apparel_contract, inspect_apparel_page, official_domains
from catalog import Catalog, MAKERS
from test_catalog import PNG, response


BRANDS = (
    (("Arc'teryx", "ARC'TERYX", "Arc’teryx", "ARCTERYX", "アークテリクス"),
     "arcteryx.jp", "Beta", "hardshell"),
    (("MILLET", "ミレー"), "millet.jp", "Drynamic", "base-layer"),
    (("finetrack", "ファイントラック"), "finetrack.com", "Drylayer", "base-layer"),
)


def fixture(brand, host, name, kind):
    # Deliberately synthetic: these codes and options assert no real-world SKU facts.
    url = "https://" + host + "/products/TEST-123"
    product = {"id": "winter-test", "name": name, "brand": brand, "categoryId": kind,
               "specs": {"model": "TEST-123", "gender": "Men's", "apparelClass": kind,
                         "optionState": "selectable"},
               "imageUrl": "https://" + host + "/images/TEST-123.png"}
    node = {"@context": "https://schema.org", "@type": "Product", "url": url,
            "brand": {"name": brand}, "model": "TEST-123", "gender": "Men's",
            "color": ["Black"], "size": ["M"], "image": product["imageUrl"]}
    return product, url, node


def source(node):
    return '<script type="application/ld+json">' + json.dumps(node) + '</script>'


def gather(product, url, node, headers=None):
    calls = []

    def fetch(target, *_):
        calls.append(target)
        if target == product["imageUrl"]:
            return response(PNG, "image/png")
        return response(source(node), status=302 if headers else 200, headers=headers)

    result = Catalog({}, fetch, source_hints={product["id"]: [url]}).gather(
        {"productIds": [product["id"]]}, {"products": [product]})
    return result, calls


def maker_refs(result):
    return [ref for ref in result["references"] if ref["kind"] == "manufacturer"]


class ApparelWinterBrandsTests(unittest.TestCase):
    def test_explicit_aliases_and_primary_hosts(self):
        for aliases, domain, name, kind in BRANDS:
            for brand in aliases:
                for host in (domain, "www." + domain):
                    with self.subTest(brand=brand, host=host):
                        product, url, node = fixture(brand, host, name, kind)
                        self.assertEqual((domain,), official_domains(product))
                        self.assertEqual((domain,), MAKERS[brand.casefold()])
                        self.assertEqual("TEST-123", apparel_contract(product)["model"])
                        result, calls = gather(product, url, node)
                        self.assertEqual(1, len(maker_refs(result)))
                        self.assertTrue(result["checks"]["facts"])
                        self.assertTrue(result["checks"]["images"])
                        self.assertIn(url, calls)

    def test_deceptive_hosts_and_host_strings_never_fetch_as_manufacturer(self):
        for aliases, domain, name, kind in BRANDS:
            product, _, node = fixture(aliases[0], domain, name, kind)
            for authority in (domain + ".example", "www." + domain + ".example",
                              "fake-" + domain, domain + "evil.com",
                              domain + "@evil.example", "evil.example@" + domain):
                url = "https://" + authority + "/products/TEST-123"
                bad = dict(node, url=url)
                with self.subTest(domain=domain, authority=authority):
                    result, calls = gather(product, url, bad)
                    self.assertFalse(maker_refs(result))
                    self.assertFalse(result["checks"]["facts"])
                    self.assertNotIn(url, calls)

    def test_redirect_to_deceptive_host_is_blocked_before_fetch(self):
        for aliases, domain, name, kind in BRANDS:
            product, url, node = fixture(aliases[0], domain, name, kind)
            destination = "https://" + domain + ".example/products/TEST-123"
            result, calls = gather(product, url, node, {"location": destination})
            self.assertIn(url, calls)
            self.assertNotIn(destination, calls)
            self.assertFalse(maker_refs(result))

    def test_wrong_model_gender_brand_url_and_missing_options_stay_on_hold(self):
        for aliases, domain, name, kind in BRANDS:
            product, url, node = fixture(aliases[0], domain, name, kind)
            for changes in ({"model": "TEST-1234"}, {"gender": "Women's"},
                            {"brand": {"name": "Unknown"}}, {"url": url + "4"},
                            {"color": []}, {"size": []}, {"@type": "WebPage"}):
                with self.subTest(domain=domain, changes=changes):
                    bad = dict(node, **changes)
                    self.assertIsNone(inspect_apparel_page(product, url, source(bad)))
                    result, _ = gather(product, url, bad)
                    self.assertFalse(maker_refs(result))
                    self.assertFalse(result["checks"]["facts"])

    def test_fixed_options_still_require_exact_color_and_size(self):
        for aliases, domain, name, kind in BRANDS:
            product, url, node = fixture(aliases[0], domain, name, kind)
            product["specs"].update(optionState="fixed", color="Black", size="M")
            node.update(color="Black", size="M")
            self.assertIsNotNone(inspect_apparel_page(product, url, source(node)))
            for changes in ({"color": "Blue"}, {"size": "L"}):
                self.assertIsNone(inspect_apparel_page(product, url, source(dict(node, **changes))))

    def test_no_inferred_brand_domains_or_model_names(self):
        for aliases, domain, name, kind in BRANDS:
            product, _, _ = fixture(aliases[0], domain, name, kind)
            for unknown in (domain, "Unknown " + aliases[0]):
                other = dict(product, brand=unknown)
                self.assertEqual((), official_domains(other))
                self.assertNotIn(unknown.casefold(), MAKERS)
                with self.assertRaises(ApparelIdentityError):
                    apparel_contract(other)
            other = copy.deepcopy(product)
            other["specs"]["model"] = name
            with self.assertRaises(ApparelIdentityError):
                apparel_contract(other)


if __name__ == "__main__":
    unittest.main()
