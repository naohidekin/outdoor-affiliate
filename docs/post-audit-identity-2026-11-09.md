# Post-publication merchant identity audit, 2026-11-09

The firepit revision was rendered correctly but merchant checks contained false positives.
- Firepit was absent from positive product-type vocabulary, causing approved full-name substring checks to reject brand parentheses and intervening words.
- Explicit HAKOSUKA was discarded by the numeric-only model extractor.
- TokyoCamp / Tokyo Camp whitespace differed.

Scoped audit fixes: firepit type evidence, whitespace-normalized brand, explicitly named alphabetic model bound to the approved product name.
Do not bypass ASIN/destination/account binding or accessory-only rejection. Missing named model evidence and conflicting firepit size wording remain unverified.

Live checks: Uniflame 683040 Amazon and Rakuten, Snow Peak ST-032RS Rakuten, TokyoCamp HAKOSUKA Rakuten matched. Snow Peak Amazon title contains both L and Sサイズ; TokyoCamp Amazon title lacks HAKOSUKA. These are unverified, not certified wrong links. No product/article/link writes were performed.

Offline validation: 41 post-audit/runtime tests, 30 catalog tests passed. Live read-only diagnostic report is in the runtime reports directory. Use operational PATH including /usr/local/bin for Node raster decoding; bare SSH PATH produces a spurious image verification failure.
