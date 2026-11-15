// Offline source/definition/prompt wiring guard. Import never runs a model or writes state.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {loadWisePolicy} from '../src/lib/wise-contract.mjs';
const ROOT=fileURLToPath(new URL('../',import.meta.url));
export const SURFACES={
 'scripts/publish-autumn-cold-gear-guide.mjs':['requireWiseReview(a)'],
 'scripts/publish-autumn-cluster.mjs':['requireWiseReview(a)'],
 'scripts/publish-landlock-x.mjs':['requireWiseReview(a)'],
 'scripts/seo/publish.mjs':['validateWiseReview(manifest.wiseReview)','review.policyId !== policy.id','passesWise(review.scores)','review.reasons[key]'],
 'scripts/article-writer-agent.js':['loadWisePolicy().text','${loadWiseSkill()}'],
 'scripts/article-codex-reviewer.js':['loadWisePolicy().text','validWiseScores(reviewed.wise_scores)','supervisor_scores'],
 'scripts/supervisor-agent.js':['passesWise(wise)','average >= WISE_PASS_THRESHOLD','wise_sense: (article.supervisor_scores?.wise_sense ?? 0)'],
 'scripts/batch-rewrite-priority-c.mjs':['${loadWisePolicy().text}'],
 'scripts/x/writer.mjs':['${loadWisePolicy().text}'],
 'scripts/x/reviewer.mjs':['loadWisePolicy()','const judgePass = passesWise','validWiseScores(parsed.scores)','"sense": N'],
 'src/lib/x-post-generator.mjs':['WISE_POLICY.text','passesWise(axes)','passesWise(s)','"sense": N','prompt += "\\n\\n【WISE-AS オーナー原本】'],
 'scripts/article-publisher-agent.js':['requireWiseReview(article)','requireWiseReview(target)'],
 'scripts/x/approve.mjs':['requireWiseReview(post)'],
 'scripts/post-to-x.js':['findWiseProof(text,'],
 'scripts/queue-to-sheets.js':['findWiseProof(row[2], proofs)'],
 'scripts/rewrite-tone.js':['loadWisePolicy().text','requireWiseReview({...art, content:rewritten})'],
 'scripts/rewrite-tone-supabase.js':['loadWisePolicy().text','requireWiseReview({...art, content:rewritten})'],
 'scripts/gsc-ctr-optimizer.js':['loadWisePolicy().text','validateManifest(manifest)','manifest.baseline.hash !== articleHash(articles[idx])'],
 'scripts/popular-repost.js':['${loadWisePolicy().text}'],
 'src/lib/viral-scout-agent.mjs':['${loadWisePolicy().text}\\n未確認の本人経験','${loadWisePolicy().text}\\n新しい事実'],
 'scripts/4koma/story-generator.mjs':['loadWisePolicy().text'],
};
const WRONG=/(?:\b[WISE]\s*[—（(]\s*(?:Body\s*Heat|Warm|Weight|Insider|Stickiness|Entry|Empathy|Science)\b|SincereScience)/i;
export function verifySurface(name,text){
 if(WRONG.test(text)) throw new Error('wise_axis_redefinition:'+name);
 for(const token of SURFACES[name]??[]) if(!text.includes(token)) throw new Error('wise_prompt_contract_drift:'+name);
}
export function verify(root=ROOT){
 const policy=loadWisePolicy(root);
 for(const name of Object.keys(SURFACES)) verifySurface(name,fs.readFileSync(path.join(root,name),'utf8'));
 return {passed:true,axes:policy.axes,floors:policy.floors,policyId:policy.id,sourceHashes:policy.sourceHashes,verifiedSurfaces:Object.keys(SURFACES).length};
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) console.log(JSON.stringify(verify()));
