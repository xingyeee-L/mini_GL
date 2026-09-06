"""Loopback-only visual acceptance console for ingestion."""

# ruff: noqa: E501 -- embedded HTML/CSS/JavaScript remains readable as a browser artifact.

from __future__ import annotations

import json
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mini_gl.ingestion import IngestionService
from mini_gl.storage.sqlite import SQLiteStore

PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>mini_GL 验收台</title><style>
:root{font-family:system-ui,sans-serif;color:#202124;background:#f6f7f8}*{box-sizing:border-box}
body{margin:0}.top{background:#fff;border-bottom:1px solid #ddd;padding:16px 5vw;display:flex;justify-content:space-between}
main{max-width:1100px;margin:auto;padding:28px 20px}.panel{background:#fff;border:1px solid #ddd;border-radius:12px;padding:20px;margin-bottom:16px}
h1{font-size:20px;margin:0}h2{font-size:16px;margin:0 0 14px}.safe{color:#187442}.row{display:flex;gap:10px;flex-wrap:wrap;align-items:end}
label{display:grid;gap:6px;flex:1;min-width:260px;color:#555}input,select,button{font:inherit;padding:10px;border:1px solid #bbb;border-radius:7px;background:#fff}
button{cursor:pointer}button.primary{background:#202124;color:#fff}.flow,.metrics{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}.flow div,.metric{background:#f7f8f9;padding:12px;border-radius:8px;text-align:center}
.flow b{display:block;color:#187442}.metrics{grid-template-columns:repeat(4,1fr)}.metric strong{display:block;font-size:24px}.metric span{color:#666}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border-bottom:1px solid #eee}th{color:#666;font-weight:500}.error{color:#b3261e}.muted{color:#666}
@media(max-width:650px){.flow{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,1fr)}.table{overflow:auto}}
</style></head><body><header class="top"><h1>🧠 mini_GL · 阶段 1 验收台</h1><span class="safe">🛡 只读 · 仅本机</span></header>
<main><section class="panel"><h2>1. 注册测试资料目录</h2><form id="register" class="row"><label>目录绝对路径<input name="root" required placeholder="C:\\path\\to\\test-files"></label><button class="primary">注册</button></form></section>
<section class="panel"><h2>2. 选择数据源并同步</h2><div class="row"><label>数据源<select id="sources"></select></label><button class="primary" id="sync">执行只读同步</button><button id="refresh">刷新状态</button></div><p id="message" class="muted" aria-live="polite">正在读取本地状态…</p></section>
<section class="panel"><div class="flow"><div><b>✓</b>授权目录</div><div><b>✓</b>安全扫描</div><div><b>✓</b>文本解析</div><div><b>✓</b>标准化</div><div><b>✓</b>原子保存</div></div></section>
<section class="panel"><h2>3. 最近一次同步结果</h2><div class="metrics"><div class="metric"><span>新增</span><strong id="created">0</strong></div><div class="metric"><span>更新</span><strong id="updated">0</strong></div><div class="metric"><span>未变化</span><strong id="unchanged">0</strong></div><div class="metric"><span>删除</span><strong id="deleted">0</strong></div></div></section>
<section class="panel"><h2>4. 文件状态（不显示正文）</h2><div class="table"><table><thead><tr><th>相对路径</th><th>大小</th><th>SHA-256</th><th>最近事件</th></tr></thead><tbody id="files"></tbody></table></div></section>
</main><script>
const token=__TOKEN__;const el=id=>document.getElementById(id);let sources=[];
async function api(path,options={}){options.headers={...(options.headers||{}),'X-Mini-GL-CSRF':token};const r=await fetch(path,options);const data=await r.json();if(!r.ok)throw new Error(data.message||'操作失败');return data}
function counts(events){const out={created:0,updated:0,unchanged:0,deleted:0};for(const e of events)if(e.kind in out)out[e.kind]++;return out}
async function load(keep=true){sources=await api('/api/sources');const old=el('sources').value;el('sources').replaceChildren(...sources.map(s=>{const option=document.createElement('option');option.value=s.source_id;option.textContent=s.root_path;return option}));if(keep&&sources.some(s=>s.source_id===old))el('sources').value=old;await detail()}
async function detail(){const id=el('sources').value;if(!id){el('message').textContent='请先注册一个测试资料目录。';el('files').innerHTML='';return}const d=await api('/api/source/'+encodeURIComponent(id));const c=counts(d.events);for(const k of Object.keys(c))el(k).textContent=c[k];const map=Object.fromEntries(d.events.map(e=>[e.object_id,e.kind]));el('files').innerHTML=d.files.map(f=>`<tr><td>${escapeHtml(f.relative_path)}</td><td>${f.size} B</td><td>${f.content_hash.slice(0,12)}…</td><td>${map[f.object_id]||'—'}</td></tr>`).join('');const run=d.status.latest_run;el('message').textContent=run?`最近状态：${run.status} · 文件 ${d.files.length} 个 · 原文件不会被修改`:'尚未同步'}
function escapeHtml(v){const d=document.createElement('div');d.textContent=v;return d.innerHTML}
el('register').addEventListener('submit',async e=>{e.preventDefault();try{const root=new FormData(e.target).get('root');await api('/api/register',{method:'POST',body:JSON.stringify({root})});await load(false)}catch(x){el('message').textContent=x.message;el('message').className='error'}});
el('sync').addEventListener('click',async()=>{try{el('message').textContent='正在安全扫描并同步…';const id=el('sources').value;await api('/api/sync',{method:'POST',body:JSON.stringify({source_id:id})});await detail()}catch(x){el('message').textContent='同步已回滚：'+x.message;el('message').className='error'}});el('refresh').onclick=()=>load();el('sources').onchange=detail;load();
</script></body></html>"""


class AcceptanceServer(ThreadingHTTPServer):
    db_path: Path
    csrf_token: str


class Handler(BaseHTTPRequestHandler):
    server: AcceptanceServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 16_384:
            raise ValueError("Request is too large")
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("JSON object required")
        return value

    def _authorized(self) -> bool:
        return secrets.compare_digest(
            self.headers.get("X-Mini-GL-CSRF", ""), self.server.csrf_token
        )

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            raw = PAGE.replace("__TOKEN__", json.dumps(self.server.csrf_token)).encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(raw)
            return
        if not self._authorized():
            self._json({"message": "Unauthorized request"}, HTTPStatus.FORBIDDEN)
            return
        try:
            with SQLiteStore(self.server.db_path) as store:
                if path == "/api/sources":
                    self._json(store.status())
                elif path.startswith("/api/source/"):
                    source_id = path.removeprefix("/api/source/")
                    status = store.status(source_id)[0]
                    self._json({"status": status, "files": store.file_status(source_id), "events": store.latest_events(source_id)})
                else:
                    self._json({"message": "Not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._json({"message": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:
        if not self._authorized():
            self._json({"message": "Unauthorized request"}, HTTPStatus.FORBIDDEN)
            return
        try:
            body = self._body()
            with SQLiteStore(self.server.db_path) as store:
                service = IngestionService(store)
                if self.path == "/api/register":
                    source = service.register(Path(str(body["root"])))
                    self._json({"source_id": source.source_id})
                elif self.path == "/api/sync":
                    self._json(service.sync(str(body["source_id"])))
                else:
                    self._json({"message": "Not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._json({"message": str(exc)}, HTTPStatus.BAD_REQUEST)


def make_server(db_path: Path, host: str = "127.0.0.1", port: int = 8765) -> AcceptanceServer:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("The acceptance console may only bind to loopback")
    server = AcceptanceServer((host, port), Handler)
    server.db_path = db_path
    server.csrf_token = secrets.token_urlsafe(32)
    return server


def serve(db_path: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    with make_server(db_path, host, port) as server:
        print(f"mini_GL acceptance console: http://{host}:{server.server_port}")
        server.serve_forever()
