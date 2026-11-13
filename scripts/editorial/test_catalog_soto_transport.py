"""Public ST-233 variant headers, no image-identity relaxation."""
import unittest
from catalog import Catalog

class SotoTransportTests(unittest.TestCase):
    def test_exact_product_page_only_and_redirect_not_forwarded(self):
        seen=[]
        def fetch(url,headers,timeout):
            seen.append((url,headers))
            if len(seen)==1:return {'status':302,'headers':{'location':'https://other.example/final'},'body':b''}
            return {'status':200,'headers':{'content-type':'text/html'},'body':b'public'}
        c=Catalog({},fetcher=fetch)
        c.request('https://soto.shinfuji.co.jp/products/st-233/')
        self.assertEqual(seen[0][1],{'User-Agent':'Mozilla/5.0','Accept':'text/html'})
        self.assertEqual(seen[1][1],{})
        for url in ['https://soto.shinfuji.co.jp/products/st-340/','https://soto.shinfuji.co.jp/wp-content/uploads/products/ST-233.jpg','https://other.example/products/st-233/']:
            c.request(url);self.assertEqual(seen[-1][1],{})

    def test_explicit_headers_preserved(self):
        seen=[]
        def fetch(url,headers,timeout):
            seen.append(headers);return {'status':200,'headers':{'content-type':'text/html'},'body':b'public'}
        Catalog({},fetcher=fetch).request('https://soto.shinfuji.co.jp/products/st-233/',{'User-Agent':'explicit','Accept':'custom'})
        self.assertEqual(seen[0],{'User-Agent':'explicit','Accept':'custom'})
