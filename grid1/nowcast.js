// nowcast.js — West WX Watchers: the outlook, corrected through the day with what's actually happening (Nov 2026).
//
//   node grid1/nowcast.js <dir>
// <dir> holds raw_<MODEL>.json.gz (the 1° grid's model profiles, grid1-data branch), obs-live.json (Live Obs),
// sondes.json (this morning's weather balloons, grid1/sondes.py) and anom_hist.json (kept between runs).
//
// 1. Surface: every BoM and DPIRD station's temperature and dew point now, against each model's value for now
//    (in space and time). Each station's usual difference at this hour over the past week (its height, its siting,
//    the model's smoothing) is taken off, so only today's departure counts. Spread over the grid (about 120 km).
// 2. Aloft: each balloon's temperature (850, 700, 500 hPa) and dew point (850, 700) against each model at launch
//    time, spread over about 350 km.
// 3. The next 9 hours of model profiles get those differences (surface ones through the lowest 150 hPa, fading
//    over 12 hours), the instability is worked out again for the old and the new profile (a surface parcel), and
//    the difference is added to each model's own CAPE, CIN and LI. Then the outlook's index maths (indices.js) runs
//    on the corrected rows, so the nowcast is in exactly the outlook's own terms.
// Writes nowcast_1deg.json.gz (index rows like outlook_1deg.json.gz, for the next 9 hours), and anom_hist.json.
'use strict';
var fs = require('fs'), zlib = require('zlib'), path = require('path');
var IX = require('./indices.js');

var LV = [1000, 925, 850, 700, 500, 300, 250, 200];        // raw row: T at 3+i, Td at 11+i
var RD = 287.04, CP = 1005.7, LVH = 2.501e6, EPS = 0.622;
var HOURS_AHEAD = 9, SFC_R = 120, UP_R = 350;

function num(x) { var v = parseFloat(x); return isFinite(v) ? v : NaN; }
function tms(s) { return Date.parse(String(s).replace(' ', 'T') + ':00+08:00'); }
function km(a, b, c, d) { var r = Math.PI / 180, x = (d - b) * r * Math.cos((a + c) / 2 * r), y = (c - a) * r; return 6371 * Math.sqrt(x * x + y * y); }
function sat(t) { return 6.112 * Math.exp(17.67 * t / (t + 243.5)); }
function perthHour(ms) { return new Date(ms + 8 * 3600e3).getUTCHours(); }
function fmt(ms) { var d = new Date(ms + 8 * 3600e3); return d.toISOString().slice(0, 13).replace('T', ' ') + ':00'; }

// ---------------------------------------------------------------- a surface parcel: CAPE, CIN, LI
function moistLapse(p, TK) {
  var es = sat(TK - 273.15), ws = EPS * es / (p - es);
  return (1 / p) * (RD * TK + LVH * ws) / (CP + (LVH * LVH * ws * EPS) / (RD * TK * TK));
}
function moistTo(p0, TK, p1) {
  var p = p0;
  while (Math.abs(p1 - p) > 1e-6) { var h = Math.max(-10, p1 - p), k1 = moistLapse(p, TK), k2 = moistLapse(p + h, TK + k1 * h); TK += 0.5 * (k1 + k2) * h; p += h; }
  return TK;
}
function parcel(prof) {   // prof: [[p, T, Td]...] surface first, pressure falling
  var s = prof[0], T = s[1] + 273.15, Td = Math.min(s[2], s[1]) + 273.15;
  var TL = 1 / (1 / (Td - 56) + Math.log(T / Td) / 800) + 56, pL = s[0] * Math.pow(TL / T, 1 / 0.2854);
  function env(p) {
    for (var i = 0; i < prof.length - 1; i++) if (prof[i][0] >= p && p >= prof[i + 1][0]) {
      var w = Math.log(prof[i][0] / p) / Math.log(prof[i][0] / prof[i + 1][0]); return prof[i][1] + w * (prof[i + 1][1] - prof[i][1]) + 273.15;
    }
    return NaN;
  }
  var cape = 0, cin = 0, lfc = false, Tp = TL, pm = pL, top = prof[prof.length - 1][0], li = NaN;
  for (var p = s[0] - 10; p >= Math.max(top, 200); p -= 10) {
    var tp = p >= pL ? T * Math.pow(p / s[0], 0.2854) : (Tp = moistTo(pm, Tp, p), pm = p, Tp);
    var te = env(p); if (!isFinite(te)) break;
    var b = RD * (tp - te) * Math.log((p + 10) / p);
    if (tp > te && p < pL) { lfc = true; cape += b; } else if (!lfc) cin += Math.min(0, b);
    if (p <= 500 && !isFinite(li)) li = te - tp;
  }
  return { cape: cape, cin: lfc ? cin : 0, li: li };   // no free convection: no CIN to speak of
}

// ---------------------------------------------------------------- model values in space and time
function Model(name, d) {
  this.name = name; this.run = d.run; this.rows = d.rows; this.at = {}; var A = this.at;
  d.rows.forEach(function (r) { var k = r[0] + '|' + r[1]; (A[k] = A[k] || []).push(r); });
  Object.keys(A).forEach(function (k) { A[k].sort(function (a, b) { return tms(a[2]) - tms(b[2]); }); });
}
Model.prototype.sfc = function (r, which) {   // surface T or Td (1000 hPa when the model has no surface fields)
  var v = num(r[which === 'T' ? 45 : 46]); return isFinite(v) ? v : num(r[which === 'T' ? 3 : 11]);
};
Model.prototype.pointAt = function (lat, lng, ms, f) {   // f(row) at a grid point, linear in time; NaN if > 3 h outside
  var L = this.at[lat + '|' + lng]; if (!L) return NaN;
  for (var i = 0; i < L.length; i++) {
    var t = tms(L[i][2]);
    if (t >= ms) {
      if (i === 0) return t - ms <= 3 * 3600e3 ? f(L[0]) : NaN;
      var t0 = tms(L[i - 1][2]), w = (ms - t0) / (t - t0), a = f(L[i - 1]), b = f(L[i]);
      return a + w * (b - a);
    }
  }
  return ms - tms(L[L.length - 1][2]) <= 3 * 3600e3 ? f(L[L.length - 1]) : NaN;
};
Model.prototype.value = function (lat, lng, ms, f) {   // bilinear on the 1° grid
  var la0 = Math.floor(lat), ln0 = Math.floor(lng), s = 0, w = 0, self = this;
  [[la0, ln0], [la0 + 1, ln0], [la0, ln0 + 1], [la0 + 1, ln0 + 1]].forEach(function (g) {
    var k = (1 - Math.abs(lat - g[0])) * (1 - Math.abs(lng - g[1])), v = self.pointAt(g[0], g[1], ms, f);
    if (k > 0 && isFinite(v)) { s += v * k; w += k; }
  });
  return w > 0.3 ? s / w : NaN;
};

function spread(pts, lat, lng, R, shrink, key) {   // Gaussian-weighted average of point differences, pulled to 0 where few
  var s = 0, w = 0;
  pts.forEach(function (p) { var d = km(lat, lng, p.lat, p.lng); if (d > 2.2 * R || !isFinite(p[key])) return; var k = Math.exp(-(d / R) * (d / R)); s += p[key] * k; w += k; });
  return w > 0 ? s / (w + shrink) : 0;
}

function main() {
  var dir = process.argv[2] || 'nc', now = process.env.NOW ? +process.env.NOW : Date.now();
  now = Math.floor(now / 3600e3) * 3600e3;
  var models = [];
  fs.readdirSync(dir).filter(function (f) { return /^raw_.*\.json\.gz$/.test(f); }).sort().forEach(function (f) {
    var d = JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(dir, f))).toString());
    models.push(new Model(d.model, d));
  });
  var obs = JSON.parse(fs.readFileSync(path.join(dir, 'obs-live.json'), 'utf8')).points || [];
  var sondes = {}; try { sondes = JSON.parse(fs.readFileSync(path.join(dir, 'sondes.json'), 'utf8')).st || {}; } catch (e) {}
  var hist = {}; try { hist = JSON.parse(fs.readFileSync(path.join(dir, 'anom_hist.json'), 'utf8')); } catch (e) {}
  var hh = String(perthHour(now));

  // 1. Surface differences, station by station (model average), less each station's usual difference at this hour
  var st = obs.filter(function (p) { return (p.source === 'BOM' || p.source === 'DPIRD') && isFinite(num(p.temp)) && isFinite(num(p.dew))
    && p.lat < -13 && p.lat > -36 && p.lng > 112 && p.lng < 130 && (!p.t || Math.abs(now - p.t) < 90 * 60e3); });
  var used = [];
  st.forEach(function (p) {
    var dT = [], dD = [];
    models.forEach(function (m) {
      var t = m.value(p.lat, p.lng, now, function (r) { return m.sfc(r, 'T'); }), d = m.value(p.lat, p.lng, now, function (r) { return m.sfc(r, 'D'); });
      if (isFinite(t) && isFinite(d)) { dT.push(num(p.temp) - t); dD.push(num(p.dew) - d); }
    });
    if (!dT.length) return;
    var aT = dT.reduce(function (a, b) { return a + b; }, 0) / dT.length, aD = dD.reduce(function (a, b) { return a + b; }, 0) / dD.length;
    var key = p.source + '|' + p.name, H = (hist[key] = hist[key] || {}), h = (H[hh] = H[hh] || []);
    var med = function (a) { var s = a.slice().sort(function (x, y) { return x - y; }); return s.length ? s[Math.floor(s.length / 2)] : 0; };
    var past = h.filter(function (x) { return x[0] < now - 6 * 3600e3; });   // earlier days only
    var bT = past.length >= 3 ? med(past.map(function (x) { return x[1]; })) : 0, bD = past.length >= 3 ? med(past.map(function (x) { return x[2]; })) : 0;
    var conf = past.length >= 3 ? 1 : 0.5;   // until a station's usual difference is known, half weight
    var seen = {}; for (var j = h.length - 1; j >= 0; j--) { if (h[j][0] === now || seen[h[j][0]]) h.splice(j, 1); else seen[h[j][0]] = 1; }   // one entry per hour: a re-run replaces it
    h.push([now, Math.round(aT * 10) / 10, Math.round(aD * 10) / 10]); while (h.length > 10) h.shift();
    used.push({ name: p.name, lat: p.lat, lng: p.lng, T: Math.max(-6, Math.min(6, (aT - bT) * conf)), D: Math.max(-8, Math.min(8, (aD - bD) * conf)), raw: [aT, aD] });
  });

  // 2. Balloons: difference from each model at launch time, averaged over the models that cover that time
  var up = [];
  Object.keys(sondes).forEach(function (sid) {
    var S = sondes[sid], t = Date.parse(S.utc); if (!(now - t < 15 * 3600e3)) return;
    var o = { name: S.name, lat: S.lat, lng: S.lng, flight: S.awst };
    [[850, 5, 13], [700, 6, 14], [500, 7, null]].forEach(function (L) {
      var ob = S.lv[String(L[0])] || [], aT = [], aD = [];
      models.forEach(function (m) {
        var mt = m.value(S.lat, S.lng, t, function (r) { return num(r[L[1]]); }), md = L[2] ? m.value(S.lat, S.lng, t, function (r) { return num(r[L[2]]); }) : NaN;
        if (isFinite(mt) && ob[0] !== null && ob[0] !== undefined) aT.push(ob[0] - mt);
        if (isFinite(md) && ob[1] !== null && ob[1] !== undefined) aD.push(ob[1] - md);
      });
      var avg = function (a) { return a.length ? a.reduce(function (x, y) { return x + y; }, 0) / a.length : NaN; };
      o['T' + L[0]] = Math.max(-5, Math.min(5, avg(aT))); if (L[2]) o['D' + L[0]] = Math.max(-12, Math.min(12, avg(aD)));
    });
    up.push(o);
  });

  // 3. Correct the next hours of every model's rows, work the instability out again, run the outlook's maths
  var out = [], changes = [], runs = {}, counts = {};
  models.forEach(function (m) {
    var sel = m.rows.filter(function (r) { var t = tms(r[2]); return t >= now - 2 * 3600e3 && t <= now + HOURS_AHEAD * 3600e3; });
    var adj = sel.map(function (r0) {
      var r = r0.slice(), lat = r[0], lng = r[1], hrs = (tms(r[2]) - now) / 3600e3;
      var ws = Math.max(0.4, Math.min(1, 1 - hrs / 12)), wu = 0.8;
      var dT = spread(used, lat, lng, SFC_R, 0.3, 'T') * ws, dD = spread(used, lat, lng, SFC_R, 0.3, 'D') * ws;
      var psfc = num(r[40]); if (!(psfc > 500)) psfc = 1000;
      var before = profileOf(r, m, psfc);
      if (isFinite(num(r[45]))) r[45] = +(num(r[45]) + dT).toFixed(1); else r[3] = +(num(r[3]) + dT).toFixed(1);
      if (isFinite(num(r[46]))) r[46] = +(num(r[46]) + dD).toFixed(1); else r[11] = +(num(r[11]) + dD).toFixed(1);
      LV.forEach(function (p, i) {
        if (p <= psfc && p > psfc - 150) { var f = (p - (psfc - 150)) / 150; r[3 + i] = +(num(r[3 + i]) + dT * f).toFixed(1); if (isFinite(num(r[11 + i]))) r[11 + i] = +(num(r[11 + i]) + dD * f).toFixed(1); }
      });
      [[53, 950], [54, 975]].forEach(function (c) { if (isFinite(num(r[c[0]])) && c[1] > psfc - 150) r[c[0]] = +(num(r[c[0]]) + dD * (c[1] - (psfc - 150)) / 150).toFixed(1); });
      if (up.length) {
        [[850, 5, 13], [700, 6, 14], [500, 7, null]].forEach(function (L) {
          var a = spread(up, lat, lng, UP_R, 0.5, 'T' + L[0]) * wu; if (isFinite(a)) r[L[1]] = +(num(r[L[1]]) + a).toFixed(1);
          if (L[2]) { var b = spread(up, lat, lng, UP_R, 0.5, 'D' + L[0]) * wu * 0.5;   // dew points aloft vary a lot in dry layers: half weight
            if (isFinite(b) && isFinite(num(r[L[2]]))) r[L[2]] = +(num(r[L[2]]) + b).toFixed(1); }
        });
      }
      for (var i = 0; i < LV.length; i++) if (isFinite(num(r[11 + i])) && num(r[11 + i]) > num(r[3 + i])) r[11 + i] = r[3 + i];
      if (isFinite(num(r[46])) && isFinite(num(r[45])) && r[46] > r[45]) r[46] = r[45];
      [[41, 5, 13], [42, 6, 14]].forEach(function (c) { if (isFinite(num(r[c[0]])) && isFinite(num(r[c[2]]))) r[c[0]] = Math.round(Math.min(100, 100 * sat(num(r[c[2]])) / sat(num(r[c[1]])))); });
      var after = profileOf(r, m, psfc), A = parcel(after), B = parcel(before);
      var dC = A.cape - B.cape;
      if (isFinite(num(r[35]))) r[35] = Math.max(0, Math.round(num(r[35]) + 0.8 * dC));
      if (isFinite(num(r[36]))) r[36] = Math.min(0, Math.round(num(r[36]) + (A.cin - B.cin)));
      if (isFinite(num(r[37])) && isFinite(A.li) && isFinite(B.li)) r[37] = +(num(r[37]) + (A.li - B.li)).toFixed(1);
      if (Math.abs(dC) >= 300) changes.push({ m: m.name, lat: lat, lng: lng, t: r[2], from: Math.round(num(r0[35])), to: r[35], dT: +dT.toFixed(1), dD: +dD.toFixed(1) });
      return r;
    });
    var ix = IX.indicesForModel({ name: m.name }, adj);
    out = out.concat(ix); runs[m.name] = m.run; counts[m.name] = ix.length;
  });

  var mean = function (a, k) { var v = a.map(function (x) { return x[k]; }).filter(isFinite); return v.length ? +(v.reduce(function (x, y) { return x + y; }, 0) / v.length).toFixed(1) : null; };
  var res = { t: Date.now(), now: fmt(now), grid: '1deg', kind: 'nowcast', h: IX.IDX_H, runs: runs, counts: counts, rows: out,
    sfc: { n: used.length, T: mean(used, 'T'), D: mean(used, 'D'), pts: used.map(function (u) { return [u.name, u.lat, u.lng, +u.T.toFixed(1), +u.D.toFixed(1)]; }) },
    up: up.map(function (u) { var o = {}; Object.keys(u).forEach(function (k) { o[k] = typeof u[k] === 'number' ? +u[k].toFixed(1) : u[k]; }); return o; }),
    changes: changes.sort(function (a, b) { return Math.abs(b.to - b.from) - Math.abs(a.to - a.from); }).slice(0, 40) };
  fs.writeFileSync(path.join(dir, 'nowcast_1deg.json.gz'), zlib.gzipSync(Buffer.from(JSON.stringify(res))));
  var hk = Object.keys(hist); hk.forEach(function (k) { Object.keys(hist[k]).forEach(function (h) { hist[k][h] = hist[k][h].filter(function (x) { return x[0] > now - 10 * 864e5; }); }); });
  fs.writeFileSync(path.join(dir, 'anom_hist.json'), JSON.stringify(hist));
  console.log('Nowcast for ' + fmt(now) + ': ' + used.length + ' stations (mean ' + res.sfc.T + '° temp, ' + res.sfc.D + '° dew point against the models, usual differences taken off), '
    + up.length + ' balloons, ' + out.length + ' index rows, ' + changes.length + ' big CAPE changes.');
  res.up.forEach(function (u) { console.log('  ' + u.name + ' (' + u.flight + '): 850 hPa ' + u.T850 + '° temp, ' + u.D850 + '° dew; 700 hPa ' + u.T700 + '°, ' + u.D700 + '° dew; 500 hPa ' + u.T500 + '°'); });
  changes.slice(0, 8).forEach(function (c) { console.log('  ' + c.m + ' ' + c.lat + ',' + c.lng + ' ' + c.t + ': CAPE ' + c.from + ' -> ' + c.to + ' (surface ' + c.dT + '°, dew ' + c.dD + '°)'); });
}

function profileOf(r, m, psfc) {
  var Ts = m.sfc(r, 'T'), Ds = m.sfc(r, 'D'), P = [[psfc, Ts, isFinite(Ds) ? Ds : Ts - 10]];
  LV.forEach(function (p, i) { if (p < psfc - 5 && isFinite(num(r[3 + i]))) P.push([p, num(r[3 + i]), isFinite(num(r[11 + i])) ? num(r[11 + i]) : num(r[3 + i]) - 20]); });
  return P;
}

if (require.main === module) main();
module.exports = { parcel: parcel };
