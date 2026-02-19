const API = 'http://localhost:8000';
let sessionId = null;
let msgCount  = 0;
let selFiles  = [];
let busy      = false;

// ── Init ────────────────────────────────────────────────
window.addEventListener('load', () => {
  checkHealth();
  loadFiles();
  setInterval(checkHealth, 30000);

  const inp = document.getElementById('msg-inp');
  inp.addEventListener('input', () => {
    inp.style.height = 'auto';
    inp.style.height = Math.min(inp.scrollHeight, 130) + 'px';
  });
  inp.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
});

// ── Panel switching ─────────────────────────────────────
function showPanel(name, btn) {
  document.getElementById('chat-panel').classList.toggle('hide', name !== 'chat');
  document.getElementById('admin-panel').classList.toggle('hide', name !== 'admin');
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('on'));
  btn.classList.add('on');
}

// ── Health check ────────────────────────────────────────
async function checkHealth() {
  try {
    const d = await (await fetch(`${API}/health`)).json();
    const dot = document.getElementById('dot');
    const stxt = document.getElementById('status-text');
    const llm = d.llm || {};

    if (llm.ollama === 'online' && llm.model_available) {
      dot.className = 'dot on';
      stxt.textContent = llm.model || 'online';
    } else if (llm.ollama === 'online') {
      dot.className = 'dot';
      stxt.style.color = 'var(--amber)';
      stxt.textContent = 'model missing';
    } else {
      dot.className = 'dot err';
      stxt.textContent = 'Ollama offline';
    }

    document.getElementById('sys-model').textContent  = llm.model || '—';
    document.getElementById('sys-ollama').textContent = llm.ollama || '—';

    const db = d.db || {};
    const total = Object.values(db).reduce((a,b)=>a+b, 0);
    document.getElementById('sys-chunks').textContent = total;
    document.getElementById('s-docs').textContent = document.getElementById('file-list').querySelectorAll('.file-card').length;

    const icons = {timetable:'📅', policy:'📋', notice:'📢', general:'📄'};
    const colView = document.getElementById('col-view');
    if (total === 0) {
      colView.innerHTML = '<div style="font-size:12px;color:var(--muted2)">No docs indexed yet</div>';
    } else {
      colView.innerHTML = Object.entries(db)
        .filter(([,v]) => v > 0)
        .map(([k,v]) => `<div class="col-row"><span class="col-k">${icons[k]||'📄'} ${k}</span><span class="col-v">${v}</span></div>`)
        .join('') || '<div style="font-size:12px;color:var(--muted2)">Empty</div>';
    }
  } catch {
    document.getElementById('dot').className = 'dot err';
    document.getElementById('status-text').textContent = 'Backend offline';
    document.getElementById('col-view').innerHTML = '<div style="font-size:12px;color:var(--red)">Backend not running</div>';
  }
}

// ── Chat ────────────────────────────────────────────────
async function send() {
  const inp = document.getElementById('msg-inp');
  const txt = inp.value.trim();
  if (!txt || busy) return;

  document.getElementById('welcome')?.remove();
  busy = true;
  document.getElementById('send').disabled = true;
  inp.value = '';
  inp.style.height = 'auto';

  addMsg('user', txt);
  const typ = addTyping();

  try {
    const r = await fetch(`${API}/chat`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ message: txt, session_id: sessionId }),
      signal: AbortSignal.timeout(90000),
    });
    typ.remove();

    if (r.ok) {
      const d = await r.json();
      sessionId = d.session_id;
      addMsg('ai', d.answer, d.sources, d.ms);
      document.getElementById('q-hits').textContent = d.hits;
      document.getElementById('q-ms').textContent   = d.ms + 'ms';
      document.getElementById('q-src').textContent  = (d.sources||[]).join(', ') || '—';
      document.getElementById('hit-info').textContent = `${d.hits} chunk(s) retrieved`;
      setTimeout(() => document.getElementById('hit-info').textContent = '', 4000);
    } else {
      const e = await r.json().catch(()=>({}));
      addMsg('ai', `⚠️ Error: ${e.detail || 'Server error'}`, [], 0);
    }
  } catch(e) {
    typ.remove();
    if (e.name === 'TimeoutError')
      addMsg('ai', '⚠️ Timed out — Ollama may be slow. Try again.', [], 0);
    else
      addDemo(txt);  // offline demo
  }

  busy = false;
  document.getElementById('send').disabled = false;
  msgCount++;
  document.getElementById('s-msgs').textContent = msgCount;
  scrollDown();
}

function addMsg(role, text, sources, ms) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  const t = new Date().toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit'});
  const srcs = (sources && sources.length && role==='ai')
    ? sources.map(s=>`<span class="src">📄 ${s}</span>`).join('') : '';
  const msText = ms ? `<span class="msg-time">${t} · ${ms}ms</span>` : `<span class="msg-time">${t}</span>`;
  div.innerHTML = `
    <div class="av ${role}">${role==='ai'?'🎓':'👤'}</div>
    <div class="msg-body">
      <div class="msg-who ${role}">${role==='ai'?'EduVerse AI':'You'}</div>
      <div class="bubble">${role==='ai'?fmt(text):esc(text)}</div>
      <div class="msg-meta">${msText}${srcs}</div>
    </div>`;
  document.getElementById('messages').appendChild(div);
  scrollDown();
}

function addTyping() {
  const div = document.createElement('div');
  div.className = 'msg ai';
  div.innerHTML = `<div class="av ai">🎓</div>
    <div class="msg-body">
      <div class="msg-who ai">EduVerse AI</div>
      <div class="typing"><div class="td"></div><div class="td"></div><div class="td"></div></div>
    </div>`;
  document.getElementById('messages').appendChild(div);
  scrollDown();
  return div;
}

function qa(text) {
  const cp = document.getElementById('chat-panel');
  if (cp.classList.contains('hide'))
    showPanel('chat', document.querySelector('.tab:first-child'));
  document.getElementById('msg-inp').value = text;
  send();
}

/**
 * prefill(text, placeholder)
 * No placeholder → query complete, send immediately.
 * With placeholder → prefill input, focus, wait for user to add details.
 */
function prefill(text, placeholder) {
  const cp = document.getElementById('chat-panel');
  if (cp.classList.contains('hide'))
    showPanel('chat', document.querySelector('.tab:first-child'));

  // Highlight clicked sidebar item
  document.querySelectorAll('.sb-item').forEach(el => el.classList.remove('on'));
  if (event && event.currentTarget) event.currentTarget.classList.add('on');

  const inp = document.getElementById('msg-inp');

  if (!placeholder) {
    // Complete query — send right away
    inp.value = text;
    inp.style.height = 'auto';
    send();
    return;
  }

  // Needs completion — prefill and wait for user input
  inp.value = text;
  inp.placeholder = placeholder;
  inp.style.height = 'auto';
  inp.focus();

  // Cursor to end so user types right after prefilled text
  const len = inp.value.length;
  inp.setSelectionRange(len, len);

  // Restore placeholder when user leaves without typing
  inp.addEventListener('blur', function restore() {
    if (!inp.value.trim()) {
      inp.placeholder = 'Ask anything about timetables, attendance, policies...';
    }
    inp.removeEventListener('blur', restore);
  }, { once: true });
}

// ── Demo responses (when backend is offline) ────────────
function addDemo(q) {
  const lq = q.toLowerCase();
  let ans = '';
  if (lq.includes('anshu') || lq.includes('23500')) {
    ans = `**Dr. Anshu Vashisth (ID: 23500) — Weekly Timetable**

| Day | Time | Course | Section | Room |
|-----|------|--------|---------|------|
| Monday | 11-12 AM | CSE320 | K24FD | 27-310 |
| Monday | 02-03 PM | CSE589 | KD078 | 30-505 |
| Monday | 03-04 PM | CSE320 | K24GR | 26-606 |
| Tuesday | 11-12 AM | CSE320 | K24GR | 26-606 |
| Wednesday | 11-12 AM | CSE320 | K24FD | 27-310 |
| Friday | 11-12 AM | CSE320 | K24FD | 27-310 |
| Friday | 02-03 PM | CSE320 | K24GR | 26-606 |

**Special classes (PHD002):** Apr 11, Apr 25, May 9 — 04-05 PM, Room 30-505

*(Demo mode — connect backend for live answers)*`;
  } else if (lq.includes('manik') || lq.includes('23538')) {
    ans = `**Dr. Manik (ID: 23538) — Weekly Timetable**

| Day | Time | Course | Section | Room |
|-----|------|--------|---------|------|
| Monday | 10-11 AM | CSE589 | KD010 | 27-205 |
| Monday | 11-12 AM | CSE320 | K24PU | 26-109 |
| Monday | 01-02 PM | REL001 | KRL01 | Academic-1 |
| Monday | 03-04 PM | REL001 | KRL01 | Academic-1 |
| Tuesday | 11-12 AM | CSE320 | K24RZ | 26-506 |
| Tuesday | 12-01 PM | CSE320 | K24PU | 26-109 |
| Wednesday | 02-03 PM | REL001 | KRL01 | Academic-1 |
| Thursday | 02-03 PM | CSE320 | K24RZ | 26-506 |
| Thursday | 03-04 PM | CSE587 | KD614 | 27-205 |
| Friday | 10-11 AM | CSE320 | K24RZ | 26-506 |
| Friday | 11-12 AM | CSE320 | K24PU | 26-109 |

*(Demo mode — connect backend for live answers)*`;
  } else if (lq.includes('minimum') || lq.includes('75') || lq.includes('80') || lq.includes('attendance')) {
    ans = `**LPU Minimum Attendance Requirements**

- Students must attend **80% or more** in aggregate across all registered courses
- A relaxation of **5%** is given for medical/genuine reasons (effective minimum = 75%)
- **Minimum 75% per individual course** required to earn attendance marks

**Marks awarded (full-time only):**

| Attendance % | Marks |
|-------------|-------|
| 90% or more | 5 |
| 85% – 90% | 4 |
| 80% – 85% | 3 |
| 75% – 80% | 2 |
| Below 75% | 0 |

*(Source: Academic Rules, Section I — Attendance Requirements)*`;
  } else if (lq.includes('65') || lq.includes('detain')) {
    ans = `**Rule: Attendance Below 65%**

If a student's aggregate attendance falls **below 65%**, they will be:
- **Fully detained** in the term
- Awarded **F grades** in ALL courses
- **Not allowed** to appear in End Term Examination (ETE)
- **Condonation does NOT apply** — 65% is an absolute floor

*Source: Academic Rules, Point 6*`;
  } else if (lq.includes('condon')) {
    ans = `**Attendance Condonation Rules**

Shortage up to **10%** may be condoned based on previous terms:

| Previous Term Attendance | Max Condonation |
|--------------------------|----------------|
| 90% or more | 10% |
| 85% – 90% | 8% |
| 80% – 85% | 6% |
| 75% – 80% | 4% |

- Only applies if current attendance ≥ **65%**
- For continuing students: average of last two terms used
- After condonation, if still < 75% → partial detention

*Source: Academic Rules, Points 3–8*`;
  } else if (lq.includes('late')) {
    ans = `**Late Registration Attendance Policy**

**Freshmen (new admission):**
- Attendance counted from start of classes **OR** last date of admission — whichever is **later**
- All days before registration are marked **Absent**

**Continuing students:**
- Attendance counted from **1st day of start of classes**

**Backlog courses:**
- Attendance counted from **date of backlog registration**

*Source: Attendance Marking Policy for Late Registration*`;
  } else {
    ans = `I can answer questions about the uploaded documents. Currently indexed:

- 📅 **Timetables** — Dr. Anshu Vashisth (ID:23500), Dr. Manik (ID:23538)
- 📋 **Policies** — Academic Rules, Attendance Policy for Late Registration

Try: *"Show Dr. Manik's Monday schedule"* or *"What is the minimum attendance?"*

*(Backend is offline — showing demo responses. Run \`uvicorn main:app --reload --port 8000\`)*`;
  }
  addMsg('ai', ans, ['Demo Mode'], 0);
}

// ── Upload ───────────────────────────────────────────────
function onDragOver(e)  { e.preventDefault(); document.getElementById('drop-zone').classList.add('drag'); }
function onDragLeave()  { document.getElementById('drop-zone').classList.remove('drag'); }
function onDrop(e)      { e.preventDefault(); onDragLeave(); selFiles=Array.from(e.dataTransfer.files); updateDZ(); }
function onFileSelect(e){ selFiles=Array.from(e.target.files); updateDZ(); }

function updateDZ() {
  const btn = document.getElementById('upload-btn');
  const ti  = document.getElementById('dz-title');
  const sub = document.getElementById('dz-sub');
  if (selFiles.length) {
    ti.textContent  = `${selFiles.length} file(s) selected`;
    sub.textContent = selFiles.map(f=>f.name).join(', ').slice(0,80);
    btn.disabled = false;
  } else {
    ti.textContent  = 'Drop files here or click to browse';
    sub.textContent = 'Faculty timetables, academic rules, notices, circulars';
    btn.disabled = true;
  }
}

async function doUpload() {
  if (!selFiles.length) return;
  const btn  = document.getElementById('upload-btn');
  const prog = document.getElementById('prog');
  const fill = document.getElementById('pfill');
  const ptxt = document.getElementById('ptext');
  const type = document.getElementById('doc-type').value;

  btn.disabled = true;
  prog.style.display = 'block';
  let done = 0;

  for (let i = 0; i < selFiles.length; i++) {
    const f = selFiles[i];
    fill.style.width = Math.round((i / selFiles.length) * 85) + '%';
    ptxt.textContent = `Uploading ${f.name} (${i+1}/${selFiles.length})...`;

    const fd = new FormData();
    fd.append('file', f);
    fd.append('doc_type', type);

    try {
      const r  = await fetch(`${API}/upload`, {method:'POST', body:fd});
      const d  = await r.json();
      if (r.ok) { toast(`✅ ${f.name} — ${d.chunks} chunks indexed`, 'ok'); done++; }
      else      { toast(`❌ ${f.name}: ${d.detail||'Failed'}`, 'err'); }
    } catch {
      toast(`❌ ${f.name}: backend offline`, 'err');
    }
  }

  fill.style.width = '100%';
  ptxt.textContent = `Done! ${done}/${selFiles.length} file(s) uploaded.`;
  setTimeout(() => { prog.style.display='none'; fill.style.width='0%'; }, 3000);

  selFiles = [];
  document.getElementById('file-inp').value = '';
  updateDZ();
  btn.disabled = false;
  loadFiles();
  checkHealth();
}

async function loadFiles() {
  try {
    const d = await (await fetch(`${API}/files`)).json();
    renderFiles(d.files || []);
  } catch {
    renderFiles(DEMO_FILES);
  }
}

const DEMO_FILES = [
  {filename:'23500_ashu_sir.xlsx',  doc_type:'timetable', chunks:8,  size_kb:22.4},
  {filename:'23538_manik_sir.xlsx', doc_type:'timetable', chunks:9,  size_kb:23.1},
  {filename:'Academic_rules.pdf',   doc_type:'policy',    chunks:14, size_kb:58.6},
  {filename:'Attendance_Marking_Policy_In_Case_of_Late_Registration.pdf', doc_type:'policy', chunks:8, size_kb:31.2},
];

function renderFiles(files) {
  const el = document.getElementById('file-list');
  document.getElementById('s-docs').textContent = files.length;
  document.getElementById('sb-count').textContent = `${files.length} file(s)`;

  if (!files.length) {
    el.innerHTML = '<div id="no-files">No documents yet. Upload your first file above.</div>';
    return;
  }
  const icn = {pdf:'📄', xlsx:'📊', xls:'📊', csv:'📋', txt:'📝', docx:'📝'};
  el.innerHTML = files.map(f => {
    const ext = f.filename.split('.').pop().toLowerCase();
    return `
    <div class="file-card">
      <div class="file-ico">${icn[ext]||'📄'}</div>
      <div class="file-info">
        <div class="file-name">${f.filename}</div>
        <div class="file-meta">${f.chunks} chunks · ${f.size_kb} KB</div>
      </div>
      <span class="badge badge-${f.doc_type}">${f.doc_type}</span>
      <button class="del-btn" onclick="delFile('${f.filename}','${f.doc_type}')">✕</button>
    </div>`;
  }).join('');
}

async function delFile(name, type) {
  if (!confirm(`Delete "${name}"?`)) return;
  try {
    const r = await fetch(`${API}/files/${encodeURIComponent(name)}`, {method:'DELETE'});
    if (r.ok) { toast(`🗑️ ${name} deleted`, 'ok'); loadFiles(); checkHealth(); }
    else toast('Delete failed', 'err');
  } catch { toast('Backend offline', 'err'); }
}

// ── Helpers ─────────────────────────────────────────────
function scrollDown() {
  const m = document.getElementById('messages');
  setTimeout(() => m.scrollTop = m.scrollHeight, 60);
}
function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function fmt(text) {
  if (!text) return '';
  let t = text;
  // tables
  const rows = t.match(/(\|.+\|[\r\n]*)+/g);
  if (rows) {
    rows.forEach(block => {
      const lines = block.trim().split('\n').filter(l => l.trim() && !/^\|[-| :]+\|$/.test(l.trim()));
      if (!lines.length) return;
      const head = lines[0].split('|').filter((c,i,a)=>i>0&&i<a.length-1).map(c=>`<th>${c.trim()}</th>`).join('');
      const body = lines.slice(1).map(l=>'<tr>'+l.split('|').filter((c,i,a)=>i>0&&i<a.length-1).map(c=>`<td>${c.trim()}</td>`).join('')+'</tr>').join('');
      t = t.replace(block, `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`);
    });
  }
  t = t.replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>');
  t = t.replace(/\*(.*?)\*/g,'<em>$1</em>');
  t = t.replace(/`([^`]+)`/g,'<code>$1</code>');
  t = t.replace(/^###\s(.+)$/gm,'<h4>$1</h4>');
  t = t.replace(/^##\s(.+)$/gm,'<h3>$1</h3>');
  t = t.replace(/^[-*]\s(.+)$/gm,'<li>$1</li>');
  t = t.replace(/(<li>.*<\/li>)/s,'<ul>$1</ul>');
  t = t.replace(/\n/g,'<br>');
  t = t.replace(/(<\/(table|ul|h3|h4)>)<br>/g,'$1');
  return t;
}
function toast(msg, type) {
  const el = document.getElementById('toast');
  el.textContent = msg; el.className = 'show ' + type;
  clearTimeout(el._t);
  el._t = setTimeout(() => el.className = '', 3500);
}