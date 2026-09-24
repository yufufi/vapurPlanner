#!/usr/bin/env node
// usage: node scripts/plan_cli.js "Arnavutköy" "Üsküdar" [YYYY-MM-DD] [HH:MM] [--window 240] [--walk] [--xfer 3] [--no-private]
const P = require('../site/planner.js');
const db = require('../site/ferries.json');
const args = process.argv.slice(2);
const flag = (n, d) => { const i = args.indexOf(n); return i < 0 ? d : (args.splice(i, 2)[1]); };
const walk = args.includes('--walk'); if (walk) args.splice(args.indexOf('--walk'), 1);
const noPrivate = args.includes('--no-private'); if (noPrivate) args.splice(args.indexOf('--no-private'), 1);
const windowMin = +flag('--window', 240), transferMin = +flag('--xfer', 3);
const [from, to, dateS, timeS] = args;
const norm = (s) => s.toLocaleLowerCase('tr').normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/ı/g, 'i');
const find = (q) => Object.keys(db.stops).find((s) => norm(s) === norm(q)) || Object.keys(db.stops).find((s) => norm(s).startsWith(norm(q)));
const A = find(from), B = find(to);
if (!A || !B) { console.error('Unknown stop. Stops:', Object.keys(db.stops).join(', ')); process.exit(1); }
const now = new Date();
const date = dateS ? new Date(dateS + 'T00:00') : now;
const [h, m] = (timeS || `${now.getHours()}:${now.getMinutes()}`).split(':').map(Number);
const js = P.plan(db, A, B, date, h * 60 + m, { windowMin, transferMin, allowWalk: walk, includePrivate: !noPrivate });
console.log(`${A} → ${B}  ${date.toDateString()} from ${timeS || 'now'} (${[...P.dayTags(date)].join(',')})\n`);
if (!js.length) console.log('No journeys found in window.');
for (const j of js) {
  console.log(`${P.fmt(j.dep)} → ${P.fmt(j.arr)}  ${j.arr - j.dep} min, ${j.rides} boat(s), wait ${j.totalWait} min${j.estimated ? '  (~ arrival estimated)' : ''}`);
  j.legs.forEach((l, i) => {
    if (i > 0 && j.waits[i - 1] > 0) console.log(`      wait ${j.waits[i - 1]} min at ${l.from}`);
    if (l.kind === 'walk') console.log(`   🚶 ${P.fmt(l.dep)} walk ${l.from} → ${l.to} (${l.min} min)`);
    else console.log(`   ⛴  ${P.fmt(l.dep)}${l.depEst ? '~' : ''} ${l.from} → ${P.fmt(l.arr)}${l.arrEst ? '~' : ''} ${l.to}   [${l.line.operator ? l.line.operator + ': ' : ''}${l.line.name}]${l.trip.note ? '  ' + l.trip.note : ''}`);
  });
  console.log();
}
