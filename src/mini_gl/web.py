"""Loopback-only visual acceptance console for ingestion."""

# ruff: noqa: E501 -- embedded HTML/CSS/JavaScript remains readable as a browser artifact.

from __future__ import annotations

import json
import os
import secrets
import subprocess
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from mini_gl.generation.context import ContextBuilder
from mini_gl.generation.local_http import LocalOpenAIChatModel
from mini_gl.generation.models import ChatModel
from mini_gl.generation.service import RAGService
from mini_gl.indexing.embeddings import EmbeddingProvider, load_bge_provider
from mini_gl.ingestion import IngestionService
from mini_gl.retrieval.hybrid import HybridSearchService, TokenOverlapReranker
from mini_gl.retrieval.lexical import LexicalSearchService
from mini_gl.retrieval.vector import VectorSearchService
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
.answer{font-size:17px;line-height:1.75;white-space:pre-wrap;background:#f7f8f9;border-left:4px solid #187442;padding:16px;border-radius:8px}.answer.insufficient{border-color:#b26a00;background:#fff8e8}.answer-meta{display:flex;gap:18px;flex-wrap:wrap;margin:12px 0;color:#666}.citations{display:grid;gap:10px}.citation{border:1px solid #e2e5e9;border-radius:9px;padding:12px;display:flex;justify-content:space-between;gap:12px;align-items:center}.badge{font-size:12px;background:#e7f4ec;color:#126536;padding:3px 7px;border-radius:999px}
@media(max-width:650px){.flow{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,1fr)}.table{overflow:auto}}
</style></head><body><header class="top"><h1>🧠 mini_GL · 本地数据与搜索验收台</h1><span class="safe">🛡 只读 · 仅本机</span></header>
<main><section class="panel"><h2>1. 注册测试资料目录</h2><form id="register" class="row"><label>目录绝对路径<input name="root" required placeholder="C:\\path\\to\\test-files"></label><button class="primary">注册</button></form></section>
<section class="panel"><h2>2. 选择数据源并同步</h2><div class="row"><label>数据源<select id="sources"></select></label><button class="primary" id="sync">执行只读同步</button><button id="index">重建关键词索引</button><button id="vector-index">构建 BGE 本地向量索引</button><button id="refresh">刷新状态</button></div><p id="message" class="muted" aria-live="polite">正在读取本地状态…</p></section>
<section class="panel"><div class="flow"><div><b>✓</b>授权目录</div><div><b>✓</b>安全扫描</div><div><b>✓</b>文本解析</div><div><b>✓</b>标准化</div><div><b>✓</b>原子保存</div></div></section>
<section class="panel"><h2>3. 最近一次同步结果</h2><div class="metrics"><div class="metric"><span>新增</span><strong id="created">0</strong></div><div class="metric"><span>更新</span><strong id="updated">0</strong></div><div class="metric"><span>未变化</span><strong id="unchanged">0</strong></div><div class="metric"><span>删除</span><strong id="deleted">0</strong></div></div></section>
<section class="panel"><h2>4. 文件状态（不显示正文）</h2><div class="table"><table><thead><tr><th>相对路径</th><th>大小</th><th>SHA-256</th><th>最近事件</th></tr></thead><tbody id="files"></tbody></table></div></section>
<section class="panel"><h2>5. 本地检索</h2><form id="search-form" class="row"><label>查询<input name="query" required placeholder="例如：项目安全边界"></label><label>检索方式<select name="mode"><option value="lexical">关键词 BM25</option><option value="hybrid">BGE 中文混合检索</option></select></label><label>文件类型<select name="file_type"><option value="">全部</option><option value=".txt">TXT</option><option value=".md">Markdown</option></select></label><button class="primary">搜索</button></form><p id="search-status" class="muted" aria-live="polite">请先构建相应索引。BGE 模型仅从本地 models 目录离线加载。</p><div class="table"><table><thead><tr><th>来源</th><th>相关片段</th><th>分数</th></tr></thead><tbody id="results"></tbody></table></div></section>
<section class="panel"><h2>6. 向本地知识库提问</h2><form id="ask-form" class="row"><label>问题<input name="question" required maxlength="500" placeholder="例如：这个项目如何保护原始文件？"></label><label>限定文件类型<select name="file_type"><option value="">全部</option><option value=".txt">TXT</option><option value=".md">Markdown</option></select></label><button class="primary">让本地 Qwen 回答</button></form><p id="ask-status" class="muted" aria-live="polite">回答只使用已授权资料；每个事实必须通过来源校验。</p><div id="answer-wrap" hidden><div id="answer" class="answer"></div><div id="answer-meta" class="answer-meta"></div><div id="citations" class="citations"></div></div></section>
<section class="panel"><h2>7. 阶段四固定基准</h2><div class="metrics"><div class="metric"><span>问答通过</span><strong>8 / 8</strong></div><div class="metric"><span>回答 P50</span><strong>319 ms</strong></div><div class="metric"><span>回答 P95</span><strong>895 ms</strong></div><div class="metric"><span>越权事实</span><strong>0</strong></div></div><p class="muted">合成中文资料 · 无证据时跳过生成 · 提示注入不会被执行</p></section>
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
el('vector-index').addEventListener('click',async()=>{try{const id=el('sources').value;el('search-status').textContent='正在离线加载 BGE 并建立向量索引…';const out=await api('/api/vector-index',{method:'POST',body:JSON.stringify({source_id:id})});el('search-status').textContent=`BGE 向量索引完成：${out.chunks} 个片段，${out.dimension} 维`}catch(x){el('search-status').textContent=x.message;el('search-status').className='error'}});
el('search-form').addEventListener('submit',async e=>{e.preventDefault();try{const form=new FormData(e.target);const params=new URLSearchParams({q:String(form.get('query')),source_id:el('sources').value});const type=String(form.get('file_type'));if(type)params.set('file_type',type);const mode=String(form.get('mode'));const out=await api((mode==='hybrid'?'/api/hybrid-search?':'/api/search?')+params);el('search-status').textContent=`找到 ${out.results.length} 条结果${out.elapsed_ms===undefined?'':' · '+out.elapsed_ms+' ms'}`;el('results').replaceChildren(...out.results.map(r=>{const tr=document.createElement('tr');const source=document.createElement('td');source.textContent=r.title+' · '+r.file_type+' ';const reveal=document.createElement('button');reveal.textContent='在文件夹中显示';reveal.addEventListener('click',()=>api('/api/reveal',{method:'POST',body:JSON.stringify({source_id:r.source_id,document_id:r.document_id})}));source.append(reveal);for(const value of [r.snippet,r.rerank_score??r.score]){const td=document.createElement('td');td.textContent=String(value);tr.append(td)}tr.prepend(source);return tr}))}catch(x){el('search-status').textContent=x.message;el('search-status').className='error'}});
el('ask-form').addEventListener('submit',async e=>{e.preventDefault();const status=el('ask-status');const wrap=el('answer-wrap');try{const form=new FormData(e.target);status.className='muted';status.textContent='正在本机检索、生成并核对每一句来源…';wrap.hidden=true;const body={source_id:el('sources').value,query:String(form.get('question')),file_type:String(form.get('file_type'))||null};const out=await api('/api/ask',{method:'POST',body:JSON.stringify(body)});wrap.hidden=false;el('answer').textContent=out.answer;el('answer').className='answer'+(out.insufficient_evidence?' insufficient':'');status.textContent=out.insufficient_evidence?'已安全停止：现有资料不足以支持回答。':'回答已通过引用与证据检查。';el('answer-meta').replaceChildren(...[`模型：${out.model||'未调用'}`,`检索：${out.retrieval_ms} ms`,`生成：${out.generation_ms} ms`,`Token：${out.prompt_tokens??'—'} + ${out.completion_tokens??'—'}`].map(v=>{const span=document.createElement('span');span.textContent=v;return span}));el('citations').replaceChildren(...out.citations.map((c,i)=>{const card=document.createElement('div');card.className='citation';const text=document.createElement('div');const badge=document.createElement('span');badge.className='badge';badge.textContent=`来源 ${i+1}`;const title=document.createElement('strong');title.textContent=' '+c.title;const detail=document.createElement('div');detail.className='muted';detail.textContent=`片段 ${c.chunk_id.slice(0,12)}… · 字符 ${c.start_offset??0}–${c.end_offset??'末尾'}`;text.append(badge,title,detail);const reveal=document.createElement('button');reveal.textContent='在文件夹中显示';reveal.onclick=()=>api('/api/reveal',{method:'POST',body:JSON.stringify({source_id:body.source_id,document_id:c.document_id})});card.append(text,reveal);return card}))}catch(x){wrap.hidden=true;status.textContent='本地问答暂不可用：'+x.message;status.className='error'}});
</script></body></html>"""


class AcceptanceServer(ThreadingHTTPServer):
    db_path: Path
    csrf_token: str
    embedding_provider: EmbeddingProvider | None
    chat_model: ChatModel


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

    def _embedding(self) -> EmbeddingProvider:
        if self.server.embedding_provider is None:
            self.server.embedding_provider = load_bge_provider()
        return self.server.embedding_provider

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
                elif path == "/api/hybrid-search":
                    query = parse_qs(urlparse(self.path).query)
                    source_id = query.get("source_id", [""])[0]
                    lexical = LexicalSearchService(store)
                    vector = VectorSearchService(store, self._embedding())
                    results = HybridSearchService(
                        lexical, vector, TokenOverlapReranker()
                    ).search(query.get("q", [""])[0], source_id)
                    self._json({"results": results})
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
                elif self.path == "/api/vector-index":
                    provider = self._embedding()
                    self._json(
                        VectorSearchService(store, provider).rebuild(str(body["source_id"]))
                    )
                elif self.path == "/api/ask":
                    provider = self._embedding()
                    retrieval = HybridSearchService(
                        LexicalSearchService(store),
                        VectorSearchService(store, provider),
                        TokenOverlapReranker(),
                    )
                    answer = RAGService(
                        retrieval, ContextBuilder(store), self.server.chat_model
                    ).answer(
                        str(body.get("query", "")),
                        str(body["source_id"]),
                        file_type=(str(body["file_type"]) if body.get("file_type") else None),
                    )
                    self._json(asdict(answer))
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
    server.embedding_provider = None
    server.chat_model = LocalOpenAIChatModel(
        "http://127.0.0.1:11434/v1/chat/completions",
        "qwen3:4b-instruct-2507-q4_K_M",
    )
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
