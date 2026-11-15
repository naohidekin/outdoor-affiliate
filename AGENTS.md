<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

## Camp編集のBuffer接続

- Bufferの資格情報はホストローカルの編集設定 `bufferEnvFile` が指定する、このリポジトリ直下の `.env.buffer.local` のみを使う。
- キー名は `BUFFER_API_KEY`。ファイルは0600・Git対象外とし、別プロジェクトの資格情報探索、チャット表示、ログ出力、同期をしない。
- 接続準備は `scripts/editorial/buffer_connection_setup.py` の一度限りのローカル入力画面を使う。既存キーの上書き・失効、新規キー発行、プラン変更は行わない。
- Bufferの予約と実際のX投稿は区別する。記事承認とSNS対象版承認は別で、以前の直接X投稿承認をBufferに流用しない。
