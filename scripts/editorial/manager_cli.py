"""Bounded, read-only Astra CLI transport. Caller owns sanitization, lease and policy.

Only the host-pinned managed wrapper is accepted. No auth files, session logs or
provider keys are read or copied. Raw CLI events and diagnostics stay in memory.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import tempfile
import time

MODEL = 'gpt-6-astra'
MAX_INPUT_BYTES = 131072
MAX_OUTPUT_BYTES = 262144
MAX_STDERR_BYTES = 65536
MAX_TIMEOUT = 300
MAX_STARTUP_WARNINGS = 16
DISABLED_FEATURES = ('shell_tool', 'unified_exec', 'apps', 'plugins', 'multi_agent',
                     'multi_agent_v2', 'browser_use', 'browser_use_external', 'in_app_browser',
                     'computer_use', 'code_mode_host', 'image_generation', 'view_image')
_ENV_KEYS = ('HOME', 'PATH', 'TMPDIR', 'TZ', 'LANG')
_SECRET_KEYS = {'env', 'authorization', 'cookie', 'cookies', 'nonce', 'credentials',
                'api_key', 'access_token', 'refresh_token', 'password', 'session_logs'}


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _strict_json(text):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError()
            value[key] = item
        return value
    def constant(_):
        raise ValueError()
    value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    _json(value)
    return value


def _command(command):
    if not isinstance(command, (list, tuple)) or not all(isinstance(s, str) for s in command):
        raise ValueError()
    home = Path.home()
    expected = ['/usr/bin/python3', str(home / 'dev/campgearlab-ops/scripts/codex-supervisor/run_codex.py'),
                '--root', str(home / 'Library/Application Support/CampGearLabCodex/runtime'),
                '--node', str(home / '.nvm/versions/node/v22.22.2/bin/node'),
                '--npm', str(home / '.nvm/versions/node/v22.22.2/bin/npm'),
                'exec', '--ignore-user-config', '--model', MODEL]
    argv = [os.path.expanduser(s) if s.startswith('~/') else s for s in command]
    if argv != expected:
        raise ValueError()
    return argv


def _public_json(value, depth=0):
    if depth > 30:
        raise ValueError()
    if isinstance(value, dict):
        for key, item in value.items():
            if (not isinstance(key, str) or key.lower() in _SECRET_KEYS
                    or key.lower().endswith(('_api_key', '_access_token', '_refresh_token'))):
                raise ValueError()
            _public_json(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _public_json(item, depth + 1)
    elif value is not None and type(value) not in (str, int, float, bool):
        raise ValueError()


def _schema(schema, depth=0):
    """Small, explicit JSON Schema subset; unsupported constructs fail closed."""
    allowed = {'$schema', 'title', 'description', 'type', 'properties', 'required',
               'additionalProperties', 'items', 'enum', 'const', 'anyOf', 'oneOf',
               'minItems', 'maxItems', 'minLength', 'maxLength', 'minimum', 'maximum', 'pattern'}
    types = {'object', 'array', 'string', 'integer', 'number', 'boolean', 'null'}
    if depth > 20 or not isinstance(schema, dict) or not schema or set(schema) - allowed:
        raise ValueError()
    kind = schema.get('type')
    if kind is not None and not (kind in types if isinstance(kind, str) else
                                 isinstance(kind, list) and kind and all(k in types for k in kind)):
        raise ValueError()
    if kind == 'object':
        props, required = schema.get('properties'), schema.get('required', [])
        if (not isinstance(props, dict) or schema.get('additionalProperties') is not False
                or not isinstance(required, list) or not all(isinstance(k, str) and k in props for k in required)):
            raise ValueError()
        for child in props.values():
            _schema(child, depth + 1)
    if kind == 'array':
        _schema(schema.get('items'), depth + 1)
    for key in ('anyOf', 'oneOf'):
        if key in schema:
            if not isinstance(schema[key], list) or not schema[key]:
                raise ValueError()
            for child in schema[key]:
                _schema(child, depth + 1)
    for key in ('minItems', 'maxItems', 'minLength', 'maxLength'):
        if key in schema and (type(schema[key]) is not int or schema[key] < 0):
            raise ValueError()
    if 'pattern' in schema:
        re.compile(schema['pattern'])


class _SchemaError(ValueError):
    def __init__(self, code, path):
        self.code, self.path = code, path
        super().__init__('manager_schema_invalid')


class ManagerCliOutputError(ValueError):
    """Content-free failure metadata; the ordinary error string stays stable."""
    def __init__(self, stage, diagnostic):
        self.diagnostic = dict(diagnostic, stage=stage)
        super().__init__('manager_cli_invalid_output')


def _validate(value, schema, path=()):
    def matches(kind):
        return {'object': isinstance(value, dict), 'array': isinstance(value, list),
                'string': isinstance(value, str), 'integer': type(value) is int,
                'number': type(value) in (int, float), 'boolean': type(value) is bool,
                'null': value is None}[kind]
    kind = schema.get('type')
    if kind is not None and not any(matches(k) for k in (kind if isinstance(kind, list) else [kind])):
        raise _SchemaError('schema_type', path)
    if 'const' in schema and _json(value) != _json(schema['const']):
        raise _SchemaError('schema_const', path)
    if 'enum' in schema and not any(_json(value) == _json(v) for v in schema['enum']):
        raise _SchemaError('schema_enum', path)
    for key in ('anyOf', 'oneOf'):
        if key in schema:
            count = 0
            for child in schema[key]:
                try:
                    _validate(value, child, path)
                    count += 1
                except ValueError:
                    pass
            if not count or key == 'oneOf' and count != 1:
                raise _SchemaError('schema_choice', path)
    if isinstance(value, dict):
        props = schema.get('properties', {})
        if set(schema.get('required', [])) - set(value) or schema.get('additionalProperties') is False and set(value) - set(props):
            raise _SchemaError('schema_keys', path)
        for key, item in value.items():
            if key in props:
                _validate(item, props[key], path + (key,))
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate(item, schema.get('items', {}), path + (index,))
    for minimum, maximum, size in (('minItems', 'maxItems', len(value) if isinstance(value, list) else None),
                                   ('minLength', 'maxLength', len(value) if isinstance(value, str) else None),
                                   ('minimum', 'maximum', value if type(value) in (int, float) else None)):
        if size is not None and (minimum in schema and size < schema[minimum] or maximum in schema and size > schema[maximum]):
            raise _SchemaError('schema_bounds', path)
    if isinstance(value, str) and 'pattern' in schema and re.search(schema['pattern'], value) is None:
        raise _SchemaError('schema_pattern', path)


def _run(argv, stdin, env, timeout):
    """Bound all pipes in memory, kill the process group on failure; never return stderr."""
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=env, start_new_session=True,
                               cwd=argv[argv.index('--cd') + 1] if '--cd' in argv else None)
    deadline = time.monotonic() + timeout
    result, stderr_size, offset = bytearray(), 0, 0
    try:
        with selectors.DefaultSelector() as selector:
            for stream in (process.stdin, process.stdout, process.stderr):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_WRITE if stream is process.stdin else selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('manager_cli_timeout')
                for key, _ in selector.select(min(remaining, .1)):
                    stream = key.fileobj
                    if stream is process.stdin:
                        try:
                            offset += os.write(stream.fileno(), stdin[offset:offset + 8192])
                        except BrokenPipeError:
                            offset = len(stdin)
                        if offset == len(stdin):
                            selector.unregister(stream)
                            stream.close()
                        continue
                    chunk = os.read(stream.fileno(), 8192)
                    if not chunk:
                        selector.unregister(stream)
                        stream.close()
                    elif stream is process.stdout:
                        if len(result) + len(chunk) > MAX_OUTPUT_BYTES:
                            raise ValueError('manager_cli_output_limit')
                        result.extend(chunk)
                    else:
                        stderr_size += len(chunk)
                        if stderr_size > MAX_STDERR_BYTES:
                            raise ValueError('manager_cli_output_limit')
        try:
            code = process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise TimeoutError('manager_cli_timeout') from None
        if code != 0:
            raise ValueError('manager_cli_failed')
        return bytes(result)
    finally:
        # A wrapper may exit while descendants still hold a pipe; kill its whole group.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


def _shape(value):
    if value is None:
        return 'null'
    if isinstance(value, dict):
        return 'object'
    if isinstance(value, list):
        return 'array'
    if isinstance(value, str):
        return 'string'
    return 'boolean' if type(value) is bool else 'number'


def _usage(value):
    """Preserve measured counters; normalize the one observed provider alias."""
    allowed = {'input_tokens', 'output_tokens', 'cached_input_tokens',
               'cache_write_input_tokens', 'reasoning_tokens', 'reasoning_output_tokens'}
    if (not isinstance(value, dict) or not {'input_tokens', 'output_tokens'} <= set(value)
            or set(value) - allowed or not all(type(v) is int and v >= 0 for v in value.values())
            or 'reasoning_tokens' in value and 'reasoning_output_tokens' in value):
        raise ValueError('manager_cli_usage_shape')
    result = dict(value)
    if 'reasoning_output_tokens' in result:
        result['reasoning_tokens'] = result.pop('reasoning_output_tokens')
    return result


def _startup_error(event, item):
    # Opaque scalar message only: no message inspection or assertion of healthy
    # tool startup. Tool payloads, result fields and unverified codes are rejected.
    return (set(event) <= {'type', 'item'} and set(item) <= {'id', 'type', 'message', 'code'}
            and isinstance(item.get('message'), str) and item.get('code') is None
            and ('id' not in item or isinstance(item['id'], str)))


def _output_diagnostic(raw):
    """Summarize the whole bounded stream, including events after a rejected item.

    Only structural type labels, counts, shape labels and reported usage survive.
    Never retain text, identifiers, arbitrary keys, raw model strings or stderr.
    """
    result = dict(eventCounts={}, itemCounts={}, agentMessageCount=0,
        agentMessageJsonObjectCount=0, agentMessageNonJsonCount=0,
        invalidJsonLineCount=0, usage=None, usagePresent=False, usageShapeValid=False,
        modelPresent=False, modelShape='null', modelMatch='missing',
        decisionShape='missing', actionsShape='missing', actionsCount=None)
    if not isinstance(raw, bytes) or len(raw) > MAX_OUTPUT_BYTES:
        return result
    try:
        lines = raw.decode('utf-8').splitlines()
    except UnicodeError:
        return result
    def count(group, label):
        # CLI type labels only: no IDs, numbers, URL/path punctuation or body text.
        if (not isinstance(label, str) or len(label) > 48
                or not re.fullmatch(r'[a-z]+(?:[._][a-z]+){0,5}', label)):
            label = 'other'
        if label not in group and len(group) >= 16:
            label = 'other'
        group[label] = group.get(label, 0) + 1
    usage_keys = {'input_tokens', 'output_tokens', 'cached_input_tokens',
                  'cache_write_input_tokens', 'reasoning_tokens', 'reasoning_output_tokens'}
    for line in lines:
        if not line.strip():
            continue
        try:
            event = _strict_json(line)
        except (ValueError, TypeError, RecursionError, OverflowError):
            result['invalidJsonLineCount'] += 1
            continue
        if not isinstance(event, dict):
            count(result['eventCounts'], None)
            continue
        kind = event.get('type')
        count(result['eventCounts'], kind)
        if kind in ('item.started', 'item.completed'):
            item = event.get('item')
            count(result['itemCounts'], item.get('type') if isinstance(item, dict) else None)
            if isinstance(item, dict) and kind == 'item.completed' and item.get('type') == 'agent_message':
                result['agentMessageCount'] += 1
                try:
                    final = _strict_json(item.get('text'))
                except (ValueError, TypeError, RecursionError, OverflowError):
                    result['agentMessageNonJsonCount'] += 1
                else:
                    result['decisionShape'] = _shape(final)
                    if isinstance(final, dict):
                        result['agentMessageJsonObjectCount'] += 1
                        result['actionsShape'] = _shape(final.get('actions'))
                        result['actionsCount'] = len(final['actions']) if isinstance(final.get('actions'), list) else None
        if kind == 'turn.completed':
            usage = event.get('usage')
            result['usagePresent'] = 'usage' in event
            try:
                normalized = _usage(usage)
            except ValueError:
                result['usageShapeValid'], result['usage'] = False, None
            else:
                result['usageShapeValid'], result['usage'] = True, normalized
            result['usageProviderKeys'] = sorted(set(usage) & usage_keys) if isinstance(usage, dict) else []
            model = event.get('model')
            result['modelPresent'] = 'model' in event
            result['modelShape'] = _shape(model)
            result['modelMatch'] = ('missing' if model is None else 'exact' if model == MODEL else
                'trimmed' if isinstance(model, str) and model.strip() == MODEL else 'other')
    return result


def _parse(raw, state_fingerprint, schema):
    diagnostic = _output_diagnostic(raw)
    def fail(stage):
        raise ManagerCliOutputError(stage, diagnostic)
    if not isinstance(raw, bytes) or len(raw) > MAX_OUTPUT_BYTES:
        fail('output_size')
    try:
        lines = raw.decode('utf-8').splitlines()
    except UnicodeError:
        fail('invalid_utf8')
    final, usage, actual, completed = None, None, None, False
    thread_started, turn_started, startup_errors = False, False, 0
    for line in lines:
        if not line.strip():
            continue
        try:
            event = _strict_json(line)
        except (ValueError, TypeError, RecursionError, OverflowError):
            fail('event_json')
        if not isinstance(event, dict):
            fail('event_shape')
        if completed:
            fail('event_after_completion')
        kind = event.get('type')
        if kind == 'thread.started':
            if thread_started or turn_started:
                fail('event_order')
            thread_started = True
            continue
        if kind == 'turn.started':
            if not thread_started or turn_started:
                fail('event_order')
            turn_started = True
            continue
        if kind in ('item.started', 'item.completed'):
            item = event.get('item')
            if isinstance(item, dict) and item.get('type') == 'error':
                if turn_started:
                    fail('turn_error_item')
                if (not thread_started or kind != 'item.completed' or not _startup_error(event, item)
                        or startup_errors >= MAX_STARTUP_WARNINGS):
                    fail('startup_diagnostic_shape')
                startup_errors += 1
                continue
            if not isinstance(item, dict) or item.get('type') not in ('reasoning', 'agent_message'):
                fail('unknown_item')
            if not turn_started:
                fail('event_order')
            if item['type'] == 'agent_message' and kind == 'item.completed':
                if final is not None:
                    fail('multiple_agent_messages')
                try:
                    final = _strict_json(item.get('text'))
                except (ValueError, TypeError, RecursionError, OverflowError):
                    fail('agent_message_json')
        elif kind == 'turn.completed':
            if not turn_started:
                fail('missing_turn_started')
            try:
                usage = _usage(event.get('usage'))
            except ValueError:
                fail('usage_shape')
            actual = event.get('model')
            if actual is not None and actual != MODEL:
                fail('reported_model_mismatch')
            completed = True
        else:
            fail('unknown_event')
    if not completed:
        fail('missing_turn_completed')
    if not isinstance(final, dict) or set(final) != {'stateFingerprint', 'summary', 'actions'}:
        fail('decision_shape')
    try:
        _validate(final, schema)
    except _SchemaError as error:
        allowed = {'stateFingerprint', 'summary', 'actions', 'action', 'jobId', 'revision', 'targetUrl',
                   'expectations', 'stage', 'socialRevision', 'approvalCurrent', 'published', 'socialPosted'}
        diagnostic['schemaCode'] = error.code
        diagnostic['schemaPath'] = [p if type(p) is int or p in allowed else 'field' for p in error.path[:20]]
        fail('schema_validation')
    if final['stateFingerprint'] != state_fingerprint:
        fail('state_fingerprint_mismatch')
    result = dict(decision=final, requestedModel=MODEL, actualModel=actual, usage=usage, actualInvoiceUsd=None)
    if startup_errors:
        result['warnings'] = dict(preTurnErrorCount=startup_errors, code='unknown', toolsStartupVerified=False)
    return result


def call(command, snapshot, prompt, schema, timeout=120, *, diagnostic=None):
    """Call once. Schema is a strict JSON object, never a caller-provided file path.

    Only sanitized public snapshot data and local instructions enter stdin. The
    caller must never supply approval capabilities, private bodies or credentials.
    """
    try:
        if diagnostic is not None and not callable(diagnostic):
            raise ValueError()
        argv = _command(command)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= MAX_TIMEOUT:
            raise ValueError()
        if not isinstance(snapshot, dict) or not isinstance(prompt, str) or not prompt.strip():
            raise ValueError()
        _public_json(snapshot)
        _schema(schema)
        if (schema.get('type') != 'object' or set(schema.get('properties', {})) != {'stateFingerprint', 'summary', 'actions'}
                or set(schema.get('required', [])) != {'stateFingerprint', 'summary', 'actions'}):
            raise ValueError()
        # Same semantic key as Manager; do not strip or trust an embedded fingerprint.
        state_fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
            separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
        payload = _json(dict(snapshot=snapshot, instructions=prompt, stateFingerprint=state_fingerprint))
        schema_bytes = _json(schema)
        if len(payload) > MAX_INPUT_BYTES or len(schema_bytes) > MAX_INPUT_BYTES:
            raise ValueError()
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError, re.error):
        raise ValueError('manager_cli_invalid_request') from None
    env = {key: os.environ[key] for key in _ENV_KEYS if key in os.environ}
    env['TZ'] = 'Asia/Tokyo'
    try:
        with tempfile.TemporaryDirectory(prefix='camp-manager-cli-') as folder:
            root = Path(folder)
            os.chmod(root, 0o700)
            work = root / 'work'
            work.mkdir(mode=0o700)
            schema_file = root / 'decision-schema.json'
            fd = os.open(schema_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as out:
                out.write(schema_bytes)
            argv += ['--ephemeral', '--sandbox', 'read-only', '--skip-git-repo-check', '--json',
                     '--color', 'never', '--output-schema', str(schema_file), '--cd', str(work),
                     '-c', 'model_reasoning_effort="high"', '-c', 'web_search="disabled"',
                     '-c', 'include_apply_patch_tool=false', '--enable', 'skip_host_skill_discovery']
            for feature in DISABLED_FEATURES:
                argv += ['--disable', feature]
            raw = _run(argv + ['-'], payload, env, timeout)
    except (TimeoutError, subprocess.TimeoutExpired):
        raise TimeoutError('manager_cli_timeout') from None
    except (OSError, ValueError, subprocess.SubprocessError):
        raise ValueError('manager_cli_failed') from None
    try:
        return _parse(raw, state_fingerprint, schema)
    except ManagerCliOutputError as error:
        if diagnostic is not None:
            try:
                diagnostic(json.loads(_json(error.diagnostic)))
            except Exception:
                pass  # Observability must never change rejection or trigger a retry.
        raise error from None
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError):
        raise ManagerCliOutputError('parser_internal', _output_diagnostic(raw)) from None
