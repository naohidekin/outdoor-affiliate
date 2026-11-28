import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ledger import fingerprint
import article_verification_receipt as proof


def bundle():
    source_sha = "a" * 64
    renderer = {"contentHash": "b" * 64,
                "displayText": {"brand": "Camp Gear Lab", "label": "比較ガイド", "heading": "選び方",
                                "productNames": ["製品A"], "title": "製品Aの選び方"},
                "renderEngine": "Chrome/test", "sourceCrops": [{"productId": "p1",
                    "sha256": source_sha, "displaySha256": "c" * 64,
                    "originalWidth": 500, "originalHeight": 500}]}
    card = {"url": "https://db.example/card.png", "finalUrl": "https://db.example/card.png",
            "sha256": "d" * 64, "size": 100, "contentType": "image/png",
            "width": 1200, "height": 630, "templateVersion": "card-v1",
            "sources": [{"productId": "p1", "sha256": source_sha}],
            "rendererEvidence": renderer}
    return {"article": {"id": "article", "slug": "candidate", "title": "Candidate",
                        "content": "[春の服装](/articles/spring-guide)", "productIds": ["p1"],
                        "generationMeta": {"socialCard": copy.deepcopy(card)}},
            "products": [{"id": "p1", "name": "製品A", "imageUrl": "https://maker.example/p.png",
                          "price": 0, "rating": 0, "availability": " Unknown ",
                          "amazonUrl": "https://www.amazon.co.jp/dp/example"}],
            "images": [{"productId": "p1", "url": "https://maker.example/p.png",
                        "sha256": source_sha, "size": 100, "verified": True},
                       dict(card, role="social-card", verified=True)], "references": []}


def preview():
    presentation = [{"productId": "p1", "componentCount": 2, "priceInput": 0,
                     "ratingInput": 0, "availabilityInput": " Unknown ",
                     "merchantCheckDisplayed": True, "zeroPriceDisplayed": False,
                     "ratingClaimDisplayed": False, "availabilityClaimDisplayed": False}]
    return {"passed": True, "status": "passed", "failures": [],
            "clicksVerified": {name: [{"productId": "p1", "store": "amazon",
                "href": "https://www.amazon.co.jp/dp/example", "placement": "product_card"}]
                for name in ("desktop", "mobile")},
            "imageReadback": [{"url": "https://maker.example/p.png", "sha256": "a" * 64,
                               "size": 100, "verified": True}],
            "viewportEvidence": {name: {"internalLinks": ["/articles/spring-guide"],
                                        "allAnchorsVerified": True}
                                 for name in ("desktop", "mobile")},
            "productPresentation": {name: copy.deepcopy(presentation)
                                    for name in ("desktop", "mobile")}}


class Request:
    def __init__(self): self.final = None; self.status = 200
    def __call__(self, url, headers, **kwargs):
        body = ("<html><head><title>春キャンプ服装</title>"
                "<meta name='description' content='春の重ね着を確認します'>"
                "<link rel='canonical' href='" + url + "'>"
                "</head><body><h1><span>春キャンプ服装</span></h1><h2>重ね着</h2></body></html>").encode()
        return {"url": self.final or url, "status": self.status,
                "headers": {"content-type": "text/html; charset=utf-8"}, "body": body}


class ReceiptTests(unittest.TestCase):
    def make(self):
        value = bundle(); job = {"id": "job", "bundle": value}
        gathered = {"checks": {"facts": True, "images": True, "affiliate": True}}
        return proof.build(job, value, gathered, preview(),
                           {"passed": True, "risks": [], "scope": "candidate_article_only"},
                           {"passed": True}, {"source": "bound"}, Request())

    def test_exact_revision_receipt_is_compact_allowlisted_and_projectable(self):
        receipt = self.make(); revision = fingerprint(bundle())
        self.assertEqual(revision, receipt["revision"])
        self.assertEqual(5, len(receipt["checks"]))
        self.assertEqual("春の重ね着を確認します", receipt["internalTargets"][0]["excerpt"])
        raw = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        self.assertLessEqual(len(raw), proof.MAX_RECEIPT_BYTES)
        for forbidden in ("outputDir", "desktop.png", "<html", "/private/"):
            self.assertNotIn(forbidden, raw.decode())
        projected = proof.projection(receipt, "job", revision)
        self.assertEqual(fingerprint(receipt), projected["receiptSha256"])
        self.assertNotIn("productPresentation", json.dumps(projected, ensure_ascii=False))
        self.assertIn("presentationSha256",
                      projected["checks"]["render"]["viewports"]["desktop"])

    def test_redirect_unpublished_or_revision_drift_fail_closed(self):
        value = bundle(); job = {"id": "job"}
        gathered = {"checks": {"facts": True, "images": True, "affiliate": True}}
        for change in ("redirect", "status", "render"):
            request = Request(); candidate_preview = preview()
            if change == "redirect": request.final = "https://camp-gear-lab.com/articles/other"
            if change == "status": request.status = 404
            if change == "render": candidate_preview["viewportEvidence"]["desktop"]["allAnchorsVerified"] = False
            with self.subTest(change=change), self.assertRaises(ValueError):
                proof.build(job, value, gathered, candidate_preview,
                            {"passed": True, "risks": []}, {"passed": True}, {}, request)
        receipt = self.make()
        with self.assertRaises(ValueError): proof.validate(receipt, "job", "0" * 64)

    def test_immutable_0600_receipt_reuses_only_identical_bytes(self):
        receipt = self.make()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "proof.json"
            sha = proof.write_once(path, receipt)
            self.assertEqual(fingerprint(receipt), sha)
            self.assertEqual(0o600, path.stat().st_mode & 0o777)
            self.assertEqual(sha, proof.write_once(path, copy.deepcopy(receipt)))
            changed = copy.deepcopy(receipt); changed["checks"]["facts"]["passed"] = False
            with self.assertRaisesRegex(ValueError, "immutable_changed"):
                proof.write_once(path, changed)

    def test_empty_or_misbound_typed_proof_never_passes_boolean_shell(self):
        receipt = self.make(); revision = receipt["revision"]
        mutations = []
        for path in (("productBindings",), ("checks", "images", "readback"),
                     ("checks", "affiliate", "viewports", "desktop", "bindings"),
                     ("checks", "render", "viewports", "mobile", "productPresentation"),
                     ("checks", "images", "socialCard", "sources")):
            changed = copy.deepcopy(receipt); target = changed
            for key in path[:-1]: target = target[key]
            target[path[-1]] = []; mutations.append(path)
            with self.subTest(path=path), self.assertRaises(ValueError):
                proof.validate(changed, "job", revision)
        self.assertEqual(5, len(mutations))

    def test_social_card_crop_bytes_display_hash_and_dimensions_are_exactly_bound(self):
        for mutation in ("crop_sha", "display_sha", "width_zero", "width_bool"):
            receipt = self.make()
            crop = receipt["checks"]["images"]["socialCard"]["renderer"]["sourceCrops"][0]
            if mutation == "crop_sha": crop["sha256"] = "0" * 64
            if mutation == "display_sha": crop["displaySha256"] = "not-a-sha"
            if mutation == "width_zero": crop["originalWidth"] = 0
            if mutation == "width_bool": crop["originalWidth"] = True
            with self.subTest(mutation=mutation), self.assertRaisesRegex(
                    ValueError, "social_card_sources"):
                proof.validate(receipt, "job", receipt["revision"])

    def test_social_card_two_source_ids_are_unique_counted_and_ordered(self):
        receipt = self.make(); second_sha = "e" * 64
        second = copy.deepcopy(receipt["productBindings"][0])
        second.update(productId="p2", name="製品B", imageSha256=second_sha,
                      imageUrlSha256="f" * 64, channels=[])
        receipt["productBindings"].append(second)
        receipt["checks"]["images"]["readback"].append({
            "productId": "p2", "urlSha256": "f" * 64,
            "sha256": second_sha, "size": 200})
        for view in receipt["checks"]["render"]["viewports"].values():
            item = copy.deepcopy(view["productPresentation"][0]); item["productId"] = "p2"
            view["productPresentation"].append(item)
        card = receipt["checks"]["images"]["socialCard"]
        card["sources"].append({"productId": "p2", "sha256": second_sha})
        crop = copy.deepcopy(card["renderer"]["sourceCrops"][0])
        crop.update(productId="p2", sha256=second_sha, displaySha256="9" * 64)
        card["renderer"]["sourceCrops"].append(crop)
        card["renderer"]["displayText"]["productNames"].append("製品B")
        proof.validate(receipt, "job", receipt["revision"])
        card["renderer"]["sourceCrops"].reverse()
        with self.assertRaisesRegex(ValueError, "social_card_sources"):
            proof.validate(receipt, "job", receipt["revision"])

    def test_unknown_stock_sentinels_are_conservative_and_source_rebinds(self):
        for sentinel in (None, "", " UNKNOWN ", "Unknown", "不明", "未確認", "記載なし", "N/A"):
            receipt = self.make(); receipt["productBindings"][0]["availability"] = sentinel
            for view in receipt["checks"]["render"]["viewports"].values():
                view["productPresentation"][0]["availabilityInput"] = sentinel
                view["productPresentation"][0]["availabilityClaimDisplayed"] = True
            with self.subTest(sentinel=sentinel), self.assertRaisesRegex(ValueError, "unknown_stock"):
                proof.validate(receipt, "job", receipt["revision"])

        value = bundle(); source = {
            "normalizedSource": {
                "products": copy.deepcopy(value["products"]),
                "references": copy.deepcopy(value["references"]),
                "images": [copy.deepcopy(value["images"][0])],
            },
            "products": copy.deepcopy(value["products"]),
            "references": copy.deepcopy(value["references"]),
            "images": [copy.deepcopy(value["images"][0])],
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.json"; sha = proof.write_source_once(path, source)
            self.assertEqual(source, proof.load_source(path, sha, value))
            changed = copy.deepcopy(value); changed["products"][0]["name"] = "drift"
            with self.assertRaisesRegex(ValueError, "source_products"):
                proof.load_source(path, sha, changed)
            changed = copy.deepcopy(value); changed["images"][0]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "source_images"):
                proof.load_source(path, sha, changed)

    def test_copied_bindings_cannot_mask_tampered_normalized_source(self):
        value = bundle()
        base = {"products": copy.deepcopy(value["products"]),
                "references": [{"url": "https://maker.example/source",
                                "model": "製品A", "text": "確認済み本文"}],
                "images": [copy.deepcopy(value["images"][0])]}
        value["references"] = copy.deepcopy(base["references"])
        for kind in ("product", "reference", "image"):
            source = {"normalizedSource": copy.deepcopy(base),
                      "products": copy.deepcopy(base["products"]),
                      "references": copy.deepcopy(base["references"]),
                      "images": copy.deepcopy(base["images"])}
            if kind == "product": source["normalizedSource"]["products"][0]["name"] = "wrong model"
            if kind == "reference": source["normalizedSource"]["references"][0]["text"] = "unsupported"
            if kind == "image": source["normalizedSource"]["images"][0]["sha256"] = "0" * 64
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "source.json"; sha = proof.write_source_once(path, source)
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    proof.load_source(path, sha, value)

    def test_eleven_products_keep_full_private_and_public_projection_within_caps(self):
        value = bundle(); value["article"]["content"] = (
            "日本語の比較本文です。"
            "[春キャンプの服装ガイド](/articles/spring-camp-layering-guide)"
            "[雨天時の装備チェック](/articles/rain-camp-equipment-check)"
            "[初心者向けテント選び](/articles/beginner-tent-selection-guide)")
        value["article"]["productIds"] = []
        value["products"] = []; value["images"] = [value["images"][-1]]
        observed = {name: [] for name in ("desktop", "mobile")}
        presentations = {name: [] for name in ("desktop", "mobile")}
        readback = []
        for index in range(11):
            pid = "p" + str(index); image_sha = hashlib.sha256(pid.encode()).hexdigest()
            image_url = "https://maker.example/" + pid + ".png"
            product = {"id": pid, "name": "製品" + str(index), "imageUrl": image_url,
                       "price": 0, "rating": 0, "availability": "unknown",
                       "amazonUrl": "https://www.amazon.co.jp/dp/" + pid,
                       "affiliateUrl": "https://item.rakuten.co.jp/shop/" + pid}
            value["article"]["productIds"].append(pid); value["products"].append(product)
            value["images"].insert(index, {"productId": pid, "url": image_url,
                "sha256": image_sha, "size": 100 + index, "verified": True})
            readback.append({"url": image_url, "sha256": image_sha,
                             "size": 100 + index, "verified": True})
            for name in observed:
                observed[name].extend([{"productId": pid, "store": "amazon",
                    "href": product["amazonUrl"], "placement": "comparison_table"},
                    {"productId": pid, "store": "rakuten", "href": product["affiliateUrl"],
                     "placement": "comparison_table"}])
                presentations[name].append({"productId": pid, "componentCount": 1,
                    "priceInput": 0, "ratingInput": 0, "availabilityInput": "unknown",
                    "merchantCheckDisplayed": True, "zeroPriceDisplayed": False,
                    "ratingClaimDisplayed": False, "availabilityClaimDisplayed": False})
        card = value["article"]["generationMeta"]["socialCard"]
        card["sources"] = [{"productId": "p0", "sha256": value["images"][0]["sha256"]}]
        card["rendererEvidence"]["sourceCrops"] = [{"productId": "p0",
            "sha256": value["images"][0]["sha256"], "displaySha256": "c" * 64,
            "originalWidth": 500, "originalHeight": 500}]
        card["rendererEvidence"]["displayText"]["productNames"] = ["製品0"]
        value["images"][-1] = dict(card, role="social-card", verified=True)
        candidate_preview = preview(); candidate_preview["clicksVerified"] = observed
        candidate_preview["productPresentation"] = presentations
        candidate_preview["imageReadback"] = readback
        for name in ("desktop", "mobile"):
            candidate_preview["viewportEvidence"][name]["internalLinks"] = [
                "/articles/spring-camp-layering-guide",
                "/articles/rain-camp-equipment-check",
                "/articles/beginner-tent-selection-guide"]
        receipt = proof.build({"id": "job"}, value,
            {"checks": {"facts": True, "images": True, "affiliate": True}}, candidate_preview,
            {"passed": True, "risks": []}, {"passed": True}, {"source": "bound"}, Request())
        self.assertLessEqual(len(json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":")).encode()), proof.MAX_RECEIPT_BYTES)
        projected = proof.projection(receipt, "job", fingerprint(value))
        projected_size = len(json.dumps(projected, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode())
        self.assertEqual(3, len(projected["internalTargets"]))
        self.assertNotIn("productPresentation", json.dumps(projected, ensure_ascii=False))
        self.assertLessEqual(projected_size, proof.MAX_PROJECTION_BYTES)


if __name__ == "__main__": unittest.main()
