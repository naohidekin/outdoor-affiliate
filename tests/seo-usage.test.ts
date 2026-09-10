import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { estimateUsage, parseSessionUsage, main } from "../scripts/seo/usage.mjs";

const line = (timestamp: string, body: object) => JSON.stringify({ timestamp, ...body });

test("uses deltas of cumulative usage and does not double count reasoning", () => {
  const text = [
    line("2026-09-11T00:00:00Z", { turn_context: { model: "gpt-6-astra" } }),
    line("2026-09-11T00:01:00Z", { token_count: { total_token_usage: { input_tokens: 100, cached_input_tokens: 20, cache_write_input_tokens: 5, output_tokens: 30, reasoning_output_tokens: 10 } } }),
    line("2026-09-11T00:02:00Z", { token_count: { total_token_usage: { input_tokens: 180, cached_input_tokens: 40, cache_write_input_tokens: 5, output_tokens: 50, reasoning_output_tokens: 15 } } }),
  ].join("\n");
  const result = parseSessionUsage(text);
  assert.deepEqual(result.models[0], { model: "gpt-6-astra", inputTokens: 180, cachedInputTokens: 40, cacheWriteInputTokens: 5, outputTokens: 50, reasoningOutputTokens: 15, unknown: false });
});

test("window filtering retains the baseline outside the window", () => {
  const text = [
    line("2026-09-10T00:00:00Z", { token_count: { total_token_usage: { input_tokens: 100, output_tokens: 10, cached_input_tokens: 0, cache_write_input_tokens: 0 } } }),
    line("2026-09-11T00:00:00Z", { token_count: { total_token_usage: { input_tokens: 160, output_tokens: 20, cached_input_tokens: 0, cache_write_input_tokens: 0 } } }),
  ].join("\n");
  assert.equal(parseSessionUsage(text, { since: "2026-09-11T00:00:00Z" }).models[0].inputTokens, 60);
});

test("model changes attribute subsequent deltas and counter resets are conservative", () => {
  const text = [
    line("2026-09-11T00:00:00Z", { turn_context: { model: "gpt-6-astra" }, token_count: { total_token_usage: { input_tokens: 100, cached_input_tokens: 0, cache_write_input_tokens: 0, output_tokens: 10 } } }),
    line("2026-09-11T00:01:00Z", { turn_context: { model: "gpt-5.6-luna" }, token_count: { total_token_usage: { input_tokens: 10, cached_input_tokens: 0, cache_write_input_tokens: 0, output_tokens: 2 } } }),
    line("2026-09-11T00:02:00Z", { token_count: { total_token_usage: { input_tokens: 30, cached_input_tokens: 0, cache_write_input_tokens: 0, output_tokens: 4 } } }),
  ].join("\n");
  const result = parseSessionUsage(text);
  assert.equal(result.models.find((m) => m.model === "gpt-5.6-luna")?.inputTokens, 20);
  assert.equal(result.attribution, "measured_with_anomalies");
});

test("unknown model or missing token values never fabricates estimates", () => {
  assert.equal(estimateUsage("mystery", { inputTokens: 10, cachedInputTokens: 0, cacheWriteInputTokens: 0, outputTokens: 2 }).apiUsdEstimate, null);
  assert.equal(estimateUsage("gpt-6-astra", { inputTokens: 10, cachedInputTokens: 0, outputTokens: 2 }).apiUsdEstimate, null);
});

test("write is an idempotent run upsert and stores only source basenames", async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "seo-usage-"));
  const log = path.join(dir, "run.jsonl");
  const root = path.join(dir, "state");
  await fs.writeFile(log, line("2026-09-11T00:00:00Z", { turn_context: { model: "gpt-6-astra" }, token_count: { total_token_usage: { input_tokens: 1, cached_input_tokens: 0, cache_write_input_tokens: 0, output_tokens: 1 } } }));
  await main(["--session", log, "--id", "run-1", "--root", root, "--write"]);
  await main(["--session", log, "--id", "run-1", "--root", root, "--write"]);
  const state = JSON.parse(await fs.readFile(path.join(root, "usage.json"), "utf8"));
  assert.equal(state.runs.length, 1);
  assert.deepEqual(state.runs[0].sourcePaths, ["run.jsonl"]);
  await fs.rm(dir, { recursive: true, force: true });
});

test('real Codex schema without cache-write computes credits but keeps API unknown',async()=>{
  const result=estimateUsage('gpt-6-astra',{inputTokens:1000,cachedInputTokens:800,outputTokens:100});
  assert.equal(result.codexCreditsEstimate,.195);assert.equal(result.apiUsdEstimate,null);
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'seo-real-usage-'));
  try {
    const log=path.join(dir,'real.jsonl');
    await fs.writeFile(log,[line('2026-09-11T00:00:00Z',{type:'turn_context',payload:{model:'gpt-6-astra'}}),line('2026-09-11T00:01:00Z',{type:'event_msg',payload:{type:'token_count',info:{total_token_usage:{input_tokens:1000,cached_input_tokens:800,output_tokens:100,reasoning_output_tokens:40}}}})].join('\n'));
    const report=await main(['--session',log]);
    assert.equal(report.run.codexCreditsEstimate,.195);assert.equal(report.run.models[0].cacheWriteInputTokens,null);assert.equal(report.run.apiUsdEstimate,null);
  }finally{await fs.rm(dir,{recursive:true,force:true});}
});

test('rate-limit-only event does not reset cumulative baseline across time window',()=>{
  const text=[line('2026-09-11T00:00:00Z',{turn_context:{model:'gpt-6-astra'},token_count:{total_token_usage:{input_tokens:100,cached_input_tokens:50,output_tokens:10}}}),line('2026-09-11T00:01:00Z',{type:'event_msg',payload:{type:'token_count',info:null,rate_limits:{}}}),line('2026-09-11T00:02:00Z',{token_count:{total_token_usage:{input_tokens:150,cached_input_tokens:70,output_tokens:15}}})].join('\n');
  assert.equal(parseSessionUsage(text,{since:'2026-09-11T00:01:30Z'}).models[0].inputTokens,50);
  assert.equal(parseSessionUsage(text).models[0].inputTokens,150);
});
