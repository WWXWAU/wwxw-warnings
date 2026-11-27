/* WWXW Plus on the website and in the app (Nov 2026).
   Sign-in: email + 6-digit code (the rainfall web app, Plus.gs). The token (1 year) stays in this browser/app.
   WWXWPlus.status(cb)   -> cb({signedIn, plus, email, plan, until, live})   (cached 10 minutes)
   WWXWPlus.code(email, cb) / WWXWPlus.verify(email, code, cb) / WWXWPlus.signOut()
   WWXWPlus.locked(cb)   -> cb(true) when Plus is switched on (app-config.json plusLock) and this person isn't a member
   In the app, every change is passed to the app itself (postMessage {wwxwPlus: {...}}). */
(function () {
  var API = 'https://script.google.com/macros/s/AKfycbyoxJApPxqA86gVVXen0USujHH7OAz3_nEwonfV-8j1G4pWAyKU7aIBRCRxsYZ5DcdJ/exec';
  var TK = 'wwxwPlusToken', ST = 'wwxwPlusStatus', subs = [];
  function get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function set(k, v) { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) {} }
  function post(body) {
    return fetch(API, { method: 'POST', headers: { 'Content-Type': 'text/plain;charset=utf-8' }, body: JSON.stringify(body) }).then(function (r) { return r.json(); });
  }
  function tell(s) {
    subs.forEach(function (f) { try { f(s); } catch (e) {} });
    try { if (window.parent !== window) window.parent.postMessage({ wwxwPlus: { plus: !!s.plus, signedIn: !!s.signedIn, email: s.email || '' } }, '*'); } catch (e) {}
  }
  function cached() { try { return JSON.parse(get(ST) || 'null'); } catch (e) { return null; } }
  var P = window.WWXWPlus = {
    token: function () { return get(TK); },
    onChange: function (f) { subs.push(f); },
    status: function (cb, fresh) {
      var t = get(TK), c = cached();
      if (!t) { var s0 = { signedIn: false, plus: false }; cb && cb(s0); return; }
      if (c && !fresh && Date.now() - c.at < 600000) { cb && cb(c); return; }
      if (c) cb && cb(c);   // show the last known state straight away, then check
      post({ plus: 'status', token: t }).then(function (r) {
        var s = r && r.ok ? { signedIn: true, plus: !!r.plus, email: r.email, plan: r.plan, until: r.until, at: Date.now(), live: true }
          : r && r.signedOut ? { signedIn: false, plus: false } : (c || { signedIn: true, plus: false });
        if (r && r.signedOut) { set(TK, null); set(ST, null); } else if (r && r.ok) set(ST, JSON.stringify(s));
        if (!c || c.plus !== s.plus || c.signedIn !== s.signedIn) tell(s);
        if (!c) cb && cb(s);
      }).catch(function () { if (!c) cb && cb({ signedIn: true, plus: false, offline: true }); });
    },
    code: function (email, cb) { post({ plus: 'code', email: email }).then(cb).catch(function () { cb({ ok: false, msg: 'Couldn\'t reach the server — check your connection and try again.' }); }); },
    verify: function (email, code, cb) {
      post({ plus: 'verify', email: email, code: code }).then(function (r) {
        if (r && r.ok) {
          set(TK, r.token);
          var s = { signedIn: true, plus: !!r.plus, email: r.email, plan: r.plan, until: r.until, at: Date.now(), live: true };
          set(ST, JSON.stringify(s)); tell(s);
        }
        cb(r);
      }).catch(function () { cb({ ok: false, msg: 'Couldn\'t reach the server — check your connection and try again.' }); });
    },
    signOut: function () { set(TK, null); set(ST, null); tell({ signedIn: false, plus: false }); },
    // Is Plus switched on yet (app-config.json), and is this person outside it?
    locked: function (cb) {
      fetch('/app-config.json?t=' + Math.floor(Date.now() / 300000)).then(function (r) { return r.json(); }).catch(function () { return {}; }).then(function (c) {
        if (!c || !c.plusLock) { cb(false); return; }
        P.status(function (s) { cb(!s.plus); });
      });
    }
  };
  // In the app: say who's signed in as soon as a page loads
  try { if (window.parent !== window) { var c0 = cached(); if (c0) tell(c0); } } catch (e) {}
})();
