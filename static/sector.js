// 주도 섹터 찾기 탭 — /api/sector?market=US|KR (sector.py)
// 한눈에 보기(주도·다음·순환매) → 섹터 지도(미국은 세부 업종까지, 크기=시가총액, 색=시장 대비) → 섹터 순위 → 고른 섹터·업종 설명
// → 더 깊게 보기(경기 국면·RRG·전체 체크표·구분법) / 🧩 테마 보기: /api/sector/themes (themes.py 종목 묶음)
(function(){
  const CHART = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js";
  const PAL = ["#e8590c", "#1c7ed6", "#2b8a3e", "#7c3aed", "#db2777", "#B0883A", "#0e1c36", "#0891b2", "#65a30d", "#dc2626", "#9333ea",
               "#ca8a04", "#0d9488", "#be185d", "#4f46e5", "#ea580c", "#16a34a", "#475569"];
  const QUAD = {"선도": "#2b8a3e", "약화": "#c2410c", "부진": "#b42318", "개선": "#1d4ed8"};
  const PER = [["x1w", "1주"], ["x1m", "1개월"], ["x3m", "3개월"], ["x6m", "6개월"]];
  const SCALE = {x1w: 3, x1m: 6, x3m: 12, x6m: 20};       // 이 %p면 가장 진한 색
  const ST = {market: "US", view: "sector", askT: null, askQ: "", ans: null, asking: false, tdata: {}, th: null, data: {}, per: "x1m", sel: null, sub: null, zoom: null, phase: null, charts: [], poll: null};
  const root = () => document.getElementById("sector-root");
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const pp = (v, d = 1) => v == null ? "–" : (v > 0 ? "+" : "") + v.toFixed(d);
  const tone = v => v == null ? "" : v > 0 ? "sc-up" : v < 0 ? "sc-dn" : "";
  const perName = () => PER.find(p => p[0] === ST.per)[1];
  const mobile = () => document.documentElement.classList.contains("is-mobile") || window.innerWidth < 720;

  function loadScript(src){
    return new Promise((ok, no) => {
      if(window.Chart) return ok();
      const s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = no; document.head.appendChild(s);
    });
  }
  function destroy(){ ST.charts.forEach(c => c.destroy()); ST.charts = []; }
  async function load(force){
    const j = await fetch(`/api/sector?market=${ST.market}${force ? "&force=1" : ""}`).then(r => r.json());
    if(j.error) throw new Error(j.error);
    ST.data[ST.market] = j;
    return j;
  }
  // 시장 대비 %p → 색 (강하면 빨강, 약하면 파랑, 비슷하면 회색)
  function heat(v){
    if(v == null) return "#3b4252";
    const a = Math.min(Math.abs(v) / SCALE[ST.per], 1);
    const mix = (c1, c2, t) => c1.map((x, i) => Math.round(x + (c2[i] - x) * t));
    const base = [59, 66, 82], to = v > 0 ? [201, 42, 42] : [28, 100, 214];
    const [r, g, b] = mix(base, to, .25 + a * .75);
    return `rgb(${r},${g},${b})`;
  }

  // ---------- 머리줄(시장 · 섹터/테마 · 기간) ----------
  function headHtml(){
    return `<div class="sc-head">
      <div class="sc-mk">${["US", "KR"].map(m => `<button type="button" class="${m === ST.market ? "on" : ""}" data-mk="${m}">${m === "US" ? "🇺🇸 미국" : "🇰🇷 한국"}</button>`).join("")}</div>
      <div class="sc-mk sc-view">${[["sector", "🗺️ 섹터"], ["theme", "🧩 테마"]].map(([k, t]) => `<button type="button" class="${k === ST.view ? "on" : ""}" data-view="${k}">${t}</button>`).join("")}</div>
      <div class="sc-per"><span>기간</span>${PER.map(([k, t]) => `<button type="button" class="${k === ST.per ? "on" : ""}" data-per="${k}">${t}</button>`).join("")}</div>
    </div>`;
  }

  // ---------- 테마 화면 ----------
  const KIND = [["new", "🚀 새 성장 산업"], ["old", "🏭 전통 산업"]];
  async function loadThemes(){
    const j = await fetch(`/api/sector/themes?market=${ST.market}`).then(r => r.json());
    if(j.error) throw new Error(j.error);
    if(!j.data) throw new Error(j.error || "테마 계산에 실패했어요");
    ST.tdata[ST.market] = j.data;
    return j.data;
  }
  function renderTheme(){
    const d = ST.tdata[ST.market];
    if(!d){
      root().innerHTML = `${headHtml()}<p class="sc-load"><i class="sc-spin"></i>테마 종목을 계산하는 중이에요(몇 초)…</p>`;
      bind();
      loadThemes().then(() => { if(ST.view === "theme") keep(render); })
        .catch(e => { root().innerHTML = `${headHtml()}<div class="sc-err">테마를 불러오지 못했어요. 잠시 뒤 다시 눌러 주세요. <small>${esc(e.message || e)}</small></div>`; bind(); });
      return;
    }
    const T = d.themes, by = (a, b) => (b[ST.per] ?? -99) - (a[ST.per] ?? -99);
    if(!ST.th || !T.some(t => t.id === ST.th)) ST.th = T.slice().sort(by)[0].id;
    const grp = k => T.filter(t => t.cls === k).sort(by);
    const bench = ST.market === "US" ? "S&P500(SPY)" : "코스피";
    root().innerHTML = `${headHtml()}
    <p class="sc-q1">섹터보다 더 잘게, <b>태양광·광통신·조선 같은 테마</b>가 시장(${bench})보다 센지 약한지 봐요. 테마마다 대표 종목을 같은 비중으로 평균했어요.</p>
    <div class="sc-sum">
      ${tSum("👑 주도 후보", "lead", grp("lead"), "오래 강했고, 종목들이 고르게 오르는 중", t => `3개월 시장보다 ${pp(t.x3m)}%p · 6개월 ${pp(t.x6m)}%p · 종목 ${t.pct200 ?? "–"}%가 상승 추세`)}
      ${tSum("🌱 다음 후보", "imp", grp("imp"), "아직 약하지만 최근 힘이 붙는 중(RRG 개선 구간)", t => `1개월 ${pp(t.x1m)}%p · 3개월 ${pp(t.x3m)}%p`)}
      ${tSum("⚡ 순환매 주의", "rot", grp("rot"), "짧게 확 튀었지만 6개월로 보면 약해요. 오래 못 갈 수 있어요", t => `${(t.x1w ?? 0) >= 5 ? `1주 ${pp(t.x1w)}%p` : `1개월 ${pp(t.x1m)}%p`} 반짝 · 6개월 ${pp(t.x6m)}%p`)}
    </div>
    <div class="sc-two th">
      <div class="sc-panel">
        <div class="sc-h3">🧩 테마 지도 <small>색 = ${perName()} 시장 대비 (빨강 강함 · 파랑 약함) · 센 순서 · 👑 주도 후보 🌱 다음 후보 ⚡ 순환매 주의 · <i class="etf">ETF</i> 투자할 수 있는 ETF 있음 · 누르면 설명</small></div>
        ${KIND.filter(([k]) => T.some(t => t.kind === k)).map(([k, nm]) => `<div class="sc-kind">${nm}</div>
          <div class="sc-tg">${T.filter(t => t.kind === k).sort(by).map(t => `<button type="button" class="${t.id === ST.th ? "on" : ""}" data-th="${esc(t.id)}" style="background:${heat(t[ST.per])}" title="${esc(t.ko)} · ${esc(t.label)}">
            <b>${BADGE[t.cls] || ""}${esc(t.ko)}</b><em>${pp(t[ST.per])}%p${(t.etfs || []).length ? ` <i class="etf">ETF</i>` : ""}</em></button>`).join("")}</div>`).join("")}
        <div class="sc-legend"><span>${perName()} 시장 대비</span><i style="background:${heatAt(-1)}"></i>−${SCALE[ST.per]}%p<i style="background:${heatAt(0)}"></i>0<i style="background:${heatAt(1)}"></i>+${SCALE[ST.per]}%p</div>
      </div>
      <div class="sc-panel" id="sc-detail">${themeDetail(T.find(t => t.id === ST.th))}</div>
    </div>
    ${askHtml()}
    <p class="sc-foot">테마와 종목은 히르찬이 직접 고른 묶음이에요(공식 분류 아님). 평균은 종목마다 같은 비중이라 작은 종목의 움직임도 크게 반영돼요. 참고용 공부 자료이며 투자 권유나 매수·매도 추천이 아니에요.
      데이터: 야후 파이낸스 종목 가격. 계산 ${esc(d.updated)}(2시간마다 새로) · 종목 ${d.n_px}/${d.n}개 받음.</p>`;
    bind();
    const t = T.find(x => x.id === ST.th);
    if(t && t.rs_line) drawRS(t);
  }
  const BADGE = {lead: "👑 ", imp: "🌱 ", rot: "⚡ "};
  function tSum(title, cls, list, sub, why){
    return `<div class="sc-sb ${cls}"><div class="t">${title}</div><div class="s">${sub}</div>
      ${list.length ? `<ul>${list.map(t => `<li data-th="${esc(t.id)}"><b>${esc(t.ko)}</b><span>${why(t)}</span></li>`).join("")}</ul>` : `<p class="none">지금은 없어요</p>`}</div>`;
  }
  const TPLAIN = {
    "주도": "1개월·3개월·6개월 모두 시장보다 강하고, 종목 대부분이 상승 추세예요",
    "강세 유지": "길게도 짧게도 시장보다 강해요. 다만 상승 추세 종목이 아주 많지는 않아요",
    "살아나는 중": "6개월로 보면 약했는데 최근 1개월은 시장보다 강해요. 반짝인지 시작인지 지켜볼 구간이에요",
    "힘 빠지는 중": "6개월로 보면 강했는데 최근 1개월은 시장보다 약해요",
    "부진": "최근 1개월도, 6개월도 시장보다 약해요",
    "자료 부족": "가격 기록이 짧아 판단하기 어려워요",
  };
  function themeDetail(t){
    if(!t) return "";
    const st = t.stocks.slice().sort((a, b) => (b[ST.per] ?? -99) - (a[ST.per] ?? -99));
    return `<div class="sc-h3">🔎 ${esc(t.ko)} <span class="sc-lab ${t.cls}">${esc(t.label)}</span> <small>${t.n_px}종목 · 같은 비중${(t.etfs || []).length ? ` · ETF ${t.etfs.length}개` : ""}</small></div>
      <div class="sc-pers">${PER.map(([k, n]) => `<div><span>${n}</span><b class="${tone(t[k])}">${pp(t[k])}%p</b></div>`).join("")}</div>
      ${(t.checks || []).length ? `<ul class="sc-why">${t.checks.filter(c => c.v != null).map(c => `<li class="${c.v ? "y" : "n"}">${c.v ? "✓" : "✗"} ${PLAIN[c.k][c.v ? 0 : 1]}</li>`).join("")}</ul>
      <p class="sc-cap">체크 ${t.score}/${t.of} · ${t.label === "주도 후보" ? "여러 조건이 함께 받쳐 주고 있어요" : t.label === "순환매 가능성" ? "짧게 튀었지만 받쳐 주는 조건이 적어요" : "RRG 위치: " + (t.quad || "–")}</p>
      <div class="sc-cv sm"><canvas id="sc-rs"></canvas></div>
      <p class="sc-cap">RS선(테마 ÷ 시장, 1년 전 = 100): 오르면 시장보다 강하다는 뜻이에요. 테마 지수는 종목들을 같은 비중으로 묶어 만들었어요.</p>` : `<p class="sc-tl">${esc(TPLAIN[t.label] || "")}</p>`}
      <div class="sc-facts"><span>${perName()} 시장보다 강한 종목 <b>${t["beat_" + ST.per]}/${t.n_px}</b></span>${t.pct200 != null ? `<span>상승 추세(200일선 위) <b>${t.pct200}%</b></span>` : ""}</div>
      <div class="sc-tw"><table class="sc-tb sm"><thead><tr><th class="l">종목</th>${PER.map(p => `<th class="${p[0] === ST.per ? "cur" : ""}">${p[1]}</th>`).join("")}</tr></thead><tbody>
      ${st.map(s => `<tr><td class="l"><b>${esc(ST.market === "US" ? s.sym : s.name)}</b><small>${esc(ST.market === "US" ? s.name : s.sym)}${s.a200 === true ? " · 상승 추세" : s.a200 === false ? " · 200일선 아래" : ""}</small></td>
        ${PER.map(p => `<td class="${tone(s[p[0]])} ${p[0] === ST.per ? "cur" : ""}">${pp(s[p[0]])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
      <div class="sc-h3" style="margin-top:14px">💼 이 테마에 투자할 수 있는 ETF</div>
      ${(t.etfs || []).length ? `<div class="sc-tw"><table class="sc-tb sm sc-etf"><thead><tr><th class="l">ETF</th>${PER.map(p => `<th class="${p[0] === ST.per ? "cur" : ""}">${p[1]}</th>`).join("")}</tr></thead><tbody>
        ${t.etfs.map(s => `<tr><td class="l"><b>${esc(ST.market === "US" ? s.sym : s.name)}</b><small>${esc(ST.market === "US" ? s.name : s.sym)}</small></td>
        ${PER.map(p => `<td class="${tone(s[p[0]])} ${p[0] === ST.per ? "cur" : ""}">${pp(s[p[0]])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
        <p class="sc-cap">ETF는 위 종목 묶음과 담은 종목·비중이 달라 성과가 다를 수 있어요. 들어 있는 종목·보수는 운용사 자료로 꼭 확인하세요.</p>`
        : `<p class="sc-cap">이 테마만 따로 담은 ETF는 찾지 못했어요.</p>`}
      <p class="sc-cap">수익률은 모두 ${ST.market === "US" ? "S&P500(SPY)" : "코스피"} 대비(%p)예요. 종목·ETF가 들어 있다고 매수 추천이 아니에요.</p>`;
  }

  // ---------- 💬 왜 움직였나 물어보기 ----------
  function askTargets(){
    const out = [], th = ST.tdata[ST.market], sd = ST.data[ST.market];
    if(th) out.push(["🧩 테마", th.themes.map(t => [`theme:${t.id}`, t.ko])]);
    if(sd) out.push(["🗺️ 섹터", sd.rows.filter(r => !r.error).map(r => [`sector:${r.sym}`, r.name])]);
    return out;
  }
  function askCur(){
    if(ST.askT) return ST.askT;
    return ST.view === "theme" ? (ST.th ? `theme:${ST.th}` : "") : (ST.sel ? `sector:${ST.sel}` : "");
  }
  const ASK_CHIPS = ["최근 주가가 왜 좋았나요?", "최근 왜 약했나요?", "이번 움직임, 오래갈 힘일까요?", "앞으로 무엇을 보면 좋을까요?"];
  function askHtml(){
    const cur = askCur(), tg = askTargets();
    const nm = (tg.flatMap(g => g[1]).find(o => o[0] === cur) || [])[1] || "";
    return `<div class="sc-ask" id="sc-ask">
      <div class="sc-h3 big">💬 왜 움직였는지 물어보기 <small>고른 테마·섹터의 대표 종목 최근 한 달 뉴스를 AI가 읽고 답해요 · 회원 전용</small></div>
      <div class="sc-ask-row">
        <select id="sc-ask-t">${tg.map(([g, os]) => `<optgroup label="${g}">${os.map(([v, n]) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(n)}</option>`).join("")}</optgroup>`).join("")}</select>
        <input id="sc-ask-q" type="text" maxlength="150" value="${esc(ST.askQ)}" placeholder="예: ${esc(nm || "항공기·엔진")} 주가가 최근 왜 좋았나요?">
        <button type="button" id="sc-ask-go" ${ST.asking ? "disabled" : ""}>${ST.asking ? "답 만드는 중…" : "물어보기"}</button>
      </div>
      <div class="sc-ask-chips">${ASK_CHIPS.map(c => `<button type="button" data-chip="${esc(c)}">${esc(c)}</button>`).join("")}</div>
      <div id="sc-ans">${ansHtml()}</div>
    </div>`;
  }
  function ansHtml(){
    if(ST.asking) return `<p class="sc-load"><i class="sc-spin"></i>대표 종목 뉴스를 모아 읽는 중이에요(10~30초)…</p>`;
    const a = ST.ans; if(!a) return "";
    if(a.error) return `<div class="sc-err">${esc(a.error)}${a.locked ? ` <a href="#" onclick="var b=document.querySelector('[data-open=login]');if(b)b.click();return false">로그인하기</a>` : ""}</div>`;
    const TONE = {"긍정": "y", "부정": "n", "중립": ""};
    return `<div class="sc-ans">
      <div class="sc-ans-q">Q. ${esc(a.target)} — ${esc(a.q)}</div>
      <p class="sc-ans-a">${esc(a.answer)}</p>
      ${(a.reasons || []).length ? `<ol class="sc-ans-r">${a.reasons.map(r => `<li><b>${esc(r.title)}</b> <span class="sc-tone ${TONE[r.tone] ?? ""}">${esc(r.tone || "")}</span>
        <p>${esc(r.detail)}</p>${(r.stocks || []).length ? `<small>관련: ${r.stocks.map(esc).join(" · ")}</small>` : ""}</li>`).join("")}</ol>` : ""}
      ${a.watch ? `<p class="sc-ans-w">👀 같이 보면 좋은 점: ${esc(a.watch)}</p>` : ""}
      <details class="sc-ans-src"><summary>근거로 읽은 뉴스 제목 ${a.n_news}개</summary>
        ${(a.sources || []).map(s => `<div><b>${esc(s.name)}</b> <small>${esc(s.code)}</small><ul>${s.news.length ? s.news.map(n => `<li><span>${esc(n.d)}</span> ${esc(n.t)}</li>`).join("") : "<li>최근 뉴스 없음</li>"}</ul></div>`).join("")}
      </details>
      <p class="sc-cap">AI가 뉴스 제목과 수익률만 보고 정리한 답이라 틀리거나 빠진 이유가 있을 수 있어요. 공부용 참고이며 투자 권유가 아니에요. ${esc(a.at || "")} 기준</p>
    </div>`;
  }
  async function askGo(){
    const t = (document.getElementById("sc-ask-t") || {}).value || "", q = (document.getElementById("sc-ask-q") || {}).value.trim();
    ST.askQ = q;
    if(!t){ ST.ans = {error: "물어볼 테마·섹터를 골라 주세요."}; return keepAsk(); }
    if(!q){ ST.ans = {error: "질문을 써 주세요. 아래 예시를 눌러도 돼요."}; return keepAsk(); }
    const [kind, id] = t.split(/:(.+)/);
    ST.asking = true; ST.ans = null; keepAsk();
    try{
      const r = await fetch("/api/sector/ask", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({market: ST.market, kind, id, q})});
      ST.ans = await r.json();
    }catch(e){ ST.ans = {error: "답을 받지 못했어요. 잠시 뒤 다시 물어봐 주세요."}; }
    ST.asking = false; keepAsk();
  }
  function keepAsk(){   // 질문 칸만 다시 그림(입력값·스크롤 유지)
    const el = document.getElementById("sc-ask"); if(!el) return;
    el.outerHTML = askHtml(); bindAsk();
  }
  function bindAsk(){
    const sel = document.getElementById("sc-ask-t"), q = document.getElementById("sc-ask-q"), go = document.getElementById("sc-ask-go");
    if(!sel) return;
    sel.onchange = () => { ST.askT = sel.value; };
    q.oninput = () => { ST.askQ = q.value; };
    q.onkeydown = e => { if(e.key === "Enter" && !e.isComposing){ e.preventDefault(); askGo(); } };
    go.onclick = askGo;
    document.querySelectorAll("#sc-ask [data-chip]").forEach(b => b.onclick = () => { q.value = ST.askQ = b.dataset.chip; q.focus(); });
  }

  // ---------- 화면 ----------
  function render(){
    destroy();
    if(ST.view === "theme") return renderTheme();
    const d = ST.data[ST.market]; if(!d) return;
    const rows = d.rows.filter(r => !r.error);
    if(!ST.sel || !rows.some(r => r.sym === ST.sel)) ST.sel = (rows.slice().sort((a, b) => (b.x3m ?? -99) - (a.x3m ?? -99))[0] || {}).sym;
    const subs = d.subs || null, br = d.breadth || {};
    const grp = k => rows.filter(r => r.cls === k);
    root().innerHTML = `
    ${headHtml()}
    <p class="sc-q1">지금 <b>시장(${esc(d.bench)})보다 센 섹터</b>는 어디고, 그 힘이 <b>오래갈 힘(주도)</b>인지 <b>잠깐 반짝(순환매)</b>인지 봐요. <span>기준 ${esc(d.last)}</span></p>

    <div class="sc-sum">
      ${sumBox("👑 주도 후보", "lead", grp("lead"), "오래 강했고, 종목들이 고르게 오르고, 이익 전망도 올라가는 중", r => `3개월 시장보다 ${pp(r.x3m)}%p${r.breadth && r.breadth.pct200 != null ? ` · 종목 ${r.breadth.pct200}%가 상승 추세` : ""}${r.breadth && r.breadth.rev_ratio != null ? ` · 이익 전망 상향 ${r.breadth.rev_ratio}%` : ""}`)}
      ${sumBox("🌱 다음 후보", "imp", grp("imp"), "아직 약하지만 최근 힘이 붙는 중(RRG 개선 구간)", r => `1개월 ${pp(r.x1m)}%p · 3개월 ${pp(r.x3m)}%p`)}
      ${sumBox("⚡ 순환매 주의", "rot", grp("rot"), "짧게 튀었지만 길게 보면 약해요. 오래 못 갈 수 있어요", r => `1개월 ${pp(r.x1m)}%p 반짝 · 6개월 ${pp(r.x6m)}%p`)}
    </div>

    <div class="sc-h2">🗺️ 섹터 지도 <small>${ST.market === "US" ? "크기 = 시가총액" : "업종 ETF"} · 색 = ${perName()} 시장 대비 (빨강 강함 · 파랑 약함) · 누르면 아래에 자세히</small></div>
    ${ST.market === "US" && !subs ? `<p class="sc-note run"><i class="sc-spin"></i>세부 업종(S&P500 500종목)을 계산하고 있어요(1~2분). 끝나면 지도에 세부 업종이 채워져요.</p>` : ""}
    ${ST.zoom ? `<button type="button" class="sc-back" data-zoom="">← 전체 지도</button>` : ""}
    <div class="sc-map" id="sc-map"></div>
    <div class="sc-legend"><span>${perName()} 시장 대비</span><i style="background:${heatAt(-1)}"></i>−${SCALE[ST.per]}%p<i style="background:${heatAt(0)}"></i>0<i style="background:${heatAt(1)}"></i>+${SCALE[ST.per]}%p</div>

    <div class="sc-two">
      <div class="sc-panel"><div class="sc-h3">📊 섹터 순위 <small>${perName()} 시장 대비 · 누르면 오른쪽에 설명</small></div><div id="sc-rank"></div></div>
      <div class="sc-panel" id="sc-detail"></div>
    </div>

    <details class="sc-deep" ${ST.deep ? "open" : ""}><summary>🔍 더 깊게 보기 <small>경기 국면 · RRG(상대회전그래프) · 전체 체크표 · 주도 vs 순환매 구분법</small></summary>
      ${deepHtml(d, rows, br)}
    </details>
    ${askHtml()}
    <p class="sc-foot">참고 신호는 정해진 규칙으로 계산한 공부용이며, 투자 권유나 매수·매도 추천이 아니에요. 데이터: 야후 파이낸스(섹터 ETF·지수·종목 가격·시가총액·애널리스트 추정), FRED, 위키백과(S&P500 구성 종목·세부 업종).
      ${ST.market === "US" ? `세부 업종 ${br.updated ? esc(br.updated) + " 계산" : ""}(6시간마다 새로).` : "한국은 업종 ETF 기준이라 세부 업종·종목 확산·이익 추정이 없어요."} 계산 ${esc(d.updated)}</p>`;
    drawMap(d, rows, subs);
    drawRank(rows);
    drawDetail(d, rows, subs);
    bind();
    const dp = root().querySelector(".sc-deep");
    dp.addEventListener("toggle", () => { ST.deep = dp.open; if(dp.open && !ST.deepDrawn) drawDeep(d, rows); });
    if(dp.open) drawDeep(d, rows);
  }
  const heatAt = t => { const p = ST.per; return t === 0 ? heat(0) : heat(t * SCALE[p]); };
  function sumBox(t, cls, list, sub, why){
    return `<div class="sc-sb ${cls}"><div class="t">${t}</div><div class="s">${sub}</div>
      ${list.length ? `<ul>${list.map(r => `<li data-sel="${esc(r.sym)}"><b>${esc(r.name)}</b><span>${why(r)}</span></li>`).join("")}</ul>` : `<p class="none">지금은 없어요</p>`}</div>`;
  }

  // ---------- 섹터 지도(트리맵) ----------
  function squarify(items, x, y, w, h){
    // items: [{v, ...}] 큰 것부터 → 각 항목에 x,y,w,h
    const out = [], total = items.reduce((a, b) => a + b.v, 0); if(!total || w <= 0 || h <= 0) return out;
    let rest = items.map(it => ({...it, a: it.v / total * w * h})), X = x, Y = y, W = w, H = h;
    const worst = (row, len) => { const s = row.reduce((a, b) => a + b.a, 0); const mx = Math.max(...row.map(r => r.a)), mn = Math.min(...row.map(r => r.a));
      return Math.max(len * len * mx / (s * s), (s * s) / (len * len * mn)); };
    while(rest.length){
      const len = Math.min(W, H); let row = [rest[0]], i = 1;
      while(i < rest.length && worst(row.concat(rest[i]), len) <= worst(row, len)){ row.push(rest[i]); i++; }
      const s = row.reduce((a, b) => a + b.a, 0);
      if(W >= H){ const cw = s / H; let cy = Y; row.forEach(r => { const rh = r.a / cw; out.push({...r, x: X, y: cy, w: cw, h: rh}); cy += rh; }); X += cw; W -= cw; }
      else { const ch = s / W; let cx = X; row.forEach(r => { const rw = r.a / ch; out.push({...r, x: cx, y: Y, w: rw, h: ch}); cx += rw; }); Y += ch; H -= ch; }
      rest = rest.slice(i);
    }
    return out;
  }
  function drawMap(d, rows, subs){
    const el = document.getElementById("sc-map"); if(!el) return;
    const W = el.clientWidth || 800, H = ST.zoom ? (mobile() ? 520 : 560) : (mobile() ? 560 : 600);
    el.style.height = H + "px";
    const secCap = {};
    (subs || []).forEach(s => { secCap[s.sector_ko] = (secCap[s.sector_ko] || 0) + (s.mcap || 0); });
    let html = "";
    const tile = (r, cls, body, attrs, title) => `<div class="sc-t ${cls}" style="left:${r.x}px;top:${r.y}px;width:${Math.max(r.w - 2, 0)}px;height:${Math.max(r.h - 2, 0)}px;background:${r.bg || "transparent"}" ${attrs} title="${esc(title)}">${body}</div>`;
    const label = (r, name, v) => r.w > 58 && r.h > 30 ? `<b style="font-size:${Math.max(11, Math.min(20, Math.sqrt(r.w * r.h) / 7))}px">${esc(name)}</b><em>${pp(v)}%p</em>` : r.w > 30 && r.h > 16 ? `<em>${pp(v, 0)}</em>` : "";
    if(ST.market === "US" && subs){
      // 섹터 → 세부 업종 (확대하면 한 섹터만)
      const secs = rows.filter(r => !ST.zoom || r.sym === ST.zoom).map(r => ({r, v: secCap[r.name] || 1})).sort((a, b) => b.v - a.v);
      const showSubs = !(mobile() && !ST.zoom);
      squarify(secs, 0, 0, W, H).forEach(S => {
        const r = S.r, hd = showSubs ? 20 : 0;
        if(showSubs){
          html += tile({x: S.x, y: S.y, w: S.w, h: hd + 1}, "sec-h", S.w > 70 ? `${esc(r.name)} <em class="${tone(r[ST.per])}">${pp(r[ST.per])}%p</em>` : "", `data-zoom="${esc(r.sym)}"`, `${r.name} ${pp(r[ST.per])}%p · 눌러서 크게`);
          const kids = subs.filter(s => s.sector_ko === r.name).map(s => ({s, v: s.mcap || 1})).sort((a, b) => b.v - a.v);
          squarify(kids, S.x, S.y + hd, S.w, S.h - hd).forEach(K => {
            const s = K.s, v = s[ST.per];
            html += tile({...K, bg: heat(v)}, "sub " + (ST.sub === s.sub ? "on" : ""), label(K, s.sub_ko, v), `data-sub="${esc(s.sub)}"`, `${s.sub_ko}(${s.sub}) · ${perName()} 시장 대비 ${pp(v)}%p · ${s.n}종목`);
          });
          html += tile({x: S.x, y: S.y, w: S.w, h: S.h}, "sec-b", "", "", "");
        } else {
          const v = r[ST.per];
          html += tile({...S, bg: heat(v)}, "sec " + (ST.sel === r.sym ? "on" : ""), label(S, r.name, v), `data-zoom="${esc(r.sym)}"`, `${r.name} · ${perName()} 시장 대비 ${pp(v)}%p · 눌러서 세부 업종 보기`);
        }
      });
    } else {
      // 섹터만(한국, 또는 세부 업종 계산 전): 같은 크기, 강한 순서
      const items = rows.map(r => ({r, v: 1})).sort((a, b) => (b.r[ST.per] ?? -99) - (a.r[ST.per] ?? -99));
      squarify(items, 0, 0, W, H).forEach(S => {
        const r = S.r, v = r[ST.per];
        html += tile({...S, bg: heat(v)}, "sec " + (ST.sel === r.sym ? "on" : ""), label(S, r.name, v), `data-sel="${esc(r.sym)}"`, `${r.name} · ${perName()} 시장 대비 ${pp(v)}%p`);
      });
    }
    el.innerHTML = html;
  }

  // ---------- 섹터 순위(막대) ----------
  function drawRank(rows){
    const el = document.getElementById("sc-rank"); if(!el) return;
    const rs = rows.slice().sort((a, b) => (b[ST.per] ?? -99) - (a[ST.per] ?? -99));
    const mx = Math.max(1, ...rs.map(r => Math.abs(r[ST.per] || 0)));
    el.innerHTML = rs.map((r, i) => { const v = r[ST.per] || 0, w = Math.abs(v) / mx * 50;
      return `<div class="sc-bar ${r.sym === ST.sel ? "on" : ""}" data-sel="${esc(r.sym)}"><span class="nm">${i + 1}. ${esc(r.name)}</span>
        <span class="tr"><i style="${v >= 0 ? `left:50%;width:${w}%` : `left:${50 - w}%;width:${w}%`};background:${v >= 0 ? "#d63939" : "#1c64d6"}"></i></span>
        <span class="v ${tone(v)}">${pp(r[ST.per])}</span><span class="sc-lab ${r.cls}">${esc(r.label)}</span></div>`; }).join("");
  }

  // ---------- 고른 섹터·업종 설명 ----------
  const PLAIN = {
    rs36: ["3개월·6개월 모두 시장보다 강해요", "3개월·6개월 중 시장보다 약한 때가 있어요"],
    ma50: ["요즘 상대강도가 평균보다 위예요", "요즘 상대강도가 평균보다 아래예요"],
    high: ["최근 상대강도 1년 최고치를 찍었어요", "상대강도 1년 최고치와는 거리가 있어요"],
    def: ["시장이 빠질 때 덜 빠졌어요", "시장이 빠질 때 같이(더) 빠졌어요"],
    turn: ["거래대금이 늘고 있어요", "거래대금이 늘지 않아요"],
    brd: ["종목 절반 넘게 상승 추세(200일선 위)예요", "상승 추세 종목이 절반이 안 돼요"],
    eps: ["애널리스트가 이익 전망을 올리는 쪽이 많아요", "이익 전망을 내리는 쪽이 많거나 비슷해요"],
  };
  function drawDetail(d, rows, subs){
    const el = document.getElementById("sc-detail"); if(!el) return;
    const s = ST.sub && subs ? subs.find(x => x.sub === ST.sub) : null;
    if(s){
      el.innerHTML = `<div class="sc-h3">🔎 ${esc(s.sub_ko)} <small>${esc(s.sector_ko)} · ${esc(s.sub)} · ${s.n}종목</small></div>
        <div class="sc-pers">${PER.map(([k, t]) => `<div><span>${t}</span><b class="${tone(s[k])}">${pp(s[k])}%p</b></div>`).join("")}</div>
        <div class="sc-facts">${s.pct200 != null ? `<span>상승 추세(200일선 위) <b>${s.pct200}%</b></span>` : ""}${s.rev_ratio != null ? `<span>이익 전망 상향 <b>${s.rev_ratio}%</b> <small>↑${s.up} ↓${s.down}</small></span>` : ""}<span>최근 1주 신고가 <b>${s.hi}</b>종목</span><span>시가총액 <b>${fmtCap(s.mcap)}</b></span></div>
        <div class="sc-tw"><table class="sc-tb sm"><thead><tr><th class="l">대표 종목</th><th>시가총액</th>${PER.slice(0, 3).map(p => `<th>${p[1]}</th>`).join("")}</tr></thead><tbody>
        ${s.stocks.map(t => `<tr><td class="l"><b>${esc(t.sym)}</b><small>${esc(t.name)}</small></td><td>${fmtCap(t.mcap)}</td>${PER.slice(0, 3).map(p => `<td class="${tone(t[p[0]])}">${pp(t[p[0]])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
        <p class="sc-cap">수익률은 모두 S&P500 대비(%p), 업종 값은 시가총액 가중이에요. <a href="#" data-sub="">← ${esc(s.sector_ko)} 섹터 설명으로</a></p>`;
      return;
    }
    const r = rows.find(x => x.sym === ST.sel); if(!r){ el.innerHTML = ""; return; }
    const kids = subs ? subs.filter(x => x.sector_ko === r.name).sort((a, b) => (b[ST.per] ?? -99) - (a[ST.per] ?? -99)) : [];
    el.innerHTML = `<div class="sc-h3">${esc(r.name)} <span class="sc-lab ${r.cls}">${esc(r.label)}</span> <small>${esc(ST.market === "US" ? r.sym : r.note)}</small></div>
      <div class="sc-pers">${PER.map(([k, t]) => `<div><span>${t}</span><b class="${tone(r[k])}">${pp(r[k])}%p</b></div>`).join("")}</div>
      <ul class="sc-why">${r.checks.filter(c => c.v != null).map(c => `<li class="${c.v ? "y" : "n"}">${c.v ? "✓" : "✗"} ${PLAIN[c.k][c.v ? 0 : 1]}</li>`).join("")}</ul>
      <p class="sc-cap">체크 ${r.score}/${r.of} · ${r.label === "주도 후보" ? "여러 조건이 함께 받쳐 주고 있어요" : r.label === "순환매 가능성" ? "짧은 힘에 비해 받쳐 주는 조건이 적어요" : "RRG 위치: " + (r.quad || "–")}</p>
      <div class="sc-cv sm"><canvas id="sc-rs"></canvas></div>
      <p class="sc-cap">RS선(섹터 ÷ 시장, 1년 전 = 100): 오르면 시장보다 강하다는 뜻이에요.</p>
      ${kids.length ? `<div class="sc-h3" style="margin-top:12px">세부 업종 <small>${perName()} 시장 대비 · 누르면 대표 종목</small></div>
        <div class="sc-kids">${kids.map(k => `<button type="button" data-sub="${esc(k.sub)}"><span>${esc(k.sub_ko)}</span><b class="${tone(k[ST.per])}">${pp(k[ST.per])}</b></button>`).join("")}</div>` : ""}`;
    drawRS(r);
  }
  const fmtCap = v => v == null ? "–" : v >= 1000 ? (v / 1000).toFixed(2) + "조$" : Math.round(v) + "십억$";
  function drawRS(r){
    const el = document.getElementById("sc-rs"); if(!el || !r || !window.Chart) return;
    const ma = Object.fromEntries(r.rs_ma);
    ST.charts.push(new Chart(el, {type: "line", data: {labels: r.rs_line.map(p => p[0].slice(2).replace(/-/g, ".")), datasets: [
        {label: "RS선", data: r.rs_line.map(p => p[1]), borderColor: "#0e1c36", borderWidth: 2, pointRadius: 0, tension: .15},
        {label: "50일 평균", data: r.rs_line.map(p => ma[p[0]] ?? null), borderColor: "#B0883A", borderWidth: 1.5, borderDash: [5, 4], pointRadius: 0}]},
      options: {responsive: true, maintainAspectRatio: false, animation: false, interaction: {mode: "index", intersect: false},
        plugins: {legend: {labels: {boxWidth: 10, font: {size: 11}}}}, scales: {x: {ticks: {maxTicksLimit: 5, font: {size: 10}}, grid: {display: false}}, y: {ticks: {font: {size: 10}}, grid: {color: "#eef0f3"}}}}}));
  }

  // ---------- 더 깊게 보기 ----------
  function deepHtml(d, rows, br){
    return `<div class="sc-h3 big">① 경기 국면으로 후보 좁히기 <small>국면을 누르면 해당 섹터가 아래 표에 표시돼요 · 국면은 직접 판단해요</small></div>
      <div class="sc-phase">${d.phases.map(p => `<button type="button" class="sc-ph ${ST.phase === p.id ? "on" : ""}" data-ph="${p.id}">
        <b>${esc(p.name)}</b><span>${esc(p.desc)}</span><em>${esc(ST.market === "US" ? p.us : rows.filter(r => r.phases.includes(p.id)).map(r => r.name).join(" · "))}</em></button>`).join("")}</div>
      <div class="sc-macro">${d.macro.map(m => `<div class="sc-mc"><span>${esc(m.k)}</span>
        <b>${m.v == null ? "–" : esc(m.v) + (m.u === "%" || m.u === "%p" ? m.u : "")}</b>
        ${m.chg != null ? `<em class="${tone(m.chg)}">3개월 ${pp(m.chg, m.chg_u === "%" ? 1 : 2)}${m.chg_u === "%" ? "%" : m.u === "%p" ? "%p" : ""}</em>` : ""}
        <small>${m.econ && m.v == null ? "경제지표 해석 탭에 ISM 해석이 올라오면 여기 보여요" : esc(m.hint)}</small><i>${esc(m.src)}${m.d ? " · " + esc(m.d) : ""}</i></div>`).join("")}</div>
      <div class="sc-h3 big">② RRG(상대회전그래프) <small>최근 8주 꼬리 · 큰 점이 이번 주 · 점을 누르면 위 설명이 바뀌어요</small></div>
      <div class="sc-panel"><div class="sc-cv sq"><canvas id="sc-rrg"></canvas></div>
        <p class="sc-cap">가로 = 상대강도, 세로 = 그 모멘텀(100이 시장과 같음). 섹터는 보통 시계 방향으로 <span style="color:${QUAD["개선"]}">개선</span> → <span style="color:${QUAD["선도"]}">선도</span> → <span style="color:${QUAD["약화"]}">약화</span> → <span style="color:${QUAD["부진"]}">부진</span>을 돌아요. 개선에서 선도로 넘어가는 섹터가 순환매의 다음 타자 후보예요(JdK 방식 근사).</p></div>
      <div class="sc-h3 big">③ 전체 체크표 <small>✓ 해당 · ✗ 아님 · – 자료 없음</small></div>
      <div class="sc-panel sc-tw"><table class="sc-tb sc-ck"><thead><tr><th class="l">섹터</th>${PER.map(p => `<th>${p[1]}</th>`).join("")}
        ${(rows[0] ? rows[0].checks : []).map(c => `<th>${esc(c.t)}</th>`).join("")}</tr></thead><tbody>
        ${rows.slice().sort((a, b) => (b.score / (b.of || 1)) - (a.score / (a.of || 1))).map(r => `<tr class="${ST.phase && r.phases.includes(ST.phase) ? "ph" : ""}" data-sel="${esc(r.sym)}">
          <td class="l"><b>${esc(r.name)}</b><small><span class="sc-lab ${r.cls}">${esc(r.label)}</span></small></td>
          ${PER.map(p => `<td class="${tone(r[p[0]])}">${pp(r[p[0]])}</td>`).join("")}
          ${r.checks.map(c => `<td class="ck ${c.v === true ? "y" : c.v === false ? "n" : ""}">${c.v === true ? "✓" : c.v === false ? "✗" : "–"}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
      <div class="sc-h3 big">④ 주도 섹터 vs 순환매 섹터 구분법</div>
      <div class="sc-panel sc-tw"><table class="sc-tb sc-rule"><thead><tr><th class="l">구분</th><th>👑 주도 섹터</th><th>⚡ 순환매 섹터</th></tr></thead><tbody>
        <tr><td class="l">상승 지속</td><td>수개월~수년</td><td>수일~수주</td></tr><tr><td class="l">이익 전망</td><td>꾸준히 상향</td><td>거의 그대로, 밸류에이션 따라잡기</td></tr>
        <tr><td class="l">조정 시</td><td>덜 빠지고 먼저 회복</td><td>같이 빠지거나 더 빠짐</td></tr><tr><td class="l">확산</td><td>대형·중소형 고르게 상승</td><td>일부 종목만 급등</td></tr>
        <tr><td class="l">거래대금</td><td>꾸준히 증가</td><td>단기 급증 후 감소</td></tr></tbody></table></div>
      <div class="sc-one">한 줄 정리: <b>RS가 강하면서 이익 상향과 확산이 같이 붙으면 주도 섹터</b>, RS만 잠깐 튀고 이익이 안 따라오면 순환매로 봐요.</div>
      <p class="sc-cap">🗓️ 실전 루틴: 매주 한 번 지도에서 1주·1개월·3개월 색을 바꿔 보고 → RRG에서 위치가 어떻게 돌았는지 확인한 뒤 → 위 섹터만 골라 체크(이익 전망·확산·거래대금)를 봐요.
        외국인·기관 업종별 순매수·ETF 자금 유입은 무료로 꾸준히 받을 곳이 없어 거래대금 변화로 대신했어요.</p>`;
  }
  const quadPlugin = {id: "scQuad", beforeDraw(c){
    const {ctx, chartArea: a, scales: {x, y}} = c; if(!a) return;
    const cx = Math.min(Math.max(x.getPixelForValue(100), a.left), a.right), cy = Math.min(Math.max(y.getPixelForValue(100), a.top), a.bottom);
    const fill = (x0, y0, x1, y1, col) => { ctx.fillStyle = col; ctx.fillRect(x0, y0, x1 - x0, y1 - y0); };
    ctx.save();
    fill(cx, a.top, a.right, cy, "rgba(43,138,62,.08)"); fill(cx, cy, a.right, a.bottom, "rgba(234,179,8,.10)");
    fill(a.left, cy, cx, a.bottom, "rgba(180,35,24,.07)"); fill(a.left, a.top, cx, cy, "rgba(29,78,216,.07)");
    ctx.font = "800 12px Pretendard, sans-serif"; ctx.globalAlpha = .75;
    ctx.fillStyle = QUAD["선도"]; ctx.textAlign = "right"; ctx.fillText("선도", a.right - 6, a.top + 16);
    ctx.fillStyle = QUAD["약화"]; ctx.fillText("약화", a.right - 6, a.bottom - 8);
    ctx.fillStyle = QUAD["부진"]; ctx.textAlign = "left"; ctx.fillText("부진", a.left + 6, a.bottom - 8);
    ctx.fillStyle = QUAD["개선"]; ctx.fillText("개선", a.left + 6, a.top + 16);
    ctx.restore();
  }};
  const labelPlugin = {id: "scLabel", afterDatasetsDraw(c){
    const {ctx} = c; ctx.save(); ctx.font = "800 11px Pretendard, sans-serif"; ctx.textAlign = "left";
    c.data.datasets.forEach((ds, i) => { const m = c.getDatasetMeta(i); if(m.hidden || !m.data.length) return;
      const p = m.data[m.data.length - 1]; ctx.fillStyle = ds.borderColor; ctx.globalAlpha = ds._dim ? .35 : 1; ctx.fillText(ds.label, p.x + 7, p.y - 6); });
    ctx.restore();
  }};
  function drawDeep(d, rows){
    ST.deepDrawn = true;
    const el = document.getElementById("sc-rrg"); if(!el || !window.Chart) return;
    const pts = rows.flatMap(r => r.rrg.map(p => [p.x, p.y])).filter(p => p[0] != null);
    const lim = Math.max(1.5, ...pts.map(p => Math.max(Math.abs(p[0] - 100), Math.abs(p[1] - 100)))) * 1.12;
    const ds = rows.map((r, i) => { const col = PAL[i % PAL.length], hi = r.sym === ST.sel || (ST.phase && r.phases.includes(ST.phase)), dim = (ST.phase && !r.phases.includes(ST.phase)) || (!ST.phase && r.sym !== ST.sel && rows.length > 12);
      return {label: r.name, data: r.rrg.map(p => ({x: p.x, y: p.y, d: p.d})), showLine: true, borderColor: col, backgroundColor: col, _dim: dim,
        borderWidth: hi ? 2.8 : 1.3, pointRadius: r.rrg.map((_, j) => j === r.rrg.length - 1 ? (hi ? 7 : 5) : 2), tension: .3,
        segment: {borderColor: () => dim ? col + "40" : col}, pointBackgroundColor: r.rrg.map(() => dim ? col + "40" : col)}; });
    ST.charts.push(new Chart(el, {type: "scatter", data: {datasets: ds}, plugins: [quadPlugin, labelPlugin],
      options: {responsive: true, maintainAspectRatio: false, animation: false,
        plugins: {legend: {display: false}, tooltip: {callbacks: {label: c => `${c.dataset.label} ${c.raw.d}: 강도 ${c.raw.x} · 모멘텀 ${c.raw.y}`}}},
        onClick: (e, els) => { if(els.length){ ST.sel = rows[els[0].datasetIndex].sym; ST.sub = null; keep(render); } },
        scales: {x: {min: 100 - lim, max: 100 + lim, title: {display: true, text: "상대강도 →"}, grid: {color: "#eef0f3"}},
                 y: {min: 100 - lim, max: 100 + lim, title: {display: true, text: "모멘텀 →"}, grid: {color: "#eef0f3"}}}}}));
  }

  function bind(){
    const R = root();
    bindAsk();
    R.querySelectorAll("[data-mk]").forEach(b => b.onclick = () => { if(b.dataset.mk !== ST.market){ ST.market = b.dataset.mk; ST.phase = null; ST.sel = null; ST.sub = null; ST.zoom = null; ST.th = null; ST.askT = null; ST.ans = null; if(ST.view === "theme") keep(render); else open(); } });
    R.querySelectorAll("[data-view]").forEach(b => b.onclick = () => { if(b.dataset.view !== ST.view){ ST.view = b.dataset.view; clearTimeout(ST.poll); if(ST.view === "sector" && !ST.data[ST.market]) open(); else { keep(render); if(ST.view === "sector") pollBreadth(); } } });
    R.querySelectorAll("[data-th]").forEach(b => b.onclick = e => { e.preventDefault(); ST.th = b.dataset.th; ST.askT = null; keep(render); toDetail(b.tagName === "LI"); });
    R.querySelectorAll("[data-per]").forEach(b => b.onclick = () => { ST.per = b.dataset.per; keep(render); });
    R.querySelectorAll("[data-ph]").forEach(b => b.onclick = () => { ST.phase = ST.phase === b.dataset.ph ? null : b.dataset.ph; keep(render); });
    R.querySelectorAll("[data-sel]").forEach(b => b.onclick = e => { e.preventDefault(); ST.sel = b.dataset.sel; ST.sub = null; ST.askT = null; keep(render); toDetail(b.tagName === "LI"); });
    R.querySelectorAll("[data-sub]").forEach(b => b.onclick = e => { e.preventDefault(); ST.sub = b.dataset.sub || null;
      if(ST.sub){ const s = (ST.data.US.subs || []).find(x => x.sub === ST.sub); const r = s && ST.data.US.rows.find(x => x.name === s.sector_ko); if(r) ST.sel = r.sym; }
      keep(render); toDetail(); });
    R.querySelectorAll("[data-zoom]").forEach(b => b.onclick = () => { const z = b.dataset.zoom || null; ST.zoom = z; if(z){ ST.sel = z; ST.sub = null; } keep(render); });
  }
  function keep(fn){ const y = window.scrollY; fn(); window.scrollTo(0, y); }
  function toDetail(force){   // 모바일은 설명이 아래에 있어 보이게 내려 줌, 위 주도·다음·순환매 칸에서 누르면 PC도 내려 줌
    if(!mobile() && !force) return;
    const el = document.getElementById("sc-detail"), sb = document.querySelector(".sidebar");
    if(el) window.scrollTo({top: el.getBoundingClientRect().top + window.scrollY - (mobile() && sb ? sb.offsetHeight : 0) - 10, behavior: "smooth"});
  }

  async function open(){
    clearTimeout(ST.poll); ST.deepDrawn = false;
    if(!ST.data[ST.market]) root().innerHTML = `<p class="sc-load"><i class="sc-spin"></i>섹터 데이터를 받는 중이에요…</p>`;
    try{
      await loadScript(CHART);
      if(!ST.data[ST.market]) await load();
      render();
    }catch(e){ root().innerHTML = `<div class="sc-err">불러오지 못했어요. 잠시 뒤 다시 눌러 주세요. <small>${esc(e.message || e)}</small></div>`; return; }
    pollBreadth();
  }
  // 미국: 세부 업종·확산·이익 추정이 뒤에서 계산 중이면 15초마다 다시 받아 채움
  function pollBreadth(){
    clearTimeout(ST.poll);
    const d = ST.data.US;
    if(ST.market !== "US" || ST.view !== "sector" || !d || (d.breadth || {}).state !== "running") return;
    ST.poll = setTimeout(async () => {
      const tab = document.getElementById("tab-sector");
      if(!tab || tab.style.display === "none") return;
      try{ await load(); if(ST.market === "US" && ST.view === "sector") keep(render); }catch(e){}
      pollBreadth();
    }, 15000);
  }
  let rz = null;
  window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => { const t = document.getElementById("tab-sector"); if(t && t.style.display !== "none" && ST.data[ST.market]) keep(render); }, 300); });
  window.sectorOpen = function(){ if(!root()) return; if(!root().dataset.shown){ root().dataset.shown = "1"; open(); } else { keep(render); pollBreadth(); } };
})();
