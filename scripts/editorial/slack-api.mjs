#!/usr/bin/env node
// Uses the already-connected bot; no new credentials or socket receiver.
import {execFileSync} from 'node:child_process';
import {readFileSync} from 'node:fs';

export async function callSlack(input, {token, fetcher = fetch} = {}) {
  const {method, data, scope} = input;
  if (!scope?.team_id || !scope?.bot_user_id || !scope?.channel_id || !scope?.thread_ts) throw Error('slack_scope_missing');
  if (!['chat.postMessage', 'conversations.replies', 'auth.test'].includes(method)) throw Error('slack_method_forbidden');
  if (method !== 'auth.test' && data?.channel !== scope.channel_id) throw Error('slack_channel_mismatch');
  if (method === 'chat.postMessage') {
    if (data.thread_ts !== scope.thread_ts || data.unfurl_links !== false || data.unfurl_media !== false || data.parse !== 'none') throw Error('slack_route_mismatch');
    if (typeof data.text !== 'string' || !data.text || data.text.length > 35000) throw Error('slack_text_invalid');
    if (JSON.stringify(data).match(/xox[baprs]-[A-Za-z0-9-]+|xapp-[A-Za-z0-9-]+/)) throw Error('slack_secret_in_payload');
  }
  if (method === 'conversations.replies' && (data.ts !== scope.thread_ts || data.limit > 100)) throw Error('slack_read_scope');
  const credential = token ?? execFileSync('/usr/bin/security', ['find-generic-password', '-s', 'review-desk-slack-bot', '-a', 'review-desk', '-w'], {encoding:'utf8',timeout:10000,stdio:['ignore','pipe','pipe']}).trim();
  const call = async (name, body) => {
    const read = name === 'conversations.replies';
    const query = read ? '?' + new URLSearchParams(Object.entries(body).map(([k,v])=>[k,String(v)])) : '';
    let r, value;
    try {
      r = await fetcher('https://slack.com/api/' + name + query, {method:read?'GET':'POST',headers:{authorization:'Bearer '+credential,'content-type':'application/json; charset=utf-8'},...(read?{}:{body:JSON.stringify(body)}),redirect:'error',signal:AbortSignal.timeout(20000)});
      value = await r.json();
    } catch { throw Error('slack_result_unknown'); }
    if (!r.ok || value.ok !== true) throw Error('slack_api_rejected');
    return value;
  };
  const identity = await call('auth.test', {});
  if (identity.team_id !== scope.team_id || identity.user_id !== scope.bot_user_id) throw Error('slack_bot_mismatch');
  return method === 'auth.test' ? identity : call(method, data);
}

if (process.argv[1]?.endsWith('/slack-api.mjs')) {
  try { const value = await callSlack(JSON.parse(readFileSync(0,'utf8'))); process.stdout.write(JSON.stringify(value)+'\n'); }
  catch (e) { process.stdout.write(JSON.stringify({ok:false,error:/^[a-z_]+$/.test(e.message)?e.message:'slack_unavailable'})+'\n'); process.exitCode=1; }
}
