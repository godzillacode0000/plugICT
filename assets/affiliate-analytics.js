/* Privacy-first referral click beacon for the static PlugICT pages.
   Configure window.PLUGICT_AFFILIATE_API only during approved activation.
   With an empty URL, this is intentionally inert. */
(function () {
  'use strict';

  var params = new URLSearchParams(window.location.search);
  var ref = (params.get('ref') || '').trim().toLowerCase();
  var cleanUrl = '';
  if (params.has('ref')) {
    params.delete('ref');
    var query = params.toString();
    cleanUrl = (window.location.pathname || '/')
      + (query ? '?' + query : '')
      + (window.location.hash || '');
  }
  function cleanReferralUrl() {
    if (!cleanUrl) return;
    try { window.history.replaceState(window.history.state, '', cleanUrl); } catch (_) {}
  }

  var api = (window.PLUGICT_AFFILIATE_API || '').replace(/\/$/, '');
  if (!api) {
    cleanReferralUrl();
    return;
  }

  /* A stored referral keeps checkout attribution alive, but must not create
     another analytics click on later visits. */
  if (!/^[a-z0-9_-]{1,64}$/.test(ref)) {
    cleanReferralUrl();
    return;
  }

  function persistentId(key) {
    try {
      var existing = localStorage.getItem(key);
      if (existing) return existing;
      var created = (window.crypto && crypto.randomUUID)
        ? crypto.randomUUID()
        : 'v_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
      localStorage.setItem(key, created);
      return created;
    } catch (_) {
      return 'ephemeral_' + Date.now().toString(36);
    }
  }

  var visitorId = persistentId('plugict_affiliate_visitor');
  var clickId = (window.crypto && crypto.randomUUID)
    ? crypto.randomUUID()
    : 'c_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
  var body = JSON.stringify({
    code: ref,
    click_id: clickId,
    visitor_id: visitorId,
    path: window.location.pathname || '/',
    referrer: document.referrer || ''
  });
  var endpoint = api + '/api/affiliate/click';

  try {
    fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain;charset=UTF-8' },
      body: body,
      keepalive: true,
      credentials: 'omit'
    }).catch(function () {});
  } catch (_) {}
  cleanReferralUrl();
}());
