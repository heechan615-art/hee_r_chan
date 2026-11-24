// 경제지표 해석 탭 — 보기 전용. 원본 사이트는 히르찬 맥의 ~/projects/경제지표(올리기·자동 해석),
// 거기서 export_valueai.py가 static/econ/bundle.json(지표 수치 + 해석 글 + 추가 해석)을 만든다.
// 화면 안 이동(홈 · 지표 · 해석 글)은 주소를 바꾸지 않고 이 탭 안에서만 한다.
(function(){
  const LIBS = ["https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js",
                "https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"];
  const WARM = "#e8590c", COOL = "#1c7ed6", PAL = ["#0e1c36", "#B0883A", "#1c7ed6", "#e8590c", "#2b8a3e", "#7c3aed", "#db2777"];
  const CTY = {US: "🇺🇸 미국", KR: "🇰🇷 한국", CN: "🇨🇳 중국", EU: "🇪🇺 유럽"};
  let B = null, charts = [], ready = null;
  const root = () => document.getElementById("econ-root");
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const today = () => new Date().toISOString().slice(0, 10);
  const ym = m => { const [y, mo] = m.split("-"); return mo ? `${y.slice(2)}.${mo}` : m; };
  const fmt = (v, u) => v == null ? "-" : (Math.abs(v) >= 1000 ? v.toLocaleString("ko-KR") : v) + (u === "%" ? "%" : u ? " " + u : "");
  const R = () => B.reports.map(r => r.meta);

  function loadScript(src){
    return new Promise((ok, no) => {
      if(document.querySelector('script[src="' + src + '"]')) return ok();
      const s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = no; document.head.appendChild(s);
    });
  }
  async function init(){
    await Promise.all(LIBS.map(loadScript));
    Chart.defaults.animation = false; Chart.defaults.font.family = "'Pretendard Variable', Pretendard, sans-serif"; Chart.defaults.color = "#4a515c";
    B = await fetch("/static/econ/bundle.json", {cache: "no-store"}).then(r => r.json());
  }
  function last(s, n = 1){ const k = Object.keys(s.data || {}).sort(); return k.slice(-n).map(m => [m, s.data[m]]); }
  function primary(ind){ const s = ind.series || {}; return s[ind.primary] || Object.values(s)[0] || null; }
  function signal(ind){
    if(ind.signal) return ind.signal;
    const s = primary(ind); if(!s || ind.target == null) return null;
    const v = last(s)[0]; if(!v) return null;
    if(ind.target === 50) return v[1] >= 50 ? {t: "확장", c: "mid"} : {t: "위축", c: "cold"};
    const d = v[1] - ind.target;
    return d > 0.5 ? {t: "목표보다 높음", c: "hot"} : d < -0.5 ? {t: "목표보다 낮음", c: "cold"} : {t: "목표 근처", c: "mid"};
  }
  function spark(s){
    const pts = last(s, 24).map(x => x[1]); if(pts.length < 2) return "";
    const mn = Math.min(...pts), mx = Math.max(...pts), w = 240, h = 36, r = mx - mn || 1;
    const xy = pts.map((v, i) => `${(i / (pts.length - 1) * w).toFixed(1)},${(h - 3 - (v - mn) / r * (h - 6)).toFixed(1)}`);
    return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${xy.join(" ")}" fill="none" stroke="#163a5c" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
  }
  function destroy(){ charts.forEach(c => c.destroy()); charts = []; }
  // 묶음(제조업 PMI = ISM + S&P 글로벌 등)
  const G = () => B.groups || [];
  const groupOf = id => G().find(g => g.members.includes(id));
  const nameOf = id => ((B.indicators.find(i => i.id === id) || G().find(g => g.id === id)) || {}).name || id;
  const SHORT = id => /-ism-/.test(id) ? "ISM" : /-spg-/.test(id) ? "S&P 글로벌" : nameOf(id);
  const arrow = d => d > 0 ? "▲" : d < 0 ? "▼" : "−";
  const udc = d => d > 0 ? "ec-up" : d < 0 ? "ec-dn" : "";
  function groupSignal(g, ms){
    if(g.signal) return g.signal;
    const v = ms.map(i => { const s = primary(i), l = s ? last(s) : []; return l.length ? l[0][1] : null; });
    if(v.some(x => x == null)) return null;
    return v.every(x => x >= 50) ? {t: "둘 다 확장", c: "mid"} : v.every(x => x < 50) ? {t: "둘 다 위축", c: "cold"} : {t: "엇갈림", c: "na"};
  }
  // 탭 안 이동 기록: '← 뒤로'는 직전 화면(보던 위치까지), '🏠 경제지표 홈'은 처음 화면
  let cur = ["h", ""], hist = [];
  function go(view, id, back){
    if(!back){
      if(view === "h") hist = [];
      else if(cur[0] !== view || cur[1] !== id) hist.push([cur[0], cur[1], window.scrollY]);
    }
    cur = [view, id || ""];
    destroy();
    const V = {i: indicator, g: group, r: report, f: fedHome, fp: fedPersonPage, fs: fedSpeech, s: spreadPage, a: aiPageV, w: aiwPageV, m: memPage, c: cuPage, o: otherList, od: otherOne, hr: hmrList};
    (V[view] || home)(id);
    if(view !== "h") addNav();
    if(back && back.y != null) window.scrollTo(0, back.y);
    else {   // 탭 맨 위로 — 모바일은 위에 붙은 메뉴 막대에 가리지 않게 그 높이만큼 덜 올림
      const top = document.getElementById("tab-econ"), sb = document.querySelector(".sidebar");
      const cover = document.documentElement.classList.contains("is-mobile") && sb ? sb.offsetHeight : 0;
      if(top){ const y = top.getBoundingClientRect().top + window.scrollY - cover - 8; if(window.scrollY > y) window.scrollTo(0, Math.max(0, y)); }
    }
  }
  function goBack(){
    const p = hist.pop();
    if(p) go(p[0], p[1], {y: p[2]}); else go("h");
  }
  function addNav(){
    const bar = where => `<div class="ec-nav ${where}"><button type="button" class="back" data-back="1">← 뒤로</button><button type="button" class="home" data-home="1">🏠 경제지표 홈</button></div>`;
    root().insertAdjacentHTML("afterbegin", bar("top"));
    root().insertAdjacentHTML("beforeend", bar("bot"));
    root().querySelectorAll("[data-back]").forEach(b => b.onclick = goBack);
    root().querySelectorAll("[data-home]").forEach(b => b.onclick = () => go("h"));
  }
  function bindNav(){
    root().querySelectorAll("[data-go]").forEach(a => a.onclick = e => { e.preventDefault(); const [v, ...id] = a.dataset.go.split(":"); go(v, id.join(":")); });
  }

  // ---------- 홈 ----------
  function home(){
    const D = B.indicators, reps = R();
    const up = D.filter(i => i.next_release && i.next_release >= today()).sort((a, b) => a.next_release < b.next_release ? -1 : 1);
    const name = id => (G().some(g => g.id === id) ? "🧩 " : "") + nameOf(id);
    let h = `<div class="ec-hub">${FP().length ? `<a href="#" data-go="f"><b>🏛️ 연준 인사 발언</b><span>매파 ↔ 비둘기 위치 · 발언 종합 · 인사별 기록</span></a>` : ""}
      <a href="#" data-go="w"><b>🛰️ AI 위험 추적</b><span>AI 리스크 계기판 · 신용 스프레드 · 메모리 가격 · 공장 가동률</span></a></div>
    <div class="home-top">
      <div class="panel"><h2 style="margin-top:0">📝 최근 해석 <small>${reps.length ? reps.length + "건" : ""}</small></h2>
        ${reps.length ? `<div class="rlist">${reps.slice(0, 6).map(r => `<a href="#" data-go="r:${esc(r.id)}"><div class="dt"><b>${esc((r.release || "").slice(5).replace("-", "/"))}</b>발표</div>
          <div><div class="t">${esc(name(r.indicator))} · ${esc(r.period || "")}</div><div class="c">${esc(r.conclusion || r.title || "")}</div></div></a>`).join("")}</div>`
        : `<div class="empty">아직 해석이 없어요. 발표 자료가 나오면 히르찬이 해석을 올려요.</div>`}</div>
      <div class="panel"><h2 style="margin-top:0">📅 다가오는 발표</h2>
        ${up.length ? `<div class="up">${up.slice(0, 8).map(i => `<a href="#" data-go="i:${i.id}"><span>${esc(i.name)}</span><b>${esc(i.next_release.slice(5).replace("-", "/"))}</b></a>`).join("")}</div>`
        : `<p class="muted" style="font-size:14px;margin:0">해석할 때 확인한 다음 발표일이 여기 모여요.</p>`}</div>
    </div>
    <div id="ec-bslot"></div><div id="ec-sslot"></div>`;
    for(const c of ["US", "KR", "CN", "EU"]){
      const list = D.filter(i => i.country === c); if(!list.length) continue;
      const cards = list.map(i => { const g = groupOf(i.id); return !g ? card(i) : g.members[0] === i.id ? groupCard(g) : ""; });
      h += `<div class="cty">${CTY[c]}</div><div class="grid">${cards.join("")}</div>`;
    }
    root().innerHTML = h + `<p class="foot">숫자는 발표 원문 그대로이며, 계산·추정값은 따로 표시해요. 투자 권유가 아닌 공부용 해석이에요. · 업데이트 ${esc(B.updated)}</p>`;
    bindNav();
    briefsHome();
    aiwHomeV();
  }
  function card(ind){
    const s = primary(ind), l = s ? last(s, 2) : [];
    if(!l.length) return `<a class="card none" href="#" data-go="i:${ind.id}"><div class="h"><span class="nm">${esc(ind.name)}</span><span class="sig na">${esc(ind.category)}</span></div>
      <div class="ds">${esc(ind.desc)}</div><div class="v"><b>아직 자료 없음</b></div></a>`;
    const [m, v] = l[l.length - 1], p = l.length > 1 ? l[0][1] : null, d = p == null ? null : v - p, sg = signal(ind);
    return `<a class="card" href="#" data-go="i:${ind.id}"><div class="h"><span class="nm">${esc(ind.name)}</span>${sg ? `<span class="sig ${sg.c}">${esc(sg.t)}</span>` : ""}</div>
      <div class="ds">${esc(ind.desc)}</div>
      <div class="v"><b>${fmt(v, s.unit)}</b>${d != null ? `<span class="${d > 0 ? "ec-up" : d < 0 ? "ec-dn" : ""}">${d > 0 ? "▲" : d < 0 ? "▼" : "−"} ${Math.abs(d).toFixed(1)}${s.unit === "%" ? "%p" : ""}</span>` : ""}</div>
      <div class="lb">${esc(s.label)} · ${ym(m)}</div>${spark(s)}
      ${ind.next_release ? `<div class="nx">다음 발표 ${esc(ind.next_release)}</div>` : ""}</a>`;
  }

  function groupCard(g){
    const ms = g.members.map(id => B.indicators.find(i => i.id === id)).filter(Boolean), sg = groupSignal(g, ms);
    const rows = ms.map(ind => { const s = primary(ind), l = s ? last(s, 2) : [];
      if(!l.length) return `<div class="gr"><span>${esc(SHORT(ind.id))}</span><b class="na">아직 자료 없음</b></div>`;
      const [m, v] = l[l.length - 1], d = l.length > 1 ? v - l[0][1] : null;
      return `<div class="gr"><span>${esc(SHORT(ind.id))}</span><b>${fmt(v, s.unit)}</b>${d != null ? `<em class="${udc(d)}">${arrow(d)} ${Math.abs(d).toFixed(1)}</em>` : ""}<small>${ym(m)}</small></div>`; });
    const nx = ms.map(i => i.next_release).filter(Boolean).sort()[0];
    return `<a class="card gcard" href="#" data-go="g:${g.id}"><div class="h"><span class="nm">🧩 ${esc(g.name)}</span>${sg ? `<span class="sig ${sg.c}">${esc(sg.t)}</span>` : ""}</div>
      <div class="ds">${esc(ms.map(i => SHORT(i.id)).join(" · "))} 함께 보기 · 각각의 해석 + 종합 해석</div><div class="grs">${rows.join("")}</div>
      ${g.summary ? `<div class="gs">${esc(g.summary)}</div>` : ""}${nx ? `<div class="nx">다음 발표 ${esc(nx)}</div>` : ""}</a>`;
  }

  // ---------- 그래프 ----------
  function lineChart(el, months, sets, target, unit){
    return new Chart(el, {type: "line", data: {labels: months.map(ym), datasets: [
        ...sets.map((s, i) => ({label: s.label, data: months.map(m => s.data[m] ?? null), borderColor: PAL[i % PAL.length], backgroundColor: PAL[i % PAL.length],
          borderWidth: i === 0 ? 2.5 : 2, pointRadius: months.length <= 13 ? 3.5 : 0, pointHoverRadius: 5, spanGaps: true, tension: .25})),
        ...(target != null ? [{label: `목표 ${target}${unit === "%" ? "%" : ""}`, data: months.map(() => target), borderColor: "#9aa1ab", borderDash: [6, 5], borderWidth: 1.5, pointRadius: 0}] : [])]},
      options: {responsive: true, maintainAspectRatio: false, interaction: {mode: "index", intersect: false},
        plugins: {legend: {labels: {boxWidth: 12}}, tooltip: {callbacks: {label: c => `${c.dataset.label}: ${c.parsed.y ?? "-"}${unit === "%" ? "%" : ""}`}}},
        scales: {y: {ticks: {callback: v => +(+v).toFixed(4) + (unit === "%" ? "%" : "")}, grid: {color: "#eef0f3"}}, x: {grid: {display: false}, ticks: {maxTicksLimit: 12}}}}});
  }
  function barChart(el, labels, values, unit, horizontal, label, multi){
    const sets = multi ? multi.map((d, i) => ({label: d.label, data: d.data, backgroundColor: ["#9aa7b8", "#163a5c", WARM, COOL][i % 4], borderRadius: 4}))
                       : [{label: label || "", data: values, backgroundColor: values.map(v => v >= 0 ? WARM : COOL), borderRadius: 4}];
    return new Chart(el, {type: "bar", data: {labels, datasets: sets},
      options: {indexAxis: horizontal ? "y" : "x", responsive: true, maintainAspectRatio: false,
        plugins: {legend: {display: !!multi, labels: {boxWidth: 12}}, tooltip: {callbacks: {label: c => `${c.dataset.label ? c.dataset.label + ": " : ""}${c.parsed[horizontal ? "x" : "y"]}${unit === "%" ? "%" : unit ? " " + unit : ""}`}}},
        scales: {[horizontal ? "x" : "y"]: {ticks: {callback: v => +(+v).toFixed(4) + (unit === "%" ? "%" : "")}, grid: {color: "#eef0f3"}}, [horizontal ? "y" : "x"]: {grid: {display: false}}}}});
  }
  function heatColor(v, mx){ const a = Math.min(Math.abs(v) / (mx || 1), 1); return v >= 0 ? `rgba(232,89,12,${.12 + a * .7})` : `rgba(28,126,214,${.12 + a * .7})`; }

  // ---------- 지표 ----------
  function indicator(id){
    const ind = B.indicators.find(i => i.id === id); if(!ind){ home(); return; }
    const S = Object.entries(ind.series || {}), main = S.filter(([, s]) => s.axis !== "mom"), mom = S.filter(([, s]) => s.axis === "mom");
    const months = [...new Set(S.flatMap(([, s]) => Object.keys(s.data)))].sort().slice(-36);
    const reps = R().filter(r => r.indicator === id), sg = signal(ind), grp = groupOf(id);
    let h = `<div class="crumb"><a href="#" data-go="h">경제지표 홈</a> › ${CTY[ind.country] || ""}${grp ? ` › <a href="#" data-go="g:${grp.id}">🧩 ${esc(grp.name)}</a>` : ""}</div>
    <div class="ihead"><div><h1>${esc(ind.name)} ${sg ? `<span class="sig ${sg.c}" style="font-size:13px;vertical-align:4px">${esc(sg.t)}</span>` : ""}</h1>
      <div class="meta">${esc(ind.desc)}<br>발표 ${esc(ind.agency)} · ${esc(ind.freq)}마다${ind.target != null ? ` · 기준선 ${ind.target}` : ""}${ind.next_release ? ` · <b>다음 발표 ${esc(ind.next_release)}</b>` : ""}</div>
      ${grp ? `<a class="gonote" href="#" data-go="g:${grp.id}">🧩 ${esc(grp.members.filter(x => x !== id).map(SHORT).join(" · "))}와 나란히 보기 · 종합 해석 →</a>` : ""}
      ${ind.summary ? `<div class="concl" style="margin-top:10px"><small>최근 해석 한 줄</small>${esc(ind.summary)}</div>` : ""}</div>
      <div class="kpis">${S.slice(0, 4).map(([, s]) => { const l = last(s, 2); if(!l.length) return ""; const v = l[l.length - 1][1], d = l.length > 1 ? v - l[0][1] : null;
        return `<div class="kpi"><span>${esc(s.label)} · ${ym(l[l.length - 1][0])}</span><b>${fmt(v, s.unit)}</b>${d != null ? `<em class="${d > 0 ? "ec-up" : d < 0 ? "ec-dn" : ""}">${d > 0 ? "▲" : d < 0 ? "▼" : ""}${Math.abs(d).toFixed(1)}</em>` : ""}</div>`; }).join("")}</div></div>`;
    h += `<h2>📝 해석 기록 <small>${reps.length}건</small></h2>${reps.length ? `<div class="panel rlist">${reps.map(r => `<a href="#" data-go="r:${esc(r.id)}"><div class="dt"><b>${esc((r.release || "").slice(5).replace("-", "/"))}</b>발표</div>
      <div><div class="t">${esc(r.period || "")}</div><div class="c">${esc(r.conclusion || "")}</div></div></a>`).join("")}</div>` : `<div class="empty">아직 해석이 없어요. 발표 자료가 나오면 히르찬이 해석을 올려요.</div>`}`;
    if(S.length){
      h += `<div class="charts"><div class="chartbox"><h3>📈 추세 (최근 ${months.length}${ind.freq === "분기" ? "분기" : "개월"})</h3><div class="cv"><canvas id="ec-c1"></canvas></div></div>
        ${mom.length ? `<div class="chartbox"><h3>📊 ${esc(mom[0][1].label)}</h3><div class="cv"><canvas id="ec-c2"></canvas></div></div>` : ""}</div>
        ${ind.auto_source ? `<div class="src">출처: ${esc(ind.auto_source)}${ind.auto_latest ? ` (최신 ${esc(ind.auto_latest)})` : ""}</div>` : ""}`;
    }
    // 세부 항목 히트맵: 본 표(items) + 추가 표(items_extra: [{label, items}], 예 PCE 전년비·소득소비)
    const heats = [];
    if(ind.items && Object.keys(ind.items).length) heats.push({label: ind.items_label || "", items: ind.items});
    (ind.items_extra || []).forEach(x => { if(x.items && Object.keys(x.items).length) heats.push(x); });
    heats.forEach((hm, n) => {
      const im = [...new Set(Object.values(hm.items).flatMap(o => Object.keys(o)))].sort();
      const ctr = ind.target === 50 ? 50 : 0;   // PMI는 50을 가운데로
      // 색 기준: 90% 위치 값(휘발유처럼 튀는 한 항목 때문에 나머지가 다 흐려지지 않게)
      const av = Object.values(hm.items).flatMap(o => Object.values(o).map(v => Math.abs(v - ctr))).sort((a, b) => a - b);
      const mx = av.length ? av[Math.min(av.length - 1, Math.floor(av.length * 0.9))] : 1;
      h += `<h2>🌡️ ${n ? "" : "세부 항목 히트맵 "}<small>${esc(hm.label)} · 진할수록 강해요</small></h2><div class="panel heat"><table style="min-width:${120 + im.length * 52}px"><tr><th class="l">항목</th>${im.map(m => `<th>${ym(m)}</th>`).join("")}</tr>
        ${Object.entries(hm.items).map(([k, o]) => `<tr><th class="l">${esc(k)}</th>${im.map(m => o[m] == null ? "<td></td>" : `<td style="background:${heatColor(o[m] - ctr, mx)}">${o[m]}</td>`).join("")}</tr>`).join("")}</table></div>`;
    });
    if(S.length){
      const tm = months.slice(-13).reverse();
      h += `<h2>🧾 월별 수치</h2><div class="panel tw"><table class="hist"><tr><th>기간</th>${S.map(([, s]) => `<th>${esc(s.label)}</th>`).join("")}</tr>
        ${tm.map(m => `<tr><td>${m}</td>${S.map(([, s]) => `<td>${s.data[m] == null ? "-" : fmt(s.data[m], s.unit)}</td>`).join("")}</tr>`).join("")}</table></div>`;
    }
    root().innerHTML = h;
    bindNav();
    if(S.length) charts.push(lineChart(document.getElementById("ec-c1"), months, main.map(x => x[1]), ind.target, (main[0] || mom[0])[1].unit));
    const c2 = document.getElementById("ec-c2");
    if(mom.length && c2){ const mm = months.slice(-13); charts.push(barChart(c2, mm.map(ym), mm.map(m => mom[0][1].data[m] ?? null), "%", false, mom[0][1].label)); }
  }

  // ---------- 묶음: 두 기관 나란히 + 종합 해석 + 기관별 해석 ----------
  function group(gid){
    const g = G().find(x => x.id === gid); if(!g){ home(); return; }
    const ms = g.members.map(id => B.indicators.find(i => i.id === id)).filter(Boolean), sg = groupSignal(g, ms), reps = R();
    const rl = rr => `<div class="panel rlist">${rr.map(r => `<a href="#" data-go="r:${esc(r.id)}"><div class="dt"><b>${esc((r.release || "").slice(5).replace("-", "/"))}</b>발표</div>
      <div><div class="t">${esc(r.period || "")}</div><div class="c">${esc(r.conclusion || "")}</div></div></a>`).join("")}</div>`;
    const box = ind => { const s = primary(ind), l = s ? last(s, 2) : [], isg = signal(ind);
      const v = l.length ? l[l.length - 1] : null, d = l.length > 1 ? v[1] - l[0][1] : null;
      return `<div class="panel cbox ${/-spg-/.test(ind.id) ? "spg" : ""}"><div class="h"><span class="tg">${esc(SHORT(ind.id))}</span>${isg ? `<span class="sig ${isg.c}">${esc(isg.t)}</span>` : ""}</div>
        <div class="nm">${esc(ind.name)}</div>
        ${v ? `<div class="v"><b>${fmt(v[1], s.unit)}</b>${d != null ? `<em class="${udc(d)}">${arrow(d)} ${Math.abs(d).toFixed(1)}</em>` : ""}<small>${esc(s.label)} · ${ym(v[0])}</small></div>` : `<div class="v"><b class="na">아직 자료 없음</b></div>`}
        ${ind.summary ? `<p class="sm">${esc(ind.summary)}</p>` : ""}
        <div class="ft">${ind.next_release ? `<span>다음 발표 <b>${esc(ind.next_release)}</b></span>` : "<span></span>"}<a href="#" data-go="i:${ind.id}">자세히 보기 →</a></div></div>`; };
    const S = ms.map(i => [i, primary(i)]).filter(x => x[1]);
    const months = [...new Set(S.flatMap(([, s]) => Object.keys(s.data)))].sort().slice(-36);
    const cr = reps.filter(r => r.indicator === gid);
    root().innerHTML = `<div class="crumb"><a href="#" data-go="h">경제지표 홈</a> › ${CTY[g.country] || ""}</div>
      <div class="ihead"><div><h1>🧩 ${esc(g.name)} ${sg ? `<span class="sig ${sg.c}" style="font-size:13px;vertical-align:4px">${esc(sg.t)}</span>` : ""}</h1>
        <div class="meta">${esc(g.desc)}</div>
        ${g.summary ? `<div class="concl" style="margin-top:10px"><small>최근 종합 해석 한 줄</small>${esc(g.summary)}</div>` : ""}</div></div>
      <div class="cmp">${ms.map(box).join("")}</div>
      ${S.length ? `<div class="chartbox" style="margin-top:16px"><h3>📈 두 기관 헤드라인 PMI 추세 (50 위면 확장)</h3><div class="cv"><canvas id="ec-g1"></canvas></div></div>` : ""}
      <h2>🧩 종합 해석 <small>${cr.length}건 · ${esc(ms.map(i => SHORT(i.id)).join(" vs "))}</small></h2>
      ${cr.length ? rl(cr) : `<div class="empty">두 기관 해석이 같은 달로 모두 나오면 종합 해석이 여기 올라와요.</div>`}
      <div class="cols">${ms.map(ind => { const rr = reps.filter(r => r.indicator === ind.id);
        return `<div><h2>📝 ${esc(SHORT(ind.id))} 해석 <small>${rr.length}건</small></h2>${rr.length ? rl(rr) : `<div class="empty">아직 해석이 없어요. 발표 자료가 나오면 히르찬이 해석을 올려요.</div>`}</div>`; }).join("")}</div>
      <p class="foot">숫자는 발표 원문 그대로이며, 계산·추정값은 따로 표시해요. 투자 권유가 아닌 공부용 해석이에요.</p>`;
    bindNav();
    if(S.length) charts.push(lineChart(document.getElementById("ec-g1"), months, S.map(([i, s]) => Object.assign({}, s, {label: `${SHORT(i.id)} ${s.label}`})), 50, S[0][1].unit));
  }

  // ---------- 해석 글 ----------
  function renderMd(src, el){
    const specs = [], briefs = [];
    let body = src.replace(/```chart\s*\n([\s\S]*?)```/g, (_, x) => { specs.push(x); return `<div class="chartbox" data-c="${specs.length - 1}"><h3></h3><div class="cv"><canvas></canvas></div><div class="src"></div></div>`; })
                  .replace(/```briefing\s*\n([\s\S]*?)```/g, (_, x) => { briefs.push(x.trim()); return `<div class="brief" data-b="${briefs.length - 1}"><div class="bh">💬 카톡 브리핑용 요약 <button type="button">복사</button></div><pre></pre></div>`; })
                  .replace(/<!--\s*extra:\s*(.+?)\s*-->/g, () => `\n<div class="xmark"></div>\n\n`);
    body = body.replace(/~/g, "&#126;").replace(/\*\*([^*\n]+?)\*\*/g, "<strong>$1</strong>");   // 한국어: 물결표 취소선·한글 붙은 굵게 보정
    el.innerHTML = marked.parse(body);
    el.querySelectorAll("[data-c]").forEach(box => {
      let sp; try{ sp = JSON.parse(specs[+box.dataset.c]); }catch(e){ box.innerHTML = "<p class='muted'>그래프 설정을 읽지 못했어요.</p>"; return; }
      box.querySelector("h3").textContent = sp.title || "";
      box.querySelector(".src").textContent = sp.source ? "출처: " + sp.source : "";
      if(sp.height) box.querySelector(".cv").style.height = sp.height + "px";
      const cv = box.querySelector("canvas");
      if(sp.type === "bar"){
        if(sp.horizontal && !sp.height) box.querySelector(".cv").style.height = Math.max(280, sp.labels.length * 26 + 60) + "px";
        charts.push(barChart(cv, sp.labels, sp.datasets[0].data, sp.unit, sp.horizontal, sp.datasets[0].label, sp.datasets.length > 1 ? sp.datasets : null));
      }
      else { const months = sp.labels, sets = sp.datasets.map(d => ({label: d.label, data: Object.fromEntries(months.map((mm, i) => [mm, d.data[i]]))}));
        charts.push(lineChart(cv, months, sets, sp.target, sp.unit)); }
    });
    el.querySelectorAll("[data-b]").forEach(box => {
      const t = briefs[+box.dataset.b]; box.querySelector("pre").textContent = t;
      box.querySelector("button").onclick = e => navigator.clipboard.writeText(t).then(() => { e.target.textContent = "✅ 복사됨"; setTimeout(() => e.target.textContent = "복사", 1500); });
    });
  }
  function takeNeeds(body){
    const items = [];
    body = body.replace(/```needs\s*\n([\s\S]*?)```\s*/g, (_, x) => {
      x.split("\n").forEach(l => { const m = l.match(/^\s*[-*]\s*\[( |x|X)\]\s*(.+)$/); if(m) items.push({done: m[1] !== " ", text: m[2].trim()}); });
      return "";
    });
    return {items, body};
  }
  function needsBox(items){
    if(!items.length) return "";
    const n = items.filter(x => x.done).length;
    const line = t => {
      const L = [];                                // [이름](주소) → 자료 받는 곳 버튼
      t = t.replace(/\s*🔗?\s*\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)\s*·?/gu, (_, n, u) => { L.push([n, u]); return " "; });
      const [a, ...b] = t.split(/\s+[—–-]\s+/).map(s => s.replace(/^[—–-]\s*/, "").trim()).filter(Boolean);
      const links = L.length ? `<span class="nl">${L.map(([n, u]) => `<a href="${esc(u)}" target="_blank" rel="noopener">🔗 ${esc(n)}</a>`).join("")}</span>` : "";
      return (b.length ? `<b>${esc(a)}</b> — ${esc(b.join(" — "))}` : `<b>${esc(a || "")}</b>`) + links;
    };
    return `<div class="needs"><div class="nh"><span>📎 더 깊게 보려면 필요한 자료 <small>${items.length}개 중 ${n}개 확인</small></span></div>
      <ol>${items.map((x, i) => `<li class="${x.done ? "done" : ""}"><span class="no">${i + 1})</span><span>${x.done ? "✅ " : ""}${line(x.text)}</span></li>`).join("")}</ol>
      <p class="nf">이 자료가 확인되면 맨 아래 '추가 자료로 본 추가 해석'이 붙어요.</p></div>`;
  }
  function report(id){
    const r = B.reports.find(x => x.meta.id === id); if(!r){ home(); return; }
    const m = r.meta, grp = G().find(g => g.id === m.indicator), ind = B.indicators.find(i => i.id === m.indicator) || {id: m.indicator, name: nameOf(m.indicator), agency: ""};
    const pg = grp ? null : groupOf(m.indicator);
    const {items, body} = takeNeeds(r.body);
    root().innerHTML = `<div class="crumb"><a href="#" data-go="h">경제지표 홈</a> › ${grp ? `<a href="#" data-go="g:${esc(grp.id)}">🧩 ${esc(grp.name)}</a>`
        : `${pg ? `<a href="#" data-go="g:${esc(pg.id)}">🧩 ${esc(pg.name)}</a> › ` : ""}<a href="#" data-go="i:${esc(m.indicator)}">${esc(ind.name)}</a>`}</div>
      <div class="rhead"><div class="tg">${grp ? `🧩 종합 해석 · ${esc(grp.members.map(SHORT).join(" vs "))}` : esc(ind.name)} · ${esc(m.agency || ind.agency || "")}</div><h1>${esc(m.title || (ind.name + " " + (m.period || "")))}</h1>
        <div class="mt"><span>기준 <b>${esc(m.period || "-")}</b></span><span>발표 <b>${esc(m.release || "-")}</b></span><span>다음 발표 <b>${esc(m.next || "-")}</b></span></div></div>
      ${m.conclusion ? `<div class="concl"><small>한 줄 결론</small>${esc(m.conclusion)}</div>` : ""}
      <div id="ec-brief"></div>
      ${needsBox(items)}
      <div class="md" id="ec-main"></div>
      ${r.extra ? `<h2>🔎 추가 자료로 본 추가 해석</h2><div class="md xmd" id="ec-extra"></div>` : ""}
      <h2>💬 이 해석에 질문하기 <small>해석 글과 최근 뉴스로 AI가 답해요 · 회원 전용</small></h2>
      <div class="panel qa"><div id="ec-qa"></div>
        <form id="ec-qa-f"><textarea id="ec-qa-q" rows="3" maxlength="600" placeholder="예: 운송 서비스 가격이 오른 건 유가 때문이고, 식품은 관세 때문인가요?"></textarea>
          <div class="qa-row"><small class="muted">앞서 물어본 것을 이어서 기억해요(이 화면에 있는 동안)</small><button type="submit">질문하기</button></div></form></div>
      <p class="foot">숫자는 발표 원문 그대로이며, 계산·추정값은 따로 표시해요. 투자 권유가 아닌 공부용 해석이에요.</p>`;
    renderMd(body, document.getElementById("ec-main"));
    if(r.extra) renderMd(r.extra, document.getElementById("ec-extra"));
    bindNav();
    bindAsk(id);
    briefsReport(id);
  }

  // 👑 리서치 보고서 PDF — 관리자에게만 보임(/api/econ/briefs가 관리자 아니면 403). 보고서는 bundle.json에 넣지 않음
  async function adminBriefs(){
    try{ const r = await fetch("/api/econ/briefs", {cache: "no-store"}); return r.ok ? (await r.json()).items || [] : null; }catch(e){ return null; }
  }
  const pdfUrl = id => "/api/econ/brief_pdf?id=" + encodeURIComponent(id);
  const stCls = s => /긍정/.test(s || "") ? "pos" : /부정/.test(s || "") ? "neg" : /혼재/.test(s || "") ? "mix" : "";
  async function briefsHome(){
    const L = await adminBriefs(); const top = document.getElementById("ec-bslot");
    if(!L || cur[0] !== "h" || !top) return;
    const hub = root().querySelector(".ec-hub");
    if(hub){ hub.insertAdjacentHTML("beforeend", `<a class="adm" href="#" data-go="o"><b>👑 기타 보고서</b><span>다른 기관 자료 분석 · 관리자 전용</span></a>
      <a class="adm" href="#" data-go="hr"><b>👑 히르찬 매크로 리서치</b><span>리포트 PDF 보기·받기 · 관리자 전용</span></a>`); bindNav(); }
    const W = L.filter(b => b.kind === "weekly"), I = L.filter(b => b.kind === "report" || b.kind === "other");
    const row = b => `<a class="ec-brow" href="${pdfUrl(b.id)}"><b>${esc(b.kind === "weekly" ? `${(b.start || "").slice(5).replace("-", "/")}~${(b.end || "").slice(5).replace("-", "/")}` : `${b.name || nameOf(b.indicator)} · ${b.period || ""}`)}</b>
      <span>${esc(b.conclusion || b.title || "")}</span>${b.stance ? `<i class="ec-st ${stCls(b.stance)}">${esc(b.stance)}</i>` : ""}<em>⬇ PDF</em></a>`;
    top.insertAdjacentHTML("afterend", `<div class="panel ec-briefs"><h2 style="margin-top:0">👑 매크로 리서치 보고서 <small>관리자에게만 보여요 · 누르면 PDF를 받아요</small></h2>
      ${L.length ? `<div class="ec-bcols"><div><h3>주간 종합</h3>${W.length ? W.map(row).join("") : `<p class="muted">아직 없어요.</p>`}</div>
        <div><h3>지표·기관 자료 보고서</h3>${I.length ? I.slice(0, 12).map(row).join("") : `<p class="muted">아직 없어요.</p>`}</div></div>`
      : `<p class="muted" style="margin:0">아직 올라온 보고서가 없어요. 맥의 경제지표 노트에서 만들고 사이트에 반영하면 여기 생겨요.</p>`}</div>`);
  }
  async function briefsReport(id){
    const L = await adminBriefs(); const box = document.getElementById("ec-brief");
    if(!L || cur[1] !== id || !box) return;
    const b = L.find(x => x.rid === id);
    box.innerHTML = b ? `<a class="ec-bbtn" href="${pdfUrl(b.id)}">👑 리서치 보고서 PDF 받기 <small>${esc(b.title || "")}${b.made ? ` · ${esc(b.made)} 작성` : ""} · 관리자 전용</small></a>`
      : `<div class="ec-bbtn none">👑 이 해석의 리서치 보고서는 아직 없어요 <small>맥의 경제지표 노트에서 만들 수 있어요 · 관리자에게만 보여요</small></div>`;
  }

  // ---------- 🏛️ 연준 인사 발언 (회원 보기 · bundle.json의 fed) ----------
  // 위치 점수: 1 = 가장 매파 🦅, 50 = 중립, 100 = 가장 비둘기 🕊️ (원본 화면: 경제지표 노트 fed.js)
  const HAWK = "#c2410c", DOVE = "#1c7ed6", VOTER = "#2b8a3e";
  const fedLabel = s => s == null ? "-" : s <= 15 ? "강한 매파" : s <= 30 ? "매파" : s <= 45 ? "약한 매파" : s <= 54 ? "중립" : s <= 69 ? "약한 비둘기" : s <= 85 ? "비둘기" : "강한 비둘기";
  const fedColor = s => s == null ? "#7b8392" : s < 46 ? HAWK : s > 54 ? DOVE : "#4a515c";
  const FP = () => ((B.fed || {}).people || {}).people || [];
  const FS = () => (B.fed || {}).speeches || [];
  const fedPerson = id => FP().find(p => p.id === id);
  const fedName = id => (fedPerson(id) || {}).name || id;
  const CHG = {"처음": "new", "새로": "new", "유지": "keep", "강화": "up", "완화": "down", "바뀜": "turn", "언급 없음": "none"};
  function fedScale(list, big){
    const ps = list.filter(p => p.score != null).slice().sort((a, b) => a.score - b.score);
    const rows = [], pos = ps.map(p => {
      const x = (Math.min(100, Math.max(1, p.score)) - 1) / 99 * 100;
      let r = rows.findIndex(last => x - last >= 11); if(r < 0){ r = rows.length; rows.push(-99); }
      rows[r] = x; return {p, x, r};
    });
    const nr = Math.max(1, rows.length);
    return `<div class="fscale${big ? " big" : ""}">
      <div class="fs-end hawk"><span class="ico">🦅</span><b>1</b><small>매파</small></div>
      <div class="fs-mid"><div class="fs-tags" style="height:${nr * 30 + 6}px">${pos.map(({p, x, r}) =>
          `<a class="fs-tag" href="#" data-go="fp:${esc(p.id)}" style="left:${x}%;bottom:${r * 30}px;--c:${p.voter ? VOTER : fedColor(p.score)}" title="${esc(p.name)} · ${p.score} · ${fedLabel(p.score)}${p.voter ? " · 투표권" : ""}">${esc(p.name)} <b>${p.score}</b></a>`).join("")}</div>
        <div class="fs-track">${pos.map(({p, x}) => `<i style="left:${x}%;--c:${p.voter ? VOTER : fedColor(p.score)}"></i>`).join("")}</div>
        <div class="fs-ticks"><span style="left:0">1</span><span style="left:25%">25</span><span style="left:50%">50 중립</span><span style="left:75%">75</span><span style="left:100%">100</span></div></div>
      <div class="fs-end dove"><span class="ico">🕊️</span><b>100</b><small>비둘기</small></div></div>`;
  }
  function fedWho(ids){
    return (ids || []).map(id => { const p = fedPerson(id);
      return `<a class="fo-who" href="#" data-go="fp:${esc(id)}" style="--c:${fedColor(p && p.score)}" title="${esc(p ? `${p.name} · ${p.score} · ${fedLabel(p.score)}` : id)}">${esc(p ? p.name.split(" ").pop() : id)}</a>`; }).join("");
  }
  function fedOverview(){
    const O = (B.fed || {}).overview; if(!O || !(O.common || []).length) return "";
    return `<div class="panel fo"><h2 style="margin-top:0">🧭 지금까지 발언 종합 <small>${esc(O.basis || "")}${O.updated ? ` · ${esc(O.updated)} 고침` : ""}</small></h2>
      ${O.headline ? `<div class="fo-head">${esc(O.headline)}</div>` : ""}
      <h3>🤝 공통된 점</h3><div class="fo-grid">${O.common.map(c => `<div class="fo-item"><b>${esc(c.title)}</b><p>${esc(c.text || "")}</p><div class="fo-ws">${fedWho(c.who)}</div></div>`).join("")}</div>
      <h3>↔️ 다르게 보는 점</h3><div class="fo-grid">${(O.differ || []).map(d => `<div class="fo-item"><b>${esc(d.title)}</b>${(d.sides || []).map(x => `<div class="fo-side">
          <div class="fo-sh"><span class="fo-lb">${esc(x.label || "")}</span>${fedWho(x.who)}</div><p>${esc(x.text || "")}</p></div>`).join("")}</div>`).join("")}</div>
      ${(O.other || []).length ? `<h3>💬 따로 나온 이야기 <small class="muted">큰 줄기(금리·물가)와 다른 주제를 한 사람만 꺼낸 것</small></h3><div class="fo-other">${O.other.map(o => `<div class="fo-o">
        <div class="fo-sh">${fedWho([o.who])}${o.tag ? `<span class="fo-tag">${esc(o.tag)}</span>` : ""}</div><b>${esc(o.title)}</b><p>${esc(o.text || "")}</p>
        ${o.speech ? `<a class="fo-more" href="#" data-go="fs:${esc(o.speech)}">발언 보기 →</a>` : ""}</div>`).join("")}</div>` : ""}
      <p class="fs-note">이름을 누르면 그 인사의 기록으로 가요(색: 🦅 매파 주황 · 🕊️ 비둘기 파랑).</p></div>`;
  }
  function fedDelta(p){
    const h = p.history || []; if(h.length < 2) return "";
    const d = h[h.length - 1].score - h[h.length - 2].score; if(!d) return `<span class="fd keep">지난번과 같음</span>`;
    return `<span class="fd ${d < 0 ? "hawk" : "dove"}">${d < 0 ? "🦅 매파 쪽으로 " : "🕊️ 비둘기 쪽으로 "}${Math.abs(d)}</span>`;
  }
  function fedRow(s){
    const m = s.meta;
    return `<a href="#" data-go="fs:${esc(m.id)}"><div class="dt"><b>${esc((m.date || "").slice(5).replace("-", "/"))}</b>${esc((m.date || "").slice(0, 4))}</div>
      <div><div class="t">${(m.persons || []).map(fedName).map(esc).join(" · ")}${m.event ? ` · ${esc(m.event)}` : ""}</div><div class="c">${esc(m.title || "")}</div></div></a>`;
  }
  // 🧭 FOMC 종합 온도계: 인사별 위치 점수를 가중 평균(의장 ×3 · 투표권 ×2 · 그 외 ×1), 왼쪽 🦅 매파 ↔ 오른쪽 🕊️ 비둘기
  const FG_BANDS = [[1, 15, "#c2410c"], [15, 30, "#ea7a3c"], [30, 45, "#f5b183"], [45, 55, "#adb5bd"], [55, 70, "#8ec5f0"], [70, 85, "#4aa3e8"], [85, 100, "#1c7ed6"]];
  const fgW = p => /의장/.test(p.role || "") && !/부의장|전 의장/.test(p.role || "") ? 3 : p.voter ? 2 : 1;
  function fgAt(P, day){   // day(YYYY-MM-DD)까지 나온 마지막 점수로 계산 · day 없으면 지금
    let s = 0, w = 0, n = 0;
    P.forEach(p => { const h = (p.history || []).filter(x => x.score != null && (!day || x.date <= day));
      const v = day ? (h.length ? h[h.length - 1].score : null) : p.score; if(v == null) return;
      s += v * fgW(p); w += fgW(p); n++; });
    return n >= 5 ? {score: s / w, n} : null;   // 5명 미만이면 비워 둠
  }
  function fgDay(days){ const d = new Date(Date.now() - days * 864e5); return d.toISOString().slice(0, 10); }
  function fedGauge(P){
    const now = fgAt(P); if(!now) return "";
    const avg = L => L.length ? L.reduce((a, p) => a + p.score, 0) / L.length : null;
    const PS = P.filter(p => p.score != null), vAvg = avg(PS.filter(p => p.voter)), aAvg = avg(PS);
    const R = 120, sw = 26, pad = sw / 2 + 20, W = 2 * (R + pad), cx = W / 2, cy = R + pad;
    const pt = (s, r) => { const a = Math.PI * (1 - (s - 1) / 99); return [cx + r * Math.cos(a), cy - r * Math.sin(a)]; };
    const arc = (a, b, col) => { const [x1, y1] = pt(a, R), [x2, y2] = pt(b, R); return `<path d="M${x1.toFixed(1)} ${y1.toFixed(1)} A${R} ${R} 0 0 1 ${x2.toFixed(1)} ${y2.toFixed(1)}" stroke="${col}" stroke-width="${sw}" fill="none"/>`; };
    const s = Math.max(1, Math.min(100, now.score)), [nx, ny] = pt(s, R - sw / 2 - 6);
    const ticks = [1, 25, 50, 75, 100].map(t => { const [x, y] = pt(t, R + sw / 2 + 9); return `<text x="${x.toFixed(1)}" y="${(y + 3).toFixed(1)}" font-size="11" fill="#9aa1ab" text-anchor="middle">${t}</text>`; }).join("");
    const svg = `<svg viewBox="0 0 ${W} ${cy + 12}" width="100%" style="max-width:320px">${FG_BANDS.map(g => arc(g[0] + 0.5, g[1] - 0.5, g[2])).join("")}${ticks}
      <line x1="${cx}" y1="${cy}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}" stroke="#1d2433" stroke-width="4" stroke-linecap="round"/><circle cx="${cx}" cy="${cy}" r="8" fill="#1d2433"/></svg>`;
    const H = [["1주 전", 7], ["2주 전", 14], ["1달 전", 30]].map(([k, d]) => { const x = fgAt(P, fgDay(d)); return `<span>${k} <b>${x ? Math.round(x.score) : "-"}</b></span>`; }).join("");
    const wk = fgAt(P, fgDay(7)), dd = wk ? now.score - wk.score : null;
    const mv = dd == null ? "" : Math.abs(dd) < 1 ? "1주 전과 거의 같아요." : `1주 전보다 ${dd < 0 ? "🦅 매파 쪽으로" : "🕊️ 비둘기 쪽으로"} ${Math.abs(dd).toFixed(1)} 움직였어요.`;
    const ext = PS.slice().sort((a, b) => a.score - b.score), nm = p => `${esc(p.name)} ${p.score}`;
    return `<div class="panel ai-gp fg"><div class="lab">🧭 FOMC 종합 온도계 <small>왼쪽 🦅 매파 · 오른쪽 🕊️ 비둘기 — 인사별 위치 점수를 하나로 모은 것</small></div>
      <div class="ai-gwrap"><div class="ai-g big"><div class="t">종합 (${now.n}명)</div>${svg}
        <div class="n" style="color:${fedColor(s)}">${Math.round(s)}<small>${fedLabel(Math.round(s))}</small></div><div class="h">${H}</div></div>
        <div class="fg-side"><div class="fg-row"><span>🗳️ 투표권자 평균</span><b style="color:${fedColor(vAvg)}">${vAvg == null ? "-" : `${vAvg.toFixed(1)} · ${fedLabel(Math.round(vAvg))}`}</b></div>
          <div class="fg-row"><span>👥 전체 단순 평균</span><b style="color:${fedColor(aAvg)}">${aAvg == null ? "-" : `${aAvg.toFixed(1)} · ${fedLabel(Math.round(aAvg))}`}</b></div>
          <div class="fg-row"><span>🦅 가장 매파</span><b>${ext.slice(0, 2).map(nm).join(" · ")}</b></div>
          <div class="fg-row"><span>🕊️ 가장 비둘기 쪽</span><b>${ext.slice(-2).reverse().map(nm).join(" · ")}</b></div>
          ${mv ? `<p class="fg-mv">${mv}</p>` : ""}</div></div>
      <p class="muted" style="font-size:12px;margin:8px 0 0">계산법: 발언을 정리한 인사의 지금 위치 점수(1 매파 ~ 100 비둘기)를 가중 평균 — 의장 ×3 · 2026년 투표권자 ×2 · 그 외 ×1. 지난 값은 그날까지 나온 마지막 점수로 다시 계산(5명 미만이면 '-'). 1~15 강한 매파 · 16~30 매파 · 31~45 약한 매파 · 46~54 중립 · 55~69 약한 비둘기 · 70~85 비둘기 · 86~100 강한 비둘기 — 히르찬의 판단 기준(공식 지표 아님).</p></div>`;
  }

  // 📂 접기 상태는 브라우저에 기억(처음엔 펼침)
  function foldOpen(k){ try{ return localStorage.getItem("econ:fold:" + k) !== "0"; }catch(e){ return true; } }
  // 📈 종합 온도계 타임라인: 발언이 있던 날마다 그날까지의 마지막 점수로 종합·투표권자·전체 평균을 다시 계산
  function fgAvgAt(P, day, f){   // 단순 평균(f로 거른 인사만)
  const L = P.filter(f || (() => true)).map(p => { const h = (p.history || []).filter(x => x.score != null && x.date <= day); return h.length ? h[h.length - 1].score : null; }).filter(v => v != null);
  return L.length ? L.reduce((a, b) => a + b, 0) / L.length : null;
}
  function fgSeries(P){
  const days = [...new Set(P.flatMap(p => (p.history || []).filter(x => x.score != null).map(x => x.date)))].sort();
  let prev = null;
  return days.map(d => {
    const w = (() => { let s = 0, ww = 0, n = 0; P.forEach(p => { const h = (p.history || []).filter(x => x.score != null && x.date <= d); if(!h.length) return; s += h[h.length - 1].score * fgW(p); ww += fgW(p); n++; }); return n ? {score: s / ww, n} : null; })();
    const ev = []; P.forEach(p => { const h = (p.history || []).filter(x => x.score != null); h.forEach((x, i) => { if(x.date !== d) return;
      const b = i ? h[i - 1].score : null; ev.push({p, from: b, to: x.score, speech: x.speech, why: x.why}); }); });
    const r = {d, all: w && w.score, n: w ? w.n : 0, ok: w && w.n >= 5, voter: fgAvgAt(P, d, p => p.voter), simple: fgAvgAt(P, d), ev, dd: prev && w ? w.score - prev : null};
    prev = w ? w.score : prev; return r;
  });
}
  let FG_PICK = "";
  function fedTimeline(P){
  const S = fgSeries(P); if(S.filter(x => x.ok).length < 2) return "";
  return `<details class="panel fold fg-tl" data-fold="fedtl"${foldOpen("fedtl") ? " open" : ""}><summary><h2 style="margin:0">📈 온도계 타임라인 <small>발언이 나온 날마다 다시 계산 · 위로 갈수록 🕊️ 비둘기, 아래로 갈수록 🦅 매파</small></h2></summary>
      <div class="fg-top"><label class="fg-pick">인사 겹쳐 보기 <select id="fgpick"><option value="">없음</option>${P.filter(p => p.score != null).sort((a, b) => a.score - b.score).map(p => `<option value="${esc(p.id)}"${FG_PICK === p.id ? " selected" : ""}>${esc(p.name)} (${p.score})</option>`).join("")}</select></label></div>
    <div class="fg-svgw" id="fgsvg">${fgChart(P, S)}</div>
    <div class="fg-leg"><span><i style="background:#1d2433"></i>종합(의장 ×3 · 투표권 ×2)</span><span><i style="background:#2b8a3e"></i>투표권자 평균</span><span><i style="background:#9aa1ab"></i>전체 단순 평균</span><span><i class="pk"></i>고른 인사</span><span class="muted">반영 인사 5명이 모인 날부터 그림(앞의 날은 아래 목록에 참고로)</span></div>
    <details class="fg-evs"><summary>🗓️ 날짜별로 누가 움직였나 <small class="muted">${S.length}일 · 최신 순</small></summary>${S.slice().reverse().map(fgEvRow).join("")}</details></details>`;
}
  function fgEvRow(x){
  const dd = x.dd == null ? "" : Math.abs(x.dd) < 0.5 ? `<span class="fd keep">종합 거의 그대로</span>` : `<span class="fd ${x.dd < 0 ? "hawk" : "dove"}">종합 ${x.dd < 0 ? "🦅 매파 쪽으로" : "🕊️ 비둘기 쪽으로"} ${Math.abs(x.dd).toFixed(1)}</span>`;
  return `<div class="fg-ev"><div class="fg-evh"><b>${esc(x.d)}</b><span class="fg-val" style="color:${fedColor(x.all)}">${x.all == null ? "-" : Math.round(x.all)}${x.ok ? "" : " <small>(참고)</small>"}</span>${dd}<small class="muted">${x.n}명 반영</small></div>
    ${x.ev.map(e => `<div class="fg-evp"><a href="#" data-go="fp:${esc(e.p.id)}">${esc(e.p.name)}</a>${e.p.voter ? `<span class="fg-vt">투표권</span>` : ""}
      <span>${e.from == null ? `처음 <b style="color:${fedColor(e.to)}">${e.to}</b>` : `${e.from} → <b style="color:${fedColor(e.to)}">${e.to}</b>`}</span>
      ${e.from == null ? `<span class="fd keep">새로 들어옴</span>` : e.to === e.from ? `<span class="fd keep">같음</span>` : `<span class="fd ${e.to < e.from ? "hawk" : "dove"}">${e.to < e.from ? "🦅" : "🕊️"} ${Math.abs(e.to - e.from)}</span>`}
      ${e.speech ? `<a class="fg-sp" href="#" data-go="fs:${esc(e.speech)}">발언 →</a>` : ""}${e.why ? `<small>${esc(e.why)}</small>` : ""}</div>`).join("")}</div>`;
}
  function fgChart(P, S){
  const i0 = Math.max(0, S.findIndex(x => x.ok)); S = S.slice(i0);   // 5명 이상 모인 날부터 그림(앞 구간은 아래 목록에만)
  const W = 760, H = 280, L = 40, R = 16, T = 14, B = 30;
  const t = d => Date.parse(d + "T00:00:00Z"), t0 = t(S[0].d), t1 = Math.max(t(S[S.length - 1].d), t0 + 864e5);
  const pk = P.find(p => p.id === FG_PICK), pkA = pk ? (pk.history || []).filter(x => x.score != null) : [], pkB = pkA.filter(x => x.date < S[0].d).pop();
  const pkH = pkA.filter(x => x.date >= S[0].d); if(pkB && !(pkH[0] && pkH[0].date === S[0].d)) pkH.unshift({...pkB, date: S[0].d});   // 앞 구간의 마지막 점수를 첫날로 이어 붙임
  const vals = S.flatMap(x => [x.all, x.voter, x.simple]).concat(pkH.map(x => x.score)).filter(v => v != null);
  const lo = Math.max(1, Math.floor((Math.min(...vals) - 5) / 10) * 10), hi = Math.min(100, Math.max(55, Math.ceil((Math.max(...vals) + 5) / 10) * 10));
  const X = d => L + (t(d) - t0) / (t1 - t0) * (W - L - R), Y = v => T + (hi - v) / (hi - lo) * (H - T - B);
  const bands = FG_BANDS.map(([a, b, c]) => { const y1 = Y(Math.min(b, hi)), y2 = Y(Math.max(a, lo)); return y2 > y1 ? `<rect x="${L}" y="${y1.toFixed(1)}" width="${W - L - R}" height="${(y2 - y1).toFixed(1)}" fill="${c}" opacity=".13"/>` : ""; }).join("");
  const gy = []; for(let v = Math.ceil(lo / 10) * 10; v <= hi; v += 10) gy.push(`<line x1="${L}" x2="${W - R}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" stroke="#e3e6eb"${v === 50 ? ` stroke-dasharray="4 3" stroke="#9aa1ab"` : ""}/><text x="${L - 6}" y="${(Y(v) + 4).toFixed(1)}" font-size="11" fill="#9aa1ab" text-anchor="end">${v}</text>`);
  const gx = []; const dt = (t1 - t0) / 864e5, step = dt > 120 ? 30 : dt > 40 ? 7 : dt > 14 ? 3 : 1;
  for(let x = t0; x <= t1 + 1; x += step * 864e5){ const d = new Date(x).toISOString().slice(0, 10), xx = X(d); gx.push(`<line x1="${xx.toFixed(1)}" x2="${xx.toFixed(1)}" y1="${T}" y2="${H - B}" stroke="#f0f2f5"/><text x="${xx.toFixed(1)}" y="${H - B + 16}" font-size="11" fill="#9aa1ab" text-anchor="middle">${+d.slice(5, 7)}/${+d.slice(8)}</text>`); }
  const step2 = (pts) => pts.map((p, i) => i ? `H${p[0].toFixed(1)}V${p[1].toFixed(1)}` : `M${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join("");   // 계단(다음 발언 전까지 그대로)
  const line = (k, col, wd, dash) => { const all = S.filter(x => x[k] != null), ok = all.filter(x => x.ok);
    const a = all.length ? `<path d="${step2(all.map(x => [X(x.d), Y(x[k])]))}" stroke="${col}" stroke-width="${wd}" fill="none" opacity=".3"${dash ? ` stroke-dasharray="${dash}"` : ""}/>` : "";
    const b = ok.length ? `<path d="${step2(ok.map(x => [X(x.d), Y(x[k])]))}" stroke="${col}" stroke-width="${wd}" fill="none"${dash ? ` stroke-dasharray="${dash}"` : ""}/>` : "";
    return a + b; };
  const pkl = pkH.length ? `<path d="${step2(pkH.map(x => [X(x.date), Y(x.score)]).concat([[X(S[S.length - 1].d), Y(pkH[pkH.length - 1].score)]]))}" stroke="#7048e8" stroke-width="2" fill="none"/>` + pkH.map(x => `<circle cx="${X(x.date).toFixed(1)}" cy="${Y(x.score).toFixed(1)}" r="4" fill="#7048e8"><title>${esc(pk.name)} ${x.date}: ${x.score}${x.why ? " — " + esc(x.why) : ""}</title></circle>`).join("") : "";
  const dots = S.map(x => x.all == null ? "" : `<circle cx="${X(x.d).toFixed(1)}" cy="${Y(x.all).toFixed(1)}" r="${x.ok ? 5 : 3.5}" fill="${x.ok ? fedColor(x.all) : "#fff"}" stroke="#1d2433" stroke-width="1.5"${x.ok ? "" : ` opacity=".5"`}><title>${x.d} 종합 ${x.all.toFixed(1)} (${x.n}명)${x.dd != null ? ` · ${x.dd < 0 ? "매파 쪽" : "비둘기 쪽"} ${Math.abs(x.dd).toFixed(1)}` : ""}\n${x.ev.map(e => `${e.p.name} ${e.from == null ? "처음 " + e.to : e.from + "→" + e.to}`).join("\n")}</title></circle>`).join("");
  const last = S[S.length - 1];
  return `<svg viewBox="0 0 ${W} ${H}" class="fg-svg">${bands}${gy.join("")}${gx.join("")}
    <text x="${L + 6}" y="${T + 12}" font-size="11" fill="#1c7ed6" font-weight="700">🕊️ 비둘기</text><text x="${L + 6}" y="${H - B - 6}" font-size="11" fill="#c2410c" font-weight="700">🦅 매파</text>
    ${line("simple", "#9aa1ab", 1.8)}${line("voter", "#2b8a3e", 2, "6 4")}${line("all", "#1d2433", 3)}${pkl}${dots}
    <text x="${(X(last.d) - 6).toFixed(1)}" y="${(Y(last.all) - 10).toFixed(1)}" font-size="12.5" font-weight="900" fill="#1d2433" text-anchor="end">${Math.round(last.all)}</text></svg>`;
}

  function fedHome(){
    const P = FP(), S = FS(), PS = P.filter(p => p.score != null);
    root().innerHTML = `<h1>🏛️ 연준 인사 발언 모음</h1>
      <p class="muted" style="margin:0 0 16px">연준 인사의 연설·인터뷰를 히르찬이 정리해요. 지난 발언과 무엇이 달라졌는지, 매파·비둘기 위치가 어디쯤인지 발언마다 이어서 고쳐요.</p>
      ${fedGauge(P)}
      ${fedTimeline(P)}
      <div class="panel"><div class="fs-head"><h2 style="margin:0">🦅 매파 ↔ 비둘기 🕊️ 위치 <small>${PS.length ? `${PS.length}명 · 이름을 누르면 변화 기록` : ""}</small></h2>
        ${P.some(p => p.voter) ? `<span class="fs-legend"><i></i>초록색: 2026년 FOMC 투표권 (${PS.filter(p => p.voter).length}명 · 전체 ${P.filter(p => p.voter).length}명)</span>` : ""}</div>
        ${PS.length ? fedScale(PS, true) : `<div class="empty">아직 정리한 발언이 없어요.</div>`}
        <p class="fs-note">1에 가까울수록 매파(금리를 높게·오래 두자), 100에 가까울수록 비둘기(금리를 내리자), 50은 중립이에요.</p></div>
      ${fedOverview()}
      ${P.length ? `<h2>👤 인사별 지금 위치 <small>점수가 낮을수록 매파</small></h2><div class="fgrid">${P.slice().sort((a, b) =>
        (a.score == null) - (b.score == null) || (a.score ?? 0) - (b.score ?? 0) || (b.voter ? 1 : 0) - (a.voter ? 1 : 0)).map(p => p.score == null ? `
        <a class="card fcard none" href="#" data-go="fp:${esc(p.id)}"><div class="fc-h"><b>${esc(p.name)}</b>${p.voter ? `<span class="vt">투표권</span>` : ""}</div>
          <div class="ds">${esc(p.role || "")}</div><div class="fc-s">아직 발언 없음</div><div class="fc-bar"></div></a>` : `
        <a class="card fcard" href="#" data-go="fp:${esc(p.id)}"><div class="fc-h"><b>${esc(p.name)}</b>${p.voter ? `<span class="vt">투표권</span>` : ""}</div>
          <div class="ds">${esc(p.role || "")}${p.last ? ` · 마지막 발언 ${esc(p.last)}` : ""}</div>
          <div class="fc-s" style="color:${fedColor(p.score)}"><b>${p.score ?? "-"}</b> ${fedLabel(p.score)} ${fedDelta(p)}</div>
          <div class="fc-bar"><i style="left:${((p.score ?? 50) - 1) / 99 * 100}%;--c:${fedColor(p.score)}"></i></div>
          <div class="fc-t">${esc(p.summary || "")}</div></a>`).join("")}</div>` : ""}
      ${S.length ? `<details class="panel fold fed-recent" data-fold="fedrecent"${foldOpen("fedrecent") ? " open" : ""}><summary><h2 style="margin:0">🗂️ 최근 정리한 발언 <small>${S.length}건</small></h2></summary><div class="rlist">${S.slice(0, 20).map(fedRow).join("")}</div></details>` : ""}`;
    bindNav();
    root().querySelectorAll("details.fold").forEach(d => d.addEventListener("toggle", () => { try{ localStorage.setItem("econ:fold:" + d.dataset.fold, d.open ? "1" : "0"); }catch(e){} }));
    const fgEnd = () => { const w = root().querySelector("#fgsvg"); if(w) w.scrollLeft = w.scrollWidth; };   // 휴대폰: 최신 날짜부터 보이게
    const fp = root().querySelector("#fgpick"); if(fp) fp.onchange = () => { FG_PICK = fp.value; root().querySelector("#fgsvg").innerHTML = fgChart(P, fgSeries(P)); fgEnd(); };
    fgEnd(); const ft = root().querySelector(".fg-tl"); if(ft) ft.addEventListener("toggle", () => { if(ft.open) fgEnd(); });
  }
  function fedPersonPage(id){
    const p = fedPerson(id); if(!p){ fedHome(); return; }
    const S = FS().filter(s => (s.meta.persons || []).includes(id)), H = p.history || [];
    root().innerHTML = `<div class="crumb"><a href="#" data-go="h">경제지표 홈</a> › <a href="#" data-go="f">🏛️ 연준 인사 발언</a></div>
      <div class="rhead"><div class="tg">${esc(p.role || "")}${p.voter ? " · 투표권 있음" : ""}${p.en ? " · " + esc(p.en) : ""}</div><h1>${esc(p.name)}</h1>
        <div class="mt"><span>지금 위치 <b style="color:${fedColor(p.score)}">${p.score == null ? "아직 발언 없음" : `${p.score} · ${fedLabel(p.score)}`}</b></span>${fedDelta(p)}<span>정리한 발언 <b>${S.length}건</b></span>${p.last ? `<span>마지막 발언 <b>${esc(p.last)}</b></span>` : ""}</div></div>
      ${p.summary ? `<div class="concl"><small>지금 입장</small>${esc(p.summary)}</div>` : ""}
      ${p.score == null ? "" : `<div class="panel">${fedScale([p], false)}</div>`}
      ${H.length ? `<div class="chartbox" style="margin-top:14px"><h3>위치 변화 <small class="muted">(아래로 갈수록 🦅 매파, 위로 갈수록 🕊️ 비둘기)</small></h3><div class="cv" style="height:260px"><canvas id="ec-fchart"></canvas></div>
        <div class="src">${H.slice().reverse().map(h => `${esc(h.date)} <b>${h.score}</b> — ${esc(h.why || "")}`).join("<br>")}</div></div>` : ""}
      <h2>📌 추적 중인 포인트 <small>발언마다 어떻게 바뀌었는지</small></h2>
      ${(p.points || []).length ? `<div class="fpts">${p.points.map((pt, i) => `<div class="panel fpt"><div class="fp-h"><span class="no">${i + 1}</span><b>${esc(pt.title)}</b></div>
        ${pt.now ? `<div class="fp-now">지금: ${esc(pt.now)}</div>` : ""}
        <ol class="fp-tl">${(pt.history || []).map(h => `<li><span class="fp-d">${esc(h.date || "")}</span><span class="chg ${CHG[h.change] || "keep"}">${esc(h.change || "")}</span>
          <span>${esc(h.text || "")}${h.speech ? ` <a href="#" data-go="fs:${esc(h.speech)}">발언 보기 →</a>` : ""}</span></li>`).join("")}</ol></div>`).join("")}</div>`
        : `<p class="muted">아직 추적 중인 포인트가 없어요.</p>`}
      <h2>🗂️ 발언 기록 <small>${S.length}건</small></h2>${S.length ? `<div class="panel rlist">${S.map(fedRow).join("")}</div>` : ""}`;
    bindNav();
    const cv = document.getElementById("ec-fchart");
    if(H.length && cv) charts.push(new Chart(cv, {type: "line",
      data: {labels: H.map(h => h.date), datasets: [{label: "위치 점수", data: H.map(h => h.score), borderColor: "#0e1c36", backgroundColor: "#0e1c36",
        pointBackgroundColor: H.map(h => fedColor(h.score)), pointRadius: 5, tension: .2}]},
      options: {responsive: true, maintainAspectRatio: false, plugins: {legend: {display: false}, tooltip: {callbacks: {label: c => `${c.parsed.y} · ${fedLabel(c.parsed.y)}`}}},
        scales: {y: {min: 1, max: 100, ticks: {stepSize: 25, callback: v => v === 1 ? "1 🦅" : v === 100 ? "100 🕊️" : v === 50 ? "50 중립" : v},
          grid: {color: c => c.tick.value === 50 ? "#b9c0cb" : "#eef0f3"}}, x: {grid: {display: false}}}}}));
  }
  function fedSpeech(id){
    const s = FS().find(x => x.meta.id === id); if(!s){ fedHome(); return; }
    const m = s.meta;
    root().innerHTML = `<div class="crumb"><a href="#" data-go="h">경제지표 홈</a> › <a href="#" data-go="f">🏛️ 연준 인사 발언</a> › ${(m.persons || []).map(p => `<a href="#" data-go="fp:${esc(p)}">${esc(fedName(p))}</a>`).join(" · ")}</div>
      <div class="rhead"><div class="tg">${(m.persons || []).map(fedName).map(esc).join(" · ")}${m.event ? " · " + esc(m.event) : ""}</div><h1>${esc(m.title || "")}</h1>
        <div class="mt"><span>발언 <b>${esc(m.date || "-")}</b></span>${m.score_after ? `<span>위치 <b>${esc(m.score_before ? m.score_before + " → " : "")}${esc(m.score_after)}</b></span>` : ""}
          ${m.source_url ? `<a href="${esc(m.source_url)}" target="_blank" rel="noopener">🔗 원문</a>` : ""}</div></div>
      <div class="md" id="ec-fed"></div>`;
    renderMd(s.body, document.getElementById("ec-fed"));
    document.querySelectorAll("#ec-fed a[href^='http']").forEach(a => { a.target = "_blank"; a.rel = "noopener"; });
    bindNav();
  }

  // ---------- 💳 신용 스프레드 (회원 보기 · /api/econ/spreads, 서버가 6시간마다 FRED에서 새로 받음) ----------
  const SPR_COL = {"하이일드": "#9b1c31", "투자등급": "#1f3a68", "BBB": "#4a7fd4", "BB": "#2b8a3e", "B": "#e8590c", "CCC": "#7c3aed"};
  const STAGE_CLS = {"조용함": "pos", "바닥 스트레스": "mix", "번지는 중": "neg", "전이": "neg"};
  const sgn = v => v == null ? "-" : (v > 0 ? "+" : "") + v.toFixed(2);
  const chgCls = v => v == null ? "" : v > 0.004 ? "sp-up" : v < -0.004 ? "sp-dn" : "";
  let SPR = null, SPR_RANGE = "1y";
  async function spLoad(){ if(!SPR || SPR.error) SPR = await fetch("/api/econ/spreads").then(r => r.json()).catch(() => ({error: "불러오지 못했어요."})); return SPR; }
  function sprWatch(w){
    return `<div class="sp-w ${w.hit ? "hit" : ""}"><b>${esc(w.short)} ${w.line}%</b><span>${w.hit ? "⚠️ 경계선 도달" : `지금 ${w.last.toFixed(2)}% · 경계선까지 ${w.gap.toFixed(2)}%p`}${w.streak ? ` · ${w.streak}일째 위` : ""}</span><small>${esc(w.rule)} — ${esc(w.why)}</small></div>`;
  }
  // 💵 등급별 실제 금리(유효 수익률) — 금리 = 국채 몫 + OAS (노트 spreads.js에서 옮김)
  const YLD_ORDER = ["BBB", "BB", "B", "CCC", "하이일드", "투자등급"];
  function yldList(j){ const Y = j.ylatest || {}; return YLD_ORDER.map(k => Object.values(Y).find(x => x.short === k)).filter(Boolean); }
  function yldOas(j, k){ return Object.values(j.latest || {}).find(x => x.short === k); }
  function yldMini(j, keys){
    const L = yldList(j).filter(x => !keys || keys.includes(x.short)); if(!L.length) return "";
    return `<div class="sp-ylab">💵 등급별 실제 금리 <small class="muted">(회사채 유효 수익률 = 국채 + 가산금리)</small></div>
      <div class="sp-mini">${L.map(x => `<div><small>${esc(x.short)} 금리</small><b>${x.last.toFixed(2)}%</b><span class="${chgCls(x.chg_1m)}">1달 ${sgn(x.chg_1m)}</span><i>3년 중 ${x.pct_3y}%</i></div>`).join("")}</div>`;
  }
  function yldTable(j){
    const L = yldList(j); if(!L.length) return "";
    const split = x => { const o = yldOas(j, x.short); if(!o || x.chg_1m == null || o.chg_1m == null) return "-";
      const cr = o.chg_1m, rt = +(x.chg_1m - cr).toFixed(2); return `국채 <span class="${chgCls(rt)}">${sgn(rt)}</span> · 가산금리 <span class="${chgCls(cr)}">${sgn(cr)}</span>`; };
    return `<div class="panel tw" style="margin-top:12px"><h2 style="margin:0 0 4px">💵 등급별 실제 금리 <small>회사채 유효 수익률(%) · ${esc(L[0].date)} 기준</small></h2>
      <p class="muted" style="font-size:13px;margin:0 0 8px">회사가 지금 돈을 빌리려면 실제로 몇 % 이자를 줘야 하는지예요. <b>금리 = 국채 몫 + 가산금리(OAS)</b> — 금리가 올랐을 때 국채 금리가 올라서인지, 신용 걱정(가산금리)이 커져서인지 오른쪽 칸에서 나눠 봐요.</p>
      <table class="hist"><tr><th>등급</th><th>지금 금리</th><th>그중 가산금리</th><th>1주</th><th>1달</th><th>3달</th><th>최근 3년 위치</th><th>3년 범위</th><th>1달 변화 나누기</th></tr>
      ${L.map(x => { const o = yldOas(j, x.short); return `<tr><td style="text-align:left"><b style="color:${SPR_COL[x.short]}">●</b> <b>${esc(x.short)}</b></td><td><b>${x.last.toFixed(2)}%</b></td><td>${o ? o.last.toFixed(2) + "%" : "-"}</td>
        <td class="${chgCls(x.chg_1w)}">${sgn(x.chg_1w)}</td><td class="${chgCls(x.chg_1m)}">${sgn(x.chg_1m)}</td><td class="${chgCls(x.chg_3m)}">${sgn(x.chg_3m)}</td>
        <td>${x.pct_3y}%</td><td>${x.min_3y.toFixed(2)}~${x.max_3y.toFixed(2)}%</td><td style="white-space:nowrap">${split(x)}</td></tr>`; }).join("")}
      </table><p class="muted" style="font-size:12.5px;margin:8px 0 0">'국채 몫'은 금리에서 가산금리를 뺀 나머지(지수 평균 만기의 국채 금리 쪽)예요. 등급마다 평균 만기가 달라 국채 몫도 조금씩 달라요. 변화는 %p · 3년 위치는 높을수록 비쌈.</p></div>`;
  }
  // 🇺🇸 국채 2년·10년(FRED DGS2·DGS10)
  const UST_COL = {"DGS2": "#e8590c", "DGS10": "#1f3a68"};
  function ustMini(j){
    const U = j.ustlatest; if(!U || !U.DGS2 || !U.DGS10) return "";
    const sp = +(U.DGS10.last - U.DGS2.last).toFixed(2);
    return `<div class="sp-ylab">🇺🇸 미국 국채 금리 <small class="muted">(회사채 금리의 바닥 · ${esc(U.DGS10.date)} 기준)</small></div>
      <div class="sp-mini">${["DGS2", "DGS10"].map(k => { const x = U[k]; return `<div><small>${esc(x.short)}</small><b>${x.last.toFixed(2)}%</b><span class="${chgCls(x.chg_1m)}">1달 ${sgn(x.chg_1m)}</span><i>3년 중 ${x.pct_3y}%</i></div>`; }).join("")}
        <div><small>10년 − 2년</small><b>${sp > 0 ? "+" : ""}${sp.toFixed(2)}%p</b><span>${sp < 0 ? "역전(장단기 금리 거꾸로)" : "정상(10년이 더 높음)"}</span><i>장단기 금리 차</i></div></div>`;
  }
  // 선 그래프 한 개(왼쪽 축 sets + 오른쪽 축 r) — 한눈에·신용 스프레드 화면 공용
  function spLine(el, dates, sets, r, unit2){
    if(!el) return;
    const ds = (x, ax) => ({label: x.label, data: dates.map(d => x.data[d] ?? null), borderColor: x.color, backgroundColor: x.color, borderWidth: x.w || 2, borderDash: x.dash || [], pointRadius: 0, spanGaps: true, tension: .25, yAxisID: ax});
    const scales = {y: {ticks: {callback: v => +(+v).toFixed(2) + "%"}, grid: {color: "#eef0f3"}}, x: {grid: {display: false}, ticks: {maxTicksLimit: 8}}};
    if(r) scales.y2 = {position: "right", grid: {display: false}, ticks: {callback: v => +(+v).toFixed(2) + (unit2 || "%")}};
    charts.push(new Chart(el, {type: "line", data: {labels: dates, datasets: sets.map(x => ds(x, "y")).concat(r ? [ds(r, "y2")] : [])},
      options: {responsive: true, maintainAspectRatio: false, interaction: {mode: "index", intersect: false}, plugins: {legend: {labels: {boxWidth: 12}}}, scales}}));
  }
  const spCut = days => new Date(Date.now() - days * 864e5).toISOString().slice(0, 10);
  function yldChart(el, j, days){   // BB·B(왼쪽) + CCC(오른쪽)
    const Y = j.yields; if(!el || !Y) return;
    const id = k => Object.keys(Y).find(x => Y[x].short === k), cut = spCut(days), dates = Object.keys(Y[id("B")].data).sort().filter(d => d >= cut);
    spLine(el, dates, ["BB", "B"].map(k => ({label: k + " 금리", color: SPR_COL[k], data: Y[id(k)].data})), {label: "CCC 금리 (오른쪽 축)", color: SPR_COL.CCC, data: Y[id("CCC")].data});
  }
  function ustChart(el, j, days){   // 2년·10년(왼쪽) + 10년−2년(오른쪽, 점선)
    const U = j.ust; if(!el || !U || !U.DGS2 || !U.DGS10) return;
    const cut = spCut(days), dates = Object.keys(U.DGS10.data).sort().filter(d => d >= cut);
    const g = Object.fromEntries(dates.filter(d => U.DGS10.data[d] != null && U.DGS2.data[d] != null).map(d => [d, +(U.DGS10.data[d] - U.DGS2.data[d]).toFixed(2)]));
    spLine(el, dates, ["DGS2", "DGS10"].map(k => ({label: U[k].short, color: UST_COL[k], data: U[k].data})), {label: "10년 − 2년 (오른쪽 축)", color: "#9aa1ab", data: g, w: 1.5, dash: [5, 4]}, "%p");
  }
  // 🧭 등급 간 차이 해석(econ_spreads.gap_read) — 접기 박스
  function gapRead(r){
    if(!r) return "";
    const [ic] = AI_LV[r.level] || ["⚪"];
    return `<details class="panel fold ai-narr sp-gapread" data-fold="gapread"${foldOpen("gapread") ? " open" : ""}><summary><div><div class="lab">🧭 등급 간 차이 — 지금 어떻게 읽나 <small>숫자가 바뀌면 문장도 규칙대로 다시 써져요(히르찬 기준)</small></div>
      <h2 style="margin:4px 0 0">${ic} ${esc(r.head)}</h2></div></summary>${r.paras.map(x => `<p>${esc(x)}</p>`).join("")}
      <p style="margin-top:10px"><b>👀 앞으로 볼 것</b></p><ul class="aiw-watch">${r.watch.map(w => `<li>${esc(w)}</li>`).join("")}</ul>
      <details class="aiw-how"><summary>📖 이 화면 읽는 법</summary><ul>${AIW_HOW.gap.map(w => `<li>${esc(w)}</li>`).join("")}</ul></details></details>`;
  }
  // 📌 사건 메모(econ_spreads_notes.json) — 최근 days일, 최신 순, 접기 박스
  function spNotes(j, days){
    const cut = spCut(days), L = (j.notes || []).filter(n => n.date >= cut).sort((a, b) => b.date.localeCompare(a.date));
    if(!L.length) return "";
    return `<details class="panel fold sp-notes" data-fold="spnotes"${foldOpen("spnotes") ? " open" : ""}><summary><h2 style="margin:0">📌 사건 메모 <small>${L.length}건 · 최근: ${esc(L[0].date.slice(5).replace("-", "/"))} ${esc(L[0].title)}</small></h2></summary>
      <p class="muted" style="font-size:12.5px;margin:0 0 4px">그래프가 크게 움직인 날 무슨 일이 있었나 · 숫자는 FRED, 사건은 기사 출처</p>${L.map(n => `<div class="sp-note">
      <div class="sp-nh"><b>${esc(n.date)}</b>${(n.tags || []).map(t => `<span class="sp-tag">${esc(t)}</span>`).join("")}</div><div class="sp-nt">${esc(n.title)}</div><p>${esc(n.text)}</p>
      ${(n.src || []).length ? `<div class="sp-src">출처: ${n.src.map(([t, u]) => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(t)}</a>`).join(" · ")}</div>` : ""}</div>`).join("")}</details>`;
  }
  function foldSave(){ root().querySelectorAll("details.fold[data-fold]").forEach(d => { if(d.dataset.fs) return; d.dataset.fs = 1; d.addEventListener("toggle", () => { try{ localStorage.setItem("econ:fold:" + d.dataset.fold, d.open ? "1" : "0"); }catch(e){} }); }); }
  async function spreadHome(){
    const j = await spLoad(), top = document.getElementById("ec-sslot");
    if(!j || j.error || cur[0] !== "h" || !top) return;
    const L = Object.values(j.latest), T = j.transfer;
    top.insertAdjacentHTML("afterend", `<div class="panel ec-sph"><h2 style="margin-top:0">💳 신용 스프레드 <small>회사채가 국채보다 더 얹어 주는 금리 · ${esc(L[0].date)} 기준</small></h2>
      <div class="sp-head"><span class="stance ${STAGE_CLS[T.stage] || ""}">${esc(T.stage)}</span><span>${esc(T.text)}</span><a href="#" data-go="s">그래프·전체 보기 →</a></div>
      <div class="sp-mini">${L.map(x => `<div><small>${esc(x.short)}</small><b>${x.last.toFixed(2)}%</b><span class="${chgCls(x.chg_1m)}">1달 ${sgn(x.chg_1m)}</span><i>3년 중 ${x.pct_3y}%</i></div>`).join("")}</div>
      ${yldMini(j, ["BB", "B", "CCC"])}
      <div class="sp-ws">${j.watch.map(sprWatch).join("")}</div></div>`);
    bindNav();
  }
  // 📖 OAS가 뭔가요? — 신용 스프레드 화면 위 접는 칸(숫자는 지금 값으로)
  const OAS_ROWS = [["BBB", "투자등급의 맨 아래 · 비교적 안전"], ["BB", "하이일드(정크본드) 중 가장 우량"], ["B", "하이일드 중간"], ["CCC", "부도 직전급 · 가장 약한 고리"]];
  function oasHelp(j){
    const by = Object.fromEntries(Object.values(j.latest).map(x => [x.short, x.last]));
    const ccc = by.CCC;
    return `<details class="panel oas-help"><summary>📖 OAS가 뭔가요? <small>회사채 금리가 아니라 '국채보다 더 얹어 주는 이자'예요</small></summary>
      <p><b>회사채 금리 그 자체가 아니라</b>, 회사채 금리에서 <b>같은 만기 미국 국채 금리를 뺀 차이(가산금리·스프레드)</b>예요. 국채보다 이자를 얼마나 더 줘야 투자자가 사 주는지 = <b>시장이 느끼는 부도 위험의 온도계</b>예요.</p>
      <p><b>OAS = Option-Adjusted Spread(옵션 조정 스프레드).</b> 회사채엔 회사가 만기 전에 미리 갚을 수 있는 조건(조기상환 옵션)이 붙은 게 많아요. 금리가 떨어지면 회사는 비싼 빚을 미리 갚고 싸게 다시 빌리니, 이 옵션은 투자자에게 불리하고 그만큼 이자에 섞여 있어요. OAS는 이 옵션 몫을 빼고 남은 <b>순수한 신용위험의 대가</b>라, 조건이 다른 채권끼리도 공정하게 비교할 수 있어요. 여기 숫자는 ICE BofA 회사채 지수 전체의 평균 OAS예요.</p>
      <div style="overflow-x:auto"><table class="hist"><thead><tr><th>등급(높은 순)</th><th>지금 OAS</th><th>뜻</th></tr></thead><tbody>
        ${OAS_ROWS.filter(([k]) => by[k] != null).map(([k, t]) => `<tr><td><b>${k}</b></td><td>${by[k].toFixed(2)}%</td><td style="text-align:left;white-space:normal;min-width:150px">국채보다 ${by[k].toFixed(2)}%p 더 받아야 팔림 · ${t}</td></tr>`).join("")}
      </tbody></table></div>
      ${ccc != null ? `<p class="muted" style="font-size:13px">${(() => { const y = yldList(j).find(x => x.short === "CCC"); return y ? `예: 지금 CCC 회사채의 실제 금리(유효 수익률)는 <b>${y.last.toFixed(2)}%</b>, 그중 가산금리(OAS)가 ${ccc.toFixed(2)}%예요 — 나머지 약 ${(y.last - ccc).toFixed(2)}%가 국채 몫이에요. 등급별 실제 금리는 아래 '💵 등급별 실제 금리'에서 봐요.` : `예: 미국 10년 국채가 5%라면 CCC 회사채 금리는 대략 ${(5 + ccc).toFixed(1)}%라는 뜻이에요.`; })()} BBB까지가 투자등급, BB부터가 하이일드예요.</p>` : ""}
      <p><b>읽는 순서</b></p>
      <ol>
        <li><b>CCC부터 봐요</b> — 신용 위기는 가장 약한 회사(CCC)에서 시작해 위 등급으로 번져요.</li>
        <li><b>B·BB가 따라오는지</b> — 아래 등급만 벌어지면 '바닥 스트레스', 위 등급까지 오르면 '전이'예요.</li>
        <li><b>등급 간 차이 그래프</b> — CCC−BB가 벌어지면 바닥 스트레스, BB−BBB가 벌어지면 하이일드 전반으로 번지는 중이에요.</li>
        <li><b>BBB·투자등급</b> — 여기까지 오르면 우량 회사도 돈 빌리기 어려워진 것, 경기 침체 우려가 커진 단계예요.</li>
      </ol></details>`;
  }
  async function spreadPage(){
    root().innerHTML = `<p class="muted">불러오는 중…</p>`;
    const j = await spLoad(); if(cur[0] !== "s") return;
    if(j.error){ root().innerHTML = `<div class="empty">${esc(j.error)}</div>`; addNav(); return; }
    const S = j.series, T = j.transfer, ids = Object.keys(S);
    root().innerHTML = `${aiwNav("s")}
      <h1>💳 신용 스프레드</h1>
      <p class="muted" style="margin:0 0 14px">회사채 금리가 같은 만기 국채보다 얼마나 높은지(OAS, %)예요. 벌어질수록 시장이 기업 부도·자금 조달 위험을 크게 본다는 뜻이에요. 가장 약한 CCC부터 벌어지고, B → BB → BBB로 위 등급까지 따라오면 신용 스트레스가 '전이'되는 신호예요.</p>
      ${oasHelp(j)}
      <div class="panel"><div class="sp-head"><span class="stance ${STAGE_CLS[T.stage] || ""}">${esc(T.stage)}</span><b>${esc(T.text)}</b></div><p class="muted" style="font-size:12.5px;margin:6px 0 0">${esc(T.rule)}</p>
        <div class="sp-ws" style="margin-top:10px">${j.watch.map(sprWatch).join("")}</div></div>
      <div class="panel tw" style="margin-top:12px"><table class="hist"><tr><th>등급</th><th>지금</th><th>1주</th><th>1달</th><th>3달</th><th>최근 3년 위치</th><th>3년 범위</th></tr>
        ${ids.map(id => { const x = j.latest[id]; return `<tr><td style="text-align:left"><b style="color:${SPR_COL[x.short]}">●</b> ${esc(S[id].name)}</td><td><b>${x.last.toFixed(2)}%</b></td><td class="${chgCls(x.chg_1w)}">${sgn(x.chg_1w)}</td><td class="${chgCls(x.chg_1m)}">${sgn(x.chg_1m)}</td><td class="${chgCls(x.chg_3m)}">${sgn(x.chg_3m)}</td><td>${x.pct_3y}%</td><td>${x.min_3y.toFixed(2)}~${x.max_3y.toFixed(2)}%</td></tr>`; }).join("")}
        </table><p class="muted" style="font-size:12.5px;margin:8px 0 0">등급 간 차이: ${Object.entries(j.gaps).map(([k, v]) => `${esc(k)} <b>${v.toFixed(2)}%p</b>`).join(" · ")} · 변화는 %p · 3년 위치는 높을수록 넓음</p></div>
      ${yldTable(j)}
      <div class="sp-bar"><span>기간</span>${[["3m", "3개월"], ["1y", "1년"], ["3y", "3년"]].map(([k, t]) => `<button type="button" data-r="${k}" class="${SPR_RANGE === k ? "on" : ""}">${t}</button>`).join("")}
        <span style="margin-left:auto" class="muted">${esc(j.source)} · 받은 시각 ${esc(j.updated)}</span></div>
      <div class="chartbox"><h3>하이일드·투자등급 (OAS, %)</h3><div class="cv"><canvas id="sp-c1"></canvas></div><div class="src">점선: 감시 경계선(하이일드 3.5%, 투자등급 1.0%)</div></div>
      <div class="chartbox" style="margin-top:12px"><h3>등급별 — CCC가 먼저 벌어지고 위 등급이 따라오는지 (OAS, %)</h3><div class="cv"><canvas id="sp-c2"></canvas></div><div class="src">CCC는 수준이 달라 아래 그래프로 따로 봐요</div></div>
      <div class="sp-two"><div class="chartbox"><h3>CCC 이하 (OAS, %)</h3><div class="cv"><canvas id="sp-c3"></canvas></div></div>
        <div class="chartbox"><h3>등급 간 차이 (%p)</h3><div class="cv"><canvas id="sp-c4"></canvas></div><div class="src">CCC−BB가 벌어지면 바닥 스트레스, BB−BBB가 벌어지면 하이일드 전반으로 번짐</div></div></div>
      ${gapRead(j.gap_read)}
      ${spNotes(j, 90)}
      ${j.yields ? `<div class="sp-two"><div class="chartbox"><h3>💵 등급별 실제 금리 — BBB·BB·B (%)</h3><div class="cv"><canvas id="sp-c5"></canvas></div><div class="src">회사채 유효 수익률 = 국채 + 가산금리</div></div>
        <div class="chartbox"><h3>💵 CCC 이하 실제 금리 (%)</h3><div class="cv"><canvas id="sp-c6"></canvas></div><div class="src">수준이 달라 따로 봐요</div></div></div>` : ""}
      ${j.ust ? `<div class="chartbox" style="margin-top:12px"><h3>🇺🇸 미국 국채 2년·10년 (%)</h3><div class="cv"><canvas id="sp-c7"></canvas></div><div class="src">FRED DGS2·DGS10 · 점선 = 10년 − 2년(오른쪽 축, 0 아래면 역전) · 회사채 금리 = 국채 몫 + 가산금리</div></div>` : ""}
      <p class="foot">출처: ICE Data Indices via FRED(세인트루이스 연은) — 가산금리는 OAS, 실제 금리는 Effective Yield 시리즈(…EY), 국채는 DGS2·DGS10. FRED는 ICE 데이터의 최근 3년만 공개해요 — '3년 중 위치'는 그 안에서의 백분위예요. 하루 한 번, 하루 늦게 갱신돼요. 감시 경계선과 전이 단계는 히르찬의 판단 기준이에요.</p>`;
    addNav(); bindNav();
    const days = {"3m": 92, "1y": 366, "3y": 1200}[SPR_RANGE];
    const cut = new Date(Date.now() - days * 864e5).toISOString().slice(0, 10);
    const dates = Object.keys(S[ids[0]].data).sort().filter(d => d >= cut);
    const ds = (label, color, data, extra) => Object.assign({label, data, borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 0, spanGaps: true, tension: .1}, extra || {});
    const ser = id => ds(S[id].short, SPR_COL[S[id].short], dates.map(d => S[id].data[d] ?? null));
    const ref = (v, label) => ds(label, "#9aa1ab", dates.map(() => v), {borderDash: [6, 5], borderWidth: 1.5});
    const gap = (a, b) => dates.map(d => S[a].data[d] != null && S[b].data[d] != null ? +(S[a].data[d] - S[b].data[d]).toFixed(2) : null);
    const mk = (id, sets, y2) => { const el = document.getElementById(id); if(!el) return;
      charts.push(new Chart(el, {type: "line", data: {labels: dates, datasets: sets},
        options: {responsive: true, maintainAspectRatio: false, interaction: {mode: "index", intersect: false}, plugins: {legend: {labels: {boxWidth: 12}}},
          scales: Object.assign({y: {ticks: {callback: v => +(+v).toFixed(2) + "%"}, grid: {color: "#eef0f3"}}, x: {grid: {display: false}, ticks: {maxTicksLimit: 8}}},
            y2 ? {y2: {position: "right", grid: {display: false}, ticks: {callback: v => +(+v).toFixed(2) + "%"}}} : {})}})); };
    mk("sp-c1", [ser("BAMLH0A0HYM2"), ser("BAMLC0A0CM"), ref(3.5, "하이일드 경계선 3.5%"), ref(1.0, "투자등급 경계선 1.0%")]);
    mk("sp-c2", [ser("BAMLH0A2HYB"), ser("BAMLH0A1HYBB"), ser("BAMLC0A4CBBB")]);
    mk("sp-c3", [ser("BAMLH0A3HYC")]);
    mk("sp-c4", [ds("CCC−BB", "#7c3aed", gap("BAMLH0A3HYC", "BAMLH0A1HYBB")), ds("BB−BBB (오른쪽 축)", "#2b8a3e", gap("BAMLH0A1HYBB", "BAMLC0A4CBBB"), {yAxisID: "y2"})], true);
    if(j.yields){ const Y = j.yields, yid = k => Object.keys(Y).find(x => Y[x].short === k);
      spLine(document.getElementById("sp-c5"), dates, ["B", "BB", "BBB"].map(k => ({label: k + " 금리", color: SPR_COL[k], data: Y[yid(k)].data})));
      spLine(document.getElementById("sp-c6"), dates, [{label: "CCC 금리", color: SPR_COL.CCC, data: Y[yid("CCC")].data}]); }
    ustChart(document.getElementById("sp-c7"), j, days);
    foldSave();
    root().querySelectorAll("[data-r]").forEach(b => b.onclick = () => { SPR_RANGE = b.dataset.r; destroy(); spreadPage(); });
  }


  // ---------- 🤖 AI 리스크 계기판 ①~⑤ (회원 보기 · bundle.json의 ai_risk, 맥의 경제지표 노트 ai_risk.py·ai_market.py가 계산) ----------
  // 원본 화면: 경제지표 노트 static/ai.js — 고치면 둘 다(aiHome·aiPage를 뺀 공통 함수는 그대로 옮겨 씀)
  const AI_LV = {g: ["🟢", "pos"], y: ["🟡", "mix"], r: ["🔴", "neg"]};
  const AI_STAGE = {"여유": "pos", "압박 커지는 중": "mix", "압박 심함": "neg"};
  const AI_COL = {MSFT: "#1f3a68", GOOGL: "#2b8a3e", AMZN: "#e8590c", META: "#4a7fd4", ORCL: "#9b1c31"};
  const aiB = v => v == null ? "-" : (Math.abs(v) >= 1e12 ? `$${(v / 1e12).toFixed(2)}조` : `$${(v / 1e9).toLocaleString("en-US", {maximumFractionDigits: 1})}B`);

  function aiSummary(j, link = true){   // 홈 요약: 종합 + ①~⑤ 한 줄씩
    const A = aiAll(j), S = j.signals, M = j.market || {};
    const dots = items => items.map(x => (AI_LV[x.level] || ["⚪"])[0]).join("");
    const line = (nm, items, note) => `<div class="ai-row"><b>${esc(nm)}</b><span>${dots(items)}</span><small>${esc(note || "")}</small></div>`;
    const P = k => (M.pillars || []).find(p => p.key === k) || {items: []};
    const G = j.gauges && j.gauges.overall, st = G ? `종합 ${Math.round(G.score)} · ${G.band}` : `종합 ${A.stage}`;
    return `<div class="sp-head"><span class="stance ${G ? gCls(G.band) : AI_ALL[A.stage]}">${esc(st)}</span><span>🔴 ${A.r} · 🟡 ${A.y} · 🟢 ${A.g}</span>${link ? `<a href="#" data-go="a">그래프·회사별 보기 →</a>` : ""}</div>
      <div class="ai-rows">${S ? line("① 빅테크 자금 압박", S.items, `${S.stage} — 투자÷영업현금 ${S.items[0].value}% · 장부 밖 리스 ${S.items[3].value > 0 ? "+" : ""}${S.items[3].value}%`) : ""}
        ${line("② AI 주식 vs 시장", P("mkt").items, M.m ? `AI 인프라 고점 대비 ${M.m.ai_dd}% · 시장 대비 3개월 ${M.m.ai_rel_3m}%` : "")}
        ${line("③ 쏠림", P("conc").items, M.m ? `시총가중÷동일가중 3년 중 ${M.m.conc_pct3y}%` : "")}
        ${line("④ 약한 고리", P("weak").items, M.m ? `빚으로 짓는 곳 vs 하이퍼스케일러 3개월 ${M.m.weak_rel_3m}% · BIZD 고점 대비 ${M.m.bizd_dd}%` : "")}
        ${line("⑤ 수요 확인", P("demand").items, M.tsmc_3m != null ? `TSMC 월매출 전년비 3개월 평균 ${M.tsmc_3m}%${M.m && M.m.mem_3m != null ? ` · D램 현물가 3개월 ${M.m.mem_3m > 0 ? "+" : ""}${M.m.mem_3m}%` : ""}${M.m && M.m.cu_6m != null ? ` · 반도체 가동률 6개월 ${M.m.cu_6m > 0 ? "+" : ""}${M.m.cu_6m}%p` : ""}` : "")}</div>`;
  }
  // 🌡️ 온도계(공포탐욕지수 모양 반원 게이지) — 점수 0~100(높을수록 위험), ai_gauge.py
  const AI_GB = [[0, 20, "#2b8a3e", "안정"], [20, 40, "#82c91e", "낮음"], [40, 60, "#f59f00", "주의"], [60, 80, "#f76707", "경계"], [80, 100, "#c92a2a", "위험"]];
  const gCls = b => ({"안정": "pos", "낮음": "pos", "주의": "mix", "경계": "neg", "위험": "neg"})[b] || "";
  function aiGauge(score, title, hist, big){
    const R = big ? 120 : 78, sw = big ? 26 : 18, pad = sw / 2 + (big ? 20 : 22), W = 2 * (R + pad), cx = W / 2, cy = R + pad;   // 눈금 숫자가 잘리지 않게 둘레 여백
    const pt = (s, r) => { const a = Math.PI * (1 - s / 100); return [cx + r * Math.cos(a), cy - r * Math.sin(a)]; };
    const arc = (a, b, col) => { const [x1, y1] = pt(a, R), [x2, y2] = pt(b, R); return `<path d="M${x1.toFixed(1)} ${y1.toFixed(1)} A${R} ${R} 0 0 1 ${x2.toFixed(1)} ${y2.toFixed(1)}" stroke="${col}" stroke-width="${sw}" fill="none"/>`; };
    const s = score == null ? null : Math.max(0, Math.min(100, score));
    const band = s == null ? null : AI_GB.find(g => s < g[1] || g[1] === 100);
    const [nx, ny] = pt(s == null ? 50 : s, R - sw / 2 - 6);
    const ticks = [0, 20, 40, 60, 80, 100].map(t => { const [x, y] = pt(t, R + sw / 2 + 9); return `<text x="${x.toFixed(1)}" y="${(y + 3).toFixed(1)}" font-size="${big ? 11 : 9}" fill="#9aa1ab" text-anchor="middle">${t}</text>`; }).join("");
    const svg = `<svg viewBox="0 0 ${W} ${cy + 12}" width="100%" style="max-width:${big ? 320 : 210}px">${AI_GB.map(g => arc(g[0] + 0.6, g[1] - 0.6, g[2])).join("")}${ticks}
      ${s == null ? "" : `<line x1="${cx}" y1="${cy}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}" stroke="#1d2433" stroke-width="${big ? 4 : 3}" stroke-linecap="round"/><circle cx="${cx}" cy="${cy}" r="${big ? 8 : 6}" fill="#1d2433"/>`}</svg>`;
    const H = hist || {}, hv = v => v == null ? "-" : Math.round(v);
    return `<div class="ai-g${big ? " big" : ""}"><div class="t">${esc(title)}</div>${svg}
      <div class="n" style="color:${band ? band[2] : "#7b8392"}">${s == null ? "-" : Math.round(s)}<small>${band ? band[3] : ""}</small></div>
      <div class="h"><span>1주 전 <b>${hv(H["1w"])}</b></span><span>1달 전 <b>${hv(H["1m"])}</b></span><span>3달 전 <b>${hv(H["3m"])}</b></span></div></div>`;
  }
  function aiGauges(j){
    const G = j.gauges; if(!G) return "";
    return `<div class="panel ai-gp"><div class="lab">🌡️ AI 리스크 온도계 <small>0 = 안정 · 100 = 위험 — 공포탐욕지수처럼 신호를 점수로 바꾼 것</small></div>
      <div class="ai-gwrap">${aiGauge(G.overall.score, "종합", G.overall.hist, true)}
        <div class="ai-gs">${G.pillars.map(p => aiGauge(p.score, p.name, p.hist)).join("")}</div></div>
      <p class="muted" style="font-size:12px;margin:8px 0 0">점수 매기는 법: 지표마다 🟡 기준선 = 40점, 🔴 기준선 = 70점이 되게 늘인 뒤 0~100으로 자르고, 칸은 지표 평균(⑤ = TSMC 월매출·D램 현물가·서버 메모리 모듈·반도체 가동률), 종합은 다섯 칸 평균(같은 무게)이에요. ③ 쏠림은 '3년 중 위치 × 0.45'(+AI 주식이 시장보다 약하면 30). ①은 분기 공시라 1주·1달 전은 지금과 같고 3달 전은 직전 분기예요. 0~20 안정 · 20~40 낮음 · 40~60 주의 · 60~80 경계 · 80~100 위험 — 히르찬의 판단 기준(공식 지표 아님).</p></div>
      ${aiGaugeTlBox(G)}`;
  }
  // 📈 온도계 타임라인 — ai_gauge.series(5거래일마다 그날 기준으로 다시 계산), 접기 박스 (노트 ai.js에서 옮김)
  let AI_TL_RANGE = "1y";
  const AI_TL_COL = {fund: "#9b1c31", mkt: "#e8590c", conc: "#7c3aed", weak: "#2b8a3e", demand: "#4a7fd4"};
  function aiGaugeTlBox(G){
    const S = G.series || []; if(S.length < 3) return "";
    const pk = b => S.reduce((m, x) => x.o != null && (m == null || (b ? x.o > m.o : x.o < m.o)) ? x : m, null), hi = pk(true), lo = pk(false), last = S[S.length - 1];
    return `<details class="panel fold ai-tl" data-fold="aitl"${foldOpen("aitl") ? " open" : ""}><summary><h2 style="margin:0">📈 온도계 타임라인 <small>종합 ${Math.round(last.o)} · 2년 최고 ${Math.round(hi.o)}(${esc(hi.d)}) · 최저 ${Math.round(lo.o)}(${esc(lo.d)})</small></h2></summary>
      <div class="sp-bar"><span>기간</span>${[["6m", "6개월"], ["1y", "1년"], ["2y", "2년"]].map(([k, t]) => `<button type="button" data-tlr="${k}" class="${AI_TL_RANGE === k ? "on" : ""}">${t}</button>`).join("")}
        <span class="muted" style="margin-left:auto;font-size:12px">아래 이름을 누르면 칸별 선을 켜고 꺼요</span></div>
      <div class="cv" style="height:300px"><canvas id="ai-gtl"></canvas></div>
      <p class="muted" style="font-size:12px;margin:8px 0 0">5거래일마다 그날까지 알 수 있던 숫자로 다시 계산한 점수예요 — 주가는 그날 종가, TSMC 월매출은 그날 이미 발표된 달까지, ① 빅테크 공시는 분기 끝 + 35일부터 반영, D램 현물가는 기록이 2026년 2월부터라 그 전 ⑤는 TSMC·가동률만으로. 배경 점선: 40 주의 · 60 경계 · 80 위험.</p></details>`;
  }
  function aiGaugeTl(j){
    const el = document.getElementById("ai-gtl"), G = j && j.gauges; if(!el || !G || !G.series) return;
    const days = {"6m": 183, "1y": 366, "2y": 800}[AI_TL_RANGE], cut = new Date(Date.now() - days * 864e5).toISOString().slice(0, 10);
    const S = G.series.filter(x => x.d >= cut), dates = S.map(x => x.d);
    const ds = [{label: "종합", data: S.map(x => x.o), borderColor: "#1d2433", backgroundColor: "#1d2433", borderWidth: 3, pointRadius: 0, tension: .25, spanGaps: true}]
      .concat(G.pillars.map(p => ({label: p.name, data: S.map(x => x.p[p.key] ?? null), borderColor: AI_TL_COL[p.key], backgroundColor: AI_TL_COL[p.key], borderWidth: 1.5, pointRadius: 0, tension: .25, spanGaps: true, hidden: true})))
      .concat([[40, "#e8a10c"], [60, "#e8590c"], [80, "#c92a2a"]].map(([v, c]) => ({label: "_" + v, data: dates.map(() => v), borderColor: c, borderDash: [5, 5], borderWidth: 1, pointRadius: 0})));
    const c = new Chart(el, {type: "line", data: {labels: dates, datasets: ds}, options: {responsive: true, maintainAspectRatio: false, interaction: {mode: "index", intersect: false},
      plugins: {legend: {labels: {boxWidth: 12, filter: x => !x.text.startsWith("_")}}, tooltip: {filter: x => !x.dataset.label.startsWith("_"), callbacks: {label: x => `${x.dataset.label}: ${x.parsed.y == null ? "-" : Math.round(x.parsed.y)}`}}},
      scales: {y: {min: 0, max: 100, ticks: {stepSize: 20}, grid: {color: "#eef0f3"}}, x: {grid: {display: false}, ticks: {maxTicksLimit: 10}}}}});
    charts.push(c);
    root().querySelectorAll("[data-tlr]").forEach(b => b.onclick = () => { AI_TL_RANGE = b.dataset.tlr; root().querySelectorAll("[data-tlr]").forEach(x => x.classList.toggle("on", x === b)); const i = charts.indexOf(c); if(i >= 0) charts.splice(i, 1); c.destroy(); aiGaugeTl(j); });
    foldSave();
  }
  function aiNarr(j){   // 🧭 지금 국면 해석(규칙, ai_market.narrative) — 계기판 맨 위
    const n = j.narrative; if(!n) return "";
    const md = t => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
    return `<div class="panel ai-narr"><div class="lab">🧭 지금 국면 <small>${esc(n.asof || "")} 시장 · ${esc(n.q || "")} 공시 기준 · 계기판 숫자로 자동으로 쓴 해석</small></div>
      <h2>${esc(n.head)}</h2>${n.paras.map(p => `<p>${md(p)}</p>`).join("")}
      <div class="ai-watch"><b>👀 다음에 볼 것</b><ul>${n.watch.map(w => `<li>${md(w)}</li>`).join("")}</ul></div></div>`;
  }
  function aiItem(x){
    const [ic, cls] = AI_LV[x.level] || ["⚪", ""];
    const v = x.value == null ? "-" : (x.key === "ratio" ? `${x.value}%` : x.key === "over" ? `${x.value}${x.unit}` : `${x.value > 0 ? "+" : ""}${x.value}%`);
    return `<div class="ai-it ${cls}"><b>${ic} ${esc(x.name)}</b><span class="v">${esc(v)}${x.who && x.who.length ? ` <small>(${esc(x.who.join("·"))})</small>` : ""}</span><small>${esc(x.rule)} — ${esc(x.why)}</small></div>`;
  }

  function aiMItem(x){
    const [ic, cls] = AI_LV[x.level] || ["⚪", ""];
    const v = x.value == null ? "-" : x.fmt === "pct" ? `${x.value}%` : `${x.value > 0 ? "+" : ""}${x.value}${x.fmt === "pt" ? "%p" : "%"}`;
    return `<div class="ai-it ${cls}"><b>${ic} ${esc(x.name)}</b><span class="v">${esc(v)}</span><small>${esc(x.rule)} — ${esc(x.why)}</small></div>`;
  }
  function aiAll(j){   // ①~⑤ 신호를 모아 🔴🟡🟢 개수
    const L = [...(j.signals ? j.signals.items : []), ...((j.market || {}).pillars || []).flatMap(p => p.items)].map(x => x.level).filter(Boolean);
    const n = k => L.filter(x => x === k).length;
    return {r: n("r"), y: n("y"), g: n("g"), stage: n("r") >= 5 ? "경계" : n("r") >= 2 ? "주의" : "안정"};
  }
  const AI_ALL = {"안정": "pos", "주의": "mix", "경계": "neg"};
  function aiMarketBody(M){
    if(!M) return "";
    const P = M.per || {}, N = M.names || {}, b = M.baskets || {};
    const row = s => { const x = P[s]; if(!x) return ""; const c = v => v == null ? "-" : `<span class="${v < 0 ? "sp-up" : ""}">${v > 0 ? "+" : ""}${v}%</span>`;
      return `<tr><td style="text-align:left">${esc(x.name)} <small class="muted">${s}</small></td><td>${c(x.chg_1m)}</td><td>${c(x.chg_3m)}</td><td>${c(x.dd)}</td></tr>`; };
    const sec = (k, h, extra) => { const p = (M.pillars || []).find(x => x.key === k); return `<h2>${esc(p ? p.name : h)}</h2>${p ? `<div class="ai-its">${p.items.map(aiMItem).join("")}</div>` : ""}${extra || ""}`; };
    return `${sec("mkt", "② AI 주식 vs 시장", `<div class="chartbox" style="margin-top:10px"><h3>바구니 ÷ S&P500 동일가중 (최근 3년, 주간, 첫 주 = 100)</h3><div class="cv"><canvas id="ai-c5"></canvas></div><div class="src">AI 인프라: ${esc((b.ai || []).map(s => N[s] || s).join("·"))} · 하이퍼스케일러: ${esc((b.hyper || []).map(s => N[s] || s).join("·"))} — 각각 동일가중. 선이 내려가면 시장(동일가중)보다 약함</div></div>`)}
      ${sec("conc", "③ 쏠림", `<div class="chartbox" style="margin-top:10px"><h3>S&P500 시가총액가중 ÷ 동일가중 (최근 3년, 주간)</h3><div class="cv"><canvas id="ai-c6"></canvas></div><div class="src">올라갈수록 큰 종목 몇 개가 시장을 끄는 것(쏠림). 지금 최근 3년 중 ${M.m.conc_pct3y}% 위치 · 3개월 ${M.m.conc_3m > 0 ? "+" : ""}${M.m.conc_3m}%</div></div>`)}
      ${sec("weak", "④ 약한 고리", `<div class="sp-two"><div class="chartbox"><h3>빚으로 짓는 곳 ÷ 하이퍼스케일러 (주간)</h3><div class="cv"><canvas id="ai-c7"></canvas></div><div class="src">코어위브·네비우스·오라클(동일가중, 상장 뒤부터) ÷ 하이퍼스케일러 바구니 · 고점 대비 ${M.m.weak_dd}%</div></div>
        <div class="chartbox"><h3>사모신용 BDC ETF(BIZD) 가격 (주간)</h3><div class="cv"><canvas id="ai-c8"></canvas></div><div class="src">배당 빼고 가격만 · 고점 대비 ${M.m.bizd_dd}% · S&P500 대비 3개월 ${M.m.bizd_rel_3m > 0 ? "+" : ""}${M.m.bizd_rel_3m}%</div></div></div>`)}
      ${sec("demand", "⑤ 수요 확인", `<div class="sp-two"><div class="chartbox"><h3>TSMC 월매출 전년비 (%)</h3><div class="cv"><canvas id="ai-c9"></canvas></div><div class="src">최근 3개월 평균 ${M.tsmc_3m}% · 그 전 3개월 ${M.tsmc_prev3m}% — TSMC IR 월매출(대만달러)</div></div>
        <div class="panel" style="margin:0"><h3 style="margin-top:0">AI 부품 생산자 가격 (PPI 전년비)</h3>${Object.values(M.ppi || {}).map(x => `<p style="margin:6px 0"><b>${esc(x.name)}</b> ${x.yoy == null ? "-" : (x.yoy > 0 ? "+" : "") + x.yoy + "%"} <small class="muted">(${esc(x.month)})</small></p>`).join("")}
          <p class="muted" style="font-size:12.5px">수요가 강하다는 뜻이지만, 동시에 AI가 물가를 밀어 올리는 통로예요(의사록 'AI 관련 수요가 공급을 압박해 기술 소비재 가격을 올림'). BLS PPI 원계열.</p></div></div>`)}
      <h2>종목별 흐름</h2><div class="panel tw"><table class="hist"><tr><th>종목</th><th>1개월</th><th>3개월</th><th>1년 고점 대비</th></tr>
        <tr><td colspan="4" style="text-align:left"><b>AI 인프라</b></td></tr>${(b.ai || []).map(row).join("")}
        <tr><td colspan="4" style="text-align:left"><b>하이퍼스케일러</b></td></tr>${(b.hyper || []).map(row).join("")}
        <tr><td colspan="4" style="text-align:left"><b>약한 고리 · 사모신용</b></td></tr>${["CRWV", "NBIS", "BIZD"].map(row).join("")}</table>
        <p class="muted" style="font-size:12.5px;margin:8px 0 0">야후 파이낸스 종가 · ${esc(M.asof)} 기준 · 받은 시각 ${esc(M.made)}</p></div>`;
  }
  function aiMarketCharts(M, mk){
    if(!M || !M.charts) return;
    const C = M.charts, ds = (label, color, data, extra) => Object.assign({label, data, borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 0, spanGaps: true, tension: .15}, extra || {});
    const norm = o => { const k = Object.keys(o).sort(), b0 = o[k[0]]; return [k, k.map(d => +(o[d] / b0 * 100).toFixed(1))]; };
    const [d1, a1] = norm(C.ai_rel), h1 = (() => { const k = Object.keys(C.hy_rel).sort(), b0 = C.hy_rel[k[0]]; return d1.map(d => C.hy_rel[d] != null ? +(C.hy_rel[d] / b0 * 100).toFixed(1) : null); })();
    mk("ai-c5", "line", d1, [ds("AI 인프라 ÷ 동일가중", "#9b1c31", a1), ds("하이퍼스케일러 ÷ 동일가중", "#1f3a68", h1), ds("100", "#9aa1ab", d1.map(() => 100), {borderDash: [6, 5], borderWidth: 1.2})], "");
    const kc = Object.keys(C.conc).sort(); mk("ai-c6", "line", kc, [ds("시총가중 ÷ 동일가중", "#7c3aed", kc.map(d => +C.conc[d].toFixed(3)))], "");
    const [dw, aw] = norm(C.weak_rel); mk("ai-c7", "line", dw, [ds("빚으로 짓는 곳 ÷ 하이퍼스케일러", "#e8590c", aw), ds("100", "#9aa1ab", dw.map(() => 100), {borderDash: [6, 5], borderWidth: 1.2})], "");
    const kb = Object.keys(C.bizd).sort(); mk("ai-c8", "line", kb, [ds("BIZD", "#2b8a3e", kb.map(d => C.bizd[d]))], "$");
    const T = M.tsmc || []; mk("ai-c9", "bar", T.map(x => x.m), [ds("TSMC 월매출 전년비", "#1f3a68", T.map(x => x.yoy), {type: "bar"}), ds("20% 기준", "#9aa1ab", T.map(() => 20), {type: "line", borderDash: [6, 5], borderWidth: 1.2})], "%");
  }
  function aiCharts(j, mk){
    const T = j.total, qs = T.map(t => t.q), F = j.firms;
    const ds = (label, color, data, extra) => Object.assign({label, data, borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 2.5, spanGaps: true, tension: .2}, extra || {});
    const B = v => v == null ? null : +(v / 1e9).toFixed(1);
    mk("ai-c1", "bar", qs, [ds("투자 지출(최근 4분기, $B)", "#9b1c31", T.map(t => B(t.invest)), {type: "bar", order: 2}),
      ds("영업현금흐름(최근 4분기, $B)", "#1f3a68", T.map(t => B(t.ocf)), {type: "bar", order: 3}),
      ds("투자 ÷ 영업현금흐름(%, 오른쪽)", "#e8590c", T.map(t => t.ratio), {type: "line", yAxisID: "y2", order: 1, borderWidth: 2.5}),
      ds("90% 기준선(오른쪽)", "#9aa1ab", qs.map(() => 90), {type: "line", yAxisID: "y2", borderDash: [6, 5], borderWidth: 1.5, pointRadius: 0, order: 0})], "$B", "%");
    mk("ai-c2", "line", qs, [ds("차입금", "#1f3a68", T.map(t => B(t.debt))), ds("장부 안 리스 부채", "#4a7fd4", T.map(t => B(t.lease)), {borderDash: [5, 4]}),
      ds("장부 밖 데이터센터 리스(미개시)", "#9b1c31", T.map(t => B(t.nc)), {borderWidth: 3}), ds("잉여현금흐름(최근 4분기)", "#2b8a3e", T.map(t => B(t.fcf)))], "$B");
    mk("ai-c3", "line", qs, [...F.map(f => ds(f.name, AI_COL[f.ticker], qs.map(q => { const r = f.rows.find(x => x.q === q); return r ? r.ratio : null; }))),
      ds("100%(번 만큼 다 투자)", "#9aa1ab", qs.map(() => 100), {borderDash: [6, 5], borderWidth: 1.5, pointRadius: 0})], "%");
    const nq = qs.filter(q => F.some(f => (f.rows.find(x => x.q === q) || {}).nc));
    mk("ai-c4", "bar", nq, F.map(f => ds(f.name, AI_COL[f.ticker], nq.map(q => B((f.rows.find(x => x.q === q) || {}).nc)), {type: "bar", stack: "s"})), "$B", null, true);
  }
  function aiBody(j){
    const S = j.signals, F = j.firms;
    const last = f => f.rows[f.rows.length - 1] || {};
    return `<div class="panel"><div class="sp-head"><span class="stance ${AI_STAGE[S.stage] || ""}">${esc(S.stage)}</span><b>${esc(S.text)}</b></div>
        <div class="ai-its" style="margin-top:10px">${S.items.map(aiItem).join("")}</div>
        <p class="muted" style="font-size:12.5px;margin:8px 0 0">단계: 🔴가 3개 이상이면 '압박 심함', 🔴가 1~2개이거나 🟡가 3개 이상이면 '압박 커지는 중', 아니면 '여유'. 기준 숫자는 히르찬의 판단 기준이에요(공식 기준 아님).</p></div>
      <div class="panel tw" style="margin-top:12px"><table class="hist"><tr><th>회사</th><th>기준 분기</th><th>투자 지출</th><th>영업현금흐름</th><th>투자÷영업현금</th><th>잉여현금</th><th>차입금(1년 변화)</th><th>장부 밖 리스(1년 변화)</th></tr>
        ${F.map(f => { const r = last(f); return `<tr><td style="text-align:left"><b style="color:${AI_COL[f.ticker]}">●</b> ${esc(f.name)} <small class="muted">${f.ticker}</small></td><td>${esc(r.end || "-")}</td><td>${aiB(r.invest)}</td><td>${aiB(r.ocf)}</td>
          <td class="${(r.ratio || 0) >= 100 ? "sp-up" : ""}"><b>${r.ratio == null ? "-" : r.ratio + "%"}</b></td><td class="${(r.fcf || 0) < 0 ? "sp-up" : ""}">${aiB(r.fcf)}</td>
          <td>${aiB(r.debt)} <small>${r.debt_yoy == null ? "" : `(${r.debt_yoy > 0 ? "+" : ""}${r.debt_yoy}%)`}</small></td><td>${aiB(r.nc)} <small>${r.nc_yoy == null ? "" : `(${r.nc_yoy > 0 ? "+" : ""}${r.nc_yoy}%)`}</small></td></tr>`; }).join("")}
        </table><p class="muted" style="font-size:12.5px;margin:8px 0 0">금액은 최근 4분기 합(잔액은 분기 말). 투자 지출 = 유형자산 취득(아마존은 생산자산 취득) + 금융리스 원금 상환. 오라클은 회계분기가 달라(5월 결산) 가장 가까운 달력 분기에 맞췄어요.</p></div>
      <div class="chartbox" style="margin-top:12px"><h3>5곳 합계 — 투자 지출 vs 영업현금흐름 (최근 4분기 합)</h3><div class="cv" style="height:300px"><canvas id="ai-c1"></canvas></div><div class="src">주황 선(오른쪽 축)이 90%를 넘으면 번 현금을 거의 다 투자에 쓰는 상태</div></div>
      <div class="chartbox" style="margin-top:12px"><h3>5곳 합계 — 빚·리스·잉여현금 ($B)</h3><div class="cv" style="height:300px"><canvas id="ai-c2"></canvas></div><div class="src">빨간 굵은 선 = 아직 시작 안 해 부채로 잡히지 않은 데이터센터 리스 약정(의사록의 '장부 밖 리스'). 5곳 모두 공시에 있는 분기만</div></div>
      <div class="sp-two"><div class="chartbox"><h3>회사별 투자 ÷ 영업현금흐름 (%)</h3><div class="cv"><canvas id="ai-c3"></canvas></div><div class="src">점선 100% 위 = 번 것보다 더 투자(빚·외부 돈 필요)</div></div>
        <div class="chartbox"><h3>회사별 장부 밖 데이터센터 리스 ($B)</h3><div class="cv"><canvas id="ai-c4"></canvas></div><div class="src">각 회사 10-Q·10-K 본문의 '아직 시작 안 한 리스' 금액</div></div></div>
      <details class="panel" style="margin-top:12px"><summary><b>📄 장부 밖 리스 — 공시 원문 문장 보기</b></summary>
        ${F.filter(f => f.not_commenced).map(f => `<p style="font-size:13px"><b>${esc(f.name)}</b> (${esc(f.not_commenced.form || "")} · ${esc(f.nc_hist && f.nc_hist[0] ? f.nc_hist[0].date : "")}) ${aiB(f.not_commenced.usd)} — <i class="muted">“…${esc(f.not_commenced.text)}…”</i> <a href="${esc(f.not_commenced.url)}" target="_blank" rel="noopener">원문 ↗</a></p>`).join("")}</details>
      <p class="muted" style="font-size:12.5px">왜 보나: 10월 FOMC 의사록은 'AI 관련 빚이 빠르게 늘었고 상당 부분이 복잡하고 불투명한 금융 구조로 이뤄졌다', '장부 밖 리스 약정과 순환 금융이 AI 투자 수익이 실망스러우면 손실을 키울 수 있다'고 했어요. 이 칸은 그중 공시로 확인할 수 있는 부분(현금·빚·장부 밖 리스)을 매 분기 따라가요. 출처: SEC EDGAR(회사 공시) · 받은 시각 ${esc(j.made)}. 투자 권유가 아니에요.</p>`;
  }
  function aiHomeV(){
    const j = B.ai_risk, top = document.getElementById("ec-sslot");
    if(!j || !j.signals || cur[0] !== "h" || !top) return;
    top.insertAdjacentHTML("beforebegin", `<div class="panel ec-aih"><h2 style="margin-top:0">🤖 AI 리스크 계기판 <small>10월 FOMC 의사록이 짚은 AI발 위험 5갈래</small></h2>${aiSummary(j)}</div>`);
    bindNav();
  }
  function aiPageV(){
    const j = B.ai_risk;
    if(!j || !j.signals){ root().innerHTML = `<div class="empty">아직 계산한 자료가 없어요.</div>`; return; }
    root().innerHTML = `${aiwNav("a")}
      <h1>🤖 AI 리스크 계기판</h1>
      <p class="muted" style="margin:0 0 14px">10월 FOMC 의사록이 짚은 AI발 위험(빚·장부 밖 리스, 자산 가격 재평가, 소수 기업 쏠림, 레버리지 높은 약한 고리)을 공시·시장 자료로 따라가요. 판단 기준 숫자는 히르찬의 판단 기준이에요(공식 기준 아님).</p>
      ${aiNarr(j)}${aiGauges(j)}
      <div class="panel">${aiSummary(j, false)}<p class="muted" style="font-size:12.5px;margin:8px 0 0">종합 점수는 위 온도계(0~100)예요. 🔴🟡🟢는 지표 신호 개수.</p></div>
      <h2>① 빅테크 자금 압박 <small class="muted">AI 데이터센터를 가장 많이 짓는 5곳이 투자를 번 현금으로 감당하는지</small></h2>${aiBody(j)}${aiMarketBody(j.market)}`;
    bindNav();
    const mkc = (id, type, labels, sets, unit, unit2, stacked) => {
      const el = document.getElementById(id); if(!el) return;
      const fmt = u => v => u === "$B" ? `$${(+v).toLocaleString("en-US")}B` : u === "%" ? `${+v}%` : u === "$" ? `$${+v}` : v;
      const scales = {y: {stacked: !!stacked, ticks: {callback: fmt(unit)}, grid: {color: "#eef0f3"}}, x: {stacked: !!stacked, grid: {display: false}}};
      if(unit2) scales.y2 = {position: "right", grid: {display: false}, ticks: {callback: fmt(unit2)}};
      charts.push(new Chart(el, {type, data: {labels, datasets: sets}, options: {responsive: true, maintainAspectRatio: false, interaction: {mode: "index", intersect: false}, plugins: {legend: {labels: {boxWidth: 12}}}, scales}}));
    };
    aiCharts(j, mkc); aiMarketCharts(j.market, mkc); aiGaugeTl(j);
  }

  // ---------- 🛰️ AI 위험 추적 (노트 aiw.js 옮김 · 메모리·가동률은 bundle.json의 ai_risk.semis) ----------
  // 선 그래프(색 지정·기준 점선) — 노트 lineChart와 같은 모양
  function aiwLC(el, months, sets, target, unit, refs){
    const n = months.length;
    return new Chart(el, {type: "line", data: {labels: months.map(ym), datasets: [
        ...sets.map((s, i) => ({label: s.label, data: months.map(m => s.data[m] ?? null), borderColor: s.color || PAL[i % PAL.length], backgroundColor: s.color || PAL[i % PAL.length],
          borderWidth: i === 0 ? 2.5 : 2, pointRadius: n <= 13 ? 3.5 : 0, pointHoverRadius: 5, spanGaps: true, tension: .25})),
        ...(refs || []).map(r => ({label: r.label, data: months.map(() => r.value), borderColor: "#9aa1ab", backgroundColor: "#9aa1ab", borderDash: [6, 5], borderWidth: 1.5, pointRadius: 0}))]},
      options: {responsive: true, maintainAspectRatio: false, interaction: {mode: "index", intersect: false},
        plugins: {legend: {labels: {boxWidth: 12}}, tooltip: {callbacks: {label: c => `${c.dataset.label}: ${c.parsed.y ?? "-"}${unit === "%" ? "%" : ""}`}}},
        scales: {y: {ticks: {callback: v => +(+v).toFixed(4) + (unit === "%" ? "%" : "")}, grid: {color: "#eef0f3"}}, x: {grid: {display: false}, ticks: {maxTicksLimit: 12}}}}});
  }
  const AIW_TABS = [["w", "🛰️ 한눈에"], ["a", "🤖 AI 리스크 계기판"], ["s", "💳 신용 스프레드"], ["m", "💾 메모리 가격"], ["c", "🏭 공장 가동률"]];
  function aiwNav(cur){
    return `<div class="crumb"><a href="#" data-go="h">경제지표 홈</a> › <a href="#" data-go="w">🛰️ AI 위험 추적</a>${cur !== "w" ? ` › ${esc((AIW_TABS.find(t => t[0] === cur) || ["", ""])[1])}` : ""}</div>
      <nav class="aiw-tabs">${AIW_TABS.map(([k, t]) => `<a href="#" data-go="${k}" class="${k === cur ? "on" : ""}">${t}</a>`).join("")}</nav>`;
  }
  const MEM_COL = {"DDR5 16Gb": "#9b1c31", "DDR4 16Gb": "#1f3a68", "DDR4 8Gb": "#4a7fd4", "NAND 512Gb 웨이퍼": "#2b8a3e", "서버 모듈 RDIMM 32GB": "#7c3aed", "PC 모듈 UDIMM 16GB": "#e8590c"};
  const KR_COL = {"KR_MFG_CU": "#1f3a68", "KR_MFG_IDX": "#4a7fd4", "KR_SEMI_IDX": "#9b1c31", "KR_SEMI_CAP": "#2b8a3e"};
  const CU_COL = {"CAPUTLG3344S": "#9b1c31", "MCUMFN": "#1f3a68", "TCU": "#9aa1ab"};
  const pc = (v, u = "%") => v == null ? "-" : `<span class="${v < 0 ? "sp-dn" : v > 0 ? "sp-up" : ""}">${v > 0 ? "+" : ""}${v}${u}</span>`;
  async function aiwData(){
    const s = await spLoad(), a = B.ai_risk;
    return {a: a && a.signals ? a : null, s: s && !s.error ? s : null, m: a && a.semis};
  }
  function aiwSigs(list){ return `<div class="ai-its">${(list || []).map(aiMItem).join("")}</div>`; }

  // 홈 화면 한 칸(접기) — 네 갈래 숫자 한 줄씩 + 탭으로
  async function aiwHomeV(){
    const {a, s, m} = await aiwData();
    const el = document.getElementById("ec-sslot"); if(!el || cur[0] !== "h") return;
    if(!a && !s) return;
    const G = a && a.gauges && a.gauges.overall, T = s && s.transfer, mi = m ? m.mem.items[0] : null, ci = m ? m.cu.items[0] : null;
    el.innerHTML = `<div class="panel ec-aih"><h2 style="margin-top:0">🛰️ AI 위험 추적 <small>AI 리스크 계기판 · 신용 스프레드 · 메모리 가격 · 공장 가동률</small></h2>
      <div class="aiw-mini">
        ${G ? `<a href="#" data-go="a"><small>🤖 AI 리스크 온도계</small><b>${Math.round(G.score)}</b><span class="stance ${gCls(G.band)}">${esc(G.band)}</span></a>` : ""}
        ${T ? `<a href="#" data-go="s"><small>💳 하이일드 스프레드</small><b>${(Object.values(s.latest).find(x => x.short === "하이일드") || Object.values(s.latest)[0]).last.toFixed(2)}%</b><span class="stance ${STAGE_CLS[T.stage] || ""}">${esc(T.stage)}</span></a>` : ""}
        ${mi ? `<a href="#" data-go="m"><small>💾 ${esc(mi.short)} 현물가</small><b>$${mi.last}</b><span>3달 ${pc(mi.chg_3m)}</span></a>` : ""}
        ${ci ? `<a href="#" data-go="c"><small>🏭 ${esc(ci.short)} 가동률</small><b>${ci.last}%</b><span>6달 ${pc(ci.chg_6m, "%p")}</span></a>` : ""}
      </div><div style="text-align:right;margin-top:8px"><a href="#" data-go="w" style="font-size:13px;font-weight:800">AI 위험 추적 전체 보기 →</a></div></div>`;
    bindNav();
  }

  async function aiwPageV(){
    root().innerHTML = `<p class="muted">불러오는 중…</p>`;
    const {a, s, m} = await aiwData(); if(cur[0] !== "w") return;
    const G = a && a.gauges && a.gauges.overall, T = s && s.transfer;
    root().innerHTML = `${aiwNav("w")}<h1 style="margin-bottom:4px">🛰️ AI 위험 추적</h1>
      <p class="muted" style="margin:0 0 14px">10월 FOMC 의사록이 짚은 AI발 위험을 한곳에서 따라가요 — 돈(빅테크 빚·리스), 시장(주가·쏠림·약한 고리), 신용(회사채 가산금리), 수요(TSMC·메모리 값·공장 가동률). 판단 기준 숫자는 히르찬의 판단 기준이에요(공식 기준 아님).</p>
      ${a ? aiNarr(a) + aiGauges(a) : ""}
      <div class="aiw-grid">
        ${a ? `<div class="panel"><h2 style="margin:0 0 8px">🤖 AI 리스크 계기판</h2>${aiSummary(a)}</div>` : ""}
        ${s ? `<div class="panel"><h2 style="margin:0 0 8px">💳 신용 스프레드 <small>${esc(Object.values(s.latest)[0].date)} 기준</small></h2>
          <div class="sp-head"><span class="stance ${STAGE_CLS[T.stage] || ""}">${esc(T.stage)}</span><span>${esc(T.text)}</span><a href="#" data-go="s">그래프·전체 보기 →</a></div>${s.gap_read ? `<p class="aiw-one">🧭 ${esc(s.gap_read.head)}</p>` : ""}
          <div class="sp-mini">${Object.values(s.latest).map(x => `<div><small>${esc(x.short)}</small><b>${x.last.toFixed(2)}%</b><span class="${chgCls(x.chg_1m)}">1달 ${sgn(x.chg_1m)}</span><i>3년 중 ${x.pct_3y}%</i></div>`).join("")}</div>
          ${yldMini(s, ["BB", "B", "CCC"])}${s.yields ? `<div class="chartbox aiw-yc"><h3>💵 BB·B·CCC 실제 금리 — 최근 1년 (%)</h3><div class="cv" style="height:230px"><canvas id="aiw-yc"></canvas></div><div class="src">CCC는 수준이 높아 오른쪽 축 · BBB·하이일드 전체와 더 긴 기간은 신용 스프레드 화면에서</div></div>` : ""}
          ${ustMini(s)}${s.ust ? `<div class="chartbox aiw-yc"><h3>🇺🇸 미국 국채 2년·10년 — 최근 1년 (%)</h3><div class="cv" style="height:230px"><canvas id="aiw-uc"></canvas></div><div class="src">점선 = 10년 − 2년(오른쪽 축) · 국채가 내리는데 회사채 금리가 오르면 신용 걱정 때문</div></div>` : ""}</div>` : ""}
        ${m ? `<div class="panel"><h2 style="margin:0 0 8px">💾 메모리 가격 <small>현물가 세션 평균</small></h2>
          <div class="sp-head"><span>${m.signals.filter(x => x.key === "mem" || x.key === "mod").map(x => `${(AI_LV[x.level] || ["⚪"])[0]} ${esc(x.name)} ${pc(x.value)}`).join(" · ")}</span><a href="#" data-go="m">그래프·전체 보기 →</a></div>${m.mem.stage ? `<p class="aiw-one">🧭 지금 ${esc(m.mem.stage.head)} — ${esc(m.mem.stage.text)}</p>` : m.mem.read ? `<p class="aiw-one">🧭 ${esc(m.mem.read.head)}</p>` : ""}
          <div class="sp-mini">${m.mem.items.filter(x => x.short === "DDR5 16Gb" || x.short.startsWith("서버 모듈")).map(x => `<div><small>${x.short === "DDR5 16Gb" ? "🔹 DDR5 칩" : "🔸 서버 모듈"}</small><b>$${x.last.toLocaleString("en-US")}</b><span>1달 ${pc(x.chg_1m)}</span><i>3달 ${pc(x.chg_3m)}</i></div>`).join("")}</div>
          <p class="muted" style="font-size:12px;margin:6px 0 0">DDR4·PC 모듈·낸드는 메모리 화면 '참고 품목'에</p></div>
        <div class="panel"><h2 style="margin:0 0 8px">🏭 공장 가동률 <small>미국·한국 · 미국 ${esc(m.cu.items[0].date.slice(0, 7))}</small></h2>
          <div class="sp-head"><span>${m.signals.filter(x => x.key === "cu").map(x => `${(AI_LV[x.level] || ["⚪"])[0]} ${esc(x.name)} ${pc(x.value, "%p")}`).join("")}</span><a href="#" data-go="c">그래프·전체 보기 →</a></div>${m.cu.read ? `<p class="aiw-one">🧭 ${esc(m.cu.read.head)}</p>` : ""}
          <div class="sp-mini">${m.cu.items.map(x => `<div><small>🇺🇸 ${esc(x.short)}</small><b>${x.last}%</b><span>6달 ${pc(x.chg_6m, "%p")}</span><i>2000년 이후 평균 ${x.avg_2000}%</i></div>`).join("")}${((m.cu.kr || {}).items || []).filter(x => x.id === "KR_SEMI_IDX" || x.id === "KR_MFG_CU").map(x => `<div><small>🇰🇷 ${esc(x.id === "KR_SEMI_IDX" ? "반도체 지수(3달 평균)" : "제조업")}</small><b>${x.unit === "%" ? x.last + "%" : x.avg3}</b><span>${x.unit === "%" ? "1년 전 같은 달 " + (x.yoy_month > 0 ? "+" : "") + x.yoy_month + "%p" : "직전 3달 " + (x.chg_3m > 0 ? "+" : "") + x.chg_3m + "%"}</span><i>2000년 이후 평균 ${x.avg_2000}${x.unit === "%" ? "%" : ""}</i></div>`).join("")}</div></div>` : ""}
      </div>`;
    addNav(); bindNav();
    if(a) aiGaugeTl(a);
    if(s){ yldChart(document.getElementById("aiw-yc"), s, 366); ustChart(document.getElementById("aiw-uc"), s, 366); }
  }

  // 🧭 해석 패널 — semis.py의 mem_read/cu_read(규칙) + 고정 '읽는 법'
  const AIW_HOW = {
    gap: ["BB−BBB = 하이일드 맨 위(BB)와 투자등급 맨 아래(BBB)의 가산금리 차이예요. '투자등급 문턱'을 사이에 둔 두 등급이라, 이 차이가 벌어지면 시장이 하이일드 쪽만 따로 위험하게 본다는 뜻이에요.",
          "CCC−BB = 하이일드 안에서 가장 약한 회사와 가장 우량한 회사의 차이. 이게 먼저 벌어지고(바닥 스트레스) 다음에 BB−BBB가 벌어지면(위쪽으로 번짐) 신용 스트레스가 위 등급으로 올라오는 순서예요.",
          "벌어진 이유는 두 다리로 나눠 봐요 — BB가 올라서인지, BBB가 내려서인지. 위험 회피 날엔 BBB는 국채처럼(금리 내림), BB는 주식처럼(금리 오름) 움직여 차이가 확 벌어져요.",
          "하루 급등은 사건(주가 급락·실적·지표) 영향이 커요. 며칠 안에 되돌아가면 사건성, 계속 쌓이면 추세예요.",
          "지난 3년 기준점: 2024년 8월 엔캐리 청산 1.12, 2025년 4월 관세 충격 1.58 — 오른쪽 축 눈금이 좁아 그래프에선 작은 움직임도 크게 보이니 숫자(%p)로 확인해요."],
    mem: ["현물가는 그날그날 거래값이라 회사 간 계약가보다 1~2분기 먼저 움직여요. 그래서 메모리 회사 실적의 '예고편'이에요.",
          "주력 DDR5 = AI 서버·최신 PC에 들어가는 D램. 이게 오르면 AI 수요가 아직 뜨겁다는 뜻이에요.",
          "서버 모듈(DDR5 RDIMM 32GB) = 16Gb 칩 16개에 제어 칩을 붙인 서버용 완제품. 값엔 칩값 위에 품귀 웃돈이 붙어 있어 수요가 식으면 칩보다 먼저·크게 빠져요 — 칩은 오르는데 모듈이 빠지면 '웃돈부터 빠지는 중'.",
          "구형 DDR4 = 회사들이 생산을 줄이는 이전 세대. 공급이 줄어 값이 튀기도 해서 수요보다 '공급 사정'이 많이 섞여 있어요.",
          "낸드 웨이퍼 = 저장장치(SSD) 재료. D램보다 값이 크게 출렁여요.",
          "3달 변화로 방향을, 1달 변화로 속도를 봐요. 오르는 속도가 줄다가 1달이 마이너스로 바뀌면 꺾이는 신호예요."],
    cu:  ["가동률 = 공장이 낼 수 있는 최대 생산량 중 실제로 돌리는 비율. 높을수록 주문이 많아 바쁜 거예요.",
          "생산지수 = 실제로 만든 양. 공장을 새로 지으면 가동률은 그대로여도 생산지수는 올라가요.",
          "생산자물가(PPI) = 공장에서 내보내는 값. 가동률과 값이 같이 오르면 공급이 빡빡하다는 뜻이에요.",
          "산업 전체 가동률 80% 이상이면 공급이 빡빡해 물가를 밀어 올려요.",
          "미국 공장 숫자라 한국·대만 메모리·파운드리 호황은 덜 잡혀요. 그래서 '꺾임 경보'용으로 봐요.",
          "한국 숫자는 통계청 조사라 %가 아니라 지수(2020년 = 100)예요. 100보다 높으면 2020년보다 바쁘게 돌린다는 뜻이고, 반도체는 생산능력이 2020년의 2배라 같은 100이어도 만드는 양은 훨씬 많아요."],
  };
  function aiwRead(r, kind){
    if(!r) return "";
    const [ic] = AI_LV[r.level] || ["⚪"];
    return `<div class="panel ai-narr"><div class="lab">🧭 지금 어떻게 읽나 <small>숫자가 바뀌면 문장도 규칙대로 다시 써져요(히르찬 기준)</small></div>
      <h2>${ic} ${esc(r.head)}</h2>${r.paras.map(p => `<p>${esc(p)}</p>`).join("")}
      <p style="margin-top:10px"><b>👀 앞으로 볼 것</b></p><ul class="aiw-watch">${r.watch.map(w => `<li>${esc(w)}</li>`).join("")}</ul>
      <details class="aiw-how"><summary>📖 이 화면 읽는 법</summary><ul>${AIW_HOW[kind].map(w => `<li>${esc(w)}</li>`).join("")}</ul></details></div>`;
  }

  let MEM_RANGE = "1y";
  // 💾 메모리 화면 — 맨 위 '지금 어디쯤?'(①→②→③) + 핵심 두 개(DDR5 칩·서버 모듈), 나머지는 접어 둠
  function memStageBox(st){
    if(!st) return "";
    const [ic, cls] = AI_LV[st.level] || ["⚪", ""];
    return `<div class="panel mm-stage ${cls}"><div class="lab">🧭 지금 어디쯤? <small>AI 서버 메모리 과열이 식는 순서 ① → ② → ③ (히르찬 기준)</small></div>
      <h2>${ic} 지금 <b>${esc(st.head)}</b> — ${esc(st.text)}</h2>
      <div class="mm-steps">${st.steps.map((x, i) => `<div class="mm-step ${x.done ? "done" : ""} ${i === st.step - 1 ? "cur" : ""}"><div class="n">${x.n}</div><div><b>${esc(x.title)}</b><span>${x.done ? "✅ 지났어요" : "⏳ 아직"} · ${esc(x.now)}</span><small>기준: ${esc(x.rule)}</small></div></div>`).join('<div class="mm-arrow">→</div>')}</div>
      <p class="mm-next">👀 ${esc(st.next)}</p></div>`;
  }
  function memKeyCard(x, kind, sig){
    if(!x) return "";
    const [ic] = sig ? (AI_LV[sig.level] || ["⚪"]) : ["⚪"];
    const what = kind === "chip" ? "메모리 '부품'(칩 1개, 2GB) · 메모리 회사가 실제로 받는 값 → 실적과 직결" : "AI·데이터센터 서버용 '완제품'(칩 16개) · 품귀 웃돈이 붙어 있어 가장 먼저 움직임";
    const rule = kind === "chip" ? "1달이 마이너스로 돌면 ③ 단계" : "1달 −5% 아래 🟡 · −15% 아래 🔴";
    return `<div class="mm-kc"><div class="t">${kind === "chip" ? "🔹 DDR5 칩" : "🔸 서버 모듈"} <small>${esc(x.name)}</small></div>
      <div class="v">$${x.last.toLocaleString("en-US")}</div>
      <div class="c">1달 ${pc(x.chg_1m)} <small>3달 ${pc(x.chg_3m)} · 최고 대비 ${pc(x.from_hi)}</small></div>
      <p>${what}</p><small class="muted">지금 신호 ${ic} · 기준: ${rule} · ${esc(x.date)} 기준(${kind === "chip" ? "매일" : "주 1회"})</small></div>`;
  }
  function memFoldOpen(k){ try{ return localStorage.getItem("econ:fold:" + k) === "1"; }catch(e){ return false; } }   // 처음엔 접힘
  function memPage(){
    const j = (B.ai_risk || {}).semis || {error: "아직 받은 자료가 없어요."};
    if(j.error){ root().innerHTML = aiwNav("m") + `<p>${esc(j.error)}</p>`; return; }
    const M = j.mem, I = M.items, H = M.hist, last = Object.keys(H).sort().pop(), R = M.read;
    const d5 = I.find(x => x.short === "DDR5 16Gb"), rd = I.find(x => x.short.startsWith("서버 모듈")), ud = I.find(x => x.short.startsWith("PC 모듈"));
    const sig = k => j.signals.find(x => x.key === k);
    root().innerHTML = `${aiwNav("m")}<h1 style="margin-bottom:4px">💾 메모리 가격</h1>
      <p class="muted" style="margin:0 0 14px">AI 수요의 가장 빠른 체온계예요. <b>두 개만 보면 돼요 — DDR5 칩(부품)과 서버 모듈(완제품).</b> 서버 모듈 값엔 품귀 웃돈이 붙어 있어서, AI 서버 수요가 식으면 ① 서버 모듈 웃돈이 먼저 빠지고 → ② 칩 값 오르는 속도가 멈추고 → ③ 칩 값도 내려요.</p>
      ${memStageBox(M.stage)}
      <div class="mm-keys">${memKeyCard(rd, "module", sig("mod"))}${memKeyCard(d5, "chip", sig("mem"))}</div>
      <div class="sp-bar"><span>기간</span>${[["3m", "3개월"], ["1y", "1년"], ["all", "전체"]].map(([k, t]) => `<button type="button" data-r="${k}" class="${MEM_RANGE === k ? "on" : ""}">${t}</button>`).join("")}
        <span style="margin-left:auto" class="muted">${esc(M.source)} · 받은 시각 ${esc(j.made)}</span></div>
      <div class="sp-two"><div class="chartbox"><h3>칩 vs 서버 모듈 — 같은 날 = 100</h3><div class="cv"><canvas id="mm-c5"></canvas></div><div class="src">모듈 선이 칩 선보다 먼저 꺾이면 품귀 웃돈이 빠지는 중 · 1년 전(기록이 그보다 짧으면 둘 다 기록이 있는 첫날) = 100</div></div>
        <div class="chartbox"><h3>1달 변화율 — 칩·서버 모듈 (%)</h3><div class="cv"><canvas id="mm-c6"></canvas></div><div class="src">점선: 0%(칩이 아래로 가면 ③) · −5%(서버 모듈 🟡·①) · −15%(서버 모듈 🔴)</div></div></div>
      ${R ? `<details class="panel fold ai-narr mm-read" data-fold="memread"${memFoldOpen("memread") ? " open" : ""}><summary><div><div class="lab">🧭 자세한 해석 <small>DDR4·낸드까지 포함 · 숫자가 바뀌면 문장도 규칙대로 다시 써져요</small></div><h2 style="margin:4px 0 0">${(AI_LV[R.level] || ["⚪"])[0]} ${esc(R.head)}</h2></div></summary>
        ${R.paras.map(x => `<p>${esc(x)}</p>`).join("")}<p style="margin-top:10px"><b>👀 앞으로 볼 것</b></p><ul class="aiw-watch">${R.watch.map(w => `<li>${esc(w)}</li>`).join("")}</ul>
        <details class="aiw-how"><summary>📖 이 화면 읽는 법</summary><ul>${AIW_HOW.mem.map(w => `<li>${esc(w)}</li>`).join("")}</ul></details></details>` : ""}
      <details class="panel fold mm-ref" data-fold="memref"${memFoldOpen("memref") ? " open" : ""}><summary><h2 style="margin:0">📦 참고 품목·그래프 <small>DDR4 칩·PC 모듈·낸드 — 안 봐도 돼요(공급 사정이 많이 섞인 숫자)</small></h2></summary>
        <p class="muted" style="font-size:13px;margin:0 0 8px">DDR4는 한 세대 전 칩이라 회사들이 덜 만들면서 값이 튀고 빠져요 — AI 수요보다 '공급 사정'. PC 모듈은 일반 소비자 쪽 기준선, 낸드는 저장장치(SSD) 재료예요.</p>
        ${aiwSigs(j.signals.filter(x => x.key === "mem" || x.key === "mod"))}
        <div style="overflow-x:auto"><table class="hist"><thead><tr><th>품목</th><th>지금($)</th><th>1주</th><th>1달</th><th>3달</th><th>1년</th><th>기록 중 최고 대비</th><th>기준일</th></tr></thead><tbody>
          ${I.map(x => `<tr><td style="text-align:left"><b style="color:${MEM_COL[x.short]}">●</b> ${esc(x.short)} <small class="muted">${esc(x.why)}</small></td><td><b>${x.last}</b></td><td>${pc(x.chg_1w)}</td><td>${pc(x.chg_1m)}</td><td>${pc(x.chg_3m)}</td><td>${pc(x.chg_1y)}</td><td>${pc(x.from_hi)}</td><td>${esc(x.date)}</td></tr>`).join("")}
        </tbody></table></div>
        <p class="muted" style="font-size:12.5px;margin:8px 0 0">D램 칩은 매일, 모듈·낸드 웨이퍼는 주 1회 갱신. 칩(16Gb = 2GB) 값과 모듈(완제품, 32GB = 16Gb 칩 16개) 값은 단위가 달라요. 과거 값은 웹 아카이브에 남은 DRAMeXchange 화면 사본(대략 주 1개)으로 채워서 1주·1달 변화는 기록 간격만큼 오차가 있어요.</p>
        <div class="chartbox" style="margin-top:12px"><h3>D램 칩 현물가 ($, 세션 평균)</h3><div class="cv" style="height:280px"><canvas id="mm-c1"></canvas></div><div class="src">DDR5 16Gb 4800/5600 · DDR4 16Gb 3200 · DDR4 8Gb 3200 (예전 기록은 같은 용량의 2666 속도 품목으로 이어 붙임)</div></div>
        <div class="sp-two"><div class="chartbox"><h3>D램 모듈 현물가 ($, 주 1회)</h3><div class="cv"><canvas id="mm-c4"></canvas></div><div class="src">서버 RDIMM 32GB(왼쪽 축) · PC UDIMM 16GB(오른쪽 축), DDR5 4800/5600</div></div>
          <div class="chartbox"><h3>D램 칩 3개월 변화율 (%)</h3><div class="cv"><canvas id="mm-c3"></canvas></div><div class="src">DDR5 칩 3개월이 0 아래면 ⑤ 수요 확인 🟡, −15% 아래면 🔴</div></div></div>
        <div class="chartbox" style="margin-top:12px"><h3>낸드 웨이퍼 현물가 ($)</h3><div class="cv"><canvas id="mm-c2"></canvas></div><div class="src">512Gb·256Gb TLC 웨이퍼</div></div>
        <details style="margin-top:12px"><summary><b>📋 ${esc(last)} 받은 전체 품목</b></summary><table class="hist">${Object.entries(H[last] || {}).map(([k, v]) => `<tr><td style="text-align:left">${esc(k)}</td><td>$${v}</td></tr>`).join("")}</table></details></details>`;
    bindNav();
    const days = {"3m": 92, "1y": 366, "all": 99999}[MEM_RANGE];
    const cut = new Date(Date.now() - days * 864e5).toISOString().slice(0, 10);
    const dates = Object.keys(H).sort().filter(d => d >= cut);
    const ser = x => ({label: x.short, color: MEM_COL[x.short], data: Object.fromEntries(dates.map(d => [d, x.series[d] ?? null]))});
    const lc = (id, sets, unit, refs, ds) => { const el = document.getElementById(id); if(!el) return; const L = ds || dates, c = aiwLC(el, L, sets, null, unit, refs); c.data.labels = L; c.options.elements = {point: {radius: L.length < 60 ? 2 : 0}}; c.update(); charts.push(c); return c; };
    const chgN = (S, n) => { const all = Object.keys(S).sort(); return Object.fromEntries(dates.map(d => {   // n일 전(3주 안의 가장 가까운 기록) 대비 %
      const c0 = new Date(new Date(d).getTime() - n * 864e5).toISOString().slice(0, 10), prev = all.filter(k => k <= c0).pop();
      return [d, prev && S[d] != null && (new Date(c0) - new Date(prev)) / 864e5 <= 21 ? +((S[d] / S[prev] - 1) * 100).toFixed(1) : null]; })); };
    // 핵심 그래프
    if(rd && d5){
      const md = dates.filter(d => rd.series[d] != null || (ud && ud.series[d] != null));   // 모듈은 주 1회라 값 있는 날만
      const yr = new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10), from = [yr, Object.keys(rd.series).sort()[0], Object.keys(d5.series).sort()[0]].sort().pop();   // 둘 다 기록 있는 첫날 = 100
      const base = S => { const k = Object.keys(S).sort().filter(d => d >= from)[0]; return k ? S[k] : null; };
      const idx = x => { const b = base(x.series); return Object.fromEntries(md.map(d => [d, x.series[d] != null && b ? +(x.series[d] / b * 100).toFixed(1) : null])); };
      lc("mm-c5", [{label: "DDR5 칩", color: MEM_COL["DDR5 16Gb"], data: idx(d5)}, {label: "서버 모듈", color: MEM_COL[rd.short], data: idx(rd)}], "", null, md.filter(d => d >= from));
      const cc = chgN(d5.series, 30), mc = chgN(rd.series, 30), dd = dates.filter(d => d >= from && (cc[d] != null || mc[d] != null));
      lc("mm-c6", [{label: "DDR5 칩 1달", color: MEM_COL["DDR5 16Gb"], data: cc}, {label: "서버 모듈 1달", color: MEM_COL[rd.short], data: mc}], "%", [{value: 0, label: "0%"}, {value: -5, label: "−5%"}, {value: -15, label: "−15%"}], dd);
      if(document.getElementById("mm-c4")){
        const c = lc("mm-c4", [{label: rd.short, color: MEM_COL[rd.short], data: rd.series}], "", null, md);
        if(c && ud){ c.data.datasets.push({label: ud.short + " (오른쪽 축)", data: md.map(d => ud.series[d] ?? null), borderColor: MEM_COL[ud.short], backgroundColor: MEM_COL[ud.short], borderWidth: 2, pointRadius: 2, spanGaps: true, tension: .25, yAxisID: "y2"});
          c.options.scales.y2 = {position: "right", grid: {display: false}}; c.update(); }
      }
    }
    // 참고 그래프
    const D = I.filter(x => x.short.startsWith("DDR"));
    lc("mm-c1", D.map(ser), "");
    lc("mm-c2", [...I.filter(x => x.short.startsWith("NAND")).map(ser), {label: "256Gb TLC", color: "#82c91e", data: Object.fromEntries(dates.map(d => [d, H[d]["256Gb TLC"] ?? null]))}], "");
    lc("mm-c3", D.map(x => ({label: x.short, color: MEM_COL[x.short], data: chgN(x.series, 91)})), "%", [{value: 0, label: "0%"}, {value: -15, label: "−15%"}]);
    root().querySelectorAll("details.fold[data-fold]").forEach(d => d.addEventListener("toggle", () => { try{ localStorage.setItem("econ:fold:" + d.dataset.fold, d.open ? "1" : "0"); }catch(e){} }));
    root().querySelectorAll("[data-r]").forEach(b => b.onclick = () => { MEM_RANGE = b.dataset.r; destroy(); memPage(); addNav(); });
  }

  let CU_RANGE = "10y";
  function cuPage(){
    const j = (B.ai_risk || {}).semis || {error: "아직 받은 자료가 없어요."};
    if(j.error){ root().innerHTML = aiwNav("c") + `<p>${esc(j.error)}</p>`; return; }
    const C = j.cu, S = C.series, N = C.names, KRB = C.kr && C.kr.items && C.kr.items.length ? C.kr : null;
    root().innerHTML = `${aiwNav("c")}<h1 style="margin-bottom:4px">🏭 공장 가동률 <small class="muted" style="font-size:15px">미국 · 한국</small></h1>
      <p class="muted" style="margin:0 0 14px">공장이 낼 수 있는 최대 생산량 중 실제로 얼마나 돌리고 있는지(%)예요(연준 산업생산 통계, 매달 중순 발표). 반도체·전자부품 가동률이 꺾이면 칩 주문이 줄었다는 뜻이고, 전체 가동률이 80%를 넘으면 공급이 빡빡해 물가 압력이 커져요.</p>
      ${aiwRead(C.read, "cu")}<div class="panel">${aiwSigs(j.signals.filter(x => x.key === "cu"))}</div>
      <div class="panel"><div style="overflow-x:auto"><table class="hist"><thead><tr><th>구분</th><th>지금</th><th>3달</th><th>6달</th><th>1년</th><th>2000년 이후 평균</th><th>장기 평균</th><th>2000년 이후 위치</th></tr></thead><tbody>
        ${C.items.map(x => `<tr><td style="text-align:left"><b style="color:${CU_COL[x.id]}">●</b> ${esc(x.name)} <small class="muted">${x.id}</small></td><td><b>${x.last}%</b> <small class="muted">${esc(x.date.slice(0, 7))}</small></td><td>${pc(x.chg_3m, "%p")}</td><td>${pc(x.chg_6m, "%p")}</td><td>${pc(x.chg_1y, "%p")}</td><td>${x.avg_2000}%</td><td>${x.avg_long}% <small class="muted">(${esc(x.first.slice(0, 4))}~)</small></td><td>${x.pct_2000}%</td></tr>`).join("")}
        </tbody></table></div><p class="muted" style="font-size:12.5px;margin:8px 0 0">변화는 %p. '위치'는 2000년 이후 달 중 지금보다 낮거나 같았던 비율(높을수록 공장이 바쁨). 미국 공장 기준이라 TSMC·한국 공장은 TSMC 월매출·메모리 값으로 따로 봐요.</p></div>
      <div class="sp-bar"><span>기간</span>${[["3y", "3년"], ["10y", "10년"]].map(([k, t]) => `<button type="button" data-r="${k}" class="${CU_RANGE === k ? "on" : ""}">${t}</button>`).join("")}
        <span style="margin-left:auto" class="muted">${esc(C.source)} · 받은 시각 ${esc(j.made)}</span></div>
      <div class="chartbox"><h3>가동률 (%)</h3><div class="cv" style="height:300px"><canvas id="cu-c1"></canvas></div><div class="src">점선: 반도체 2000년 이후 평균 · 80%(공급이 빡빡해지는 선)</div></div>
      <div class="sp-two"><div class="chartbox"><h3>${esc(N.IPG3344S)}</h3><div class="cv"><canvas id="cu-c2"></canvas></div><div class="src">가동률이 같아도 생산 능력이 늘면 생산지수는 올라가요</div></div>
        <div class="chartbox"><h3>${esc(N.PCU334413334413)} 전년비 (%)</h3><div class="cv"><canvas id="cu-c3"></canvas></div><div class="src">미국에서 만든 반도체 출하 가격(메모리 비중은 작음)</div></div></div>
      ${KRB ? `<h2 style="margin:22px 0 8px">🇰🇷 한국 공장 가동률 <small class="muted">${esc(KRB.items[0].date.slice(0, 7))} · 통계청</small></h2>
      <div class="panel"><div style="overflow-x:auto"><table class="hist"><thead><tr><th>구분</th><th>지금</th><th>3달 평균</th><th>직전 3달 대비</th><th>1년 전 3달 대비</th><th>2000년 이후 평균</th><th>2000년 이후 위치</th></tr></thead><tbody>
        ${KRB.items.map(x => { const u = x.unit === "%" ? "%" : "", d = x.unit === "%" ? "%p" : "%";
          return `<tr><td style="text-align:left"><b style="color:${KR_COL[x.id]}">●</b> ${esc(x.name)}</td><td><b>${x.last}${u}</b></td><td>${x.avg3}${u}</td><td>${pc(x.chg_3m, d)}</td><td>${pc(x.chg_1y, d)}</td><td>${x.avg_2000}${u}</td><td>${x.pct_2000}%</td></tr>`; }).join("")}
        </tbody></table></div><p class="muted" style="font-size:12.5px;margin:8px 0 0">지수는 2020년 = 100. 반도체 가동률지수는 한 달에 10% 넘게 출렁여서 3달 평균끼리 비교해요(지수는 %, 평균가동률은 %p). 평균가동률은 계절 조정 전 숫자예요. 매달 말 통계청 산업활동동향으로 전달 숫자가 나와요.</p></div>
      <div class="chartbox"><h3>한국 가동률지수 (2020=100, 계절조정)</h3><div class="cv" style="height:300px"><canvas id="cu-k1"></canvas></div><div class="src">굵은 선: 반도체 3달 평균 · 점선 100 = 2020년 수준</div></div>
      <div class="sp-two"><div class="chartbox"><h3>한국 반도체 생산능력지수 (2020=100)</h3><div class="cv"><canvas id="cu-k2"></canvas></div><div class="src">공장을 새로 지으면 올라가요</div></div>
        <div class="chartbox"><h3>한국 제조업 평균가동률 (%)</h3><div class="cv"><canvas id="cu-k3"></canvas></div><div class="src">계절 조정 전 숫자 · 점선: 2000년 이후 평균</div></div></div>` : ""}`;
    bindNav();
    const yrs = {"3y": 3, "10y": 10}[CU_RANGE], cut = new Date(Date.now() - yrs * 365.25 * 864e5).toISOString().slice(0, 10);
    const ms = Object.keys(S.TCU).sort().filter(d => d >= cut);
    const set = (id, label) => ({label, color: CU_COL[id] || "#2b8a3e", data: Object.fromEntries(ms.map(d => [d, S[id][d] ?? null]))});
    const lc = (id, sets, unit, refs) => { const c = aiwLC(document.getElementById(id), ms.map(d => d.slice(0, 7)), sets.map(x => ({...x, data: Object.fromEntries(Object.entries(x.data).map(([k, v]) => [k.slice(0, 7), v]))})), null, unit, refs); charts.push(c); };
    const semi = C.items.find(x => x.id === "CAPUTLG3344S");
    lc("cu-c1", C.items.map(x => set(x.id, x.short)), "%", [{value: semi.avg_2000, label: `반도체 평균 ${semi.avg_2000}%`}, {value: 80, label: "80%"}]);
    lc("cu-c2", [set("IPG3344S", "생산지수")], "");
    const P = S.PCU334413334413, pk = Object.keys(P).sort();
    const yoy = Object.fromEntries(ms.map(d => { const p = pk.find(k => k.slice(0, 7) === `${+d.slice(0, 4) - 1}${d.slice(4, 7)}`); return [d, P[d] != null && p ? +((P[d] / P[p] - 1) * 100).toFixed(1) : null]; }));
    lc("cu-c3", [{label: "반도체 PPI 전년비", color: "#e8590c", data: yoy}], "%", [{value: 0, label: "0%"}]);
    if(KRB){
      const K = KRB.series, km = Object.keys(K.KR_SEMI_IDX).sort().filter(d => d >= cut);
      const ks = (id, label, extra = {}) => ({label, color: KR_COL[id], data: Object.fromEntries(km.map(d => [d.slice(0, 7), K[id][d] ?? null])), ...extra});
      const sm = Object.keys(K.KR_SEMI_IDX).sort(), avg3 = Object.fromEntries(km.map(d => { const i = sm.indexOf(d), w = sm.slice(Math.max(0, i - 2), i + 1).map(k => K.KR_SEMI_IDX[k]);
        return [d.slice(0, 7), w.length === 3 ? +(w.reduce((a, b) => a + b, 0) / 3).toFixed(1) : null]; }));
      const kl = (id, sets, unit, refs) => charts.push(aiwLC(document.getElementById(id), km.map(d => d.slice(0, 7)), sets, null, unit, refs));
      kl("cu-k1", [ks("KR_SEMI_IDX", "반도체(월)", {color: "#e6a5ae"}), {label: "반도체 3달 평균", color: KR_COL.KR_SEMI_IDX, data: avg3}, ks("KR_MFG_IDX", "제조업")], "", [{value: 100, label: "100"}]);
      kl("cu-k2", [ks("KR_SEMI_CAP", "반도체 생산능력")], "");
      const mf = KRB.items.find(x => x.id === "KR_MFG_CU");
      kl("cu-k3", [ks("KR_MFG_CU", "제조업 평균가동률")], "%", mf ? [{value: mf.avg_2000, label: `평균 ${mf.avg_2000}%`}] : []);
    }
    root().querySelectorAll("[data-r]").forEach(b => b.onclick = () => { CU_RANGE = b.dataset.r; destroy(); cuPage(); addNav(); });
  }

  // ---------- 👑 기타 보고서 분석 · 히르찬 매크로 리서치 (관리자 전용 · 아니면 서버가 403) ----------
  async function adminGet(url){
    try{ const r = await fetch(url, {cache: "no-store"}); return r.ok ? await r.json() : null; }catch(e){ return null; }
  }
  const adminOnly = () => `<div class="empty">관리자에게만 보이는 화면이에요.</div>`;
  async function otherList(){
    root().innerHTML = `<p class="muted">불러오는 중…</p>`;
    const j = await adminGet("/api/econ/other"); if(cur[0] !== "o") return;
    if(!j){ root().innerHTML = adminOnly(); addNav(); return; }
    const L = j.items || [];
    root().innerHTML = `<div class="crumb"><a href="#" data-go="h">경제지표 홈</a> › 👑 기타 보고서</div>
      <h1>📚 기타 보고서 분석 <small class="muted" style="font-size:14px">관리자 전용</small></h1>
      <p class="muted" style="margin:0 0 14px">다른 기관 자료(연준·IMF·투자은행 등)를 맥의 경제지표 노트에 올려 분석한 글이에요. 회원에게는 보이지 않아요.</p>
      ${L.length ? `<div class="panel rlist">${L.map(x => `<a href="#" data-go="od:${esc(x.id)}"><div class="dt"><b>${esc((x.date || x.made || "").slice(5, 10).replace("-", "/") || "-")}</b>${esc(x.org || "")}</div>
        <div><div class="t">${esc(x.title || x.id)}${x.stance ? ` <i class="ec-st ${stCls(x.stance)}">${esc(x.stance)}</i>` : ""}</div><div class="c">${esc(x.conclusion || "")}</div></div></a>`).join("")}</div>`
        : `<div class="empty">아직 분석한 자료가 없어요.</div>`}`;
    addNav(); bindNav();
  }
  async function otherOne(id){
    root().innerHTML = `<p class="muted">불러오는 중…</p>`;
    const j = await adminGet("/api/econ/other?id=" + encodeURIComponent(id)); if(cur[0] !== "od") return;
    if(!j){ root().innerHTML = adminOnly(); addNav(); return; }
    const m = j.meta;
    root().innerHTML = `<div class="crumb"><a href="#" data-go="h">경제지표 홈</a> › <a href="#" data-go="o">👑 기타 보고서</a></div>
      <div class="rhead"><div class="tg">${esc(m.org || "기타 보고서")} · 관리자 전용</div><h1>${esc(m.title || id)}</h1>
        <div class="mt">${m.date ? `<span>자료 <b>${esc(m.date)}</b></span>` : ""}${m.made ? `<span>분석 <b>${esc(m.made)}</b></span>` : ""}${m.stance ? `<span>위험자산 관점 <i class="ec-st ${stCls(m.stance)}">${esc(m.stance)}</i></span>` : ""}</div></div>
      ${m.conclusion ? `<div class="concl"><small>한 줄 결론</small>${esc(m.conclusion)}</div>` : ""}
      <div id="ec-obrief"></div>
      <div class="md" id="ec-other"></div>`;
    adminBriefs().then(L => {   // 이 자료로 만든 📑 리서치 보고서 PDF가 있으면 받기 버튼
      const b = (L || []).find(x => x.kind === "other" && x.oid === id), box = document.getElementById("ec-obrief");
      if(b && box && cur[0] === "od") box.innerHTML = `<a class="ec-bbtn" href="${pdfUrl(b.id)}">👑 리서치 보고서 PDF 받기 <small>${esc(b.title || "")}${b.made ? ` · ${esc(b.made)} 작성` : ""} · 관리자 전용</small></a>`;
    });
    renderMd(j.body.replace(/==([^=\n]+)==/g, "**$1**"), document.getElementById("ec-other"));
    document.querySelectorAll("#ec-other a[href^='http']").forEach(a => { a.target = "_blank"; a.rel = "noopener"; });
    addNav(); bindNav();
  }
  async function hmrList(){
    root().innerHTML = `<p class="muted">불러오는 중…</p>`;
    const j = await adminGet("/api/econ/hmr"); if(cur[0] !== "hr") return;
    if(!j){ root().innerHTML = adminOnly(); addNav(); return; }
    const L = j.items || [], u = (id, dl) => "/api/econ/hmr_pdf?id=" + encodeURIComponent(id) + (dl ? "&dl=1" : "");
    root().innerHTML = `<div class="crumb"><a href="#" data-go="h">경제지표 홈</a> › 👑 히르찬 매크로 리서치</div>
      <h1>✍️ 히르찬 매크로 리서치 <small class="muted" style="font-size:14px">관리자 전용</small></h1>
      <p class="muted" style="margin:0 0 14px">맥의 경제지표 노트에서 쓴 HEECHAN Macro Research 리포트예요. 'PDF 보기'는 원본 그대로, '⬇ 받기'는 연준 발언 번호를 뺀 PDF예요.</p>
      ${L.length ? `<div class="panel ec-hmr">${L.map(x => `<div class="ec-hrow"><div><small>${esc(x.date || "")}</small><b>${esc(x.title || x.id)}</b>${x.subtitle ? `<span>${esc(x.subtitle)}</span>` : ""}</div>
        <div class="ec-hact"><a href="${u(x.id)}" target="_blank" rel="noopener">PDF 보기</a><a class="dl" href="${u(x.id, 1)}">⬇ 받기</a></div></div>`).join("")}</div>`
        : `<div class="empty">아직 리포트가 없어요.</div>`}`;
    addNav(); bindNav();
  }

  // 💬 해석 글에 질문하기: /api/econ/ask(회원 전용). 대화는 이 해석 글을 보는 동안만 기억
  const QA = {};
  function paintQA(id){
    const box = document.getElementById("ec-qa"); if(!box) return;
    box.innerHTML = (QA[id] || []).map(x => `<div class="qa-i"><div class="qa-q">🙋 ${esc(x.q)}</div>${
      x.loading ? `<div class="qa-a wait">⏳ 해석 글을 읽고 최근 뉴스를 찾아보는 중이에요… (보통 10~20초)</div>`
      : x.error ? `<div class="qa-a bad">${esc(x.error)}${x.locked ? ` <a href="#" data-login="1">로그인하기</a>` : ""}</div>`
      : `<div class="md qa-a"></div>${x.sources && x.sources.length ? `<div class="qa-src"><b>참고한 뉴스</b>${x.sources.map(n =>
          `<a href="${esc(n.url)}" target="_blank" rel="noopener">[${n.n}] ${esc(n.d)} ${esc(n.src)} · ${esc(n.t)}</a>`).join("")}</div>` : ""}<div class="qa-meta">${esc(x.at || "")} · AI 답변이라 틀릴 수 있어요. 투자 권유가 아니에요.</div>`}</div>`).join("");
    const els = box.querySelectorAll(".md.qa-a");
    (QA[id] || []).filter(x => !x.loading && !x.error).forEach((x, i) => { if(els[i]){ renderMd(x.answer, els[i]);
      els[i].querySelectorAll("a[href^='http']").forEach(a => { a.target = "_blank"; a.rel = "noopener"; }); } });
    box.querySelectorAll("[data-login]").forEach(a => a.onclick = e => { e.preventDefault(); const b = document.querySelector("[data-open=login]"); if(b) b.click(); });
  }
  async function askQA(id, q){
    q = (q || "").trim(); if(!q) return;
    const L = QA[id] = QA[id] || [];
    if(L.some(x => x.loading)) return;
    const history = L.filter(x => x.answer).slice(-3).map(x => ({q: x.q, a: x.answer}));
    const it = {q, loading: true}; L.push(it); paintQA(id);
    try{
      const r = await fetch("/api/econ/ask", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({id, q, history})});
      Object.assign(it, await r.json());
    }catch(e){ it.error = "답을 받지 못했어요. 잠시 뒤 다시 물어봐 주세요."; }
    it.loading = false; paintQA(id);
  }
  function bindAsk(id){
    const f = document.getElementById("ec-qa-f"), t = document.getElementById("ec-qa-q"); if(!f) return;
    f.onsubmit = e => { e.preventDefault(); const q = t.value; if(q.trim()){ t.value = ""; askQA(id, q); } };
    t.onkeydown = e => { if(e.key === "Enter" && (e.ctrlKey || e.metaKey)){ e.preventDefault(); f.requestSubmit(); } };
    paintQA(id);
  }

  window.econOpen = async function(){
    if(!root()) return;
    if(!ready){
      root().innerHTML = `<p class="muted">불러오는 중…</p>`;
      ready = init().catch(e => { ready = null; throw e; });
    }
    try{ await ready; }catch(e){ root().innerHTML = `<div class="empty">불러오지 못했어요. 잠시 뒤 다시 눌러 주세요.</div>`; return; }
    if(!root().dataset.shown){ root().dataset.shown = "1"; go("h"); }
    else charts.forEach(c => c.resize());
  };
})();
