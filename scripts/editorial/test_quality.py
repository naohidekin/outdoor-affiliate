"""Offline editorial gate regression tests. Run: python3 -B -m unittest discover -s scripts/editorial."""
import copy
import unittest

from quality import inspect_bundle, inspect_polish


def bundle():
    return {
        "affiliateConfig": {"amazonPartnerTag": "camp78-22"},
        "article": {
            "id": "a1", "slug": "tent-guide", "title": "テントおすすめ1選",
            "content": "## 選び方\n調査記事です。\n{{comparison:tent-a}}\n{{product:tent-a}}\n"
                       "[設営](/articles/setup) [撤収](/articles/cleanup)",
            "excerpt": "テントの選び方", "metaDescription": "用途に合わせたテント選びを紹介します。" * 5,
            "faqs": [{"question": f"質問{i}？", "answer": "仕様を確認します。"} for i in range(3)],
            "productIds": ["tent-a"], "categoryId": "tent", "author": "ギア男", "eyecatch": None,
        },
        "products": [{"id": "tent-a", "imageUrl": "https://images.example.com/tent.jpg",
                      "affiliateUrl": "https://hb.afl.rakuten.co.jp/ichiba/known-id/?pc=https%3A%2F%2Fitem.rakuten.co.jp%2Fshop%2Ftent%2F",
                      "amazonUrl": "https://www.amazon.co.jp/dp/B012345678/?tag=camp78-22",
                      "asin": "B012345678"}],
        "brief": {"purpose": "選択を支援", "reader": "初心者", "conclusion": "用途で選ぶ",
                  "headings": ["選び方"], "facts": [], "numbers": [], "links": [],
                  "requiredExpressions": [], "protected": [], "style": "ですます",
                  "length": "5000〜8000字", "cta": "チェックを", "format": "comparison"},
        "references": [{"url": "https://maker.example.com/tent", "checkedAt": "2026-11-03T09:00:00+09:00"}],
        "images": [{"productId": "tent-a", "url": "https://images.example.com/tent.jpg", "verified": True}],
    }


class BundleTests(unittest.TestCase):
    def reject(self, data, code):
        result = inspect_bundle(data)
        self.assertFalse(result["passed"], result)
        self.assertTrue(any(code in str(f) for f in result["failures"]), result)

    def test_valid_offline_result_is_not_publication_or_fact_approval(self):
        data = bundle()
        before = copy.deepcopy(data)
        result = inspect_bundle(data)
        self.assertTrue(result["passed"], result)
        self.assertEqual(data, before)
        self.assertTrue(result["mandatory_evidence"])
        self.assertTrue(all(e["status"] == "pending" for e in result["mandatory_evidence"]))

    def test_structure_and_selection_failures(self):
        mutations = [
            ("h1", lambda b: b["article"].update(content="# 重複タイトル\n" + b["article"]["content"])),
            ("h1", lambda b: b["article"].update(content="重複\n===\n" + b["article"]["content"])),
            ("h1", lambda b: b["article"].update(content="<h1>重複</h1>\n" + b["article"]["content"])),
            ("product", lambda b: b["article"].update(content=b["article"]["content"] + "{{ranking:ghost}}")),
            ("product", lambda b: b["article"].update(productIds=["ghost"])),
            ("product", lambda b: b["article"].update(content=b["article"]["content"].replace("{{product:tent-a}}", "{{product: tent-a }}"))),
            ("selection", lambda b: b["article"].update(title="テントおすすめ3選")),
            ("internal_links", lambda b: b["article"].update(content="## 本文\n[設営](/articles/setup)")),
            ("internal_links", lambda b: b["article"].update(content="## 本文\n[x](/articles/setup) [x](/articles/setup)")),
            ("faq", lambda b: b["article"].update(faqs=[])),
            ("meta_description", lambda b: b["article"].update(metaDescription="")),
            ("comparison", lambda b: b["article"].update(content=b["article"]["content"].replace("{{comparison:tent-a}}", ""))),
        ]
        for code, change in mutations:
            with self.subTest(code=code):
                data = bundle()
                change(data)
                self.reject(data, code)

    def test_missing_channel_requires_explicit_bound_na_evidence(self):
        data = bundle()
        data["products"][0]["amazonUrl"] = ""
        self.reject(data, "purchase")
        data["purchaseEvidence"] = [{"productId": "tent-a", "channel": "amazon", "status": "NA",
                                     "reason": "対象型番の取扱なし", "checkedAt": "2026-11-03T09:00:00+09:00",
                                     "reviewedBy": "editor"}]
        self.assertTrue(inspect_bundle(data)["passed"])
        data["purchaseEvidence"][0]["productId"] = "another"
        self.reject(data, "purchase")

    def test_no_valid_purchase_destination_still_fails(self):
        data = bundle()
        data["products"][0].update(amazonUrl="", affiliateUrl="")
        data["purchaseEvidence"] = [{"productId": "tent-a", "channel": c, "status": "NA", "reason": "取扱なし",
                                    "checkedAt": "2026-11-03T09:00:00+09:00", "reviewedBy": "editor"}
                                   for c in ("amazon", "rakuten")]
        self.reject(data, "purchase")

    def test_affiliate_identity_and_optional_yahoo(self):
        for field, value in [
            ("affiliateUrl", "https://hb.afl.rakuten.co.jp.evil.com/ichiba/a/"),
            ("amazonUrl", "https://www.amazon.co.jp/dp/B012345678"),
            ("amazonUrl", "https://www.amazon.co.jp/dp/INVALID/?tag=camp78-22"),
            ("amazonUrl", "https://www.amazon.co.jp/dp/B999999999/?tag=camp78-22"),
            ("amazonUrl", "https://www.amazon.co.jp/dp/B012345678/?tag=other-22"),
            ("yahooUrl", "htps://store.shopping.yahoo.co.jp/shop/tent.html"),
        ]:
            with self.subTest(field=field, value=value):
                data = bundle()
                data["products"][0][field] = value
                self.reject(data, "url" if field == "yahooUrl" else "affiliate")
        data = bundle()
        data["products"][0]["yahooUrl"] = "https://store.shopping.yahoo.co.jp/shop/tent.html"
        self.assertTrue(inspect_bundle(data)["passed"])

    def test_unsafe_urls_in_every_surface(self):
        bad = ["http://localhost/x", "https://127.0.0.1/a", "http://[::1]/a", "https://10.0.0.1/a",
               "https://169.254.169.254/a", "https://2130706433/a", "https://127.1/a", "https://0x7f000001/a",
               "javascript:alert(1)", "htps://example.com/x", "https//example.com/x", "www.example.com/x", "//evil.example/x", "https://user:pass@example.com/x",
               "https://example.com\\@localhost/a", "https://printer.local/a"]
        for url in bad:
            with self.subTest(url=url):
                data = bundle()
                data["article"]["content"] += f"\n[外部]({url})"
                self.reject(data, "url")
        for surface in ("images", "references", "products"):
            data = bundle()
            data[surface][0]["url" if surface != "products" else "imageUrl"] = "http://192.168.1.1/x"
            self.reject(data, "url")

    def test_image_evidence_binds_id_and_url_and_boolean(self):
        for patch in ({"verified": False}, {"verified": "true"}, {"productId": "other"}, {"url": "https://example.com/other.jpg"}):
            data = bundle()
            data["images"][0].update(patch)
            self.reject(data, "image")

    def test_reference_requires_timezone_aware_check(self):
        data = bundle()
        data["references"][0]["checkedAt"] = "2026-11-03"
        self.reject(data, "reference")

    def test_images_html_and_unused_definitions_do_not_count_as_article_links(self):
        for links in ("![a](/articles/setup) ![b](/articles/cleanup)",
                      "![a][x] ![b][y]\n[x]: /articles/setup\n[y]: /articles/cleanup",
                      '<a href="/articles/setup">a</a><a href="/articles/cleanup">b</a>',
                      "[a]: /articles/setup\n[b]: /articles/cleanup"):
            data = bundle()
            data["article"]["content"] = "## 内容\n{{comparison:tent-a}}\n" + links
            self.reject(data, "internal_links")

    def test_reference_article_links_count_when_used(self):
        data = bundle()
        data["article"]["content"] = ("## 内容\n{{comparison:tent-a}}\n[設営][x] [撤収][y]\n"
                                        "[x]: /articles/setup\n[y]: /articles/cleanup")
        self.assertTrue(inspect_bundle(data)["passed"])

    def test_boundaries_for_faq_meta_image_hash_brief_and_yahoo(self):
        changes = [
            ("faq", lambda b: b["article"].update(faqs=b["article"]["faqs"] * 2)),
            ("meta_description", lambda b: b["article"].update(metaDescription="あ" * 161)),
            ("image", lambda b: b["images"][0].update(sha256="not-a-hash")),
            ("brief", lambda b: b["brief"].pop("protected")),
            ("purchase", lambda b: b["products"][0].update(yahooAvailable=True)),
        ]
        for code, change in changes:
            data = bundle()
            change(data)
            self.reject(data, code)

    def test_rakuten_and_yahoo_wrappers_reject_private_redirect_targets(self):
        for field, value in (
            ("affiliateUrl", "https://hb.afl.rakuten.co.jp/ichiba/id/?pc=http%3A%2F%2F127.0.0.1%2Fa"),
            ("yahooUrl", "https://ck.jp.ap.valuecommerce.com/servlet/referral?vc_url=http%3A%2F%2F10.0.0.1%2Fa"),
        ):
            data = bundle()
            data["products"][0][field] = value
            self.reject(data, "url")

    def test_extra_catalog_product_is_also_checked(self):
        data = bundle()
        data["products"].append({"id": "other", "imageUrl": "http://localhost/a"})
        self.reject(data, "image")

    def test_malformed_empty_url_and_wrong_channel_do_not_pass(self):
        for field, value in (("imageUrl", []), ("amazonUrl", {}), ("affiliateUrl", 2),
                             ("yahooUrl", "https://unrelated.example.com/a")):
            data = bundle()
            data["products"][0][field] = value
            self.assertFalse(inspect_bundle(data)["passed"])

    def test_malformed_input_fails_closed(self):
        for data in (None, [], {}, {"article": []}, {**bundle(), "products": [None]}, {**bundle(), "images": None}):
            with self.subTest(data=data):
                self.assertFalse(inspect_bundle(data)["passed"])


class PolishTests(unittest.TestCase):
    SOURCE = ("広告: 本記事はアフィリエイト広告を含みます。\n## 選び方\n重さは2.5kgです。\n"
              "{{product:tent-a}}\n{{comparison:tent-a,tent-b}}\n[設営](/articles/setup?q=1#steps)\n"
              "[公式](https://maker.example.com/a_(b))\n[詳細][ref]\n[ref]: ../guide \"説明\"\n"
              "| 項目 | 値 |\n| --- | --- |\n| 重量 | 2.5kg |\n\n"
              "```python\nprint('固定')\n```\n`inline()`\n本文は読みやすいです。")

    def test_only_prose_may_change(self):
        result = inspect_polish(self.SOURCE, self.SOURCE.replace("本文は読みやすいです。", "本文をすらすら読めます。"))
        self.assertTrue(result["passed"], result)

    def test_protected_content_cannot_change_or_disappear(self):
        for old, new in [("## 選び方", "## 選択"), ("2.5kg", "3kg"), ("tent-a", "tent-c"),
                         ("/articles/setup?q=1#steps", "/articles/other"), ("a_(b)", "a_(c)"),
                         ("../guide", "../other"), ("| 項目 | 値 |", "| 種類 | 値 |"),
                         ("print('固定')", "print('変更')"), ("`inline()`", "`other()`"),
                         ("広告: 本記事はアフィリエイト広告を含みます。", ""),
                         ("[ref]: ../guide", "[other]: ../guide")]:
            with self.subTest(old=old):
                self.assertFalse(inspect_polish(self.SOURCE, self.SOURCE.replace(old, new))["passed"])

    def test_relative_destinations_with_balanced_parentheses_and_spaces(self):
        for source, candidate in [('[x](../a_(b))', '[x](../a_(c))'),
                                  ('[x](<../a b>)', '[x](<../a c>)'),
                                  ('<a href="../a">x</a>', '<a href="../b">x</a>'),
                                  ('見出し\n---\n本文', '別見出し\n---\n本文')]:
            self.assertFalse(inspect_polish(source, candidate)["passed"])

    def test_order_and_multiplicity_are_preserved(self):
        for source, candidate in [("## A\n## B", "## B\n## A"),
                                  ("[a](/a) [b](/b)", "[b](/b) [a](/a)"),
                                  ("{{product:a}}\n## B", "## B\n{{product:a}}"),
                                  ("重量2kg、2kg", "重量2kg")]:
            self.assertFalse(inspect_polish(source, candidate)["passed"])

    def test_reference_usage_cannot_reorder_or_vanish(self):
        source = "[設営][a] [撤収][b]\n\n[a]: ../setup\n[b]: ../cleanup"
        for candidate in (source.replace("[設営][a] [撤収][b]", "[撤収][b] [設営][a]"),
                          source.replace("[設営][a]", "設営")):
            self.assertFalse(inspect_polish(source, candidate)["passed"])

    def test_multibacktick_inline_code_and_nested_heading_preserved(self):
        for source, candidate in [("``some ` code``", "``other ` code``"),
                                  ("> ## 選び方", "> ## 比較"),
                                  ("- ## 選び方", "- ## 比較"),
                                  ("<code>fixed</code>", "<code>changed</code>"),
                                  ("定員は三名です", "定員は四名です"),
                                  ("容量は20mlです", "容量は20mです")]:
            self.assertFalse(inspect_polish(source, candidate)["passed"])

    def test_body_strings_only_and_empty_candidate_rejected(self):
        for source, candidate in [({}, "body"), ("body", {}), ("body", ""), ("", "")]:
            self.assertFalse(inspect_polish(source, candidate)["passed"])


if __name__ == "__main__":
    unittest.main()
