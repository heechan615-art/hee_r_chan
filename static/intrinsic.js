// 🧮 기업 내재가치 분석 탭 — /api/intrinsic(intrinsic.py)이 주는 재료로 화면에서 계산
// 방법 6가지: DCF(잉여현금흐름 할인) · 역DCF · 잔여이익(RIM) · 배당할인(DDM) · 그레이엄 공식 · PER(금융사는 PBR) 밴드
// → 종합(가중 평균·범위·안전마진 매수 구간) · 가치 범위 그림 · 규칙 해석 · DCF 민감도 표. 가정을 바꾸면 바로 다시 계산.
(function(){
  const ST = {d: null, a: null, def: null, loading: false, q: ""};
  const root = () => document.getElementById("iv-root");
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const KR = () => ST.d && ST.d.currency === "KRW";
  const P = v => v == null || !isFinite(v) ? "–" : KR() ? Math.round(v).toLocaleString("ko-KR") + "원" : "$" + v.toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const pct = (v, d = 1) => v == null || !isFinite(v) ? "–" : (v > 0 ? "+" : "") + v.toFixed(d) + "%";
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const r1 = v => Math.round(v * 10) / 10;
  const FCF_MODES = [["last", "최근 실적 1년"], ["avg3", "최근 실적 3년 평균"], ["est", "컨센서스 추정 이어 쓰기"], ["cycle", "사이클 평균(실적 3년 + 추정 2년)"]];

  // ---------- 기준 잉여현금흐름(주당) ----------
  function fcfParts(d){
    const act = d.fcf.filter(x => !x.est && x.v != null), est = d.fcf.filter(x => x.est && x.v != null);
    const avg = a => a.length ? a.reduce((s, x) => s + x.v, 0) / a.length : null;
    const last = act.length ? act[act.length - 1].v : null, avg3 = avg(act.slice(-3));
    const cycle = est.length ? avg(act.slice(-3).concat(est.slice(0, 2))) : avg(act);
    return {act, est, last, avg3, cycle};
  }
  function baseFcf(d, mode){
    const f = fcfParts(d);
    if(mode === "est") return f.est.length ? f.last : null;
    return {last: f.last, avg3: f.avg3, cycle: f.cycle}[mode];
  }

  // ---------- 기본 가정 ----------
  function defaults(d){
    const c = d.coe, r = r1(c.rf + c.beta * c.erp + c.crp + c.size);
    const gT = d.market === "KR" ? 2.0 : 2.5;
    const sug = d.growth && d.growth.suggest != null ? d.growth.suggest * 100 : 5;
    const f = fcfParts(d);
    let mode = "last";
    if(d.cyclical) mode = f.est.length ? "cycle" : "avg3";
    else if(f.est.length) mode = "est";
    if(!d.cyclical && mode === "last" && !(f.last > 0)) mode = "avg3";
    const roes = d.roe.filter(x => x.v != null);
    let roe = null;
    if(d.cyclical && roes.length) roe = roes.reduce((s, x) => s + x.v, 0) / roes.length;
    else if(d.eps_fwd > 0 && d.bps > 0) roe = d.eps_fwd / d.bps * 100;
    else if(roes.filter(x => !x.est).length) roe = roes.filter(x => !x.est).slice(-1)[0].v;
    const dg = d.div && d.div.cagr != null ? clamp(d.div.cagr * 100, 0, 12) : 3;
    // 시클리컬은 사이클 평균 현금흐름에 이미 앞으로의 회복·호황이 섞여 있어 성장률을 또 크게 얹지 않음(3%)
    const g1 = d.cyclical && mode !== "est" ? 3 : r1(clamp(sug, -5, 20));
    return {r, gT, g1, mode, roe: roe == null ? null : r1(roe), w: 0.9, dg: r1(dg), mos: 25};
  }

  // ---------- 모델 ----------
  function dcf(d, a, o = {}){
    const r = (o.r ?? a.r) / 100, gT = (o.gT ?? a.gT) / 100, g1 = (o.g1 ?? a.g1) / 100;
    const b0 = baseFcf(d, a.mode);
    if(!(b0 > 0) || r <= gT + 0.005) return null;
    const est = a.mode === "est" ? fcfParts(d).est : [];
    let f = b0, pv = 0; const rows = [];
    for(let t = 1; t <= 10; t++){
      const g = t <= 5 ? g1 : g1 + (gT - g1) * (t - 5) / 5;
      const e = est[t - 1];
      const nf = e && e.v != null ? e.v : f * (1 + g);
      const p = nf / Math.pow(1 + r, t);
      rows.push({t, y: e ? e.y + "E" : null, f: nf, g: f ? (nf / f - 1) * 100 : null, pv: p, est: !!e});
      pv += p; f = nf;
    }
    const tv = f * (1 + gT) / (r - gT), tvpv = tv / Math.pow(1 + r, 10);
    const nd = d.net_debt_ps || 0;
    return {value: pv + tvpv - nd, pv, tvpv, nd, rows, b0, tvShare: tvpv / (pv + tvpv) * 100};
  }
  function reverseDcf(d, a){
    const v = g => { const x = dcf(d, a, {g1: g}); return x ? x.value : null; };
    let lo = -40, hi = 80;
    const vl = v(lo), vh = v(hi);
    if(vl == null || vh == null) return null;
    if(d.price <= vl) return {g: lo, edge: "lo"};
    if(d.price >= vh) return {g: hi, edge: "hi"};
    for(let i = 0; i < 60; i++){ const m = (lo + hi) / 2; (v(m) < d.price ? (lo = m) : (hi = m)); }
    return {g: (lo + hi) / 2};
  }
  function rim(d, a, o = {}){
    const roe = (o.roe ?? a.roe) / 100, r = (o.r ?? a.r) / 100, w = a.w;
    if(!(d.bps > 0) || a.roe == null) return null;
    return d.bps + d.bps * (roe - r) / (1 + r - w);
  }
  function ddm(d, a, o = {}){
    const D0 = d.div && d.div.ttm, r = (o.r ?? a.r) / 100, gT = a.gT / 100, g = (o.dg ?? a.dg) / 100;
    if(!(D0 > 0) || r <= gT + 0.005) return null;
    let D = D0, pv = 0;
    for(let t = 1; t <= 5; t++){ D *= 1 + g; pv += D / Math.pow(1 + r, t); }
    return pv + D * (1 + gT) / (r - gT) / Math.pow(1 + r, 5);
  }
  function graham(d, a, o = {}){
    const g = clamp(o.g ?? a.g1, 0, 15), Y = d.coe.rf + 1.0;
    if(!(d.eps_ttm > 0)) return null;
    return d.eps_ttm * (8.5 + 2 * g) * 4.4 / Y;
  }

  // ---------- 6가지 방법 → 결과 목록 ----------
  function models(d, a){
    const out = [], fp = fcfParts(d);
    const payout = d.div && d.div.ttm > 0 && d.eps_ttm > 0 ? d.div.ttm / d.eps_ttm * 100 : null;
    const divYears = d.div ? Object.keys(d.div.years).length : 0;
    // DCF
    const m = {key: "dcf", name: "DCF (잉여현금흐름 할인)", w: 1};
    const base = dcf(d, a);
    if(d.is_fin){ m.skip = "금융사는 예금·대출 자체가 영업이라 잉여현금흐름이 의미가 없어요 → 잔여이익모형·PBR로 봐요."; }
    else if(!base){ m.skip = a.r <= a.gT + 0.5 ? "할인율이 영구성장률보다 충분히 커야 계산돼요." : "기준 잉여현금흐름이 0 이하라(적자·대규모 투자) 계산할 수 없어요 → 상대가치(PER)로 봐요."; }
    else {
      const lo = dcf(d, a, {r: a.r + 1, g1: a.g1 - 3}), hi = dcf(d, a, {r: Math.max(a.r - 1, a.gT + 1), g1: a.g1 + 3});
      Object.assign(m, {v: base.value, lo: lo && lo.value, hi: hi && hi.value, det: base,
        note: `기준 FCF ${P(base.b0)}/주(${FCF_MODES.find(x => x[0] === a.mode)[1]}) · 1~5년 ${a.g1}% → 6~10년 ${a.gT}%로 줄임 · 할인율 ${a.r}% · 가치의 ${Math.round(base.tvShare)}%가 10년 뒤(잔존가치)`});
    }
    out.push(m);
    // RIM
    const rm = {key: "rim", name: "잔여이익모형 (RIM)", w: 1};
    const rv = rim(d, a);
    if(rv == null) rm.skip = "주당순자산(BPS)이나 ROE가 없어 계산할 수 없어요.";
    else {
      Object.assign(rm, {v: rv, lo: rim(d, a, {roe: a.roe - 2, r: a.r + 1}), hi: rim(d, a, {roe: a.roe + 2, r: a.r - 1}),
        note: `BPS ${P(d.bps)} + 초과이익(ROE ${a.roe}% − 할인율 ${a.r}%) · 지속계수 ${a.w}(해마다 초과이익이 ${Math.round((1 - a.w) * 100)}%씩 줄어듦)`});
      if(a.roe > 40) { rm.ref = true; rm.warn = "ROE가 40%를 넘어요 — 자사주 매입·배당으로 자본이 작아진 회사는 RIM이 가치를 크게 낮게 잡아서 종합에서 뺐어요."; }
    }
    out.push(rm);
    // DDM
    const dm = {key: "ddm", name: "배당할인모형 (DDM)", w: 1};
    const dv = ddm(d, a);
    if(dv == null) dm.skip = d.div && d.div.ttm > 0 ? "할인율이 영구성장률보다 충분히 커야 계산돼요." : "배당을 주지 않는 회사예요.";
    else {
      Object.assign(dm, {v: dv, lo: ddm(d, a, {r: a.r + 1, dg: a.dg - 2}), hi: ddm(d, a, {r: Math.max(a.r - 1, a.gT + 1), dg: a.dg + 2}),
        note: `최근 1년 배당 ${P(d.div.ttm)} · 5년 동안 연 ${a.dg}% 증가 → 이후 ${a.gT}% · 배당성향 ${payout == null ? "–" : Math.round(payout) + "%"}`});
      if(payout == null || payout < 30 || divYears < 3){ dm.ref = true; dm.warn = "이익 중 배당으로 주는 몫이 작아(30% 미만) 배당만으로는 가치를 낮게 잡아요 — 참고로만 보고 종합에서 뺐어요."; }
    }
    out.push(dm);
    // 그레이엄
    const gm = {key: "graham", name: "그레이엄 공식", w: 0.5};
    const gv = graham(d, a);
    if(gv == null) gm.skip = "최근 1년 EPS가 0 이하라 계산할 수 없어요.";
    else {
      Object.assign(gm, {v: gv, lo: graham(d, a, {g: a.g1 - 3}), hi: graham(d, a, {g: a.g1 + 3}),
        note: `EPS ${P(d.eps_ttm)} × (8.5 + 2 × 성장률 ${clamp(a.g1, 0, 15)}) × 4.4 ÷ 회사채 금리(국채 ${d.coe.rf}% + 1%p 근사) · 빠른 점검용이라 비중 절반`});
      if(d.cyclical){ gm.ref = true; gm.warn = "시클리컬은 한 해 EPS가 사이클에 따라 크게 바뀌어 이 공식이 맞지 않아요 — 종합에서 뺐어요."; }
    }
    out.push(gm);
    // PER 밴드 / 금융사는 PBR 밴드
    if(d.per_band && d.per_band.neutral){
      const b = d.per_band;
      out.push({key: "per", name: `PER 밴드 (${b.basis === "예상EPS" ? "예상 EPS" : "최근 EPS"} × 과거 PER)`, w: d.is_fin ? 0.5 : 1, v: b.neutral, lo: b.bear, hi: b.bull,
        note: `EPS ${P(b.eps)} × 과거 PER 중간값 · 범위는 과거 PER 최저~최고 — 시장이 이 회사에 매겨 온 값`,
        ...(d.cyclical ? {ref: true, warn: "시클리컬은 불황 때 이익이 작아 PER이 높게 찍히고 호황 땐 낮게 찍혀요. 과거 PER × 호황 이익은 크게 부풀어서 종합에서 뺐어요."} : {})});
    } else out.push({key: "per", name: "PER 밴드", w: 1, skip: "이익이 0 이하이거나 과거 PER 기록이 부족해요."});
    if(d.is_fin && d.pbr_band && d.pbr_band.neutral){
      const b = d.pbr_band;
      out.push({key: "pbr", name: "PBR 밴드 (BPS × 과거 PBR)", w: 1, v: b.neutral, lo: b.bear, hi: b.bull, note: `BPS ${P(b.bps)} × 과거 PBR 중간값 · 금융사의 기본 잣대`});
    }
    // 주 방법
    const main = d.is_fin ? "rim" : (payout != null && payout >= 50 && divYears >= 5 && !dm.skip && !dm.ref) ? "ddm" : !m.skip ? "dcf" : "per";
    out.forEach(x => { x.main = x.key === main; if(x.main && !x.skip && !x.ref) x.w *= 2; });
    return {list: out, main, payout};
  }

  function summary(d, a, M){
    const inc = M.list.filter(x => !x.skip && !x.ref && x.v > 0);
    if(!inc.length) return null;
    const W = inc.reduce((s, x) => s + x.w, 0);
    const c = inc.reduce((s, x) => s + x.v * x.w, 0) / W;
    const vs = inc.map(x => x.v);
    const lo = Math.min(...vs), hi = Math.max(...vs), buy = c * (1 - a.mos / 100);
    const gap = (d.price / c - 1) * 100;
    let lv, head;
    if(d.price <= buy){ lv = "g"; head = `안전마진 구간 — 내재가치 중심값보다 ${Math.abs(gap).toFixed(0)}% 싸요`; }
    else if(d.price <= c){ lv = "g"; head = `내재가치 아래 — ${Math.abs(gap).toFixed(0)}% 싸지만 안전마진(${a.mos}%)까진 아니에요`; }
    else if(d.price <= hi){ lv = "y"; head = `내재가치 범위 안 위쪽 — 중심값보다 ${gap.toFixed(0)}% 비싸요`; }
    else { lv = "r"; head = `모든 방법보다 비싸요 — 중심값보다 ${gap.toFixed(0)}% 높아요`; }
    return {c, lo, hi, buy, gap, lv, head, inc};
  }

  // ---------- 해석(규칙) ----------
  function reading(d, a, M, S, rev){
    const P1 = [];
    const mainM = M.list.find(x => x.main);
    let why = {dcf: "현금을 꾸준히 버는 회사라 앞으로 벌 현금(잉여현금흐름)으로 보는 DCF가 기본이에요.",
      rim: "금융사는 자본으로 돈을 버는 회사라 '자본 + 자본비용보다 더 버는 이익'으로 보는 잔여이익모형이 기본이에요.",
      ddm: "이익의 절반 이상을 오래 배당해 온 회사라 배당할인모형이 기본이에요.",
      per: "잉여현금흐름이 0 이하라 현금흐름 할인이 안 돼서, 시장이 매겨 온 PER로 봐요."}[M.main];
    if(M.main === "dcf" && d.cyclical) why = "경기에 따라 이익이 크게 출렁이는 회사라, 한 해 숫자 대신 사이클 평균 잉여현금흐름으로 DCF를 봐요.";
    P1.push(`🎯 주 방법: ${mainM.name} — ${why}`);
    if(S) P1.push(`📌 계산되는 방법 ${S.inc.length}개를 합치면 내재가치 중심값은 ${P(S.c)}(범위 ${P(S.lo)} ~ ${P(S.hi)})이고, 지금 주가(${P(d.price)})는 중심값 대비 ${pct(S.gap, 0)}예요. 안전마진 ${a.mos}%를 두면 매수 구간은 ${P(S.buy)} 아래예요.`);
    if(rev){
      const cons = d.growth && d.growth.suggest != null ? d.growth.suggest * 100 : null;
      let s = rev.edge === "hi" ? "지금 주가를 정당화하려면 잉여현금흐름이 5년간 연 80% 넘게 늘어야 해요 — 시장 기대가 매우 높아요."
        : rev.edge === "lo" ? "지금 주가는 잉여현금흐름이 계속 줄어드는 것까지 반영했어요 — 비관이 많이 들어가 있어요."
        : `🔄 역DCF: 지금 주가는 앞으로 5년간 잉여현금흐름이 연 ${rev.g.toFixed(1)}%씩 늘어난다는 가정과 같아요.`;
      if(!rev.edge && cons != null && d.cyclical) s += " 사이클 평균 현금흐름 기준이라, 호황기 애널리스트 성장률과 바로 비교하진 않아요.";
      else if(!rev.edge && cons != null){
        const df = rev.g - cons;
        s += ` 애널리스트가 보는 이익 성장률(${cons.toFixed(1)}%)보다 ${Math.abs(df).toFixed(1)}%p ${df > 0 ? "높아서, 시장이 예상보다 더 큰 성장을 미리 가격에 넣었어요" : "낮아서, 예상만큼만 자라도 주가가 올라갈 여지가 있어요"}.`;
      }
      P1.push(s);
    }
    const ok = M.list.filter(x => !x.skip && !x.ref && x.v > 0);
    if(ok.length >= 2){
      const s2 = ok.slice().sort((x, y) => y.v - x.v), H = s2[0], L = s2[s2.length - 1];
      if(H.v / L.v > 1.8) P1.push(`↔️ 방법끼리 차이가 커요: ${H.name} ${P(H.v)} vs ${L.name} ${P(L.v)}. 이럴 땐 숫자 하나를 믿기보다 '어떤 가정 차이 때문인지'를 보는 게 공부 포인트예요${H.key === "per" ? " — PER 밴드가 높으면 시장이 이 회사에 늘 높은 배수를 줬다는 뜻이에요" : ""}.`);
    }
    const base = dcf(d, a), up = dcf(d, a, {r: a.r - 1}), dn = dcf(d, a, {r: a.r + 1});
    if(base && up && dn) P1.push(`🎚️ 민감도: 할인율을 1%p만 바꿔도 DCF 값이 ${pct((dn.value / base.value - 1) * 100, 0)} ~ ${pct((up.value / base.value - 1) * 100, 0)} 움직여요. 그래서 한 값보다 범위로 봐야 해요.`);
    const warn = [];
    if(d.cyclical) warn.push("경기에 따라 이익이 크게 출렁이는 회사(시클리컬)라 한 해 숫자 대신 사이클 평균을 기본으로 썼어요. 호황 꼭대기 이익으로 계산하면 크게 부풀어요.");
    if(base && base.tvShare > 75) warn.push(`DCF 가치의 ${Math.round(base.tvShare)}%가 10년 뒤 잔존가치예요 — 먼 미래 가정에 많이 기대고 있어요.`);
    if(a.mode === "est") warn.push("앞쪽 몇 해는 증권사 컨센서스 추정 잉여현금흐름을 그대로 썼어요. 추정이 틀리면 가치도 같이 달라져요.");
    if(d.fin_fx) warn.push(`재무제표 통화가 주가 통화와 달라 환율(${d.fin_fx.toFixed(3)})로 바꿔 계산했어요.`);
    return {paras: P1, warn};
  }

  // ---------- 가치 범위 그림(SVG) ----------
  function field(d, M, S){
    const rows = M.list.filter(x => !x.skip && x.v > 0);
    if(!rows.length) return "";
    const all = rows.flatMap(x => [x.lo, x.v, x.hi]).filter(v => v > 0).concat([d.price]);
    let mx = Math.max(...all) * 1.08, mn = Math.min(...all) * 0.9;
    const cap = d.price * 4; if(mx > cap) mx = cap;
    mn = Math.max(0, Math.min(mn, d.price * 0.5));
    const W = 760, L = 150, R = 46, rh = 34, top = 26, H = top + rows.length * rh + 30;
    const X = v => L + (clamp(v, mn, mx) - mn) / (mx - mn) * (W - L - R);
    const ticks = 5, tk = Array.from({length: ticks + 1}, (_, i) => mn + (mx - mn) * i / ticks);
    let s = `<svg viewBox="0 0 ${W} ${H}" class="iv-svg" role="img" aria-label="방법별 내재가치 범위">`;
    tk.forEach(v => { s += `<line x1="${X(v)}" y1="${top - 6}" x2="${X(v)}" y2="${H - 24}" stroke="#eef0f4"/><text x="${X(v)}" y="${H - 8}" text-anchor="middle" class="iv-ax">${esc(P(v))}</text>`; });
    if(S){ s += `<rect x="${X(mn)}" y="${top - 6}" width="${Math.max(0, X(S.buy) - X(mn))}" height="${H - top - 18}" fill="#2b8a3e" opacity=".07"/>`;
      s += `<line x1="${X(S.c)}" y1="${top - 10}" x2="${X(S.c)}" y2="${H - 24}" stroke="#B0883A" stroke-width="2.5" stroke-dasharray="5 4"/><text x="${X(S.c)}" y="${top - 13}" text-anchor="middle" class="iv-lab" fill="#8f6d2b">중심 ${esc(P(S.c))}</text>`; }
    rows.forEach((x, i) => {
      const y = top + i * rh + 8, c = x.ref ? "#c3c8d2" : x.main ? "#0e1c36" : "#4a7fd4";
      s += `<text x="${L - 10}" y="${y + 13}" text-anchor="end" class="iv-nm">${x.main ? "★ " : ""}${esc(x.name.split(" (")[0])}${x.ref ? " (참고)" : ""}</text>`;
      if(x.lo > 0 && x.hi > 0) s += `<rect x="${X(Math.min(x.lo, x.hi))}" y="${y + 3}" width="${Math.max(2, Math.abs(X(x.hi) - X(x.lo)))}" height="14" rx="7" fill="${c}" opacity=".22"/>`;
      s += `<circle cx="${X(x.v)}" cy="${y + 10}" r="6.5" fill="${c}"/>${x.v > mx ? `<text x="${W - R}" y="${y + 14}" text-anchor="end" class="iv-lab">→ ${esc(P(x.v))}</text>` : ""}`;
    });
    s += `<line x1="${X(d.price)}" y1="${top - 10}" x2="${X(d.price)}" y2="${H - 24}" stroke="#d63939" stroke-width="2.5"/><text x="${X(d.price)}" y="${H - 26}" text-anchor="middle" class="iv-lab" fill="#d63939" dy="-2">지금 ${esc(P(d.price))}</text>`;
    return s + "</svg>";
  }

  // ---------- DCF 민감도 표 ----------
  function sens(d, a){
    if(!dcf(d, a)) return "";
    const rs = [-2, -1, 0, 1, 2].map(x => r1(a.r + x)), gs = [-1, -0.5, 0, 0.5, 1].map(x => r1(a.gT + x));
    let h = `<table class="iv-sens"><thead><tr><th>할인율 ＼ 영구성장률</th>${gs.map(g => `<th>${g}%</th>`).join("")}</tr></thead><tbody>`;
    rs.forEach(r => {
      h += `<tr><th>${r}%</th>` + gs.map(g => { const x = dcf(d, a, {r, gT: g}); if(!x) return `<td>–</td>`;
        const gp = (x.value / d.price - 1) * 100, cls = gp >= 25 ? "s3" : gp >= 0 ? "s2" : gp >= -25 ? "s1" : "s0";
        return `<td class="${cls}${r === a.r && g === a.gT ? " cur" : ""}">${esc(P(x.value))}<small>${pct(gp, 0)}</small></td>`; }).join("") + "</tr>";
    });
    return h + `</tbody></table><p class="iv-small">칸 아래 %는 지금 주가 대비. 진한 초록 = 25% 이상 싸다는 뜻, 빨강 = 25% 넘게 비싸다는 뜻. 가운데 테두리 칸이 지금 가정이에요.</p>`;
  }

  // ---------- 그리기 ----------
  function inp(k, label, val, step, help, extra = ""){
    return `<label class="iv-in"><span>${label}</span><input type="number" step="${step}" data-k="${k}" value="${val == null ? "" : val}" ${extra}><em>${help}</em></label>`;
  }
  function render(){
    const d = ST.d, a = ST.a, el = document.getElementById("iv-out");
    if(!d || !el) return;
    const M = models(d, a), S = summary(d, a, M), rev = !d.is_fin ? reverseDcf(d, a) : null, R = reading(d, a, M, S, rev);
    const c = d.coe, LV = {g: ["🟢", "iv-g"], y: ["🟡", "iv-y"], r: ["🔴", "iv-r"]};
    const base = dcf(d, a);
    el.innerHTML = `
      <div class="iv-head"><div><h2>${esc(d.name)} <small>${esc(d.ticker)} · ${esc(d.sector || "")}${d.is_fin ? " · 금융사" : ""}${d.cyclical ? " · 시클리컬" : ""}</small></h2>
        <div class="iv-px">지금 주가 <b>${P(d.price)}</b></div></div>
        ${S ? `<div class="iv-verdict ${LV[S.lv][1]}"><div class="t">${LV[S.lv][0]} ${esc(S.head)}</div>
          <div class="nums"><span>내재가치 중심<b>${P(S.c)}</b></span><span>범위<b>${P(S.lo)} ~ ${P(S.hi)}</b></span><span>매수 구간(안전마진 ${a.mos}%)<b>${P(S.buy)} 아래</b></span></div></div>` : `<div class="iv-verdict iv-y"><div class="t">⚪ 계산되는 방법이 없어요 — 아래 가정을 바꿔 보세요</div></div>`}
      </div>
      <div class="iv-panel iv-read"><div class="lab">🧭 지금 어떻게 읽나 <small>숫자가 바뀌면 문장도 규칙대로 다시 써져요(히르찬 기준, 투자 권유 아님)</small></div>
        ${R.paras.map(p => `<p>${esc(p)}</p>`).join("")}
        ${R.warn.length ? `<ul class="iv-warn">${R.warn.map(w => `<li>⚠️ ${esc(w)}</li>`).join("")}</ul>` : ""}</div>
      <div class="iv-panel"><div class="iv-h3">📏 방법별 내재가치 <small>점 = 기본 가정 · 막대 = 가정을 조금 바꿨을 때 범위 · ★ 주 방법 · 빨간 선 = 지금 주가 · 초록 바탕 = 매수 구간</small></div>
        <div class="iv-svgwrap">${field(d, M, S)}</div></div>
      <div class="iv-panel"><div class="iv-h3">⚙️ 가정 바꿔 보기 <small>바꾸면 바로 다시 계산돼요</small> <button type="button" id="iv-reset">기본값으로</button></div>
        <div class="iv-ins">
          ${inp("r", "할인율(요구수익률) %", a.r, 0.1, `국채 ${c.rf}% + 베타 ${c.beta} × 시장 위험 ${c.erp}%${c.crp ? ` + 국가 ${c.crp}%` : ""}${c.size ? ` + 규모 ${c.size}%` : ""}`)}
          ${inp("g1", "1~5년 성장률 %", a.g1, 0.5, d.growth && d.growth.cands ? "애널리스트·과거 성장률 기준" + (d.growth.suggest != null ? ` (추천 ${r1(d.growth.suggest * 100)}%, 상한 20%)` : "") : "기본 5%")}
          ${inp("gT", "영구성장률 %", a.gT, 0.1, "10년 뒤부터 영원히 · 보통 2~3%(경제 성장률 근처)")}
          <label class="iv-in"><span>기준 잉여현금흐름</span><select data-k="mode">${FCF_MODES.map(([k, t]) => { const v = baseFcf(d, k); return `<option value="${k}"${a.mode === k ? " selected" : ""}${v == null ? " disabled" : ""}>${t} (${P(v)})</option>`; }).join("")}</select><em>주당 · 들쭉날쭉하면 평균을 써요</em></label>
          ${inp("roe", "ROE % (RIM)", a.roe, 0.5, "자기자본으로 1년에 버는 비율")}
          ${inp("w", "초과이익 지속계수 (RIM)", a.w, 0.05, "1 = 영원히 유지, 0.9 = 해마다 10%씩 줄어듦", 'min="0" max="1"')}
          ${inp("dg", "배당 성장률 % (DDM)", a.dg, 0.5, d.div && d.div.cagr != null ? `최근 5년 연평균 ${r1(d.div.cagr * 100)}%` : "배당 기록 부족")}
          ${inp("mos", "안전마진 %", a.mos, 5, "내재가치보다 이만큼 싸야 산다")}
        </div></div>
      <div class="iv-cards">${M.list.map(x => `<div class="iv-card${x.main ? " main" : ""}${x.skip ? " off" : ""}${x.ref ? " ref" : ""}">
          <div class="nm">${x.main ? "★ " : ""}${esc(x.name)}${x.main ? ' <span class="tag">주 방법</span>' : ""}${x.ref ? ' <span class="tag gray">참고</span>' : ""}</div>
          ${x.skip ? `<div class="sk">${esc(x.skip)}</div>` : `<div class="v">${P(x.v)} <small class="${x.v >= d.price ? "up" : "dn"}">지금 대비 ${pct((x.v / d.price - 1) * 100, 0)}</small></div>
            <div class="rg">범위 ${P(Math.min(x.lo, x.hi))} ~ ${P(Math.max(x.lo, x.hi))}</div><div class="nt">${esc(x.note || "")}</div>${x.warn ? `<div class="wn">⚠️ ${esc(x.warn)}</div>` : ""}`}
        </div>`).join("")}
        ${rev ? `<div class="iv-card rev"><div class="nm">🔄 역DCF — 지금 주가에 들어 있는 기대</div>
          <div class="v">연 ${rev.edge === "hi" ? "80% 넘게" : rev.edge === "lo" ? "−40% 아래" : rev.g.toFixed(1) + "%"}</div>
          <div class="nt">다른 가정(할인율 ${a.r}%·영구성장률 ${a.gT}%·기준 FCF)은 그대로 두고, 지금 주가가 딱 맞는 1~5년 잉여현금흐름 성장률을 거꾸로 푼 값이에요. 애널리스트 이익 성장률 ${d.growth && d.growth.suggest != null ? r1(d.growth.suggest * 100) + "%" : "–"}와 비교해 보세요.</div></div>` : ""}
      </div>
      ${base ? `<details class="iv-panel"><summary class="iv-h3">📋 DCF 10년 계산표 <small>주당 잉여현금흐름 · 현재가치</small></summary>
        <div class="iv-scroll"><table class="iv-tbl"><thead><tr><th>해</th><th>주당 FCF</th><th>증가율</th><th>현재가치</th></tr></thead><tbody>
        ${base.rows.map(x => `<tr><td>${x.t}년 후${x.est ? ` <small>${esc(x.y)} 추정</small>` : ""}</td><td>${P(x.f)}</td><td>${pct(x.g)}</td><td>${P(x.pv)}</td></tr>`).join("")}
        <tr class="sum"><td>10년 합계</td><td></td><td></td><td>${P(base.pv)}</td></tr>
        <tr class="sum"><td>잔존가치(10년 뒤 이후 전부)</td><td></td><td></td><td>${P(base.tvpv)}</td></tr>
        <tr class="sum"><td>${base.nd >= 0 ? "− 순부채" : "+ 순현금"}</td><td></td><td></td><td>${P(Math.abs(base.nd))}</td></tr>
        <tr class="sum tot"><td>주당 내재가치</td><td></td><td></td><td>${P(base.value)}</td></tr></tbody></table></div>
        <p class="iv-small">수업용으로 단순하게: 회사 전체 현금흐름을 자기자본 요구수익률로 할인하고 순부채(부채 − 현금)를 뺐어요. 실무 WACC보다 할인율이 조금 높아 보수적으로 나와요.</p></details>
      <div class="iv-panel"><div class="iv-h3">🎚️ DCF 민감도 표 <small>할인율 × 영구성장률 — 가정이 조금만 달라도 값이 얼마나 바뀌는지</small></div><div class="iv-scroll">${sens(d, a)}</div></div>` : ""}
      ${d.fcf.length ? `<details class="iv-panel"><summary class="iv-h3">🧾 재료 숫자 <small>주당 잉여현금흐름·ROE·배당</small></summary><div class="iv-scroll"><table class="iv-tbl">
        <thead><tr><th>연도</th>${d.fcf.map(x => `<th>${esc(x.y)}${x.est ? "E" : ""}</th>`).join("")}</tr></thead><tbody>
        <tr><td>주당 FCF</td>${d.fcf.map(x => `<td>${P(x.v)}</td>`).join("")}</tr>
        <tr><td>ROE</td>${d.roe.map(x => `<td>${x.v == null ? "–" : x.v.toFixed(1) + "%"}</td>`).join("")}</tr></tbody></table>
        ${d.div && Object.keys(d.div.years).length ? `<table class="iv-tbl" style="margin-top:8px"><thead><tr><th>배당(주당)</th>${Object.keys(d.div.years).map(y => `<th>${y}</th>`).join("")}<th>최근 1년</th></tr></thead><tbody><tr><td></td>${Object.values(d.div.years).map(v => `<td>${P(v)}</td>`).join("")}<td>${P(d.div.ttm)}</td></tr></tbody></table>` : ""}</div>
        <p class="iv-small">EPS ${P(d.eps_ttm)}(최근 1년) · ${P(d.eps_fwd)}(예상) · BPS ${P(d.bps)} · 순부채 ${P(d.net_debt_ps)}/주(음수 = 순현금). 재무 출처는 기업 밸류에이션 탭과 같아요(국내 네이버·WISEfn, 미국 야후). 주당 숫자 = 회사 전체 ÷ 시가총액 기준 주식 수.</p></details>` : ""}
      ${howTo()}`;
    el.querySelectorAll("[data-k]").forEach(i => i.onchange = () => {
      const k = i.dataset.k, v = k === "mode" ? i.value : parseFloat(i.value);
      if(k !== "mode" && !isFinite(v)) return;
      ST.a[k] = k === "w" ? clamp(v, 0, 1) : v; render();
    });
    const rb = document.getElementById("iv-reset"); if(rb) rb.onclick = () => { ST.a = Object.assign({}, ST.def); render(); };
  }
  function howTo(){
    return `<details class="iv-panel"><summary class="iv-h3">📖 방법 6가지 쉽게 이해하기</summary><div class="iv-how">
      <p><b>① DCF(잉여현금흐름 할인)</b> — 회사가 앞으로 벌어 마음대로 쓸 수 있는 현금(영업현금 − 설비투자)을 10년 예상하고, 그 뒤는 '영원히 조금씩 자란다'고 보고 전부 지금 돈으로 바꿔 더해요. 가장 정통이지만 할인율·성장률에 민감해요.</p>
      <p><b>② 역DCF</b> — 반대로 '지금 주가가 맞으려면 몇 % 성장해야 하나'를 풀어요. 미래를 맞힐 필요 없이 시장 기대가 과한지만 보면 돼서 실전에서 가장 쓸모 있어요.</p>
      <p><b>③ 잔여이익모형(RIM)</b> — 가치 = 지금 자본 + '요구수익률보다 더 버는 이익'의 현재가치. 은행·보험처럼 현금흐름을 정의하기 어려운 회사에 맞아요. 한국 증권사가 많이 써요.</p>
      <p><b>④ 배당할인모형(DDM)</b> — 주주가 받는 배당만으로 가치를 매겨요. 이익 대부분을 배당하는 통신·유틸리티·리츠에 맞고, 배당이 적은 성장주엔 맞지 않아요.</p>
      <p><b>⑤ 그레이엄 공식</b> — 가치 = EPS × (8.5 + 2 × 성장률) × 4.4 ÷ 회사채 금리. 벤저민 그레이엄의 빠른 점검식이라 비중을 절반만 줘요.</p>
      <p><b>⑥ PER(금융사는 PBR) 밴드</b> — 시장이 이 회사에 과거에 매겨 온 배수 × 이익. '시장 눈높이'라 다른 방법과 비교하는 기준점이에요.</p>
      <p><b>종합하는 법</b> — 회사에 맞는 주 방법(★, 비중 2배)을 정하고, 맞지 않는 방법은 '참고'로 빼요. 남은 방법의 가중 평균이 중심값, 가장 낮은~높은 값이 범위예요. 중심값보다 안전마진만큼 싼 가격을 매수 구간으로 둬요. 숫자 하나를 정답으로 믿지 말고, '어떤 가정이면 얼마'를 보는 게 핵심이에요.</p></div></details>`;
  }

  async function search(q){
    q = (q || "").trim(); if(!q || ST.loading) return;
    ST.loading = true; ST.q = q;
    const el = document.getElementById("iv-out");
    el.innerHTML = `<div class="iv-loading"><div class="spin"></div>재료 모으는 중… (기업 밸류에이션 탭과 같은 자료, 5~15초)</div>`;
    try{
      const r = await fetch("/api/intrinsic?ticker=" + encodeURIComponent(q)), j = await r.json();
      if(j.error) throw new Error(j.error);
      ST.d = j; ST.def = defaults(j); ST.a = Object.assign({}, ST.def);
      try{ history.replaceState(null, "", "#iv=" + encodeURIComponent(q)); }catch(e){}
      render();
    }catch(e){ el.innerHTML = `<div class="iv-err">${esc(e.message || e)}</div>`; ST.d = null; }
    ST.loading = false;
  }

  function shell(){
    root().innerHTML = `<form class="iv-f" id="iv-f"><input id="iv-q" placeholder="회사 이름 또는 티커 (예: 삼성전자, KO, AAPL, JPM)" autocomplete="off"><button type="submit">분석</button></form>
      <div class="iv-chips">${["삼성전자", "SK텔레콤", "KB금융", "AAPL", "KO", "JPM", "NVDA"].map(t => `<span class="chip" data-iv="${t}">${t}</span>`).join("")}</div>
      <div id="iv-out"><div class="iv-empty">종목을 검색하면 6가지 방법으로 내재가치를 구하고, 회사에 맞는 주 방법·종합 범위·매수 구간·해석까지 보여 드려요. 가정(할인율·성장률)은 직접 바꿔 볼 수 있어요.</div></div>`;
    document.getElementById("iv-f").onsubmit = e => { e.preventDefault(); search(document.getElementById("iv-q").value); };
    root().querySelectorAll("[data-iv]").forEach(c => c.onclick = () => { document.getElementById("iv-q").value = c.dataset.iv; search(c.dataset.iv); });
  }

  window.ivOpen = function(){
    if(!root()) return;
    if(!document.getElementById("iv-f")) shell();
    const m = location.hash.match(/^#iv=([^&]+)/);
    const want = m ? decodeURIComponent(m[1]) : ((document.getElementById("q") || {}).value || "").trim();
    if(want && !ST.d && !ST.loading){ document.getElementById("iv-q").value = want; search(want); }
  };
})();
