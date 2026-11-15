"""One-use loopback form: owner enters a Buffer key; only macpro stores it.

No key in arguments, files on this host, HTTP logs, responses or command output.
The remote config must explicitly name the dedicated, git-ignored credential file.
"""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import hashlib
import hmac
import json
import re
import secrets
import selectors
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

REMOTE_ROTATE = r'''
import json,sys
from pathlib import Path
root=Path.home()/"Library/Application Support/CampGearLabCodex/editorial"
config_path=root/"config.json"
try:
 config=json.loads(config_path.read_text())
 repo=Path(config["repo"]).resolve()
 sys.path.insert(0,str(repo/"scripts/editorial"))
 from buffer_key_rotation import RotationSession
 session=RotationSession(config_path)
 print(json.dumps({"ready":True,"snapshotDigest":session.baseline_digest,
                   "postCount":len(session.baseline)}),flush=True)
 raw=sys.stdin.read(4097)
 if len(raw)>4096:raise ValueError()
 value=json.loads(raw)
 if set(value)!={"key","postsWriteUiConfirmed"}:raise ValueError()
 result=session.commit(value["key"],posts_write_confirmed=value["postsWriteUiConfirmed"] is True)
 print(json.dumps({"saved":True,"proof":result}),flush=True)
except Exception:
 print(json.dumps({"saved":False,"hold":True}),flush=True)
 raise SystemExit(3)
finally:
 try:session.close()
 except Exception:pass
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


def _readline(process, timeout):
    selector = selectors.DefaultSelector()
    try:
        selector.register(process.stdout, selectors.EVENT_READ)
        if not selector.select(timeout):
            raise TimeoutError()
        line = process.stdout.readline(4097)
        if not line or len(line) > 4096:
            raise ValueError()
        return line
    finally:
        selector.close()


class RemoteRotation:
    def __init__(self, process):
        self.process = process
        self.consumed = False
        try:
            ready = json.loads(_readline(process, 25))
            if (set(ready) != {'ready', 'snapshotDigest', 'postCount'}
                    or ready['ready'] is not True
                    or re.fullmatch(r'[a-f0-9]{64}', str(ready['snapshotDigest'])) is None
                    or type(ready['postCount']) is not int or not 0 <= ready['postCount'] <= 100):
                raise ValueError()
            self.ready = ready
        except Exception:
            self.close()
            raise ValueError('buffer_rotation_prepare_failed') from None

    def commit(self, key, posts_write_confirmed=False):
        if self.consumed or not valid_key(key) or posts_write_confirmed is not True:
            return None
        self.consumed = True
        try:
            self.process.stdin.write(json.dumps({'key': key, 'postsWriteUiConfirmed': True},
                                                 separators=(',', ':')))
            self.process.stdin.close()
            result = json.loads(_readline(self.process, 30))
            code = self.process.wait(timeout=5)
            if code != 0 or not isinstance(result, dict) or result.get('saved') is not True:
                return None
            proof = result.get('proof')
            if (not isinstance(proof, dict) or proof.get('saved') is not True
                    or proof.get('snapshotDigest') != self.ready['snapshotDigest']
                    or proof.get('postCount') != self.ready['postCount']):
                return None
            return proof
        except (OSError, subprocess.SubprocessError, TimeoutError, ValueError):
            return None

    def close(self):
        process = getattr(self, 'process', None)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)


def start_remote_rotation(host='macpro', popen=subprocess.Popen):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', host):
        raise ValueError('buffer_rotation_host_invalid')
    process = popen(['ssh', '-o', 'BatchMode=yes', host,
                     '/usr/bin/python3 -c ' + shlex.quote(REMOTE_ROTATE)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, bufsize=1)
    return RemoteRotation(process)


def serve(host='macpro', *, rotate=False, rotation_factory=start_remote_rotation,
          announce=print, timeout=900):
    token = secrets.token_urlsafe(32)
    signing_key = secrets.token_bytes(32)
    nonce = secrets.token_urlsafe(32)
    signature = hmac.new(signing_key, nonce.encode(), hashlib.sha256).hexdigest()
    rotation = rotation_factory(host) if rotate else None
    consumed = False
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
            if rotate:
                return self.respond(200, '''<!doctype html><html lang="ja"><meta charset="utf-8"><title>Camp Bufferキー更新</title>
<style>body{font:18px system-ui;max-width:680px;margin:60px auto;padding:24px;line-height:1.7}input{font:inherit;width:95%;padding:12px}button{font:inherit;padding:12px;margin-top:24px}</style>
<h1>Camp Gear LabのBufferキー更新</h1><p>旧キーによる読取snapshotを取得し、ローカル実行を静止しました。ここからBuffer UIで同じキーを再生成してください。</p>
<p>posts write権限はread-only APIでは証明できません。Buffer UIでaccount read・posts read・posts writeが維持されていることを確認してください。</p>
<form method="post"><input type="hidden" name="nonce" value="''' + nonce + '''"><input type="hidden" name="signature" value="''' + signature + '''">
<label>新しいAPIキー<input name="key" type="password" required autocomplete="off" maxlength="2048"></label>
<label><input name="posts_write_confirmed" type="checkbox" value="1" required> Buffer UIでposts writeを維持したことを確認しました（APIでの証明ではありません）</label>
<button type="submit">読取照合して資格情報だけを更新する</button></form></html>''')
            self.respond(200, '''<!doctype html><html lang="ja"><meta charset="utf-8"><title>Camp Buffer接続</title>
<style>body{font:18px system-ui;max-width:680px;margin:60px auto;padding:24px;line-height:1.7}input{font:inherit;width:95%;padding:12px}button{font:inherit;padding:12px;margin-top:24px}</style>
<h1>Camp Gear LabのBuffer接続</h1><p>Bufferで作成したCamp用APIキーを入力してください。チャットへ貼る必要はありません。</p>
<p>キーはこのMacには保存せず、SSHでmacproのCamp専用設定へ直接保存します。記事公開・SNS予約・投稿は実行しません。</p>
<form method="post"><label>APIキー<input name="key" type="password" required autocomplete="off" maxlength="2048"></label>
<button type="submit">macproへ保存する</button></form></html>''')

        def do_POST(self):
            nonlocal consumed
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
                expected = ({'key', 'nonce', 'signature', 'posts_write_confirmed'}
                            if rotate else {'key'})
                if set(fields) != expected or any(len(value) != 1 for value in fields.values()):
                    raise ValueError()
                if rotate and (fields['nonce'][0] != nonce
                               or not hmac.compare_digest(fields['signature'][0], signature)
                               or fields['posts_write_confirmed'][0] != '1'):
                    raise ValueError()
                key = fields['key'][0]
            except (ValueError, UnicodeError, OSError):
                return self.respond(400, '入力を確認してください。')
            if rotate:
                if consumed:
                    return self.respond(409, 'この更新画面は使用済みです。')
                consumed = True
                proof = rotation.commit(key, posts_write_confirmed=True)
                if not proof:
                    self.respond(409, '照合または保存結果を確認できません。再試行せず、Codexへ照合を依頼してください。')
                else:
                    self.respond(200, '<meta charset="utf-8"><h1>資格情報を更新しました</h1><p>account/posts読取とqueue不変を確認しました。posts writeはBuffer UIでの本人確認であり、read-only APIによる証明ではありません。</p>')
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if not self.server.save_key(key, host):
                return self.respond(409, '保存できませんでした。既存キーは上書きしていません。キーをチャットへ貼らずCodexへお知らせください。')
            self.respond(200, '<meta charset="utf-8"><h1>保存しました</h1><p>Codexへ「保存済み」とお知らせください。接続確認・予約投稿の検証はこれから行います。</p>')
            threading.Thread(target=self.server.shutdown, daemon=True).start()

    server = HTTPServer(('127.0.0.1', 0), Handler)
    server.authority = '127.0.0.1:' + str(server.server_port)
    server.save_key = save_remote
    server.timeout = timeout
    announce({'setupUrl': 'http://' + server.authority + '/' + token})
    timer = threading.Timer(timeout, server.shutdown)
    timer.daemon = True
    timer.start()
    try:
        server.serve_forever()
    finally:
        timer.cancel()
        server.server_close()
        if rotation is not None:
            rotation.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='macpro')
    parser.add_argument('--rotate', action='store_true')
    args = parser.parse_args()
    serve(args.host, rotate=args.rotate,
          announce=lambda value: print(json.dumps(value), flush=True))
