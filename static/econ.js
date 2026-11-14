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
    const V = {i: indicator, g: group, r: report, f: fedHome, fp: fedPersonPage, fs: fedSpeech, s: spreadPage, o: otherList, od: otherOne, hr: hmrList};
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
      <a href="#" data-go="s"><b>💳 신용 스프레드</b><span>하이일드·투자등급·등급별 전이 · 매일 자동</span></a></div>
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
    spreadHome();
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
    const W = L.filter(b => b.kind === "weekly"), I = L.filter(b => b.kind === "report");
    const row = b => `<a class="ec-brow" href="${pdfUrl(b.id)}"><b>${esc(b.kind === "weekly" ? `${(b.start || "").slice(5).replace("-", "/")}~${(b.end || "").slice(5).replace("-", "/")}` : `${b.name || nameOf(b.indicator)} · ${b.period || ""}`)}</b>
      <span>${esc(b.conclusion || b.title || "")}</span>${b.stance ? `<i class="ec-st ${stCls(b.stance)}">${esc(b.stance)}</i>` : ""}<em>⬇ PDF</em></a>`;
    top.insertAdjacentHTML("afterend", `<div class="panel ec-briefs"><h2 style="margin-top:0">👑 매크로 리서치 보고서 <small>관리자에게만 보여요 · 누르면 PDF를 받아요</small></h2>
      ${L.length ? `<div class="ec-bcols"><div><h3>주간 종합</h3>${W.length ? W.map(row).join("") : `<p class="muted">아직 없어요.</p>`}</div>
        <div><h3>지표 보고서</h3>${I.length ? I.slice(0, 12).map(row).join("") : `<p class="muted">아직 없어요.</p>`}</div></div>`
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
  function fedHome(){
    const P = FP(), S = FS(), PS = P.filter(p => p.score != null);
    root().innerHTML = `<h1>🏛️ 연준 인사 발언 모음</h1>
      <p class="muted" style="margin:0 0 16px">연준 인사의 연설·인터뷰를 히르찬이 정리해요. 지난 발언과 무엇이 달라졌는지, 매파·비둘기 위치가 어디쯤인지 발언마다 이어서 고쳐요.</p>
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
      ${S.length ? `<h2>🗂️ 최근 정리한 발언 <small>${S.length}건</small></h2><div class="panel rlist">${S.slice(0, 20).map(fedRow).join("")}</div>` : ""}`;
    bindNav();
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
  async function spreadHome(){
    const j = await spLoad(), top = document.getElementById("ec-sslot");
    if(!j || j.error || cur[0] !== "h" || !top) return;
    const L = Object.values(j.latest), T = j.transfer;
    top.insertAdjacentHTML("afterend", `<div class="panel ec-sph"><h2 style="margin-top:0">💳 신용 스프레드 <small>회사채가 국채보다 더 얹어 주는 금리 · ${esc(L[0].date)} 기준</small></h2>
      <div class="sp-head"><span class="stance ${STAGE_CLS[T.stage] || ""}">${esc(T.stage)}</span><span>${esc(T.text)}</span><a href="#" data-go="s">그래프·전체 보기 →</a></div>
      <div class="sp-mini">${L.map(x => `<div><small>${esc(x.short)}</small><b>${x.last.toFixed(2)}%</b><span class="${chgCls(x.chg_1m)}">1달 ${sgn(x.chg_1m)}</span><i>3년 중 ${x.pct_3y}%</i></div>`).join("")}</div>
      <div class="sp-ws">${j.watch.map(sprWatch).join("")}</div></div>`);
    bindNav();
  }
  async function spreadPage(){
    root().innerHTML = `<p class="muted">불러오는 중…</p>`;
    const j = await spLoad(); if(cur[0] !== "s") return;
    if(j.error){ root().innerHTML = `<div class="empty">${esc(j.error)}</div>`; addNav(); return; }
    const S = j.series, T = j.transfer, ids = Object.keys(S);
    root().innerHTML = `<div class="crumb"><a href="#" data-go="h">경제지표 홈</a> › 💳 신용 스프레드</div>
      <h1>💳 신용 스프레드</h1>
      <p class="muted" style="margin:0 0 14px">회사채 금리가 같은 만기 국채보다 얼마나 높은지(OAS, %)예요. 벌어질수록 시장이 기업 부도·자금 조달 위험을 크게 본다는 뜻이에요. 가장 약한 CCC부터 벌어지고, B → BB → BBB로 위 등급까지 따라오면 신용 스트레스가 '전이'되는 신호예요.</p>
      <div class="panel"><div class="sp-head"><span class="stance ${STAGE_CLS[T.stage] || ""}">${esc(T.stage)}</span><b>${esc(T.text)}</b></div><p class="muted" style="font-size:12.5px;margin:6px 0 0">${esc(T.rule)}</p>
        <div class="sp-ws" style="margin-top:10px">${j.watch.map(sprWatch).join("")}</div></div>
      <div class="panel tw" style="margin-top:12px"><table class="hist"><tr><th>등급</th><th>지금</th><th>1주</th><th>1달</th><th>3달</th><th>최근 3년 위치</th><th>3년 범위</th></tr>
        ${ids.map(id => { const x = j.latest[id]; return `<tr><td style="text-align:left"><b style="color:${SPR_COL[x.short]}">●</b> ${esc(S[id].name)}</td><td><b>${x.last.toFixed(2)}%</b></td><td class="${chgCls(x.chg_1w)}">${sgn(x.chg_1w)}</td><td class="${chgCls(x.chg_1m)}">${sgn(x.chg_1m)}</td><td class="${chgCls(x.chg_3m)}">${sgn(x.chg_3m)}</td><td>${x.pct_3y}%</td><td>${x.min_3y.toFixed(2)}~${x.max_3y.toFixed(2)}%</td></tr>`; }).join("")}
        </table><p class="muted" style="font-size:12.5px;margin:8px 0 0">등급 간 차이: ${Object.entries(j.gaps).map(([k, v]) => `${esc(k)} <b>${v.toFixed(2)}%p</b>`).join(" · ")} · 변화는 %p · 3년 위치는 높을수록 넓음</p></div>
      <div class="sp-bar"><span>기간</span>${[["3m", "3개월"], ["1y", "1년"], ["3y", "3년"]].map(([k, t]) => `<button type="button" data-r="${k}" class="${SPR_RANGE === k ? "on" : ""}">${t}</button>`).join("")}
        <span style="margin-left:auto" class="muted">${esc(j.source)} · 받은 시각 ${esc(j.updated)}</span></div>
      <div class="chartbox"><h3>하이일드·투자등급 (OAS, %)</h3><div class="cv"><canvas id="sp-c1"></canvas></div><div class="src">점선: 감시 경계선(하이일드 3.5%, 투자등급 1.0%)</div></div>
      <div class="chartbox" style="margin-top:12px"><h3>등급별 — CCC가 먼저 벌어지고 위 등급이 따라오는지 (OAS, %)</h3><div class="cv"><canvas id="sp-c2"></canvas></div><div class="src">CCC는 수준이 달라 아래 그래프로 따로 봐요</div></div>
      <div class="sp-two"><div class="chartbox"><h3>CCC 이하 (OAS, %)</h3><div class="cv"><canvas id="sp-c3"></canvas></div></div>
        <div class="chartbox"><h3>등급 간 차이 (%p)</h3><div class="cv"><canvas id="sp-c4"></canvas></div><div class="src">CCC−BB가 벌어지면 바닥 스트레스, BB−BBB가 벌어지면 하이일드 전반으로 번짐</div></div></div>
      <p class="foot">출처: ICE Data Indices via FRED(세인트루이스 연은). FRED는 ICE 데이터의 최근 3년만 공개해요 — '3년 중 위치'는 그 안에서의 백분위예요. 하루 한 번, 하루 늦게 갱신돼요. 감시 경계선과 전이 단계는 히르찬의 판단 기준이에요.</p>`;
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
    root().querySelectorAll("[data-r]").forEach(b => b.onclick = () => { SPR_RANGE = b.dataset.r; destroy(); spreadPage(); });
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
      <div class="md" id="ec-other"></div>`;
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
