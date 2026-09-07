"""Loopback-only visual acceptance console for ingestion."""

# ruff: noqa: E501 -- embedded HTML/CSS/JavaScript remains readable as a browser artifact.

from __future__ import annotations

import json
import os
import secrets
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from mini_gl.ingestion import IngestionService
from mini_gl.retrieval.lexical import LexicalSearchService
from mini_gl.security.paths import PathPolicy
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
</style></head><body><header class="top"><h1>🧠 mini_GL · 本地数据与搜索验收台</h1><span class="safe">🛡 只读 · 仅本机</span></header>
<main><section class="panel"><h2>1. 注册测试资料目录</h2><form id="register" class="row"><label>目录绝对路径<input name="root" required placeholder="C:\\path\\to\\test-files"></label><button class="primary">注册</button></form></section>
<section class="panel"><h2>2. 选择数据源并同步</h2><div class="row"><label>数据源<select id="sources"></select></label><button class="primary" id="sync">执行只读同步</button><button id="index">重建关键词索引</button><button id="refresh">刷新状态</button></div><p id="message" class="muted" aria-live="polite">正在读取本地状态…</p></section>
<section class="panel"><div class="flow"><div><b>✓</b>授权目录</div><div><b>✓</b>安全扫描</div><div><b>✓</b>文本解析</div><div><b>✓</b>标准化</div><div><b>✓</b>原子保存</div></div></section>
<section class="panel"><h2>3. 最近一次同步结果</h2><div class="metrics"><div class="metric"><span>新增</span><strong id="created">0</strong></div><div class="metric"><span>更新</span><strong id="updated">0</strong></div><div class="metric"><span>未变化</span><strong id="unchanged">0</strong></div><div class="metric"><span>删除</span><strong id="deleted">0</strong></div></div></section>
<section class="panel"><h2>4. 文件状态（不显示正文）</h2><div class="table"><table><thead><tr><th>相对路径</th><th>大小</th><th>SHA-256</th><th>最近事件</th></tr></thead><tbody id="files"></tbody></table></div></section>
<section class="panel"><h2>5. 中文关键词检索</h2><form id="search-form" class="row"><label>查询<input name="query" required placeholder="例如：项目安全边界"></label><label>文件类型<select name="file_type"><option value="">全部</option><option value=".txt">TXT</option><option value=".md">Markdown</option></select></label><button class="primary">搜索</button></form><p id="search-status" class="muted" aria-live="polite">请先重建关键词索引。</p><div class="table"><table><thead><tr><th>来源</th><th>相关片段</th><th>分数</th></tr></thead><tbody id="results"></tbody></table></div></section>
<section class="panel"><h2>6. 固定中文基准</h2><div class="metrics"><div class="metric"><span>Recall@5</span><strong>0.66</strong></div><div class="metric"><span>MRR</span><strong>0.56</strong></div><div class="metric"><span>禁止结果率</span><strong>0</strong></div><div class="metric"><span>P95</span><strong>0.49 ms</strong></div></div><p class="muted">15 篇虚构文档 · 25 条查询 · 基准文件保持冻结</p></section>
</main><script>
const token=__TOKEN__;const el=id=>document.getElementById(id);let sources=[];
async function api(path,options={}){options.headers={...(options.headers||{}),'X-Mini-GL-CSRF':token};const r=await fetch(path,options);const data=await r.json();if(!r.ok)throw new Error(data.message||'操作失败');return data}
function counts(events){const out={created:0,updated:0,unchanged:0,deleted:0};for(const e of events)if(e.kind in out)out[e.kind]++;return out}
async function load(keep=true){sources=await api('/api/sources');const old=el('sources').value;el('sources').replaceChildren(...sources.map(s=>{const option=document.createElement('option');option.value=s.source_id;option.textContent=s.root_path;return option}));if(keep&&sources.some(s=>s.source_id===old))el('sources').value=old;await detail()}
async function detail(){const id=el('sources').value;if(!id){el('message').textContent='请先注册一个测试资料目录。';el('files').innerHTML='';return}const d=await api('/api/source/'+encodeURIComponent(id));const c=counts(d.events);for(const k of Object.keys(c))el(k).textContent=c[k];const map=Object.fromEntries(d.events.map(e=>[e.object_id,e.kind]));el('files').innerHTML=d.files.map(f=>`<tr><td>${escapeHtml(f.relative_path)}</td><td>${f.size} B</td><td>${f.content_hash.slice(0,12)}…</td><td>${map[f.object_id]||'—'}</td></tr>`).join('');const run=d.status.latest_run;el('message').textContent=run?`最近状态：${run.status} · 文件 ${d.files.length} 个 · 原文件不会被修改`:'尚未同步'}
function escapeHtml(v){const d=document.createElement('div');d.textContent=v;return d.innerHTML}
el('register').addEventListener('submit',async e=>{e.preventDefault();try{const root=new FormData(e.target).get('root');await api('/api/register',{method:'POST',body:JSON.stringify({root})});await load(false)}catch(x){el('message').textContent=x.message;el('message').className='error'}});
el('sync').addEventListener('click',async()=>{try{el('message').textContent='正在安全扫描并同步…';const id=el('sources').value;await api('/api/sync',{method:'POST',body:JSON.stringify({source_id:id})});await detail()}catch(x){el('message').textContent='同步已回滚：'+x.message;el('message').className='error'}});el('refresh').onclick=()=>load();el('sources').onchange=detail;load();
el('index').addEventListener('click',async()=>{try{const id=el('sources').value;const out=await api('/api/index',{method:'POST',body:JSON.stringify({source_id:id})});el('search-status').textContent=`索引完成：${out.documents} 个文档，${out.chunks} 个片段`}catch(x){el('search-status').textContent=x.message;el('search-status').className='error'}});
el('search-form').addEventListener('submit',async e=>{e.preventDefault();try{const form=new FormData(e.target);const params=new URLSearchParams({q:String(form.get('query')),source_id:el('sources').value});const type=String(form.get('file_type'));if(type)params.set('file_type',type);const out=await api('/api/search?'+params);el('search-status').textContent=`找到 ${out.results.length} 条结果 · ${out.elapsed_ms} ms`;el('results').replaceChildren(...out.results.map(r=>{const tr=document.createElement('tr');const source=document.createElement('td');source.textContent=r.title+' · '+r.file_type+' ';const reveal=document.createElement('button');reveal.textContent='在文件夹中显示';reveal.addEventListener('click',()=>api('/api/reveal',{method:'POST',body:JSON.stringify({source_id:r.source_id,document_id:r.document_id})}));source.append(reveal);for(const value of [r.snippet,r.score]){const td=document.createElement('td');td.textContent=String(value);tr.append(td)}tr.prepend(source);return tr}))}catch(x){el('search-status').textContent=x.message;el('search-status').className='error'}});
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
                elif path == "/api/search":
                    query = parse_qs(urlparse(self.path).query)
                    result = LexicalSearchService(store).search(
                        query.get("q", [""])[0],
                        source_id=query.get("source_id", [None])[0],
                        file_type=query.get("file_type", [None])[0],
                    )
                    self._json(result)
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
                elif self.path == "/api/index":
                    self._json(LexicalSearchService(store).rebuild(str(body["source_id"])))
                elif self.path == "/api/reveal":
                    path = resolve_document_path(
                        store, str(body["source_id"]), str(body["document_id"])
                    )
                    reveal_path(path)
                    self._json({"revealed": True})
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


def resolve_document_path(store: SQLiteStore, source_id: str, document_id: str) -> Path:
    source = store.get_source(source_id)
    row = store.connection.execute(
        "SELECT d.source_uri FROM documents d JOIN file_state f "
        "ON f.source_id=d.source_id AND f.document_id=d.document_id "
        "WHERE d.source_id=? AND d.document_id=?",
        (source_id, document_id),
    ).fetchone()
    if row is None:
        raise ValueError("Document is not part of the current source snapshot")
    policy = PathPolicy(
        (source.root_path,),
        source.allowed_extensions,
        source.max_file_size,
        source.max_depth,
    )
    return policy.authorize(Path(row["source_uri"]))


def reveal_path(path: Path) -> None:
    if os.name != "nt":
        raise RuntimeError("Source reveal is currently supported on Windows only")
    subprocess.Popen(["explorer.exe", f"/select,{path}"], close_fds=True)  # noqa: S603,S607


def serve(db_path: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    with make_server(db_path, host, port) as server:
        print(f"mini_GL acceptance console: http://{host}:{server.server_port}")
        server.serve_forever()
