-- products.availability カラム追加（在庫状態のローカル⇔Supabase同期用）
-- 使い方: Supabase の SQL Editor でこのファイルの内容を1回実行し、
-- その後 scripts/sync-to-supabase.js の productToRow で availability 行の
-- コメントアウトを外すと同期が有効になる。
alter table products add column if not exists availability text;
