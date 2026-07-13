-- affiliate_clicks に placement（ボタン位置）と product_name を追加
-- 使い方: Supabase の SQL Editor でこの内容を1回実行する。
-- 実行後、/api/track-click が新カラムへ書き込みを始める（既存行はNULLのまま＝無害）。
alter table affiliate_clicks add column if not exists placement text;
alter table affiliate_clicks add column if not exists product_name text;

-- 集計を速くするための任意インデックス（無くても動く）
create index if not exists idx_affiliate_clicks_placement on affiliate_clicks (placement);
