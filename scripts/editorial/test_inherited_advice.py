"""Offline inherited-template binding, including visible disclaimer and DOM drift."""
import copy
import unittest
from inherited_advice import advice_evidence, validate_presentation

ADVICE = '<aside aria-label="医師からのアドバイス" class="unchanged"><h3>医師から一言：既存の注意</h3><p>既存の安全情報。</p><ul><li>既存の注意事項</li></ul><p>※一般的な医学情報です。症状がある場合は医療機関を受診してください。</p></aside>'
FILES = {'src/app/articles/[slug]/page.tsx':'a'*64,'src/components/MedicalAdvice.tsx':'b'*64,'src/lib/medicalAdviceData.ts':'c'*64}


def context(slug='firepit-beginner-guide'):
    observed=advice_evidence(ADVICE)
    return dict(schemaVersion=1,kind='unchanged_medical_advice',slug=slug,html=ADVICE,
                domSha256=observed['domSha256'],renderedText=observed['text'],
                templateFiles=FILES,clinicalReverified=False,unchanged=True)


class InheritedAdviceTests(unittest.TestCase):
    def test_actual_dom_keeps_disclaimer_and_exact_text_and_attributes(self):
        result=advice_evidence(ADVICE)
        self.assertIn('※一般的な医学情報',result['text'])
        self.assertNotEqual(result['domSha256'],advice_evidence(ADVICE.replace('既存の安全情報','変更された情報'))['domSha256'])
        self.assertNotEqual(result['domSha256'],advice_evidence(ADVICE.replace('unchanged','different'))['domSha256'])
        self.assertEqual(context(),validate_presentation(context(),'firepit-beginner-guide'))

    def test_duplicate_hidden_or_missing_dom_and_false_clinical_claim_refused(self):
        for html in ('<p>none</p>',ADVICE+ADVICE,'<script>'+ADVICE+'</script>'):
            with self.assertRaises(ValueError):advice_evidence(html)
        for key,value in (('clinicalReverified',True),('domSha256','0'*64),('renderedText','not visible'),('slug','wrong')):
            value_context=copy.deepcopy(context());value_context[key]=value
            with self.assertRaises(ValueError):validate_presentation(value_context,'firepit-beginner-guide')

    def test_full_page_selects_only_real_reading_context_not_hydration_or_sidebar(self):
        html='<html><body><aside aria-label="医師からのアドバイス">sidebar</aside><main><article><div id="article-reading-content">'+ADVICE+'</div></article></main><script>'+ADVICE+'</script></body></html>'
        self.assertEqual(advice_evidence(ADVICE)['domSha256'],advice_evidence(html,full_page=True)['domSha256'])
        self.assertEqual(advice_evidence(ADVICE)['text'],advice_evidence(html,full_page=True)['text'])
        with self.assertRaises(ValueError):advice_evidence(html.replace('article-reading-content','other'),full_page=True)


if __name__=='__main__':unittest.main()
