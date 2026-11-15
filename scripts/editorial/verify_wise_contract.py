"""Deterministic offline guard for owner sources, explanations and prompt wiring."""
import json
import re
from pathlib import Path
from wise_contract import ROOT, load_policy

# These are the actual current and retained legacy request paths, not source drafts.
SURFACES = {
    'scripts/editorial/runtime.py': ['load_policy', "data['wisePolicy']", "'wisePolicy': context['wisePolicy']", "'wisePolicy': policy", 'require_current_review'],
    'scripts/editorial/models.py': ['Wit, Insight, Sincere, Empth, AI-free, Sense', 'wiseScores={w,i,s,e,ai,sense}', "valid_scores(result.get('wiseScores'))", "passes(result['wiseScores'])"],
    'scripts/editorial/manual_review.py': ["'wisePolicy': context['wisePolicy']"],
    'scripts/editorial/fixed_price_review.py': ["runtime._wise_context(live_context)", "'wisePolicy':context['wisePolicy']"],
    'scripts/article-writer-agent.js': ['loadWisePolicy().text', '${loadWiseSkill()}'],
    'scripts/article-codex-reviewer.js': ['loadWisePolicy().text', 'validWiseScores(reviewed.wise_scores)', 'supervisor_scores'],
    'scripts/supervisor-agent.js': ['passesWise(wise)', 'average >= WISE_PASS_THRESHOLD', 'wise_sense: (article.supervisor_scores?.wise_sense ?? 0)'],
    'scripts/batch-rewrite-priority-c.mjs': ['${loadWisePolicy().text}'],
    'scripts/x/writer.mjs': ['${loadWisePolicy().text}'],
    'scripts/x/reviewer.mjs': ['loadWisePolicy()', 'const judgePass = passesWise', 'validWiseScores(parsed.scores)', '"sense": N'],
    'src/lib/x-post-generator.mjs': ['WISE_POLICY.text', 'passesWise(axes)', 'passesWise(s)', '"sense": N', 'prompt += "\\n\\n【WISE-AS オーナー原本】'],
    'scripts/editorial/publish.mjs': ['requireWiseBinding(input.bundle, input.review, input.revision)'],
    'scripts/article-publisher-agent.js': ['requireWiseReview(article)', 'requireWiseReview(target)'],
    'scripts/x/approve.mjs': ['requireWiseReview(post)'],
    'scripts/post-to-x.js': ['findWiseProof(text,'],
    'scripts/queue-to-sheets.js': ['findWiseProof(row[2], proofs)'],
    'scripts/editorial/social_publisher.py': ["require_current_review(proposal, job['social'].get('review')"],
    'scripts/editorial/buffer_publisher.py': ["require_current_review(proposal, job['social'].get('review')"],
}
WRONG_DEFINITION = re.compile(r'(?:\b[WISE]\s*[—（(]\s*(?:Body\s*Heat|Warm|Weight|Insider|Stickiness|Entry|Empathy|Science)\b|SincereScience)', re.I)


def verify_surface(name, text):
    if WRONG_DEFINITION.search(text):
        raise ValueError('wise_axis_redefinition:' + name)
    for token in SURFACES.get(name, []):
        if token not in text:
            raise ValueError('wise_prompt_contract_drift:' + name)


def verify(repo=ROOT):
    policy = load_policy(repo)
    for name in SURFACES:
        verify_surface(name, (Path(repo) / name).read_text())
    return {'passed': True, 'axes': policy['axes'], 'floors': policy['floors'],
            'policyId': policy['id'], 'sourceHashes': policy['sourceHashes'],
            'verifiedSurfaces': len(SURFACES)}


if __name__ == '__main__':
    print(json.dumps(verify(), ensure_ascii=False, sort_keys=True))
