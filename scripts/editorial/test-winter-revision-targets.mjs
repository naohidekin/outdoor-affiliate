import test from 'node:test';
import assert from 'node:assert/strict';
import {articleFields, bundleHash, productRow} from './publish.mjs';
import {executeRevision} from './revision-publisher.mjs';
import {adviceEvidence, TEMPLATE_FILES} from './template-context.mjs';

const targets = [
  ['article-024', 'firepit-beginner-guide'],
  ['article-005', 'single-burner-ranking'],
  ['article-002', 'landlock-vs-landnest-shelter'],
  ['3082b43c-a612-4ae0-926e-8bd86c6ab84e', 'autumn-camp-classic-fleece-comparison'],
  ['winter-camp-heating-comparison-p1', 'winter-camp-heating-comparison'],
  ['camp-kerosene-stove-8xzl2p', 'camp-kerosene-stove-comparison'],
  ['article-010', 'rainwear-ranking'],
  ['article-043', 'autumn-camp-clothing-layering-guide'],
];

function fixture(id, slug) {
  const stamp = '2026-11-01T00:00:00+09:00';
  const baseArticle = {id, slug, status:'published', title:'Fixture', content:'Fixture source',
    productIds:['fixture-product'], createdAt:stamp, updatedAt:stamp, publishedAt:stamp};
  const product = {id:'fixture-product', name:'Fixture', brand:'Fixture', categoryId:'tent',
    specs:{}, imageUrl:'https://images.example/fixture.png', updatedAt:stamp};
  const html = '<aside aria-label="医師からのアドバイス"><h3>既存の注意</h3><p>既存の安全情報。</p></aside>';
  const observed = adviceEvidence(html);
  const context = {kind:'article_revision', baseArticle, baseHash:bundleHash(baseArticle),
    changeSummary:'Fixture correction', editorialCorrectionInstructions:'Fixture only', verifiedAuthorFacts:[],
    targetProductIds:[product.id], productRemovalReasons:{}, baseProducts:[product],
    candidateProducts:[structuredClone(product)], productPatches:[]};
  const bundle = {article:{...structuredClone(baseArticle), content:'Fixture correction', author:'ギア男'},
    products:context.candidateProducts, images:[{productId:product.id, url:product.imageUrl, verified:true}],
    revisionContext:context, inheritedPresentationContext:{schemaVersion:1, kind:'unchanged_medical_advice',
      slug, html, domSha256:observed.domSha256, renderedText:observed.text,
      templateFiles:Object.fromEntries(TEMPLATE_FILES.map(f=>[f,'a'.repeat(64)])),
      clinicalReverified:false, unchanged:true}};
  const state = {reads:0, article:Object.fromEntries(Object.entries(articleFields).map(([k,v])=>[v,baseArticle[k] ?? null])),
    product:{...productRow(product), xmin:'10'}};
  const deps = {lock:async fn=>fn(), db:{
    findArticles:async()=>{state.reads++;return [structuredClone(state.article)];},
    getProducts:async()=>{state.reads++;return [structuredClone(state.product)];},
    patchPublishedCAS:async()=>assert.fail('no public writes'),
    patchProductCAS:async()=>assert.fail('no product writes'),
  }};
  return {input:{action:'stage-revision', bundle, revision:bundleHash(bundle)}, deps, state};
}

test('all exact legacy and winter targets stage with fake baselines only', async()=>{
  for(const [id,slug] of targets) {
    const h=fixture(id,slug);
    assert.equal((await executeRevision(h.input,h.deps)).status,'private_revision');
    assert.equal(h.state.reads,2);
  }
});

test('swapped slugs and unlisted targets fail before baseline reads', async()=>{
  for(const [id,slug] of targets) {
    const invalid=targets.filter(([other])=>other!==id).map(([,otherSlug])=>[id,otherSlug]);
    invalid.push(['unlisted',slug],[id,slug+'-unlisted'],['unlisted','unlisted']);
    for(const [badId,badSlug] of invalid) {
      const h=fixture(badId,badSlug);
      await assert.rejects(executeRevision(h.input,h.deps),/fixed revision target/);
      assert.equal(h.state.reads,0);
    }
  }
});

test('winter targets retain approval, article/product baseline and product subset guards', async()=>{
  for(const [id,slug] of targets.slice(3)) {
    for(const mode of ['approval','stale-approval','article','product','subset']) {
      const h=fixture(id,slug);
      let error;
      if(mode==='approval' || mode==='stale-approval') {
        h.input.action='publish-revision';
        if(mode==='stale-approval') {
          h.input.approval={revision:h.input.revision, approverId:'fixture-owner', evidence:{source:'fixture'}};
          h.input.bundle.article.content+=' changed';
          h.input.revision=bundleHash(h.input.bundle);
        }
        error=/exact revision owner approval/;
      } else if(mode==='article') {h.state.article.content+=' drift';error=/article baseline changed/;
      } else if(mode==='product') {h.state.product.description='drift';error=/full product baseline or candidate changed/;
      } else {
        h.input.bundle.revisionContext.targetProductIds.push('new-product');
        h.input.bundle.article.productIds.push('new-product');
        h.input.revision=bundleHash(h.input.bundle);
        error=/revision product selection changed/;
      }
      await assert.rejects(executeRevision(h.input,h.deps),error);
    }
  }
});
