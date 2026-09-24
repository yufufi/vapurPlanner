// Ferry journey planner (RAPTOR-style). Works in browser (window.FerryPlanner) and Node (module.exports).
//
// DB shape (ferries.json):
//   stops: { name: {lat, lon} }
//   lines: [{ id, name, tour?, trips: [{ id, days:[...], stops:[{stop, t (min), est?: 'gtfs'|'timetable'|'distance', no_board?}], note? }] }]
//   walks: [{a, b, min}]
// Times are minutes after service-day midnight (may exceed 1440 for after-midnight runs).

(function (root) {
  const DAY = 1440;

  // ---- day types -------------------------------------------------------
  // Turkish public holidays in the timetable period (7 Sep 2026 – 27 Jun 2027), per the official 2027 calendar:
  // Ramazan Bayramı 9–11 Mar, Kurban Bayramı 16–19 May. Half-day eves (arife) keep the normal timetable.
  const HOLIDAYS = new Set([
    '2026-10-29', '2027-01-01', '2027-03-09', '2027-03-10', '2027-03-11', '2027-04-23', '2027-05-01',
    '2027-05-16', '2027-05-17', '2027-05-18', '2027-05-19',
  ]);

  function ymd(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  // Service tags active for a calendar date: base day type plus night-service tags.
  function dayTags(date) {
    const dow = date.getDay(); // 0 Sun .. 6 Sat
    const tags = new Set();
    if (HOLIDAYS.has(ymd(date)) || dow === 0) tags.add('sunday');
    else if (dow === 6) tags.add('saturday');
    else tags.add('weekday');
    if (dow === 5) tags.add('friday_night');
    if (dow === 6) tags.add('saturday_night');
    return tags;
  }

  function tagsFor(dayType) {
    // manual override: 'weekday' | 'saturday' | 'sunday' (+ optional friday/saturday night)
    return new Set(Array.isArray(dayType) ? dayType : [dayType]);
  }

  // ---- timetable expansion ----------------------------------------------
  // Build a flat list of trip instances over [day-1, day, day+1] so after-midnight trips of the
  // previous service day and early trips of the next day are all on one absolute-minute axis.
  function expand(db, date, opts) {
    const days = opts.dayTypeOverride
      ? [[-1, tagsFor(opts.dayTypeOverride)], [0, tagsFor(opts.dayTypeOverride)], [1, tagsFor(opts.dayTypeOverride)]]
      : [-1, 0, 1].map((o) => {
          const d = new Date(date.getFullYear(), date.getMonth(), date.getDate() + o);
          return [o, dayTags(d)];
        });
    const out = [];
    for (const line of db.lines) {
      if (line.tour && !opts.includeTours) continue;
      for (const trip of line.trips) {
        for (const [off, tags] of days) {
          if (!trip.days.some((d) => tags.has(d))) continue;
          const shift = off * DAY;
          const first = trip.stops[0].t + shift;
          if (first > DAY * 2 || trip.stops[trip.stops.length - 1].t + shift < -60) continue;
          out.push({ line, trip, shift });
        }
      }
    }
    return out;
  }

  // ---- RAPTOR ---------------------------------------------------------------
  // Labels: { t, prev } where prev = { kind:'ride', it, from, to, lbl } | { kind:'walk', min, lbl } | null (origin).
  // Round k holds earliest arrivals using exactly k boats (only kept when they beat every earlier round).
  function neighbours(walks, stop) {
    const out = [];
    for (const w of walks) {
      if (w.a === stop) out.push([w.b, w.min]);
      else if (w.b === stop) out.push([w.a, w.min]);
    }
    return out;
  }

  function raptor(inst, walks, origin, depMin, opts) {
    const maxRides = opts.maxRides || 4;
    const xfer = opts.transferMin ?? 3;
    const start = { t: depMin, prev: null };
    const round0 = new Map([[origin, start]]);
    if (opts.allowWalk) for (const [nb, m] of neighbours(walks, origin)) round0.set(nb, { t: depMin + m, prev: { kind: 'walk', min: m, lbl: start } });
    const rounds = [round0];
    const best = new Map([...round0].map(([s, l]) => [s, l.t]));
    let reach = round0; // labels usable for boarding in the next round
    for (let k = 1; k <= maxRides; k++) {
      const cur = new Map();
      for (const it of inst) {
        const s = it.trip.stops;
        let board = null;
        for (let i = 0; i < s.length; i++) {
          const t = s[i].t + it.shift;
          if (board && !s[i].no_alight && s[i].stop !== s[board.i].stop) {
            const b = best.get(s[i].stop);
            const ex = cur.get(s[i].stop);
            if ((b === undefined || t < b) && (!ex || t < ex.t)) {
              cur.set(s[i].stop, { t, prev: { kind: 'ride', it, from: board.i, to: i, lbl: board.lbl } });
            }
          }
          if (!board && i < s.length - 1 && !s[i].no_board) {
            const p = reach.get(s[i].stop);
            if (p) {
              const need = p.t + (p.prev && p.prev.kind === 'ride' ? xfer : 0);
              if (t >= need) board = { i, lbl: p };
            }
          }
        }
      }
      if (opts.allowWalk) {
        for (const [stop, lbl] of [...cur]) {
          if (lbl.prev.kind !== 'ride') continue;
          for (const [nb, m] of neighbours(walks, stop)) {
            const t = lbl.t + m;
            const b = best.get(nb);
            const ex = cur.get(nb);
            if ((b === undefined || t < b) && (!ex || t < ex.t)) cur.set(nb, { t, prev: { kind: 'walk', min: m, lbl } });
          }
        }
      }
      if (cur.size === 0) break;
      for (const [st, l] of cur) best.set(st, Math.min(best.get(st) ?? Infinity, l.t));
      rounds.push(cur);
      // next round may board from any stop reached so far (keep the earliest label per stop)
      const nextReach = new Map(reach);
      for (const [st, l] of cur) if (!nextReach.has(st) || l.t < nextReach.get(st).t) nextReach.set(st, l);
      reach = nextReach;
    }
    return rounds;
  }

  function reconstruct(lbl) {
    const legs = [];
    // walk the pointer chain backwards; stop names come from ride legs, walk legs get patched after
    for (let l = lbl; l && l.prev; l = l.prev.lbl) {
      const p = l.prev;
      if (p.kind === 'ride') {
        const s = p.it.trip.stops;
        legs.unshift({
          kind: 'ride', line: p.it.line, trip: p.it.trip,
          from: s[p.from].stop, to: s[p.to].stop,
          dep: s[p.from].t + p.it.shift, arr: s[p.to].t + p.it.shift,
          depEst: s[p.from].est || false, arrEst: s[p.to].est || false,
          via: s.slice(p.from + 1, p.to).map((x) => x.stop),
        });
      } else {
        legs.unshift({ kind: 'walk', dep: l.t - p.min, arr: l.t, min: p.min });
      }
    }
    return legs;
  }

  // Journey key for dedup
  const jkey = (legs) => legs.map((l) => (l.kind === 'ride' ? `${l.trip.id}:${l.from}>${l.to}` : `w:${l.from}>${l.to}`)).join('|');

  // Plan all Pareto-optimal journeys (later departure / earlier arrival / fewer boats) with a departure
  // inside [depMin, depMin + windowMin].
  function plan(db, origin, dest, date, depMin, opts = {}) {
    opts = { windowMin: 240, maxRides: 4, transferMin: 3, transferPenalty: 15, allowWalk: false, includeTours: false, ...opts };
    const inst = expand(db, date, opts);
    const walks = db.walks || [];
    // candidate departure times: every boat leaving origin (or a walk-neighbour) in the window
    const originSet = new Set([origin]);
    if (opts.allowWalk) for (const [nb] of neighbours(walks, origin)) originSet.add(nb);
    const cands = new Set();
    for (const it of inst) {
      for (const s of it.trip.stops) {
        if (!originSet.has(s.stop) || s.no_board) continue;
        const t = s.t + it.shift;
        const walk = s.stop === origin ? 0 : neighbours(walks, origin).find(([nb]) => nb === s.stop)[1];
        const leave = t - walk;
        if (leave >= depMin && leave <= depMin + opts.windowMin) cands.add(leave);
      }
    }
    const found = new Map();
    for (const t0 of [...cands].sort((a, b) => b - a)) {
      const rounds = raptor(inst, walks, origin, t0, opts);
      for (let k = 1; k < rounds.length; k++) {
        const lbl = rounds[k].get(dest);
        if (!lbl) continue;
        const legs = fillWalkNames(reconstruct(lbl), origin, dest);
        if (!legs.length || legs[0].dep < depMin) continue;
        const key = jkey(legs);
        if (!found.has(key)) found.set(key, legs);
      }
    }
    let js = [...found.values()].map(summarize);
    // Pareto filter: dominated if another departs no earlier, arrives no later, uses no more boats
    // Dominance with a transfer penalty: an extra boat must save at least `transferPenalty` minutes to be worth
    // listing (pure Pareto keeps silly 4-boat detours that beat a 2-boat trip by a few minutes).
    const pen = opts.transferPenalty;
    const dominates = (b, a) => b !== a && b.dep >= a.dep && b.arr + pen * (b.rides - a.rides) <= a.arr &&
      (b.dep > a.dep || b.arr < a.arr || b.rides < a.rides || jkey(b.legs) < jkey(a.legs));
    js = js.filter((a) => !js.some((b) => dominates(b, a)));
    js.sort((a, b) => a.arr - b.arr || a.rides - b.rides || b.dep - a.dep);
    return js;
  }

  function fillWalkNames(legs, origin, dest) {
    for (let i = 0; i < legs.length; i++) {
      if (legs[i].kind !== 'walk') continue;
      legs[i].from = i === 0 ? origin : legs[i - 1].to;
      legs[i].to = i === legs.length - 1 ? dest : legs[i + 1].from;
    }
    return legs;
  }

  function summarize(legs) {
    const rides = legs.filter((l) => l.kind === 'ride');
    const waits = [];
    for (let i = 1; i < legs.length; i++) waits.push(legs[i].dep - legs[i - 1].arr);
    return {
      legs,
      dep: legs[0].dep,
      arr: legs[legs.length - 1].arr,
      rides: rides.length,
      waits,
      totalWait: waits.reduce((a, b) => a + b, 0),
      onBoard: rides.reduce((a, l) => a + (l.arr - l.dep), 0),
      estimated: legs.some((l) => l.depEst || l.arrEst),
    };
  }

  function fmt(min) {
    const m = ((min % DAY) + DAY) % DAY;
    const s = `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
    if (min >= DAY) return s + ' (+1)';
    if (min < 0) return s + ' (-1)';
    return s;
  }

  const api = { plan, fmt, dayTags, HOLIDAYS };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.FerryPlanner = api;
})(typeof window !== 'undefined' ? window : globalThis);
