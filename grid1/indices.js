// indices.js — West WX Watchers: the outlook's index calculation, run on GitHub for the 1° grid.

// GENERATED from Code.gs, Lift.gs and WebApp.gs (calculateIndices and its helpers). Do not edit by hand:

// when Code.gs or Lift.gs index maths changes, regenerate this file so both grids use the same rules.

'use strict';

var fs = require('fs'), zlib = require('zlib'), path = require('path');

var RD_ = 287.04, CP_ = 1005.7, LV_ = 2.501e6, EPS_ = 0.622, G_ = 9.81;

var PLEVELS = [1000, 925, 850, 700, 500, 300, 250, 200];

var OMEGA700_UNITS = 'ms';   // the raw rows hold upward vertical velocity in m/s, as Open-Meteo does

var _wwDtCache = {};

function num_(x) { var v = parseFloat(x); return isFinite(v) ? v : NaN; }

function satVap_(tC) { return 6.112 * Math.exp(17.67 * tC / (tC + 243.5)); }

function dewFromVap_(e) { var l = Math.log(e / 6.112); return 243.5 * l / (17.67 - l); }

function vapAt_(T, Td, RH) {
  if (isFinite(T) && RH > 0) return Math.min(RH, 100) / 100 * satVap_(T);
  if (isFinite(Td)) return satVap_(Td);
  return NaN;
}

function thetaE_(p, T, e) {
  var TK = T + 273.15, TdK = dewFromVap_(e) + 273.15, w = EPS_ * e / (p - e);
  var TL = 1 / (1 / (TdK - 56) + Math.log(TK / TdK) / 800) + 56;
  return TK * Math.pow(1000 / p, 0.2854 * (1 - 0.28 * w)) * Math.exp((3.376 / TL - 0.00254) * 1000 * w * (1 + 0.81 * w));
}

function moistLapse_(p, TK) {
  var es = satVap_(TK - 273.15), ws = EPS_ * es / (p - es);
  return (1 / p) * (RD_ * TK + LV_ * ws) / (CP_ + (LV_ * LV_ * ws * EPS_) / (RD_ * TK * TK));
}

function moistMove_(p0, TK, p1) {
  var p = p0;
  while (Math.abs(p1 - p) > 1e-6) {
    var h = p1 > p ? Math.min(5, p1 - p) : Math.max(-5, p1 - p);
    var k1 = moistLapse_(p, TK), k2 = moistLapse_(p + h, TK + k1 * h);
    TK += 0.5 * (k1 + k2) * h; p += h;
  }
  return TK;
}

function wetBulbK_(p, T, e) {
  var TK = T + 273.15, TdK = dewFromVap_(e) + 273.15;
  var TL = 1 / (1 / (TdK - 56) + Math.log(TK / TdK) / 800) + 56;
  return moistMove_(p * Math.pow(TL / TK, 1 / 0.2854), TL, p);
}

function calcLI_(pts, t500) {
  var s = pts && pts[0];
  if (!s || !isFinite(s.T) || !(s.e > 0) || !isFinite(t500)) return NaN;
  var TK = s.T + 273.15, TdK = Math.min(dewFromVap_(s.e), s.T) + 273.15;
  var TL = 1 / (1 / (TdK - 56) + Math.log(TK / TdK) / 800) + 56;
  var pL = s.p * Math.pow(TL / TK, 1 / 0.2854);
  var Tp = pL > 500 ? moistMove_(pL, TL, 500) : TK * Math.pow(500 / s.p, 0.2854);
  return t500 - (Tp - 273.15);
}

function calcMLLCL_(pts) {
  var s = pts && pts[0];
  if (!s || !isFinite(s.T) || !(s.e > 0)) return NaN;
  var top = s.p - 100, sumTh = 0, sumW = 0, sumDp = 0;
  var th = function (p, T) { return (T + 273.15) * Math.pow(1000 / p, 0.2854); };
  var w = function (p, e) { return EPS_ * e / (p - e); };
  for (var i = 0; i < pts.length - 1; i++) {
    var a = pts[i], b = pts[i + 1];
    if (!isFinite(a.T) || !isFinite(b.T) || !(a.e > 0) || !(b.e > 0) || a.p <= top) break;
    if (b.p < top) {   // stop at the top of the layer
      var f = (a.p - top) / (a.p - b.p);
      b = { p: top, T: a.T + f * (b.T - a.T), e: a.e + f * (b.e - a.e) };
    }
    var dp = a.p - b.p;
    sumTh += 0.5 * (th(a.p, a.T) + th(b.p, b.T)) * dp;
    sumW += 0.5 * (w(a.p, a.e) + w(b.p, b.e)) * dp;
    sumDp += dp;
  }
  var thM, wM;
  if (sumDp > 0) { thM = sumTh / sumDp; wM = sumW / sumDp; } else { thM = th(s.p, s.T); wM = w(s.p, s.e); }
  var TK = thM * Math.pow(s.p / 1000, 0.2854);                    // parcel temperature at the surface
  var e0 = wM * s.p / (EPS_ + wM);
  var TdK = Math.min(dewFromVap_(e0) + 273.15, TK);
  var TL = 1 / (1 / (TdK - 56) + Math.log(TK / TdK) / 800) + 56;  // Bolton (1980) LCL temperature
  var pL = s.p * Math.pow(TL / TK, 1 / 0.2854);
  return Math.max(0, RD_ * ((TK + TL) / 2) / G_ * Math.log(s.p / pL));
}

function freezingLevel_(pts) {
  var z = 0;
  for (var i = 0; i < pts.length - 1; i++) {
    var a = pts[i], b = pts[i + 1];
    if (!isFinite(a.T) || !isFinite(b.T)) continue;
    if (i === 0 && a.T <= 0) return 0;
    var dz = RD_ * ((a.T + b.T) / 2 + 273.15) / G_ * Math.log(a.p / b.p);
    if (a.T > 0 && b.T <= 0) return Math.round(z + dz * a.T / (a.T - b.T));
    z += dz;
  }
  return NaN;
}

function buildProfile_(psfc, lv) {
  var pts = [{p: psfc, T: lv.sfc.T, e: vapAt_(lv.sfc.T, lv.sfc.Td, NaN)}];
  lv.levels.forEach(function(L) {
    if (L.p < psfc - 5 && isFinite(L.T)) pts.push({p: L.p, T: L.T, e: vapAt_(L.T, L.Td, L.RH)});
  });
  return pts;
}

function precipWater_(pts) {
  var s = 0, n = 0;
  for (var i = 0; i < pts.length - 1; i++) {
    var a = pts[i], b = pts[i + 1];
    if (!isFinite(a.e) || !isFinite(b.e)) continue;
    var qa = EPS_ * a.e / (a.p - 0.378 * a.e), qb = EPS_ * b.e / (b.p - 0.378 * b.e);
    s += 0.5 * (qa + qb) * (a.p - b.p); n++;
  }
  return n >= 3 ? s * 100 / G_ : NaN;
}

function envTAt_(pts, p) {
  for (var i = 0; i < pts.length - 1; i++) {
    if (p <= pts[i].p && p >= pts[i + 1].p) {
      var f = Math.log(pts[i].p / p) / Math.log(pts[i].p / pts[i + 1].p);
      return pts[i].T + f * (pts[i + 1].T - pts[i].T);
    }
  }
  return NaN;
}

function calcDCAPE_(pts) {
  var psfc = pts[0].p, src = null;
  pts.forEach(function(q) {
    if (q.p < psfc - 50 && q.p >= psfc - 400 && isFinite(q.e) && isFinite(q.T)) {
      var te = thetaE_(q.p, q.T, q.e);
      if (!src || te < src.te) src = {p: q.p, T: q.T, e: q.e, te: te};
    }
  });
  if (!src) return NaN;
  var TK = wetBulbK_(src.p, src.T, src.e), p = src.p, dc = 0;
  while (p < psfc - 1e-6) {
    var h = Math.min(10, psfc - p), T0 = TK;
    var k1 = moistLapse_(p, TK), k2 = moistLapse_(p + h, TK + k1 * h);
    TK += 0.5 * (k1 + k2) * h;
    var diff = 0.5 * ((envTAt_(pts, p) + 273.15 - T0) + (envTAt_(pts, p + h) + 273.15 - TK));
    if (isFinite(diff) && diff > 0) dc += RD_ * diff * Math.log((p + h) / p);
    p += h;
  }
  return dc;
}

function calcSHIP_(cape, muMixrGkg, lapse, t500, shearKmh, fzl) {
  if (!(cape > 0) || !isFinite(lapse) || !isFinite(t500)) return 0;
  var mr = Math.max(11, Math.min(13.6, muMixrGkg || 11));
  var sh = Math.max(7, Math.min(27, shearKmh / 3.6));
  var t5 = Math.min(t500, -5.5);
  var s = cape * mr * lapse * (-t5) * sh / 42000000;
  if (cape < 1300) s *= cape / 1300;
  if (lapse < 5.8) s *= lapse / 5.8;
  if (fzl > 0 && fzl < 2400) s *= fzl / 2400;
  return Math.max(0, s);
}

function toUV(spd, dir) {
  var rad=(dir||0)*Math.PI/180;
  return {u:-(spd||0)*Math.sin(rad), v:-(spd||0)*Math.cos(rad)};
}

function calcSRH(levels, su, sv) {
  var srh=0;
  for (var i=0;i<levels.length-1;i++) {
    srh+=(levels[i].u-su)*(levels[i+1].v-sv)-(levels[i].v-sv)*(levels[i+1].u-su);
  }
  return -srh;
}

function fx_(v, d) { return isFinite(v) ? v.toFixed(d) : ''; }

function gridWinds_(data) {
  var out = {};
  data.forEach(function (r) {
    var k = Number(r[0]) + ',' + Number(r[1]) + '|' + fmtDateTime(r[2]);
    var s8 = num_(r[21]), d8 = num_(r[29]), ss = num_(r[47]), ds = num_(r[48]);
    if (!isFinite(ss) || !isFinite(ds)) { ss = num_(r[20]); ds = num_(r[28]); }   // no 10 m wind: 925 hPa
    var a = isFinite(s8) && isFinite(d8) ? toUV(s8, d8) : null, b = isFinite(ss) && isFinite(ds) ? toUV(ss, ds) : null;
    out[k] = { u8: a ? a.u : NaN, v8: a ? a.v : NaN, us: b ? b.u : NaN, vs: b ? b.v : NaN };
  });
  return out;
}

function convAt_(windAt, lat, lng, dt, f) {
  var U = 'u' + f, V = 'v' + f;
  var g = function (la, lo) { var w = windAt[la + ',' + lo + '|' + dt]; return w && isFinite(w[U]) && isFinite(w[V]) ? w : null; };
  var C = g(lat, lng);
  if (!C) return NaN;
  var E = g(lat, lng + 2), W = g(lat, lng - 2), N = g(lat + 2, lng), S = g(lat - 2, lng);
  var dx = 2 * 111200 * Math.cos(lat * Math.PI / 180), dy = 2 * 111200;
  var diff = function (A, B, key, step) {
    return A && B ? (A[key] - B[key]) / (2 * step) : A ? (A[key] - C[key]) / step : B ? (C[key] - B[key]) / step : NaN;
  };
  var dudx = diff(E, W, U, dx), dvdy = diff(N, S, V, dy);
  if (!isFinite(dudx) || !isFinite(dvdy)) return NaN;
  var div = (dudx + dvdy - C[V] * Math.tan(lat * Math.PI / 180) / 6371000) / 3.6;   // km/h -> m/s, per second
  return -div * 1e5;
}

function ascent700_(raw, t700) {
  if (!isFinite(raw)) return NaN;
  if (OMEGA700_UNITS === 'ms') return raw * 100;
  if (OMEGA700_UNITS === 'pas') {
    var rho = 70000 / (RD_ * (t700 + 273.15));
    return -raw / (rho * G_) * 100;
  }
  return NaN;
}

function calcConvTemp_(pts) {
  var s = pts && pts[0];
  if (!s || !isFinite(s.T) || !(s.e > 0)) return NaN;
  var w = function (p, e) { return EPS_ * e / (p - e); };
  var ws = function (p, T) { var es = satVap_(T); return EPS_ * es / (p - es); };
  var top = s.p - 100, sumW = 0, sumDp = 0, i;
  for (i = 0; i < pts.length - 1; i++) {
    var a = pts[i], b = pts[i + 1];
    if (!(a.e > 0) || !(b.e > 0) || a.p <= top) break;
    if (b.p < top) { var f = (a.p - top) / (a.p - b.p); b = { p: top, e: a.e + f * (b.e - a.e) }; }
    var dp = a.p - b.p;
    sumW += 0.5 * (w(a.p, a.e) + w(b.p, b.e)) * dp; sumDp += dp;
  }
  var wM = sumDp > 0 ? sumW / sumDp : w(s.p, s.e), prev = null;
  for (i = 0; i < pts.length; i++) {
    var q = pts[i];
    if (!isFinite(q.T)) continue;
    var d = ws(q.p, q.T) - wM, pc, tc;
    if (d <= 0) {
      if (!prev) { pc = q.p; tc = q.T; }
      else {
        var f2 = prev.d / (prev.d - d);
        pc = Math.exp(Math.log(prev.p) + f2 * (Math.log(q.p) - Math.log(prev.p)));
        tc = prev.T + f2 * (q.T - prev.T);
      }
      if (pc < 500) return NaN;
      return (tc + 273.15) * Math.pow(s.p / pc, 0.2854) - 273.15;
    }
    prev = { p: q.p, T: q.T, d: d };
  }
  return NaN;
}

function fmtDateTime(dt) {
  var key = dt instanceof Date ? 'd' + dt.getTime() : 's' + String(dt);
  if (_wwDtCache[key]) return _wwDtCache[key];
  var out = dt instanceof Date
    ? dt.toISOString().substring(0, 16).replace('T', ' ')
    : String(dt).replace('T', ' ').substring(0, 16);
  _wwDtCache[key] = out;
  return out;
}

var IDX_H = ['model','lat','lng','datetime',
    'CAPE','ML_CAPE','SFC_CAPE','CIN','DCAPE','LI','K_INDEX',
    'TOTAL_TOTALS','CROSS_TOTALS','VERT_TOTALS','SWEAT',
    'PRECIPWATER','WBZ_HEIGHT','LAPSE_700_500','LAPSE_03KM',
    'BULK_SHEAR_06','BULK_SHEAR_01','SRH_1KM','SRH_3KM',
    'STORM_U','STORM_V','STP','SHIP','BRN_SHEAR','SCP',
    'T_SFC','TD_SFC','T925','T850','T700','T500',
    'TD925','TD850','TD700','TD500','TD950','TD975',
    'RH_SFC','RH850','RH700','RH500','RH300','RH800',
    'GUST','PRECIP','MSLP',
    'WS300','WS200','WD300','WD200',
    'BLH','FREEZE_LVL','OMEGA700','GEOPOT500',
    'CAP_STRENGTH','MID_DRY_IDX','POTENTIAL_INST',
    'WS850','WS700','STEER_U','STEER_V','LCL',
    'CONV850','CONV_SFC','ASCENT700','TCONV'
  ];

// One model's raw rows (the model-sheet layout, rawHeaders_ in Code.gs) -> index rows (IDX_H)
function indicesForModel(model, data) {
  var allRows = [];
  data = data.filter(function (r) { return isFinite(num_(r[5])); });   // rows with pressure-level data only
  var windAt = gridWinds_(data);
  data.forEach(function(r) {
      // Full forecast time 'yyyy-MM-dd HH:mm' AWST (fmtDateTime is in WebApp.gs)
      var lat=r[0],lng=r[1],dt=fmtDateTime(r[2]);
      var T925=parseFloat(r[4])||0,  T850=parseFloat(r[5])||0;
      var T700=parseFloat(r[6])||0,  T500=parseFloat(r[7])||0;
      var Td925=parseFloat(r[12])||0, Td850=parseFloat(r[13])||0;
      var Td700=parseFloat(r[14])||0, Td500=parseFloat(r[15])||0;
      var WS925=parseFloat(r[20])||0, WS850=parseFloat(r[21])||0;
      var WS700=parseFloat(r[22])||0, WS500=parseFloat(r[23])||0;
      var WS300=parseFloat(r[24])||0, WS200=parseFloat(r[26])||0;
      var WD925=parseFloat(r[28])||0, WD850=parseFloat(r[29])||0;
      var WD700=parseFloat(r[30])||0, WD500=parseFloat(r[31])||0;
      var WD300=parseFloat(r[32])||0, WD200=parseFloat(r[34])||0;
      var CAPE=parseFloat(r[35])||0,  CIN=parseFloat(r[36])||0;
      var LI=parseFloat(r[37])||0,    GUST=parseFloat(r[38])||0;
      var PRECIP=parseFloat(r[39])||0, MSLP=parseFloat(r[40])||0;
      var RH850=parseFloat(r[41])||0, RH700=parseFloat(r[42])||0;
      var RH500=parseFloat(r[43])||0, RH300=parseFloat(r[44])||0;
      var T_SFC=parseFloat(r[45])||0, Td_SFC=parseFloat(r[46])||0;
      var WS_SFC=parseFloat(r[47])||0, WD_SFC=parseFloat(r[48])||0;
      var BLH=parseFloat(r[49])||0,   FREEZE_LVL=parseFloat(r[50])||0;
      var OMEGA700=parseFloat(r[51])||0, GEOPOT500=parseFloat(r[52])||0;
      var Td950=parseFloat(r[53])||0, Td975=parseFloat(r[54])||0;
      var RH800=parseFloat(r[55])||0;

      // Models without surface fields (AIFS): use the 1000 hPa values instead
      // of treating the missing surface temperature/dewpoint/wind as zero.
      var tS = num_(r[45]), tdS = num_(r[46]);
      if (!isFinite(tS)) tS = num_(r[3]);
      if (!isFinite(tdS)) {
        var e1000 = vapAt_(num_(r[3]), num_(r[11]), num_(r[56]));
        if (isFinite(e1000)) tdS = dewFromVap_(e1000);
      }
      if (isFinite(tS))  T_SFC = tS;
      if (isFinite(tdS)) Td_SFC = tdS;
      if (!isFinite(num_(r[47])) && isFinite(num_(r[19]))) {
        WS_SFC = num_(r[19]); WD_SFC = parseFloat(r[27])||0;
      }

      var psfc=num_(r[40]); if(!(psfc>500)) psfc=1000;
      var prof = buildProfile_(psfc, {
        sfc: {T: tS, Td: tdS},
        levels: [
          {p:1000, T:num_(r[3]), Td:num_(r[11]), RH:num_(r[56])},
          {p:925,  T:num_(r[4]), Td:num_(r[12]), RH:num_(r[57])},
          {p:850,  T:num_(r[5]), Td:num_(r[13]), RH:num_(r[41])},
          {p:700,  T:num_(r[6]), Td:num_(r[14]), RH:num_(r[42])},
          {p:500,  T:num_(r[7]), Td:num_(r[15]), RH:num_(r[43])},
          {p:300,  T:num_(r[8]), Td:num_(r[16]), RH:num_(r[44])}
        ]
      });
      var TCWV=num_(r[58]);

      // Derive dewpoint from RH when not provided (AIFS)
      // Magnus approximation: Td ≈ T - ((100 - RH) / 5)
      if (!Td850 && RH850>0 && T850!==0) Td850 = T850 - ((100-RH850)/5);
      if (!Td700 && RH700>0 && T700!==0) Td700 = T700 - ((100-RH700)/5);
      if (!Td925 && RH850>0 && T925!==0) Td925 = T925 - ((100-RH850)/5);
      if (!Td500 && RH500>0 && T500!==0) Td500 = T500 - ((100-RH500)/5);

      var VERT_TOTALS  = T850 - T500;
      var CROSS_TOTALS = Td850 - T500;
      var TOTAL_TOTALS = VERT_TOTALS + CROSS_TOTALS;
      var K_INDEX = (T850-T500) + Td850 - (T700-Td700);
      var swTd850 = Math.max(Td850,0);
      var SWEAT = (12*swTd850) + (20*Math.max(TOTAL_TOTALS-49,0)) + (2*WS850) + WS500
        + (125*(Math.sin((WD500-WD850)*Math.PI/180)+0.2));
      // Precipitable water: the model's own total column water vapour where
      // provided, otherwise integrated from the humidity profile.
      var PRECIPWATER = TCWV > 0 ? TCWV : precipWater_(prof);
      if (!isFinite(PRECIPWATER)) {
        var PW_850 = Td850>-20 ? Math.max(0,Td850+20)*0.5 : 0;
        var PW_700 = Td700>-30 ? Math.max(0,Td700+30)*0.3 : 0;
        PRECIPWATER = Math.max(0, PW_850+PW_700+(RH850/100)*10+(RH700/100)*5);
      }
      // Lapse rates (°C/km) using the actual layer depth (hypsometric equation)
      // instead of assuming each layer is 3 km deep.
      var dz75 = RD_*((T700+T500)/2+273.15)/G_*Math.log(700/500);
      var LAPSE_700_500 = (T700-T500)/dz75*1000;
      var dzS7 = RD_*((T_SFC+T700)/2+273.15)/G_*Math.log(Math.max(psfc,701)/700);
      var LAPSE_03KM   = (T_SFC-T700)/dzS7*1000;
      var thetaE850 = T850 + 2500*Math.max(0,Td850/273) + 273;
      var thetaE500 = T500 + 2500*Math.max(0,Td500/273) + 273;
      var POTENTIAL_INST = thetaE850 - thetaE500;
      // Freezing level from the temperature profile where the model doesn't supply it
      if (!(FREEZE_LVL > 0)) { var fzl = freezingLevel_(prof); if (isFinite(fzl) && fzl > 0) FREEZE_LVL = fzl; }
      var WBZ_HEIGHT = FREEZE_LVL>0 ? FREEZE_LVL : 0;
      var LCL_ML = calcMLLCL_(prof);
      // Lift (Lift.gs): convergence at 850 hPa and near the surface, rising air at 700 hPa,
      // and the convective temperature (heating needed to break the cap without a trigger)
      var CONV850 = convAt_(windAt, Number(lat), Number(lng), dt, '8');
      var CONV_SFC = convAt_(windAt, Number(lat), Number(lng), dt, 's');
      var ASCENT700 = ascent700_(num_(r[51]), num_(r[6]));
      var TCONV = calcConvTemp_(prof);
      if (WBZ_HEIGHT===0&&T_SFC>0) {
        WBZ_HEIGHT = Math.max(0,Math.min(6000,Math.round(T_SFC/(T_SFC-Math.min(T700,0)+0.001)*3000)));
      }
      var ML_CAPE  = CAPE*0.8;
      var SFC_CAPE = CAPE*1.1;
      var DCAPE    = calcDCAPE_(prof);
      if (!isFinite(DCAPE)) DCAPE = 0;
      // Lifted index where the model doesn't supply it: proper parcel ascent (was dry-only)
      if (!LI && T500 !== 0) { var liCalc = calcLI_(prof, T500); LI = isFinite(liCalc) ? liCalc : 0; }
      var CAP_STRENGTH = T850-(T_SFC-9.8*1.5);
      var MID_DRY_IDX  = Math.max(0,Math.min(1,(1-(RH500+RH300)/200)));

      // Winds converted from km/h to m/s: storm motion, SRH, SCP and STP are
      // all defined in m/s (SRH in m²/s²).
      var KMH = 3.6;
      var sfc  = toUV(WS_SFC/KMH,WD_SFC), p925 = toUV(WS925/KMH,WD925);
      var p850 = toUV(WS850/KMH,WD850),   p700 = toUV(WS700/KMH,WD700);
      var p500 = toUV(WS500/KMH,WD500),   p200 = toUV(WS200/KMH,WD200);
      // General storm direction: the 500 hPa wind (km/h, components toward which it blows)
      var STEER_U = p500.u*KMH, STEER_V = p500.v*KMH;
      var BS06u = p500.u-sfc.u, BS06v = p500.v-sfc.v;
      var BS06_MS = Math.sqrt(BS06u*BS06u+BS06v*BS06v);
      var BULK_SHEAR_06 = BS06_MS*KMH;   // stored in km/h as before
      var BS01u = p925.u-sfc.u, BS01v = p925.v-sfc.v;
      var BULK_SHEAR_01 = Math.sqrt(BS01u*BS01u+BS01v*BS01v)*KMH;

      // Southern Hemisphere Bunkers left mover (the cyclonic supercell in the SH),
      // 7.5 m/s deviation from the mean wind.
      var mean_u = (sfc.u+p925.u+p850.u+p700.u+p500.u)/5;
      var mean_v = (sfc.v+p925.v+p850.v+p700.v+p500.v)/5;
      var shu = p500.u-sfc.u, shv = p500.v-sfc.v;
      var shm = Math.sqrt(shu*shu+shv*shv)||1;
      var su = mean_u-7.5*(shv/shm);
      var sv = mean_v+7.5*(shu/shm);
      var STORM_U = su*KMH, STORM_V = sv*KMH;   // stored in km/h
      // SRH in m²/s². Southern Hemisphere supercells have NEGATIVE helicity.
      var SRH_1KM = calcSRH([sfc,p925,p850],su,sv);
      var SRH_3KM = calcSRH([sfc,p925,p850,p700],su,sv);
      var BRN_SHEAR = 0.5*(BS06_MS*BS06_MS);   // m²/s²

      var lcl_m = Math.max(0,(T_SFC-Td_SFC)*125);
      var lcl_f = lcl_m<=1000?1:Math.max(0,(2000-lcl_m)/1000);
      var cin_f = CIN>=-50?1:Math.max(0,(200+CIN)/150);
      // Fixed-layer STP and SCP (SPC formulations). The SRH sign is flipped so
      // that Southern Hemisphere (negative) helicity counts as favourable.
      // STP shear term: 0 below 12.5 m/s, capped at 1.5 (30 m/s).
      var stpShear = BS06_MS<12.5 ? 0 : Math.min(BS06_MS,30)/20;
      var STP  = (CAPE/1500)*lcl_f*(Math.max(0,-SRH_1KM)/150)*stpShear*cin_f;
      // SHIP inputs: most-unstable mixing ratio (lowest levels) and the true
      // 700–500 hPa lapse rate using the hypsometric layer depth.
      var muMr = 0;
      prof.forEach(function(q){ if (q.p >= 800 && isFinite(q.e)) muMr = Math.max(muMr, 1000*EPS_*q.e/(q.p-q.e)); });
      var SHIP = calcSHIP_(CAPE, muMr, LAPSE_700_500, T500, BULK_SHEAR_06, FREEZE_LVL);
      // SCP shear term: 0 below 10 m/s, capped at 1.0 (20 m/s).
      var scpShear = BS06_MS<10 ? 0 : Math.min(BS06_MS,20)/20;
      var SCP  = (CAPE/1000)*(Math.max(0,-SRH_3KM)/50)*scpShear;
      // Surface relative humidity from vapour pressures (the old 100 − 5×(T−Td)
      // rule of thumb is badly wrong in dry air, e.g. 2% instead of 30%).
      var RH_SFC = (isFinite(tS) && isFinite(tdS))
        ? Math.round(Math.min(100, Math.max(0, 100 * satVap_(Td_SFC) / satVap_(T_SFC))))
        : '';

      allRows.push([
        model.name,lat,lng,dt,
        Math.round(CAPE),Math.round(ML_CAPE),Math.round(SFC_CAPE),
        Math.round(CIN),Math.round(DCAPE),
        LI.toFixed(1),K_INDEX.toFixed(1),
        TOTAL_TOTALS.toFixed(1),CROSS_TOTALS.toFixed(1),VERT_TOTALS.toFixed(1),
        Math.round(SWEAT),PRECIPWATER.toFixed(1),Math.round(WBZ_HEIGHT),
        LAPSE_700_500.toFixed(2),LAPSE_03KM.toFixed(2),
        Math.round(BULK_SHEAR_06),Math.round(BULK_SHEAR_01),
        Math.round(SRH_1KM),Math.round(SRH_3KM),
        STORM_U.toFixed(1),STORM_V.toFixed(1),
        STP.toFixed(2),SHIP.toFixed(2),Math.round(BRN_SHEAR),SCP.toFixed(2),
        T_SFC.toFixed(1),Td_SFC.toFixed(1),
        T925.toFixed(1),T850.toFixed(1),T700.toFixed(1),T500.toFixed(1),
        Td925.toFixed(1),Td850.toFixed(1),Td700.toFixed(1),Td500.toFixed(1),
        Td950.toFixed(1),Td975.toFixed(1),
        RH_SFC,Math.round(RH850),Math.round(RH700),Math.round(RH500),
        Math.round(RH300),Math.round(RH800),
        Math.round(GUST),PRECIP.toFixed(1),Math.round(MSLP),
        Math.round(WS300),Math.round(WS200),Math.round(WD300),Math.round(WD200),
        Math.round(BLH),Math.round(FREEZE_LVL),OMEGA700.toFixed(3),Math.round(GEOPOT500),
        CAP_STRENGTH.toFixed(1),MID_DRY_IDX.toFixed(2),POTENTIAL_INST.toFixed(1),
        Math.round(WS850),Math.round(WS700),STEER_U.toFixed(1),STEER_V.toFixed(1),isFinite(LCL_ML)?Math.round(LCL_ML):'',
        fx_(CONV850,2),fx_(CONV_SFC,2),fx_(ASCENT700,2),fx_(TCONV,1)
      ]);
    });
  return allRows;
}


// Run: node grid1/indices.js data/grid1  -> data/grid1/outlook_1deg.json.gz
function main() {
  var dir = process.argv[2] || 'data/grid1', rows = [], runs = {}, counts = {};
  fs.readdirSync(dir).filter(function (f) { return /^raw_.*\.json$/.test(f); }).sort().forEach(function (f) {
    var d = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
    var r = indicesForModel({ name: d.model }, d.rows);
    rows = rows.concat(r); runs[d.model] = d.run; counts[d.model] = r.length;
    console.log(d.model + ' (run ' + d.run + '): ' + d.rows.length + ' raw rows -> ' + r.length + ' index rows');
  });
  if (!rows.length) { console.log('No raw model files found: nothing written.'); process.exit(1); }
  var out = { t: Date.now(), grid: '1deg', runs: runs, counts: counts, h: IDX_H, rows: rows };
  var gz = zlib.gzipSync(Buffer.from(JSON.stringify(out)));
  fs.writeFileSync(path.join(dir, 'outlook_1deg.json.gz'), gz);
  console.log('Wrote outlook_1deg.json.gz: ' + rows.length + ' rows, ' + Math.round(gz.length / 1024) + ' KB.');
}
if (require.main === module) main();
module.exports = { indicesForModel: indicesForModel, IDX_H: IDX_H };
