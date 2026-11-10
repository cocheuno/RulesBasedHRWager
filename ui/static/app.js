/* Race Day Desk front end: plain JS over the JSON API in ui/server.py. */
'use strict';

const S = { cards: [], card: null, data: null, race: null, tab: 'before', horse: null, screen: 'desk', scratches: {}, dirty: false, analysis: null, filters: {} };
const $ = (sel, el = document) => el.querySelector(sel);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const money = v => (v == null ? '' : '$' + Number(v).toFixed(2));

const UNIT_NAMES = [['WIN', 'win'], ['EXACTA', 'exacta'], ['TRIFECTA', 'trifecta'], ['SUPERFECTA', 'superfecta'], ['DOUBLE', 'double'], ['PICK3', 'Pick 3'], ['PICK4', 'Pick 4']];
function unitsText(u) { u = u || { WIN: 2, EXACTA: 1, TRIFECTA: 0.5, SUPERFECTA: 0.1, DOUBLE: 1, PICK3: 1, PICK4: 0.5 }; return UNIT_NAMES.filter(([k]) => u[k] != null).map(([k, n]) => money(u[k]) + ' ' + n).join(', '); }
const pct = v => (v == null ? '' : Math.round(v * 100) + '%');

function toast(msg, ms = 3500) { const t = $('#toast'); t.textContent = msg; t.classList.add('on'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('on'), ms); }
async function api(path, opts = {}) {
  const r = await fetch(path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts));
  const j = await r.json().catch(() => ({ error: r.statusText }));
  if (!r.ok || j.error) throw new Error(j.error || r.statusText);
  return j;
}

// ------------------------------------------------------------------ scratches as race:program text <-> sets
// S.scratches: race -> Set of tokens.  A plain program number is a scratch; "+12" says AE/MTO #12 is officially
// in, "-12" that it stays out.  All three forms survive every round trip to the server (run, PUT, re-run).
function scratchText() { return Object.entries(S.scratches).flatMap(([r, set]) => [...set].map(p => `${r}:${p}`)).join(', '); }
function parseScratches(txt) {
  const out = {};
  (txt || '').split(/[\s,]+/).forEach(tok => { const m = tok.match(/^(\d+):([+-]?)(\d+[A-Za-z]?)$/); if (m) (out[m[1]] = out[m[1]] || new Set()).add(m[2] + m[3].toUpperCase()); });
  return out;
}
function statusOf(set, pgm) { const k = String(pgm).toUpperCase(); return set.has(k) ? 'scr' : set.has('+' + k) ? 'in' : set.has('-' + k) ? 'out' : ''; }

// ------------------------------------------------------------------ loading
async function checkStale() {
  try {
    const st = await api('/api/status');
    let b = $('#stale');
    if (st.code_changed) {
      if (!b) { b = document.createElement('div'); b.id = 'stale'; b.className = 'stale'; document.body.insertBefore(b, document.body.firstChild); }
      b.innerHTML = `<b>The app is running old code.</b> Files changed on disk since it started (${esc(st.changed_files.slice(0, 4).join(', '))}${st.changed_files.length > 4 ? ', …' : ''}). In PowerShell: <code>python ui.py stop</code> then <code>python ui.py start</code>, then reload this page. Picks run now would use the old rules and parser.`;
    } else if (b) b.remove();
  } catch (e) { /* older server without /api/status */ }
}
async function loadCards() {
  await checkStale();
  S.cards = await api('/api/cards');
  const sel = $('#cardSelect');
  sel.innerHTML = S.cards.map(c => `<option value="${esc(c.card)}">${esc(c.card)}${c.track ? ' · ' + esc(c.track) : ''}${c.date ? ' · ' + esc(c.date) : ''}</option>`).join('') || '<option value="">no cards: load PPs</option>';
  if (!S.card && S.cards.length) S.card = S.cards[0].card;
  sel.value = S.card || '';
}
async function loadCard(card) {
  S.card = card; S.data = null; S.dirty = false; S.horse = null;
  if (!card) return render();
  S.data = await api('/api/cards/' + encodeURIComponent(card));
  S.scratches = parseScratches(S.data.state.scratches);
  const races = S.data.roster.length ? S.data.roster : (S.data.picks ? S.data.picks.races : []);
  if (!S.race || !races.some(r => r.race_no === S.race)) S.race = races.length ? races[0].race_no : null;
  render();
}
async function runPicks() {
  if (!S.card) return toast('Load a card first');
  const b = $('#btnRun'); b.disabled = true; b.textContent = 'Running…';
  try { S.data = await api('/api/cards/' + encodeURIComponent(S.card) + '/run', { method: 'POST', body: JSON.stringify({ scratches: scratchText() }) }); S.dirty = false; toast('Picks ready: ' + S.data.state.runs.at(-1).notes.at(-1)); }
  catch (e) { toast('Run failed: ' + e.message, 7000); }
  b.disabled = false; render();
}
async function processResults() {
  if (!S.card) return;
  const b = $('#btnProcess'); b.disabled = true; b.textContent = 'Reading screenshots…';
  try { S.data = await api('/api/cards/' + encodeURIComponent(S.card) + '/process', { method: 'POST', body: '{}' }); const n = (S.data.results ? S.data.results.races : []).filter(r => r.ocr && r.ocr.warnings.length).length; toast('Results read' + (n ? ' — ' + n + ' race(s) need a check' : '') + '; back-test written to results/' + S.card + '.backtest.md', 6000); S.tab = 'after'; }
  catch (e) { toast('Process failed: ' + e.message, 8000); }
  b.disabled = false; b.textContent = 'Process results'; render();
}
async function ocrRace(rn, force) {
  try { S.data = await api('/api/cards/' + encodeURIComponent(S.card) + '/ocr', { method: 'POST', body: JSON.stringify({ race_no: rn, force: !!force }) }); toast('Screenshot r' + rn + '.png read'); }
  catch (e) { toast('OCR failed: ' + e.message, 8000); }
  render();
}

// ------------------------------------------------------------------ rendering
function render() {
  document.querySelectorAll('.tabs a').forEach(a => a.classList.toggle('on', a.dataset.screen === S.screen));
  renderChips();
  const btn = $('#btnRun'); btn.textContent = S.dirty ? 'Re-run with scratches' : (S.data && S.data.picks ? 'Re-run picks' : 'Run picks');
  $('#btnProcess').disabled = !(S.data && S.data.picks && (S.data.results || (S.data.files.pngs || []).length || (S.data.files.charts || []).length));
  const m = $('#screen');
  if (S.screen === 'load') return renderLoad(m);
  if (S.screen === 'analysis') return renderAnalysis(m);
  return renderDesk(m);
}
function renderChips() {
  const c = $('#chips'); if (!S.data) { c.innerHTML = ''; return; }
  const f = S.data.files, nScr = Object.values(S.scratches).reduce((n, s) => n + [...s].filter(t => !/^[+-]/.test(t)).length, 0), nRes = (S.data.results ? S.data.results.races.length : 0), nRaces = S.data.roster.length;
  const prof = S.data.picks ? S.data.picks.track_profile : '';
  c.innerHTML = [
    ['PPs', f.pp || f.card_json, 'good', 'bad'], ['Quick sheet', f.sheet, 'good', ''], [S.data.picks ? 'Picks · profile ' + prof : 'No run yet', !!S.data.picks, 'good', 'warn'],
    [nScr + ' scratches' + (S.dirty ? ' (re-run)' : ''), nScr > 0, 'warn', ''], ['Results ' + nRes + ' / ' + nRaces, nRes > 0, nRes >= nRaces && nRaces ? 'good' : 'warn', '']
  ].map(([t, on, a, b]) => `<span class="chip ${on ? a : b}">${esc(t)}</span>`).join('');
}

function renderDesk(m) {
  if (!S.data) { m.innerHTML = '<div class="card"><h2>No card selected</h2><p class="muted">Go to <a href="#load">Load</a> and drop the day\'s PPs, or copy them to data/pps/&lt;card&gt;.pdf.</p></div>'; return; }
  const d = S.data, picks = d.picks, byNo = {}; (picks ? picks.races : []).forEach(r => byNo[r.race_no] = r);
  const resBy = {}; (d.results ? d.results.races : []).forEach(r => resBy[r.race_no] = r);
  const roster = d.roster.length ? d.roster : (picks ? picks.races.map(r => ({ race_no: r.race_no, class_text: r.class_text, distance_text: r.distance_text, surface: r.surface, horses: r.sheets.map(s => ({ pgm: s.pgm, name: s.name, ml_odds: s.ml_odds, run_style: s.run_style, speed_pts: s.speed_pts })) })) : []);
  const list = roster.map(r => {
    const p = byNo[r.race_no], res = resBy[r.race_no];
    let chip = '';
    if (p && res && res.finish && res.finish.length) {
      const live = p.sheets.filter(s => !s.eliminated && !s.flags.length), w = res.finish[0];
      const rank = live.findIndex(s => s.pgm === w);
      chip = rank === 0 ? `<span class="pos">WIN · #${esc(w)}</span>` : rank > 0 && rank < 3 ? `<span style="color:var(--warn);font-weight:600">top 3 · #${esc(w)} won</span>` : `<span class="neg">miss · #${esc(w)} won</span>`;
    }
    return `<button type="button" class="racebtn ${r.race_no === S.race ? 'on' : ''}" data-race="${r.race_no}">
      <div class="row"><span><b>R${r.race_no}</b> <span class="muted">${esc(r.class_text || '')}</span></span>${p ? `<span class="badge ${p.confidence}">${p.confidence}</span>` : ''}</div>
      <div class="row sub"><span>${esc(r.distance_text || '')}${r.surface ? ' (' + r.surface + ')' : ''}</span>${chip}</div></button>`;
  }).join('');
  const r = roster.find(x => x.race_no === S.race), p = byNo[S.race], res = resBy[S.race];
  m.innerHTML = `<div class="layout"><nav class="racelist" aria-label="Races"><div class="small muted" style="padding:4px 8px">RACES</div>${list}</nav><section class="panel">${r ? racePanel(r, p, res) : '<div class="card muted">Run picks to see the races.</div>'}</section></div>`;
  m.querySelectorAll('.racebtn').forEach(b => b.onclick = () => { S.race = +b.dataset.race; S.horse = null; render(); });
  m.querySelectorAll('.segtabs button').forEach(b => b.onclick = () => { S.tab = b.dataset.tab; render(); });
  m.querySelectorAll('input[data-scr]').forEach(cb => cb.onchange = () => { const [rn, pg] = cb.dataset.scr.split(':'); const set = S.scratches[rn] = S.scratches[rn] || new Set(); cb.checked ? set.add(pg) : set.delete(pg); if (!set.size) delete S.scratches[rn]; S.dirty = true; api('/api/cards/' + encodeURIComponent(S.card) + '/scratches', { method: 'PUT', body: JSON.stringify({ scratches: scratchText() }) }).catch(e => toast(e.message)); render(); });
  m.querySelectorAll('tr[data-horse]').forEach(tr => tr.onclick = ev => { if (ev.target.tagName === 'INPUT') return; S.horse = tr.dataset.horse; render(); });
  const form = $('#resultForm', m); if (form) form.onsubmit = submitResult;
  m.querySelectorAll('button[data-ocr]').forEach(b => b.onclick = () => ocrRace(+b.dataset.ocr, b.dataset.force === '1'));
}

function racePanel(r, p, res) {
  const sheets = p ? p.sheets : [], sb = {}; sheets.forEach(s => sb[s.pgm] = s);
  const leg = (p && p.leg) || {}, scr = S.scratches[r.race_no] || new Set();
  const head = `<div style="display:flex;flex-wrap:wrap;align-items:flex-end;gap:12px"><div><h1>Race ${r.race_no} · ${esc(r.class_text || '')}</h1><div class="muted">${esc(r.distance_text || '')}${r.surface ? ' (' + r.surface + ')' : ''} · field ${r.horses.length - scr.size}${p ? ' · pace ' + p.pace_shape + ' · confidence ' + p.confidence : ''}${r.post_time ? ' · post ' + esc(r.post_time) : ''}</div></div>
    <div class="segtabs"><button type="button" data-tab="before" class="${S.tab === 'before' ? 'on' : ''}">Before the race</button><button type="button" data-tab="after" class="${S.tab === 'after' ? 'on' : ''}">After the race</button></div></div>`;
  const rows = r.horses.map(h => {
    const s = sb[h.pgm], st = statusOf(scr, h.pgm), isScr = st === 'scr';
    const grade = s ? (s.eliminated ? 'ELIM' : s.flags && s.flags.length ? 'AE' : (leg.A || []).includes(s.pgm) ? 'A' : (leg.B || []).includes(s.pgm) ? 'B' : '–') : '';
    const why = s ? s.hits.filter(x => x.points && !x.value).sort((a, b) => Math.abs(b.points) - Math.abs(a.points)).slice(0, 3).map(x => `${x.rule} ${x.points > 0 ? '+' : ''}${x.points.toFixed(1)} ${x.note}`).join('; ') : '';
    const prob = s ? (s.win_prob != null ? s.win_prob : (leg.probs && leg.probs[s.pgm] != null ? leg.probs[s.pgm] : s.implied_prob)) : null;
    const val = s && s.value ? (s.value.label === 'fair' || s.value.edge == null ? s.value.label : `${s.value.label} ${s.value.edge > 0 ? '+' : ''}${Math.round(s.value.edge * 100)}%`) : '';
    return `<tr data-horse="${esc(h.pgm)}" class="clickable ${isScr ? 'scr' : ''} ${S.horse === String(h.pgm) ? 'sel' : ''}"><td><input type="checkbox" data-scr="${r.race_no}:${esc(String(h.pgm).toUpperCase())}" ${isScr ? 'checked' : ''} aria-label="Scratch ${esc(h.name)}"></td><td><b>${esc(h.pgm)}</b></td><td class="muted">${esc(h.post ?? '')}</td><td><b>${esc(h.name)}</b>${h.entry_status ? ' <span class="chip warn">' + esc(h.entry_status) + '</span>' : ''}${st === 'in' ? ' <span class="chip good">officially in</span>' : st === 'out' ? ' <span class="chip">held out</span>' : ''}</td><td>${esc(h.ml_odds ?? '')}</td><td>${esc(h.run_style ?? '')}${h.speed_pts != null ? ' ' + h.speed_pts : ''}</td><td>${s && !isScr ? (s.rank != null ? s.rank : (s.conditional_rank != null ? '(' + s.conditional_rank + ')' : '')) : ''}</td><td>${s && !isScr ? s.score.toFixed(1) : ''}</td><td>${s && !isScr && prob != null ? pct(prob) : ''}</td><td class="small ${val.startsWith('over') ? 'pos' : val.startsWith('under') ? 'neg' : 'muted'}">${s && !isScr ? esc(val) : ''}</td><td class="grade-${grade}">${isScr ? 'SCR' : grade}</td><td class="small muted" style="max-width:380px">${esc(why)}</td></tr>`;
  }).join('');
  const table = `<div class="card tight"><div class="head"><h2>Horses</h2><span class="small muted">tick a horse to mark it scratched, then re-run · click a row for its audit · (rank) = where an AE/MTO would stand if it draws in</span>${S.dirty ? '<span class="chip warn" style="margin-left:auto">scratches changed — re-run picks</span>' : ''}</div><div class="scroll"><table><thead><tr><th>Scr</th><th>Pgm</th><th>PP</th><th>Horse</th><th>ML</th><th>Style/pts</th><th>Rank</th><th>Score</th><th>Win %</th><th>Value</th><th>Grade</th><th>Top reasons</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
  let body = '';
  if (S.tab === 'before') {
    const names = {}; r.horses.forEach(h => names[h.pgm] = h.name);
    const play = p ? (p.picks.length ? p.picks.map(k => `#${k} ${names[k] || ''} (${sb[k] ? sb[k].ml_odds : ''})`).join(', ') : 'PASS') : '';
    const tickets = p ? multiTickets(r.race_no) : '';
    body = table + `<div class="grid2"><div class="card"><h2>Bets from pick.py</h2>${p ? `<div class="play" style="margin-top:10px"><div class="k">PRIMARY PLAY · confidence ${p.confidence}</div><div class="v">${esc(play)}</div><div class="muted">${esc(p.bet_structure)}</div></div><div class="small muted" style="margin-top:10px;font-weight:600">OTHER WAGERS</div><ul style="margin:6px 0 0;padding-left:18px">${(p.other_wagers || []).map(w => `<li>${esc(w)}</li>`).join('')}</ul>` : '<p class="muted">Run picks first.</p>'}</div>
      <div class="card"><h2>Multi-race tickets that include this race</h2>${tickets || '<p class="muted">None recommended through this race.</p>'}</div></div>` + audit(p);
  } else {
    const hasPng = (S.data.files.pngs || []).includes(`r${r.race_no}.png`) || (S.data.files.charts || []).includes(`r${r.race_no}.pdf`);
    body = (res && res.finish && res.finish.length ? afterPanel(r, p, res) : (hasPng ? `<div class="card"><h2>Screenshot r${r.race_no}.png is loaded but not read yet</h2><p class="muted">Press <b>Process results</b> to read every screenshot, or read just this one.</p><button class="btn primary" type="button" data-ocr="${r.race_no}">Read this screenshot</button></div>` : resultForm(r, p))) + audit(p);
  }
  return head + body;
}
function multiTickets(rn) {
  const mr = S.data.picks && S.data.picks.multirace; if (!mr) return '';
  return ['pick3', 'pick4'].map(k => { const rec = mr[k] && mr[k].recommended; if (!rec || !rec.races.includes(rn)) return ''; return `<div class="soft" style="margin-top:10px"><b>${esc(rec.name)}</b> · ${money(rec.cost)} · hit probability est. ${pct(rec.hit_prob)} · <span class="muted">tracked, not counted as a bet</span><div class="small muted" style="margin-top:6px;line-height:1.6">${rec.tickets.map(t => `${esc(t.name)}: ${t.legs.map(l => l.join(',')).join(' / ')} — ${money(t.cost)}`).join('<br>')}</div></div>`; }).join('');
}
function audit(p) {
  if (!p) return '';
  const s = p.sheets.find(x => x.pgm === S.horse) || p.sheets[0]; if (!s) return '';
  return `<div class="card"><div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px"><h2>Rule-by-rule audit · #${esc(s.pgm)} ${esc(s.name)} · ${s.score.toFixed(1)}</h2><span class="small muted">every point traces to a rule id</span></div><div class="scroll" style="margin-top:8px"><table><thead><tr><th>Rule</th><th>Name</th><th>Points</th><th>Note</th></tr></thead><tbody>${s.hits.map(h => `<tr><td><b style="color:var(--accent)">${esc(h.rule)}</b></td><td>${esc(h.name)}</td><td class="${h.points < 0 ? 'neg' : h.points > 0 ? 'pos' : 'muted'}">${h.points ? (h.points > 0 ? '+' : '') + h.points.toFixed(2) : ''}</td><td class="small muted">${esc(h.note)}</td></tr>`).join('')}</tbody></table></div></div>`;
}
function afterPanel(r, p, res) {
  const names = {}; r.horses.forEach(h => names[h.pgm] = h.name);
  const places = ['1st', '2nd', '3rd', '4th', '5th'];
  const odds = res.final_odds || {}, runners = {}; (res.runners || []).forEach(x => runners[x.pgm] = x);
  const finish = `<div class="finish">${res.finish.slice(0, 6).map((pg, i) => `<div><span class="p">${places[i] || (i + 1) + 'th'}</span><span class="n">#${esc(pg)}</span><span class="h">${esc(names[pg] || (runners[pg] || {}).name || '')}</span>${odds[pg] != null ? `<span class="h">${odds[pg]}-1${runners[pg] && runners[pg].beaten ? ' · ' + runners[pg].beaten + 'L' : ''}</span>` : ''}</div>`).join('')}</div>`;
  const pay = [res.win != null ? ['WIN', '#' + res.finish[0], '$2', money(res.win)] : null].filter(Boolean)
    .concat(Object.entries(res.place || {}).map(([k, v]) => ['PLACE', '#' + k, '$2', money(v)]), Object.entries(res.show || {}).map(([k, v]) => ['SHOW', '#' + k, '$2', money(v)]),
      (res.exotics || []).map(e => [e.type, e.combo, money(e.base), money(e.payout)]));
  const png = (S.data.files.pngs || []).includes(`r${r.race_no}.png`) ? `<a href="/png/${encodeURIComponent(S.card)}/r${r.race_no}.png" target="_blank"><img class="shot" src="/png/${encodeURIComponent(S.card)}/r${r.race_no}.png" alt="Payout page race ${r.race_no}"></a>` : '<div class="drop">no screenshot r' + r.race_no + '.png loaded</div>';
  const ev = S.data.evaluation, rows = ev ? ev.rows.filter(x => x.races.includes(r.race_no) && !x.tracked_only) : [], tracked = ev ? ev.rows.filter(x => x.races.includes(r.race_no) && x.tracked_only) : [];
  const bt = S.data.backtest && S.data.backtest.races.find(x => x.race_no === r.race_no);
  const ocr = res.ocr || null;
  const check = ocr ? (ocr.source === 'chart' ? `<div class="small muted" style="margin-top:8px">read from the official chart${res.track_condition ? ' · track ' + esc(res.track_condition) : ''}${res.final_odds ? ' · final odds on file' : ''}</div>` : ocr.warnings.length ? `<div class="soft" style="margin-top:10px;background:var(--warn-bg);color:var(--warn)"><b>Check this result</b> — read from the screenshot with confidence ${ocr.confidence}: ${esc(ocr.warnings.join('; '))}. Correct it below if it is wrong.</div>` : `<div class="small muted" style="margin-top:8px">read from the screenshot (confidence ${ocr.confidence}; names ${esc((ocr.names || []).filter(Boolean).join(', '))})</div>`) : '';
  const reread = (S.data.files.pngs || []).includes(`r${r.race_no}.png`) ? `<button class="btn small" type="button" data-ocr="${r.race_no}" data-force="1" style="margin-left:8px">Re-read screenshot</button>` : '';
  return `<div class="grid2"><div class="card"><div style="display:flex;justify-content:space-between;align-items:center"><h2>Result</h2><span class="small muted">r${r.race_no}.png ${reread}</span></div>${check}<div style="margin-top:10px">${finish}</div><table style="margin-top:10px"><thead><tr><th>Pool</th><th>Combo</th><th>Base</th><th>Paid</th></tr></thead><tbody>${pay.map(x => `<tr><td>${esc(x[0])}</td><td><b>${esc(x[1])}</b></td><td class="muted">${x[2]}</td><td><b>${x[3]}</b></td></tr>`).join('')}</tbody></table><div style="margin-top:10px">${png}</div><details style="margin-top:10px"><summary class="small muted">Edit this result</summary>${resultForm(r, p, res)}</details></div>
    <div class="card"><h2>Bet results — what the suggested wagers returned</h2><div class="small muted">${S.data.latest_kind === 'as-run' ? '<b>As-run re-score</b> (retrospective: the field as the charts say it ran). ' : ''}${S.data.pre_race ? `Pre-race snapshot (${esc(S.data.pre_race.snapshot.at_utc)} UTC): ${S.data.pre_race.evaluation.totals.hits} of ${S.data.pre_race.evaluation.totals.bets} bets hit, staked ${money(S.data.pre_race.evaluation.totals.cost)}, returned ${money(S.data.pre_race.evaluation.totals.ret)} — that is the honest number. ` : 'No pre-race snapshot on file for this card. '}Unit stakes: ${esc(unitsText(S.data.evaluation && S.data.evaluation.units))}.</div><table style="margin-top:8px"><thead><tr><th>Wager</th><th>Unit</th><th>Cost</th><th>Result</th><th>Return</th></tr></thead><tbody>${rows.map(x => `<tr><td>${esc(x.label)}</td><td>${money(x.unit == null ? 1 : x.unit)}</td><td>${money(x.cost)}</td><td class="${x.placed === false ? 'muted' : x.hit ? 'hit' : x.known ? 'miss' : 'unknown'}">${x.placed === false ? (x.status || 'passed') : x.hit ? 'HIT' : x.known ? 'miss' : 'unknown'}${x.note ? '<div class="small muted">' + esc(x.note) + '</div>' : ''}</td><td><b>${x.ret == null ? (x.hit ? 'payout not on file' : '') : money(x.ret)}</b></td></tr>`).join('') || '<tr><td colspan="5" class="muted">no wagers evaluated (run picks first)</td></tr>'}</tbody></table>${tracked.length ? `<div class="small muted" style="margin-top:10px"><b>Pick 3 / 4 tickets through this race — tracked, not counted as bets:</b> ${tracked.map(x => `${esc(x.label)} ${money(x.cost)} ${x.hit ? 'HIT ' + money(x.ret) : x.known ? 'miss' : 'unknown'}`).join(' · ')}</div>` : ''}
    ${bt ? `<div class="soft" style="margin-top:10px;line-height:1.6"><b>Winner #${esc(bt.winner)}</b> ranked ${bt.winner_rank ?? '—'} by the engine${bt.winner_eliminated ? ' (had been eliminated)' : ''}; top pick #${esc(bt.top_pick)} ${bt.top_pick_won ? 'won' : bt.winner_in_top3 ? 'did not win but the winner was in the top 3' : 'missed'}.${bt.brisnet_pick ? ` Brisnet pick #${esc(bt.brisnet_pick)}${bt.brisnet_won ? ' won' : ''}.` : ''}</div>` : ''}</div></div>`;
}
function resultForm(r, p, res) {
  const ex = (res && res.exotics ? res.exotics : []).map(e => `${e.type} ${e.base} ${e.combo} ${e.payout}`).join('\n');
  const kv = o => Object.entries(o || {}).map(([k, v]) => `${k}:${v}`).join(', ');
  return `<form id="resultForm" class="card"><h2>Enter the result for race ${r.race_no}</h2><p class="small muted">Copy from the payout page (or its screenshot). Finish order and win payoff are enough for the back-test; exotics make the bet results complete. One exotic per line: <code>EXACTA 1 8/3 40.10</code> (type, base, combo, payout).</p>
    <p class="small muted">Normally the screenshot is read for you (Process results). This form is the fallback and the way to correct a misread.</p>
    <div class="form"><label>Finish order, program numbers<input type="text" name="finish" value="${esc((res && res.finish || []).join('/'))}" placeholder="8/3/1/4" required></label><label>Win payoff ($2)<input type="number" step="0.01" name="win" value="${res && res.win != null ? res.win : ''}" placeholder="9.40"></label>
    <label>Place ($2), program:amount<input type="text" name="place" value="${esc(kv(res && res.place))}" placeholder="8:5.40, 3:6.80"></label><label>Show ($2), program:amount<input type="text" name="show" value="${esc(kv(res && res.show))}" placeholder="8:3.00, 3:4.40, 1:2.60"></label>
    <label class="wide">Exotics<textarea name="exotics" placeholder="EXACTA 1 8/3 40.10&#10;TRIFECTA 0.5 8/3/1 79.20&#10;DOUBLE 2 6/8 29.80&#10;PICK3 0.5 1/6/8 19.55">${esc(ex)}</textarea></label></div>
    <div style="display:flex;gap:8px;margin-top:10px;align-items:center"><button class="btn primary" type="submit">Save result</button><span class="small muted">saved to results/${esc(S.card)}.results.json — commit that file</span></div></form>`;
}
async function submitResult(ev) {
  ev.preventDefault();
  const f = ev.target, kv = s => Object.fromEntries((s || '').split(/[,\s]+/).filter(Boolean).map(x => x.split(':')).filter(a => a.length === 2));
  const exotics = (f.exotics.value || '').split('\n').map(l => l.trim().split(/\s+/)).filter(a => a.length >= 4).map(a => ({ type: a[0], base: a[1], combo: a[2], payout: a[3] }));
  const body = { race_no: S.race, finish: f.finish.value.split('/'), win: f.win.value || null, place: kv(f.place.value), show: kv(f.show.value), exotics };
  try { S.data = await api('/api/cards/' + encodeURIComponent(S.card) + '/results', { method: 'POST', body: JSON.stringify(body) }); toast('Result saved for race ' + S.race); S.tab = 'after'; }
  catch (e) { toast('Save failed: ' + e.message, 7000); }
  render();
}

// ------------------------------------------------------------------ Load screen
function renderLoad(m) {
  const d = S.data, f = d ? d.files : {}, st = d ? d.state : { runs: [], activity: [] };
  const code = S.card || '';
  m.innerHTML = `<div style="display:flex;flex-wrap:wrap;align-items:flex-end;gap:12px"><div><h1>Load documents for a race day</h1><div class="muted">Card code = the PP file name (e.g. dmr1106y). Files go to data/ on this computer; nothing here is committed except the results file.</div></div>
    <label class="field" style="margin-left:auto">New card code <input type="text" id="newCard" placeholder="gpx1107y" value="${esc(code)}" style="width:160px"></label></div>
    <div class="grid3" style="margin-top:16px">
      <div class="card"><div style="display:flex;justify-content:space-between;align-items:center"><h2>1 · Ultimate PPs</h2><span class="chip ${f.pp ? 'good' : ''}">${f.pp ? 'loaded' : 'not loaded'}</span></div><label class="drop" style="margin-top:10px">Drop or choose &lt;card&gt;.pdf<input type="file" accept="application/pdf" data-kind="pp" hidden></label>${d && d.meta.track ? `<div class="small muted" style="margin-top:8px">${esc(d.meta.track)} (${esc(d.meta.track_code || '')}) · ${esc(d.meta.date || '')} · ${d.roster.length} races</div>` : ''}${f.pp ? '<button class="btn small" type="button" id="btnReparse" style="margin-top:8px">Re-read PPs and re-run picks</button><div class="small muted" style="margin-top:4px">The PDF is re-read on its own when it is newer than the cached card or the parser has changed.</div>' : ''}</div>
      <div class="card"><div style="display:flex;justify-content:space-between;align-items:center"><h2>2 · Power Play quick sheet</h2><span class="chip ${f.sheet ? 'good' : ''}">${f.sheet ? 'loaded' : 'optional'}</span></div><label class="drop" style="margin-top:10px">Drop or choose &lt;card&gt;q.pdf<br><span class="small">turns on the key-race rule and the Brisnet benchmark</span><input type="file" accept="application/pdf" data-kind="sheet" hidden></label></div>
      <div class="card"><div style="display:flex;justify-content:space-between;align-items:center"><h2>3 · Results</h2><span class="chip ${((f.charts || []).length + (f.pngs || []).length) ? 'good' : ''}">${(f.charts || []).length} charts · ${(f.pngs || []).length} screenshots</span></div>
        <label class="drop" style="margin-top:10px"><b>Result charts (PDF)</b> — best: drop them as downloaded (20261106BELUSA1.pdf) or as r1.pdf …<br><span class="small">every finisher, final odds, condition, comments; no OCR needed</span><input type="file" accept="application/pdf" multiple data-kind="chart" hidden></label>
        <label class="drop" style="margin-top:8px">Payout-page screenshots named r1.png, r2.png …<br><span class="small">read by OCR; a chart for the same race wins</span><input type="file" accept="image/png" multiple data-kind="png" hidden></label>
        <div class="small muted" style="margin-top:8px">${(f.charts || []).concat(f.pngs || []).join(' · ')}</div>
        ${((f.charts || []).length || (f.pngs || []).length) ? '<button class="btn small" type="button" id="btnReread" style="margin-top:8px">Re-read all results files</button>' : ''}</div></div>
    <div class="card" style="margin-top:16px"><h2>Scratches</h2><div class="filters" style="margin-top:8px"><input type="text" id="scrText" style="flex:1 1 420px" value="${esc(scratchText())}" placeholder="2:10, 4:2, 4:11, 7:13" aria-label="Scratch list"><button class="btn primary" type="button" id="btnApply">Apply and re-run picks</button></div><div class="small muted" style="margin-top:8px">race:program pairs; also-eligibles draw in automatically; 4:+12 = AE/MTO #12 officially in, 4:-12 = held out; or tick horses on the Desk.</div></div>
    <div class="grid2" style="margin-top:16px"><div class="card"><h2>Runs kept for this card</h2><div class="small muted">Every run is frozen in data/out/snapshots; "pre-race" runs are the ones the analysis is scored on.</div><table style="margin-top:8px"><thead><tr><th>When</th><th>Kind</th><th>Scratches</th><th>Profile</th></tr></thead><tbody>${(st.runs || []).slice().reverse().map(r => `<tr><td class="muted">${esc(r.at)}</td><td>${esc(r.kind || '')}</td><td>${esc(r.scratches || '—')}</td><td>${esc(r.profile || '')}</td></tr>`).join('') || '<tr><td colspan="4" class="muted">none yet</td></tr>'}</tbody></table></div>
    <div class="card"><h2>Activity</h2><table style="margin-top:8px"><thead><tr><th>When</th><th>Step</th><th>Outcome</th></tr></thead><tbody>${(st.activity || []).slice().reverse().map(a => `<tr><td class="muted">${esc(a.at)}</td><td>${esc(a.step)}</td><td>${esc(a.outcome)}</td></tr>`).join('') || '<tr><td colspan="3" class="muted">nothing yet</td></tr>'}</tbody></table></div></div>`;
  m.querySelectorAll('input[type=file]').forEach(inp => inp.onchange = () => upload(inp.dataset.kind, inp.files));
  m.querySelectorAll('.drop').forEach(z => { z.ondragover = e => { e.preventDefault(); }; z.ondrop = e => { e.preventDefault(); upload($('input', z).dataset.kind, e.dataTransfer.files); }; });
  const rr = $('#btnReread', m); if (rr) rr.onclick = async () => { rr.disabled = true; rr.textContent = 'Reading…'; try { S.data = await api('/api/cards/' + encodeURIComponent(S.card) + '/ocr', { method: 'POST', body: JSON.stringify({ force: true }) }); toast('All results files re-read'); } catch (e) { toast('Re-read failed: ' + e.message, 8000); } render(); };
  const rp = $('#btnReparse', m); if (rp) rp.onclick = async () => { rp.disabled = true; rp.textContent = 'Re-reading…'; try { S.data = await api('/api/cards/' + encodeURIComponent(S.card) + '/run', { method: 'POST', body: JSON.stringify({ scratches: scratchText(), reparse: true }) }); S.dirty = false; toast('PPs re-read: ' + S.data.state.runs.at(-1).notes.at(-1)); } catch (e) { toast('Re-read failed: ' + e.message, 8000); } render(); };
  $('#btnApply', m).onclick = async () => { S.scratches = parseScratches($('#scrText', m).value); await runPicks(); S.screen = 'desk'; location.hash = '#desk'; render(); };
}
async function upload(kind, files) {
  const card = ($('#newCard') && $('#newCard').value.trim()) || S.card;
  if (!card) return toast('Type a card code first (e.g. gpx1107y)');
  for (const file of files) {
    const fd = new FormData(); fd.append('card', card); fd.append('kind', kind); fd.append('file', file, file.name);
    try { const r = await fetch('/api/upload', { method: 'POST', body: fd }); const j = await r.json(); if (j.error) throw new Error(j.error); toast('Saved ' + j.saved.join(', ')); }
    catch (e) { toast('Upload failed: ' + e.message, 7000); }
  }
  await loadCards(); await loadCard(card);
}

// ------------------------------------------------------------------ Analysis screen
async function renderAnalysis(m) {
  if (!S.analysis) { m.innerHTML = '<div class="card muted">Loading…</div>'; try { S.analysis = await api('/api/analysis'); } catch (e) { m.innerHTML = '<div class="card neg">' + esc(e.message) + '</div>'; return; } }
  const A = S.analysis, F = S.filters;
  if (!A.rollup) { m.innerHTML = '<div class="card"><h2>Wagering analysis</h2><p class="muted">No card has both a run and results yet. Run picks, enter results, then come back.</p></div>'; return; }
  const passedRows = A.rows.filter(x => x.placed === false).length;
  const rows = A.rows.filter(x => x.placed !== false && !x.tracked_only).filter(x => (!F.track || x.track === F.track) && (!F.type || x.type === F.type) && (!F.conf || x.confidence === F.conf) && (!F.from || (x.date || '') >= F.from) && (!F.to || (x.date || '') <= F.to));
  const agg = key => { const g = {}; rows.forEach(x => { const k = key(x); const d = g[k] = g[k] || { bets: 0, hits: 0, misses: 0, unknown: 0, cost: 0, ret: 0 }; d.bets++; if (!x.known) { d.unknown++; return; } x.hit ? d.hits++ : d.misses++; d.cost += x.cost; d.ret += x.ret || 0; }); return g; };
  const byTrack = agg(x => x.track || '?'), byType = agg(x => x.type), byConf = agg(x => x.confidence || '?');
  const all = Object.values(byTrack).reduce((a, d) => ({ bets: a.bets + d.bets, hits: a.hits + d.hits, misses: a.misses + d.misses, unknown: a.unknown + d.unknown, cost: a.cost + d.cost, ret: a.ret + d.ret }), { bets: 0, hits: 0, misses: 0, unknown: 0, cost: 0, ret: 0 });
  const roi = d => d.cost ? (d.ret - d.cost) / d.cost : null, roiCell = d => { const r = roi(d); return r == null ? '' : `<span class="${r >= 0 ? 'pos' : 'neg'}">${r >= 0 ? '+' : ''}${Math.round(r * 100)}%</span>`; };
  const series = Object.entries(byTrack).map(([t, d]) => ({ track: t, hits: d.hits, misses: d.misses })).concat([{ track: 'ALL', hits: all.hits, misses: all.misses }]);
  const max = Math.max(1, ...series.map(s => s.hits + s.misses));
  const tracks = [...new Set(A.rows.map(x => x.track).filter(Boolean))], types = [...new Set(A.rows.map(x => x.type))], confs = [...new Set(A.rows.map(x => x.confidence).filter(Boolean))];
  const opt = (list, cur) => '<option value="">All</option>' + list.map(v => `<option ${v === cur ? 'selected' : ''}>${esc(v)}</option>`).join('');
  const tbl = (g, label) => `<table><thead><tr><th>${label}</th><th>Bets</th><th>Hits</th><th>Misses</th><th>Unknown</th><th>Cost</th><th>Return</th><th>ROI</th></tr></thead><tbody>${Object.entries(g).map(([k, d]) => `<tr><td><b>${esc(k)}</b></td><td>${d.bets}</td><td>${d.hits}</td><td>${d.misses}</td><td>${d.unknown}</td><td>${money(d.cost)}</td><td>${money(d.ret)}</td><td>${roiCell(d)}</td></tr>`).join('')}</tbody></table>`;
  const cardsTbl = A.cards.map(c => `<tr><td><a href="#desk" data-card="${esc(c.card)}"><b>${esc(c.card)}</b></a></td><td>${esc(c.track || '')}</td><td class="small muted">${esc(c.basis || '')}</td><td>${c.races}</td><td>${c.top_pick_wins}</td><td>${c.winner_in_top3}</td><td>${c.hits} / ${c.bets}</td><td>${Object.entries(c.multirace).map(([k, v]) => k + (v ? ' hit' : ' miss')).join(' · ') || '—'}</td><td class="${c.ret - c.cost >= 0 ? 'pos' : 'neg'}">${money(c.ret - c.cost)}</td></tr>`).join('');
  const b = A.benchmark;
  m.innerHTML = `<div style="display:flex;flex-wrap:wrap;align-items:flex-end;gap:12px"><div><h1>Wagering analysis</h1><div class="muted">Every suggested wager at its unit stake (${esc(A.units_text || unitsText(A.units))}), other wagers counted as bets placed, across every card with results on file.</div></div>
    <div class="filters" style="margin-left:auto"><label class="field">From <input type="text" id="fFrom" value="${esc(F.from || '')}" placeholder="2026-11-01" style="width:120px"></label><label class="field">To <input type="text" id="fTo" value="${esc(F.to || '')}" placeholder="2026-11-30" style="width:120px"></label><label class="field">Track <select id="fTrack">${opt(tracks, F.track)}</select></label><label class="field">Bet <select id="fType">${opt(types, F.type)}</select></label><label class="field">Confidence <select id="fConf">${opt(confs, F.conf)}</select></label></div></div>
    <div class="kpis" style="margin-top:14px">${[['CARDS · RACES', A.cards.length + ' · ' + A.cards.reduce((n, c) => n + c.races, 0), ''], ['TOP PICK WON', A.cards.reduce((n, c) => n + c.top_pick_wins, 0) + ' / ' + A.cards.reduce((n, c) => n + c.races, 0), ''], ['WINNER IN TOP 3', A.cards.reduce((n, c) => n + c.winner_in_top3, 0) + ' / ' + A.cards.reduce((n, c) => n + c.races, 0), ''], ['BETS (FILTERED)', all.bets, all.hits + ' successful · ' + all.misses + ' unsuccessful' + (passedRows ? ' · ' + passedRows + ' win bets passed (price)' : '')], ['STAKED · RETURNED', money(all.cost) + ' · ' + money(all.ret), A.rollup.tracked_multirace && A.rollup.tracked_multirace.tickets ? 'Pick 3/4: ' + A.rollup.tracked_multirace.hits + ' of ' + A.rollup.tracked_multirace.tickets + ' tickets hit, tracked not counted' : ''], ['ROI', roi(all) == null ? '—' : (roi(all) >= 0 ? '+' : '') + Math.round(roi(all) * 100) + '%', A.cards.length < 5 ? 'few cards: not yet meaningful' : '']].map(([l, v, s]) => `<div class="card kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join('')}</div>
    <div class="card" style="margin-top:14px"><div style="display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px;align-items:center"><h2>Bets won and lost, by track</h2><div class="legend" aria-label="Legend"><span><span class="sw" style="background:var(--hit)"></span>successful</span><span><span class="sw" style="background:var(--miss)"></span>unsuccessful</span></div></div>
      <div class="bars" style="margin-top:12px">${series.map(s => `<div class="bar"><div class="t">${esc(s.track)}</div><div class="seg" title="${esc(s.track)}: ${s.hits} successful, ${s.misses} unsuccessful"><div style="background:var(--hit);width:${(100 * s.hits / max).toFixed(1)}%"></div><div style="background:var(--miss);width:${(100 * s.misses / max).toFixed(1)}%"></div></div><div class="c">${s.hits} won · ${s.misses} lost · ${s.hits + s.misses} bets</div></div>`).join('')}</div><div class="small muted" style="margin-top:8px">scale 0 to ${max} bets; the By-track table is the same data</div></div>
    <div class="grid2" style="margin-top:14px"><div class="card"><h2>By bet type</h2>${tbl(byType, 'Bet')}</div><div class="card"><h2>By track and by confidence</h2>${tbl(byTrack, 'Track')}<div style="height:10px"></div>${tbl(byConf, 'Confidence')}${b.races ? `<div class="soft" style="margin-top:10px">Engine vs Brisnet Power Play over ${b.races} races with a sheet: engine top pick won ${b.engine_wins}, Brisnet top pick won ${b.brisnet_wins} (winner in its Top 3: ${b.brisnet_top3}), Best Bets ${b.best_bet_wins}/${b.best_bets}.</div>` : ''}</div></div>
    <div class="grid2" style="margin-top:14px"><div class="card"><h2>By rule — when the rule fired, how often that horse won</h2><div class="scroll"><table><thead><tr><th>Rule</th><th>Sign</th><th>Fired</th><th>Won</th><th>Win %</th><th>ITM %</th></tr></thead><tbody>${A.rules.map(r => `<tr style="${r.fired < 20 ? 'color:#8A8A94' : ''}"><td><b style="color:var(--accent)">${esc(r.rule)}</b></td><td>${esc(r.sign)}</td><td>${r.fired}</td><td>${r.won}</td><td><b>${r.win_pct}%</b></td><td>${r.itm_pct}%</td></tr>`).join('')}</tbody></table></div><div class="small muted" style="margin-top:6px">grey rows have under 20 firings</div></div>
    <div class="card"><h2>Cards</h2><div class="scroll"><table><thead><tr><th>Card</th><th>Track</th><th>Basis</th><th>Races</th><th>Top pick won</th><th>Top 3</th><th>Bets hit</th><th>Pick 3 / 4</th><th>Net</th></tr></thead><tbody>${cardsTbl}</tbody></table></div></div></div>`;
  ['fFrom', 'fTo', 'fTrack', 'fType', 'fConf'].forEach(id => { const el = $('#' + id, m); el.onchange = () => { S.filters = { from: $('#fFrom', m).value, to: $('#fTo', m).value, track: $('#fTrack', m).value, type: $('#fType', m).value, conf: $('#fConf', m).value }; renderAnalysis(m); }; });
  m.querySelectorAll('a[data-card]').forEach(a => a.onclick = async e => { e.preventDefault(); S.screen = 'desk'; location.hash = '#desk'; $('#cardSelect').value = a.dataset.card; await loadCard(a.dataset.card); });
}

// ------------------------------------------------------------------ boot
function route() { const h = (location.hash || '#desk').slice(1); S.screen = ['desk', 'load', 'analysis'].includes(h) ? h : 'desk'; if (S.screen === 'analysis') S.analysis = null; render(); }
window.addEventListener('hashchange', route);
$('#cardSelect').onchange = e => loadCard(e.target.value);
$('#btnRun').onclick = runPicks;
$('#btnProcess').onclick = processResults;
(async () => { try { await loadCards(); if (S.card) await loadCard(S.card); } catch (e) { toast(e.message, 8000); } route(); })();
