-- affiliate_clicks テーブル作成
-- Supabase SQL Editor で実行してください

CREATE TABLE IF NOT EXISTS affiliate_clicks (
  id BIGSERIAL PRIMARY KEY,
  product_id TEXT NOT NULL,
  store TEXT NOT NULL,
  page_path TEXT DEFAULT '',
  clicked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ip TEXT DEFAULT '',
  ua TEXT DEFAULT '',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_product ON affiliate_clicks(product_id);
CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_date ON affiliate_clicks(clicked_at);

ALTER TABLE affiliate_clicks ENABLE ROW LEVEL SECURITY;
CREATE POLICY "clicks_insert" ON affiliate_clicks FOR INSERT WITH CHECK (true);
CREATE POLICY "clicks_read" ON affiliate_clicks FOR SELECT USING (true);
