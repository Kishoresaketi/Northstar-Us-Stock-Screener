#!/usr/bin/env node
// Local verification for the Shareholders section: the top institutional
// holders and top insiders tables, and the summary split (institutions /
// insiders / public). Extracts the pure row builders from profile.js and
// runs them against a hand-built fixture, and — when the real
// data/top-holders.json exists — against every ticker in it (top-5 sums
// must reconcile with the audited totals, shares must rank descending,
// no invented holders). No DOM, no network, no push.
//
// Run:  node tests/test_profile_topholders.js
//
// NOTE: no 'use strict' here on purpose — the extracted functions are
// loaded with a direct eval in sloppy mode so their declarations land
// in this file's scope.
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'profile.js'), 'utf8');

function extract(name) {
  let start = src.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`function ${name} not found in profile.js`);
  if (src.slice(start - 6, start) === 'async ') start -= 6;
  let i = src.indexOf('{', start);
  let depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') { depth--; if (depth === 0) return src.slice(start, i + 1); }
  }
  throw new Error(`unbalanced braces in ${name}`);
}

for (const name of ['fmtPct', 'fmtShares', 'shareholdingSummaryRows', 'topInstitutionRows', 'topInsiderRows']) {
  eval(extract(name));
}

// --- Fixture: one AAPL-shaped entry -------------------------------------
const fixture = {
  institutions: {
    top: [
      { name: 'BlackRock, Inc.', cik: '2012383', shares: 1050000000, pct: 0.0722 },
      { name: 'Vanguard Capital Management LLC', cik: '2100119', shares: 959000000, pct: 0.0660 },
      { name: 'State Street Corp', cik: '93751', shares: 615000000, pct: 0.0423 },
    ],
    managers: 6073, total_shares: 9508327855, pct: 0.6543,
  },
  insiders: {
    top: [
      { name: 'Timothy D. Cook', cik: '1214128', shares: 3200000, pct: 0.0002, filing_date: '2026-11-17' },
      { name: 'Arthur D. Levinson', cik: '1214128', shares: 1100000, pct: 0.0001, filing_date: '2026-11-18' },
    ],
    total_shares: 12345678, total_pct: 0.0008, owners_measured: 14,
  },
  public_pct: 0.3449,
};

let checks = 0;
function check(cond, msg) { assert.ok(cond, msg); checks++; }

// fmtShares
check(fmtShares(null) === '—', 'fmtShares null is a dash');
check(fmtShares(1050000000) === '1,050M', `fmtShares millions: ${fmtShares(1050000000)}`);
check(fmtShares(3200000) === '3M', `fmtShares small millions: ${fmtShares(3200000)}`);
check(fmtShares(500) === '500', `fmtShares sub-million: ${fmtShares(500)}`);

// Summary rows: insiders measured
let rows = shareholdingSummaryRows(0.6543, 0.0008);
check(rows[0][1] === '65.4%', `institutions pct: ${rows[0][1]}`);
check(rows[1][1] === '0.1%', `insiders pct: ${rows[1][1]}`);
check(rows[2][0] === 'Public (aggregate)', `public label: ${rows[2][0]}`);
check(rows[2][1] === '34.5%', `public pct: ${rows[2][1]}`);

// Summary rows: insiders unmeasured (old behaviour preserved)
rows = shareholdingSummaryRows(0.6543, null);
check(rows[1][1] === '—', 'insiders dash when unmeasured');
check(rows[2][0] === 'Public (includes insiders)', `public label fallback: ${rows[2][0]}`);
check(rows[2][1] === '34.6%', `public pct fallback: ${rows[2][1]}`);

// Top institution rows
rows = topInstitutionRows(fixture.institutions.top);
check(rows.length === 3, 'three institution rows');
check(rows[0][0] === 1 && rows[0][1] === 'BlackRock, Inc.', 'first row is BlackRock');
check(rows[0][2] === '1,050M' && rows[0][3] === '7.2%', `first row values: ${rows[0][2]} ${rows[0][3]}`);
check(rows[2][2] === '615M', 'third row shares');

// Top insider rows
rows = topInsiderRows(fixture.insiders.top);
check(rows.length === 2, 'two insider rows');
check(rows[0][1] === 'Timothy D. Cook', 'first insider is Cook');
check(rows[0][4] === '2026-11-17', 'filing date shown');
check(rows[1][3] === '0.0%', `small pct rounds to 0.0%: ${rows[1][3]}`);
check(topInsiderRows([]).length === 0, 'empty insiders render no rows');
check(topInstitutionRows(null).length === 0, 'null top renders no rows');

// --- Real data, when it exists ------------------------------------------
const topPath = path.join(ROOT, 'data', 'top-holders.json');
const shPath = path.join(ROOT, 'data', 'shareholding.json');
if (fs.existsSync(topPath) && fs.existsSync(shPath)) {
  const top = JSON.parse(fs.readFileSync(topPath, 'utf8'));
  const sh = JSON.parse(fs.readFileSync(shPath, 'utf8'));
  let tickers = 0;
  for (const [symbol, entry] of Object.entries(top.entries)) {
    tickers++;
    const inst = entry.institutions;
    const shEntry = sh.entries[symbol];
    check(inst.top.length <= 5, `${symbol}: at most 5 institutions`);
    const shares = inst.top.map(h => h.shares);
    check(shares.every((s, i) => i === 0 || s <= shares[i - 1]), `${symbol}: institutions ranked descending`);
    const topSum = shares.reduce((a, b) => a + b, 0);
    check(topSum <= inst.total_shares, `${symbol}: top-5 sum ${topSum} exceeds total ${inst.total_shares}`);
    if (shEntry && shEntry.institutions_shares != null) {
      check(inst.total_shares === shEntry.institutions_shares,
        `${symbol}: per-manager total ${inst.total_shares} != audited ${shEntry.institutions_shares}`);
    }
    const ins = entry.insiders;
    if (ins && ins.top.length) {
      const ishares = ins.top.map(h => h.shares);
      check(ishares.every((s, i) => i === 0 || s <= ishares[i - 1]), `${symbol}: insiders ranked descending`);
      check(ins.top.length <= 5, `${symbol}: at most 5 insiders`);
      const itopSum = ishares.reduce((a, b) => a + b, 0);
      check(itopSum <= ins.total_shares, `${symbol}: insider top-5 sum exceeds insider total`);
      check(ins.top.every(h => h.filing_date), `${symbol}: every insider has a filing date`);
    }
    if (ins && ins.overlap) {
      // Overlapping reports: the top 5 are real filings, the summed total
      // is not — total and public must both be null.
      check(ins.total_pct == null, `${symbol}: overlap ticker must have null insider total`);
      check(entry.public_pct == null, `${symbol}: overlap ticker must have null public pct`);
      check(typeof ins.overlap_note === 'string' && ins.overlap_note.length > 0,
        `${symbol}: overlap ticker must carry an overlap note`);
    }
    if (ins && ins.total_pct != null && shEntry && shEntry.institutions_pct != null) {
      const pub = 1 - shEntry.institutions_pct - ins.total_pct;
      check(Math.abs(pub - entry.public_pct) < 1e-9, `${symbol}: public pct mismatch`);
    }
  }
  check(tickers === 517, `expected 517 tickers, got ${tickers}`);
  console.log(`real data/top-holders.json: ${tickers} tickers checked`);
} else {
  console.log('data/top-holders.json not built yet — fixture checks only');
}

// --- Dropdown structure: Institutions / Insiders / Public each open like
// a dropdown over their top-5 list; the tables keep their ids so the
// loaders above still populate them.
const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
for (const id of ['holderGroupInstitutions', 'holderGroupInsiders', 'holderGroupPublic',
  'holderPctInstitutions', 'holderPctInsiders', 'holderPctPublic',
  'holderBodyInstitutions', 'holderBodyInsiders', 'holderBodyPublic',
  'topInstitutionsTable', 'topInsidersTable']) {
  check(html.includes(`id="${id}"`), `index.html must contain id="${id}"`);
}
check((html.match(/class="holder-group-head"/g) || []).length === 3, 'index.html must have exactly 3 holder-group-head buttons');
check(html.includes('profile.js?v=7'), 'index.html must load profile.js?v=7');
check(src.includes("'.holder-group-head'"), 'profile.js must wire the holder-group-head buttons');
check(src.includes("holder-group'") || src.includes('holder-group'), 'profile.js must toggle the holder-group open state');
check(src.includes('holderPctInstitutions') && src.includes('holderPctInsiders') && src.includes('holderPctPublic'),
  'profile.js must update the three dropdown header percentages');

console.log(`ALL CHECKS PASSED (${checks} checks)`);
