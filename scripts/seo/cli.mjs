#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import { createStore } from "./state.mjs";
import { readUsage, renderReport, writeReport } from "./report.mjs";

const PUBLIC_POLICY = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../docs/seo-department/policy.json");

export const HELP = `SEO実験台帳\n\n使い方: node scripts/seo/cli.mjs [--root PATH] [--run-id ID] [--dry-run] <command>\n\nコマンド:\n  init [--policy policy.json]\n  list | due\n  propose --file proposal.json\n  approve ID --file decision.json\n  decide ID --file decision.json\n  record ID --file observation.json\n  event ID --file publication-event.json\n  pause ID [--file reason.json] | resume ID\n  report [--write]\n\n--root がない場合は SEO_STATE_ROOT、次に $HOME/.secretary/state/campgearlab-seo を使います。`;

function parse(argv) {
  const options = { args: [] };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (["--root", "--file", "--policy", "--run-id"].includes(arg)) options[arg.slice(2)] = argv[++index];
    else if (arg === "--dry-run" || arg === "--write") options[arg.slice(2)] = true;
    else options.args.push(arg);
  }
  return options;
}
async function json(filename) { if (!filename) throw new Error("--file JSON is required"); return JSON.parse(await fs.readFile(path.resolve(filename), "utf8")); }
async function configuredPolicy() {
  try { return JSON.parse(await fs.readFile(PUBLIC_POLICY, "utf8")); }
  catch (error) { if (error.code === "ENOENT") return undefined; throw error; }
}
export async function runCli(argv = process.argv.slice(2), { stdout = console.log, stderr = console.error } = {}) {
  const options = parse(argv); const [command, id] = options.args;
  if (!command || command === "help" || command === "--help") { stdout(HELP); return 0; }
  const suppliedPolicy = options.policy ? await json(options.policy) : await configuredPolicy();
  const store = createStore({ root: options.root, dryRun: Boolean(options["dry-run"]), policy: suppliedPolicy, runId: options["run-id"] });
  try {
    let value;
    if (command === "init") value = await store.init();
    else if (command === "list") value = await store.list();
    else if (command === "due") value = await store.due();
    else if (command === "propose") value = await store.propose(await json(options.file));
    else if (command === "approve") value = await store.approve(id, await json(options.file));
    else if (command === "decide") { const decision = await json(options.file); value = await store.transition(id, decision.status, decision); }
    else if (command === "record") value = await store.record(id, await json(options.file));
    else if (command === "event") value = await store.event(id, await json(options.file));
    else if (command === "pause") { const body = options.file ? await json(options.file) : {}; value = await store.pause(id, body.reason); }
    else if (command === "resume") value = await store.resume(id);
    else if (command === "report") {
      const reportData = await store.reportData(); const markdown = renderReport({ ...reportData, usage: await readUsage(store.root) });
      if (options.write) { if (options["dry-run"]) throw new Error("--dry-run cannot be combined with report --write"); value = { markdown, writtenTo: await writeReport(store.root, markdown, reportData.generatedAt) }; }
      else value = { markdown };
    } else throw new Error(`unknown command: ${command}`);
    stdout(command === "report" && !options.write ? value.markdown : JSON.stringify(value, null, 2)); return 0;
  } catch (error) { stderr(`SEO command failed: ${error.message}`); return 1; }
}
if (import.meta.url === `file://${process.argv[1]}`) process.exitCode = await runCli();
