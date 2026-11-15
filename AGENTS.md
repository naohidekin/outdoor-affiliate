<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

## Camp編集のBuffer接続

- Bufferの資格情報はホストローカルの編集設定 `bufferEnvFile` が指定する、このリポジトリ直下の `.env.buffer.local` のみを使う。
- キー名は `BUFFER_API_KEY`。ファイルは0600・Git対象外とし、別プロジェクトの資格情報探索、チャット表示、ログ出力、同期をしない。
- 初回接続は `scripts/editorial/buffer_connection_setup.py` の一度限りのローカル入力画面を使い、既存キーを上書きしない。本人が更新を指定した場合だけ `--rotate` で更新前snapshotと新キー検証を通した原子的差替えを行う。キー再生成は本人操作とし、失効・発行・プラン変更を自動実行しない。
- Bufferの予約と実際のX投稿は区別する。記事承認とSNS対象版承認は別で、以前の直接X投稿承認をBufferに流用しない。
