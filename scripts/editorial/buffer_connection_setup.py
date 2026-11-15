"""One-use loopback form: owner enters a Buffer key; only macpro stores it.

No key in arguments, files on this host, HTTP logs, responses or command output.
The remote config must explicitly name the dedicated, git-ignored credential file.
"""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import re
import secrets
import shlex
import subprocess
import threading
from urllib.parse import parse_qs


REMOTE_SAVE = r'''
import os,json,re,sys
from pathlib import Path
key=sys.stdin.read(4097).strip()
if not re.fullmatch(r"[A-Za-z0-9_.:/+=-]{16,2048}",key):raise SystemExit(2)
root=Path.home()/"Library/Application Support/CampGearLabCodex/editorial"
config=json.loads((root/"config.json").read_text())
dest=Path(config["bufferEnvFile"])
repo=Path(config["repo"]).resolve()
if dest != repo/".env.buffer.local" or dest.is_symlink():raise SystemExit(2)
fd=os.open(str(dest),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,"w") as stream:
 stream.write("BUFFER_API_KEY="+key+"\n");stream.flush();os.fsync(stream.fileno())
print(json.dumps({"saved":True}))
'''


def valid_key(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:/+=-]{16,2048}', value) is not None


def save_remote(key, host='macpro', runner=subprocess.run):
    if not valid_key(key) or not re.fullmatch(r'[A-Za-z0-9_-]+', host):
        return False
    try:
        result = runner(['ssh', '-o', 'BatchMode=yes', host,
                         '/usr/bin/python3 -c ' + shlex.quote(REMOTE_SAVE)],
                        input=key, text=True, capture_output=True, timeout=25)
        return result.returncode == 0 and json.loads(result.stdout) == {'saved': True}
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def serve(host='macpro'):
    token = secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(5)
            super().setup()

        def log_message(self, *args):
            pass

        def respond(self, code, body):
            raw = body.encode('utf-8')
            self.send_response(code)
            for key, value in [('Content-Type', 'text/html; charset=utf-8'),
                               ('Cache-Control', 'no-store'), ('Referrer-Policy', 'same-origin'),
                               ('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"),
                               ('X-Content-Type-Options', 'nosniff'), ('Content-Length', str(len(raw)))]:
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(raw)

        def allowed(self):
            return self.path == '/' + token and self.headers.get('Host') == self.server.authority

        def do_GET(self):
            if not self.allowed():
                return self.respond(404, 'Not found')
            self.respond(200, '''<!doctype html><html lang="ja"><meta charset="utf-8"><title>Camp Buffer接続</title>
<style>body{font:18px system-ui;max-width:680px;margin:60px auto;padding:24px;line-height:1.7}input{font:inherit;width:95%;padding:12px}button{font:inherit;padding:12px;margin-top:24px}</style>
<h1>Camp Gear LabのBuffer接続</h1><p>Bufferで作成したCamp用APIキーを入力してください。チャットへ貼る必要はありません。</p>
<p>キーはこのMacには保存せず、SSHでmacproのCamp専用設定へ直接保存します。記事公開・SNS予約・投稿は実行しません。</p>
<form method="post"><label>APIキー<input name="key" type="password" required autocomplete="off" maxlength="2048"></label>
<button type="submit">macproへ保存する</button></form></html>''')

        def do_POST(self):
            if not self.allowed() or self.headers.get('Origin') != 'http://' + self.server.authority:
                return self.respond(403, 'Forbidden')
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 8192 or self.headers.get('Content-Type', '').split(';')[0] != 'application/x-www-form-urlencoded':
                    raise ValueError()
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError()
                fields = parse_qs(raw.decode(), strict_parsing=True)
                if set(fields) != {'key'} or len(fields['key']) != 1:
                    raise ValueError()
                key = fields['key'][0]
            except (ValueError, UnicodeError, OSError):
                return self.respond(400, '入力を確認してください。')
            if not self.server.save_key(key, host):
                return self.respond(409, '保存できませんでした。既存キーは上書きしていません。キーをチャットへ貼らずCodexへお知らせください。')
            self.respond(200, '<meta charset="utf-8"><h1>保存しました</h1><p>Codexへ「保存済み」とお知らせください。接続確認・予約投稿の検証はこれから行います。</p>')
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    server = HTTPServer(('127.0.0.1', 0), Handler)
    server.authority = '127.0.0.1:' + str(server.server_port)
    server.save_key = save_remote
    server.timeout = 900
    print(json.dumps({'setupUrl': 'http://' + server.authority + '/' + token}), flush=True)
    timer = threading.Timer(900, server.shutdown)
    timer.daemon = True
    timer.start()
    try:
        server.serve_forever()
    finally:
        timer.cancel()
        server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='macpro')
    args = parser.parse_args()
    serve(args.host)
