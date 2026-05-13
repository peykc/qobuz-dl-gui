/**
 * Cloudflare Worker: Qobuz-DL-GUI feedback inbox + KV storage.
 *
 * Env bindings:
 *   FEEDBACK_KV – KV namespace
 *   ADMIN_TOKEN – Bearer token for admin JSON API + log downloads + HTML inbox when PUBLIC_INBOX=false
 *   PUBLIC_INBOX – optional "true" to allow unauthenticated HTML inbox (not recommended)
 *
 * Keys:
 *   fb:<unix>:<uuid>     – feedback record (JSON)
 *   fblog:<uuid>         – plain-text session log attachment
 *
 * Deploy: wrangler deploy (see Cloudflare dashboard for routes).
 */
export default {
  async fetch(request, env) {
    return handleRequest(request, env);
  },
};

const PAGE_STYLE = `
  :root {
    --background: oklch(0.985 0 0);
    --foreground: oklch(0.145 0 0);
    --card: oklch(1 0 0);
    --card-fg: oklch(0.145 0 0);
    --border: oklch(0.922 0 0);
    --muted: oklch(0.97 0 0);
    --muted-fg: oklch(0.556 0 0);
    --accent: oklch(0.205 0 0);
    --ok: oklch(0.55 0.17 145);
    --radius: 0.5rem;
    --font: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --background: oklch(0.145 0 0);
      --foreground: oklch(0.985 0 0);
      --card: oklch(0.205 0 0);
      --card-fg: oklch(0.985 0 0);
      --border: oklch(1 0 0 / 0.1);
      --muted: oklch(0.269 0 0);
      --muted-fg: oklch(0.708 0 0);
      --accent: oklch(0.985 0 0);
      --ok: oklch(0.72 0.17 145);
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    font-family: var(--font);
    background: var(--background);
    color: var(--foreground);
    line-height: 1.5;
  }
  .shell { max-width: 52rem; margin: 0 auto; padding: 2rem 1.25rem 4rem; position: relative; }
  .header { margin-bottom: 1.25rem; }
  .header--bar {
    display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem;
  }
  .header--bar .header-text { min-width: 0; }
  .title { font-size: 1.5rem; font-weight: 600; letter-spacing: -0.025em; margin: 0 0 0.25rem; }
  .subtitle { margin: 0; font-size: 0.875rem; color: var(--muted-fg); }
  .admin-user-btn {
    flex-shrink: 0;
    display: inline-flex; align-items: center; justify-content: center;
    width: 2.5rem; height: 2.5rem;
    padding: 0; border-radius: 50%;
    border: 1px solid var(--border); background: var(--muted); color: var(--foreground);
    cursor: pointer; transition: background 0.15s, border-color 0.15s;
  }
  .admin-user-btn:hover { background: var(--card); border-color: var(--muted-fg); }
  .admin-user-btn svg { width: 1.25rem; height: 1.25rem; }
  .admin-user-btn[aria-expanded="true"] { border-color: var(--accent); background: var(--card); }
  .admin-backdrop {
    display: none; position: fixed; inset: 0; z-index: 40; background: transparent;
  }
  .admin-backdrop.admin-backdrop--open { display: block; }
  .admin-panel {
    display: none; position: fixed; z-index: 50;
    top: 4.75rem; right: max(1.25rem, calc((100vw - 52rem) / 2 + 1.25rem));
    width: min(20rem, calc(100vw - 2rem));
    padding: 1rem 1.125rem;
    background: var(--card); color: var(--card-fg);
    border: 1px solid var(--border); border-radius: var(--radius);
    box-shadow: 0 12px 40px oklch(0 0 0 / 0.35);
    font-size: 0.8125rem;
  }
  .admin-panel.admin-panel--open { display: block; }
  .admin-panel label { display: block; margin-bottom: 0.35rem; color: var(--muted-fg); font-weight: 500; }
  .admin-panel input {
    width: 100%; padding: 0.45rem 0.55rem; margin-bottom: 0.5rem;
    border-radius: calc(var(--radius) - 2px); border: 1px solid var(--border);
    background: var(--background); color: var(--foreground); font: inherit;
  }
  .admin-panel .admin-actions { display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; }
  .admin-panel button[type=button].btn-save {
    padding: 0.45rem 0.85rem; border-radius: calc(var(--radius) - 2px);
    border: 1px solid var(--accent); background: var(--accent); color: var(--background);
    font: inherit; font-weight: 600; cursor: pointer;
  }
  .admin-panel .admin-hint { margin: 0.65rem 0 0; font-size: 0.75rem; color: var(--muted-fg); line-height: 1.4; }
  .tabs { display: flex; gap: 0.5rem; margin-bottom: 1rem; flex-wrap: wrap; }
  .tabs a {
    text-decoration: none; padding: 0.35rem 0.75rem; border-radius: calc(var(--radius) - 2px);
    border: 1px solid var(--border); font-size: 0.8125rem; font-weight: 500; color: var(--foreground);
    background: var(--muted);
  }
  .tabs a.tab--active { background: var(--accent); color: var(--background); border-color: var(--accent); }
  .list { display: flex; flex-direction: column; gap: 0.75rem; }
  .card {
    background: var(--card); color: var(--card-fg);
    border: 1px solid var(--border); border-radius: var(--radius);
    padding: 1rem 1.125rem; box-shadow: 0 1px 2px oklch(0 0 0 / 0.04);
  }
  .card-meta { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; font-size: 0.75rem; color: var(--muted-fg); margin-bottom: 0.625rem; }
  .card-meta strong { color: var(--card-fg); font-weight: 600; }
  .card-meta-spacer { flex: 1 1 auto; min-width: 0.5rem; }
  .card-delete {
    display: none; flex-shrink: 0;
    align-items: center; justify-content: center;
    width: 1.875rem; height: 1.875rem;
    padding: 0; border: none; border-radius: calc(var(--radius) - 2px);
    background: oklch(0.55 0.22 25); color: oklch(0.98 0 0);
    cursor: pointer; transition: filter 0.12s;
  }
  .card-delete:hover { filter: brightness(1.08); }
  .card-delete:active { filter: brightness(0.92); }
  .card-delete svg { width: 0.95rem; height: 0.95rem; display: block; }
  body.admin-authed .card-delete { display: inline-flex; }
  .badge { display: inline-flex; align-items: center; border-radius: calc(var(--radius) - 2px); border: 1px solid var(--border); background: var(--muted); padding: 0.125rem 0.5rem; font-size: 0.75rem; font-weight: 500; }
  .badge.badge--open { border-color: oklch(0.65 0.15 55); background: oklch(0.65 0.15 55 / 0.12); }
  .badge.badge--closed { border-color: oklch(0.55 0.12 145); background: oklch(0.55 0.12 145 / 0.12); color: var(--ok); }
  .msg-wrap { margin: 0; border-radius: calc(var(--radius) - 2px); }
  .msg-wrap--expandable { cursor: pointer; outline: none; }
  .msg-wrap--expandable:focus-visible { box-shadow: 0 0 0 2px oklch(0.65 0.15 230 / 0.5); }
  .msg { margin: 0; font-size: 0.875rem; font-family: ui-monospace, "Cascadia Code", Consolas, monospace; white-space: pre-wrap; word-break: break-word; }
  .msg.msg--clamp {
    display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3;
    overflow: hidden;
  }
  .msg-suffix { color: var(--muted-fg); }
  .msg-modal { display: none; position: fixed; inset: 0; z-index: 100; align-items: center; justify-content: center; padding: 1rem; }
  .msg-modal.msg-modal--open { display: flex; }
  .msg-modal-backdrop { position: absolute; inset: 0; background: oklch(0 0 0 / 0.55); }
  .msg-modal-panel {
    position: relative; z-index: 1; width: min(42rem, 100%); max-height: min(80vh, 36rem);
    display: flex; flex-direction: column;
    background: var(--card); color: var(--card-fg); border: 1px solid var(--border);
    border-radius: var(--radius); box-shadow: 0 20px 60px oklch(0 0 0 / 0.4);
  }
  .msg-modal-head { display: flex; align-items: center; justify-content: space-between; padding: 0.65rem 0.85rem; border-bottom: 1px solid var(--border); font-size: 0.875rem; font-weight: 600; }
  .msg-modal-close {
    border: none; background: transparent; color: var(--muted-fg); cursor: pointer; font-size: 1.25rem; line-height: 1; padding: 0.2rem 0.45rem; border-radius: 4px;
  }
  .msg-modal-close:hover { color: var(--foreground); background: var(--muted); }
  .msg-modal-body { margin: 0; padding: 1rem 1.125rem; overflow: auto; font-size: 0.8125rem; font-family: ui-monospace, "Cascadia Code", Consolas, monospace; white-space: pre-wrap; word-break: break-word; }
  .empty { text-align: center; padding: 2.5rem 1rem; border: 1px dashed var(--border); border-radius: var(--radius); color: var(--muted-fg); font-size: 0.875rem; }
  .dl-row { margin-top: 0.75rem; }
  .dl-btn {
    display: inline-flex; align-items: center; gap: 0.35rem;
    font-size: 0.8125rem; font-weight: 500; padding: 0.35rem 0.65rem;
    border-radius: calc(var(--radius) - 2px); border: 1px solid var(--border);
    background: var(--muted); color: var(--foreground); cursor: pointer; font-family: inherit;
  }
  .dl-btn:disabled { opacity: 0.45; cursor: not-allowed; }
`;

const MAX_MESSAGE_LEN = 2000;
const MAX_LOG_LEN = 120000;
const LOG_PREFIX = "fblog:";

function getCorsOrigin(request) {
  const origin = request.headers.get("Origin") || "";
  return /^http:\/\/(127\.0\.0\.1|localhost)(?::\d+)?$/.test(origin)
    ? origin
    : null;
}

function corsHeaders(origin, ext = {}) {
  if (!origin) return {};
  return {
    "Access-Control-Allow-Origin": origin,
    Vary: "Origin",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    ...ext,
  };
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function checkAdminBearer(request, env) {
  const auth = request.headers.get("Authorization") || "";
  const token = auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
  return Boolean(env.ADMIN_TOKEN && token && token === env.ADMIN_TOKEN);
}

function json(obj, status, origin) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      ...(origin ? corsHeaders(origin) : {}),
    },
  });
}

async function loadAllFeedback(env) {
  const listed = await env.FEEDBACK_KV.list({ prefix: "fb:", limit: 500 });
  const items = [];
  for (const k of listed.keys) {
    const v = await env.FEEDBACK_KV.get(k.name, "json");
    if (v) items.push({ key: k.name, ...v });
  }
  items.sort((a, b) => Number(b.timestamp || 0) - Number(a.timestamp || 0));
  return items;
}

function inboxScript() {
  return `
<script>
(function(){
  var SK='feedback_admin_bearer';
  var TRASH_SVG='<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M9 3v1H4v2h1v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V6h1V4h-5V3H9zm2 2h2v1h-2V5zm-4 3h10v11H7V8zm2 2v7H9v-7h1zm4 0v7h-1v-7h1z"/></svg>';
  var USER_SVG='<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M20 21a8 8 0 1 0-16 0"/><circle cx="12" cy="8" r="4"/></svg>';
  function tok(){ try { return (sessionStorage.getItem(SK)||'').trim(); } catch(e){ return ''; } }
  function setTok(t){ try { sessionStorage.setItem(SK,(t||'').trim()); } catch(e){} }
  function refreshAdminVerified(){
    return new Promise(function(resolve){
      var t=tok();
      if(!t){
        document.body.classList.remove('admin-authed');
        resolve(false);
        return;
      }
      fetch('/api/feedback/admin-verify',{ headers:{ 'Authorization':'Bearer '+t }})
        .then(function(r){
          return r.json().catch(function(){ return {}; }).then(function(j){ return { ok:r.ok&&j&&j.ok===true }; });
        })
        .then(function(x){
          document.body.classList.toggle('admin-authed',x.ok);
          resolve(x.ok);
        })
        .catch(function(){
          document.body.classList.remove('admin-authed');
          resolve(false);
        });
    });
  }
  function closeAdminPanel(){
    var p=document.getElementById('admin-panel');
    var b=document.getElementById('admin-backdrop');
    var btn=document.getElementById('admin-user-btn');
    if(p) p.classList.remove('admin-panel--open');
    if(b) b.classList.remove('admin-backdrop--open');
    if(btn){ btn.setAttribute('aria-expanded','false'); }
  }
  function openAdminPanel(){
    var p=document.getElementById('admin-panel');
    var b=document.getElementById('admin-backdrop');
    var btn=document.getElementById('admin-user-btn');
    if(p) p.classList.add('admin-panel--open');
    if(b) b.classList.add('admin-backdrop--open');
    if(btn){ btn.setAttribute('aria-expanded','true'); }
    if(inp) setTimeout(function(){ inp.focus(); }, 0);
  }
  function toggleAdminPanel(){
    var p=document.getElementById('admin-panel');
    if(p&&p.classList.contains('admin-panel--open')) closeAdminPanel();
    else openAdminPanel();
  }
  var userBtn=document.getElementById('admin-user-btn');
  var backdrop=document.getElementById('admin-backdrop');
  var inp=document.getElementById('admin-token-input');
  var saveBtn=document.getElementById('admin-token-save');
  if(userBtn){
    userBtn.innerHTML=USER_SVG;
    userBtn.addEventListener('click',function(e){ e.stopPropagation(); toggleAdminPanel(); });
  }
  if(backdrop){ backdrop.addEventListener('click',closeAdminPanel); }
  if(inp&&saveBtn){
    inp.value=tok();
    saveBtn.addEventListener('click',function(){
      setTok(inp.value);
      inp.value=tok();
      refreshAdminVerified().then(function(ok){
        if(tok().length>0&&!ok){
          alert('That token is not accepted. Use the same admin bearer as for log downloads.');
        }
        closeAdminPanel();
      });
    });
  }
  refreshAdminVerified();

  function readFullMsg(wrap){
    try { return decodeURIComponent(wrap.getAttribute('data-full-msg')||''); } catch(e){ return ''; }
  }
  function syncMsgClamp(pre,trimmed){
    var measureSuffix=' ... \\u2192';
    if(!trimmed) return false;
    pre.textContent=trimmed;
    if(pre.scrollHeight<=pre.clientHeight+1) return false;
    var lo=0, hi=trimmed.length;
    while(lo<hi){
      var mid=Math.ceil((lo+hi)/2);
      var chunk=trimmed.slice(0,mid).trimEnd()+measureSuffix;
      pre.textContent=chunk;
      if(pre.scrollHeight>pre.clientHeight+1) hi=mid-1; else lo=mid;
    }
    if(lo<1) lo=1;
    var prefix=trimmed.slice(0,lo).trimEnd();
    pre.textContent='';
    pre.appendChild(document.createTextNode(prefix+'...'));
    var suf=document.createElement('span');
    suf.className='msg-suffix';
    suf.textContent=' \\u2192';
    pre.appendChild(suf);
    return true;
  }
  function setupMessages(){
    document.querySelectorAll('.msg-wrap[data-full-msg]').forEach(function(wrap){
      var pre=wrap.querySelector('pre.msg');
      if(!pre) return;
      var full=readFullMsg(wrap);
      var trimmed=full.replace(/^\\s+|\\s+$/g,'');
      if(!trimmed) return;
      pre.classList.add('msg--clamp');
      pre.textContent=trimmed;
      if(syncMsgClamp(pre,trimmed)){
        wrap.classList.add('msg-wrap--expandable');
        wrap.setAttribute('role','button');
        wrap.setAttribute('tabindex','0');
        wrap.setAttribute('aria-label','View full message');
        function openFull(e){
          e.preventDefault(); e.stopPropagation();
          var m=document.getElementById('msg-modal');
          var body=document.getElementById('msg-modal-body');
          if(!m||!body) return;
          body.textContent=readFullMsg(wrap);
          m.classList.add('msg-modal--open');
        }
        wrap.addEventListener('click',openFull);
        wrap.addEventListener('keydown',function(e){
          if(e.key==='Enter'||e.key===' '){ openFull(e); }
        });
      }
    });
  }
  setupMessages();

  var msgModal=document.getElementById('msg-modal');
  var msgModalClose=document.getElementById('msg-modal-close');
  if(msgModal){
    msgModal.querySelector('.msg-modal-backdrop').addEventListener('click',function(){
      msgModal.classList.remove('msg-modal--open');
    });
  }
  if(msgModalClose){
    msgModalClose.addEventListener('click',function(){ msgModal.classList.remove('msg-modal--open'); });
  }
  document.addEventListener('keydown',function(e){
    if(e.key!=='Escape') return;
    if(msgModal&&msgModal.classList.contains('msg-modal--open')){
      msgModal.classList.remove('msg-modal--open');
      return;
    }
    var p=document.getElementById('admin-panel');
    if(p&&p.classList.contains('admin-panel--open')) closeAdminPanel();
  });

  document.querySelectorAll('[data-log-key]').forEach(function(bt){
    bt.addEventListener('click',async function(){
      var key=bt.getAttribute('data-log-key');
      var t=tok();
      if(!t){ openAdminPanel(); if(inp) inp.focus(); return; }
      var r=await fetch('/api/feedback/log?key='+encodeURIComponent(key),{
        headers:{ 'Authorization':'Bearer '+t }
      });
      if(!r.ok){ alert('Download failed ('+r.status+')'); return; }
      var blob=await r.blob();
      var a=document.createElement('a');
      a.href=URL.createObjectURL(blob);
      a.download='feedback-log.txt';
      a.click();
      URL.revokeObjectURL(a.href);
    });
  });

  document.querySelectorAll('.card-delete').forEach(function(bt){
    bt.innerHTML=TRASH_SVG;
    bt.addEventListener('click',async function(e){
      e.preventDefault(); e.stopPropagation();
      var id=bt.getAttribute('data-feedback-id');
      if(!id) return;
      var t=tok();
      if(!t){ openAdminPanel(); if(inp) inp.focus(); return; }
      if(!confirm('Delete this feedback permanently?')) return;
      var r=await fetch('/api/feedback/admin-delete',{
        method:'POST',
        headers:{ 'Content-Type':'application/json','Authorization':'Bearer '+t },
        body: JSON.stringify({ id: id })
      });
      var j=await r.json().catch(function(){ return {}; });
      if(!r.ok||!j.ok){ alert('Delete failed ('+r.status+')'); return; }
      var card=bt.closest('article.card');
      if(card) card.remove();
    });
  });
})();
</script>`;
}

async function renderInboxHtml(env, request) {
  const url = new URL(request.url);
  const filter = (url.searchParams.get("filter") || "open").toLowerCase();
  const f =
    filter === "closed" ? "closed" : filter === "all" ? "all" : "open";

  const items = await loadAllFeedback(env);
  const filtered =
    f === "all"
      ? items
      : items.filter((x) => (f === "open" ? !x.closed : x.closed));

  const tab = (name, label, active) =>
    `<a class="tab${active ? " tab--active" : ""}" href="?filter=${name}">${label}</a>`;

  function renderCard(x) {
   const ts = Number(x.timestamp) || 0;
    const when = new Date(ts * 1000).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
    const version = escapeHtml(x.version ?? "unknown");
    const platform = escapeHtml(x.platform ?? "unknown");
    const msgRaw = String(x.message ?? "");
    const msgEsc = escapeHtml(msgRaw);
    const msgDataAttr = encodeURIComponent(msgRaw);
    const closed = Boolean(x.closed);
    const stLabel = closed ? "Closed" : "Open";
    const stClass = closed ? "badge--closed" : "badge--open";
    const logKeyRaw = x.logKey && String(x.logKey).startsWith(LOG_PREFIX) ? String(x.logKey) : "";
    const logKey = logKeyRaw ? escapeHtml(logKeyRaw) : "";
    const idAttr = escapeHtml(x.key);
    const dl = logKey
      ? `<div class="dl-row"><button type="button" class="dl-btn" data-log-key="${logKey}">Download logs</button></div>`
      : "";
    return `
<article class="card">
  <div class="card-meta">
    <strong>${escapeHtml(when)}</strong>
    <span class="badge ${stClass}">${stLabel}</span>
    <span class="badge">v${version}</span>
    <span class="badge">${platform}</span>
    <span class="card-meta-spacer" aria-hidden="true"></span>
    <button type="button" class="card-delete" data-feedback-id="${idAttr}" title="Delete permanently" aria-label="Delete feedback permanently"></button>
  </div>
  <div class="msg-wrap" data-feedback-key="${idAttr}" data-full-msg="${msgDataAttr}">
    <pre class="msg">${msgEsc}</pre>
  </div>
  ${dl}
</article>`;
  }

  const rows =
    filtered.length === 0
      ? `<div class="empty">No ${f === "all" ? "" : f + " "}feedback.</div>`
      : filtered.map(renderCard).join("");

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Feedback · pkcollection</title>
  <style>${PAGE_STYLE}</style>
</head>
<body>
  <div id="admin-backdrop" class="admin-backdrop"></div>
  <div id="admin-panel" class="admin-panel" role="dialog" aria-modal="true" aria-labelledby="admin-panel-title">
    <div id="admin-panel-title" style="font-weight:600;margin-bottom:0.65rem;font-size:0.9375rem">Admin access</div>
    <label for="admin-token-input">Bearer token</label>
    <input id="admin-token-input" type="password" autocomplete="off" placeholder="Paste token" />
    <div class="admin-actions">
      <button type="button" class="btn-save" id="admin-token-save">Save</button>
    </div>
    <p class="admin-hint">Stored in this tab only. Must match your admin token: trash and log download work only after a successful save.</p>
  </div>
  <div class="shell">
    <header class="header header--bar">
      <div class="header-text">
        <h1 class="title">Feedback inbox</h1>
        <p class="subtitle">Qobuz-DL-GUI · ${filtered.length} shown (${items.length} total)</p>
      </div>
      <button type="button" class="admin-user-btn" id="admin-user-btn" title="Admin" aria-label="Open admin sign-in" aria-expanded="false" aria-controls="admin-panel"></button>
    </header>
    <nav class="tabs" aria-label="Filter">
      ${tab("open", "Open", f === "open")}
      ${tab("closed", "Closed", f === "closed")}
      ${tab("all", "All", f === "all")}
    </nav>
    <div class="list">${rows}</div>
  </div>
  <div id="msg-modal" class="msg-modal" role="dialog" aria-modal="true" aria-labelledby="msg-modal-title">
    <div class="msg-modal-backdrop"></div>
    <div class="msg-modal-panel">
      <div class="msg-modal-head">
        <span id="msg-modal-title">Full message</span>
        <button type="button" class="msg-modal-close" id="msg-modal-close" aria-label="Close">&times;</button>
      </div>
      <pre class="msg-modal-body" id="msg-modal-body"></pre>
    </div>
  </div>
  ${inboxScript()}
</body>
</html>`;
}

async function handleRequest(request, env) {
  const url = new URL(request.url);
  const allowedOrigin = getCorsOrigin(request);

  if (request.method === "OPTIONS") {
    const pathOk =
      url.pathname === "/api/feedback/close" ||
      url.pathname === "/api/feedback/admin-delete" ||
      url.pathname === "/api/feedback/admin-verify" ||
      url.pathname === "/api/feedback/log" ||
      url.pathname === "/api/feedback" ||
      url.pathname === "/" ||
      url.pathname === "";
    if (!pathOk) return new Response(null, { status: 403 });
    if (!allowedOrigin) return new Response(null, { status: 403 });
    return new Response(null, { status: 204, headers: corsHeaders(allowedOrigin) });
  }

  /* Admin: verify bearer (same check as log download / delete) */
  if (request.method === "GET" && url.pathname === "/api/feedback/admin-verify") {
    if (!checkAdminBearer(request, env)) {
      return new Response(JSON.stringify({ ok: false }), {
        status: 401,
        headers: { "Content-Type": "application/json; charset=utf-8" },
      });
    }
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  }

  /* Admin: download log file */
  if (request.method === "GET" && url.pathname === "/api/feedback/log") {
    if (!checkAdminBearer(request, env)) {
      return new Response("Unauthorized", { status: 401 });
    }
    const key = (url.searchParams.get("key") || "").trim();
    if (!key.startsWith(LOG_PREFIX)) {
      return new Response("Invalid key", { status: 400 });
    }
    const text = await env.FEEDBACK_KV.get(key);
    if (text === null) return new Response("Not found", { status: 404 });
    const safe = key.replace(/[^a-zA-Z0-9:-]/g, "").slice(0, 48);
    return new Response(text, {
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Content-Disposition": `attachment; filename="qobuz-dl-feedback-${safe}.txt"`,
      },
    });
  }

  if (request.method === "POST" && url.pathname === "/api/feedback/admin-delete") {
    if (!checkAdminBearer(request, env)) {
      return new Response(JSON.stringify({ ok: false, error: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json; charset=utf-8" },
      });
    }
    let data;
    try {
      data = await request.json();
    } catch {
      return new Response(JSON.stringify({ ok: false, error: "Invalid JSON" }), {
        status: 400,
        headers: { "Content-Type": "application/json; charset=utf-8" },
      });
    }
    const id = typeof data.id === "string" ? data.id.trim() : "";
    if (!id.startsWith("fb:")) {
      return new Response(JSON.stringify({ ok: false, error: "invalid id" }), {
        status: 400,
        headers: { "Content-Type": "application/json; charset=utf-8" },
      });
    }
    const raw = await env.FEEDBACK_KV.get(id);
    if (raw) {
      try {
        const rec = JSON.parse(raw);
        const lk = rec.logKey;
        if (typeof lk === "string" && lk.startsWith(LOG_PREFIX)) {
          await env.FEEDBACK_KV.delete(lk);
        }
      } catch {
        /* ignore corrupt */
      }
    }
    await env.FEEDBACK_KV.delete(id);
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  }

  if (request.method === "GET" && url.pathname === "/api/feedback") {
    const needAuth = env.PUBLIC_INBOX === "false" || env.PUBLIC_INBOX === false;
    if (needAuth && !checkAdminBearer(request, env)) {
      return new Response("Unauthorized", { status: 401 });
    }
    const items = await loadAllFeedback(env);
    return new Response(JSON.stringify({ ok: true, count: items.length, items }), {
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  }

  if (request.method === "GET" && (url.pathname === "/" || url.pathname === "")) {
    const needAuth = env.PUBLIC_INBOX === "false" || env.PUBLIC_INBOX === false;
    if (needAuth && !checkAdminBearer(request, env)) {
      return new Response("Unauthorized", { status: 401 });
    }
    const html = await renderInboxHtml(env, request);
    return new Response(html, {
      headers: { "Content-Type": "text/html; charset=utf-8" },
    });
  }

  /* User: mark closed (must match clientToken stored on submit) */
  if (request.method === "POST" && url.pathname === "/api/feedback/close") {
    if (!allowedOrigin) {
      return new Response("Forbidden origin", { status: 403 });
    }
    let data;
    try {
      data = await request.json();
    } catch {
      return json({ ok: false, error: "Invalid JSON" }, 400, allowedOrigin);
    }
    const id = typeof data.id === "string" ? data.id.trim() : "";
    const clientToken =
      typeof data.clientToken === "string" ? data.clientToken.trim() : "";
    if (!id.startsWith("fb:")) {
      return json({ ok: false, error: "invalid id" }, 400, allowedOrigin);
    }
    if (!clientToken || clientToken.length < 8) {
      return json({ ok: false, error: "clientToken required" }, 400, allowedOrigin);
    }
    const raw = await env.FEEDBACK_KV.get(id);
    if (!raw) {
      return json({ ok: false, error: "not found" }, 404, allowedOrigin);
    }
    let rec;
    try {
      rec = JSON.parse(raw);
    } catch {
      return json({ ok: false, error: "corrupt record" }, 500, allowedOrigin);
    }
    if (rec.clientToken !== clientToken) {
      return json({ ok: false, error: "forbidden" }, 403, allowedOrigin);
    }
    rec.closed = true;
    rec.closedAt = new Date().toISOString();
    await env.FEEDBACK_KV.put(id, JSON.stringify(rec));
    return json({ ok: true }, 200, allowedOrigin);
  }

  if (request.method !== "POST") {
    return new Response("Not Found", { status: 404 });
  }

  if (!allowedOrigin) {
    return new Response("Forbidden origin", { status: 403 });
  }

  let data;
  try {
    data = await request.json();
  } catch {
    return json({ ok: false, error: "Invalid JSON" }, 400, allowedOrigin);
  }

  const message = typeof data.message === "string" ? data.message.trim() : "";
  if (!message) {
    return json({ ok: false, error: "message is required" }, 400, allowedOrigin);
  }
  if (message.length > MAX_MESSAGE_LEN) {
    return json(
      { ok: false, error: `message too long (max ${MAX_MESSAGE_LEN})` },
      400,
      allowedOrigin,
    );
  }

  const clientToken =
    typeof data.clientToken === "string" ? data.clientToken.trim() : "";
  if (!clientToken || clientToken.length < 8) {
    return json({ ok: false, error: "clientToken is required" }, 400, allowedOrigin);
  }

  let logText = typeof data.logText === "string" ? data.logText : "";
  if (logText.length > MAX_LOG_LEN) {
    logText = logText.slice(logText.length - MAX_LOG_LEN);
  }
  let logKey = null;
  if (logText.trim().length > 0) {
    logKey = `${LOG_PREFIX}${crypto.randomUUID()}`;
    await env.FEEDBACK_KV.put(logKey, logText);
  }

  const payload = {
    message,
    version: String(data.version || "unknown"),
    platform: String(data.platform || "unknown"),
    timestamp: Number.isFinite(Number(data.timestamp))
      ? Number(data.timestamp)
      : Math.floor(Date.now() / 1000),
    receivedAt: new Date().toISOString(),
    clientToken,
    closed: false,
    ip: request.headers.get("CF-Connecting-IP") || "",
    ua: request.headers.get("User-Agent") || "",
    hasLog: Boolean(logKey),
    logKey,
  };

  const key = `fb:${payload.timestamp}:${crypto.randomUUID()}`;
  await env.FEEDBACK_KV.put(key, JSON.stringify(payload));

  console.log("feedback_saved", { key, version: payload.version, hasLog: payload.hasLog });

  return json({ ok: true, id: key }, 200, allowedOrigin);
}
