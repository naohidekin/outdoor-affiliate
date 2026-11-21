"""Offline regressions for owner semantics, score gates and stale approvals."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from wise_contract import ROOT, load_policy, passes, require_current_review, valid_scores
from models import Models, ModelError, SOCIAL_REVIEW_SCHEMA
from test_models import ENV, FLAGS, REVIEW, Fake, response, bundle, article_review_value

SCORES = dict(w=2, i=2, s=2, e=2, ai=3, sense=2)


class WiseContractTests(unittest.TestCase):
    def test_owner_raw_source_and_python_javascript_binding_are_identical(self):
        policy = load_policy()
        self.assertEqual(['Wit', 'Insight', 'Sincere', 'Empth', 'AI-free', 'Sense'], policy['axes'])
        for name in policy['sourceHashes']:
            self.assertIn((ROOT / 'rules/common' / name).read_text(), policy['text'])
        result = subprocess.run(['node', '--input-type=module', '-e',
            "import {loadWisePolicy} from './src/lib/wise-contract.mjs'; console.log(JSON.stringify(loadWisePolicy()))"],
            cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(policy, json.loads(result.stdout))

    def test_each_axis_floor_and_strict_complete_six_scores(self):
        self.assertTrue(passes(SCORES))
        for key in SCORES:
            low = dict(SCORES, **{key: SCORES[key] - 1})
            self.assertFalse(passes(low), key)
            missing = dict(SCORES); missing.pop(key)
            self.assertFalse(valid_scores(missing), key)
        for value in [True, '3', float('nan'), float('inf'), 0, 5]:
            self.assertFalse(passes(dict(SCORES, sense=value)))
        wrong = dict(SCORES); wrong['Science'] = wrong.pop('s')
        self.assertFalse(passes(wrong))

    def test_corrupted_names_semantics_and_explanations_stop_before_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ['rules/common', 'docs']:
                (root / name).mkdir(parents=True)
            for name in ['SKILL.md', 'docs/WISE-GEARMAN.md', 'docs/sense-definition.md',
                         'rules/common/wise-master.md', 'rules/common/sense-master.md', 'rules/common/wise-contract.json']:
                shutil.copyfile(ROOT / name, root / name)
            self.assertEqual(load_policy()['id'], load_policy(root)['id'])
            for filename, old, bad in [('rules/common/wise-master.md', 'Wit', 'Weight'),
                                       ('rules/common/wise-master.md', 'Wit', 'Warm'),
                                       ('rules/common/wise-master.md', 'Sincere', 'Science'),
                                       ('rules/common/wise-master.md', 'Sense', 'Omitted'),
                                       ('SKILL.md', 'Wit', 'Warm')]:
                target = root / filename; raw = target.read_text()
                target.write_text(raw.replace(old, bad))
                with self.assertRaises(ValueError): load_policy(root)
                target.write_text(raw)
            contract = root / 'rules/common/wise-contract.json'
            data = json.loads(contract.read_text()); data['axes'][2] = 'Science'
            contract.write_text(json.dumps(data))
            with self.assertRaises(ValueError): load_policy(root)

    def test_old_policy_approval_never_authorizes_current_action_and_history_intact(self):
        policy = load_policy()
        artifact = dict(wisePolicy=policy['id'])
        review = dict(wisePolicy=policy['id'], wiseScores=SCORES, passed=True)
        self.assertEqual(policy, require_current_review(artifact, review))
        for changed_artifact, changed_review in [({}, review), (dict(wisePolicy='old'), review),
                                                  (artifact, dict(review, wisePolicy='old')),
                                                  (artifact, dict(review, wiseScores=dict(SCORES, sense=1)))]:
            before = copy.deepcopy((changed_artifact, changed_review))
            with self.assertRaises(ValueError): require_current_review(changed_artifact, changed_review)
            self.assertEqual(before, (changed_artifact, changed_review))

    def test_social_review_real_gate_and_raw_prompt_no_article_criteria(self):
        policy = load_policy()
        checks = dict(reviewKind='social', wisePolicy=policy, evidence=FLAGS)
        fake = Fake(response(dict(REVIEW, wiseScores=SCORES)))
        result = Models(ENV, fake).review(bundle(), checks)
        self.assertTrue(result['passed'])
        self.assertEqual(policy['id'], result['wisePolicy'])
        request = fake.calls[0][2]
        self.assertEqual(SOCIAL_REVIEW_SCHEMA, request['output_config']['format']['schema'])
        self.assertNotIn('criteria', SOCIAL_REVIEW_SCHEMA['required'])
        serialized = json.dumps(request, ensure_ascii=False)
        for axis in policy['axes']: self.assertIn(axis, serialized)
        self.assertIn('角度の取り方', serialized)
        failed = Models(ENV, Fake(response(dict(REVIEW, wiseScores=dict(SCORES, sense=1))))).review(bundle(), checks)
        self.assertFalse(failed['passed'])
        missing = dict(SCORES); missing.pop('sense')
        with self.assertRaisesRegex(ModelError, 'six scores'):
            Models(ENV, Fake(response(dict(REVIEW, wiseScores=missing)))).review(bundle(), checks)

    def test_prompt_and_handoff_semantics_guard_detects_wrong_axis_or_missing_sense(self):
        from verify_wise_contract import verify, verify_surface
        self.assertTrue(verify()['passed'])
        for bad in ['W（Warm / 体温）', 'W — Weight', 'S（Science）', 'SincereScience']:
            with self.assertRaises(ValueError): verify_surface('synthetic-prompt', bad)
        text = (ROOT / 'scripts/x/reviewer.mjs').read_text()
        with self.assertRaises(ValueError):
            verify_surface('scripts/x/reviewer.mjs', text.replace('"sense": N', '"missing": N'))

    def test_article_owner_floors_and_supervisor_mean_are_independent(self):
        from models import CRITERIA_FIELDS
        policy = load_policy()
        checks = dict(wisePolicy=policy, editorialRules=policy['text'], evidence=FLAGS, structural={'passed':True})
        value = article_review_value(wiseScores=SCORES)
        self.assertTrue(Models(ENV, Fake(response(value))).review(bundle(), checks)['passed'])
        self.assertFalse(Models(ENV, Fake(response(dict(value, wiseScores=dict(SCORES, sense=1))))).review(bundle(), checks)['passed'])
        low = dict.fromkeys(value['criteria'], 7)
        result = Models(ENV, Fake(response(article_review_value(wiseScores=SCORES, criteria=low)))).review(bundle(), checks)
        self.assertTrue(result['passed']); self.assertEqual(80 / 11, result['score'])
        bad_policy = copy.deepcopy(policy); bad_policy['axes'][0] = 'Warm'
        fake = Fake(response(value))
        with self.assertRaises(ModelError):
            Models(ENV, fake).review(bundle(), dict(checks, wisePolicy=bad_policy))
        self.assertEqual([], fake.calls)


if __name__ == '__main__':
    unittest.main()
