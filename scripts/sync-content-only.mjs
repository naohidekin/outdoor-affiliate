#!/usr/bin/env node
// 特定記事のcontent+updated_atのみをSupabaseに同期（quality_score等を保持）
import { createClient } from "@supabase/supabase-js";
import { loadEnv, readJson } from "../src/lib/x-agent-utils.mjs";

loadEnv();

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY);
const articles = readJson("articles.json");

const ids = process.argv.slice(2).length > 0
  ? process.argv.slice(2)
  : [
      "4d6b5cc3-8cdb-4cab-bac9-279f7011d557",
      "27494334-4734-4495-8520-37f472784734",
      "ff10c312-bce0-4d26-a624-4dfc043d5fa2",
      "cf991360-06ef-47e0-8d57-9360add42fe3",
      "e9755060-ccc7-43fe-8b60-c2563ce083da",
      "e0947ba0-14d5-47e9-8d11-c6a3eb41e34b",
    ];

for (const id of ids) {
  const a = articles.find((x) => x.id === id);
  if (!a) { console.log("NOT FOUND:", id); continue; }
  const { error } = await supabase
    .from("articles")
    .update({ content: a.content, updated_at: a.updatedAt })
    .eq("id", id);
  if (error) { console.error("ERROR:", a.slug, error.message); }
  else { console.log("OK:", a.slug); }
}
console.log("完了");
