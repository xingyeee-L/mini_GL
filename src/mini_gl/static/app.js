"use strict";

const token = document.querySelector('meta[name="mini-gl-token"]').content;
const byId = (id) => document.getElementById(id);
let sources = [];
let details = new Map();
let schedules = new Map();
let currentFiles = [];

async function api(path, options = {}) {
  options.headers = {...(options.headers || {}), "X-Mini-GL-CSRF": token};
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || "操作失败");
  return data;
}

function showToast(message, error = false) {
  const toast = byId("toast");
  toast.textContent = message;
  toast.className = `toast show${error ? " error" : ""}`;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => { toast.className = "toast"; }, 2600);
}

const titles = {home: "首页", search: "搜索", ask: "智能问答", library: "知识库", console: "控制台"};

function switchView(name) {
  if (!titles[name]) name = "home";
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.dataset.view === name));
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.viewTarget === name));
  byId("view-title").textContent = titles[name];
  document.querySelector(".sidebar").classList.remove("open");
  history.replaceState(null, "", `#${name}`);
  window.scrollTo({top: 0, behavior: "smooth"});
}

function switchConsole(name) {
  document.querySelectorAll("[data-console]").forEach((panel) => panel.classList.toggle("active", panel.dataset.console === name));
  document.querySelectorAll("[data-console-target]").forEach((button) => button.classList.toggle("active", button.dataset.consoleTarget === name));
}

document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-view-target]");
  if (target) {
    switchView(target.dataset.viewTarget);
    if (target.dataset.consoleTab) switchConsole(target.dataset.consoleTab);
  }
  const consoleTarget = event.target.closest("[data-console-target]");
  if (consoleTarget) switchConsole(consoleTarget.dataset.consoleTarget);
});

byId("mobile-menu").onclick = () => document.querySelector(".sidebar").classList.toggle("open");

function sourceKind(source) {
  return source.source_type === "chat_export" ? "聊天记录" : "本地文件夹";
}

function sourceName(source) {
  const parts = source.root_path.replaceAll("\\", "/").split("/").filter(Boolean);
  return parts.at(-1) || source.root_path;
}

function optionFor(source) {
  const option = document.createElement("option");
  option.value = source.source_id;
  option.textContent = `${sourceKind(source)} · ${sourceName(source)}`;
  return option;
}

function fillSourceSelect(select, previous) {
  select.replaceChildren(...sources.map(optionFor));
  if (sources.some((source) => source.source_id === previous)) select.value = previous;
}

function counts(events) {
  const output = {created: 0, updated: 0, unchanged: 0, deleted: 0};
  events.forEach((event) => { if (event.kind in output) output[event.kind] += 1; });
  return output;
}

function makeSourceRow(source, detail) {
  const row = document.createElement("div");
  row.className = "source-row";
  const icon = document.createElement("span");
  icon.className = "source-icon";
  icon.textContent = sourceKind(source) === "聊天记录" ? "聊" : "文";
  const text = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = sourceName(source);
  const meta = document.createElement("small");
  meta.textContent = `${sourceKind(source)} · ${detail.files.length} 个文件 · ${detail.index.lexical_chunks} 个关键词片段`;
  text.append(title, meta);
  const state = document.createElement("span");
  state.className = `source-state${source.paused ? " paused" : ""}`;
  state.textContent = source.paused ? "已暂停" : "正常";
  row.append(icon, text, state);
  return row;
}

function makeLibraryCard(source, detail) {
  const card = document.createElement("article");
  card.className = "library-card";
  const icon = document.createElement("div");
  icon.className = "source-icon";
  icon.textContent = sourceKind(source) === "聊天记录" ? "聊" : "文";
  const title = document.createElement("h2");
  title.textContent = sourceName(source);
  title.title = source.root_path;
  const path = document.createElement("p");
  path.textContent = source.root_path;
  const footer = document.createElement("footer");
  const stats = document.createElement("span");
  stats.textContent = `${detail.files.length} 文件 · ${detail.index.vector_chunks} 向量片段`;
  const state = document.createElement("span");
  state.className = source.paused ? "paused" : "";
  state.textContent = source.paused ? "已暂停" : "● 正常";
  footer.append(stats, state);
  const actions = document.createElement("div");
  actions.className = "library-actions";
  const inspect = document.createElement("button");
  inspect.className = "secondary";
  inspect.textContent = "查看文件";
  inspect.onclick = () => openSourceFiles(source.source_id);
  const remove = document.createElement("button");
  remove.className = "danger-ghost";
  remove.textContent = "移除数据源";
  remove.onclick = () => revokeSource(source.source_id);
  actions.append(inspect, remove);
  card.append(icon, title, path, footer, actions);
  return card;
}

function openSourceFiles(sourceId) {
  switchView("console");
  switchConsole("sources");
  byId("sources").value = sourceId;
  showSourceDetail();
  byId("file-filter").focus();
}

async function revokeSource(sourceId) {
  const source = sources.find((item) => item.source_id === sourceId);
  if (!source) return;
  const suffix = sourceId.slice(-8);
  const answer = window.prompt(`将撤销“${sourceName(source)}”的授权，并删除 mini_GL 中的快照、索引与同步计划；原文件不会被删除。请输入 ${suffix} 确认：`);
  if (answer !== suffix) return;
  try {
    await api("/api/revoke-source", {method: "POST", body: JSON.stringify({source_id: sourceId, confirmation: suffix})});
    await loadAll(false);
    await loadCommonFolders();
    showToast("数据源已移除，原文件未修改");
  } catch (error) { showToast(error.message, true); }
}

async function loadAll(keep = true) {
  const previous = {
    sources: byId("sources").value,
    search: byId("search-source").value,
    ask: byId("ask-source").value,
  };
  const [runtime, sourceList, scheduleList] = await Promise.all([api("/api/runtime"), api("/api/sources"), api("/api/schedules")]);
  sources = sourceList;
  schedules = new Map(scheduleList.schedules.map((schedule) => [schedule.source_id, schedule]));
  byId("network-state").textContent = runtime.network;
  byId("embedding-state").textContent = runtime.embedding;
  byId("model-state").textContent = runtime.chat_model;
  fillSourceSelect(byId("sources"), keep ? previous.sources : "");
  fillSourceSelect(byId("search-source"), keep ? previous.search : "");
  fillSourceSelect(byId("ask-source"), keep ? previous.ask : "");
  const allSources = document.createElement("option");
  allSources.value = "all";
  allSources.textContent = "全部已授权数据源";
  byId("search-source").prepend(allSources);
  if (!keep || !previous.search) byId("search-source").value = "all";
  const allAnswerSources = allSources.cloneNode(true);
  byId("ask-source").prepend(allAnswerSources);
  if (!keep || !previous.ask) byId("ask-source").value = "all";

  const entries = await Promise.all(sources.map(async (source) => {
    try { return [source.source_id, await api(`/api/source/${encodeURIComponent(source.source_id)}`)]; }
    catch { return [source.source_id, {files: [], events: [], index: {lexical_chunks: 0, vector_chunks: 0}, status: {}}]; }
  }));
  details = new Map(entries);
  renderOverview();
  await showSourceDetail();
}

function renderOverview() {
  let files = 0;
  let lexical = 0;
  let vectors = 0;
  sources.forEach((source) => {
    const detail = details.get(source.source_id);
    files += detail.files.length;
    lexical += detail.index.lexical_chunks;
    vectors += detail.index.vector_chunks;
  });
  byId("home-source-count").textContent = `${sources.length} 个数据源`;
  byId("home-document-count").textContent = `${files} 个文件快照 · ${vectors} 个向量片段`;
  byId("library-source-count").textContent = sources.length;
  byId("library-file-count").textContent = files;
  byId("library-lexical-count").textContent = lexical;
  byId("library-vector-count").textContent = vectors;
  byId("recent-sources").className = "source-list";
  byId("recent-sources").replaceChildren(...sources.slice(0, 4).map((source) => makeSourceRow(source, details.get(source.source_id))));
  byId("library-grid").replaceChildren(...sources.map((source) => makeLibraryCard(source, details.get(source.source_id))));
}

async function showSourceDetail() {
  const id = byId("sources").value;
  if (!id) {
    byId("message").textContent = "暂无数据源。请先添加资料目录或导入中立聊天 JSON。";
    byId("files").replaceChildren();
    return;
  }
  const detail = details.get(id) || await api(`/api/source/${encodeURIComponent(id)}`);
  details.set(id, detail);
  const eventCounts = counts(detail.events);
  Object.entries(eventCounts).forEach(([key, value]) => { byId(key).textContent = value; });
  currentFiles = detail.files;
  renderFileRows();
  const source = sources.find((item) => item.source_id === id);
  byId("pause").textContent = source.paused ? "恢复数据源" : "暂停数据源";
  ["sync", "index", "vector-index"].forEach((key) => { byId(key).disabled = source.paused; });
  const run = detail.status.latest_run;
  byId("message").textContent = `${source.paused ? "已暂停" : "运行中"} · ${run ? `最近同步 ${run.status}` : "尚未同步"} · ${detail.files.length} 个文件 · 原文件不会被修改`;
  const schedule = schedules.get(id) || {frequency: "manual", pause_on_battery: true, auto_lexical: true, auto_vector: true};
  const scheduleForm = byId("source-schedule-form");
  scheduleForm.elements.frequency.value = schedule.frequency;
  scheduleForm.elements.pause_on_battery.checked = schedule.pause_on_battery;
  scheduleForm.elements.auto_indexes.checked = schedule.auto_lexical && schedule.auto_vector;
  byId("schedule-status").textContent = schedule.frequency === "manual"
    ? "当前仅手动同步。"
    : `下次同步：${schedule.next_run_at ? new Date(schedule.next_run_at).toLocaleString() : "等待计算"}${schedule.last_status ? ` · 上次 ${schedule.last_status}` : ""}`;
}

function renderFileRows() {
  const query = byId("file-filter").value.trim().toLocaleLowerCase();
  const eventMap = Object.fromEntries((details.get(byId("sources").value)?.events || []).map((event) => [event.object_id, event.kind]));
  const visible = currentFiles.filter((file) => file.relative_path.toLocaleLowerCase().includes(query));
  byId("files").replaceChildren(...visible.map((file) => {
    const row = document.createElement("tr");
    const normalized = file.relative_path.replaceAll("\\", "/");
    const split = normalized.lastIndexOf("/");
    const folder = split < 0 ? "（根目录）" : normalized.slice(0, split);
    const name = split < 0 ? normalized : normalized.slice(split + 1);
    [folder, name, `${file.size} B`, `${file.content_hash.slice(0, 12)}…`, eventMap[file.object_id] || "—"].forEach((value) => {
      const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
    });
    return row;
  }));
}

byId("file-filter").addEventListener("input", renderFileRows);

function showSyncWarnings(output) {
  const box = byId("sync-warnings");
  if (!output.warnings?.length) { box.hidden = true; box.replaceChildren(); return; }
  const title = document.createElement("strong");
  title.textContent = `${output.skipped} 个文件或目录因安全边界被跳过，其他文件已正常同步：`;
  const list = document.createElement("ul");
  const reasons = {unsupported_text_encoding: "编码不受支持", maximum_recursion_depth: "超过递归深度上限", maximum_file_size: "超过 10 MiB 单文件上限", link_or_reparse_point: "符号链接或 Windows 重解析点，未跟随", pdf_parse_rejected: "PDF 不完整、损坏或不符合安全规范", docx_parse_rejected: "DOCX 损坏或不符合安全规范", office_parse_rejected: "Office 文件类型或包结构不符合安全规范", parser_safety_rejection: "内容格式不符合安全解析规范"};
  output.warnings.forEach((warning) => { const item = document.createElement("li"); const size = warning.size == null ? "" : ` · ${(warning.size / 1024 / 1024).toFixed(1)} MiB`; item.textContent = `${warning.relative_path} · ${reasons[warning.reason] || warning.reason}${size}`; list.append(item); });
  box.replaceChildren(title, list);
  box.hidden = false;
}

function createResultCard(result) {
  const card = document.createElement("article");
  card.className = "result-card";
  const content = document.createElement("div");
  const title = document.createElement("h3");
  title.textContent = result.title;
  const type = document.createElement("span");
  type.textContent = result.file_type || "资料";
  title.append(type);
  const snippet = document.createElement("p");
  snippet.textContent = result.snippet;
  const meta = document.createElement("div");
  meta.className = "result-meta";
  meta.textContent = result.source_uri || "已授权来源";
  const score = document.createElement("span");
  score.className = "score";
  score.textContent = `相关度 ${Number(result.rerank_score ?? result.score).toFixed(3)}`;
  meta.append(score);
  content.append(title, snippet, meta);
  const actions = document.createElement("div");
  actions.className = "result-actions";
  const previewButton = document.createElement("button");
  previewButton.textContent = "查看来源";
  previewButton.onclick = () => preview(result.source_id, result.document_id);
  const revealButton = document.createElement("button");
  revealButton.textContent = "文件夹";
  revealButton.onclick = () => api("/api/reveal", {method: "POST", body: JSON.stringify({source_id: result.source_id, document_id: result.document_id})}).catch((error) => showToast(error.message, true));
  actions.append(previewButton, revealButton);
  card.append(content, actions);
  return card;
}

async function runSearch(query, sourceId, mode, fileType = "") {
  if (!sourceId) throw new Error("请先选择数据源");
  const params = new URLSearchParams({q: query, source_id: sourceId});
  if (fileType) params.set("file_type", fileType);
  byId("search-status").textContent = "正在本机检索…";
  const started = performance.now();
  const output = await api(`${mode === "hybrid" ? "/api/hybrid-search" : "/api/search"}?${params}`);
  const elapsed = output.elapsed_ms ?? (performance.now() - started).toFixed(1);
  byId("search-status").textContent = `找到 ${output.results.length} 条结果 · ${elapsed} ms`;
  byId("results").className = output.results.length ? "results" : "results empty-state";
  byId("results").replaceChildren(...(output.results.length ? output.results.map(createResultCard) : [emptyMessage("没有找到相关资料", "可以换一种说法，或检查所选数据源是否已建立索引。")]));
}

function emptyMessage(titleText, description) {
  const wrap = document.createElement("div");
  const title = document.createElement("strong"); title.textContent = titleText;
  const text = document.createElement("p"); text.textContent = description;
  wrap.append(title, text); return wrap;
}

byId("search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try { await runSearch(String(form.get("query")), String(form.get("source_id")), String(form.get("mode")), String(form.get("file_type"))); }
  catch (error) { byId("search-status").textContent = error.message; showToast(error.message, true); }
});

byId("home-search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const query = String(form.get("query"));
  const intent = String(form.get("intent"));
  switchView(intent);
  if (intent === "search") {
    byId("search-form").elements.query.value = query;
    await runSearch(query, byId("search-source").value, "lexical").catch((error) => showToast(error.message, true));
  } else {
    byId("ask-form").elements.question.value = query;
    byId("ask-form").requestSubmit();
  }
});

document.querySelectorAll("[data-suggestion]").forEach((button) => {
  button.onclick = () => { byId("home-search-form").elements.query.value = button.dataset.suggestion; byId("home-search-form").elements.intent.value = "ask"; };
});

function citationCard(citation, sourceId, index) {
  const card = document.createElement("article");
  card.className = "citation";
  const label = document.createElement("span"); label.className = "citation-index"; label.textContent = `来源 ${index + 1}`;
  const title = document.createElement("strong"); title.textContent = citation.title;
  const meta = document.createElement("p"); meta.textContent = `片段 ${citation.chunk_id.slice(0, 12)}… · 字符 ${citation.start_offset ?? 0}–${citation.end_offset ?? "末尾"}`;
  const citationSource = citation.source_id || sourceId;
  const button = document.createElement("button"); button.textContent = "展开来源"; button.onclick = () => preview(citationSource, citation.document_id);
  card.append(label, title, meta, button); return card;
}

let currentQaSessionId = null;
let currentQaTurns = [];

function renderQaTurns() {
  const wrap = byId("answer-wrap");
  const empty = byId("conversation-empty");
  wrap.hidden = currentQaTurns.length === 0;
  empty.hidden = currentQaTurns.length !== 0;
  byId("turn-list").replaceChildren(...currentQaTurns.map((turn) => {
    const item = document.createElement("article"); item.className = "qa-turn";
    const question = document.createElement("div"); question.className = "question-bubble"; question.textContent = turn.question;
    const assistant = document.createElement("div"); assistant.className = "assistant-answer";
    const orb = document.createElement("span"); orb.className = "assistant-orb small"; orb.textContent = "✦";
    const body = document.createElement("div");
    const answer = document.createElement("div"); answer.className = `answer${turn.insufficient_evidence ? " insufficient" : ""}`; answer.textContent = turn.answer;
    const meta = document.createElement("div"); meta.className = "answer-meta";
    meta.replaceChildren(...[`模型 ${turn.model || "未调用"}`, `检索 ${turn.retrieval_ms} ms`, `生成 ${turn.generation_ms} ms`, `Token ${turn.prompt_tokens ?? "—"} + ${turn.completion_tokens ?? "—"}`].map((value) => { const span = document.createElement("span"); span.textContent = value; return span; }));
    body.append(answer, meta); assistant.append(orb, body); item.append(question, assistant); return item;
  }));
  if (currentQaTurns.length) wrap.scrollTop = wrap.scrollHeight;
}

function renderQaCitations(turn) {
  const citations = turn?.citations || [];
  const sourceId = turn?.source_scope || "all";
  byId("citations").className = citations.length ? "citations" : "citations empty-evidence";
  if (!citations.length) { byId("citations").textContent = "没有可展示的支持来源。"; return; }
  byId("citations").replaceChildren(...citations.map((citation, index) => citationCard(citation, sourceId, index)));
}

async function loadQaSession(sessionId) {
  const output = await api(`/api/qa-session/${encodeURIComponent(sessionId)}`);
  currentQaSessionId = output.session_id;
  currentQaTurns = output.turns;
  renderQaTurns();
  renderQaCitations(currentQaTurns.at(-1));
  await loadQaSessions();
}

async function deleteQaSession(sessionId) {
  const suffix = sessionId.slice(-8);
  const answer = window.prompt(`这只会删除本地问答历史，不影响原始资料。请输入 ${suffix} 确认：`);
  if (answer !== suffix) return;
  await api("/api/delete-qa-session", {method: "POST", body: JSON.stringify({session_id: sessionId, confirmation: suffix})});
  if (currentQaSessionId === sessionId) resetQaSession();
  await loadQaSessions();
  showToast("该会话已从本地历史中删除");
}

async function loadQaSessions() {
  const output = await api("/api/qa-sessions?limit=50");
  const container = byId("qa-sessions");
  if (!output.sessions.length) { const empty = document.createElement("p"); empty.className = "muted"; empty.textContent = "还没有本地会话。"; container.replaceChildren(empty); return; }
  container.replaceChildren(...output.sessions.map((session) => {
    const row = document.createElement("div"); row.className = `qa-session${session.session_id === currentQaSessionId ? " active" : ""}`;
    const open = document.createElement("button"); open.className = "qa-session-main";
    const title = document.createElement("strong"); title.textContent = session.title;
    const detail = document.createElement("small"); detail.textContent = `${session.turn_count} 轮 · ${new Date(session.updated_at).toLocaleString()}`;
    open.append(title, detail); open.onclick = () => loadQaSession(session.session_id).catch((error) => showToast(error.message, true));
    const remove = document.createElement("button"); remove.className = "qa-session-delete"; remove.title = "删除本地会话"; remove.textContent = "删除"; remove.onclick = () => deleteQaSession(session.session_id).catch((error) => showToast(error.message, true));
    row.append(open, remove); return row;
  }));
}

function resetQaSession() {
  currentQaSessionId = null;
  currentQaTurns = [];
  renderQaTurns();
  byId("citations").className = "citations empty-evidence";
  byId("citations").textContent = "回答后，相关来源会显示在这里。";
  byId("ask-status").textContent = "本地 Qwen · 每个事实必须通过来源校验";
}

byId("new-qa-session").onclick = () => { resetQaSession(); loadQaSessions().catch((error) => showToast(error.message, true)); };

byId("ask-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const question = String(form.get("question"));
  const sourceId = String(form.get("source_id"));
  const status = byId("ask-status");
  try {
    if (!sourceId) throw new Error("请先选择数据源");
    status.className = "inline-status";
    status.textContent = "正在本机检索、生成并核对每一句来源…";
    byId("citations").className = "citations empty-evidence";
    byId("citations").textContent = "正在寻找可靠来源…";
    const output = await api("/api/ask", {method: "POST", body: JSON.stringify({source_id: sourceId, query: question, file_type: form.get("file_type") || null, session_id: currentQaSessionId})});
    currentQaSessionId = output.session_id;
    currentQaTurns.push({...output, question, source_scope: sourceId});
    renderQaTurns();
    renderQaCitations(currentQaTurns.at(-1));
    status.textContent = output.insufficient_evidence ? "现有资料不足，系统已安全停止。" : "回答已通过引用与证据检查。";
    event.target.reset();
    fillSourceSelect(byId("ask-source"), sourceId);
    await loadQaSessions();
  } catch (error) {
    status.textContent = `本地问答暂不可用：${error.message}`;
    status.className = "inline-status error";
  }
});

async function preview(sourceId, documentId) {
  const output = await api("/api/source-preview", {method: "POST", body: JSON.stringify({source_id: sourceId, document_id: documentId})});
  byId("preview-title").textContent = output.title;
  const fields = [["类型", output.source_type], ["原始位置", output.source_uri], ["会话", output.conversation_id || "—"], ["时间范围", [output.timestamp_start, output.timestamp_end].filter(Boolean).join(" → ") || "—"], ["参与者", (output.participants || []).join("、") || "—"], ["访问范围", output.access_scope]];
  byId("preview-meta").replaceChildren(...fields.map(([key, value]) => { const box = document.createElement("div"); const title = document.createElement("strong"); title.textContent = key; const text = document.createElement("span"); text.textContent = value; box.append(title, text); return box; }));
  byId("preview-content").textContent = output.content;
  byId("source-preview").showModal();
}

byId("preview-close").onclick = () => byId("source-preview").close();
byId("sources").onchange = showSourceDetail;
byId("refresh").onclick = () => loadAll();

byId("register").addEventListener("submit", async (event) => {
  event.preventDefault();
  try { const form = new FormData(event.target); await api("/api/register", {method: "POST", body: JSON.stringify({root: form.get("root"), authorized: form.get("authorized") === "on"})}); await loadAll(false); showToast("常用文档格式已授权，可以开始只读同步"); }
  catch (error) { showToast(error.message, true); }
});

async function loadCommonFolders() {
  const output = await api("/api/common-folders");
  const byKey = new Map(output.folders.map((folder) => [folder.key, folder]));
  document.querySelectorAll('#common-folders input[name="folders"]').forEach((input) => {
    const folder = byKey.get(input.value);
    const label = input.closest("label");
    input.disabled = !folder?.available;
    label.classList.toggle("unavailable", !folder?.available);
    label.title = folder ? `${folder.path}${folder.registered ? " · 已注册" : ""}` : "不可用";
    label.querySelector(".registered-note")?.remove();
    if (folder?.registered) { const note = document.createElement("small"); note.className = "registered-note"; note.textContent = "已注册"; label.append(note); }
  });
}

byId("common-folders-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = byId("common-folders-status");
  try {
    const form = new FormData(event.target);
    const folders = form.getAll("folders").map(String);
    const autoIndexes = form.get("auto_indexes") === "on";
    const output = await api("/api/register-common-folders", {method: "POST", body: JSON.stringify({folders, frequency: form.get("frequency"), authorized: form.get("authorized") === "on", pause_on_battery: form.get("pause_on_battery") === "on", auto_lexical: autoIndexes, auto_vector: autoIndexes})});
    status.textContent = `已注册 ${output.registered.length} 个独立数据源；注册过程没有扫描正文。`;
    await loadAll(false);
    await loadCommonFolders();
  } catch (error) { status.textContent = `注册失败：${error.message}`; }
});

byId("source-schedule-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const sourceId = byId("sources").value;
  if (!sourceId) return;
  const form = new FormData(event.target);
  const autoIndexes = form.get("auto_indexes") === "on";
  try {
    const output = await api("/api/source-schedule", {method: "POST", body: JSON.stringify({source_id: sourceId, frequency: form.get("frequency"), pause_on_battery: form.get("pause_on_battery") === "on", auto_lexical: autoIndexes, auto_vector: autoIndexes})});
    schedules.set(sourceId, output);
    await showSourceDetail();
    showToast("自动同步计划已保存");
  } catch (error) { showToast(error.message, true); }
});

byId("choose-root").addEventListener("click", async () => {
  try {
    const output = await api("/api/pick-directory", {method: "POST", body: "{}"});
    if (output.selected) {
      byId("register-root").value = output.path;
      showToast("文件夹已选择；确认授权后再注册");
    }
  } catch (error) { showToast(`无法打开文件夹选择器：${error.message}`, true); }
});

byId("chat-import").addEventListener("submit", async (event) => {
  event.preventDefault(); const status = byId("chat-status");
  try { const form = new FormData(event.target); const output = await api("/api/chat-import", {method: "POST", body: JSON.stringify({path: form.get("path"), authorized: form.get("authorized") === "on"})}); status.textContent = `导入成功：${output.documents} 个会话片段 · 新增 ${output.created} · 更新 ${output.updated}`; await loadAll(false); }
  catch (error) { status.textContent = `导入失败：${error.message}`; status.className = "inline-status error"; }
});

async function sourceAction(path, message) {
  const id = byId("sources").value;
  if (!id) throw new Error("请先选择数据源");
  byId("message").textContent = message;
  const output = await api(path, {method: "POST", body: JSON.stringify({source_id: id})});
  await loadAll(); return output;
}

byId("sync").onclick = () => sourceAction("/api/sync", "正在安全扫描并同步…").then((output) => { showSyncWarnings(output); showToast(output.skipped ? `同步完成，隔离 ${output.skipped} 个文件` : "同步完成"); }).catch((error) => { byId("message").textContent = `同步已回滚：${error.message}`; });
byId("index").onclick = () => sourceAction("/api/index", "正在重建关键词索引…").then(() => showToast("关键词索引完成")).catch((error) => showToast(error.message, true));
byId("vector-index").onclick = () => sourceAction("/api/vector-index", "正在离线构建 BGE 向量索引…").then(() => showToast("BGE 向量索引完成")).catch((error) => showToast(error.message, true));
byId("pause").onclick = async () => { try { const id = byId("sources").value; const source = sources.find((item) => item.source_id === id); await api("/api/source-pause", {method: "POST", body: JSON.stringify({source_id: id, paused: !source.paused})}); await loadAll(); showToast(source.paused ? "数据源已恢复" : "数据源已暂停"); } catch (error) { showToast(error.message, true); } };
byId("delete-derived").onclick = async () => { const id = byId("sources").value; if (!id) return; const suffix = id.slice(-8); const answer = window.prompt(`只删除应用生成的数据，不删除原文件。请输入 ${suffix} 确认：`); if (answer !== suffix) return; try { await api("/api/delete-derived", {method: "POST", body: JSON.stringify({source_id: id, confirmation: suffix})}); await loadAll(); showToast("派生数据已删除，原文件未修改"); } catch (error) { showToast(error.message, true); } };

function diagnosticItem(label, value, healthy = true) {
  const item = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = `${healthy ? "✓" : "!"} ${label}`;
  const detail = document.createElement("span");
  detail.textContent = value;
  item.append(title, detail);
  return item;
}

async function diagnose() {
  const container = byId("diagnostic-results");
  container.textContent = "正在检查本地运行环境…";
  try {
    const output = await api("/api/diagnostics");
    const ollama = output.ollama;
    const embedding = output.embedding;
    const formats = output.document_formats;
    container.replaceChildren(
      diagnosticItem("Python", output.python),
      diagnosticItem("SQLite", `${output.sqlite} · ${output.database_integrity}`, output.database_integrity === "ok"),
      diagnosticItem("常用文件解析", formats.available ? `Office/文本内置 · PDF ${formats.pdf}` : "PDF 依赖缺失", formats.available),
      diagnosticItem("本地模型服务", ollama.reachable ? "Ollama 已连接" : "Ollama 未运行", ollama.reachable),
      diagnosticItem("Qwen 模型", ollama.model_available ? "已安装" : "未检测到固定模型", ollama.model_available),
      diagnosticItem("数据规模", `${output.documents} 文档 · ${output.vector_chunks} 向量片段`),
      diagnosticItem("数据库", `${Math.ceil(output.database_size / 1024)} KiB`)
    );
    byId("bge-model-status").textContent = embedding.available ? "● 本地模型目录可用" : "! 未找到本地模型目录";
    byId("qwen-model-status").textContent = ollama.model_available ? "● Ollama 与固定模型可用" : (ollama.reachable ? "! Ollama 已启动，但固定模型缺失" : "! Ollama 服务未运行");
    byId("model-next-step").textContent = output.ready
      ? "模型环境已就绪，可以同步资料并建立索引。"
      : (!ollama.reachable ? "下一步：启动 Ollama，然后重新诊断。" : (!ollama.model_available ? "下一步：安装固定版本的 Qwen 模型。" : "下一步：确认 BGE 模型目录完整。"));
  } catch (error) { container.textContent = `诊断失败：${error.message}`; }
}

byId("diagnose").onclick = diagnose;
byId("diagnose-models").onclick = diagnose;

async function loadManagedBackups() {
  const output = await api("/api/backups");
  const container = byId("backup-list");
  if (!output.backups.length) { const empty = document.createElement("p"); empty.className = "muted"; empty.textContent = "还没有应用托管备份。"; container.replaceChildren(empty); return; }
  container.replaceChildren(...output.backups.map((backup) => {
    const item = document.createElement("div"); item.className = "backup-item";
    const text = document.createElement("div");
    const name = document.createElement("strong"); name.textContent = backup.name;
    const detail = document.createElement("small"); detail.textContent = `${Math.ceil(backup.size / 1024)} KiB · ${new Date(backup.modified_at).toLocaleString()}`;
    text.append(name, detail);
    const choose = document.createElement("button"); choose.className = "secondary"; choose.textContent = "用于恢复"; choose.onclick = () => { byId("restore-form").elements.backup.value = backup.path; };
    item.append(text, choose); return item;
  }));
}

byId("managed-backup").onclick = async () => {
  const status = byId("maintenance-status");
  try { const output = await api("/api/managed-backup", {method: "POST", body: "{}"}); status.className = "inline-status"; status.textContent = `托管备份完成：${output.path} · ${output.integrity}`; await loadManagedBackups(); }
  catch (error) { status.textContent = `备份失败：${error.message}`; status.className = "inline-status error"; }
};

byId("backup-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const status = byId("maintenance-status");
  try { const destination = new FormData(event.target).get("destination"); const output = await api("/api/backup", {method: "POST", body: JSON.stringify({destination})}); status.textContent = `备份完成：${output.path} · ${output.integrity} · SHA-256 ${output.sha256.slice(0, 12)}…`; }
  catch (error) { status.textContent = `备份失败：${error.message}`; status.className = "inline-status error"; }
});
byId("restore-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const status = byId("maintenance-status"); const form = new FormData(event.target);
  try { const output = await api("/api/restore", {method: "POST", body: JSON.stringify({backup: form.get("backup"), destination: form.get("destination"), confirmation: form.get("confirmed") === "on" ? "RESTORE" : ""})}); status.textContent = `恢复副本已创建：${output.path} · 当前运行数据库未替换`; }
  catch (error) { status.textContent = `恢复失败：${error.message}`; status.className = "inline-status error"; }
});

const commandDialog = byId("command-dialog");
byId("command-open").onclick = () => { commandDialog.showModal(); byId("command-input").focus(); };
document.addEventListener("keydown", (event) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); commandDialog.showModal(); byId("command-input").focus(); } });
document.querySelectorAll("[data-command-view]").forEach((button) => { button.onclick = () => { commandDialog.close(); switchView(button.dataset.commandView); }; });
byId("command-input").addEventListener("keydown", (event) => { if (event.key === "Enter" && event.target.value.trim()) { event.preventDefault(); const query = event.target.value.trim(); commandDialog.close(); switchView("search"); byId("search-form").elements.query.value = query; runSearch(query, byId("search-source").value, "lexical").catch((error) => showToast(error.message, true)); } });

switchView(location.hash.slice(1) || "home");
loadAll().catch((error) => showToast(`无法读取本地状态：${error.message}`, true));
loadQaSessions().catch((error) => showToast(`无法读取本地会话：${error.message}`, true));
loadManagedBackups().catch((error) => showToast(`无法读取本地备份：${error.message}`, true));
loadCommonFolders().catch((error) => showToast(`无法读取常用目录状态：${error.message}`, true));
diagnose();
