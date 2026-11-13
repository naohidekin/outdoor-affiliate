"""New, unstaged articles only: diagnostic preparation, never catalog mutation.

Current evidence schema proves specifications/images/routes, not price/rating.
Zero means hidden display, never free. A pass is not verified-price evidence.
"""
import math
from ledger import fingerprint


def build_prewrite_plan(job, gathered):
    if job.get('kind') == 'article_revision' or job.get('bundle') is not None or job.get('revision') is not None:
        return {'status':'not_applicable'}
    products = gathered.get('products')
    evidence = gathered.get('evidence', {}).get('products')
    ids = job.get('theme', {}).get('productIds')
    if (not isinstance(products,list) or not products or not isinstance(evidence,list)
            or not isinstance(ids,list) or not ids or any(not isinstance(x,str) or not x for x in ids)
            or len(ids)!=len(set(ids)) or any(not isinstance(p,dict) for p in products)
            or [p.get('id') for p in products]!=ids or any(not isinstance(e,dict) for e in evidence)
            or [e.get('productId') for e in evidence]!=ids):
        raise ValueError('prewrite_display_evidence_structure_invalid')
    proposals=[]
    for product,proof in zip(products,evidence):
        if (not isinstance(proof.get('unverifiedFields'),list)
                or any(not isinstance(x,str) for x in proof['unverifiedFields'])):
            raise ValueError('prewrite_display_evidence_structure_invalid')
        changes={}
        for field in ('price','rating'):
            value=product.get(field)
            if type(value) not in (int,float) or (type(value) is float and not math.isfinite(value)) or value<0:
                raise ValueError('prewrite_display_numeric_structure_invalid')
            # Absence from unverifiedFields is not independent verification.
            # No price/rating evidence schema is approved by this component.
            if value>0:changes[field]=0
        if changes:
            proposals.append({'productId':product['id'],'baseProductFingerprint':fingerprint(product),
                'proposedDisplayChanges':changes,'reason':'price_rating_evidence_not_supported'})
    return {'status':'correction_required' if proposals else 'display_safe',
        'articleId':job['id'],'sourceFingerprint':fingerprint({'products':products,'evidence':evidence}),
        'proposals':proposals,'approved':False,'applied':False,'priceVerified':False,'ratingVerified':False,
        'zeroMeaning':'0は非表示を意味し、無料ではありません。',
        'instructions':'未承認・未適用の候補です。元商品・既存記事・CMSを自動変更しません。共有商品の修正は既存記事への影響を確認し正規承認経路へ。'}
