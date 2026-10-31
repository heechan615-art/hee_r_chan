// ---------- 내 계좌 비중 탭 ----------
// 계좌·종목·매매 기록은 이 브라우저(localStorage)에만 저장. 서버(/api/pf/*)는 종목 찾기·현재가·일정·이슈만 준다.
// 평균단가는 증권사와 같은 이동평균법: 살 때만 다시 계산하고, 팔면 수량만 줄고 평균단가는 그대로(차익은 실현손익).
(function(){
const KEY = "hrc_pf_v1";
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const uid = () => Math.random().toString(36).slice(2, 10);
const today = () => { const d = new Date(); return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); };
const SAFE = ["#0f7f6b","#22a88f","#5cc7b0","#0b5e50","#93dccb","#3a9d8a","#b9ebdf"];
const RISK = ["#e8711a","#f39a45","#c9570f","#f7bd7e","#a8460c","#f5a95f","#fbd5aa"];
const ACC = ["#2563eb","#7c3aed","#db2777","#0891b2","#b8862b","#475569"];   // 계좌 색: 막대그래프와 계좌 칸 띠가 같은 색

let S = load();
let Q = {quotes: {}, fx: null, time: null};
const INFO = {}, ISS = {}, OPEN = {};
let started = false, timer = null, showAllIss = {};
// 일정·이슈 칸 접기 상태(브라우저에 기억)
let FOLD = (() => { try{ return JSON.parse(localStorage.getItem("hrc_pf_fold") || "{}"); }catch(e){ return {}; } })();
const foldBtn = k => `<button type="button" class="pf-fold" data-act="fold" data-k="${k}" aria-expanded="${!FOLD[k]}">${FOLD[k] ? "펴기 ▾" : "접기 ▴"}</button>`;

function load(){
  try{ const s = JSON.parse(localStorage.getItem(KEY) || "null"); if(s && Array.isArray(s.accounts)) return s; }catch(e){}
  return {accounts: [{id: uid(), broker: "", name: "A계좌", items: []}]};
}
function save(){ S.updated = new Date().toISOString(); try{ localStorage.setItem(KEY, JSON.stringify(S)); }catch(e){} }
// 되돌리기: 바꾸기 직전 상태를 최근 30개까지 보관(새로고침해도 남게 localStorage)
const UKEY = "hrc_pf_undo_v1";
let UNDO = (() => { try{ return JSON.parse(localStorage.getItem(UKEY) || "[]"); }catch(e){ return []; } })();
function snap(label){ UNDO.push({label, s: JSON.stringify(S)}); if(UNDO.length > 30) UNDO.shift();
  try{ localStorage.setItem(UKEY, JSON.stringify(UNDO)); }catch(e){} }
function undo(){
  const u = UNDO.pop(); if(!u) return;
  try{ localStorage.setItem(UKEY, JSON.stringify(UNDO)); }catch(e){}
  S = JSON.parse(u.s); save(); render(); toast(`'${u.label}'을(를) 되돌렸어요`, false);
}
let toastT = null;
function toast(msg, canUndo = true){
  let t = document.getElementById("pf-toast");
  if(!t){ t = document.createElement("div"); t.id = "pf-toast"; document.body.appendChild(t); }
  t.innerHTML = `<span>${esc(msg)}</span>${canUndo && UNDO.length ? `<button type="button">↶ 되돌리기</button>` : ""}`;
  const b = t.querySelector("button"); if(b) b.onclick = () => { t.classList.remove("on"); undo(); };
  t.classList.add("on"); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("on"), 7000);
}

// ---------- 계산 ----------
// 달러 종목은 매매마다 그날 환율(t.fx)을 기억 → 원화 기준 매입원가(avgK)도 같은 이동평균으로 쌓아 환차손익을 따로 계산
function pos(it){                       // 매매 기록 → 보유 수량·평균단가·실현손익 (원래 통화 + 원화)
  let qty = 0, avg = 0, avgK = 0, realized = 0, realK = 0;
  const usd = it.cur === "USD";
  for(const t of it.trades || []){
    const fx = usd ? (t.fx || Q.fx || 0) : 1;
    if(t.t === "b"){ avg = (avg * qty + t.p * t.q) / (qty + t.q); avgK = (avgK * qty + t.p * fx * t.q) / (qty + t.q); qty += t.q; }
    else { const n = Math.min(t.q, qty); realized += (t.p - avg) * n; realK += (t.p * fx - avgK) * n; qty -= n; if(qty < 1e-9){ qty = 0; } }
  }
  return {qty, avg, avgK, avgFx: usd && avg ? avgK / avg : null, cost: qty * avg, costK: qty * avgK, realized, realK: usd ? realK : realized};
}
function price(it){ if(it.kind === "cash") return 1; const q = Q.quotes[it.sym]; return q && q.price ? q.price : null; }
function stat(it){
  const p = pos(it), px = price(it), cur = it.cur || "KRW", usd = cur === "USD";
  const val = px == null ? p.cost : p.qty * px, fx = usd ? Q.fx : 1;
  const valK = fx ? val * fx : p.costK;
  const div = INFO[it.sym] && INFO[it.sym].dividend ? p.qty * (INFO[it.sym].dividend.annual || 0) : 0;
  const stockK = usd ? (fx ? (val - p.cost) * fx : 0) : val - p.cost;     // 주가가 움직여 생긴 손익(지금 환율로)
  const fxK = usd && fx ? p.qty * (p.avg * fx - p.avgK) : 0;               // 환율이 움직여 생긴 손익
  return {...p, px, val, pnl: val - p.cost, ret: p.cost ? (val / p.cost - 1) * 100 : 0,
          valK, pnlK: valK - p.costK, retK: p.costK ? (valK / p.costK - 1) * 100 : 0, stockK, fxK,
          divK: div * (fx || 0)};
}
function agg(items){
  const o = {cost: 0, val: 0, real: 0, div: 0, safe: 0, risk: 0,
             krw: {cost: 0, val: 0, real: 0}, usd: {cost: 0, val: 0, real: 0, costK: 0, valK: 0, realK: 0, stockK: 0, fxK: 0}};
  for(const it of items){ const s = stat(it);
    o.cost += s.costK; o.val += s.valK; o.real += s.realK; o.div += s.divK; o[it.cls] += s.valK;
    if(it.cur === "USD"){ const u = o.usd; u.cost += s.cost; u.val += s.val; u.real += s.realized; u.costK += s.costK; u.valK += s.valK; u.realK += s.realK; u.stockK += s.stockK; u.fxK += s.fxK; }
    else { o.krw.cost += s.costK; o.krw.val += s.valK; o.krw.real += s.realK; } }
  o.pnl = o.val - o.cost; o.ret = o.cost ? (o.val / o.cost - 1) * 100 : 0;
  o.hasUsd = items.some(i => i.cur === "USD"); o.hasKrw = items.some(i => i.cur !== "USD");
  return o;
}
const allItems = () => S.accounts.flatMap(a => a.items);

// ---------- 표시 ----------
const won = n => n == null || isNaN(n) ? "-" : Math.round(n).toLocaleString("ko-KR") + "원";
const man = n => { if(n == null || isNaN(n)) return "-"; const a = Math.abs(n);
  return a >= 1e8 ? (n / 1e8).toFixed(a >= 1e10 ? 0 : 2).replace(/\.?0+$/, "") + "억원" : a >= 1e4 ? Math.round(n / 1e4).toLocaleString("ko-KR") + "만원" : won(n); };
const money = (n, cur) => n == null || isNaN(n) ? "-" : cur === "USD" ? "$" + n.toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2}) : won(n);
const qtyf = n => (+n).toLocaleString("ko-KR", {maximumFractionDigits: 6});
const sgn = n => n > 0 ? "pos" : n < 0 ? "neg" : "";
const pctf = n => (n > 0 ? "+" : "") + n.toFixed(1) + "%";
const signed = (n, f) => (n > 0 ? "+" : n < 0 ? "−" : "") + f(Math.abs(n));
const WD = ["일","월","화","수","목","금","토"];
function md(s){ const d = new Date(s + (s.length === 7 ? "-01" : "") + "T00:00:00"); return s.length === 7 ? (d.getMonth() + 1) + "월 중" : (d.getMonth() + 1) + "/" + d.getDate() + " (" + WD[d.getDay()] + ")"; }
function dday(s){ if(s.length === 7) return ""; const n = Math.round((new Date(s + "T00:00:00") - new Date(today() + "T00:00:00")) / 864e5); return n === 0 ? "오늘" : n > 0 ? "D-" + n : ""; }
function acName(a){ return [a.broker, a.name].filter(Boolean).join(" ") || "계좌"; }

// ---------- 원형 그래프 (SVG) — 한 번에 하나: 안전·위험 / 종목별 ----------
function arc(cx, cy, r0, r1, a0, a1){
  if(a1 - a0 >= Math.PI * 2 - 1e-6) a1 = a0 + Math.PI * 2 - 1e-4;
  const p = (r, a) => [cx + r * Math.sin(a), cy - r * Math.cos(a)], lg = a1 - a0 > Math.PI ? 1 : 0;
  const [x0, y0] = p(r1, a0), [x1, y1] = p(r1, a1), [x2, y2] = p(r0, a1), [x3, y3] = p(r0, a0);
  return `M${x0},${y0}A${r1},${r1} 0 ${lg} 1 ${x1},${y1}L${x2},${y2}A${r0},${r0} 0 ${lg} 0 ${x3},${y3}Z`;
}
function ring(segs, r0, r1){
  const tot = segs.reduce((s, x) => s + x.v, 0); let a = 0, out = "";
  for(const x of segs){ if(x.v <= 0) continue; const b = a + x.v / tot * Math.PI * 2;
    out += `<path d="${arc(90, 90, r0, r1, a, b)}" fill="${x.c}" stroke="#fff" stroke-width="1.5"><title>${esc(x.l)} ${(x.v / tot * 100).toFixed(1)}%</title></path>`; a = b; }
  return out;
}
let VIEW = (() => { try{ return JSON.parse(localStorage.getItem("hrc_pf_view") || "{}"); }catch(e){ return {}; } })();
function chart(items, scope){
  const rows = items.map(it => ({it, v: stat(it).valK})).filter(x => x.v > 0);
  const tot = rows.reduce((s, x) => s + x.v, 0);
  if(tot <= 0) return "";
  const mode = VIEW[scope] || "a";
  const merge = cls => { const m = new Map(); rows.filter(x => x.it.cls === cls).forEach(x => { const k = x.it.kind === "cash" ? "cash:" + x.it.name : x.it.sym;
      const o = m.get(k); if(o) o.v += x.v; else m.set(k, {n: x.it.name, v: x.v}); }); return [...m.values()].sort((a, b) => b.v - a.v); };
  const ms = merge("safe"), mr = merge("risk");
  const ss = ms.reduce((s, x) => s + x.v, 0), rs = mr.reduce((s, x) => s + x.v, 0);
  const pc = v => Math.round(v / tot * 100) + "%";
  let svg, lg;
  if(mode === "a"){
    svg = ring([{l: "안전자산", v: ss, c: SAFE[0]}, {l: "위험자산", v: rs, c: RISK[0]}], 54, 86)
      + `<text x="90" y="86" text-anchor="middle" font-size="11" font-weight="700" fill="#7b8392">위험자산</text><text x="90" y="106" text-anchor="middle" font-size="22" font-weight="900" fill="${RISK[2]}">${pc(rs)}</text>`;
    lg = `<div class="big"><i style="background:${SAFE[0]}"></i><span>🛡️ 안전자산</span><b>${pc(ss)}</b><small>${man(ss)}</small></div>
          <div class="big"><i style="background:${RISK[0]}"></i><span>🔥 위험자산</span><b>${pc(rs)}</b><small>${man(rs)}</small></div>
          <p class="hint">안전자산: 예금·현금·채권처럼 잘 안 흔들리는 돈 · 위험자산: 주식처럼 오르내림이 큰 돈</p>`;
  } else {
    const outer = [...ms.map((x, i) => ({l: x.n, v: x.v, c: SAFE[(i + 1) % SAFE.length]})), ...mr.map((x, i) => ({l: x.n, v: x.v, c: RISK[(i + 1) % RISK.length]}))];
    svg = ring([{l: "안전자산", v: ss, c: SAFE[0]}, {l: "위험자산", v: rs, c: RISK[0]}], 40, 58) + ring(outer, 61, 88)
      + `<text x="90" y="95" text-anchor="middle" font-size="12.5" font-weight="900" fill="#11151a">${rows.length}종목</text>`;
    const li = (arr, pal) => arr.slice(0, 5).map((x, i) => `<div><i style="background:${pal[(i + 1) % pal.length]}"></i><span>${esc(x.n)}</span><b>${pc(x.v)}</b></div>`).join("")
      + (arr.length > 5 ? `<div class="etc"><span>그 밖 ${arr.length - 5}개</span><b>${pc(arr.slice(5).reduce((s, x) => s + x.v, 0))}</b></div>` : "");
    lg = (ms.length ? `<div class="grp">🛡️ 안전자산 <b>${pc(ss)}</b></div>${li(ms, SAFE)}` : "") + (mr.length ? `<div class="grp">🔥 위험자산 <b>${pc(rs)}</b></div>${li(mr, RISK)}` : "")
      + `<p class="hint">안쪽 원은 안전·위험, 바깥 원은 종목이에요</p>`;
  }
  return `<div class="pf-chart" data-scope="${esc(scope)}">
    <div class="pf-seg"><button type="button" data-act="view" data-v="a" class="${mode === "a" ? "on" : ""}">안전 · 위험</button><button type="button" data-act="view" data-v="b" class="${mode === "b" ? "on" : ""}">종목별</button></div>
    <div class="body"><svg viewBox="0 0 180 180">${svg}</svg><div class="lg ${mode}">${lg}</div></div></div>`;
}

// 달러 자산 한 줄 설명 (+자세히)
function usdLine(g){
  if(!g.hasUsd || !Q.fx) return "";
  const u = g.usd;
  return `<div class="pf-usd">💱 달러 자산 <b>${money(u.val, "USD")}</b> · 원화로 손익 <b class="${sgn(u.valK - u.costK)}">${signed(u.valK - u.costK, man)}</b>
    = 주가로 <b class="${sgn(u.stockK)}">${signed(u.stockK, man)}</b>, 환율로 <b class="${sgn(u.fxK)}">${signed(u.fxK, man)}</b>
    <span class="q" title="달러 종목은 산 날 환율을 기억해요. 그때보다 환율이 내려가면(원화 강세) 같은 주가라도 원화로는 손해가 나요.">?</span></div>`;
}

// ---------- 화면 ----------
function render(){
  const root = $("#pf-root"); if(!root) return;
  const tab = VIEW.tab === "watch" ? "watch" : "acc";
  const tabs = `<div class="pf-tabs"><button type="button" data-act="tab" data-v="acc" class="${tab === "acc" ? "on" : ""}">💼 내 계좌</button><button type="button" data-act="tab" data-v="watch" class="${tab === "watch" ? "on" : ""}">⭐ 관심종목 <small>${watchAll().length || ""}</small></button></div>`;
  if(tab === "watch"){ root.innerHTML = tabs + watchView(); bind(root); return; }
  const items = allItems(), g = agg(items), has = items.length > 0;
  const live = items.filter(i => pos(i).qty > 0).length;
  root.innerHTML = tabs + `
  ${has ? `<div class="pf-panel pf-hero">
    <div class="top"><span class="lbl">내 자산 <small>${S.accounts.length > 1 ? `계좌 ${S.accounts.length}개 합계` : ""} · ${live}종목</small></span>
      ${UNDO.length ? `<button type="button" class="pf-btn sm ghost" data-act="undo" title="마지막 작업: ${esc(UNDO[UNDO.length - 1].label)}">↶ 되돌리기</button>` : ""}</div>
    <div class="amt">${won(g.val)}</div>
    <div class="pnl ${sgn(g.pnl)}">${signed(g.pnl, won)} <span>(${pctf(g.ret)})</span></div>
    <div class="sub">넣은 돈 ${won(g.cost)}${g.div ? ` · 💰 1년 배당 예상 ${man(g.div)}` : ""}${g.real ? ` · 판 종목에서 ${signed(g.real, man)}` : ""}</div>
    ${usdLine(g)}
    ${chart(items, "all")}
    ${S.accounts.length > 1 && g.val > 0 ? accBar(g) : ""}
    <div class="meta">${Q.time ? "현재가 " + new Date(Q.time).toLocaleTimeString("ko-KR", {hour: "2-digit", minute: "2-digit"}) + " 기준, 30초마다 바뀌어요" : "현재가 불러오는 중…"}${g.hasUsd && Q.fx ? ` · 환율 ${won(Q.fx)}` : ""}
      <button type="button" class="lnk" data-act="refresh">↻ 새로고침</button></div>
  </div>
  <div class="pf-two">${upcomingPanel()}${issuePanel()}</div>` : welcome()}
  ${S.accounts.map((a, i) => accPanel(a, i)).join("")}
  <div class="pf-foot">
    <button type="button" class="pf-btn" data-act="addacc">＋ 계좌 추가</button>
    <span class="sp"></span>
    <button type="button" class="lnk" data-act="export">💾 백업 저장</button>
    <button type="button" class="lnk" data-act="import">📂 백업 불러오기</button>
    ${has ? `<button type="button" class="lnk" data-act="reset">모두 지우기</button>` : ""}
    <input type="file" id="pf-file" accept=".json,application/json" style="display:none">
    <p>🔒 입력한 내용은 <b>이 브라우저에만</b> 저장돼요(서버로 안 보내요). 다른 기기에서 보려면 백업을 저장해 불러오세요. 호재·악재는 AI가 기사를 보고 나눈 것이라 판단은 직접 해 주세요. 투자 권유가 아니에요.</p>
  </div>`;
  bind(root);
}

// 계좌(증권사)별 비중 막대
function accBar(g){
  const rows = S.accounts.map((a, i) => ({a, c: ACC[i % ACC.length], v: agg(a.items).val})).filter(x => x.v > 0);
  return `<div class="pf-accbar"><div class="t">계좌별 비중</div>
    <div class="bar">${rows.map(x => { const w = x.v / g.val * 100; return `<div style="width:${w}%;background:${x.c}" title="${esc(acName(x.a))} ${w.toFixed(1)}%">${w >= 12 ? Math.round(w) + "%" : ""}</div>`; }).join("")}</div>
    <div class="lg">${rows.map(x => `<span><i style="background:${x.c}"></i>${esc(acName(x.a))} <b>${(x.v / g.val * 100).toFixed(1)}%</b> <small>${man(x.v)}</small></span>`).join("")}</div></div>`;
}

function welcome(){
  return `<div class="pf-panel pf-welcome"><h3>💼 내 계좌, 한눈에 보기</h3>
    <ol><li><b>계좌 이름</b>을 적어요 <small>예: 키움증권 · ISA</small></li>
      <li><b>＋ 종목 추가</b>를 눌러 가진 종목을 넣어요 <small>"삼성전자", "인텔"처럼 이름만 쳐도 원화·달러를 알아서 맞춰요</small></li>
      <li>끝! <b>안전·위험 비중 그래프, 수익률, 배당·실적 일정, 최근 이슈</b>가 자동으로 나와요</li></ol>
    <button type="button" class="pf-btn ghost" data-act="sample">예시로 먼저 둘러보기</button></div>`;
}

function accPanel(a, i){
  const g = agg(a.items), many = S.accounts.length > 1, fold = FOLD["acc" + a.id], c = ACC[i % ACC.length];
  const sec = cls => {
    const list = a.items.filter(i => i.cls === cls).map(it => ({it, s: stat(it)})).sort((x, y) => (y.s.qty > 0) - (x.s.qty > 0) || y.s.valK - x.s.valK);
    const sum = list.reduce((s, x) => s + x.s.valK, 0), tot = g.safe + g.risk;
    return `<div class="pf-sec ${cls}" data-acc="${a.id}" data-cls="${cls}">
      <h4>${cls === "safe" ? "🛡️ 안전자산" : "🔥 위험자산"} <small>${cls === "safe" ? "예금·현금·채권 등" : "주식·ETF·코인 등"}</small>
        ${tot ? `<span class="sum">${man(sum)} · ${Math.round(sum / tot * 100)}%</span>` : ""}</h4>
      ${list.length ? list.map(x => row(a, x.it, x.s)).join("") : `<p class="none">아직 없어요</p>`}
      <div class="adds"><button type="button" class="pf-btn sm" data-act="additem">＋ 종목 추가</button><button type="button" class="pf-btn sm ghost" data-act="cash">＋ 현금·예금</button></div></div>`;
  };
  return `<div class="pf-panel pf-acc" data-acc="${a.id}" style="--ac:${c};--ac-soft:${c}14">
    <div class="pf-acc-h"><span class="no" title="계좌 ${i + 1}">${i + 1}</span>
      <input class="br" data-f="broker" value="${esc(a.broker)}" placeholder="증권사 (예: 키움증권)" aria-label="증권사">
      <input class="nm" data-f="name" value="${esc(a.name)}" placeholder="계좌 이름 (예: ISA)" aria-label="계좌 이름">
      <span class="tot">${a.items.length && many ? `<b>${man(g.val)}</b> <em class="${sgn(g.pnl)}">${signed(g.pnl, man)} (${pctf(g.ret)})</em>` : ""}</span>
      ${many ? `<button type="button" class="pf-fold" data-act="fold" data-k="acc${a.id}">${fold ? "펴기 ▾" : "접기 ▴"}</button>` : ""}
    </div>
    ${fold ? "" : `${a.items.length && many ? `<div class="pf-acc-sub">넣은 돈 ${won(g.cost)}${g.real ? ` · 판 종목에서 ${signed(g.real, man)}` : ""}</div>${usdLine(g)}${chart(a.items, a.id)}` : ""}
    ${sec("safe")}${sec("risk")}
    ${many ? `<div style="text-align:right;margin-top:8px"><button type="button" class="lnk mute" data-act="delacc">이 계좌 삭제</button></div>` : ""}`}</div>`;
}

// 종목 한 줄(카드): 이름 · 지금 가치 / 수량·평균·현재가 · 수익률 / 버튼
function row(a, it, s){
  const cash = it.kind === "cash", cur = it.cur || "KRW", q = Q.quotes[it.sym];
  const done = !cash && s.qty === 0, op = OPEN[it.id];
  const usdK = cur === "USD" && Q.fx ? ` <small>(${man(s.valK)})</small>` : "";
  return `<div class="pf-item${done ? " done" : ""}${op ? " open" : ""}" data-acc="${a.id}" data-it="${it.id}">
    <div class="l1"><b class="nm" data-act="open">${esc(it.name)}</b>${q && q.chg_pct != null && !done ? `<span class="today ${sgn(q.chg_pct)}">오늘 ${pctf(q.chg_pct)}</span>` : ""}
      <span class="val">${done ? "다 팔았어요" : money(s.val, cur) + usdK}</span></div>
    <div class="l2"><span class="info">${cash ? (cur === "USD" ? "달러 현금" : "현금·예금")
        : done ? `판 종목에서 <b class="${sgn(s.realized)}">${signed(s.realized, v => money(v, cur))}</b>`
        : `${qtyf(s.qty)}주 · 평균 ${money(s.avg, cur)} → 지금 ${s.px == null ? "…" : money(s.px, cur)}`}</span>
      ${cash || done ? "" : `<span class="ret ${sgn(s.ret)}">${pctf(s.ret)} <small>${signed(s.pnl, v => money(v, cur))}</small></span>`}</div>
    <div class="l3">${cash ? `<button type="button" class="pf-btn sm buy" data-act="buy">넣기</button><button type="button" class="pf-btn sm sell" data-act="sell">빼기</button>`
        : `<button type="button" class="pf-btn sm buy" data-act="buy">매수</button>${done ? "" : `<button type="button" class="pf-btn sm sell" data-act="sell">매도</button>`}`}
      <button type="button" class="tog" data-act="open">${op ? "닫기 ▴" : "자세히 ▾"}</button>
      <span class="sp"></span><button type="button" class="del" data-act="delit" title="이 종목 지우기" aria-label="${esc(it.name)} 지우기">✕<span class="t"> 지우기</span></button></div>
    ${op ? detail(a, it, s) : ""}</div>`;
}

function detail(a, it, s){
  const cash = it.kind === "cash", cur = it.cur || "KRW", inf = INFO[it.sym], iss = ISS[it.sym];
  const trades = (it.trades || []).map((t, i) => `<div class="tr"><span>${esc((t.d || "").slice(2).replace(/-/g, "."))} ${t.t === "b" ? (cash ? "넣음" : "매수") : (cash ? "뺌" : "매도")}</span>
      <span>${cash ? money(t.q, cur) : money(t.p, cur) + " × " + qtyf(t.q) + "주"}${cur === "USD" && t.fx && !cash ? ` <small>환율 ${won(t.fx)}</small>` : ""}</span><button type="button" data-act="deltr" data-i="${i}" title="이 기록 지우기">✕</button></div>`).join("");
  const other = it.cls === "safe" ? "위험자산" : "안전자산";
  const ops = `<div class="ops"><button type="button" class="lnk mute" data-act="move">⇄ ${other} 칸으로 옮기기</button>${cash ? `<button type="button" class="lnk mute" data-act="rename">이름 바꾸기</button>` : ""}</div>`;
  if(cash) return `<div class="pf-det"><div class="blk"><h5>🧾 기록</h5>${trades}</div>${ops}</div>`;
  const d = inf && inf.dividend, e = inf && inf.earnings, last = inf && inf.last;
  const lines = [];
  // 배당
  if(!inf) lines.push(`<p class="pf-note">배당·실적 정보를 불러오는 중…</p>`);
  else {
    lines.push(`<div class="blk"><h5>💰 배당</h5>${!d || !d.annual ? `<p>최근 1년 배당이 없어요</p>`
      : `<p>1주에 1년 <b>${money(d.annual, cur)}</b>${d.freq ? ` (${d.freq}번 나눠서)` : ""} → 내 몫 1년 약 <b>${money(s.qty * d.annual, cur)}</b>${cur === "USD" && Q.fx ? ` (${man(s.qty * d.annual * Q.fx)})` : ""}</p>
         ${d.next_ex ? `<p>다음 배당을 받으려면 <b>${md(d.next_ex)}</b> 전날까지 갖고 있어야 해요${d.next_ex_est ? " <small>(작년 기준 예상)</small>" : ""}</p>` : ""}
         ${d.pay ? `<p>돈 들어오는 날 <b>${md(d.pay)}</b></p>` : ""}`}</div>`);
    lines.push(`<div class="blk"><h5>📊 실적</h5>${inf.etf ? `<p>ETF라 실적 발표가 없어요</p>`
      : `<p>다음 발표 ${e && e.next ? `<b>${md(e.next)}</b> ${dday(e.next)}${e.est ? " <small>(예상일)</small>" : ""}` : "아직 날짜 미정"}</p>
         ${last && last.headline ? `<p>지난 ${esc(last.label)}: <b>${esc(last.headline)}</b> <button type="button" class="lnk" data-act="cards">실적 카드 보기 →</button></p>` : ""}`}</div>`);
  }
  // 환율
  if(cur === "USD" && s.qty && Q.fx) lines.push(`<div class="blk"><h5>💱 환율</h5><p>산 날 평균 환율 <b>${won(s.avgFx)}</b> → 지금 <b>${won(Q.fx)}</b></p>
      <p>원화로 손익 <b class="${sgn(s.pnlK)}">${signed(s.pnlK, man)}</b> = 주가로 <b class="${sgn(s.stockK)}">${signed(s.stockK, man)}</b> + 환율로 <b class="${sgn(s.fxK)}">${signed(s.fxK, man)}</b></p></div>`);
  // 일정·이슈
  const evs = [...(inf ? inf.events.filter(x => x.kind !== "배당") : []), ...(iss ? iss.upcoming : [])].sort((x, y) => x.date < y.date ? -1 : 1);
  const news = iss ? (iss.recent.length ? iss.recent.slice(0, 4).map(x => evRow(x, null)).join("")
      : (iss.news || []).slice(0, 4).map(n => `<div class="pf-ev"><div class="bd"><a href="${esc(n.url)}" target="_blank" rel="noopener" class="plain">${esc(n.title)}</a><p>${esc(n.date || "")} · ${esc(n.src || "")}</p></div></div>`).join("")) : "";
  lines.push(`<div class="blk wide"><h5>📅 앞으로 · 📰 최근 소식</h5>${evs.map(x => evRow(x, null)).join("")}${news || (iss ? `<p>최근 30일 소식이 없어요</p>` : `<p class="pf-note">기사 읽는 중…</p>`)}</div>`);
  lines.push(`<div class="blk wide"><h5>🧾 매매 기록 <small>잘못 넣었으면 ✕</small></h5>${trades}</div>`);
  return `<div class="pf-det">${lines.join("")}${ops}</div>`;
}

function evRow(x, name){
  const src = (x.src || []).map(s => `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.by || "출처")} ↗</a>`).join("")
    + (x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener">DART 공시 ↗</a>` : "");
  const dd = x.date ? dday(x.date) : "";
  const title = name && x.title.startsWith(name) ? x.title.slice(name.length).replace(/^[\s,·:]+/, "") || x.title : x.title;
  return `<div class="pf-ev"><div class="dt"><b>${x.date ? esc(md(x.date).replace(/ \(.\)/, "")) : "-"}</b>${dd ? `<small>${dd}</small>` : ""}</div>
    <div class="bd"><span class="pf-tg ${esc(x.tone)}">${esc(x.tone)}</span>${name ? `<span class="nm">${esc(name)}</span> ` : ""}<b>${esc(title)}</b>${x.detail ? `<p>${esc(x.detail)}</p>` : ""}${src ? `<div class="src">${src}</div>` : ""}</div></div>`;
}

function syms(){ const m = new Map(); allItems().forEach(it => { if(it.kind !== "cash" && pos(it).qty > 0 && !m.has(it.sym)) m.set(it.sym, it); }); return [...m.values()]; }

let showAllUp = {};
// list: 보여 줄 종목들(내 계좌 보유 종목 또는 관심종목), k: 접기·더보기 상태 이름
function upcomingPanel(list0 = syms(), k = "up"){
  const t = today(), lim = new Date(Date.now() + 120 * 864e5).toISOString().slice(0, 10);
  const evs = [];
  list0.forEach(it => {
    (INFO[it.sym] ? INFO[it.sym].events : []).forEach(e => evs.push({...e, name: it.name}));
    (ISS[it.sym] ? ISS[it.sym].upcoming : []).forEach(e => evs.push({...e, name: it.name}));
  });
  const list = evs.filter(e => e.date >= t.slice(0, e.date.length) && e.date <= lim).sort((a, b) => a.date < b.date ? -1 : 1);
  const loading = list0.some(it => !INFO[it.sym]);
  const head = `📅 다가오는 일정 <small>${list.length ? list.length + "건" : ""}</small>${foldBtn(k)}`;
  if(FOLD[k]) return `<div class="pf-panel folded"><h3>${head}</h3>${list.length ? `<p class="pf-note one">가장 가까운: ${esc(md(list[0].date))} ${esc(list[0].name)} ${esc(list[0].title)}</p>` : ""}</div>`;
  const shown = showAllUp[k] ? list : list.slice(0, 5);
  return `<div class="pf-panel"><h3>${head}</h3>
    ${shown.length ? shown.map(e => evRow(e, e.name)).join("") : `<p class="pf-note">${loading ? "일정을 불러오는 중…" : "4달 안에 잡힌 일정이 없어요"}</p>`}
    ${list.length > 5 ? `<button type="button" class="pf-more" data-act="moreup" data-k="${k}">${showAllUp[k] ? "접기 ▴" : `+ ${list.length - 5}건 더 보기`}</button>` : ""}
    <p class="pf-note">실적 발표 · 배당 받으려면 갖고 있어야 하는 날 · 회사 행사</p></div>`;
}
function issuePanel(list0 = syms(), k = "iss", title = "내 종목 소식"){
  const all = [];
  list0.forEach(it => (ISS[it.sym] ? ISS[it.sym].recent : []).forEach(x => all.push({...x, name: it.name})));
  all.sort((a, b) => (b.date || "") < (a.date || "") ? -1 : 1);
  const n = list0.length, got = list0.filter(it => ISS[it.sym]).length;
  const cnt = tone => all.filter(x => x.tone === tone).length;
  const shown = showAllIss[k] ? all : all.slice(0, 5);
  const head = `📰 ${title} <small>${got < n ? `읽는 중 ${got}/${n}` : `<span class="pos">호재 ${cnt("호재")}</span> · <span class="neg">악재 ${cnt("악재")}</span>`}</small>${foldBtn(k)}`;
  if(FOLD[k]) return `<div class="pf-panel folded"><h3>${head}</h3></div>`;
  return `<div class="pf-panel"><h3>${head}</h3>
    ${shown.length ? shown.map(x => evRow(x, x.name)).join("") : `<p class="pf-note">${got < n ? "기사를 읽고 정리하는 중이에요…" : "최근 30일 소식이 없어요"}</p>`}
    ${all.length > 5 ? `<button type="button" class="pf-more" data-act="moreiss" data-k="${k}">${showAllIss[k] ? "접기 ▴" : `+ ${all.length - 5}개 더 보기`}</button>` : ""}
    <p class="pf-note">최근 30일 기사·공시를 AI가 요약했어요</p></div>`;
}

// ---------- 동작 ----------
function find(el){ const h = el.closest("[data-acc]"); const a = h ? S.accounts.find(x => x.id === h.dataset.acc) : null;
  const r = el.closest("[data-it]"); return {a, it: r && a ? a.items.find(x => x.id === r.dataset.it) : null}; }

function bind(root){
  root.querySelectorAll(".pf-acc-h input").forEach(inp => inp.onchange = () => { const {a} = find(inp); snap("계좌 이름 바꾸기"); a[inp.dataset.f] = inp.value.trim(); save(); render(); });
  root.querySelectorAll("[data-act]").forEach(b => { if(b.tagName === "INPUT") return; b.onclick = () => act(b.dataset.act, b); });
  root.querySelectorAll(".pf-wadd .q").forEach(inp => inp.onkeydown = e => { if(e.key === "Enter") act("w-add", inp.parentNode.querySelector("[data-act=w-add]")); });
  root.querySelectorAll(".pf-wnew .gname").forEach(inp => inp.onkeydown = e => { if(e.key === "Enter") act("w-newg", inp.parentNode.querySelector("[data-act=w-newg]")); });
  const f = $("#pf-file"); if(f) f.onchange = () => importFile(f.files[0]);
}
function act(k, b){
  if(k === "refresh") return refresh(true);
  if(k === "undo") return undo();
  if(k === "addacc"){ snap("계좌 추가"); const n = S.accounts.length; S.accounts.push({id: uid(), broker: "", name: String.fromCharCode(65 + n % 26) + "계좌", items: []}); save(); render();
    setTimeout(() => { const el = document.querySelectorAll(".pf-acc .br"); if(el.length) el[el.length - 1].focus(); }, 30); return; }
  if(k === "sample") return sample();
  if(k === "export") return exportFile();
  if(k === "import") return $("#pf-file").click();
  if(k === "reset"){ if(confirm("입력한 계좌와 종목을 모두 지울까요? ('되돌리기'로 되살릴 수 있어요)")){ snap("모두 지우기"); S = {accounts: [{id: uid(), broker: "", name: "A계좌", items: []}]}; save(); render(); } return; }
  if(k === "fold"){ FOLD[b.dataset.k] = !FOLD[b.dataset.k]; try{ localStorage.setItem("hrc_pf_fold", JSON.stringify(FOLD)); }catch(e){} render(); return; }
  if(k === "moreiss"){ showAllIss[b.dataset.k] = !showAllIss[b.dataset.k]; render(); return; }
  if(k === "moreup"){ showAllUp[b.dataset.k] = !showAllUp[b.dataset.k]; render(); return; }
  if(k === "tab"){ VIEW.tab = b.dataset.v; try{ localStorage.setItem("hrc_pf_view", JSON.stringify(VIEW)); }catch(e){} render(); if(VIEW.tab === "watch"){ refresh(true); loadAllMeta(watchSyms()); } return; }
  if(k.startsWith("w-")) return watchAct(k, b);
  if(k === "view"){ VIEW[b.closest(".pf-chart").dataset.scope] = b.dataset.v; try{ localStorage.setItem("hrc_pf_view", JSON.stringify(VIEW)); }catch(e){} render(); return; }
  const {a, it} = find(b);
  if(!a) return;
  if(k === "delacc"){ if(confirm(`'${acName(a)}' 계좌를 지울까요? 안에 있는 종목도 함께 지워져요.`)){ snap(acName(a) + " 계좌 삭제"); S.accounts = S.accounts.filter(x => x !== a); save(); render(); toast(`${acName(a)} 계좌를 지웠어요`); } return; }
  if(k === "additem") return addModal(a, b.closest(".pf-sec").dataset.cls, false);
  if(k === "cash") return addModal(a, b.closest(".pf-sec").dataset.cls, true);
  if(!it) return;
  if(k === "open"){ OPEN[it.id] = !OPEN[it.id]; render(); if(OPEN[it.id] && it.kind !== "cash") loadMeta(it, true); return; }
  if(k === "buy" || k === "sell") return trade(a, it, k);
  if(k === "deltr"){ const t = it.trades[+b.dataset.i]; if(confirm(`${t.d} 기록을 지울까요? 수량·평균단가가 다시 계산돼요.`)){ snap(it.name + " 기록 삭제"); it.trades.splice(+b.dataset.i, 1); save(); render(); toast("기록을 지웠어요"); } return; }
  if(k === "delit"){ if(confirm(`'${it.name}'을(를) 지울까요? 사고판 기록도 함께 지워져요.`)){ snap(it.name + " 삭제"); a.items = a.items.filter(x => x !== it); save(); render(); toast(`${it.name}을(를) 지웠어요`); } return; }
  if(k === "move"){ snap(it.name + " 옮기기"); it.cls = it.cls === "safe" ? "risk" : "safe"; save(); render(); toast(`${it.name}을(를) ${it.cls === "safe" ? "안전자산" : "위험자산"} 칸으로 옮겼어요`); return; }
  if(k === "rename"){ const n = prompt("이름", it.name); if(n && n.trim()){ snap("이름 바꾸기"); it.name = n.trim().slice(0, 30); save(); render(); } return; }
  if(k === "cards"){ const tb = document.querySelector('.tab-btn[data-tab="cards"]'); if(tb) tb.click();
    setTimeout(() => { if($("#ec-q")) $("#ec-q").value = it.name; if(window.ecSearch) window.ecSearch(it.code || it.sym); window.scrollTo({top: 0}); }, 80); }
}

const FXC = {};
async function fxOn(d){
  if(!d || d >= today()) return Q.fx;
  if(FXC[d]) return FXC[d];
  try{ const j = await (await fetch("/api/pf/fx?d=" + d)).json(); if(j.fx) FXC[d] = j.fx; return j.fx || null; }catch(e){ return null; }
}
const byDate = (x, y) => (x.d || "") < (y.d || "") ? -1 : (x.d || "") > (y.d || "") ? 1 : 0;

// 종목·현금 추가 창: 종목 이름을 치면 원/달러를 알아서 판별하고 단위·환율을 맞춰 줌
function addModal(a, cls, cash){
  const m = document.createElement("div"); m.className = "pf-modal";
  const where = `${acName(a)} · ${cls === "safe" ? "🛡️ 안전자산" : "🔥 위험자산"}`;
  m.innerHTML = cash ? `<div><h4>현금·예금 추가</h4><div class="s">${esc(where)}</div>
      <label>이름</label><input class="nm" value="예수금" placeholder="예: 파킹통장, CMA, 예수금">
      <label>통화</label><div class="pf-seg wide"><button type="button" data-c="KRW" class="on">🇰🇷 원화</button><button type="button" data-c="USD">🇺🇸 달러</button></div>
      <label class="al">금액 (원)</label><input class="am" type="number" inputmode="decimal" step="any" min="0" placeholder="예: 1500000">
      <div class="bt"><button type="button" class="pf-btn ghost" data-x>취소</button><button type="button" class="pf-btn" data-ok>추가</button></div></div>`
    : `<div><h4>종목 추가</h4><div class="s">${esc(where)}</div>
      <label>① 종목 이름</label><input class="q" placeholder="예: 삼성전자, 인텔, KODEX 200" autocomplete="off">
      <div class="det"></div>
      <div class="rest" style="display:none">
        <label class="pl">② 매수 가격</label><input class="p" type="number" inputmode="decimal" step="any" min="0">
        <label>③ 수량 (주)</label><input class="n" type="number" inputmode="decimal" step="any" min="0" placeholder="예: 10">
        <label>④ 매수일 <small>모르면 그대로 두세요</small></label><input class="d" type="date" value="${today()}" max="${today()}">
        <div class="pv"></div></div>
      <div class="bt"><button type="button" class="pf-btn ghost" data-x>취소</button><button type="button" class="pf-btn" data-ok disabled>추가</button></div></div>`;
  document.body.appendChild(m);
  const close = () => m.remove();
  m.onclick = e => { if(e.target === m) close(); };
  m.querySelector("[data-x]").onclick = close;
  const $m = s => m.querySelector(s);
  if(cash){
    let cur = "KRW";
    m.querySelectorAll("[data-c]").forEach(b => b.onclick = () => { cur = b.dataset.c; m.querySelectorAll("[data-c]").forEach(x => x.classList.toggle("on", x === b));
      $m(".al").textContent = cur === "USD" ? "금액 (달러 $)" : "금액 (원)"; $m(".am").placeholder = cur === "USD" ? "예: 500" : "예: 1500000"; });
    setTimeout(() => $m(".am").focus(), 30);
    $m("[data-ok]").onclick = async () => {
      const name = $m(".nm").value.trim() || "예수금", amt = parseFloat($m(".am").value);
      if(!(amt > 0)){ $m(".am").focus(); return; }
      const fx = cur === "USD" ? await fxOn(today()) : null;
      snap(name + " 추가");
      a.items.push({id: uid(), cls, kind: "cash", sym: "", code: "", name: name.slice(0, 30), cur, trades: [{t: "b", d: today(), p: 1, q: amt, ...(fx ? {fx} : {})}]});
      save(); close(); render(); toast(`${name} ${money(amt, cur)}을(를) 넣었어요`);
    };
    return;
  }
  let res = null, fx = null, timer = null;
  const usd = () => res && res.currency === "USD";
  const paint = () => {
    const ok = $m("[data-ok]"), p = parseFloat($m(".p").value) || (res && res.price), n = parseFloat($m(".n").value);
    ok.disabled = !(res && n > 0 && p > 0);
    if(!res) return;
    const ex = a.items.find(x => x.sym === res.sym);
    $m(".pv").innerHTML = n > 0 && p > 0 ? `${esc(res.name)} ${qtyf(n)}주 × ${money(p, res.currency)} = <b>${money(p * n, res.currency)}</b>${usd() && fx ? ` <small>(환율 ${won(fx)} → ${man(p * n * fx)})</small>` : ""}`
      + (ex && pos(ex).qty > 0 ? `<br><small>이미 가진 종목이라 추가 매수로 넣고 평균단가를 다시 계산해요</small>` : "") : "";
  };
  const detect = async () => {
    const q = $m(".q").value.trim(); res = null; $m(".rest").style.display = "none"; paint();
    if(!q){ $m(".det").innerHTML = ""; return; }
    $m(".det").innerHTML = `<span class="ld">찾는 중…</span>`;
    try{ const r = await fetch("/api/pf/resolve?q=" + encodeURIComponent(q)); const j = await r.json();
      if($m(".q").value.trim() !== q) return;
      if(!r.ok || j.error){ $m(".det").innerHTML = `<span class="err">${esc(j.error || "종목을 찾지 못했어요")}</span>`; return; }
      res = j; fx = usd() ? await fxOn($m(".d").value) : null;
      $m(".det").innerHTML = `<b>${esc(j.name)}</b> <small>${esc(j.code)}</small> · ${usd() ? "🇺🇸 미국 주식이라 <b>달러</b>로 넣어요" : "🇰🇷 <b>원화</b>로 넣어요"} · 지금 ${money(j.price, j.currency)}`;
      $m(".pl").textContent = usd() ? "② 매수 가격 (달러 $)" : "② 매수 가격 (원)";
      $m(".p").placeholder = `비우면 지금 가격 ${money(j.price, j.currency)}`;
      $m(".rest").style.display = ""; paint(); $m(".n").focus();
    }catch(e){ $m(".det").innerHTML = `<span class="err">잠시 뒤 다시 시도해 주세요</span>`; }
  };
  $m(".q").oninput = () => { clearTimeout(timer); timer = setTimeout(detect, 450); };
  $m(".q").onkeydown = e => { if(e.key === "Enter"){ clearTimeout(timer); detect(); } };
  $m(".p").oninput = paint; $m(".n").oninput = paint;
  $m(".n").onkeydown = e => { if(e.key === "Enter") $m("[data-ok]").click(); };
  $m(".d").onchange = async () => { if(usd()){ fx = await fxOn($m(".d").value); paint(); } };
  setTimeout(() => $m(".q").focus(), 30);
  $m("[data-ok]").onclick = async () => {
    if(!res) return;
    const p = parseFloat($m(".p").value) || res.price, n = parseFloat($m(".n").value), day = $m(".d").value || today();
    if(!(n > 0 && p > 0)) return;
    if(usd() && !fx) fx = await fxOn(day);
    if(usd() && !fx){ $m(".pv").innerHTML = `<span class="err">${day} 환율을 찾지 못했어요. 잠시 뒤 다시 시도해 주세요.</span>`; return; }
    const tr = {t: "b", d: day, p, q: n, ...(usd() ? {fx} : {})};
    let it = a.items.find(x => x.sym === res.sym);
    snap(res.name + (it ? " 추가 매수" : " 추가"));
    if(it){ it.trades.push(tr); it.trades.sort(byDate); }
    else { it = {id: uid(), cls, kind: "stock", sym: res.sym, code: res.code, name: res.name, market: res.market, cur: res.currency, trades: [tr]}; a.items.push(it); }
    Q.quotes[res.sym] = Q.quotes[res.sym] || {price: res.price};
    save(); close(); render(); loadMeta(it); refresh();
    toast(`${res.name} ${qtyf(n)}주를 넣었어요`);
  };
}

function trade(a, it, k){
  const cash = it.kind === "cash", cur = it.cur || "KRW", s = stat(it), buy = k === "buy";
  const word = cash ? (buy ? "넣기" : "빼기") : (buy ? "매수" : "매도");
  const m = document.createElement("div"); m.className = "pf-modal";
  m.innerHTML = `<div><h4>${esc(it.name)} ${word}</h4>
    <div class="s">${cash ? "지금 " + money(s.qty, cur) : `가진 것 ${qtyf(s.qty)}주 · 평균 ${money(s.avg, cur)}${s.px ? " · 지금 " + money(s.px, cur) : ""}`}</div>
    ${cash ? "" : `<label>${word} 가격 (${cur === "USD" ? "달러 $" : "원"})</label><input type="number" class="p" step="any" min="0" inputmode="decimal" value="${s.px || ""}">`}
    <label>${cash ? (cur === "USD" ? "금액 (달러 $)" : "금액 (원)") : `${word} 수량 (주)`}</label><input type="number" class="q" step="any" min="0" inputmode="decimal" placeholder="${!buy && !cash ? "최대 " + qtyf(s.qty) : ""}">
    <label>날짜 <small>모르면 그대로 두세요</small></label><input type="date" class="d" value="${today()}" max="${today()}">
    ${cur === "USD" && !cash ? `<label>환율 <small>날짜를 고르면 그날 환율이 들어가요 · 실제 환전 환율로 고쳐도 돼요</small></label><input type="number" class="fx" step="any" min="0" inputmode="decimal" value="${Q.fx || ""}">` : ""}
    <div class="pv"></div>
    <div class="bt"><button type="button" class="pf-btn ghost" data-x>취소</button><button type="button" class="pf-btn ${buy ? "buy" : "sell"}" data-ok>${word}</button></div></div>`;
  document.body.appendChild(m);
  const P = () => cash ? 1 : parseFloat(m.querySelector(".p").value), N = () => parseFloat(m.querySelector(".q").value);
  const FX = () => cur === "USD" && !cash ? parseFloat(m.querySelector(".fx").value) : (cur === "USD" ? Q.fx : 1);
  let fxTouched = false;
  if(cur === "USD" && !cash){
    m.querySelector(".fx").addEventListener("input", () => { fxTouched = true; });
    m.querySelector(".d").addEventListener("change", async () => { if(fxTouched) return; const v = await fxOn(m.querySelector(".d").value); if(v){ m.querySelector(".fx").value = v; pv(); } });
  }
  const pv = () => {
    const p = P(), n = N(), box = m.querySelector(".pv");
    if(!(p > 0) || !(n > 0)){ box.innerHTML = ""; return true; }
    if(!buy && n > s.qty + 1e-9){ box.innerHTML = `<span class="neg">보유 ${cash ? won(s.qty) : qtyf(s.qty) + "주"}보다 많아요.</span>`; return false; }
    const fx = FX();
    if(cur === "USD" && !(fx > 0)){ box.innerHTML = "환율을 넣어 주세요."; return false; }
    if(cash){ box.innerHTML = `${word} 뒤 금액: <b>${money(buy ? s.qty + n : s.qty - n, cur)}</b>`; return true; }
    if(buy){ const q2 = s.qty + n, a2 = (s.avg * s.qty + p * n) / q2, k2 = (s.avgK * s.qty + p * fx * n) / q2;
      box.innerHTML = `넣으면 <b>${qtyf(q2)}주</b> · 평균단가 ${s.qty ? `${money(s.avg, cur)} → ` : ""}<b>${money(a2, cur)}</b>`; }
    else { const r = (p - s.avg) * n;
      const rk = (p * fx - s.avgK) * n;
      box.innerHTML = `넣으면 <b>${qtyf(s.qty - n)}주</b> 남아요 · 이번에 <b class="${sgn(r)}">${signed(r, v => money(v, cur))}</b> ${r >= 0 ? "벌었어요" : "손해 봤어요"}${cur === "USD" ? ` <small>(원화로 ${signed(rk, man)})</small>` : ""}
        <br><small style="color:var(--muted)">팔아도 평균단가는 그대로예요(증권사와 같은 방식)</small>`; }
    return true;
  };
  m.querySelectorAll("input").forEach(i => i.oninput = pv); pv();
  setTimeout(() => m.querySelector(".q").focus(), 30);
  const close = () => m.remove();
  m.onclick = e => { if(e.target === m) close(); };
  m.querySelector("[data-x]").onclick = close;
  m.querySelector("[data-ok]").onclick = () => {
    const p = P(), n = N(); if(!(p > 0) || !(n > 0) || !pv()) return;
    snap(`${it.name} ${word} ${cash ? money(n, cur) : qtyf(n) + "주"}`);
    it.trades.push({t: buy ? "b" : "s", d: m.querySelector(".d").value || today(), p, q: n, ...(cur === "USD" ? {fx: FX()} : {})});
    it.trades.sort(byDate);
    save(); close(); render(); toast(`${it.name}: ${cash ? money(n, cur) + (buy ? " 넣었어요" : " 뺐어요") : qtyf(n) + "주 " + word + " 기록을 넣었어요"}`);
  };
}

// ---------- 데이터 불러오기 ----------
async function refresh(force){
  const list = [...new Set([...syms().map(it => it.sym), ...watchAll().map(w => w.sym)])];
  if(!list.length && !allItems().some(i => i.cur === "USD")){ Q.time = new Date().toISOString(); return render(); }
  try{
    const r = await fetch("/api/pf/quotes?s=" + encodeURIComponent(list.join(",")));
    const j = await r.json();
    Q.quotes = {...Q.quotes, ...(j.quotes || {})}; Q.fx = j.fx || Q.fx; Q.time = j.time;
  }catch(e){}
  if(document.activeElement && document.activeElement.closest && document.activeElement.closest("#pf-root") && !force) return;  // 입력 중이면 다시 그리지 않음
  render();
}
const busy = {};
async function loadMeta(it, withIssues){
  const s = it.sym; if(!s) return;
  const jobs = [];
  if(!INFO[s] && !busy["i" + s]){ busy["i" + s] = 1;
    jobs.push(fetch("/api/pf/info?s=" + encodeURIComponent(s)).then(r => r.json()).then(j => { INFO[s] = j.error ? {events: [], error: j.error} : j; })
      .catch(() => { INFO[s] = {events: []}; }).finally(() => { delete busy["i" + s]; })); }
  if(!ISS[s] && !busy["s" + s]){ busy["s" + s] = 1;
    jobs.push(fetch("/api/pf/issues?s=" + encodeURIComponent(s) + "&n=" + encodeURIComponent(it.name)).then(r => r.json()).then(j => { ISS[s] = j.error ? {recent: [], upcoming: [], news: []} : j; })
      .catch(() => { ISS[s] = {recent: [], upcoming: [], news: []}; }).finally(() => { delete busy["s" + s]; })); }
  await Promise.all(jobs);
  if(jobs.length && !(document.activeElement && document.activeElement.closest && document.activeElement.closest(".pf-acc-h"))) render();
}
async function loadAllMeta(list = syms()){
  let i = 0;
  const worker = async () => { while(i < list.length){ const it = list[i++]; await loadMeta(it); } };
  await Promise.all([worker(), worker(), worker()]);
}

// ---------- 관심종목: 개별 + 그룹(예: 로봇주) ----------
// S.watch = {groups: [{id, name, items: [{id, sym, code, name, cur}]}]} — 첫 그룹(id "solo")은 '개별 관심종목'
function watch(){
  if(!S.watch || !Array.isArray(S.watch.groups)) S.watch = {groups: []};
  if(!S.watch.groups.some(g => g.id === "solo")) S.watch.groups.unshift({id: "solo", name: "개별 관심종목", items: []});
  return S.watch;
}
const watchAll = () => (S.watch && S.watch.groups ? S.watch.groups.flatMap(g => g.items) : []);
const WOPEN = {};
function watchSyms(){ const m = new Map(); watchAll().forEach(w => { if(!m.has(w.sym)) m.set(w.sym, w); }); return [...m.values()]; }
function watchView(){
  const W = watch(), solo = W.groups[0], groups = W.groups.slice(1);
  const card = w => {
    const q = Q.quotes[w.sym], op = WOPEN[w.id], inf = INFO[w.sym], iss = ISS[w.sym];
    const own = allItems().some(it => it.sym === w.sym && pos(it).qty > 0);
    let det = "";
    if(op){
      const e = inf && inf.earnings, d = inf && inf.dividend, last = inf && inf.last;
      const evs = [...(inf ? inf.events : []), ...(iss ? iss.upcoming : [])].sort((x, y) => x.date < y.date ? -1 : 1);
      det = `<div class="pf-det">${!inf ? `<p class="pf-note">불러오는 중…</p>` : `
        <div class="blk"><h5>📊 실적</h5>${inf.etf ? "<p>ETF라 실적 발표가 없어요</p>" : `<p>다음 발표 ${e && e.next ? `<b>${md(e.next)}</b> ${dday(e.next)}${e.est ? " <small>(예상일)</small>" : ""}` : "미정"}</p>
          ${last && last.headline ? `<p>지난 ${esc(last.label)}: <b>${esc(last.headline)}</b></p>` : ""}`}</div>
        <div class="blk"><h5>💰 배당</h5>${d && d.annual ? `<p>1주에 1년 <b>${money(d.annual, w.cur)}</b>${q && q.price ? ` · 배당수익률 약 ${(d.annual / q.price * 100).toFixed(1)}%` : ""}</p>${d.next_ex ? `<p>다음 배당 기준 ${md(d.next_ex)}${d.next_ex_est ? " <small>(예상)</small>" : ""}</p>` : ""}` : "<p>최근 1년 배당이 없어요</p>"}</div>`}
        <div class="blk wide"><h5>📅 앞으로 · 📰 최근 소식</h5>${evs.map(x => evRow(x, null)).join("")}${iss ? (iss.recent.length ? iss.recent.slice(0, 4).map(x => evRow(x, null)).join("") : "<p>최근 30일 소식이 없어요</p>") : `<p class="pf-note">기사 읽는 중…</p>`}</div></div>`;
    }
    return `<div class="pf-witem${op ? " open" : ""}" data-w="${w.id}">
      <div class="l1"><b class="nm" data-act="w-open">${esc(w.name)}</b><small>${esc(w.code || w.sym)}</small>${own ? `<span class="own">보유 중</span>` : ""}
        <span class="px">${q && q.price ? money(q.price, w.cur) : "…"}</span>
        <span class="chg ${q ? sgn(q.chg_pct) : ""}">${q && q.chg_pct != null ? pctf(q.chg_pct) : ""}</span>
        <button type="button" class="tog" data-act="w-open">${op ? "▴" : "▾"}</button>
        <button type="button" class="del" data-act="w-del" title="관심종목에서 빼기">✕</button></div>${det}</div>`;
  };
  const groupAvg = g => { const v = g.items.map(w => Q.quotes[w.sym]).filter(q => q && q.chg_pct != null); return v.length ? v.reduce((s, q) => s + q.chg_pct, 0) / v.length : null; };
  const addRow = gid => `<div class="pf-wadd" data-g="${gid}"><input class="q" placeholder="종목 이름·티커 (예: ${gid === "solo" ? "애플, 현대차" : "레인보우로보틱스, 테슬라"})" autocomplete="off"><button type="button" class="pf-btn sm" data-act="w-add">추가</button><span class="msg"></span></div>`;
  const grpCard = (g, i) => { const avg = groupAvg(g), fold = FOLD["wg" + g.id], c = ACC[i % ACC.length];
    return `<div class="pf-panel pf-wgroup" data-g="${g.id}" style="--ac:${c};--ac-soft:${c}14">
      <div class="pf-wg-h"><b>📁 ${esc(g.name)}</b><small>${g.items.length}종목</small>
        ${avg != null ? `<span class="avg">오늘 평균 <b class="${sgn(avg)}">${pctf(avg)}</b></span>` : ""}
        <button type="button" class="lnk mute" data-act="w-rename">이름 바꾸기</button><button type="button" class="lnk mute" data-act="w-delg">그룹 삭제</button>
        <button type="button" class="pf-fold" data-act="fold" data-k="wg${g.id}">${fold ? "펴기 ▾" : "접기 ▴"}</button></div>
      ${fold ? "" : `${g.items.length ? g.items.map(card).join("") : `<p class="pf-note">아직 없어요. 아래에서 종목을 넣어 보세요.</p>`}${addRow(g.id)}`}</div>`; };
  const wl = watchSyms();
  return `
  ${wl.length ? `<div class="pf-two">${upcomingPanel(wl, "wup")}${issuePanel(wl, "wiss", "관심종목 소식")}</div>` : ""}
  <div class="pf-panel" data-g="solo"><h3>⭐ 개별 관심종목 <small>${solo.items.length ? solo.items.length + "종목" : "궁금한 종목을 하나씩 넣어 두세요"}</small></h3>
    ${solo.items.map(card).join("")}${addRow("solo")}</div>
  <div class="pf-wg-top"><h3>📁 관심종목 그룹 <small>주제별로 묶어 보기 (예: 로봇주, 반도체, 배당주)</small></h3>
    <div class="pf-wnew"><input class="gname" placeholder="새 그룹 이름 (예: 로봇주)"><button type="button" class="pf-btn sm" data-act="w-newg">＋ 그룹 만들기</button></div></div>
  ${groups.length ? groups.map(grpCard).join("") : `<div class="pf-panel pf-empty-g">아직 그룹이 없어요. 위에서 '로봇주'처럼 이름을 넣고 그룹을 만들어 보세요.</div>`}
  <div class="pf-foot"><span class="sp"></span>${UNDO.length ? `<button type="button" class="lnk" data-act="undo">↶ 되돌리기</button>` : ""}
    <p>현재가는 30초마다 바뀌어요. 종목 이름을 누르면 실적 발표일 · 배당 · 최근 소식을 볼 수 있어요. 관심종목도 이 브라우저에만 저장되고, 백업 파일에 함께 들어가요.</p></div>`;
}
async function watchAct(k, b){
  const W = watch();
  if(k === "w-newg"){
    const inp = b.parentNode.querySelector(".gname"), name = inp.value.trim();
    if(!name){ inp.focus(); return; }
    snap(name + " 그룹 만들기"); W.groups.push({id: uid(), name: name.slice(0, 20), items: []}); save(); render();
    setTimeout(() => { const el = document.querySelectorAll(".pf-wgroup .pf-wadd .q"); if(el.length) el[el.length - 1].focus(); }, 30);
    toast(`'${name}' 그룹을 만들었어요. 종목을 넣어 보세요`); return;
  }
  const gEl = b.closest("[data-g]"), g = gEl && W.groups.find(x => x.id === gEl.dataset.g);
  if(!g) return;
  if(k === "w-add"){
    const box = b.closest(".pf-wadd"), inp = box.querySelector(".q"), q = inp.value.trim(), msg = box.querySelector(".msg");
    if(!q){ inp.focus(); return; }
    msg.textContent = "찾는 중…"; msg.className = "msg";
    try{ const r = await fetch("/api/pf/resolve?q=" + encodeURIComponent(q)); const j = await r.json();
      if(!r.ok || j.error) throw new Error(j.error || "종목을 찾지 못했어요.");
      if(g.items.some(w => w.sym === j.sym)){ msg.textContent = `${j.name}은(는) 이미 있어요`; msg.className = "msg err"; return; }
      snap(`${g.name}에 ${j.name} 추가`);
      g.items.push({id: uid(), sym: j.sym, code: j.code, name: j.name, cur: j.currency});
      Q.quotes[j.sym] = Q.quotes[j.sym] || {price: j.price};
      save(); render(); refresh(true); loadMeta(g.items[g.items.length - 1]); toast(`${g.name}에 ${j.name}을(를) 넣었어요`);
      setTimeout(() => { const el = document.querySelector(`.pf-wadd[data-g="${g.id}"] .q`); if(el) el.focus(); }, 30);
    }catch(e){ msg.textContent = e.message; msg.className = "msg err"; }
    return;
  }
  if(k === "w-delg"){ if(confirm(`'${g.name}' 그룹을 지울까요? 안의 종목 ${g.items.length}개도 함께 빠져요.`)){ snap(g.name + " 그룹 삭제"); W.groups = W.groups.filter(x => x !== g); save(); render(); toast(`'${g.name}' 그룹을 지웠어요`); } return; }
  if(k === "w-rename"){ const n = prompt("그룹 이름", g.name); if(n && n.trim()){ snap("그룹 이름 바꾸기"); g.name = n.trim().slice(0, 20); save(); render(); } return; }
  const w = g.items.find(x => x.id === b.closest("[data-w]").dataset.w); if(!w) return;
  if(k === "w-del"){ snap(`${g.name}에서 ${w.name} 빼기`); g.items = g.items.filter(x => x !== w); save(); render(); toast(`${w.name}을(를) 뺐어요`); return; }
  if(k === "w-open"){ WOPEN[w.id] = !WOPEN[w.id]; render(); if(WOPEN[w.id]) loadMeta(w); return; }
}

// 환율 없이 저장된 달러 매매(이 기능 전 기록·백업)는 그날 환율로 채움
async function fillFx(){
  let ch = false;
  for(const it of allItems()) if(it.cur === "USD") for(const t of it.trades || []) if(!t.fx){ const v = await fxOn(t.d || today()); if(v){ t.fx = v; ch = true; } }
  if(ch){ save(); render(); }
}

// ---------- 백업 · 예시 ----------
function exportFile(){
  const blob = new Blob([JSON.stringify(S, null, 1)], {type: "application/json"});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "내계좌_백업_" + today() + ".json"; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
function importFile(f){
  if(!f) return; const rd = new FileReader();
  rd.onload = () => { try{ const j = JSON.parse(rd.result);
      if(!j || !Array.isArray(j.accounts)) throw 0;
      if(!confirm(`백업을 불러올까요? 지금 화면의 계좌(${S.accounts.length}개)는 백업 내용으로 바뀌어요.`)) return;
      snap("백업 불러오기"); S = j; save(); render(); refresh().then(fillFx); loadAllMeta();
    }catch(e){ alert("백업 파일을 읽지 못했어요. '백업 파일 저장'으로 만든 .json 파일인지 확인해 주세요."); } };
  rd.readAsText(f);
}
async function sample(){
  const d = n => { const x = new Date(Date.now() - n * 864e5); return x.toISOString().slice(0, 10); };
  const mk = (cls, sym, code, name, cur, trades) => ({id: uid(), cls, kind: "stock", sym, code, name, market: cur === "USD" ? "US" : "KR", cur, trades});
  snap("예시로 채우기");
  S = {accounts: [
    {id: uid(), broker: "키움증권", name: "A계좌", items: [
      {id: uid(), cls: "safe", kind: "cash", sym: "", code: "", name: "예수금", cur: "KRW", trades: [{t: "b", d: d(60), p: 1, q: 1500000}]},
      mk("safe", "153130.KS", "153130", "KODEX 단기채권", "KRW", [{t: "b", d: d(90), p: 112000, q: 20}]),
      mk("risk", "005930.KS", "005930", "삼성전자", "KRW", [{t: "b", d: d(120), p: 180000, q: 10}, {t: "b", d: d(40), p: 215000, q: 5}]),
      mk("risk", "000660.KS", "000660", "SK하이닉스", "KRW", [{t: "b", d: d(100), p: 900000, q: 2}])]},
    {id: uid(), broker: "미래에셋증권", name: "B계좌 (해외)", items: [
      mk("safe", "SGOV", "SGOV", "iShares 0-3개월 미국채", "USD", [{t: "b", d: d(80), p: 100.4, q: 30}]),
      mk("risk", "ORCL", "ORCL", "오라클", "USD", [{t: "b", d: d(150), p: 210, q: 5}, {t: "s", d: d(30), p: 250, q: 2}]),
      mk("risk", "INTC", "INTC", "인텔", "USD", [{t: "b", d: d(70), p: 40, q: 30}]),
      mk("risk", "KO", "KO", "코카콜라", "USD", [{t: "b", d: d(200), p: 70, q: 10}])]}]};
  save(); render(); await refresh(true); await fillFx(); loadAllMeta();
}

// ---------- 시작 ----------
window.pfOpen = function(){
  render();
  if(!started){ started = true; refresh(true).then(fillFx); loadAllMeta(VIEW.tab === "watch" ? [...watchSyms(), ...syms()] : syms());
    timer = setInterval(() => { if(!document.hidden && $("#tab-pf") && $("#tab-pf").style.display !== "none") refresh(); }, 30000); }
};
})();
