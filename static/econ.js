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
    if(view === "i") indicator(id); else if(view === "g") group(id); else if(view === "r") report(id); else home();
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
    let h = `<div class="home-top">
      <div class="panel"><h2 style="margin-top:0">📝 최근 해석 <small>${reps.length ? reps.length + "건" : ""}</small></h2>
        ${reps.length ? `<div class="rlist">${reps.slice(0, 6).map(r => `<a href="#" data-go="r:${esc(r.id)}"><div class="dt"><b>${esc((r.release || "").slice(5).replace("-", "/"))}</b>발표</div>
          <div><div class="t">${esc(name(r.indicator))} · ${esc(r.period || "")}</div><div class="c">${esc(r.conclusion || r.title || "")}</div></div></a>`).join("")}</div>`
        : `<div class="empty">아직 해석이 없어요. 발표 자료가 나오면 히르찬이 해석을 올려요.</div>`}</div>
      <div class="panel"><h2 style="margin-top:0">📅 다가오는 발표</h2>
        ${up.length ? `<div class="up">${up.slice(0, 8).map(i => `<a href="#" data-go="i:${i.id}"><span>${esc(i.name)}</span><b>${esc(i.next_release.slice(5).replace("-", "/"))}</b></a>`).join("")}</div>`
        : `<p class="muted" style="font-size:14px;margin:0">해석할 때 확인한 다음 발표일이 여기 모여요.</p>`}</div>
    </div>`;
    for(const c of ["US", "KR", "CN", "EU"]){
      const list = D.filter(i => i.country === c); if(!list.length) continue;
      const cards = list.map(i => { const g = groupOf(i.id); return !g ? card(i) : g.members[0] === i.id ? groupCard(g) : ""; });
      h += `<div class="cty">${CTY[c]}</div><div class="grid">${cards.join("")}</div>`;
    }
    root().innerHTML = h + `<p class="foot">숫자는 발표 원문 그대로이며, 계산·추정값은 따로 표시해요. 투자 권유가 아닌 공부용 해석이에요. · 업데이트 ${esc(B.updated)}</p>`;
    bindNav();
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
        scales: {y: {ticks: {callback: v => v + (unit === "%" ? "%" : "")}, grid: {color: "#eef0f3"}}, x: {grid: {display: false}, ticks: {maxTicksLimit: 12}}}}});
  }
  function barChart(el, labels, values, unit, horizontal, label, multi){
    const sets = multi ? multi.map((d, i) => ({label: d.label, data: d.data, backgroundColor: ["#9aa7b8", "#163a5c", WARM, COOL][i % 4], borderRadius: 4}))
                       : [{label: label || "", data: values, backgroundColor: values.map(v => v >= 0 ? WARM : COOL), borderRadius: 4}];
    return new Chart(el, {type: "bar", data: {labels, datasets: sets},
      options: {indexAxis: horizontal ? "y" : "x", responsive: true, maintainAspectRatio: false,
        plugins: {legend: {display: !!multi, labels: {boxWidth: 12}}, tooltip: {callbacks: {label: c => `${c.dataset.label ? c.dataset.label + ": " : ""}${c.parsed[horizontal ? "x" : "y"]}${unit === "%" ? "%" : unit ? " " + unit : ""}`}}},
        scales: {[horizontal ? "x" : "y"]: {ticks: {callback: v => v + (unit === "%" ? "%" : "")}, grid: {color: "#eef0f3"}}, [horizontal ? "y" : "x"]: {grid: {display: false}}}}});
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
    if(ind.items && Object.keys(ind.items).length){
      const im = [...new Set(Object.values(ind.items).flatMap(o => Object.keys(o)))].sort();
      const ctr = ind.target === 50 ? 50 : 0;   // PMI는 50을 가운데로
      const mx = Math.max(...Object.values(ind.items).flatMap(o => Object.values(o).map(v => Math.abs(v - ctr))));
      h += `<h2>🌡️ 세부 항목 히트맵 <small>${esc(ind.items_label || "")} · 진할수록 강해요</small></h2><div class="panel heat"><table style="min-width:${120 + im.length * 52}px"><tr><th class="l">항목</th>${im.map(m => `<th>${ym(m)}</th>`).join("")}</tr>
        ${Object.entries(ind.items).map(([k, o]) => `<tr><th class="l">${esc(k)}</th>${im.map(m => o[m] == null ? "<td></td>" : `<td style="background:${heatColor(o[m] - ctr, mx)}">${o[m]}</td>`).join("")}</tr>`).join("")}</table></div>`;
    }
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
      ${needsBox(items)}
      <div class="md" id="ec-main"></div>
      ${r.extra ? `<h2>🔎 추가 자료로 본 추가 해석</h2><div class="md xmd" id="ec-extra"></div>` : ""}
      <p class="foot">숫자는 발표 원문 그대로이며, 계산·추정값은 따로 표시해요. 투자 권유가 아닌 공부용 해석이에요.</p>`;
    renderMd(body, document.getElementById("ec-main"));
    if(r.extra) renderMd(r.extra, document.getElementById("ec-extra"));
    bindNav();
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
