"""Offline Astra CLI adapter contracts. Never invokes the managed CLI or a model."""
import json
import os
from pathlib import Path
import stat
import sys
import unittest
from unittest.mock import patch

import manager_cli as mod

MODEL = 'gpt-6-astra'
HOME = str(Path.home())
COMMAND = ['/usr/bin/python3', HOME + '/dev/campgearlab-ops/scripts/codex-supervisor/run_codex.py',
           '--root', HOME + '/Library/Application Support/CampGearLabCodex/runtime',
           '--node', HOME + '/.nvm/versions/node/v22.22.2/bin/node',
           '--npm', HOME + '/.nvm/versions/node/v22.22.2/bin/npm',
           'exec', '--ignore-user-config', '--model', MODEL]
SCHEMA = {'type': 'object', 'additionalProperties': False,
          'required': ['stateFingerprint', 'summary', 'actions'], 'properties': {
              'stateFingerprint': {'type': 'string'}, 'summary': {'type': 'string'},
              'actions': {'type': 'array', 'maxItems': 1, 'items': {'type': 'object',
                  'additionalProperties': False, 'required': ['action'],
                  'properties': {'action': {'type': 'string', 'enum': ['wait']}}}}}}
SNAPSHOT = {'jobs': [], 'externalQueue': {'status': 'unknown'}}
STATE_KEY = 'be8ebfc3781663f388b22cc0ee395354af271f14652eb028dfd760c0584f931d'
DECISION = {'stateFingerprint': STATE_KEY, 'summary': 'Wait for evidence.', 'actions': [{'action': 'wait'}]}
USAGE = {'input_tokens': 100, 'cached_input_tokens': 0, 'output_tokens': 20}


def events(decision=None, usage=None):
    return [dict(type='thread.started', thread_id='PRIVATE_SESSION_ID'), dict(type='turn.started'),
            dict(type='item.completed', item=dict(id='r', type='reasoning', text='PRIVATE_REASONING')),
            dict(type='item.completed', item=dict(id='a', type='agent_message',
                 text=json.dumps(DECISION if decision is None else decision))),
            dict(type='turn.completed', usage=USAGE if usage is None else usage)]


def output(value=None):
    return '\n'.join(json.dumps(e) for e in (events() if value is None else value)).encode()


class ManagerCliTests(unittest.TestCase):
    def call(self, command=None, snapshot=None, schema=None, timeout=2):
        return mod.call(COMMAND if command is None else command,
                        SNAPSHOT if snapshot is None else snapshot, 'Choose one safe action.',
                        SCHEMA if schema is None else schema, timeout)

    def test_exact_safe_argv_private_schema_workdir_stdin_and_environment(self):
        seen = {}
        def runner(argv, stdin, env, timeout):
            seen['argv'] = argv
            self.assertEqual(2, timeout)
            self.assertEqual({'HOME', 'PATH', 'TMPDIR', 'TZ', 'LANG'}, set(env))
            self.assertEqual('Asia/Tokyo', env['TZ'])
            work = Path(argv[argv.index('--cd') + 1])
            schema = Path(argv[argv.index('--output-schema') + 1])
            seen['work'], seen['schema'] = work, schema
            self.assertEqual([], list(work.iterdir()))
            self.assertEqual(0o700, stat.S_IMODE(work.stat().st_mode))
            self.assertEqual(0o600, stat.S_IMODE(schema.stat().st_mode))
            self.assertEqual(SCHEMA, json.loads(schema.read_text()))
            self.assertEqual({'snapshot': SNAPSHOT, 'instructions': 'Choose one safe action.', 'stateFingerprint': STATE_KEY}, json.loads(stdin))
            self.assertEqual(COMMAND[:8] + ['exec', '--ignore-user-config', '--model', MODEL,
                '--ephemeral', '--sandbox', 'read-only', '--skip-git-repo-check', '--json',
                '--color', 'never', '--output-schema', str(schema), '--cd', str(work),
                '-c', 'model_reasoning_effort="high"', '-c', 'web_search="disabled"',
                '-c', 'include_apply_patch_tool=false', '--enable', 'skip_host_skill_discovery',
                *[v for feature in mod.DISABLED_FEATURES for v in ('--disable', feature)], '-'], argv)
            return output()
        with patch.dict(os.environ, {'HOME': HOME, 'PATH': '/usr/bin:/bin', 'TMPDIR': '/tmp',
                                     'LANG': 'en_US.UTF-8', 'API_KEY': 'NEVER_SEND',
                                     'OPENAI_API_KEY': 'NEVER_SEND', 'CODEX_HOME': 'NEVER_SEND'}), \
                patch.object(mod, '_run', side_effect=runner):
            result = self.call()
        self.assertEqual(dict(decision=DECISION, requestedModel=MODEL, actualModel=None,
                              usage=USAGE, actualInvoiceUsd=None), result)
        self.assertFalse(seen['work'].exists())
        self.assertFalse(seen['schema'].exists())
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_manager_fixed_schema_and_semantic_key_are_compatible(self):
        from manager import DECISION_SCHEMA, semantic_key
        decision = dict(stateFingerprint=STATE_KEY, summary='No change.', actions=[{
            'action': 'wait', 'jobId': None, 'revision': None, 'targetUrl': None, 'expectations': {
                'stage': None, 'revision': None, 'socialRevision': None,
                'approvalCurrent': False, 'published': False, 'socialPosted': False}}])
        value = events(decision=decision, usage=dict(USAGE, reasoning_tokens=3))
        self.assertEqual(STATE_KEY, semantic_key(SNAPSHOT))
        with patch.object(mod, '_run', return_value=output(value)):
            self.assertEqual(decision, self.call(schema=DECISION_SCHEMA)['decision'])

    def test_observed_provider_usage_and_warnings_survive_manager_contract(self):
        from manager import DECISION_SCHEMA, validate_decision, _returned_evidence
        decision = dict(stateFingerprint=STATE_KEY, summary='No change.', actions=[{
            'action': 'wait', 'jobId': None, 'revision': None, 'targetUrl': None, 'expectations': {
                'stage': None, 'revision': None, 'socialRevision': None,
                'approvalCurrent': False, 'published': False, 'socialPosted': False}}])
        value = events(decision=decision, usage=dict(USAGE, cache_write_input_tokens=7, reasoning_output_tokens=11))
        value[1:1] = [{'type': 'item.completed', 'item': {'id': 'synthetic', 'type': 'error',
            'message': 'PRIVATE_STARTUP_DIAGNOSTIC'}}] * 4
        with patch.object(mod, '_run', return_value=output(value)):
            result = self.call(schema=DECISION_SCHEMA)
        plan = validate_decision(result, SNAPSHOT, STATE_KEY, MODEL)
        self.assertEqual('wait', plan.action)
        evidence = _returned_evidence(result)
        self.assertEqual(7, evidence['usage']['cache_write_input_tokens'])
        self.assertEqual(11, evidence['usage']['reasoning_tokens'])
        self.assertEqual(result['warnings'], evidence['warnings'])
        self.assertIsNone(evidence['actualModel'])
        self.assertIsNone(evidence['actualInvoiceUsd'])

    def test_untrusted_command_flags_models_and_wrapper_are_rejected_before_spawn(self):
        invalid = [COMMAND + [flag] for flag in ('--approve-for-me', '--dangerously-bypass-approvals-and-sandbox',
            '--full-auto', '--yolo', '--sandbox=workspace-write', '--search', '-c', '-', '--unknown')]
        invalid += [COMMAND + ['--model', MODEL], COMMAND[:-1] + ['gpt-6-sol'],
                    COMMAND[:-2] + ['--model=' + MODEL], COMMAND[0:1] + ['/tmp/run_codex.py'] + COMMAND[2:],
                    ['/bin/sh', '-c', 'anything'], ' '.join(COMMAND)]
        for command in invalid:
            with self.subTest(command=command), patch.object(mod, '_run') as run:
                with self.assertRaises(ValueError):
                    self.call(command=command)
                run.assert_not_called()

    def test_tilde_command_paths_expand_without_shell_or_profile(self):
        command = [part.replace(HOME + '/', '~/') for part in COMMAND]
        with patch.object(mod, '_run', return_value=output()) as run:
            self.call(command=command)
        self.assertEqual(COMMAND[:8], run.call_args.args[0][:8])

    def test_tool_and_unknown_events_are_rejected_even_before_valid_final(self):
        for tool in ('command_execution', 'mcp_tool_call', 'web_search', 'file_change', 'tool_call', 'unknown'):
            value = events()
            value.insert(2, dict(type='item.completed', item=dict(type=tool, text='PRIVATE_TOOL_DATA')))
            with self.subTest(tool=tool), patch.object(mod, '_run', return_value=output(value)):
                with self.assertRaisesRegex(ValueError, '^manager_cli_invalid_output$'):
                    self.call()
        for event in ({'type': 'tool.started'}, {'type': 'error', 'message': 'PRIVATE_ERROR'}):
            with patch.object(mod, '_run', return_value=output([event] + events())):
                with self.assertRaisesRegex(ValueError, '^manager_cli_invalid_output$'):
                    self.call()

    def test_usage_required_and_model_identity_never_inferred(self):
        for usage in ({}, {'output_tokens': 10}, {'input_tokens': True, 'output_tokens': 10},
                      {'input_tokens': -1, 'output_tokens': 1}):
            with self.subTest(usage=usage), patch.object(mod, '_run', return_value=output(events(usage=usage))):
                with self.assertRaises(ValueError):
                    self.call()
        value = events()
        value[-1].pop('usage')
        with patch.object(mod, '_run', return_value=output(value)), self.assertRaises(ValueError):
            self.call()
        value = events()
        value[-1]['model'] = MODEL
        with patch.object(mod, '_run', return_value=output(value)):
            self.assertEqual(MODEL, self.call()['actualModel'])
        value[-1]['model'] = 'other-model'
        with patch.object(mod, '_run', return_value=output(value)), self.assertRaises(ValueError):
            self.call()

    def test_only_one_strict_json_final_with_matching_schema_and_fingerprint(self):
        invalid = [b'PRIVATE BAD OUTPUT', output(events()[:-1]), output(events() + events()),
                   output(events()) + b'\n{"type":"error"}',
                   output(events(decision=dict(DECISION, stateFingerprint='stale'))),
                   output(events(decision=dict(DECISION, approve=True))),
                   output(events(decision=dict(DECISION, actions=[{'action': 'publish'}])))]
        value = events()
        value[-2]['item']['text'] = '```json\n' + json.dumps(DECISION) + '\n```'
        invalid.append(output(value))
        value = events()
        value[-2]['item']['text'] = '{"stateFingerprint":"x","stateFingerprint":"y"}'
        invalid.append(output(value))
        value = events()
        value[-2]['item']['text'] = '{"stateFingerprint":"x","summary":NaN,"actions":[]}'
        invalid.append(output(value))
        for raw in invalid:
            with self.subTest(raw=raw[:50]), patch.object(mod, '_run', return_value=raw):
                with self.assertRaisesRegex(ValueError, '^manager_cli_invalid_output$'):
                    self.call()

    def test_observed_pre_turn_startup_errors_and_usage_are_bounded_warnings(self):
        # Synthetic SHAPE fixture from main's v2 report; no actual text or logs.
        value = events(usage={'input_tokens': 101, 'cached_input_tokens': 23,
            'cache_write_input_tokens': 7, 'output_tokens': 31, 'reasoning_output_tokens': 11})
        for index in range(4):
            value.insert(1, {'type': 'item.completed', 'item': {
                'id': f'fixture-{index}', 'type': 'error', 'message': 'PRIVATE_STARTUP_DIAGNOSTIC'}})
        with patch.object(mod, '_run', return_value=output(value)) as run:
            result = self.call()
        self.assertEqual(1, run.call_count)
        self.assertEqual(DECISION, result['decision'])
        self.assertEqual({'preTurnErrorCount': 4, 'code': 'unknown', 'toolsStartupVerified': False}, result['warnings'])
        self.assertEqual({'input_tokens': 101, 'cached_input_tokens': 23,
            'cache_write_input_tokens': 7, 'output_tokens': 31, 'reasoning_tokens': 11}, result['usage'])
        self.assertIsNone(result['actualModel'])
        self.assertIsNone(result['actualInvoiceUsd'])
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_after_turn_errors_and_structured_tool_errors_never_become_warnings(self):
        invalid = []
        value = events(); value.insert(2, {'type': 'item.completed', 'item': {'type': 'error', 'message': 'PRIVATE'}})
        invalid.append(value)
        for item in ({'type': 'command_execution', 'error': 'PRIVATE'},
                     {'type': 'mcp_tool_call', 'error': 'PRIVATE'},
                     {'type': 'error', 'message': 'PRIVATE', 'tool_name': 'shell'},
                     {'type': 'error', 'message': 'PRIVATE', 'code': 'command_execution'},
                     {'type': 'error', 'message': {'tool': 'PRIVATE'}}):
            value = events(); value.insert(1, {'type': 'item.completed', 'item': item}); invalid.append(value)
        value = events(); value.insert(1, {'type': 'item.started', 'item': {'type': 'error'}}); invalid.append(value)
        value = events(); value[0:0] = [{'type': 'item.completed', 'item': {'type': 'error', 'message': 'PRIVATE'}}]
        invalid.append(value)
        for value in invalid:
            with self.subTest(value=value[:3]), patch.object(mod, '_run', return_value=output(value)), self.assertRaises(ValueError):
                self.call()

    def test_startup_warnings_never_override_invalid_final_tool_events_or_completion(self):
        bad_streams = [events()[:-1], events(decision=dict(DECISION, stateFingerprint='stale')),
                       events(decision=dict(DECISION, actions=[{'action': 'publish'}]))]
        value = events(); value.insert(3, {'type': 'item.completed', 'item': {'type': 'web_search'}}); bad_streams.append(value)
        value = events(); value.append({'type': 'item.completed', 'item': {'type': 'error', 'message': 'PRIVATE'}})
        bad_streams.append(value)
        for value in bad_streams:
            value.insert(1, {'type': 'item.completed', 'item': {'type': 'error', 'message': 'PRIVATE'}})
            with patch.object(mod, '_run', return_value=output(value)), self.assertRaises(ValueError):
                self.call()
        value = events()
        value[1:1] = [{'type': 'item.completed', 'item': {'type': 'error', 'message': 'PRIVATE'}}] * 17
        with patch.object(mod, '_run', return_value=output(value)), self.assertRaises(ValueError):
            self.call()

    def test_usage_normalization_rejects_unknown_alias_collisions_and_never_fills_zero(self):
        for usage in (dict(USAGE, unknown_tokens=1), dict(USAGE, reasoning_tokens=2, reasoning_output_tokens=3),
                      dict(USAGE, cache_write_input_tokens=True), dict(USAGE, cache_write_input_tokens=-1)):
            with self.subTest(usage=usage), patch.object(mod, '_run', return_value=output(events(usage=usage))), \
                    self.assertRaises(ValueError):
                self.call()
        usage = {'input_tokens': 101, 'output_tokens': 31, 'reasoning_output_tokens': 11}
        with patch.object(mod, '_run', return_value=output(events(usage=usage))):
            result = self.call()
        self.assertEqual({'input_tokens': 101, 'output_tokens': 31, 'reasoning_tokens': 11}, result['usage'])
        self.assertNotIn('cached_input_tokens', result['usage'])
        self.assertNotIn('cache_write_input_tokens', result['usage'])

    def test_optional_diagnostic_counts_entire_stream_without_message_content(self):
        value = events()
        value.insert(2, {'type': 'turn.extra', 'text': 'PRIVATE_BODY'})
        value[-1]['model'] = ' gpt-6-astra '
        diagnostics = []
        with patch.object(mod, '_run', return_value=output(value)), self.assertRaises(ValueError) as raised:
            mod.call(COMMAND, SNAPSHOT, 'Choose one safe action.', SCHEMA, 2,
                     diagnostic=diagnostics.append)
        self.assertEqual('manager_cli_invalid_output', str(raised.exception))
        diagnostic = raised.exception.diagnostic
        self.assertEqual('unknown_event', diagnostic['stage'])
        self.assertEqual(1, diagnostic['eventCounts']['turn.extra'])
        self.assertEqual(1, diagnostic['eventCounts']['turn.completed'])
        self.assertEqual(1, diagnostic['itemCounts']['agent_message'])
        self.assertEqual(USAGE, diagnostic['usage'])
        self.assertEqual('trimmed', diagnostic['modelMatch'])
        self.assertEqual([diagnostic], diagnostics)
        self.assertNotIn('PRIVATE', json.dumps(diagnostic))
        self.assertNotIn('thread_id', json.dumps(diagnostic))
        self.assertNotIn(DECISION['summary'], json.dumps(diagnostic))

    def test_non_json_commentary_before_final_stays_rejected_but_is_distinguishable(self):
        value = events()
        value.insert(2, dict(type='item.completed', item=dict(type='agent_message', text='PRIVATE COMMENTARY')))
        with patch.object(mod, '_run', return_value=output(value)), self.assertRaises(ValueError) as raised:
            self.call()
        diagnostic = raised.exception.diagnostic
        self.assertEqual('agent_message_json', diagnostic['stage'])
        self.assertEqual(2, diagnostic['agentMessageCount'])
        self.assertEqual(1, diagnostic['agentMessageJsonObjectCount'])
        self.assertEqual(1, diagnostic['agentMessageNonJsonCount'])
        self.assertEqual(USAGE, diagnostic['usage'])
        self.assertNotIn('PRIVATE', json.dumps(diagnostic))

    def test_specific_parse_stage_codes_preserve_all_existing_rejections(self):
        cases = []
        value = events(); value[-1].pop('usage'); cases.append((value, 'usage_shape'))
        value = events(); value[-1]['model'] = ' gpt-6-astra '; cases.append((value, 'reported_model_mismatch'))
        cases.append((events()[:-1], 'missing_turn_completed'))
        cases.append((events(decision=dict(DECISION, stateFingerprint='stale')), 'state_fingerprint_mismatch'))
        value = events(); value.insert(2, dict(type='item.completed', item=dict(type='command_execution')))
        cases.append((value, 'unknown_item'))
        value = events(); value.insert(2, value[-2]); cases.append((value, 'multiple_agent_messages'))
        for value, stage in cases:
            with self.subTest(stage=stage), patch.object(mod, '_run', return_value=output(value)), \
                    self.assertRaises(ValueError) as raised:
                self.call()
            self.assertEqual(stage, raised.exception.diagnostic['stage'])
        with patch.object(mod, '_run', return_value=b'PRIVATE INVALID OUTPUT'), self.assertRaises(ValueError) as raised:
            self.call()
        self.assertEqual('event_json', raised.exception.diagnostic['stage'])
        self.assertIsNone(raised.exception.diagnostic['usage'])

    def test_schema_diagnostic_is_only_fixed_path_and_reason_no_values(self):
        value = events(decision=dict(DECISION, actions=[{'action': 'PRIVATE_ACTION'}]))
        with patch.object(mod, '_run', return_value=output(value)), self.assertRaises(ValueError) as raised:
            self.call()
        diagnostic = raised.exception.diagnostic
        self.assertEqual('schema_validation', diagnostic['stage'])
        self.assertEqual('schema_enum', diagnostic['schemaCode'])
        self.assertEqual(['actions', 0, 'action'], diagnostic['schemaPath'])
        self.assertEqual('object', diagnostic['decisionShape'])
        self.assertEqual('array', diagnostic['actionsShape'])
        self.assertEqual(1, diagnostic['actionsCount'])
        self.assertNotIn('PRIVATE', json.dumps(diagnostic))

    def test_diagnostic_callback_cannot_mask_or_retry_rejection(self):
        def diagnostic(_):
            raise OSError('PRIVATE_CALLBACK_ERROR')
        with patch.object(mod, '_run', return_value=b'invalid') as run, self.assertRaises(ValueError) as raised:
            mod.call(COMMAND, SNAPSHOT, 'Choose one safe action.', SCHEMA, 2, diagnostic=diagnostic)
        self.assertEqual('manager_cli_invalid_output', str(raised.exception))
        self.assertEqual(1, run.call_count)
        self.assertNotIn('PRIVATE', str(raised.exception))

    def test_schema_is_a_bounded_object_not_arbitrary_path_and_input_has_no_secrets(self):
        for schema in ('/tmp/schema.json', Path('/tmp/schema.json'), {'$ref': '/etc/passwd'}, {}):
            with self.subTest(schema=schema), patch.object(mod, '_run') as run:
                with self.assertRaises(ValueError):
                    self.call(schema=schema)
                run.assert_not_called()
        for snapshot in (dict(SNAPSHOT, env={'API_KEY': 'secret'}),
                         dict(SNAPSHOT, nested={'nonce': 'private'}),
                         dict(SNAPSHOT, authorization='secret'),
                         dict(SNAPSHOT, padding='x' * (mod.MAX_INPUT_BYTES + 1))):
            with self.subTest(snapshot=list(snapshot)), patch.object(mod, '_run') as run:
                with self.assertRaises(ValueError):
                    self.call(snapshot=snapshot)
                run.assert_not_called()

    def test_timeout_and_runtime_errors_are_sanitized_and_never_retried(self):
        for exception, expected in ((TimeoutError('PRIVATE_TIMEOUT'), TimeoutError),
                                   (OSError('PRIVATE_PATH'), ValueError)):
            with patch.object(mod, '_run', side_effect=exception) as run:
                with self.assertRaises(expected) as raised:
                    self.call()
                self.assertNotIn('PRIVATE', str(raised.exception))
                self.assertEqual(1, run.call_count)
        for timeout in (0, -1, True, float('nan'), mod.MAX_TIMEOUT + 1):
            with self.subTest(timeout=timeout), patch.object(mod, '_run') as run:
                with self.assertRaises(ValueError):
                    self.call(timeout=timeout)
                run.assert_not_called()


class ProcessBoundaryTests(unittest.TestCase):
    def run_code(self, code, timeout=2):
        return mod._run([sys.executable, '-c', code], b'{}',
                        {'HOME': HOME, 'PATH': '/usr/bin:/bin', 'TMPDIR': '/tmp',
                         'TZ': 'Asia/Tokyo', 'LANG': 'en_US.UTF-8'}, timeout)

    def test_real_child_receives_no_extra_parent_environment(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'SECRET', 'ANTHROPIC_API_KEY': 'SECRET'}):
            value = json.loads(self.run_code('import os,json; print(json.dumps(dict(os.environ)))'))
        self.assertNotIn('OPENAI_API_KEY', value)
        self.assertNotIn('ANTHROPIC_API_KEY', value)
        self.assertNotIn('CODEX_HOME', value)

    def test_output_stderr_and_time_limits_stop_once_without_raw_diagnostics(self):
        for code, expected in (('import time; time.sleep(3)', TimeoutError),
            (f'import sys; sys.stdout.write("x"*{mod.MAX_OUTPUT_BYTES + 1})', ValueError),
            (f'import sys; sys.stderr.write("x"*{mod.MAX_STDERR_BYTES + 1})', ValueError),
            ('import sys; print("PRIVATE_ERR",file=sys.stderr); sys.exit(2)', ValueError)):
            with self.subTest(code=code), self.assertRaises(expected) as raised:
                self.run_code(code, timeout=.15)
            self.assertNotIn('PRIVATE', str(raised.exception))

    def test_success_returns_stdout_only(self):
        self.assertEqual(b'{}\n', self.run_code('import sys; print(sys.stdin.read()); print("PRIVATE",file=sys.stderr)'))
