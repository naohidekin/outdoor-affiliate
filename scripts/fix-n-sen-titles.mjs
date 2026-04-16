#!/usr/bin/env node
import { createClient } from "@supabase/supabase-js";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";

loadEnv();
const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY);

// タイトルの数字だけ置換する（他の文言は維持）
const fixes = [
  { slug: "compact-tent-ranking",           from: "9選", to: "3選" },
  { slug: "low-table-ranking",              from: "8選", to: "3選" },
  { slug: "family-camp-chair-ranking",      from: "7選", to: "3選" },
  { slug: "rain-proof-tent-ranking",        from: "8選", to: "3選" },
  { slug: "tent-vestibule-size-ranking",    from: "7選", to: "3選" },
  { slug: "solo-tarp-ranking",              from: "5選", to: "3選" },
  { slug: "compact-lightweight-chair-ranking", from: "7選", to: "3選" },
  { slug: "rain-camp-gear-essentials",      from: "7選", to: "3選" },
];

for (const f of fixes) {
  const { data } = await supabase.from("articles").select("id, title").eq("slug", f.slug).single();
  if (!data) { console.log("NOT FOUND:", f.slug); continue; }

  const newTitle = data.title.replace(f.from, f.to);
  const { error } = await supabase
    .from("articles")
    .update({ title: newTitle, updated_at: new Date().toISOString() })
    .eq("id", data.id);

  if (error) console.log("ERROR:", f.slug, error.message);
  else console.log(`✅ ${f.slug}\n   ${data.title}\n   → ${newTitle}\n`);
}
