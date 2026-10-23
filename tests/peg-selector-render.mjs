// Local rendering check; explicitly reuses installed libraries. No app server or API.
// node tests/peg-selector-render.mjs --dependency-root /path/node_modules [--extra-dependency-root /other/node_modules] [--browser]
import assert from "node:assert/strict";
import { createRequire, register } from "node:module";
import { mkdtemp, readFile, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";

const arg = (name) => process.argv.includes(name) ? process.argv[process.argv.indexOf(name) + 1] : undefined;
const roots = [arg("--dependency-root"), arg("--extra-dependency-root")].filter(Boolean);
if (!roots.length || roots.some((root) => !path.isAbsolute(root))) throw new Error("Explicit absolute dependency roots required");
const require = createRequire(path.join(roots[0], "fixture.cjs"));
const repository = fileURLToPath(new URL("../", import.meta.url));
const temp = await mkdtemp(path.join(tmpdir(), "peg-selector-test-"));
let browser;
let page;
let blocked = 0;
const browserErrors = [];
try {
  const loader = path.join(temp, "loader.mjs");
  await writeFile(loader, `
    import {createRequire} from 'node:module'; import {readFileSync,existsSync} from 'node:fs';
    import {pathToFileURL,fileURLToPath} from 'node:url'; import path from 'node:path';
    const requires=${JSON.stringify(roots)}.map(root=>createRequire(path.join(root,'fixture.cjs')));
    const ts=requires[0]('typescript'); const repository=${JSON.stringify(repository)};
    export function resolve(specifier,context,nextResolve){
      let candidate;
      if(specifier.startsWith('@/')) candidate=path.join(repository,'src',specifier.slice(2));
      else if(specifier.startsWith('.') && context.parentURL?.startsWith('file:')) candidate=fileURLToPath(new URL(specifier,context.parentURL));
      if(candidate){for(const suffix of ['', '.ts','.tsx','.js']) if(existsSync(candidate+suffix)) return {url:pathToFileURL(candidate+suffix).href,shortCircuit:true};}
      if(!specifier.startsWith('.')&&!specifier.startsWith('/')&&!specifier.includes(':')){
        for(const require of requires){try{return {url:pathToFileURL(require.resolve(specifier)).href,shortCircuit:true};}catch{}}
      }
      return nextResolve(specifier,context);
    }
    export function load(url,context,nextLoad){
      if(url.startsWith('file:')&&/\\.tsx?$/.test(url)) return {format:'module',shortCircuit:true,source:ts.transpileModule(readFileSync(fileURLToPath(url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020,jsx:ts.JsxEmit.ReactJSX}}).outputText};
      return nextLoad(url,context);
    }
  `);
  register(pathToFileURL(loader));
  const React = require("react");
  const { renderToStaticMarkup, renderToString } = require("react-dom/server");
  const { default: Guide } = await import(pathToFileURL(path.join(repository, "src/components/PegGuideContent.tsx")));
  const { default: Selector } = await import(pathToFileURL(path.join(repository, "src/components/PegProductSelector.tsx")));
  const { PEG_VARIANTS } = await import(pathToFileURL(path.join(repository, "src/lib/pegs/variants.ts")));
  const content = "## Before the selector\n\n| A | B |\n|---|---|\n| one | two |\n\n<!-- PRODUCT_SELECTOR -->\n\n## After the selector\n\nArticle end.";
  const html = renderToStaticMarkup(React.createElement(Guide, { content }));
  assert.equal((html.match(/data-peg-variant=/g) || []).length, 17);
  assert.equal((html.match(/<select\b/g) || []).length, 3);
  assert.match(html, /Before the selector/); assert.match(html, /After the selector/);
  assert.ok(html.indexOf("Before the selector") < html.indexOf('id="product-selector"'));
  assert.ok(html.indexOf("After the selector") > html.indexOf('id="product-selector"'));
  assert.doesNotMatch(html, /<img\b|PRODUCT_SELECTOR|Slack|imageRights|利用条件を確認中/);
  assert.match(html, /aria-live="polite"/);
  assert.match(html, /販売先で.*選択/);
  assert.match(html, /Amazonで検索（広告）/);
  assert.throws(() => renderToStaticMarkup(React.createElement(Guide, { content: "missing marker" })));
  const escaped = renderToStaticMarkup(React.createElement(Selector, { variants: [{ ...PEG_VARIANTS[0], name: '<img src="https://evil.test/x">' }] }));
  assert.doesNotMatch(escaped, /<img\b/); assert.match(escaped, /&lt;img/);
  console.log("PASS SSR: 17 variants, 3 labelled filters, all links present without JS, marker position, missing-marker rejection, no product images/private fields, escaped text.");

  if (process.argv.includes("--browser")) {
    const { webpack } = require("next/dist/compiled/webpack/webpack.js");
    const tsLoader = path.join(temp, "typescript-loader.cjs");
    await writeFile(tsLoader, `const ts=require(${JSON.stringify(require.resolve("typescript"))});module.exports=function(source){return ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020,jsx:ts.JsxEmit.ReactJSX}}).outputText;};`);
    const entry = path.join(temp, "entry.js");
    await writeFile(entry, `import React,{useEffect} from 'react';import {hydrateRoot} from 'react-dom/client';
      import Selector from ${JSON.stringify(path.join(repository, "src/components/PegProductSelector.tsx"))};
      import {PEG_VARIANTS} from ${JSON.stringify(path.join(repository, "src/lib/pegs/variants.ts"))};
      function Harness(){
        useEffect(()=>{document.documentElement.dataset.pegHydrated='true';},[]);
        return React.createElement(Selector,{variants:PEG_VARIANTS});
      }
      hydrateRoot(document.getElementById('root'),React.createElement(Harness));`);
    await new Promise((resolve, reject) => {
      const compiler = webpack({ mode: "development", devtool: false, entry, resolve: { modules: roots, extensions: [".tsx", ".ts", ".js"], alias: { "@": path.join(repository, "src") } },
        // Match Next's browser replacement without reading real environment variables.
        plugins: [new webpack.DefinePlugin({ "process.env": JSON.stringify({ NODE_ENV: "development", NEXT_PUBLIC_POSTHOG_KEY: "", NEXT_PUBLIC_POSTHOG_HOST: "" }) })],
        module: { rules: [{ test: /\.tsx?$/, use: tsLoader, exclude: /node_modules/ }] },
        // Inline fixture scripts have no script URL from which webpack can infer a chunk base.
        // Any unexpected chunk request is still blocked by the browser interceptor.
        output: { path: temp, filename: "bundle.js", publicPath: "/" } });
      compiler.run((error, stats) => compiler.close(() => error || stats.hasErrors() ? reject(error || new Error(stats.toString({ all: false, errors: true }))) : resolve()));
    });
    browser = await require("puppeteer").launch({ headless: true, executablePath: arg("--chrome") || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
      args: ["--disable-background-networking", "--disable-component-update", "--no-first-run"] });
    page = await browser.newPage();
    await page.setViewport({ width: 390, height: 844 });
    await page.setRequestInterception(true);
    page.on("request", (request) => { blocked++; void request.abort(); });
    page.on("pageerror", (error) => browserErrors.push(`pageerror: ${error.message}`));
    page.on("console", (message) => { if (message.type() === "error") browserErrors.push(`console: ${message.text()}`); });
    function Harness() {
      React.useEffect(() => {}, []);
      return React.createElement(Selector, { variants: PEG_VARIANTS });
    }
    // Hydration needs React's text-node boundary markers; static markup omits them.
    await page.setContent(`<html><body><div id="root">${renderToString(React.createElement(Harness))}</div></body></html>`);
    await page.addScriptTag({ content: await readFile(path.join(temp, "bundle.js"), "utf8") });
    await page.waitForFunction(() => document.documentElement.dataset.pegHydrated === "true", { timeout: 10000 });
    assert.deepEqual(browserErrors, []);
    await page.waitForFunction(() => document.querySelectorAll('[data-peg-variant]').length === 17);
    const ids = await page.$$eval("select", (elements) => elements.map((element) => element.id));
    assert.equal(await page.$$eval("label", (labels) => labels.every((label) => !!document.getElementById(label.htmlFor))), true);
    await page.select(`[id="${ids[0]}"]`, "18cm");
    await page.waitForFunction(() => document.querySelectorAll('[data-peg-variant]').length === 5);
    await page.select(`[id="${ids[1]}"]`, "ブラック");
    await page.waitForFunction(() => document.querySelectorAll('[data-peg-variant]').length === 0);
    assert.match(await page.$eval("[role=status]", (element) => element.textContent), /^0件/);
    assert.match(await page.$eval("body", (element) => element.textContent), /この条件の組み合わせは掲載していません/);
    await page.select(`[id="${ids[0]}"]`, "28cm");
    await page.waitForFunction(() => document.querySelector('[data-peg-variant="ellisse-28-black"]'));
    assert.equal(await page.$$eval('[data-peg-variant]', (elements) => elements.length), 1);
    assert.match(await page.$eval('[data-peg-variant]', (element) => element.textContent), /8本/);
    await page.click("button");
    await page.waitForFunction(() => document.querySelectorAll('[data-peg-variant]').length === 17);
    assert.equal(await page.evaluate(() => document.activeElement?.id), ids[0]);
    assert.equal(await page.$("img"), null);
    assert.equal(blocked, 0);
    assert.deepEqual(browserErrors, []);
    console.log("PASS browser: SSR hydration, size/color intersection, zero result, exact variant, reset/focus, no images, no external requests. No affiliate links clicked.");
  }
} catch (error) {
  const state = await page?.evaluate(() => ({ hydrated: document.documentElement.dataset.pegHydrated ?? false,
    count: document.querySelectorAll('[data-peg-variant]').length,
    filters: [...document.querySelectorAll('select')].map((select) => ({ id: select.id, value: select.value })) })).catch(() => null);
  console.error("Browser diagnostics:", JSON.stringify({ errors: browserErrors, blockedRequests: blocked, state }, null, 2));
  throw error;
} finally {
  await browser?.close();
  await rm(temp, { recursive: true, force: true });
}
