"""품질 점검 + 자동 보정 (설계서 7장) — Playwright로 연 페이지 안에서 검사 → 보정 → 재검사.

검사 항목
- 넘침      : 글자가 자기 칸보다 넓음 (.chk 요소)
- 박스 밖   : 글자가 패널·머리글·바닥글 밖으로 나감
- 그림 밖   : 차트(SVG) 글자가 그림 영역 밖으로 나가 잘림
- 겹침      : 차트 글자끼리 겹침 (같은 라벨 묶음 g.grp 안의 윗줄·아랫줄은 제외)
- 선·마커   : 값 라벨이 차트 선(8px)·점 마커에 걸림 (실제 선 두께로 판정)
자동 보정 (최대 10번 반복)
- 넘침·박스 밖 → 글씨 6%씩 줄임 (원래 크기의 66%까지)
- 그림 밖      → 넘친 만큼 안으로 옮김
- 겹침·선·마커 → 위/아래로 12·24·36px 옮겨 빈자리 찾기, 안 되면 글씨 8% 줄임
끝까지 남으면 PNG 이름에 _CHECK.
"""
from __future__ import annotations

from pathlib import Path

QC_JS = r"""
window.__qc = (() => {
  const R = el => el.getBoundingClientRect();
  const ovl = (a, b, p = 1) => a.left < b.right - p && b.left < a.right - p && a.top < b.bottom - p && b.top < a.bottom - p;
  const name = el => (el.tagName === 'g' ? [...el.querySelectorAll('text')].map(t => t.textContent).join(' ')
                                         : (el.textContent || '')).trim().replace(/\s+/g, ' ').slice(0, 28);
  const unitOf = t => t.closest('g.grp') || t;
  const textsOf = u => u.tagName === 'text' ? [u] : [...u.querySelectorAll('text')];

  function htmlIssues() {
    const out = [];
    document.querySelectorAll('.chk').forEach(el => {
      if (el.closest('svg')) return;
      if (el.scrollWidth > el.clientWidth + 1) { out.push({ kind: '넘침', el }); return; }
      const box = el.closest('.panel, header, footer');
      if (box) { const a = R(el), b = R(box);
        if (a.right > b.right - 2 || a.left < b.left + 2) out.push({ kind: '박스 밖', el }); }
    });
    return out;
  }

  function hitsStroke(t, svg) {
    if (t.closest('g.grp')) return false;
    const b = t.getBBox();
    const pts = [];
    for (let ix = 0; ix <= 8; ix++) for (let iy = 0; iy <= 3; iy++)  // 9×4 점 (5×3은 선 끝을 놓쳤음)
      pts.push([b.x + b.width * ix / 8, b.y + b.height * (0.15 + 0.7 * iy / 3)]);
    for (const p of svg.querySelectorAll('path[fill="none"]'))
      for (const [x, y] of pts) if (p.isPointInStroke(new DOMPoint(x, y))) return true;
    for (const c of svg.querySelectorAll('circle')) {
      const cx = +c.getAttribute('cx'), cy = +c.getAttribute('cy');
      const r = +c.getAttribute('r') + (+c.getAttribute('stroke-width') || 0) / 2;
      const nx = Math.max(b.x, Math.min(cx, b.x + b.width)), ny = Math.max(b.y, Math.min(cy, b.y + b.height));
      if ((nx - cx) ** 2 + (ny - cy) ** 2 < r * r) return true;
    }
    return false;
  }

  function outside(t, svg) {
    const r = R(t), s = R(svg);
    return r.width > 0 && (r.left < s.left - 1 || r.right > s.right + 1 || r.top < s.top - 1 || r.bottom > s.bottom + 1);
  }

  function svgIssues() {
    const out = [];
    document.querySelectorAll('svg').forEach(svg => {
      const ts = [...svg.querySelectorAll('text')];
      const rs = ts.map(R);
      ts.forEach(t => { if (outside(t, svg)) out.push({ kind: '그림 밖', el: t, svg }); });
      for (let i = 0; i < ts.length; i++) for (let j = i + 1; j < ts.length; j++) {
        if (unitOf(ts[i]) === unitOf(ts[j]) && unitOf(ts[i]).tagName === 'g') continue;
        if (rs[i].width && rs[j].width && ovl(rs[i], rs[j]))
          out.push({ kind: '겹침', el: ts[j], other: ts[i], svg });
      }
      ts.forEach(t => { if (hitsStroke(t, svg)) out.push({ kind: '선·마커 겹침', el: t, svg }); });
    });
    return out;
  }

  const all = () => [...htmlIssues(), ...svgIssues()];
  const report = () => all().map(it => [it.kind, it.other ? name(it.el) + ' ↔ ' + name(it.other) : name(it.el)]);

  function clean(unit, svg) {
    const mine = new Set(textsOf(unit));
    const others = [...svg.querySelectorAll('text')].filter(t => !mine.has(t));
    for (const t of mine) {
      if (outside(t, svg) || hitsStroke(t, svg)) return false;
      const r = R(t);
      for (const o of others) if (ovl(r, R(o))) return false;
    }
    return true;
  }

  function move(unit, dy, dx = 0) {
    if (unit.tagName === 'text') {
      unit.setAttribute('y', +unit.getAttribute('y') + dy);
      unit.setAttribute('x', +unit.getAttribute('x') + dx);
    } else {
      const m = (unit.getAttribute('transform') || '').match(/translate\(([-\d.]+),\s*([-\d.]+)\)/);
      unit.setAttribute('transform', `translate(${(m ? +m[1] : 0) + dx},${(m ? +m[2] : 0) + dy})`);
    }
  }

  function shrinkHtml(el) {
    const cur = parseFloat(getComputedStyle(el).fontSize);
    el.dataset.f0 = el.dataset.f0 || cur;
    if (cur <= el.dataset.f0 * 0.66) return false;
    el.style.fontSize = (cur * 0.94).toFixed(1) + 'px';
    return true;
  }

  function shrinkSvg(unit) {
    let ok = false;
    for (const t of textsOf(unit)) {
      const cur = +t.getAttribute('font-size');
      t.dataset.f0 = t.dataset.f0 || cur;
      if (cur > t.dataset.f0 * 0.7) { t.setAttribute('font-size', (cur * 0.92).toFixed(1)); ok = true; }
    }
    return ok;
  }

  function fix() {
    const log = [];
    const shrunk = new Map();  // 글씨 줄인 요소 → 마지막에 '몇 %로' 한 줄씩
    for (let round = 0; round < 10; round++) {
      const iss = all();
      if (!iss.length) break;
      let changed = false;
      const seen = new Set();
      for (const it of iss) {
        if (!it.svg) {
          if (seen.has(it.el)) continue; seen.add(it.el);
          if (shrinkHtml(it.el)) { shrunk.set(it.el, true); changed = true; }
          continue;
        }
        const unit = unitOf(it.el);
        if (seen.has(unit)) continue; seen.add(unit);
        if (it.kind === '그림 밖') {
          const s = R(it.svg), r = R(unit);
          let dx = 0, dy = 0;
          if (r.right > s.right) dx = s.right - r.right - 2;
          if (r.left < s.left) dx = s.left - r.left + 2;
          if (r.bottom > s.bottom) dy = s.bottom - r.bottom - 2;
          if (r.top < s.top) dy = s.top - r.top + 2;
          move(unit, dy, dx); log.push(['안으로 옮김', name(unit)]); changed = true; continue;
        }
        let ok = false;
        // 위·아래 먼저, 안 되면 좌우로도 조금 (가까운 자리부터)
        const tries = [];
        for (const d of [-12, 12, -24, 24, -36, 36, -48, 48]) tries.push([d, 0]);
        for (const d of [-12, 12, -24, 24]) for (const dx of [-30, 30]) tries.push([d, dx]);
        for (const [d, dx] of tries) {
          move(unit, d, dx);
          if (clean(unit, it.svg)) {
            ok = true;
            log.push(['라벨 옮김', `${name(unit)} (${d < 0 ? '위' : '아래'} ${Math.abs(d)}px${dx ? (dx < 0 ? ' · 왼쪽 ' : ' · 오른쪽 ') + Math.abs(dx) + 'px' : ''})`]);
            break;
          }
          move(unit, -d, -dx);
        }
        if (!ok && shrinkSvg(unit)) shrunk.set(unit, true);
        changed = true;
      }
      if (!changed) break;
    }
    for (const el of shrunk.keys()) {
      const t = el.tagName === 'g' ? el.querySelector('text') : el;
      const f0 = +t.dataset.f0, cur = t.tagName === 'text' ? +t.getAttribute('font-size') : parseFloat(getComputedStyle(t).fontSize);
      log.push(['글씨 줄임', `${name(el)} (${Math.round(cur / f0 * 100)}%)`]);
    }
    return log;
  }

  return { report, fix };
})();
"""


def check_and_fix(page) -> dict:
    """페이지에 점검 스크립트를 넣고 검사 → 보정 → 재검사."""
    page.add_script_tag(content=QC_JS)
    before = page.evaluate("__qc.report()")
    fixed = page.evaluate("__qc.fix()") if before else []
    after = page.evaluate("__qc.report()") if before else []
    return {"before": before, "fixed": fixed, "after": after}


def render(html: str, out_dir: Path, stem: str, W: int, H: int) -> tuple[Path, dict]:
    from playwright.sync_api import sync_playwright
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{stem}.html"
    html_path.write_text(html)
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=2)
        page.goto(html_path.as_uri())
        page.evaluate("document.fonts.ready.then(() => true)")
        rep = check_and_fix(page)
        if rep["fixed"]:  # 보정된 모습을 원본 HTML에도 남김
            html_path.write_text(page.content())
        png = out_dir / (f"{stem}_CHECK.png" if rep["after"] else f"{stem}.png")
        page.screenshot(path=str(png), clip={"x": 0, "y": 0, "width": W, "height": H})
        b.close()
    other = out_dir / (f"{stem}.png" if rep["after"] else f"{stem}_CHECK.png")
    if other.exists():
        other.unlink()
    return png, rep
