-- 月次クリックレポート（EPC分析用）
-- 使い方: Supabase Dashboard → SQL Editor に貼り付け、期間の2行を対象月に
-- 書き換えて Run → 結果テーブル右上の「Download CSV」で保存。
-- 成果レポート（楽天注文別CSV・Amazonトラッキング別CSV）と同じ月に合わせること。
-- 期間はJST（clicked_atはUTC保存のため+09:00付きで指定する）。

-- ① 記事×商品×ストア別クリック（分析のメイン。これをCSVで渡す）
select
  page_path,
  product_id,
  max(product_name) as product_name,
  store,
  coalesce(placement, '(旧データ)') as placement,
  count(*) as clicks
from affiliate_clicks
where clicked_at >= '2026-07-01T00:00:00+09:00'
  and clicked_at <  '2026-08-01T00:00:00+09:00'
group by page_path, product_id, store, placement
order by clicks desc;

-- ② おまけ: ストア別合計（楽天/Amazon/Yahooの総クリック。①だけでも計算可能）
-- select store, count(*) as clicks
-- from affiliate_clicks
-- where clicked_at >= '2026-07-01T00:00:00+09:00'
--   and clicked_at <  '2026-08-01T00:00:00+09:00'
-- group by store order by clicks desc;
