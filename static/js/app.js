(function () {
  'use strict';

  /* ===================== Constants ===================== */
  // SLA day-offsets and statuses follow Lextria's own trademark-cycle chart
  // (search -> filing -> objection [30d reply] -> hearing -> accept & advertise
  // [4mo opposition window] -> registration, with a parallel opposition track
  // [2mo counter-statement]) so deadline suggestions match the real process.
  var STATUS_DEFS = [
    { key: 'filed', label: 'Filed', tier: 'neutral', type: 'trademark', suggestedAction: 'Await formalities check', slaDays: null },
    { key: 'formalities_pass', label: 'Formalities Chk Pass', tier: 'neutral', type: 'trademark', suggestedAction: 'Await examination', slaDays: null },
    { key: 'objected', label: 'Objected', tier: 'warning', type: 'trademark', suggestedAction: 'File response to Examination Report', slaDays: 30 },
    { key: 'response_filed', label: 'Response Filed', tier: 'info', type: 'trademark', suggestedAction: 'Awaiting hearing notice or acceptance', slaDays: null },
    { key: 'hearing_fixed', label: 'Hearing Fixed', tier: 'warning', type: 'trademark', suggestedAction: 'Prepare and attend hearing; file written submission promptly if directed', slaDays: null },
    { key: 'accepted_advertised', label: 'Accepted & Advertised', tier: 'info', type: 'trademark', suggestedAction: 'Monitor the opposition window (4 months from advertisement)', slaDays: 120 },
    { key: 'opposed', label: 'Opposed', tier: 'serious', type: 'trademark', suggestedAction: 'File counter-statement (TM-O)', slaDays: 60 },
    { key: 'registered', label: 'Registered', tier: 'good', type: 'trademark', suggestedAction: 'File renewal before expiry (10-year term)', slaDays: null, renewYears: 10 },
    { key: 'refused', label: 'Refused', tier: 'critical', type: 'trademark', suggestedAction: 'Decide: appeal or abandon', slaDays: null },
    { key: 'abandoned', label: 'Abandoned', tier: 'neutral', type: 'trademark', suggestedAction: '', slaDays: null },

    // Copyright pipeline — from Lextria's Copyright Information Document: Filing of Application ->
    // (30d office turnaround) -> Formality Check -> (30d mandatory waiting period) -> Reply to Formality
    // Check -> (ASAP) -> Examination -> (30d) -> Discrepancy -> (ASAP) -> Reply -> (1d) -> Hearing ->
    // (ASAP) -> Hearing submission -> Registration. Doc notes ~3-6 months average end to end.
    { key: 'cr_filed', label: 'Filed', tier: 'neutral', type: 'copyright', suggestedAction: 'Await formality check', slaDays: null },
    { key: 'cr_formality_check', label: 'Formality Check', tier: 'neutral', type: 'copyright', suggestedAction: 'Awaiting formality check outcome (approx. 30 days)', slaDays: 30 },
    { key: 'cr_formality_reply', label: 'Reply to Formality Check', tier: 'warning', type: 'copyright', suggestedAction: 'File reply to formality discrepancy; then a 30-day mandatory waiting period applies before examination', slaDays: 30 },
    { key: 'cr_examination', label: 'Examination', tier: 'info', type: 'copyright', suggestedAction: 'Awaiting examination outcome', slaDays: null },
    { key: 'cr_discrepancy', label: 'Discrepancy', tier: 'warning', type: 'copyright', suggestedAction: 'File reply to discrepancy', slaDays: 30 },
    { key: 'cr_reply_filed', label: 'Reply Filed', tier: 'info', type: 'copyright', suggestedAction: 'Awaiting hearing notice or registration', slaDays: null },
    { key: 'cr_hearing', label: 'Hearing Fixed', tier: 'warning', type: 'copyright', suggestedAction: 'Attend hearing; file hearing submission promptly (within 1 day)', slaDays: 1 },
    { key: 'cr_registered', label: 'Registered', tier: 'good', type: 'copyright', suggestedAction: 'Copyright registered — no renewal filing required (protection runs for the statutory term)', slaDays: null },
    { key: 'cr_refused', label: 'Refused', tier: 'critical', type: 'copyright', suggestedAction: 'Decide: appeal or abandon', slaDays: null },
    { key: 'cr_abandoned', label: 'Abandoned', tier: 'neutral', type: 'copyright', suggestedAction: '', slaDays: null },

    // Design pipeline — from Lextria's Design Patent Information Document: Design Application Filing ->
    // (ASAP) -> Issuing of FER -> (max 6 months) -> Filing FER Response -> (ASAP) -> Hearing ->
    // (max 6 months) -> Hearing Submission -> (ASAP) -> Grant, then publication in the official
    // journal with grant/certificate if no opposition is raised. Doc notes ~6 months average.
    { key: 'id_filed', label: 'Filed', tier: 'neutral', type: 'design', suggestedAction: 'Await First Examination Report (FER)', slaDays: null },
    { key: 'id_fer_issued', label: 'FER Issued', tier: 'warning', type: 'design', suggestedAction: 'File FER response (novelty/distinctiveness/classification objections)', slaDays: 180 },
    { key: 'id_fer_response_filed', label: 'FER Response Filed', tier: 'info', type: 'design', suggestedAction: 'Awaiting hearing notice or registration', slaDays: null },
    { key: 'id_hearing_fixed', label: 'Hearing Fixed', tier: 'warning', type: 'design', suggestedAction: 'Attend hearing; file hearing submission', slaDays: 180 },
    { key: 'id_hearing_submission_filed', label: 'Hearing Submission Filed', tier: 'info', type: 'design', suggestedAction: 'Awaiting registration/grant decision', slaDays: null },
    { key: 'id_published', label: 'Published — Opposition Window', tier: 'info', type: 'design', suggestedAction: 'Monitor for opposition; grant and certificate follow if none is raised', slaDays: null },
    { key: 'id_registered', label: 'Registered', tier: 'good', type: 'design', suggestedAction: 'File renewal/extension before expiry (10-year initial term)', slaDays: null, renewYears: 10 },
    { key: 'id_refused', label: 'Refused', tier: 'critical', type: 'design', suggestedAction: 'Decide: appeal or abandon', slaDays: null },
    { key: 'id_abandoned', label: 'Abandoned', tier: 'neutral', type: 'design', suggestedAction: '', slaDays: null }
  ];
  function statusDefsForType(ipType) {
    return STATUS_DEFS.filter(function (s) { return s.type === ipType; });
  }

  // Statutory categories of work enumerated in the Copyright Information Document's checklist slide.
  var COPYRIGHT_CATEGORIES = ['Literary work', 'Musical work', 'Dramatic work', 'Artistic work',
    'Cinematograph film', 'Sound recording', 'Architectural work', 'Software'];

  var MARK_TYPES = ['Word', 'Device/Logo', 'Word + Logo', 'Label', 'Colour', 'Sound', 'Series', 'Other'];
  var ENTITY_TYPES = ['Individual', 'Company', 'LLP', 'Partnership', 'Proprietorship', 'Trust', 'Society', 'Other'];
  // Per-matter financial fields. The server strips these from the payload for
  // any role without 'view_financials' (backend/roles.py), so a browser that
  // may not see them never receives them -- these constants only drive the UI.
  var FINANCIAL_FIELDS = ['officialFee', 'professionalFee', 'amountPaid', 'paymentStatus', 'invoiceRef'];
  var PAYMENT_STATUSES = ['Unpaid', 'Partly paid', 'Paid', 'Waived'];

  var GENDER_OPTIONS = ['', 'Male', 'Female', 'Other', 'Prefer not to say'];
  var TIER_VAR = { good: '--good', info: '--accent', neutral: '--neutral', warning: '--warning', serious: '--serious', critical: '--critical' };

  // Per-ipType field labels/modes and behaviour. clsMode/markTypeMode: 'select' | 'text' | 'hidden'.
  // hasAuthors/hasLogo follow the same "field exists on the data model but is only shown/used for
  // certain ipTypes" convention as hasRenewal above.
  var IP_CONFIG = {
    trademark: {
      label: 'Trademark', addLabel: 'Add trademark',
      brandLabel: 'Brand / mark', clsLabel: 'Class', clsMode: 'text', clsOptions: null, clsPlaceholder: 'e.g. 42',
      appnoLabel: 'Application no.', markTypeLabel: 'Mark type', markTypeMode: 'select', markTypeOptions: MARK_TYPES,
      descLabel: 'Goods & services', hasRenewal: true, renewYears: 10, hasAuthors: false, hasContributors: false, hasLogo: true,
      searchPlaceholder: 'Search brand, class, application no., goods & services…'
    },
    copyright: {
      label: 'Copyright', addLabel: 'Add copyright',
      brandLabel: 'Title of Work', clsLabel: 'Category of Work', clsMode: 'select', clsOptions: COPYRIGHT_CATEGORIES,
      appnoLabel: 'Diary Number', markTypeLabel: null, markTypeMode: 'hidden', markTypeOptions: null,
      descLabel: 'Description of Work', hasRenewal: false, renewYears: null, hasAuthors: true, hasContributors: false, hasLogo: false,
      searchPlaceholder: 'Search title of work, category, diary number, description…'
    },
    design: {
      label: 'Design', addLabel: 'Add design',
      brandLabel: 'Design Title', clsLabel: 'Locarno Class', clsMode: 'text', clsOptions: null,
      appnoLabel: 'Application No.', markTypeLabel: 'Article', markTypeMode: 'text', markTypeOptions: null, clsPlaceholder: 'e.g. 09-01',
      descLabel: 'Description of Design', hasRenewal: true, renewYears: 10, hasAuthors: false, hasContributors: true, hasLogo: false,
      searchPlaceholder: 'Search design title, Locarno class, application no., description…'
    }
  };
  function ipConfig(ipType) { return IP_CONFIG[ipType] || IP_CONFIG.trademark; }

  var LOCAL_KEYS = {
    theme: 'lextria-theme', notify: 'lextria-notify-deadlines',
    unlocked: 'lextria-unlocked', notifiedDate: 'lextria-last-notified', pageSize: 'lextria-page-size',
    lockOnRefresh: 'lextria-lock-on-refresh'
  };

  // Search-field definitions: 'all' is always offered; each of these is only
  // offered in the field dropdown when at least one record in view has data for it.
  var SEARCH_FIELDS = [
    { key: 'code', label: 'Code', get: function (r) { return r.code || ''; } },
    { key: 'client', label: 'Client', get: function (r) { var c = clientById(r.clientId); return c ? c.name : ''; }, clientOnly: true },
    { key: 'brand', label: function (cfg) { return cfg.brandLabel; }, get: function (r) { return r.brand || ''; } },
    { key: 'cls', label: function (cfg) { return cfg.clsLabel; }, get: function (r) { return r.cls !== null && r.cls !== undefined ? String(r.cls) : ''; } },
    { key: 'appno', label: function (cfg) { return cfg.appnoLabel; }, get: function (r) { return r.appno || ''; } },
    { key: 'markType', label: function (cfg) { return cfg.markTypeLabel; }, get: function (r) { return r.markType || ''; }, hiddenIf: function (cfg) { return cfg.markTypeMode === 'hidden'; } },
    { key: 'status', label: 'Status', get: function (r) { return statusDef(r.status).label; } },
    { key: 'desc', label: function (cfg) { return cfg.descLabel; }, get: function (r) { return r.desc || ''; } },
    { key: 'action', label: 'Next step', get: function (r) { return r.action || ''; } },
    { key: 'applicant', label: 'Applicant', get: function (r) { return (r.applicants || []).map(function (a) { return [a.name, a.authorizedPerson, a.address].filter(Boolean).join(' '); }).join(' '); } },
    { key: 'author', label: 'Author', get: function (r) { return (r.authors || []).map(function (a) { return [a.name, a.institution, a.address].filter(Boolean).join(' '); }).join(' '); }, hiddenIf: function (cfg) { return !cfg.hasAuthors; } },
    { key: 'assignedTo', label: 'Assigned to', get: function (r) { return r.assignedTo || ''; }, hiddenIf: function () { return !userCan('edit_matter'); } },
    { key: 'invoiceRef', label: 'Invoice ref', get: function (r) { return r.invoiceRef || ''; }, hiddenIf: function () { return !userCan('view_financials'); } },
    { key: 'paymentStatus', label: 'Payment status', get: function (r) { return r.paymentStatus || ''; }, hiddenIf: function () { return !userCan('view_financials'); } },
    { key: 'contributor', label: 'Contributor / Researcher', get: function (r) { return (r.contributors || []).map(function (c) { return [c.name, c.institution, c.affiliation].filter(Boolean).join(' '); }).join(' '); }, hiddenIf: function (cfg) { return !cfg.hasContributors; } }
  ];
  function searchFieldLabel(f, cfg) {
    return typeof f.label === 'function' ? f.label(cfg) : f.label;
  }
  function computeSearchFields(records, showClient, ipType) {
    var cfg = ipConfig(ipType);
    return SEARCH_FIELDS.filter(function (f) {
      if (f.clientOnly && !showClient) return false;
      if (f.hiddenIf && f.hiddenIf(cfg)) return false;
      return records.some(function (r) { return (f.get(r) || '').toString().trim() !== ''; });
    });
  }

  function getLocalPref(key, fallback) {
    try { var v = localStorage.getItem(key); return v === null ? fallback : v; } catch (e) { return fallback; }
  }
  function setLocalPref(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* private mode etc — degrade quietly */ }
  }
  function applyTheme(theme) {
    var root = document.documentElement;
    if (theme === 'dark') root.setAttribute('data-theme', 'dark');
    else if (theme === 'light') root.setAttribute('data-theme', 'light');
    else root.removeAttribute('data-theme');
  }
  function simpleHash(text) {
    var h = 0;
    for (var i = 0; i < text.length; i++) { h = (Math.imul(31, h) + text.charCodeAt(i)) | 0; }
    return 'sh_' + (h >>> 0).toString(16);
  }
  async function sha256Hex(text) {
    try {
      var enc = new TextEncoder().encode(text);
      var buf = await crypto.subtle.digest('SHA-256', enc);
      return Array.prototype.map.call(new Uint8Array(buf), function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
    } catch (e) {
      return simpleHash(text);
    }
  }

  function addDays(iso, days) {
    var d = new Date((iso || todayIso()) + 'T00:00:00Z');
    d.setUTCDate(d.getUTCDate() + days);
    return d.toISOString().slice(0, 10);
  }
  function addYears(iso, years) {
    var d = new Date((iso || todayIso()) + 'T00:00:00Z');
    d.setUTCFullYear(d.getUTCFullYear() + years);
    return d.toISOString().slice(0, 10);
  }

  // Stand-in for a status key that isn't in STATUS_DEFS (legacy or hand-edited
  // data). It reports itself as unknown rather than impersonating a real stage:
  // the previous fallback returned STATUS_DEFS[0], i.e. trademark "Filed", so a
  // copyright or design record with an unreadable status silently displayed as a
  // filed trademark, counted itself into "In examination queue", and — via
  // normalizeState's `sd.type` check — got stamped ipType 'trademark', which
  // also made the CR-/ID- code-prefix fallback there unreachable.
  var UNKNOWN_STATUS = { key: null, label: 'Unknown status', tier: 'neutral', type: null, suggestedAction: '', slaDays: null };

  function statusDef(key) {
    var found = null;
    STATUS_DEFS.forEach(function (s) { if (s.key === key) found = s; });
    return found || UNKNOWN_STATUS;
  }

  /* ===================== Pagination ===================== */
  function getPageSize() {
    var n = parseInt(getLocalPref(LOCAL_KEYS.pageSize, '20'), 10);
    return (n === 10 || n === 20 || n === 50 || n === 100) ? n : 20;
  }
  function setPageSize(n) {
    setLocalPref(LOCAL_KEYS.pageSize, String(n));
    // The page-size control lives in Settings, which has no page counter of its own — reset every
    // paginated view's counter so none of them show a stale, now out-of-range page when revisited.
    view.ledgerPage = 1; view.logPage = 1; view.deadlinesPage = 1;
    renderAll();
  }
  function paginate(items, page, pageSize) {
    var total = items.length;
    var totalPages = Math.max(1, Math.ceil(total / pageSize));
    var p = Math.min(Math.max(1, page || 1), totalPages);
    var start = (p - 1) * pageSize;
    return { pageItems: items.slice(start, start + pageSize), totalPages: totalPages, page: p, total: total };
  }
  function pagerPageKey(scope) {
    if (scope === 'ledger') return 'ledgerPage';
    if (scope === 'log') return 'logPage';
    return 'deadlinesPage';
  }
  function pageNumberList(current, total) {
    var pages = [];
    if (total <= 7) { for (var i = 1; i <= total; i++) pages.push(i); return pages; }
    pages.push(1);
    if (current > 3) pages.push('…');
    for (var j = Math.max(2, current - 1); j <= Math.min(total - 1, current + 1); j++) pages.push(j);
    if (current < total - 2) pages.push('…');
    pages.push(total);
    return pages;
  }
  function renderPager(scope, info) {
    if (!info.total) return '';
    var pageSize = getPageSize();
    var startN = (info.page - 1) * pageSize + 1;
    var endN = Math.min(info.page * pageSize, info.total);
    var html = '<div class="pager">';
    html += '<button data-action="pager-prev" data-scope="' + scope + '"' + (info.page <= 1 ? ' disabled' : '') + '>&lsaquo; Prev</button>';
    pageNumberList(info.page, info.totalPages).forEach(function (p) {
      if (p === '…') { html += '<span class="pager-ellipsis">&hellip;</span>'; return; }
      html += '<button data-action="pager-goto" data-scope="' + scope + '" data-page="' + p + '"' + (p === info.page ? ' aria-current="page"' : '') + '>' + p + '</button>';
    });
    html += '<button data-action="pager-next" data-scope="' + scope + '"' + (info.page >= info.totalPages ? ' disabled' : '') + '>Next &rsaquo;</button>';
    html += '<span class="pager-note">Showing ' + startN + '&ndash;' + endN + ' of ' + info.total + '</span>';
    html += '</div>';
    return html;
  }

  /* ===================== Password reveal ===================== */
  function passwordField(id, value, dataAttrs, placeholder) {
    var eyeOpen = '<svg class="pw-icon-show" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7Z"/><circle cx="12" cy="12" r="3"/></svg>';
    var eyeOff = '<svg class="pw-icon-hide" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:none"><path d="M17.94 17.94A10.94 10.94 0 0 1 12 19c-7 0-11-7-11-7a21.6 21.6 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 7 11 7a21.6 21.6 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><path d="M1 1l22 22"/></svg>';
    return '<div class="password-field"><input type="password" class="pw-input" id="' + id + '"' + (dataAttrs || '') +
      ' value="' + escapeHtml(value || '') + '" placeholder="' + escapeHtml(placeholder || '') + '">' +
      '<button type="button" class="pw-toggle" data-action="toggle-password" data-target="' + id + '" aria-label="Show passphrase">' + eyeOpen + eyeOff + '</button></div>';
  }

  /* ===================== State ===================== */
  function normalizeState(s) {
    s = s || {};
    s.clients = s.clients || [];
    s.records = s.records || [];
    s.log = s.log || [];
    s.settings = s.settings || {};
    if (s.settings.loginEnabled === undefined) s.settings.loginEnabled = false;
    if (s.settings.loginHash === undefined) s.settings.loginHash = null;

    // Enforce guaranteed unique IDs and timeline array across all records
    var seenRecordIds = {};
    var maxRecordSeq = s.nextRecordSeq || 1;
    s.records.forEach(function (r) {
      if (!r.ipType) {
        var sd = statusDef(r.status);
        r.ipType = (sd && sd.type) ? sd.type : (r.code && r.code.startsWith('CR-') ? 'copyright' : (r.code && r.code.startsWith('ID-') ? 'design' : 'trademark'));
      }
      if (!r.timeline || !Array.isArray(r.timeline)) {
        r.timeline = [];
      }
      if (!r.applicants || !Array.isArray(r.applicants)) {
        r.applicants = [];
      }
      if (!r.authors || !Array.isArray(r.authors)) {
        r.authors = [];
      }
      if (!r.contributors || !Array.isArray(r.contributors)) {
        r.contributors = [];
      }
      if (!r.id || seenRecordIds[r.id]) {
        var newId = 't-' + String(maxRecordSeq++).padStart(3, '0');
        while (seenRecordIds[newId]) { newId = 't-' + String(maxRecordSeq++).padStart(3, '0'); }
        r.id = newId;
      }
      seenRecordIds[r.id] = true;
      var m = (r.id || '').match(/^t-(\d+)$/);
      if (m) maxRecordSeq = Math.max(maxRecordSeq, parseInt(m[1], 10) + 1);
    });
    s.nextRecordSeq = maxRecordSeq;

    // Enforce guaranteed unique IDs across all clients
    var seenClientIds = {};
    var maxClientSeq = s.nextClientSeq || 1;
    s.clients.forEach(function (c) {
      if (!c.id || seenClientIds[c.id]) {
        var newCId = 'c-' + String(maxClientSeq++);
        while (seenClientIds[newCId]) { newCId = 'c-' + String(maxClientSeq++); }
        c.id = newCId;
      }
      seenClientIds[c.id] = true;
      var m = (c.id || '').match(/^c-(\d+)$/);
      if (m) maxClientSeq = Math.max(maxClientSeq, parseInt(m[1], 10) + 1);
    });
    s.nextClientSeq = maxClientSeq;

    return s;
  }
  var state = normalizeState(JSON.parse(document.getElementById('app-state').textContent));
  var artifactApi = null;
  var isReadOnly = false;

  /* ===================== Persistence tiers =====================
     Three tiers are tried in order at load time and the winner is used for every
     save for the rest of the session:
       1. 'claude'  — window.claude artifact API (unchanged from the original behavior)
       2. 'backend' — a shared /api/state backend (the bundled FastAPI + SQLite backend), so every browser
                      signed in with an account sees the same live data
       3. 'local'   — this browser's localStorage (always available, never blocks) */
  // The three files this page is split across. Referenced here so the artifact
  // tier can fetch and re-inline them; keep in step with index.html.
  var ASSET_CSS = '/static/css/app.css';
  var ASSET_JS = '/static/js/app.js';
  var ASSET_LOGO = '/static/img/lextria-logo.png';

  var PERSIST_TIER = null;
  var LEXTRIA_STATE_KEY = 'lextria-state';
  var LEXTRIA_AUTH_HEADER = 'X-Lextria-Key';
  var backendConfigured = false;
  var backendAuthorized = false;
  // Whether the backend requires a sign-in. True for the bundled FastAPI
  // backend, which has real accounts; false only when the page is running with
  // no backend at all, where there is nobody to authenticate against.
  var backendAuthRequired = false;
  var sessionUnlocked = false;

  function shouldLockOnRefresh() {
    return getLocalPref(LOCAL_KEYS.lockOnRefresh, 'on') === 'on';
  }

  function tierLabel() {
    if (PERSIST_TIER === 'claude') return 'Claude artifact';
    if (PERSIST_TIER === 'backend') return 'shared team database';
    return 'this browser only';
  }

  // Session identity travels in the HttpOnly cookie, not a header, so this
  // only sets the content type. Kept as a function because every fetch uses it.
  function apiAuthHeaders() {
    return { 'Content-Type': 'application/json' };
  }

  /* ===================== Signed-in user and roles =====================
     currentUser mirrors what the server said in /api/state or /api/login. It
     decides what this browser DISPLAYS; it decides nothing about what may be
     read or written. The server filters the payload and merges writes by role
     (backend/roles.py), so tampering with anything here changes the view and
     not the data. */
  var currentUser = null;

  function userCan(capability) {
    // Outside the backend tier (a Claude artifact, or localStorage-only) there
    // is no server to enforce roles, so the single local user gets everything.
    if (PERSIST_TIER !== 'backend') return true;
    if (!currentUser || !currentUser.can) return false;
    return currentUser.can.indexOf(capability) !== -1;
  }

  function isSignedIn() {
    return PERSIST_TIER !== 'backend' || !!currentUser;
  }

  async function apiPost(url, body) {
    var res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    var data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    return { ok: res.ok, status: res.status, data: data };
  }

  // A failed / non-JSON / non-2xx response from /api/state is treated exactly like
  // { configured: false } so a plain static host (no serverless function at all,
  // e.g. `python3 -m http.server`) falls through to localStorage without ever
  // surfacing an error to the user.
  async function fetchBackendState(overrideKey) {
    try {
      var res = await fetch('/api/state', {
        headers: apiAuthHeaders(overrideKey),
        credentials: 'same-origin'   // carry the session cookie
      });
      var data = null;
      try { data = await res.json(); } catch (e) { data = null; }
      // 401 still means a backend exists — it just wants a sign-in — so this is
      // NOT the "no backend, fall back to localStorage" case.
      if (res.status === 401) {
        return { configured: true, authorized: false, authRequired: true, user: null, state: null };
      }
      if (!res.ok || !data || typeof data !== 'object') return { configured: false, authorized: false, authRequired: false, user: null, state: null };
      return {
        configured: !!data.configured,
        authorized: !!data.authorized,
        // Absent means "assume a sign-in is needed", so a backend predating this
        // field keeps its old gated behaviour rather than silently dropping its
        // access control.
        authRequired: data.authRequired !== false,
        user: (data.user && typeof data.user === 'object') ? data.user : null,
        state: (data.state && typeof data.state === 'object') ? data.state : null
      };
    } catch (e) {
      return { configured: false, authorized: false, authRequired: false, user: null, state: null };
    }
  }

  function loadLocalStorageState() {
    var saved = getLocalPref(LEXTRIA_STATE_KEY, '');
    if (!saved) return;
    try {
      var parsed = JSON.parse(saved);
      if (parsed && typeof parsed === 'object') state = normalizeState(parsed);
    } catch (e) { /* corrupt/foreign value — keep the embedded seed */ }
  }

  async function initPersistence() {
    // Tier 1: Claude artifact API (only present when this exact HTML is opened as a
    // Claude artifact — reopening this shipped copy there still works unchanged).
    if (window.claude && window.claude.use) {
      try {
        var api = await window.claude.use('artifact');
        if (api) {
          // Publishing to an artifact means rebuilding this app as one
          // self-contained file, which needs the CSS/JS/logo the page loads
          // separately. Fetch them up front: if they cannot be read, fall
          // through to a tier that can actually save rather than accepting the
          // tier and failing on the user's first edit.
          await loadInlineSources();
          artifactApi = api;
          PERSIST_TIER = 'claude';
          return;
        }
      } catch (e) { artifactApi = null; }
    }

    // Tier 2: shared backend (see backend/main.py).
    var result = await fetchBackendState();
    if (result.configured) {
      backendConfigured = true;
      backendAuthRequired = result.authRequired;
      PERSIST_TIER = 'backend';
      if (result.authorized) {
        backendAuthorized = true;
        currentUser = result.user;
        sessionUnlocked = true;
        if (result.state) state = normalizeState(result.state);
      } else {
        // A live session cookie is absent or expired — the sign-in screen is
        // rendered by the gate on entry.
        backendAuthorized = false;
        currentUser = null;
      }
      return;
    }

    // Tier 3: localStorage — always available, the guaranteed fallback.
    PERSIST_TIER = 'local';
    loadLocalStorageState();
  }




  var view = {
    mode: 'ledger',
    clientId: '__all__',
    ipType: 'trademark',
    search: '',
    searchField: 'all',
    statusFilter: {},
    sortKey: 'brand',
    sortDir: 1,
    expandedId: null,
    deadlineClientFilter: '__all__',
    ledgerPage: 1,
    logPage: 1,
    deadlinesPage: 1,
    dashboardClientId: '__all__'
  };

  var modalState = null;
  var settingsDraft = { editingLogin: false, newPass: '', confirmPass: '', error: '' };

  /* ===================== Utilities ===================== */
  function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function clientById(id) {
    var found = null;
    state.clients.forEach(function (c) { if (c.id === id) found = c; });
    return found;
  }
  function recordById(id) {
    var found = null;
    state.records.forEach(function (r) { if (r.id === id) found = r; });
    return found;
  }
  // Fees are stored as free text (they may carry a currency or a note), so
  // format only when the value is purely numeric and leave anything else alone.
  function fmtMoney(v) {
    var raw = String(v === null || v === undefined ? '' : v).trim();
    if (!raw) return '';
    if (!/^\d+(\.\d+)?$/.test(raw)) return raw;
    var n = parseFloat(raw);
    return n.toLocaleString('en-IN', { maximumFractionDigits: 2 });
  }

  function fmtDate(iso) {
    if (!iso) return null;
    var parts = iso.split('-');
    if (parts.length !== 3) return iso;
    var d = new Date(Date.UTC(+parts[0], +parts[1] - 1, +parts[2]));
    return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' });
  }
  function fmtDateTime(isoStr) {
    if (!isoStr) return '—';
    try {
      var d = new Date(isoStr);
      if (isNaN(d.getTime())) return isoStr;
      return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) + ', ' +
        d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
    } catch (e) {
      return isoStr;
    }
  }
  function getStatusPipelineIndex(ipType, statusKey) {
    if (!statusKey) return -1;
    var sd = statusDef(statusKey);
    var effectiveType = ipType || (sd ? sd.type : null) || (view && view.ipType) || 'trademark';
    var defs = statusDefsForType(effectiveType);
    for (var i = 0; i < defs.length; i++) {
      if (defs[i].key === statusKey) return i;
    }
    // Not a stage of this ipType's pipeline (e.g. a trademark status left on a
    // record that was imported as a copyright). There is no position to report:
    // returning an index into the combined STATUS_DEFS array instead — as this
    // used to — mixes two different numbering schemes, so isForwardTransition
    // would then compare a 0..9 pipeline position against a 0..28 global one
    // and call arbitrary pairs "forward".
    return -1;
  }
  function isForwardTransition(ipType, oldStatus, newStatus) {
    if (!oldStatus || !newStatus || oldStatus === newStatus) return false;
    var oldSd = statusDef(oldStatus);
    var newSd = statusDef(newStatus);
    var effectiveType = ipType || (oldSd ? oldSd.type : null) || (newSd ? newSd.type : null) || (view && view.ipType) || 'trademark';
    var oldIdx = getStatusPipelineIndex(effectiveType, oldStatus);
    var newIdx = getStatusPipelineIndex(effectiveType, newStatus);
    if (oldIdx === -1 || newIdx === -1) return false;
    return newIdx > oldIdx;
  }
  function calculateSuggestedDeadline(ipType, newStatusKey) {
    var sd = statusDef(newStatusKey);
    if (sd && sd.slaDays != null) {
      return addDays(todayIso(), sd.slaDays);
    }
    return '';
  }
  function todayIso() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  function daysUntil(iso) {
    var today = new Date(todayIso() + 'T00:00:00Z');
    var target = new Date(iso + 'T00:00:00Z');
    return Math.round((target - today) / 86400000);
  }
  function humanCountdown(days) {
    if (days < 0) return Math.abs(days) + 'd overdue';
    if (days === 0) return 'due today';
    var years = Math.floor(days / 365);
    var months = Math.floor((days % 365) / 30);
    if (years >= 1) return 'in ' + years + 'y ' + months + 'm';
    if (months >= 1) return 'in ' + months + 'mo';
    return 'in ' + days + 'd';
  }
  function nextRecordId(st) {
    var s = st || state;
    var max = 0;
    (s.records || []).forEach(function (r) {
      var m = (r.id || '').match(/^t-(\d+)$/);
      if (m) max = Math.max(max, parseInt(m[1], 10));
    });
    var seq = Math.max(max + 1, s.nextRecordSeq || 1);
    return 't-' + String(seq).padStart(3, '0');
  }
  function nextClientId(st) {
    var s = st || state;
    var max = 0;
    (s.clients || []).forEach(function (c) {
      var m = (c.id || '').match(/^c-(\d+)$/);
      if (m) max = Math.max(max, parseInt(m[1], 10));
    });
    var seq = Math.max(max + 1, s.nextClientSeq || 1);
    return 'c-' + String(seq);
  }
  function toast(msg, tone) {
    var root = document.getElementById('toast-root');
    var el = document.createElement('div');
    el.className = 'toast';
    el.textContent = msg;
    root.appendChild(el);
    setTimeout(function () { el.remove(); }, 4200);
  }

  /* ===================== Login gate =====================
     NOTE ON SECURITY: this is a client-side convenience screen only. Anyone
     with the artifact link can still read this page's full source (including
     the state and this very script) via their browser's dev tools — a
     passphrase check running in that same page cannot stop them. Real access
     control comes from keeping this artifact private and sharing the link
     only with people who should see it. This screen just keeps the dashboard
     from being visible to someone who stumbles onto an open screen or link. */
  function isUnlocked() {
    if (sessionUnlocked) return true;
    if (!shouldLockOnRefresh()) {
      if (sessionStorage.getItem('lextria-session-unlocked') === 'yes' || getLocalPref(LOCAL_KEYS.unlocked, '') === 'yes') {
        sessionUnlocked = true;
        return true;
      }
    }
    return false;
  }
  function needsGate() {
    // The backend requires a real account, so the gate is a sign-in screen and
    // stays up until the server confirms a session. The legacy shared
    // passphrase only applies when there is no backend to authenticate against.
    if (PERSIST_TIER === 'backend' && backendAuthRequired) return !currentUser;
    if (state.settings && state.settings.loginEnabled && state.settings.loginHash) {
      return !isUnlocked();
    }
    return false;
  }

  function renderSignIn(root, errorMsg, busy) {
    root.innerHTML = '<div class="gate-overlay"><div class="gate-card">' +
      '<img class="brand-logo" src="/static/img/lextria-logo.png" alt="Lextria Research seal">' +
      '<h2>Lextria IP Ledger</h2>' +
      '<p>Sign in to continue.</p>' +
      (errorMsg ? '<p class="gate-error">' + escapeHtml(errorMsg) + '</p>' : '') +
      '<div class="field"><input type="text" id="signin-user" placeholder="Username" ' +
      'autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false"></div>' +
      passwordField('signin-pass', '', ' autocomplete="current-password"', 'Password') +
      '<button class="btn btn-primary" data-action="signin-submit" style="width:100%;justify-content:center;"' +
      (busy ? ' disabled' : '') + '>' + (busy ? 'Signing in…' : 'Sign in') + '</button>' +
      '<p class="gate-hint">Your account decides what you can see. Ask a super admin if you need access.</p>' +
      '</div></div>';
    var userInput = document.getElementById('signin-user');
    var passInput = document.getElementById('signin-pass');
    function onKey(e) { if (e.key === 'Enter') attemptSignIn(); }
    if (userInput) { userInput.focus(); userInput.addEventListener('keydown', onKey); }
    if (passInput) { passInput.addEventListener('keydown', onKey); }
  }

  async function attemptSignIn() {
    var userInput = document.getElementById('signin-user');
    var passInput = document.getElementById('signin-pass');
    if (!userInput || !passInput) return;
    var username = userInput.value.trim();
    var password = passInput.value;
    if (!username || !password) {
      renderGate('Enter your username and password.');
      return;
    }
    renderGate(null, true);
    var res = await apiPost('/api/login', { username: username, password: password });
    if (!res.ok) {
      renderGate((res.data && res.data.error) || 'Could not sign in. Please try again.');
      return;
    }
    // Re-read the ledger: what comes back is already filtered for this role.
    var fresh = await fetchBackendState();
    currentUser = (res.data && res.data.user) || fresh.user;
    backendAuthorized = true;
    sessionUnlocked = true;
    state = normalizeState(fresh.state || { clients: [], records: [], log: [] });
    renderGate();
    renderAll();
    if (userCan('manage_users')) loadUsers();
    loadAssignees().then(function () { renderAll(); });
    toast('Signed in as ' + currentUser.username + ' (' + currentUser.roleLabel + ')');
  }

  async function signOut() {
    await apiPost('/api/logout');
    currentUser = null;
    backendAuthorized = false;
    sessionUnlocked = false;
    try { sessionStorage.removeItem('lextria-session-unlocked'); } catch (e) { /* private mode */ }
    state = normalizeState({ clients: [], records: [], log: [] });
    renderAll();
    renderGate();
  }
  function renderGate(errorMsg, busy) {
    var root = document.getElementById('gate-root');
    if (!root) return;
    if (!needsGate()) {
      root.innerHTML = '';
      document.body.classList.remove('gated');
      return;
    }
    document.body.classList.add('gated');
    // Real accounts on the backend get the sign-in form; the shared-passphrase
    // screen below is only for the no-backend case.
    if (PERSIST_TIER === 'backend' && backendAuthRequired) {
      renderSignIn(root, errorMsg, busy);
      return;
    }
    root.innerHTML = '<div class="gate-overlay"><div class="gate-card">' +
      '<img class="brand-logo" src="/static/img/lextria-logo.png" alt="Lextria Research seal">' +
      '<h2>Lextria IP Ledger</h2>' +
      '<p>Enter the team passphrase to continue.</p>' +
      (errorMsg ? '<p class="gate-error">' + escapeHtml(errorMsg) + '</p>' : '') +
      passwordField('gate-input', '', ' autocomplete="current-password"', 'Passphrase') +
      '<button class="btn btn-primary" data-action="gate-submit" style="width:100%;justify-content:center;">Unlock Dashboard</button>' +
      '<p class="gate-hint">Ask whoever manages this ledger for the passphrase.</p>' +
      '</div></div>';
    var input = document.getElementById('gate-input');
    if (input) {
      input.focus();
      input.addEventListener('keydown', function (e) { if (e.key === 'Enter') attemptUnlock(); });
    }
  }
  async function attemptUnlock() {
    var input = document.getElementById('gate-input');
    if (!input) return;
    var pass = input.value.trim();
    if (!pass) {
      renderGate('Please enter your passphrase.');
      return;
    }

    // The access-key branch that used to live here is gone: a backend now
    // means real accounts, and renderGate routes to the sign-in form before
    // this function is ever reached. What remains is the local, no-backend
    // passphrase screen.

    if (state.settings && state.settings.loginEnabled && state.settings.loginHash) {
      var hash = await sha256Hex(pass);
      if (hash === state.settings.loginHash) {
        sessionUnlocked = true;
        sessionStorage.setItem('lextria-session-unlocked', 'yes');
        if (!shouldLockOnRefresh()) {
          setLocalPref(LOCAL_KEYS.unlocked, 'yes');
        }
        renderGate();
        renderAll();
        toast('Unlocked.');
        return;
      } else {
        renderGate('Incorrect passphrase — try again.');
        return;
      }
    }

    sessionUnlocked = true;
    renderGate();
    renderAll();
  }
  function lockNow() {
    sessionUnlocked = false;
    sessionStorage.removeItem('lextria-session-unlocked');
    setLocalPref(LOCAL_KEYS.unlocked, '');
    renderGate();
    renderAll();
    toast('Dashboard locked.');
  }
  function setLoginPassphrase(newPass) {
    sha256Hex(newPass).then(function (hash) {
      var newState = JSON.parse(JSON.stringify(state));
      newState.settings = newState.settings || {};
      newState.settings.loginHash = hash;
      newState.settings.loginEnabled = true;
      pushLog(newState, (state.settings.loginEnabled ? 'Updated' : 'Turned on') + ' the ledger login passphrase');
      setLocalPref(LOCAL_KEYS.unlocked, 'yes');
      persist(newState, 'Passphrase saved');
    });
  }
  function disableLogin() {
    var newState = JSON.parse(JSON.stringify(state));
    newState.settings = newState.settings || {};
    newState.settings.loginEnabled = false;
    pushLog(newState, 'Turned off the ledger login passphrase');
    persist(newState, 'Login turned off');
  }
  function submitLoginSave() {
    if (!settingsDraft.newPass || settingsDraft.newPass.length < 4) {
      settingsDraft.error = 'Use at least 4 characters.';
      renderAll();
      return;
    }
    if (settingsDraft.newPass !== settingsDraft.confirmPass) {
      settingsDraft.error = 'Passphrases don\'t match.';
      renderAll();
      return;
    }
    setLoginPassphrase(settingsDraft.newPass);
    settingsDraft = { editingLogin: false, newPass: '', confirmPass: '', error: '' };
  }

  /* ===================== Deadline notifications (this device only) ===================== */
  function maybeNotifyDeadlines() {
    if (getLocalPref(LOCAL_KEYS.notify, 'off') !== 'on') return;
    if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
    var today = todayIso();
    if (getLocalPref(LOCAL_KEYS.notifiedDate, '') === today) return;
    setLocalPref(LOCAL_KEYS.notifiedDate, today);
    var urgent = computeDeadlines('__all__').filter(function (d) { return daysUntil(d.date) <= 45; });
    if (!urgent.length) return;
    try {
      new Notification('Lextria IP Ledger', {
        body: urgent.length + ' filing' + (urgent.length === 1 ? '' : 's') + ' due within 45 days. Soonest: ' +
          urgent[0].record.brand + ' — ' + fmtDate(urgent[0].date) + '.',
        tag: 'lextria-deadlines'
      });
    } catch (e) { /* some hosts restrict Notification even when "granted" — fail quietly */ }
  }
  function handleNotifyToggle(checked) {
    if (!checked) { setLocalPref(LOCAL_KEYS.notify, 'off'); renderAll(); return; }
    if (typeof Notification === 'undefined') {
      toast('Desktop notifications aren\'t available in this preview window.');
      renderAll();
      return;
    }
    if (Notification.permission === 'granted') {
      setLocalPref(LOCAL_KEYS.notify, 'on');
      toast('Desktop alerts turned on.');
      renderAll();
      setLocalPref(LOCAL_KEYS.notifiedDate, '');
      maybeNotifyDeadlines();
      return;
    }
    if (Notification.permission === 'denied') {
      toast('Notifications are blocked for this page in your browser\'s settings.');
      renderAll();
      return;
    }
    Notification.requestPermission().then(function (perm) {
      if (perm === 'granted') {
        setLocalPref(LOCAL_KEYS.notify, 'on');
        toast('Desktop alerts turned on.');
        setLocalPref(LOCAL_KEYS.notifiedDate, '');
        maybeNotifyDeadlines();
      } else {
        toast('Notifications need your browser\'s permission — allow them and try again.');
      }
      renderAll();
    });
  }

  /* ===================== Persistence =====================
     The page loads its CSS, JS and logo as three separate files. The Claude
     artifact tier, however, publishes ONE self-contained HTML document, so
     those three have to be fetched back and inlined at publish time. They are
     cached here rather than re-fetched on every save, and are only ever loaded
     when that tier is actually in use — the normal FastAPI path never pays for
     them. */
  var inlineSources = null;

  function fetchText(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error('Could not read ' + url);
      return r.text();
    });
  }

  function fetchDataUri(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error('Could not read ' + url);
      return r.blob();
    }).then(function (blob) {
      return new Promise(function (resolve, reject) {
        var fr = new FileReader();
        fr.onload = function () { resolve(fr.result); };
        fr.onerror = function () { reject(new Error('Could not encode ' + url)); };
        fr.readAsDataURL(blob);
      });
    });
  }

  function loadInlineSources() {
    if (inlineSources) return Promise.resolve(inlineSources);
    return Promise.all([
      fetchText(ASSET_CSS), fetchText(ASSET_JS), fetchDataUri(ASSET_LOGO)
    ]).then(function (parts) {
      inlineSources = { css: parts[0], js: parts[1], logo: parts[2] };
      return inlineSources;
    });
  }

  // Requires loadInlineSources() to have resolved. initPersistence awaits it
  // before committing to the artifact tier, so a publish cannot reach here with
  // an empty cache and silently ship a document with no styles and no logo.
  function buildFullDocument(newState) {
    if (!inlineSources) throw new Error('Inline sources not loaded');
    var logo = inlineSources.logo;
    // Point every logo reference back at an embedded image, so the published
    // artifact holds no outbound reference to this server.
    var reLogo = new RegExp(ASSET_LOGO.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g');
    var titleHtml = '<title>' + escapeHtml(document.title) + '</title>';
    // Only the webfont links travel with the artifact — the stylesheet and
    // favicon links address this server and would 404 anywhere else.
    var fontLinkTags = Array.prototype.map.call(
      document.querySelectorAll('link[href^="https://fonts."]'),
      function (l) { return l.outerHTML; }
    ).join('\n');
    var styleHtml = '<style id="app-style">' + inlineSources.css.replace(reLogo, logo) + '</style>';
    var scriptSrc = inlineSources.js.replace(reLogo, logo);
    // <, not '&lt;': this JSON is embedded in a <script> element, whose
    // content is raw text where HTML entities are never decoded. The original
    // here was .replace(/</g, '<') — a no-op that left any ledger value
    // containing "</script>" (a client name, a description) free to close the
    // block early and inject markup into the published artifact. The escape has
    // to survive JSON.parse, so it has to be a JSON string escape.
    var stateJson = JSON.stringify(newState).replace(/</g, '\\u003c');
    return '<!doctype html>\n<html>\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n' +
      titleHtml + '\n' + fontLinkTags + '\n' + styleHtml + '\n</head>\n<body>\n' +
      '<div class="app" id="app-root"></div>\n<div id="modal-root"></div>\n<div id="gate-root"></div>\n<div id="backend-key-root"></div>\n<div id="toast-root" class="toast-stack"></div>\n' +
      '<script id="app-state" type="application/json">' + stateJson + '<' + '/script>\n' +
      '<script id="app-script">' + scriptSrc + '<' + '/script>\n</body>\n</html>';
  }

  function persist(newState, successMsg) {
    // Optimistic update: the UI reflects the change immediately, for every tier —
    // a failed remote save reports itself via toast rather than reverting silently
    // or looking like it worked.
    state = newState;
    renderAll();

    if (PERSIST_TIER === 'claude') {
      if (!artifactApi) {
        toast((successMsg || 'Saved') + ' — local preview only (open from claude.ai to sync with your team)');
        return;
      }
      artifactApi.publish(buildFullDocument(state)).then(function () {
        // successful publish reloads this view automatically
      }, function (err) {
        if (err && (err.code === 'not_writer' || err.code === 'not_granted')) {
          isReadOnly = true;
          toast('This ledger is read-only for your account.');
          renderAll();
        } else if (err && err.code === 'conflict') {
          toast('Someone else just updated the ledger — reloading…');
        } else {
          toast('Could not save — please try again.');
        }
      });
      return;
    }

    if (PERSIST_TIER === 'backend') {
      fetch('/api/state', { method: 'PUT', headers: apiAuthHeaders(), credentials: 'same-origin', body: JSON.stringify(state) })
        .then(function (res) {
          if (res.status === 401) {
            // The session lapsed. Put the sign-in screen back rather than
            // leaving someone editing a ledger that can no longer be saved.
            backendAuthorized = false;
            currentUser = null;
            toast('Your session expired — please sign in again.');
            renderGate();
            return;
          }
          if (res.status === 403) {
            toast('Your role does not allow that change.');
            return;
          }
          if (!res.ok) {
            toast('Could not save to the shared database — please try again.');
          }
        })
        .catch(function () {
          toast('Could not save to the shared database — check your connection and try again.');
        });
      return;
    }

    // Local-only tier.
    try {
      localStorage.setItem(LEXTRIA_STATE_KEY, JSON.stringify(state));
    } catch (e) {
      toast('Could not save — this browser\'s storage may be full or in private-browsing mode.');
    }
  }

  /* ===================== Derived data ===================== */
  function recordsFor(clientId, ipType) {
    return state.records.filter(function (r) {
      return r.ipType === ipType && (!clientId || clientId === '__all__' || r.clientId === clientId);
    });
  }
  function computeDeadlines(clientFilter, ipTypeFilter) {
    var items = [];
    state.records.forEach(function (r) {
      if (ipTypeFilter && r.ipType !== ipTypeFilter) return;
      if (clientFilter && clientFilter !== '__all__' && r.clientId !== clientFilter) return;
      var client = clientById(r.clientId);
      if (r.actionDate) {
        items.push({ record: r, client: client, kind: 'action', label: r.action || statusDef(r.status).suggestedAction || 'Action required', date: r.actionDate });
      }
      if (r.renewDate) {
        items.push({ record: r, client: client, kind: 'renewal', label: 'File renewal', date: r.renewDate });
      }
    });
    items.sort(function (a, b) { return a.date < b.date ? -1 : a.date > b.date ? 1 : 0; });
    return items;
  }
  // "Needs a deadline" = matters sitting in an at-risk status (tier warning/serious — e.g. trademark's
  // Objected/Opposed) with no action date logged yet. Tier-based so it generalizes across ipTypes.
  function computeNeedsDeadline(clientFilter, ipTypeFilter) {
    return state.records.filter(function (r) {
      if (ipTypeFilter && r.ipType !== ipTypeFilter) return false;
      if (clientFilter && clientFilter !== '__all__' && r.clientId !== clientFilter) return false;
      var tier = statusDef(r.status).tier;
      return (tier === 'warning' || tier === 'serious') && !r.actionDate;
    });
  }

  /* ===================== Rendering: shell ===================== */
  function renderAll() {
    document.getElementById('app-root').innerHTML = renderApp();
  }

  function renderApp() {
    var html = '';
    html += renderMasthead();
    if (isReadOnly) {
      html += '<div class="readonly-banner">👁 You have read-only access to this ledger. Changes you make here won\'t be saved.</div>';
    }
    html += '<main>';
    html += '<div class="view-panel' + (view.mode === 'clientDashboard' ? ' active' : '') + '" id="view-clientdashboard">' + renderClientDashboardView() + '</div>';
    html += '<div class="view-panel' + (view.mode === 'ledger' ? ' active' : '') + '" id="view-ledger">' + renderLedgerView() + '</div>';
    html += '<div class="view-panel' + (view.mode === 'deadlines' ? ' active' : '') + '" id="view-deadlines">' + renderDeadlinesView() + '</div>';
    html += '<div class="view-panel' + (view.mode === 'log' ? ' active' : '') + '" id="view-log">' + renderLogView() + '</div>';
    html += '<div class="view-panel' + (view.mode === 'settings' ? ' active' : '') + '" id="view-settings">' + renderSettingsView() + '</div>';
    html += '</main>';
    html += renderFooter();
    return html;
  }

  function renderMasthead() {
    var totalDeadlines = computeDeadlines('__all__').filter(function (d) { return daysUntil(d.date) <= 45; }).length;
    return '' +
      '<header class="masthead">' +
      '<div class="brand"><img class="brand-logo" src="/static/img/lextria-logo.png" alt="Lextria Research seal"><div class="brand-text"><span class="brand-kicker">Lextria Research</span><h1>Lextria IP Dashboard</h1></div></div>' +
      '<nav class="view-tabs" role="tablist" aria-label="View">' +
      '<button class="tab' + (view.mode === 'clientDashboard' ? ' active' : '') + '" data-action="set-mode" data-mode="clientDashboard">Overview</button>' +
      '<button class="tab' + (view.mode === 'ledger' ? ' active' : '') + '" data-action="set-mode" data-mode="ledger">Ledger</button>' +
      '<button class="tab' + (view.mode === 'deadlines' ? ' active' : '') + '" data-action="set-mode" data-mode="deadlines">Deadlines' +
      (totalDeadlines > 0 ? ' <span class="count-pill">' + totalDeadlines + '</span>' : '') + '</button>' +
      '<button class="tab' + (view.mode === 'log' ? ' active' : '') + '" data-action="set-mode" data-mode="log">Log</button>' +
      '<button class="tab' + (view.mode === 'settings' ? ' active' : '') + '" data-action="set-mode" data-mode="settings" aria-label="Settings">' +
      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"/></svg>' +
      'Settings</button>' +
      (currentUser
        ? '<span class="tab role-badge" title="Signed in as ' + escapeHtml(currentUser.username) + '">' +
            escapeHtml(currentUser.username) + ' &middot; ' + escapeHtml(currentUser.roleLabel) + '</span>'
        : '') +
      (currentUser
        ? '<button class="tab" data-action="sign-out" title="Sign out">Sign out</button>'
        : '') +
      (currentUser ? '' :
      '<button class="tab" data-action="lock-now" aria-label="Lock" title="Lock dashboard and require login">' +
      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>' +
      'Lock</button>') +
      '</nav>' +
      '</header>';
  }

  function renderFooter() {
    return '<footer><span>' + state.clients.length + ' client' + (state.clients.length === 1 ? '' : 's') + ' &middot; ' +
      state.records.length + ' matters tracked</span><span>Lextria IP Dashboard</span>' +
      '<span>Saving to: ' + escapeHtml(tierLabel()) + '</span></footer>';
  }

  /* ===================== Client Dashboard view ===================== */
  function renderClientDashboardView() {
    if (view.dashboardClientId && view.dashboardClientId !== '__all__' && !clientById(view.dashboardClientId)) {
      view.dashboardClientId = '__all__';
    }
    var cid = view.dashboardClientId || '__all__';
    var html = '<div class="toolbar" style="margin-bottom:18px;"><div class="toolbar-left">';
    html += '<select class="client-select" data-action="dashboard-change-client">';
    html += '<option value="__all__"' + (cid === '__all__' ? ' selected' : '') + '>All Clients</option>';
    state.clients.forEach(function (c) {
      html += '<option value="' + escapeHtml(c.id) + '"' + (c.id === cid ? ' selected' : '') + '>' + escapeHtml(c.name) + '</option>';
    });
    html += '</select></div></div>';

    html += '<div class="stats-row">';
    ['trademark', 'copyright', 'design'].forEach(function (t) {
      var tcfg = ipConfig(t);
      var n = recordsFor(cid, t).length;
      html += '<button type="button" class="stat-tile stat-tile-clickable" data-action="dashboard-goto" data-iptype="' + t + '">' +
        '<div class="stat-label">' + escapeHtml(tcfg.label) + 's</div>' +
        '<div class="stat-value">' + n + '</div>' +
        '<div class="stat-foot stat-link">View ledger &rarr;</div>' +
        '</button>';
    });
    html += '</div>';
    return html;
  }

  /* ===================== Ledger view ===================== */
  function renderLedgerView() {
    if (view.clientId && view.clientId !== '__all__' && !clientById(view.clientId)) {
      view.clientId = '__all__';
    }
    var cid = view.clientId || '__all__';
    var cfg = ipConfig(view.ipType);
    var html = '<div class="toolbar">';
    html += '<div class="toolbar-left">';
    html += '<select class="client-select" data-action="change-client">';
    html += '<option value="__all__"' + (cid === '__all__' ? ' selected' : '') + '>All ' + cfg.label + 's</option>';
    state.clients.forEach(function (c) {
      html += '<option value="' + escapeHtml(c.id) + '"' + (c.id === cid ? ' selected' : '') + '>' + escapeHtml(c.name) + '</option>';
    });
    html += '<option value="__new__">+ Add client&hellip;</option>';
    html += '</select>';
    html += '<div class="subtabs">';
    ['trademark', 'copyright', 'design'].forEach(function (t) {
      var label = ipConfig(t).label;
      html += '<button class="subtab' + (view.ipType === t ? ' active' : '') + '" data-action="set-iptype" data-iptype="' + t + '">' + label + '</button>';
    });
    html += '</div></div>';
    html += '<div class="toolbar-right">';
    if (userCan('export')) html += '<button class="btn btn-secondary" data-action="open-export"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 21V9m0 0-4 4m4-4 4 4M4 7V5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v2"/></svg>Export</button>';
    if (!isReadOnly && userCan('import')) {
      html += '<button class="btn btn-secondary" data-action="open-import"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v12m0 0-4-4m4 4 4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>Import</button>';
    }
    if (!isReadOnly && userCan('create_matter')) {
      html += '<button class="btn btn-primary" data-action="open-add"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>' + escapeHtml(cfg.addLabel) + '</button>';
    }
    html += '</div></div>';

    var clientRecords = recordsFor(cid, view.ipType);
    html += renderStats(clientRecords, view.ipType);
    html += '<div class="workspace">';
    html += renderLedgerTable(clientRecords, view.ipType);
    html += renderLedgerRail(clientRecords, view.ipType);
    html += '</div>';
    return html;
  }

  // Buckets generalize by status tier (rather than hardcoded status keys) so the same logic works
  // across trademark/copyright/design. For trademark this reproduces the exact previous counts:
  // registered==tier good, queued (filed/formalities-pass)==tier neutral, needs-attention
  // (objected/opposed/refused)==tier warning|serious|critical.
  function renderStats(records, ipType) {
    var total = records.length;
    var registered = records.filter(function (r) { return statusDef(r.status).tier === 'good'; }).length;
    var queued = records.filter(function (r) { return statusDef(r.status).tier === 'neutral'; }).length;
    var attention = records.filter(function (r) {
      var t = statusDef(r.status).tier;
      return t === 'warning' || t === 'serious' || t === 'critical';
    }).length;
    function tile(label, value, foot, tone) {
      return '<div class="stat-tile' + (tone ? ' ' + tone : '') + '"><div class="stat-label">' + label + '</div>' +
        '<div class="stat-value">' + value + '</div>' + (foot ? '<div class="stat-foot">' + foot + '</div>' : '') + '</div>';
    }
    var scopeLabel = view.clientId === '__all__' ? 'Across all clients' : 'For this client';
    return '<div class="stats-row">' +
      tile('Total applications', total, total ? scopeLabel : 'No matters yet') +
      tile('Registered &amp; secured', registered, total ? Math.round(registered / total * 100) + '% of portfolio' : '', 'accent-good') +
      tile('In examination queue', queued, 'Filed or formalities passed') +
      tile('Needs attention', attention, 'Objected, opposed or refused', attention > 0 ? 'accent-warn' : '') +
      '</div>';
  }

  function matchesSearch(r, q, field, showClient) {
    if (!q) return true;
    q = q.toLowerCase();
    if (field && field !== 'all') {
      var fd = null;
      SEARCH_FIELDS.forEach(function (f) { if (f.key === field) fd = f; });
      if (!fd) return true;
      return (fd.get(r) || '').toString().toLowerCase().indexOf(q) !== -1;
    }
    var hay = SEARCH_FIELDS.filter(function (f) { return !f.clientOnly || showClient; })
      .map(function (f) { return f.get(r); }).join(' ');
    return hay.toLowerCase().indexOf(q) !== -1;
  }
  function cmpRecords(a, b, key, dir) {
    var av = a[key], bv = b[key];
    if (key === 'client') {
      var ca = clientById(a.clientId), cb = clientById(b.clientId);
      av = ca ? ca.name : ''; bv = cb ? cb.name : '';
    }
    if (key === 'renewDate') { av = av || '9999-99-99'; bv = bv || '9999-99-99'; }
    if (av === null || av === undefined) av = '';
    if (bv === null || bv === undefined) bv = '';
    return String(av).localeCompare(String(bv), undefined, { numeric: true }) * dir;
  }

  // The fee breakdown for one matter, shown in the expanded row. Only reached
  // when the role may see financials -- for anyone else the fields are not even
  // present on the record.
  function renderFinancialBlock(r) {
    var rows = [
      ['Official / govt. fee', r.officialFee],
      ['Professional fee', r.professionalFee],
      ['Amount received', r.amountPaid],
      ['Invoice reference', r.invoiceRef]
    ].filter(function (row) { return row[1]; });
    if (!rows.length && !r.paymentStatus) return '';

    var html = '<div class="detail-block"><h4>Financials</h4>';
    if (r.paymentStatus) {
      html += '<p><span class="pay-pill pay-' +
        escapeHtml(String(r.paymentStatus).toLowerCase().replace(/[^a-z]+/g, '-')) + '">' +
        escapeHtml(r.paymentStatus) + '</span></p>';
    }
    rows.forEach(function (row) {
      var value = row[0] === 'Invoice reference' ? row[1] : fmtMoney(row[1]);
      html += '<p><span class="fin-label">' + escapeHtml(row[0]) + '</span> ' +
        escapeHtml(value) + '</p>';
    });

    // Outstanding is worth stating rather than leaving to mental arithmetic,
    // but only when both figures are plain numbers.
    var fee = parseFloat(r.professionalFee), paid = parseFloat(r.amountPaid);
    if (!isNaN(fee) && !isNaN(paid) && fee > paid) {
      html += '<p class="fin-outstanding">Outstanding ' + escapeHtml(fmtMoney(String(fee - paid))) + '</p>';
    }
    html += '</div>';
    return html;
  }

  function renderLedgerTable(allRecords, ipType) {
    var cfg = ipConfig(ipType);
    var showClient = view.clientId === '__all__';
    var searchFields = computeSearchFields(allRecords, showClient, ipType);
    if (view.searchField !== 'all' && !searchFields.some(function (f) { return f.key === view.searchField; })) {
      view.searchField = 'all';
    }
    var activeStatuses = Object.keys(view.statusFilter).filter(function (k) { return view.statusFilter[k]; });
    var rows = allRecords.filter(function (r) {
      if (activeStatuses.length && activeStatuses.indexOf(r.status) === -1) return false;
      return matchesSearch(r, view.search, view.searchField, showClient);
    }).sort(function (a, b) { return cmpRecords(a, b, view.sortKey, view.sortDir); });

    var pageInfo = paginate(rows, view.ledgerPage, getPageSize());
    view.ledgerPage = pageInfo.page;
    var pageRows = pageInfo.pageItems;

    var html = '<div class="card ledger-card">';
    html += '<div class="ledger-controls">';
    html += '<div class="search-controls">';
    html += '<div class="search-box"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>' +
      '<input type="text" data-action="search" placeholder="' + escapeHtml(cfg.searchPlaceholder) + '" value="' + escapeHtml(view.search) + '"></div>';
    html += '<select class="search-field-select" data-action="search-field" title="Search a specific field">';
    html += '<option value="all"' + (view.searchField === 'all' ? ' selected' : '') + '>All fields</option>';
    searchFields.forEach(function (f) {
      html += '<option value="' + f.key + '"' + (view.searchField === f.key ? ' selected' : '') + '>' + escapeHtml(searchFieldLabel(f, cfg)) + '</option>';
    });
    html += '</select>';
    html += '</div>';
    html += '<div class="chip-row">';
    var counts = {};
    allRecords.forEach(function (r) { counts[r.status] = (counts[r.status] || 0) + 1; });
    html += '<button class="chip" data-action="clear-status-filter" aria-pressed="' + (activeStatuses.length === 0 ? 'true' : 'false') + '">All <span class="n">' + allRecords.length + '</span></button>';
    statusDefsForType(ipType).forEach(function (s) {
      var n = counts[s.key] || 0;
      if (!n) return;
      html += '<button class="chip" data-action="toggle-status-filter" data-status="' + s.key + '" aria-pressed="' + (view.statusFilter[s.key] ? 'true' : 'false') + '">' +
        '<span class="dot" style="background:var(' + TIER_VAR[s.tier] + ')"></span>' + s.label + ' <span class="n">' + n + '</span></button>';
    });
    html += '</div></div>';
    var noteN = rows.length;
    var noteHtml = noteN ? 'Showing ' + ((pageInfo.page - 1) * getPageSize() + 1) + '&ndash;' + Math.min(pageInfo.page * getPageSize(), noteN) + ' of ' + noteN + ' applications' : 'Showing 0 of ' + allRecords.length + ' applications';
    if (noteN !== allRecords.length) noteHtml += ' (filtered from ' + allRecords.length + ' total)';
    html += '<p class="result-note">' + noteHtml + '</p>';

    html += '<div class="table-scroll"><table><thead><tr>';
    var cols = [['code', 'Code'], ['brand', cfg.brandLabel]];
    if (showClient) cols.push(['client', 'Client']);
    cols.push(['cls', cfg.clsLabel], ['appno', cfg.appnoLabel]);
    if (cfg.markTypeMode !== 'hidden') cols.push(['markType', cfg.markTypeLabel]);
    cols.push(['status', 'Status']);
    if (cfg.hasRenewal) cols.push(['renewDate', 'Renewal']);
    if (userCan('edit_matter')) cols.push(['assignedTo', 'Assigned to']);
    // Only a role the server actually sends financials to gets the columns.
    // Just the payment state here -- the full fee breakdown lives in the
    // expanded row, because three more columns pushed the table off-screen.
    if (userCan('view_financials')) cols.push(['paymentStatus', 'Payment']);
    var colCount = cols.length + 1;
    cols.forEach(function (c) {
      html += '<th data-sort="' + c[0] + '"' + (view.sortKey === c[0] ? ' data-active' : '') + '><button data-action="sort" data-key="' + c[0] + '">' + escapeHtml(c[1]) + ' <span class="arrow">' + (view.sortKey === c[0] ? (view.sortDir === 1 ? '↑' : '↓') : '↕') + '</span></button></th>';
    });
    html += '<th style="width:70px">Actions</th>';
    html += '</tr></thead><tbody>';

    if (!pageRows.length) {
      html += '<tr><td colspan="' + colCount + '"><div class="empty-state">No matters match this filter.</div></td></tr>';
    }
    pageRows.forEach(function (r) {
      var sd = statusDef(r.status);
      var isOpen = view.expandedId === r.id;
      var client = clientById(r.clientId);
      html += '<tr class="row" data-action="toggle-expand" data-id="' + r.id + '" aria-expanded="' + isOpen + '">';
      html += '<td class="num">' + (r.code ? escapeHtml(r.code) : '—') + '</td>';
      html += '<td class="brand-cell"><span class="chevron">▶</span> ' + (cfg.hasLogo && r.logoUrl ? '<img class="brand-thumb" src="' + escapeHtml(r.logoUrl) + '" alt="">' : '') + '<span class="brand-name">' + escapeHtml(r.brand) + '</span></td>';
      if (showClient) html += '<td>' + escapeHtml(client ? client.name : '—') + '</td>';
      html += '<td class="num">' + (r.cls != null && r.cls !== '' ? escapeHtml(r.cls) : '—') + '</td>';
      html += '<td class="num">' + escapeHtml(r.appno) + '</td>';
      if (cfg.markTypeMode !== 'hidden') html += '<td>' + escapeHtml(r.markType) + '</td>';
      html += '<td>' + renderStatusSelect(r) + '</td>';
      if (cfg.hasRenewal) html += '<td class="num">' + (fmtDate(r.renewDate) || '—') + '</td>';
      if (userCan('edit_matter')) {
        html += '<td>' + (r.assignedTo ? escapeHtml(r.assignedTo) : '<span class="unassigned">Unassigned</span>') + '</td>';
      }
      if (userCan('view_financials')) {
        html += '<td>' + (r.paymentStatus ? '<span class="pay-pill pay-' +
          escapeHtml(String(r.paymentStatus).toLowerCase().replace(/[^a-z]+/g, '-')) + '">' +
          escapeHtml(r.paymentStatus) + '</span>' : '—') + '</td>';
      }
      html += '<td class="row-actions">' +
        '<button class="btn-ghost" data-action="open-edit" data-id="' + r.id + '" title="' +
        (userCan('edit_matter') ? 'Edit' : 'Update status / deadline') + '"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg></button>' +
        '</td>';
      html += '</tr>';
      if (isOpen) {
        html += '<tr class="detail-row"><td colspan="' + colCount + '"><div class="detail-grid">' +
          '<div class="detail-block"><h4>' + escapeHtml(cfg.descLabel) + '</h4><p>' + escapeHtml(r.desc || '—') + '</p></div>' +
          '<div class="detail-block"><h4>' + escapeHtml(sd.label) + ' — next step</h4><p>' + escapeHtml(r.action || sd.suggestedAction || '—') +
          (r.actionDate ? '\n\nDeadline: ' + fmtDate(r.actionDate) : '') + '</p></div>' +
          '<div class="detail-block"><h4>Applicant(s)</h4>' + (r.applicants && r.applicants.length ? personSummaryLines(r.applicants, true) : '<p>—</p>') + '</div>' +
          (cfg.hasAuthors && r.authors && r.authors.length ? '<div class="detail-block"><h4>Author(s)</h4>' + personSummaryLines(r.authors, false) + '</div>' : '') +
          (cfg.hasContributors && r.contributors && r.contributors.length ? '<div class="detail-block"><h4>Internal Contributor(s) / Researcher(s)</h4>' + contributorSummaryLines(r.contributors) + '</div>' : '') +
          (cfg.hasLogo && r.logoUrl ? '<div class="detail-block"><h4>Logo</h4><img class="detail-logo-img" src="' + escapeHtml(r.logoUrl) + '" alt=""></div>' : '') +
          (userCan('edit_matter') ? '<div class="detail-block"><h4>Assigned to</h4><p>' +
            (r.assignedTo ? escapeHtml(r.assignedTo) : '<span class="unassigned">Unassigned</span>') + '</p></div>' : '') +
          (userCan('view_financials') ? renderFinancialBlock(r) : '') +
          renderRecordTimeline(r) +
          '</div></td></tr>';
      }
    });
    html += '</tbody></table></div>';
    html += renderPager('ledger', pageInfo);
    html += '</div>';
    return html;
  }

  function renderRecordTimeline(r) {
    var timeline = (r && r.timeline && Array.isArray(r.timeline)) ? r.timeline : [];
    var count = timeline.length;
    var html = '<div class="detail-block timeline-block span-2">';
    html += '<div class="timeline-block-head">';
    html += '<div class="timeline-title-wrap">';
    html += '<h4>Audit History / Stage Timeline</h4>';
    html += '<span class="timeline-badge">' + count + ' transition' + (count === 1 ? '' : 's') + '</span>';
    html += '</div>';
    html += '</div>';

    if (!timeline.length) {
      html += '<div class="timeline-empty"><span style="font-size:16px;">⏳</span> No stage transitions recorded yet for this matter. When this matter advances in status, transition dates and remarks will be tracked here.</div>';
      html += '</div>';
      return html;
    }

    html += '<div class="timeline-track">';
    timeline.forEach(function (entry) {
      var fromSd = statusDef(entry.fromStatus);
      var toSd = statusDef(entry.toStatus);
      var markerTier = toSd.tier || 'info';
      html += '<div class="timeline-item">';
      html += '<div class="timeline-marker tier-' + markerTier + '"></div>';
      html += '<div class="timeline-card">';

      html += '<div class="timeline-card-header">';
      html += '<div class="timeline-transition">';
      html += '<span class="badge tier-' + fromSd.tier + '"><span class="dot"></span>' + escapeHtml(entry.fromStatusLabel || fromSd.label) + '</span>';
      html += '<span class="timeline-arrow">➔</span>';
      html += '<span class="badge tier-' + toSd.tier + '"><span class="dot"></span>' + escapeHtml(entry.toStatusLabel || toSd.label) + '</span>';
      html += '</div>';
      html += '<div class="timeline-meta mono" title="Recorded at ' + escapeHtml(entry.timestamp || '') + '">';
      html += '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle;margin-right:4px;"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>';
      html += escapeHtml(fmtDateTime(entry.timestamp));
      html += '</div>';
      html += '</div>';

      html += '<div class="timeline-dates">';
      html += '<span class="timeline-date-chip"><strong>Effective:</strong> ' + (fmtDate(entry.effectiveDate) || escapeHtml(entry.effectiveDate) || '—') + '</span>';
      if (entry.deadline) {
        html += '<span class="timeline-date-chip deadline-chip"><strong>Deadline:</strong> ' + (fmtDate(entry.deadline) || escapeHtml(entry.deadline)) + '</span>';
      }
      html += '</div>';

      if (entry.remarks) {
        html += '<div class="timeline-remarks">' + escapeHtml(entry.remarks) + '</div>';
      }

      html += '</div>';
      html += '</div>';
    });
    html += '</div>';
    html += '</div>';
    return html;
  }

  function renderStatusSelect(r) {
    var sd = statusDef(r.status);
    var html = '<select class="status-select tier-' + sd.tier + '" data-action="change-status" data-id="' + r.id + '">';
    statusDefsForType(r.ipType).forEach(function (s) {
      html += '<option value="' + s.key + '"' + (s.key === r.status ? ' selected' : '') + '>' + s.label + '</option>';
    });
    html += '</select>';
    return html;
  }

  function renderLedgerRail(records, ipType) {
    var cfg = ipConfig(ipType);
    var deadlines = computeDeadlines(view.clientId, ipType).slice(0, 6);
    var html = '<aside class="rail">';
    html += '<div class="card rail-card"><h3>Upcoming deadlines</h3><p class="rail-sub">This client, soonest first</p>';
    if (!deadlines.length) {
      html += '<p class="rail-sub" style="margin:0;">No dated deadlines on record yet.</p>';
    }
    deadlines.forEach(function (dl) {
      html += '<div class="renewal-item"><div><div class="r-name">' + escapeHtml(dl.record.brand) + '</div>' +
        '<div class="r-meta">' + (dl.kind === 'renewal' ? 'Renewal' : 'Action due') + ' &middot; ' + escapeHtml(cfg.clsLabel) + ' ' + (dl.record.cls || '—') + '</div></div>' +
        '<div class="r-when"><div class="r-date">' + fmtDate(dl.date) + '</div><div class="r-count">' + humanCountdown(daysUntil(dl.date)) + '</div></div></div>';
    });
    var allCount = computeDeadlines(view.clientId, ipType).length;
    if (allCount > deadlines.length) {
      html += '<div class="renewal-more">+' + (allCount - deadlines.length) + ' more &mdash; see Deadlines tab</div>';
    }
    html += '</div>';

    html += '<div class="card rail-card"><h3>Status breakdown</h3><p class="rail-sub">' + records.length + ' applications by current status</p>';
    var counts = {};
    records.forEach(function (r) { counts[r.status] = (counts[r.status] || 0) + 1; });
    var order = statusDefsForType(ipType).slice().sort(function (a, b) { return (counts[b.key] || 0) - (counts[a.key] || 0); });
    var max = Math.max.apply(null, order.map(function (s) { return counts[s.key] || 0; }).concat([1]));
    order.forEach(function (s) {
      var n = counts[s.key] || 0;
      if (!n) return;
      html += '<div class="bar-row"><div class="bar-label"><span class="bl-name">' + s.label + '</span><span class="bl-val">' + n + '</span></div>' +
        '<div class="bar-track"><div class="bar-fill" style="width:' + (n / max * 100) + '%; background:var(' + TIER_VAR[s.tier] + ')"></div></div></div>';
    });
    html += '</div></aside>';
    return html;
  }

  /* ===================== Deadlines view ===================== */
  function renderDeadlinesView() {
    var needs = computeNeedsDeadline(view.deadlineClientFilter);
    var items = computeDeadlines(view.deadlineClientFilter);
    var overdue = items.filter(function (i) { return daysUntil(i.date) < 0; });
    var soon = items.filter(function (i) { var d = daysUntil(i.date); return d >= 0 && d <= 45; });
    var upcoming = items.filter(function (i) { return daysUntil(i.date) > 45; });

    var html = '<div class="deadlines-wrap">';
    html += '<div class="chip-row">';
    html += '<button class="chip" data-action="set-deadline-client" data-client="__all__" aria-pressed="' + (view.deadlineClientFilter === '__all__') + '">All clients</button>';
    state.clients.forEach(function (c) {
      html += '<button class="chip" data-action="set-deadline-client" data-client="' + escapeHtml(c.id) + '" aria-pressed="' + (view.deadlineClientFilter === c.id) + '">' + escapeHtml(c.name.split(' ')[0]) + '</button>';
    });
    html += '</div>';

    if (needs.length) {
      html += '<div class="cta-banner"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex:none;color:var(--warning)"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>' +
        '<p><strong>' + needs.length + ' matter' + (needs.length === 1 ? '' : 's') + '</strong> ' + (needs.length === 1 ? 'is' : 'are') + ' objected or opposed with no deadline logged yet. Add a date so it shows up here.</p>' +
        '<button class="btn btn-secondary" data-action="scroll-needs">Review</button></div>';
    }

    html += renderDeadlineSection('Overdue', overdue, 'overdue');
    html += renderDeadlineSection('Due within 45 days', soon, 'soon');
    // Overdue/Soon stay fully visible (short worklists by design) — only Upcoming is paginated,
    // since it is the bucket most likely to grow long once all three ipTypes are mixed together.
    html += renderDeadlineSection('Upcoming', upcoming, 'upcoming', 'deadlines-upcoming');

    if (needs.length) {
      html += '<div class="deadline-section" id="needs-deadline-section"><h2>Needs a deadline added <span class="sec-count">' + needs.length + '</span></h2><div class="deadline-list">';
      needs.forEach(function (r) {
        var client = clientById(r.clientId);
        var sd = statusDef(r.status);
        var rcfg = ipConfig(r.ipType);
        html += '<div class="deadline-item"><div class="deadline-stripe" style="background:var(' + TIER_VAR[sd.tier] + ')"></div>' +
          '<div class="deadline-main"><div class="d-title"><span class="client-tag">' + escapeHtml(client ? client.name.split(' ')[0] : '') + '</span> ' +
          '<span class="client-tag" style="color:var(--ink-secondary);background:var(--surface-2);">' + escapeHtml(rcfg.label) + '</span> ' + escapeHtml(r.brand) + '</div>' +
          '<div class="d-meta">' + escapeHtml(rcfg.clsLabel) + ' ' + (r.cls || '—') + ' &middot; ' + escapeHtml(r.appno) + ' &middot; ' + sd.label + '</div></div>' +
          '<button class="btn btn-secondary" data-action="open-edit" data-id="' + r.id + '">Add deadline</button></div>';
      });
      html += '</div></div>';
    }

    if (!items.length && !needs.length) {
      html += '<div class="empty-state">No deadlines logged yet. Add applications with renewal or action dates to see them here.</div>';
    }
    html += '</div>';
    return html;
  }

  function renderDeadlineSection(title, items, tone, pagerScope) {
    if (!items.length) return '';
    var list = items, pageInfo = null;
    if (pagerScope) {
      pageInfo = paginate(items, view[pagerPageKey(pagerScope)], getPageSize());
      view[pagerPageKey(pagerScope)] = pageInfo.page;
      list = pageInfo.pageItems;
    }
    var html = '<div class="deadline-section"><h2>' + title + ' <span class="sec-count">' + items.length + '</span></h2><div class="deadline-list">';
    list.forEach(function (dl) {
      var sd = statusDef(dl.record.status);
      var rcfg = ipConfig(dl.record.ipType);
      var days = daysUntil(dl.date);
      var isOverdue = days < 0;
      html += '<div class="deadline-item' + (isOverdue ? ' is-overdue' : '') + '">' +
        '<div class="deadline-stripe" style="background:var(' + (isOverdue ? '--critical' : TIER_VAR[sd.tier]) + ')"></div>' +
        '<div class="deadline-main"><div class="d-title"><span class="client-tag">' + escapeHtml(dl.client ? dl.client.name.split(' ')[0] : '') + '</span> ' +
        '<span class="client-tag" style="color:var(--ink-secondary);background:var(--surface-2);">' + escapeHtml(rcfg.label) + '</span> ' + escapeHtml(dl.record.brand) + '</div>' +
        '<div class="d-meta">' + escapeHtml(rcfg.clsLabel) + ' ' + (dl.record.cls || '—') + ' &middot; ' + escapeHtml(dl.record.appno) + ' &middot; ' + sd.label + '</div>' +
        '<div class="d-what">' + (dl.kind === 'renewal' ? 'Renewal due' : escapeHtml(dl.label)) + '</div></div>' +
        '<div class="deadline-when"><div class="d-date">' + fmtDate(dl.date) + '</div><div class="d-count" style="color:var(' + (isOverdue ? '--critical' : '--accent') + ')">' + humanCountdown(days) + '</div></div>' +
        '<button class="btn-ghost" data-action="open-edit" data-id="' + dl.record.id + '" title="Open"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg></button>' +
        '</div>';
    });
    html += '</div>';
    if (pagerScope) html += renderPager(pagerScope, pageInfo);
    html += '</div>';
    return html;
  }

  /* ===================== Log view ===================== */
  function relativeTime(iso) {
    var d = new Date(iso);
    var diffMin = Math.round((Date.now() - d.getTime()) / 60000);
    if (diffMin < 1) return 'just now';
    if (diffMin < 60) return diffMin + 'm ago';
    var diffH = Math.round(diffMin / 60);
    if (diffH < 24) return diffH + 'h ago';
    var diffD = Math.round(diffH / 24);
    if (diffD < 30) return diffD + 'd ago';
    return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
  }
  function absoluteTime(iso) {
    var d = new Date(iso);
    return d.toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  function renderLogView() {
    var entries = (state.log || []);
    var html = '<div class="card rail-card" style="padding:8px 4px;">';
    if (!entries.length) {
      html += '<div class="empty-state">No changes logged yet. Every add, edit, status change and import will show up here.</div>';
    } else {
      var pageInfo = paginate(entries, view.logPage, getPageSize());
      view.logPage = pageInfo.page;
      html += '<div class="log-list">';
      pageInfo.pageItems.forEach(function (e) {
        html += '<div class="log-item"><div class="log-dot"></div><div class="log-body"><div class="log-summary">' + escapeHtml(e.summary) + '</div>' +
          '<div class="log-time" title="' + escapeHtml(absoluteTime(e.ts)) + '">' + escapeHtml(relativeTime(e.ts)) + '</div></div></div>';
      });
      html += '</div>';
      html += renderPager('log', pageInfo);
    }
    html += '</div>';
    return html;
  }

  /* ===================== Settings view ===================== */
  function settingsRadio(name, value, isChecked, title, sub) {
    return '<label class="radio-tile' + (isChecked ? ' active' : '') + '"><input type="radio" name="' + name + '" value="' + value + '" data-action="' + name + '"' + (isChecked ? ' checked' : '') + '>' +
      '<span><strong>' + escapeHtml(title) + '</strong>' + (sub ? '<small>' + escapeHtml(sub) + '</small>' : '') + '</span></label>';
  }
  /* ===================== Your account ===================== */
  var pwState = { current: '', next: '', confirm: '', error: '', busy: false };

  function renderAccountCard() {
    if (!currentUser) return '';
    var html = '<div class="card settings-card"><h3>Your account</h3>';
    html += '<p class="settings-desc">Signed in as <strong>' + escapeHtml(currentUser.username) +
      '</strong> (' + escapeHtml(currentUser.roleLabel) + ').</p>';
    if (pwState.error) {
      html += '<p class="settings-note" style="color:var(--critical);">' + escapeHtml(pwState.error) + '</p>';
    }
    html += '<div class="field"><label>Current password</label>' +
      passwordField('pw-current', pwState.current, ' data-pwfield="current" autocomplete="current-password"', 'Current password') + '</div>';
    html += '<div class="field"><label>New password</label>' +
      passwordField('pw-next', pwState.next, ' data-pwfield="next" autocomplete="new-password"', 'At least 8 characters') + '</div>';
    html += '<div class="field"><label>Confirm new password</label>' +
      passwordField('pw-confirm', pwState.confirm, ' data-pwfield="confirm" autocomplete="new-password"', 'Repeat the new password') + '</div>';
    html += '<button class="btn btn-primary" data-action="change-password"' + (pwState.busy ? ' disabled' : '') + '>' +
      (pwState.busy ? 'Changing…' : 'Change password') + '</button>';
    html += '<p class="settings-note" style="margin-top:10px;">Changing your password signs out every other device.</p>';
    html += '</div>';
    return html;
  }

  async function submitPasswordChange() {
    pwState.error = '';
    if (!pwState.current || !pwState.next) {
      pwState.error = 'Enter your current password and a new one.';
      renderAll(); return;
    }
    if (pwState.next.length < 8) {
      pwState.error = 'The new password must be at least 8 characters.';
      renderAll(); return;
    }
    if (pwState.next !== pwState.confirm) {
      pwState.error = 'The two new passwords do not match.';
      renderAll(); return;
    }
    pwState.busy = true; renderAll();
    var res = await apiPost('/api/password', {
      currentPassword: pwState.current, newPassword: pwState.next
    });
    pwState.busy = false;
    if (!res.ok) {
      pwState.error = (res.data && res.data.error) || 'Could not change your password.';
      renderAll(); return;
    }
    pwState = { current: '', next: '', confirm: '', error: '', busy: false };
    toast('Password changed. Other devices have been signed out.');
    renderAll();
  }

  /* ===================== User management (superadmin only) ===================== */
  // Populated by loadUsers(); null until the list has been fetched.
  var usersState = { list: null, roles: [], error: '', busy: false,
                     draft: { username: '', password: '', role: 'drafter' } };

  async function loadUsers() {
    if (!userCan('manage_users')) return;
    try {
      var res = await fetch('/api/users', { credentials: 'same-origin' });
      if (!res.ok) { usersState.list = []; return; }
      var data = await res.json();
      usersState.list = data.users || [];
      usersState.roles = data.roles || [];
    } catch (e) {
      usersState.list = [];
    }
    if (view.mode === 'settings') renderAll();
  }

  async function submitNewUser() {
    var d = usersState.draft;
    usersState.error = '';
    if (!d.username.trim() || !d.password) {
      usersState.error = 'Enter a username and a password.';
      renderAll();
      return;
    }
    if (d.password.length < 8) {
      usersState.error = 'Password must be at least 8 characters.';
      renderAll();
      return;
    }
    usersState.busy = true;
    renderAll();
    var res = await apiPost('/api/users', {
      username: d.username.trim(), password: d.password, role: d.role
    });
    usersState.busy = false;
    if (!res.ok) {
      usersState.error = (res.data && res.data.error) || 'Could not create that account.';
      renderAll();
      return;
    }
    toast('Created ' + d.username.trim() + '.');
    usersState.draft = { username: '', password: '', role: 'drafter' };
    await loadUsers();
    renderAll();
  }

  async function setUserActive(userId, makeActive) {
    var res = await fetch('/api/users/' + encodeURIComponent(userId), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ active: !!makeActive })
    });
    if (!res.ok) {
      var data = null;
      try { data = await res.json(); } catch (e) { /* no body */ }
      toast((data && data.error) || 'Could not update that account.');
      return;
    }
    await loadUsers();
    await loadAssignees();
    renderAll();
  }

  async function deleteUser(userId) {
    var res = await fetch('/api/users/' + encodeURIComponent(userId), {
      method: 'DELETE', credentials: 'same-origin'
    });
    if (!res.ok) {
      var data = null;
      try { data = await res.json(); } catch (e) { /* no body */ }
      toast((data && data.error) || 'Could not delete that account.');
      return;
    }
    await loadUsers();
    renderAll();
  }

  function renderUsersCard() {
    if (!userCan('manage_users')) return '';
    var html = '<div class="card settings-card"><h3>People and access</h3>';
    html += '<p class="settings-desc">Accounts are stored on the server and each one has a role. ' +
      'A <strong>trademark admin</strong> sees every matter but no financial figures. ' +
      'A <strong>drafter</strong> sees only matters assigned to them, no financials, ' +
      'and can move a matter through its stages but not create or edit one.</p>';

    if (usersState.list === null) {
      html += '<p class="settings-status">Loading accounts&hellip;</p></div>';
      return html;
    }

    html += '<table class="user-table"><thead><tr><th>Username</th><th>Role</th><th></th></tr></thead><tbody>';
    usersState.list.forEach(function (u) {
      var isSelf = currentUser && u.username.toLowerCase() === currentUser.username.toLowerCase();
      html += '<tr' + (u.active ? '' : ' class="user-suspended"') + '><td><strong>' +
        escapeHtml(u.username) + '</strong>' +
        (isSelf ? ' <span class="hint">(you)</span>' : '') +
        (u.active ? '' : ' <span class="hint">suspended</span>') + '</td>' +
        '<td><span class="user-role-pill">' + escapeHtml(roleLabelFor(u.role)) + '</span></td>' +
        '<td style="text-align:right;white-space:nowrap;">' +
        (isSelf ? '' :
          '<button class="btn-ghost" data-action="user-suspend" data-userid="' +
            escapeHtml(String(u.id)) + '" data-active="' + (u.active ? '0' : '1') + '" title="' +
            (u.active ? 'Suspend this account (ends its sessions)' : 'Restore access') + '">' +
            (u.active ? 'Suspend' : 'Restore') + '</button>' +
          '<button class="btn-ghost" data-action="user-delete" data-userid="' +
            escapeHtml(String(u.id)) + '" title="Remove account">Remove</button>') +
        '</td></tr>';
    });
    html += '</tbody></table>';

    if (usersState.error) {
      html += '<p class="settings-note" style="color:var(--critical);">' + escapeHtml(usersState.error) + '</p>';
    }

    html += '<div class="user-add-row">';
    html += '<div class="field"><label>New username</label><input type="text" data-userfield="username" ' +
      'autocapitalize="none" spellcheck="false" value="' + escapeHtml(usersState.draft.username) + '"></div>';
    html += '<div class="field"><label>Password</label>' +
      passwordField('new-user-pass', usersState.draft.password, ' data-userfield="password" autocomplete="new-password"', 'At least 8 characters') +
      '</div>';
    html += '<div class="field"><label>Role</label><select data-userfield="role">';
    (usersState.roles.length ? usersState.roles : [{ value: 'drafter', label: 'Drafter' }]).forEach(function (r) {
      html += '<option value="' + escapeHtml(r.value) + '"' +
        (usersState.draft.role === r.value ? ' selected' : '') + '>' + escapeHtml(r.label) + '</option>';
    });
    html += '</select></div>';
    html += '<button class="btn btn-primary" data-action="user-add"' + (usersState.busy ? ' disabled' : '') + '>' +
      (usersState.busy ? 'Adding…' : 'Add') + '</button>';
    html += '</div>';

    html += '<p class="settings-note" style="margin-top:10px;">Forgotten passwords are reset from the ' +
      'command line: <code>py -m backend.manage passwd &lt;username&gt;</code> — only the hash is stored, ' +
      'so no one can read an existing password back.</p>';
    html += '</div>';
    return html;
  }

  function roleLabelFor(role) {
    var found = null;
    (usersState.roles || []).forEach(function (r) { if (r.value === role) found = r.label; });
    return found || role;
  }

  function renderBackendSettingsCard() {
    if (PERSIST_TIER === 'claude') {
      // The Claude artifact tier has its own sharing model (Claude's share
      // menu); a competing "shared backend" control here would only confuse
      // which one is in effect.
      return '';
    }
    var html = '<div class="card settings-card"><h3>Where this data is stored</h3>';
    if (PERSIST_TIER === 'backend') {
      html += '<p class="settings-desc">This ledger is saved on the server you signed in to. ' +
        'Everyone with an account sees the same live data, and what each person can see ' +
        'is decided by their role.</p>';
      html += '<p class="settings-status">Status: <strong>Connected</strong></p>';
    } else {
      html += '<p class="settings-desc">No server is answering, so this ledger is saved in ' +
        'this browser only — other people and other devices will not see it. Start the ' +
        'FastAPI backend and open the app from it to share the ledger.</p>';
      html += '<p class="settings-status">Status: <strong>This browser only</strong></p>';
    }
    html += '<p class="settings-note" style="margin-top:12px;">Currently saving to: <strong>' +
      escapeHtml(tierLabel()) + '</strong></p>';
    html += '</div>';
    return html;
  }
  function renderSettingsView() {
    var theme = getLocalPref(LOCAL_KEYS.theme, 'system');
    var notifyOn = getLocalPref(LOCAL_KEYS.notify, 'off') === 'on';
    var notifSupported = typeof Notification !== 'undefined';
    var loginOn = !!(state.settings && state.settings.loginEnabled && state.settings.loginHash);

    var html = '<div class="settings-grid">';

    html += '<div class="card settings-card"><h3>Appearance</h3>' +
      '<p class="settings-desc">Choose how the ledger looks on this device. This only changes your own browser.</p>';
    html += '<div class="radio-stack">';
    html += settingsRadio('theme-radio', 'system', theme === 'system', 'Match system', 'Follow this device\'s light/dark setting');
    html += settingsRadio('theme-radio', 'light', theme === 'light', 'Light', '');
    html += settingsRadio('theme-radio', 'dark', theme === 'dark', 'Dark', '');
    html += '</div></div>';

    html += '<div class="card settings-card"><h3>Rows per page</h3>' +
      '<p class="settings-desc">How many rows to show per page in the ledger table, the log and the Deadlines "Upcoming" list. This only changes your own browser.</p>';
    html += '<div class="radio-stack">';
    [10, 20, 50, 100].forEach(function (n) {
      html += settingsRadio('pagesize-radio', String(n), getPageSize() === n, n + ' per page', '');
    });
    html += '</div></div>';

    html += '<div class="card settings-card"><h3>Deadline alerts</h3>' +
      '<p class="settings-desc">Get a desktop notification for filings due within 45 days when you open the dashboard. Checked once a day, on this device only.</p>';
    if (!notifSupported) {
      html += '<p class="settings-note">Desktop notifications aren\'t available in this preview window.</p>';
    } else {
      html += '<label class="switch-row"><span>Desktop alerts for upcoming deadlines</span><span class="switch"><input type="checkbox" data-action="notify-toggle"' + (notifyOn ? ' checked' : '') + '><span class="switch-track"></span></span></label>';
      if (Notification.permission === 'denied') {
        html += '<p class="settings-note">Notifications are blocked for this page in your browser\'s site settings — allow them there, then turn this back on.</p>';
      }
    }
    html += '</div>';

    html += '<div class="card settings-card"><h3>Login passphrase</h3>';
    html += '<p class="settings-desc">A passphrase screen anyone must clear before seeing this dashboard. <strong>This is a light deterrent, not real security</strong> — the page and its data can still be read by anyone with the link who opens their browser\'s developer tools. For actual access control, keep this artifact private and share the link only with your team from Claude\'s share menu.</p>';
    html += '<p class="settings-status">Status: <strong>' + (loginOn ? 'On' : 'Off') + '</strong></p>';
    if (settingsDraft.editingLogin) {
      html += '<div class="field"><label>New passphrase</label>' + passwordField('settings-new-pass', settingsDraft.newPass, ' data-settings-field="newPass" autocomplete="new-password"', '') + '</div>';
      html += '<div class="field"><label>Confirm passphrase</label>' + passwordField('settings-confirm-pass', settingsDraft.confirmPass, ' data-settings-field="confirmPass" autocomplete="new-password"', '') + '</div>';
      if (settingsDraft.error) html += '<p class="settings-note" style="color:var(--critical);">' + escapeHtml(settingsDraft.error) + '</p>';
      html += '<div style="display:flex;gap:8px;"><button class="btn btn-secondary" data-action="login-cancel">Cancel</button>' +
        '<button class="btn btn-primary" data-action="login-save">' + (loginOn ? 'Update passphrase' : 'Turn on & save') + '</button></div>';
    } else {
      html += '<div style="display:flex;gap:8px;flex-wrap:wrap;">';
      html += '<button class="btn btn-secondary" data-action="login-edit">' + (loginOn ? 'Change passphrase' : 'Turn on passphrase login') + '</button>';
      if (loginOn) html += '<button class="btn btn-danger" data-action="login-disable">Turn off</button>';
      html += '</div>';
      if (loginOn) html += '<button class="btn-ghost" style="margin-top:10px;padding-left:0;" data-action="lock-now">Lock this device now</button>';
    }
    html += '</div>';

    var lockRefreshOn = shouldLockOnRefresh();
    html += '<div class="card settings-card"><h3>Security & Session Lock</h3>' +
      '<p class="settings-desc">Control whether this dashboard locks automatically when refreshed or closed, asking you to sign in again each time.</p>';
    html += '<label class="switch-row"><span>Auto-lock on page refresh / reload</span><span class="switch"><input type="checkbox" data-action="lock-refresh-toggle"' + (lockRefreshOn ? ' checked' : '') + '><span class="switch-track"></span></span></label>';
    html += '<p class="settings-note">When enabled, nothing that unlocks the dashboard is remembered between page loads.</p>';
    html += '<div style="margin-top:12px;"><button class="btn btn-secondary" data-action="lock-now"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:4px;"><rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>Lock session now</button></div>';
    html += renderAccountCard();
    html += renderUsersCard();
    html += renderBackendSettingsCard();

    html += '<div class="card settings-card"><h3>Data Management & Clean Up</h3>' +
      '<p class="settings-desc">Manage the stored applications and clients in your ledger database.</p>' +
      '<p class="settings-status">Current records: <strong>' + state.records.length + ' matters</strong> &middot; <strong>' + state.clients.length + ' clients</strong></p>' +
      '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:12px;">' +
      '<button class="btn btn-secondary" data-action="deduplicate-records"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:4px;"><path d="M20 6L9 17l-5-5"/></svg>Clean up duplicate records</button>' +
      '<button class="btn btn-danger" data-action="clear-all-records"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:4px;"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>Clear all matters</button>' +
      '</div>' +
      '<p class="settings-note">Use "Clean up duplicate records" to collapse identical duplicate entries into single matters, or "Clear all matters" if you wish to reset and re-import a clean CSV file.</p>' +
      '</div>';

    html += '</div>';
    return html;
  }

  /* ===================== Modal: add/edit/import ===================== */
  // Fields a role may not change are rendered disabled rather than merely
  // ignored on save. The server discards them either way (backend/roles.py),
  // but an editable-looking box plus an optimistic re-render made a drafter's
  // rejected edit appear to have been saved until the next reload.
  function lockedAttr(field) {
    if (userCan('edit_matter')) return '';
    return DRAFTER_EDITABLE_UI_FIELDS.indexOf(field) === -1 ? ' disabled' : '';
  }
  var DRAFTER_EDITABLE_UI_FIELDS = ['status', 'actionDate', 'action'];

  /* ===================== Assignees ===================== */
  // Who a matter may be assigned to. Fetched from the server rather than typed,
  // because a typo in a free-text username silently hides the matter from every
  // drafter, with no warning anywhere. null means "not loaded yet".
  var assignees = null;

  async function loadAssignees() {
    if (PERSIST_TIER !== 'backend' || !userCan('edit_matter')) return;
    try {
      var res = await fetch('/api/assignees', { credentials: 'same-origin' });
      if (!res.ok) { assignees = []; return; }
      var data = await res.json();
      assignees = data.assignees || [];
    } catch (e) {
      assignees = [];
    }
  }

  function blankDraft() {
    var cfg = ipConfig(view.ipType);
    return { id: null, clientId: view.clientId === '__all__' ? ((state.clients[0] && state.clients[0].id) || null) : view.clientId,
      ipType: view.ipType, code: '', brand: '', cls: cfg.clsMode === 'select' ? (cfg.clsOptions[0] || '') : '', appno: '',
      markType: cfg.markTypeMode === 'select' ? MARK_TYPES[0] : '', status: statusDefsForType(view.ipType)[0].key, desc: '', action: '',
      actionDate: '', renewDate: '', newClientName: '', applicants: [], authors: [], contributors: [], logoUrl: '', timeline: [],
      assignedTo: '', officialFee: '', professionalFee: '', amountPaid: '', paymentStatus: PAYMENT_STATUSES[0], invoiceRef: '' };
  }

  function openAddModal() {
    modalState = { mode: 'add', draft: blankDraft(), errors: {}, autoFilled: {}, parseNotice: null };
    renderModal();
  }
  function openEditModal(id) {
    var r = recordById(id);
    if (!r) return;
    modalState = {
      mode: 'edit',
      initialStatus: r.status,
      stageEffectiveDate: todayIso(),
      stageDeadline: calculateSuggestedDeadline(r.ipType, r.status),
      stageRemarks: '',
      draft: JSON.parse(JSON.stringify(r)),
      errors: {},
      autoFilled: {},
      parseNotice: null
    };
    modalState.draft.newClientName = '';
    if (!modalState.draft.applicants) modalState.draft.applicants = [];
    if (!modalState.draft.authors) modalState.draft.authors = [];
    if (!modalState.draft.contributors) modalState.draft.contributors = [];
    if (!modalState.draft.logoUrl) modalState.draft.logoUrl = '';
    if (!modalState.draft.timeline) modalState.draft.timeline = [];
    renderModal();
  }
  function openStageTransitionModal(record, newStatus) {
    modalState = {
      mode: 'stage-transition',
      recordId: record.id,
      oldStatus: record.status,
      newStatus: newStatus,
      effectiveDate: todayIso(),
      deadline: calculateSuggestedDeadline(record.ipType, newStatus),
      remarks: '',
      errors: {}
    };
    renderModal();
  }
  function openImportModal() {
    modalState = { mode: 'import', ipType: view.ipType, stage: 'idle', rows: null, fileError: null };
    renderModal();
  }
  function openExportModal() {
    modalState = { mode: 'export', scope: 'filtered', format: 'csv', columns: null, exportFallback: null };
    renderModal();
  }
  function closeModal() {
    modalState = null;
    renderModal();
    renderAll();
  }

  function renderModal() {
    var root = document.getElementById('modal-root');
    if (!modalState) { root.innerHTML = ''; return; }
    if (modalState.mode === 'import') {
      root.innerHTML = renderImportModal();
    } else if (modalState.mode === 'export') {
      root.innerHTML = renderExportModal();
    } else if (modalState.mode === 'stage-transition') {
      root.innerHTML = renderStageTransitionModal();
    } else {
      root.innerHTML = renderFormModal();
    }
  }

  function fieldClass(name) {
    var c = 'field';
    if (modalState.errors[name]) c += ' has-error';
    if (modalState.autoFilled && modalState.autoFilled[name]) c += ' auto-filled';
    return c;
  }

  function personCardField(labelText, inputHtml, spanClass) {
    return '<div class="person-field' + (spanClass ? ' ' + spanClass : '') + '"><label>' + escapeHtml(labelText) + '</label>' + inputHtml + '</div>';
  }
  function genderSelectHtml(dataAttrs, value, disabled) {
    var html = '<select ' + dataAttrs + (disabled ? ' disabled style="opacity:.45"' : '') + '>';
    GENDER_OPTIONS.forEach(function (g) {
      html += '<option value="' + g + '"' + (g === (value || '') ? ' selected' : '') + '>' + (g === '' ? '— Select —' : g) + '</option>';
    });
    html += '</select>';
    return html;
  }
  // Applicants and Authors are structurally similar repeatable-person cards; kept as two render
  // functions (rather than one fully-generic helper) since their field sets genuinely differ
  // (entity type + authorised signatory vs. authors always being individuals) while still sharing
  // the personCardField/genderSelectHtml building blocks and identical visual treatment.
  function renderApplicantCard(a, idx) {
    var isIndividual = (a.entityType || 'Individual') === 'Individual';
    var showAuth = !isIndividual;
    var dAttr = ' data-applicant-idx="' + idx + '"';
    var html = '<div class="person-card" data-applicant-idx="' + idx + '">';
    html += '<div class="person-card-head"><span class="person-card-title">Applicant ' + (idx + 1) + '</span>' +
      '<button type="button" class="btn-ghost" data-action="remove-applicant" data-idx="' + idx + '" title="Remove">✕</button></div>';
    html += '<div class="person-field-grid">';
    html += personCardField('Name', '<input type="text" data-applicant-field="name"' + dAttr + ' value="' + escapeHtml(a.name || '') + '" placeholder="Applicant name">');
    var etHtml = '<select data-applicant-field="entityType"' + dAttr + '>';
    ENTITY_TYPES.forEach(function (t) { etHtml += '<option value="' + t + '"' + (t === a.entityType ? ' selected' : '') + '>' + t + '</option>'; });
    etHtml += '</select>';
    html += personCardField('Entity Type', etHtml);
    html += personCardField('Authorized Signatory', '<input type="text" data-applicant-field="authorizedPerson"' + dAttr + ' value="' + escapeHtml(a.authorizedPerson || '') + '" placeholder="Authorised signatory"' + (showAuth ? '' : ' disabled style="opacity:.45"') + '>');
    html += personCardField('Address / Affiliation', '<textarea data-applicant-field="address"' + dAttr + ' placeholder="Registered / residential address">' + escapeHtml(a.address || '') + '</textarea>', 'span-2');
    html += personCardField('Nationality', '<input type="text" data-applicant-field="nationality"' + dAttr + ' value="' + escapeHtml(a.nationality || '') + '"' + (isIndividual ? '' : ' disabled style="opacity:.45"') + '>');
    html += personCardField('Country of Residence', '<input type="text" data-applicant-field="countryOfResidence"' + dAttr + ' value="' + escapeHtml(a.countryOfResidence || '') + '"' + (isIndividual ? '' : ' disabled style="opacity:.45"') + '>');
    html += personCardField('Gender', genderSelectHtml('data-applicant-field="gender"' + dAttr, a.gender, !isIndividual));
    html += '</div></div>';
    return html;
  }
  function renderAuthorCard(a, idx) {
    var dAttr = ' data-author-idx="' + idx + '"';
    var html = '<div class="person-card" data-author-idx="' + idx + '">';
    html += '<div class="person-card-head"><span class="person-card-title">Author ' + (idx + 1) + '</span>' +
      '<button type="button" class="btn-ghost" data-action="remove-author" data-idx="' + idx + '" title="Remove">✕</button></div>';
    html += '<div class="person-field-grid">';
    html += personCardField('Name', '<input type="text" data-author-field="name"' + dAttr + ' value="' + escapeHtml(a.name || '') + '" placeholder="Author full name">', 'span-2');
    html += personCardField('Institution / Department', '<input type="text" data-author-field="institution"' + dAttr + ' value="' + escapeHtml(a.institution || '') + '" placeholder="e.g. Dept. of Computer Science / University or College">', 'span-2');
    html += personCardField('Address / Affiliation', '<textarea data-author-field="address"' + dAttr + ' placeholder="Residential or institutional address">' + escapeHtml(a.address || '') + '</textarea>', 'span-2');
    html += personCardField('Nationality', '<input type="text" data-author-field="nationality"' + dAttr + ' value="' + escapeHtml(a.nationality || '') + '">');
    html += personCardField('Country of Residence', '<input type="text" data-author-field="countryOfResidence"' + dAttr + ' value="' + escapeHtml(a.countryOfResidence || '') + '">');
    html += personCardField('Gender', genderSelectHtml('data-author-field="gender"' + dAttr, a.gender, false), 'span-2');
    html += '</div></div>';
    return html;
  }

  function renderContributorCard(c, idx) {
    var dAttr = ' data-contributor-idx="' + idx + '"';
    var html = '<div class="person-card" data-contributor-idx="' + idx + '">';
    html += '<div class="person-card-head"><span class="person-card-title">Contributor / Researcher ' + (idx + 1) + '</span>' +
      '<button type="button" class="btn-ghost" data-action="remove-contributor" data-idx="' + idx + '" title="Remove">✕</button></div>';
    html += '<div class="person-field-grid">';
    html += personCardField('Contributor Name', '<input type="text" data-contributor-field="name"' + dAttr + ' value="' + escapeHtml(c.name || '') + '" placeholder="Contributor / Researcher name">', 'span-2');
    html += personCardField('Institution / Department', '<input type="text" data-contributor-field="institution"' + dAttr + ' value="' + escapeHtml(c.institution || '') + '" placeholder="e.g. School of Design / Department of Mechanical Engg">', 'span-2');
    html += personCardField('Affiliation / Employee ID (Optional)', '<input type="text" data-contributor-field="affiliation"' + dAttr + ' value="' + escapeHtml(c.affiliation || '') + '" placeholder="e.g. Lead Researcher / EMP-84920">', 'span-2');
    html += '</div></div>';
    return html;
  }

  // Shared by the ledger detail-expand row for Applicant(s) and Author(s) blocks
  function personSummaryLines(list, isApplicant) {
    return (list || []).map(function (a) {
      var line1 = escapeHtml(a.name || '');
      if (isApplicant) {
        line1 += ' (' + escapeHtml(a.entityType || 'Individual') + ')';
        if (a.authorizedPerson) line1 += ' — authorised: ' + escapeHtml(a.authorizedPerson);
      }
      var parts = [];
      if (a.institution) parts.push('Institution: ' + escapeHtml(a.institution));
      if (a.address) parts.push(escapeHtml(a.address));
      if (a.nationality) parts.push('Nationality: ' + escapeHtml(a.nationality));
      if (a.countryOfResidence) parts.push('Country: ' + escapeHtml(a.countryOfResidence));
      if (a.gender) parts.push(escapeHtml(a.gender));
      var line2 = parts.join(' · ');
      return '<div class="person-summary-item"><p class="person-summary-main">' + line1 + '</p>' +
        (line2 ? '<p class="person-summary-sub">' + line2 + '</p>' : '') + '</div>';
    }).join('');
  }

  function contributorSummaryLines(list) {
    return (list || []).map(function (c) {
      var line1 = escapeHtml(c.name || '');
      var parts = [];
      if (c.institution) parts.push('Dept / Institution: ' + escapeHtml(c.institution));
      if (c.affiliation) parts.push('Affiliation / ID: ' + escapeHtml(c.affiliation));
      var line2 = parts.join(' · ');
      return '<div class="person-summary-item"><p class="person-summary-main">' + line1 + '</p>' +
        (line2 ? '<p class="person-summary-sub">' + line2 + '</p>' : '') + '</div>';
    }).join('');
  }

  /* ===================== Logo / device-mark upload ===================== */
  // Live preview on typed URL changes: a direct DOM tweak (mirrors the password-toggle pattern)
  // rather than a full renderModal(), since re-rendering the whole form on every keystroke would
  // steal focus from the text field the user is typing into.
  function updateLogoPreview(url) {
    var img = document.querySelector('.logo-preview');
    if (!img) return;
    if (url) { img.src = url; img.style.display = ''; }
    else { img.style.display = 'none'; }
  }
  // File upload is comparatively rare (not on every keystroke), so a full renderModal() once the
  // FileReader resolves is simplest and carries none of the "wipe what's typed elsewhere" risk the
  // passphrase-reveal toggle had to work around.
  function handleLogoFile(file) {
    var reader = new FileReader();
    reader.onload = function () {
      downscaleImageDataUri(String(reader.result), 400, 0.82).then(function (uri) {
        if (!modalState || !modalState.draft) return;
        modalState.draft.logoUrl = uri;
        renderModal();
      });
    };
    reader.readAsDataURL(file);
  }
  // Optional polish: keeps very large phone-camera-sized logo photos from bloating the published
  // document — downscales to at most 400px on the longest side as a JPEG. Falls back to the
  // original data URI untouched if canvas access fails for any reason.
  function downscaleImageDataUri(dataUri, maxDim, quality) {
    return new Promise(function (resolve) {
      var img = new Image();
      img.onload = function () {
        var w = img.naturalWidth, h = img.naturalHeight;
        if (!w || !h || (w <= maxDim && h <= maxDim)) { resolve(dataUri); return; }
        var scale = Math.min(maxDim / w, maxDim / h);
        var cw = Math.max(1, Math.round(w * scale)), ch = Math.max(1, Math.round(h * scale));
        try {
          var canvas = document.createElement('canvas');
          canvas.width = cw; canvas.height = ch;
          var ctx = canvas.getContext('2d');
          ctx.drawImage(img, 0, 0, cw, ch);
          resolve(canvas.toDataURL('image/jpeg', quality));
        } catch (e) {
          resolve(dataUri);
        }
      };
      img.onerror = function () { resolve(dataUri); };
      img.src = dataUri;
    });
  }

  function renderFormModal() {
    var d = modalState.draft;
    var cfg = ipConfig(d.ipType || view.ipType);
    var isEdit = modalState.mode === 'edit';
    var html = '<div class="modal-overlay" data-action="overlay-close"><div class="modal" role="dialog" aria-modal="true">';
    html += '<div class="modal-header"><h2>' + (isEdit ? 'Edit ' + cfg.label.toLowerCase() : cfg.addLabel) + '</h2><button class="btn-ghost" data-action="close-modal">✕</button></div>';
    html += '<div class="modal-body">';

    if (modalState.parseNotice) {
      html += '<div class="parse-banner' + (modalState.parseOk ? ' ok' : '') + '"><strong>' + (modalState.parseOk ? 'Parsed — please review' : 'Could not read everything') + '</strong>' + modalState.parseNotice + '</div>';
    }

    html += '<div class="field-grid">';
    html += '<div class="' + fieldClass('clientId') + '"><label>Client</label><select data-field="clientId"' + lockedAttr('clientId') + '>';
    state.clients.forEach(function (c) {
      html += '<option value="' + escapeHtml(c.id) + '"' + (c.id === d.clientId ? ' selected' : '') + '>' + escapeHtml(c.name) + '</option>';
    });
    html += '<option value="__new__"' + (d.clientId === '__new__' ? ' selected' : '') + '>+ New client&hellip;</option>';
    html += '</select></div>';

    html += '<div class="' + fieldClass('code') + '"><label>Code <span class="hint">(internal reference)</span></label><input type="text" data-field="code"' + lockedAttr('code') + ' value="' + escapeHtml(d.code || '') + '" placeholder="e.g. TR123"></div>';

    if (d.clientId === '__new__') {
      html += '<div class="' + fieldClass('newClientName') + ' span-2"><label>New client name</label><input type="text" data-field="newClientName"' + lockedAttr('newClientName') + ' value="' + escapeHtml(d.newClientName || '') + '" placeholder="e.g. Acme Pharmaceuticals Pvt. Ltd.">' +
        (modalState.errors.newClientName ? '<div class="error-msg">' + modalState.errors.newClientName + '</div>' : '') + '</div>';
    }

    html += '<div class="' + fieldClass('brand') + '"><label>' + escapeHtml(cfg.brandLabel) + '</label><input type="text" data-field="brand"' + lockedAttr('brand') + ' value="' + escapeHtml(d.brand) + '">' +
      (modalState.errors.brand ? '<div class="error-msg">' + modalState.errors.brand + '</div>' : '') + '</div>';

    if (cfg.markTypeMode === 'select') {
      html += '<div class="' + fieldClass('markType') + '"><label>' + escapeHtml(cfg.markTypeLabel) + '</label><select data-field="markType"' + lockedAttr('markType') + '>';
      cfg.markTypeOptions.forEach(function (t) { html += '<option value="' + t + '"' + (t === d.markType ? ' selected' : '') + '>' + t + '</option>'; });
      html += '</select></div>';
    } else if (cfg.markTypeMode === 'text') {
      html += '<div class="' + fieldClass('markType') + '"><label>' + escapeHtml(cfg.markTypeLabel) + '</label><input type="text" data-field="markType"' + lockedAttr('markType') + ' value="' + escapeHtml(d.markType || '') + '"></div>';
    }

    if (cfg.clsMode === 'select') {
      html += '<div class="' + fieldClass('cls') + '"><label>' + escapeHtml(cfg.clsLabel) + '</label><select data-field="cls"' + lockedAttr('cls') + '>';
      cfg.clsOptions.forEach(function (t) { html += '<option value="' + escapeHtml(t) + '"' + (t === d.cls ? ' selected' : '') + '>' + escapeHtml(t) + '</option>'; });
      html += '</select></div>';
    } else {
      html += '<div class="' + fieldClass('cls') + '"><label>' + escapeHtml(cfg.clsLabel) + '</label><input type="text" data-field="cls"' + lockedAttr('cls') + ' value="' + escapeHtml(d.cls) + '" placeholder="' + escapeHtml(cfg.clsPlaceholder || '') + '"></div>';
    }
    html += '<div class="' + fieldClass('appno') + '"><label>' + escapeHtml(cfg.appnoLabel) + '</label><input type="text" data-field="appno"' + lockedAttr('appno') + ' value="' + escapeHtml(d.appno) + '">' +
      (modalState.errors.appno ? '<div class="error-msg">' + modalState.errors.appno + '</div>' : '') + '</div>';

    html += '<div class="' + fieldClass('status') + ' span-2"><label>Status</label><select data-field="status">';
    statusDefsForType(d.ipType || view.ipType).forEach(function (s) { html += '<option value="' + s.key + '"' + (s.key === d.status ? ' selected' : '') + '>' + s.label + '</option>'; });
    html += '</select><span class="hint">' + escapeHtml(statusDef(d.status).suggestedAction) + '</span></div>';

    if (modalState.mode === 'edit' && modalState.initialStatus && isForwardTransition(d.ipType, modalState.initialStatus, d.status)) {
      var oldStDef = statusDef(modalState.initialStatus);
      var newStDef = statusDef(d.status);
      html += '<div class="field span-2" style="background:var(--surface-2);border:1px solid var(--border);border-radius:12px;padding:14px 16px;margin-bottom:14px;">';
      html += '<div style="font-size:12.5px;font-weight:700;color:var(--ink);margin-bottom:10px;display:flex;align-items:center;gap:8px;">' +
        '<span class="badge tier-' + oldStDef.tier + '"><span class="dot"></span>' + escapeHtml(oldStDef.label) + '</span> ➔ ' +
        '<span class="badge tier-' + newStDef.tier + '"><span class="dot"></span>' + escapeHtml(newStDef.label) + '</span>' +
        '<span style="font-size:11.5px;font-weight:600;color:var(--accent);margin-left:auto;">⚡ Stage Transition Log</span></div>';
      html += '<div class="field-grid">';
      html += '<div class="field"><label>Stage Effective Date <span style="color:var(--critical);">*</span></label><input type="date" data-field="stageEffectiveDate" value="' + escapeHtml(modalState.stageEffectiveDate || todayIso()) + '"></div>';
      html += '<div class="field"><label>Stage Deadline <span class="hint">' + (newStDef.slaDays ? '(+' + newStDef.slaDays + 'd suggested)' : '') + '</span></label><input type="date" data-field="stageDeadline" value="' + escapeHtml(modalState.stageDeadline || '') + '"></div>';
      html += '</div>';
      html += '<div class="field" style="margin-bottom:0;"><label>Stage Notes / Remarks <span style="color:var(--critical);">*</span></label><textarea data-field="stageRemarks" rows="2" placeholder="Record key events, official notices, or hearing comments...">' + escapeHtml(modalState.stageRemarks || '') + '</textarea></div>';
      html += '</div>';
    }

    html += '<div class="' + fieldClass('desc') + ' span-2"><label>' + escapeHtml(cfg.descLabel) + '</label><textarea data-field="desc"' + lockedAttr('desc') + '>' + escapeHtml(d.desc) + '</textarea></div>';
    html += '<div class="' + fieldClass('action') + ' span-2"><label>Next step / notes</label><textarea data-field="action" placeholder="' + escapeHtml(statusDef(d.status).suggestedAction) + '">' + escapeHtml(d.action) + '</textarea></div>';

    html += '<div class="' + fieldClass('actionDate') + '"><label>Next deadline <span class="hint">(reply / form to file)</span></label><input type="date" data-field="actionDate" value="' + escapeHtml(d.actionDate || '') + '"></div>';
    if (cfg.hasRenewal) {
      html += '<div class="' + fieldClass('renewDate') + '"><label>Renewal date</label><input type="date" data-field="renewDate" value="' + escapeHtml(d.renewDate || '') + '"></div>';
    }

    // Assignment drives what a drafter can see, so only roles that manage
    // matters get to set it.
    if (userCan('edit_matter')) {
      html += '<div class="' + fieldClass('assignedTo') + '"><label>Assigned to</label>';
      if (assignees === null) {
        // The list has not arrived (or there is no backend): fall back to a
        // plain box rather than showing an empty, unusable dropdown.
        html += '<input type="text" data-field="assignedTo" autocapitalize="none" spellcheck="false" value="' +
          escapeHtml(d.assignedTo || '') + '">';
      } else {
        html += '<select data-field="assignedTo">';
        html += '<option value=""' + (!d.assignedTo ? ' selected' : '') + '>Unassigned</option>';
        var seenAssignee = false;
        assignees.forEach(function (a) {
          if (a.username === d.assignedTo) seenAssignee = true;
          html += '<option value="' + escapeHtml(a.username) + '"' +
            (a.username === d.assignedTo ? ' selected' : '') + '>' +
            escapeHtml(a.username) + ' — ' + escapeHtml(a.roleLabel) + '</option>';
        });
        // Keep a name that no longer matches an account, so simply opening a
        // matter never silently reassigns it.
        if (d.assignedTo && !seenAssignee) {
          html += '<option value="' + escapeHtml(d.assignedTo) + '" selected>' +
            escapeHtml(d.assignedTo) + ' — no such account</option>';
        }
        html += '</select>';
      }
      html += '</div>';
    }

    // Financials: rendered only for a role the server actually sends them to.
    if (userCan('view_financials')) {
      var readOnlyFin = !userCan('edit_financials');
      html += '<div class="field span-2" style="margin-top:4px;"><label style="font-weight:700;">Financials</label></div>';
      html += '<div class="' + fieldClass('officialFee') + '"><label>Official / govt. fee</label>' +
        '<input type="text" inputmode="decimal" data-field="officialFee"' + (readOnlyFin ? ' disabled' : '') +
        ' placeholder="e.g. 9000" value="' + escapeHtml(d.officialFee || '') + '"></div>';
      html += '<div class="' + fieldClass('professionalFee') + '"><label>Professional fee</label>' +
        '<input type="text" inputmode="decimal" data-field="professionalFee"' + (readOnlyFin ? ' disabled' : '') +
        ' placeholder="e.g. 15000" value="' + escapeHtml(d.professionalFee || '') + '"></div>';
      html += '<div class="' + fieldClass('amountPaid') + '"><label>Amount received</label>' +
        '<input type="text" inputmode="decimal" data-field="amountPaid"' + (readOnlyFin ? ' disabled' : '') +
        ' placeholder="e.g. 9000" value="' + escapeHtml(d.amountPaid || '') + '"></div>';
      html += '<div class="' + fieldClass('paymentStatus') + '"><label>Payment status</label><select data-field="paymentStatus"' +
        (readOnlyFin ? ' disabled' : '') + '>';
      PAYMENT_STATUSES.forEach(function (ps) {
        html += '<option value="' + escapeHtml(ps) + '"' + ((d.paymentStatus || '') === ps ? ' selected' : '') + '>' + escapeHtml(ps) + '</option>';
      });
      html += '</select></div>';
      html += '<div class="' + fieldClass('invoiceRef') + ' span-2"><label>Invoice reference</label>' +
        '<input type="text" data-field="invoiceRef"' + (readOnlyFin ? ' disabled' : '') +
        ' placeholder="e.g. INV-2026-014" value="' + escapeHtml(d.invoiceRef || '') + '"></div>';
    }

    if (cfg.hasLogo) {
      html += '<div class="field span-2"><label>Logo / device mark <span class="hint">(optional — paste a URL or upload an image)</span></label>';
      html += '<div class="logo-field-row">';
      html += '<input type="text" class="logo-url-input" data-field="logoUrl" placeholder="https://example.com/logo.png" value="' + escapeHtml(d.logoUrl || '') + '">';
      html += '<label class="btn btn-secondary logo-upload-btn" style="cursor:pointer;">Upload<input type="file" accept="image/*" data-action="logo-file-input" style="display:none;"></label>';
      html += '</div>';
      html += '<img class="logo-preview" src="' + escapeHtml(d.logoUrl || '') + '" alt="Logo preview"' + (d.logoUrl ? '' : ' style="display:none;"') + '>';
      html += '</div>';
    }

    html += '<div class="field span-2"><label>Applicant(s) on record</label>';
    html += '<div class="person-cards">';
    (d.applicants || []).forEach(function (a, idx) {
      html += renderApplicantCard(a, idx);
    });
    html += '</div>';
    html += '<button type="button" class="btn btn-secondary" style="margin-top:10px;" data-action="add-applicant">+ Add applicant</button>';
    html += '</div>';

    if (cfg.hasAuthors) {
      html += '<div class="field span-2"><label>Author(s) <span class="hint">(individuals who created the work)</span></label>';
      html += '<div class="person-cards">';
      (d.authors || []).forEach(function (a, idx) {
        html += renderAuthorCard(a, idx);
      });
      html += '</div>';
      html += '<button type="button" class="btn btn-secondary" style="margin-top:10px;" data-action="add-author">+ Add Author</button>';
      html += '</div>';
    }

    if (cfg.hasContributors) {
      html += '<div class="field span-2"><label>Internal Contributors / Researchers <span class="hint">(faculty, employees, or researchers who contributed to the design)</span></label>';
      html += '<div class="person-cards">';
      (d.contributors || []).forEach(function (c, idx) {
        html += renderContributorCard(c, idx);
      });
      html += '</div>';
      html += '<button type="button" class="btn btn-secondary" style="margin-top:10px;" data-action="add-contributor">+ Add Contributor</button>';
      html += '</div>';
    }

    html += '</div></div>';

    html += '<div class="modal-footer">';
    html += (isEdit && userCan('delete_matter')) ? '<button class="btn btn-danger" data-action="delete-record">Delete</button>' : '<span></span>';
    html += '<div class="right-actions"><button class="btn btn-secondary" data-action="close-modal">Cancel</button>' +
      '<button class="btn btn-primary" data-action="save-record">' + (isEdit ? 'Save changes' : 'Add to ledger') + '</button></div>';
    html += '</div></div></div>';
    return html;
  }

  function renderImportModal() {
    var ipType = modalState.ipType || view.ipType;
    var cfg = ipConfig(ipType);
    var typeLabel = cfg.label.toLowerCase();
    var html = '<div class="modal-overlay" data-action="overlay-close"><div class="modal" role="dialog" aria-modal="true">';
    html += '<div class="modal-header"><h2>Import ' + escapeHtml(typeLabel) + 's</h2><button class="btn-ghost" data-action="close-modal">✕</button></div>';
    html += '<div class="modal-body">';

    if (modalState.stage === 'idle') {
      html += '<p style="font-size:13px;color:var(--ink-secondary);margin-top:0;">Bulk-add matters from a spreadsheet. Download the template, fill one row per ' + escapeHtml(typeLabel) + ', then upload it back here as CSV or XLSX.</p>';
      html += '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;">';
      html += '<button class="btn btn-primary" data-action="download-template"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v12m0 0-4-4m4 4 4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>Download CSV template</button>';
      html += '<label class="btn btn-secondary" style="cursor:pointer;">Choose file to upload<input type="file" accept=".csv,.xlsx" data-action="import-file-input" style="display:none;"></label>';
      html += '</div>';
      if (modalState.fileError) html += '<div class="parse-banner"><strong>Could not read that file</strong>' + escapeHtml(modalState.fileError) + '</div>';
      html += '<details class="format-guide"><summary>View template columns as text</summary><pre>' + escapeHtml(importColumnsFor(ipType).join(', ')) + '\n\nOne row per ' + escapeHtml(typeLabel) + '. Dates as DD/MM/YYYY. Leave Applicant 2 columns blank unless there is a joint applicant.</pre></details>';
    } else if (modalState.stage === 'preview') {
      var rows = modalState.rows || [];
      var ok = rows.filter(function (r) { return r.ok; });
      var bad = rows.filter(function (r) { return !r.ok; });
      html += '<div class="parse-banner' + (bad.length ? '' : ' ok') + '"><strong>' + rows.length + ' row' + (rows.length === 1 ? '' : 's') + ' found in ' + escapeHtml(modalState.fileName || 'file') + '</strong>' +
        ok.length + ' ready to import' + (bad.length ? ', ' + bad.length + ' will be skipped (missing required fields)' : '') + '.</div>';
      html += '<div class="table-scroll" style="max-height:280px;border:1px solid var(--border);border-radius:10px;"><table style="min-width:520px;"><thead><tr>' +
        '<th style="width:40px">Row</th><th>' + escapeHtml(cfg.brandLabel) + '</th><th>Client</th><th>Status</th><th>Notes</th></tr></thead><tbody>';
      rows.forEach(function (r) {
        html += '<tr' + (r.ok ? '' : ' style="opacity:.55;"') + '>' +
          '<td class="num">' + r.rowNum + '</td>' +
          '<td>' + escapeHtml(r.draft.brand || '—') + '</td>' +
          '<td>' + escapeHtml(r.draft.clientName || '—') + '</td>' +
          '<td>' + escapeHtml(statusDef(r.draft.status).label) + '</td>' +
          '<td style="font-size:11.5px;color:' + (r.errors.length ? 'var(--critical)' : 'var(--ink-muted)') + ';">' +
          (r.errors.concat(r.warnings).join('; ') || '—') + '</td></tr>';
      });
      html += '</tbody></table></div>';
    }

    html += '</div>';
    html += '<div class="modal-footer">';
    if (modalState.stage === 'preview') {
      var okCount = (modalState.rows || []).filter(function (r) { return r.ok; }).length;
      html += '<button class="btn btn-secondary" data-action="import-back">Back</button>';
      html += '<div class="right-actions"><button class="btn btn-secondary" data-action="close-modal">Cancel</button>' +
        '<button class="btn btn-primary" data-action="import-commit"' + (okCount ? '' : ' disabled') + '>Import ' + okCount + ' row' + (okCount === 1 ? '' : 's') + '</button></div>';
    } else {
      html += '<span></span><div class="right-actions"><button class="btn btn-secondary" data-action="close-modal">Cancel</button></div>';
    }
    html += '</div></div></div>';
    return html;
  }

  function renderStageTransitionModal() {
    var rec = recordById(modalState.recordId);
    if (!rec) return '';
    var client = clientById(rec.clientId);
    var oldSd = statusDef(modalState.oldStatus);
    var newSd = statusDef(modalState.newStatus);
    var errors = modalState.errors || {};

    var html = '<div class="modal-overlay" data-action="overlay-close"><div class="modal" role="dialog" aria-modal="true" style="max-width: 580px;">';
    html += '<div class="modal-header">';
    html += '<div><h2>Advance Stage</h2><p style="margin:2px 0 0;font-size:12.5px;color:var(--ink-muted);"><strong style="color:var(--ink);">' + escapeHtml(rec.brand) + '</strong> (' + escapeHtml(rec.appno || 'No App #') + ')' + (client ? ' &middot; ' + escapeHtml(client.name) : '') + '</p></div>';
    html += '<button class="btn-ghost" data-action="close-modal">✕</button>';
    html += '</div>';

    html += '<div class="modal-body">';

    // Transition banner
    html += '<div class="transition-summary-box">';
    html += '<div class="transition-stages-flow">';
    html += '<div class="transition-stage-node">';
    html += '<span class="transition-stage-sub">Current Stage</span>';
    html += '<span class="badge tier-' + oldSd.tier + '"><span class="dot"></span>' + escapeHtml(oldSd.label) + '</span>';
    html += '</div>';
    html += '<div class="transition-arrow-lg">➔</div>';
    html += '<div class="transition-stage-node">';
    html += '<span class="transition-stage-sub">Advancing To</span>';
    html += '<span class="badge tier-' + newSd.tier + '"><span class="dot"></span>' + escapeHtml(newSd.label) + '</span>';
    html += '</div>';
    html += '</div>';
    if (newSd.suggestedAction) {
      html += '<div style="margin-top:10px;font-size:12px;color:var(--ink-secondary);"><strong style="color:var(--ink);">Next Action:</strong> ' + escapeHtml(newSd.suggestedAction) + '</div>';
    }
    html += '</div>';

    // Form fields
    html += '<div class="field' + (errors.effectiveDate ? ' has-error' : '') + '">';
    html += '<label>Stage Effective Date <span style="color:var(--critical);">*</span> <span class="hint">(mandatory date picker)</span></label>';
    html += '<input type="date" data-stage-field="effectiveDate" value="' + escapeHtml(modalState.effectiveDate || '') + '">';
    if (errors.effectiveDate) {
      html += '<div class="error-msg">' + escapeHtml(errors.effectiveDate) + '</div>';
    }
    html += '</div>';

    html += '<div class="field' + (errors.deadline ? ' has-error' : '') + '">';
    html += '<label>Stage Deadline <span class="hint">(reply / action deadline' + (newSd.slaDays ? ' &mdash; suggested: +' + newSd.slaDays + ' days' : '') + ')</span></label>';
    html += '<input type="date" data-stage-field="deadline" value="' + escapeHtml(modalState.deadline || '') + '">';
    if (errors.deadline) {
      html += '<div class="error-msg">' + escapeHtml(errors.deadline) + '</div>';
    }
    html += '</div>';

    html += '<div class="field' + (errors.remarks ? ' has-error' : '') + '">';
    html += '<label>Stage Notes / Remarks <span style="color:var(--critical);">*</span> <span class="hint">(mandatory key events or comments)</span></label>';
    html += '<textarea data-stage-field="remarks" rows="3" placeholder="Record key events, hearing outcomes, or transition remarks...">' + escapeHtml(modalState.remarks || '') + '</textarea>';
    if (errors.remarks) {
      html += '<div class="error-msg">' + escapeHtml(errors.remarks) + '</div>';
    }
    html += '</div>';

    html += '</div>'; // modal-body

    html += '<div class="modal-footer">';
    html += '<button class="btn btn-secondary" data-action="close-modal">Cancel</button>';
    html += '<button class="btn btn-primary" data-action="commit-stage-transition">Confirm &amp; Record Transition</button>';
    html += '</div>';

    html += '</div></div>';
    return html;
  }

  function commitStageTransition() {
    if (!modalState || modalState.mode !== 'stage-transition') return;
    var errors = {};
    if (!modalState.effectiveDate || !modalState.effectiveDate.trim()) {
      errors.effectiveDate = 'Stage Effective Date is required.';
    }
    if (!modalState.remarks || !modalState.remarks.trim()) {
      errors.remarks = 'Stage Notes / Remarks are required.';
    }
    if (Object.keys(errors).length) {
      modalState.errors = errors;
      renderModal();
      return;
    }

    var r = recordById(modalState.recordId);
    if (!r) { closeModal(); return; }

    var newState = JSON.parse(JSON.stringify(state));
    var oldSd = statusDef(modalState.oldStatus);
    var newSd = statusDef(modalState.newStatus);
    var oldLabel = oldSd.label;
    var newLabel = newSd.label;

    var newTimelineEntry = {
      id: 'st-' + Date.now() + '-' + Math.floor(Math.random() * 10000),
      fromStatus: modalState.oldStatus,
      fromStatusLabel: oldLabel,
      toStatus: modalState.newStatus,
      toStatusLabel: newLabel,
      effectiveDate: modalState.effectiveDate.trim(),
      deadline: modalState.deadline ? modalState.deadline.trim() : null,
      remarks: modalState.remarks.trim(),
      timestamp: new Date().toISOString()
    };

    for (var i = 0; i < newState.records.length; i++) {
      if (newState.records[i].id === r.id) {
        var updated = JSON.parse(JSON.stringify(newState.records[i]));
        updated.status = modalState.newStatus;
        if (modalState.deadline) {
          updated.actionDate = modalState.deadline.trim();
        }
        if (modalState.remarks) {
          updated.action = modalState.remarks.trim();
        }
        if (newSd.renewYears != null && !updated.renewDate) {
          updated.renewDate = addYears(modalState.effectiveDate || todayIso(), newSd.renewYears);
        }
        if (!updated.timeline || !Array.isArray(updated.timeline)) {
          updated.timeline = [];
        }
        updated.timeline.unshift(newTimelineEntry);
        newState.records[i] = updated;
        break;
      }
    }

    var cl = clientById(r.clientId);
    var clientName = cl ? cl.name : '';
    pushLog(newState, r.brand + ' (' + r.appno + ') — ' + clientName + ': ' + oldLabel + ' → ' + newLabel + ' [Effective: ' + fmtDate(modalState.effectiveDate) + ']');
    view.expandedId = r.id;
    closeModal();
    persist(newState, 'Stage transition recorded');
  }

  /* ===================== Form field updates ===================== */
  function applySlaSuggestion(draft, newStatusKey) {
    var sd = statusDef(newStatusKey);
    if (sd.slaDays != null && !draft.actionDate) {
      draft.actionDate = addDays(todayIso(), sd.slaDays);
    }
    if (sd.renewYears != null && !draft.renewDate) {
      draft.renewDate = addYears(todayIso(), sd.renewYears);
    }
  }

  function updateDraftField(name, value) {
    if (!modalState || !modalState.draft) return;
    modalState.draft[name] = value;
    if (modalState.autoFilled) delete modalState.autoFilled[name];
    if (name === 'status') {
      if (!modalState.draft.action) modalState.draft.action = statusDef(value).suggestedAction;
      applySlaSuggestion(modalState.draft, value);
    }
  }

  function validateDraft(d) {
    var cfg = ipConfig(d.ipType || view.ipType);
    var errors = {};
    if (!d.brand || !d.brand.trim()) errors.brand = 'Enter a value for ' + cfg.brandLabel.toLowerCase() + '.';
    if (!d.appno || !d.appno.trim()) errors.appno = 'Enter ' + cfg.appnoLabel.toLowerCase() + ' (or "Not yet filed").';
    if (d.clientId === '__new__' && (!d.newClientName || !d.newClientName.trim())) errors.newClientName = 'Enter the new client\'s name.';
    return errors;
  }

  function pushLog(newState, summary) {
    newState.log = newState.log || [];
    newState.log.unshift({ ts: new Date().toISOString(), summary: summary });
    if (newState.log.length > 500) newState.log.length = 500;
    view.logPage = 1;
  }

  function cleanApplicants(list) {
    return (list || []).map(function (a) {
      return {
        name: (a.name || '').trim(), entityType: a.entityType || 'Individual', authorizedPerson: (a.authorizedPerson || '').trim(),
        address: (a.address || '').trim(), nationality: (a.nationality || '').trim(),
        countryOfResidence: (a.countryOfResidence || '').trim(), gender: a.gender || ''
      };
    }).filter(function (a) { return a.name; });
  }
  function cleanAuthors(list) {
    return (list || []).map(function (a) {
      return {
        name: (a.name || '').trim(),
        institution: (a.institution || '').trim(),
        address: (a.address || '').trim(),
        nationality: (a.nationality || '').trim(),
        countryOfResidence: (a.countryOfResidence || '').trim(),
        gender: a.gender || ''
      };
    }).filter(function (a) { return a.name || a.institution; });
  }
  function cleanContributors(list) {
    return (list || []).map(function (c) {
      return {
        name: (c.name || '').trim(),
        institution: (c.institution || '').trim(),
        affiliation: (c.affiliation || '').trim()
      };
    }).filter(function (c) { return c.name || c.institution || c.affiliation; });
  }

  function saveRecord() {
    var d = modalState.draft;
    var errors = validateDraft(d);
    modalState.errors = errors;
    if (Object.keys(errors).length) { renderModal(); return; }

    var newState = JSON.parse(JSON.stringify(state));
    var clientId = d.clientId;
    var clientName = null;
    if (clientId === '__new__') {
      clientId = nextClientId(newState);
      clientName = d.newClientName.trim();
      newState.clients.push({ id: clientId, name: clientName });
      newState.nextClientSeq = (newState.nextClientSeq || newState.clients.length + 1) + 1;
    } else {
      var cl = clientById(clientId);
      clientName = cl ? cl.name : clientId;
    }

    var isEdit = modalState.mode === 'edit';
    var existingRecord = isEdit ? recordById(d.id) : null;
    var record = {
      id: d.id || nextRecordId(newState),
      clientId: clientId,
      ipType: d.ipType || view.ipType,
      code: (d.code || '').trim(),
      brand: d.brand.trim(),
      cls: (d.cls || '').toString().trim(),
      appno: (d.appno || '').toString().trim(),
      markType: d.markType,
      status: d.status,
      desc: d.desc || '',
      action: d.action || '',
      actionDate: d.actionDate || null,
      renewDate: d.renewDate || null,
      applicants: cleanApplicants(d.applicants),
      authors: cleanAuthors(d.authors),
      contributors: cleanContributors(d.contributors),
      logoUrl: (d.logoUrl || '').trim(),
      assignedTo: (d.assignedTo || '').trim(),
      timeline: (d.timeline && Array.isArray(d.timeline)) ? d.timeline : (existingRecord && existingRecord.timeline ? existingRecord.timeline : [])
    };

    // Financial values are only ever written by a role entitled to see them.
    // Anyone else never received them, so writing back what is in the draft
    // would blank them; the server refuses that too (roles.merge_for_role),
    // this just avoids sending a pointless change.
    if (userCan('edit_financials')) {
      FINANCIAL_FIELDS.forEach(function (f) { record[f] = (d[f] === undefined || d[f] === null) ? '' : String(d[f]).trim(); });
    } else if (existingRecord) {
      FINANCIAL_FIELDS.forEach(function (f) {
        if (existingRecord[f] !== undefined) record[f] = existingRecord[f];
      });
    }

    if (isEdit && existingRecord && isForwardTransition(record.ipType, existingRecord.status, record.status)) {
      var oldSd = statusDef(existingRecord.status);
      var newSd = statusDef(record.status);
      var effDate = (modalState && modalState.stageEffectiveDate && modalState.stageEffectiveDate.trim()) ? modalState.stageEffectiveDate.trim() : todayIso();
      var dlDate = (modalState && modalState.stageDeadline && modalState.stageDeadline.trim()) ? modalState.stageDeadline.trim() : (record.actionDate || null);
      var rem = (modalState && modalState.stageRemarks && modalState.stageRemarks.trim()) ? modalState.stageRemarks.trim() : (record.action || ('Advanced to ' + newSd.label));
      record.timeline.unshift({
        id: 'st-' + Date.now() + '-' + Math.floor(Math.random() * 10000),
        fromStatus: existingRecord.status,
        fromStatusLabel: oldSd.label,
        toStatus: record.status,
        toStatusLabel: newSd.label,
        effectiveDate: effDate,
        deadline: dlDate,
        remarks: rem,
        timestamp: new Date().toISOString()
      });
      if (dlDate) record.actionDate = dlDate;
      if (modalState && modalState.stageRemarks && modalState.stageRemarks.trim() && !record.action) {
        record.action = modalState.stageRemarks.trim();
      }
    }

    if (isEdit) {
      var foundIdx = -1;
      for (var i = 0; i < newState.records.length; i++) {
        if (newState.records[i].id === record.id) {
          foundIdx = i;
          break;
        }
      }
      if (foundIdx >= 0) {
        newState.records[foundIdx] = record;
      } else {
        newState.records.push(record);
      }
      pushLog(newState, 'Edited ' + record.brand + ' (' + record.appno + ') — ' + clientName);
    } else {
      newState.records.push(record);
      newState.nextRecordSeq = (newState.nextRecordSeq || state.records.length + 1) + 1;
      pushLog(newState, 'Added ' + record.brand + ' (' + record.appno + ') — ' + clientName);
    }
    view.clientId = clientId;
    closeModal();
    persist(newState, isEdit ? 'Changes saved' : 'Added to ledger');
  }

  function deleteRecordConfirmed(id) {
    var r = recordById(id);
    var newState = JSON.parse(JSON.stringify(state));
    var foundIdx = -1;
    for (var i = 0; i < newState.records.length; i++) {
      if (newState.records[i].id === id) {
        foundIdx = i;
        break;
      }
    }
    if (foundIdx >= 0) {
      newState.records.splice(foundIdx, 1);
    }
    if (r) {
      var cl = clientById(r.clientId);
      pushLog(newState, 'Removed ' + r.brand + ' (' + r.appno + ') — ' + (cl ? cl.name : ''));
    }
    closeModal();
    persist(newState, 'Matter removed');
  }

  function changeStatus(id, newStatus) {
    var r = recordById(id);
    if (!r) return;
    var newState = JSON.parse(JSON.stringify(state));
    var oldLabel = statusDef(r.status).label;
    for (var i = 0; i < newState.records.length; i++) {
      if (newState.records[i].id === id) {
        var updated = JSON.parse(JSON.stringify(newState.records[i]));
        updated.status = newStatus;
        if (!updated.action || updated.action === statusDef(newState.records[i].status).suggestedAction) {
          updated.action = statusDef(newStatus).suggestedAction;
        }
        applySlaSuggestion(updated, newStatus);
        newState.records[i] = updated;
        break;
      }
    }
    var cl = clientById(r.clientId);
    pushLog(newState, r.brand + ' (' + r.appno + ') — ' + (cl ? cl.name : '') + ': ' + oldLabel + ' → ' + statusDef(newStatus).label);
    persist(newState, 'Status updated');
  }

  function deduplicateRecords() {
    var newState = JSON.parse(JSON.stringify(state));
    var seen = {};
    var unique = [];
    var removed = 0;
    newState.records.forEach(function (r) {
      var key = (r.ipType || '') + '|' + (r.clientId || '') + '|' + (r.appno || '').toLowerCase().trim() + '|' + (r.brand || '').toLowerCase().trim() + '|' + (r.cls || '');
      if (seen[key]) {
        removed++;
      } else {
        seen[key] = true;
        unique.push(r);
      }
    });
    if (removed === 0) {
      toast('No duplicate records found.');
      return;
    }
    newState.records = unique;
    pushLog(newState, 'Cleaned up ' + removed + ' duplicate matter' + (removed === 1 ? '' : 's'));
    persist(newState, 'Cleaned up ' + removed + ' duplicate matter' + (removed === 1 ? '' : 's'));
  }

  function clearAllRecords() {
    if (!state.records.length) {
      toast('There are no matters in the database.');
      return;
    }
    if (!confirm('Are you sure you want to clear all ' + state.records.length + ' matters? You can re-import your CSV cleanly.')) return;
    var newState = JSON.parse(JSON.stringify(state));
    var count = newState.records.length;
    newState.records = [];
    newState.nextRecordSeq = 1;
    pushLog(newState, 'Cleared all ' + count + ' matters');
    persist(newState, 'All matters cleared. Ready for clean CSV import.');
  }

  /* ===================== Import: CSV / XLSX ===================== */
  // Column counts for the per-applicant / per-author blocks scale with however many are actually
  // on record for that ipType today (minimum 1), the same way computeExportColumns sizes itself.
  function maxApplicantsForIpType(ipType) {
    var max = 1;
    state.records.forEach(function (r) { if (r.ipType === ipType) max = Math.max(max, (r.applicants || []).length); });
    return max;
  }
  function maxAuthorsForIpType(ipType) {
    var max = 1;
    state.records.forEach(function (r) { if (r.ipType === ipType) max = Math.max(max, (r.authors || []).length); });
    return max;
  }
  function maxContributorsForIpType(ipType) {
    var max = 1;
    state.records.forEach(function (r) { if (r.ipType === ipType) max = Math.max(max, (r.contributors || []).length); });
    return max;
  }
  function importColumnsFor(ipType) {
    var cfg = ipConfig(ipType);
    var cols = ['Code', 'Client Name', cfg.brandLabel];
    if (cfg.markTypeMode !== 'hidden') cols.push(cfg.markTypeLabel);
    cols.push(cfg.clsLabel, cfg.appnoLabel, 'Status', cfg.descLabel, 'Next Step', 'Next Deadline (DD/MM/YYYY)');
    if (cfg.hasRenewal) cols.push('Renewal Date (DD/MM/YYYY)');
    if (userCan('edit_matter')) cols.push('Assigned To');
    if (userCan('view_financials')) {
      cols.push('Official Fee', 'Professional Fee', 'Amount Received',
                'Payment Status', 'Invoice Reference');
    }
    var maxApp = maxApplicantsForIpType(ipType);
    for (var i = 1; i <= maxApp; i++) {
      cols.push('Applicant ' + i + ' Name', 'Applicant ' + i + ' Entity Type', 'Applicant ' + i + ' Authorized Person',
        'Applicant ' + i + ' Address', 'Applicant ' + i + ' Nationality', 'Applicant ' + i + ' Country of Residence', 'Applicant ' + i + ' Gender');
    }
    if (cfg.hasAuthors) {
      var maxAuth = maxAuthorsForIpType(ipType);
      for (var j = 1; j <= maxAuth; j++) {
        cols.push('Author ' + j + ' Name', 'Author ' + j + ' Institution / Department', 'Author ' + j + ' Address / Affiliation', 'Author ' + j + ' Nationality', 'Author ' + j + ' Country of Residence', 'Author ' + j + ' Gender');
      }
    }
    if (cfg.hasContributors) {
      var maxContrib = maxContributorsForIpType(ipType);
      for (var k = 1; k <= maxContrib; k++) {
        cols.push('Contributor ' + k + ' Name', 'Contributor ' + k + ' Institution / Department', 'Contributor ' + k + ' Affiliation / Employee ID');
      }
    }
    return cols;
  }
  // Internal field keys are stable across ipTypes; aliases cover every label variant used by any
  // ipType's column headers (plus a few common synonyms) so an uploaded file matches regardless of
  function normalizeKey(str) {
    return (str || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  }

  // Internal field keys are stable across ipTypes; aliases cover every label variant used by any
  // ipType's column headers (plus a few common synonyms) so an uploaded file matches regardless of
  // which ipType's template it started from.
  var IMPORT_ALIASES = {
    'code': ['code', 'matter code', 'id'],
    'clientname': ['client name', 'client', 'client / applicant', 'applicant name', 'applicant'],
    'brand': ['brand / mark', 'brand/mark', 'brand', 'trademark', 'mark', 'title of work', 'title', 'work title', 'design title', 'title of design'],
    'marktype': ['mark type', 'marktype', 'type', 'article', 'device'],
    'class': ['class', 'nice class', 'category of work', 'category', 'locarno class'],
    'applicationno': ['application no.', 'application no', 'application number', 'app no.', 'app no', 'appno', 'diary number', 'diary no.', 'diary no'],
    'status': ['status', 'matter status', 'current status'],
    'description': ['goods & services', 'goods and services', 'goods/services', 'description of work', 'description of design', 'description', 'desc'],
    'nextstep': ['next step', 'next action', 'action', 'nextstep', 'step', 'notes'],
    'nextdeadline': ['next deadline (dd/mm/yyyy)', 'next deadline', 'deadline (dd/mm/yyyy)', 'deadline', 'due date', 'action date'],
    'renewaldate': ['renewal date (dd/mm/yyyy)', 'renewal date', 'renewal (dd/mm/yyyy)', 'renewal', 'valid upto', 'valid up to', 'expiry date']
  };

  function getField(row, key) {
    var candidates = IMPORT_ALIASES[key] || [key];
    var normEntries = {};
    var strictNorm = {};
    Object.keys(row).forEach(function (k) {
      var val = row[k];
      normEntries[k.trim().toLowerCase()] = val;
      strictNorm[normalizeKey(k)] = val;
    });

    for (var i = 0; i < candidates.length; i++) {
      var c = candidates[i].toLowerCase();
      if (normEntries[c] !== undefined && normEntries[c] !== '') return String(normEntries[c]).trim();
      var sc = normalizeKey(candidates[i]);
      if (strictNorm[sc] !== undefined && strictNorm[sc] !== '') return String(strictNorm[sc]).trim();
    }
    return '';
  }

  // Applicant N / Author N columns are open-ended (N depends on how many are on record), so rather
  // than a static per-index alias table they're matched by building the expected header directly —
  // "applicant N address", "applicant N nationality", "applicant N country of residence",
  // "applicant N gender" etc — with a couple of reasonable synonyms per field.
  function getFieldVariants(row, candidates) {
    var normEntries = {};
    var strictNorm = {};
    Object.keys(row).forEach(function (k) {
      var val = row[k];
      normEntries[k.trim().toLowerCase()] = val;
      strictNorm[normalizeKey(k)] = val;
    });
    for (var i = 0; i < candidates.length; i++) {
      var c = candidates[i].toLowerCase();
      if (normEntries[c] !== undefined && normEntries[c] !== '') return String(normEntries[c]).trim();
      var sc = normalizeKey(candidates[i]);
      if (strictNorm[sc] !== undefined && strictNorm[sc] !== '') return String(strictNorm[sc]).trim();
    }
    return '';
  }

  function getPersonField(row, kind, n, field) {
    var base = kind + ' ' + n + ' ';
    var map = {
      name: [base + 'Name', base + 'Full Name', kind + ' Name ' + n, kind + ' Name'],
      entityType: [base + 'Entity Type', base + 'Type', base + 'Entity'],
      authorized: [base + 'Authorized Person', base + 'Authorised Person', base + 'Authorized Signatory', base + 'Signatory'],
      institution: [base + 'Institution / Department', base + 'Institution', base + 'Department', base + 'Dept', base + 'Institution/Department', base + 'College / Dept', base + 'University / Dept', base + 'Org'],
      affiliation: [base + 'Affiliation / Employee ID', base + 'Affiliation / ID', base + 'Affiliation', base + 'Employee ID', base + 'Emp ID', base + 'Designation / ID', base + 'ID', base + 'Designation'],
      address: [base + 'Address / Affiliation', base + 'Address', base + 'Full Address', base + 'Affiliation / Address', base + 'Affiliation'],
      nationality: [base + 'Nationality'],
      country: [base + 'Country of Residence', base + 'Country', base + 'Residence'],
      gender: [base + 'Gender', base + 'Sex']
    };
    return getFieldVariants(row, map[field] || [base + field]);
  }

  function csvEscape(v) {
    v = v == null ? '' : String(v);
    if (/[",\n]/.test(v)) return '"' + v.replace(/"/g, '""') + '"';
    return v;
  }
  function buildTemplateCsv(ipType) {
    var cfg = ipConfig(ipType);
    var cols = importColumnsFor(ipType);
    // Example values are keyed by column label (rather than a fixed positional array) since the
    // set of columns is dynamic — it grows with however many applicant/author slots are in use —
    // so any column this ipType doesn't have simply has no entry and renders blank.
    var exampleValues = {};
    exampleValues['Code'] = ipType === 'copyright' ? 'CR101' : (ipType === 'design' ? 'ID101' : 'TR101');
    exampleValues['Client Name'] = 'Acme Pharmaceuticals Pvt. Ltd.';
    exampleValues[cfg.brandLabel] = ipType === 'copyright' ? 'AcmeCure Brand Manual' : (ipType === 'design' ? 'AcmeCure Bottle Shape' : 'AcmeCure');
    if (cfg.markTypeMode !== 'hidden') exampleValues[cfg.markTypeLabel] = ipType === 'design' ? 'Bottle' : 'Word';
    exampleValues[cfg.clsLabel] = ipType === 'copyright' ? 'Literary work' : (ipType === 'design' ? 'Class 09-01' : '5');
    exampleValues[cfg.appnoLabel] = ipType === 'copyright' ? 'DL-12345/2026' : (ipType === 'design' ? '345678' : '1234567');
    exampleValues['Status'] = ipType === 'copyright' ? 'Examination' : (ipType === 'design' ? 'FER Issued' : 'Objected');
    exampleValues[cfg.descLabel] = ipType === 'copyright' ? 'Instruction manual and brand style guide' : (ipType === 'design' ? 'Ornamental shape of a pharmaceutical bottle' : 'Pharmaceutical preparations');
    exampleValues['Next Step'] = ipType === 'copyright' ? 'Awaiting examination outcome' : (ipType === 'design' ? 'File FER response' : 'File response to examination report');
    exampleValues['Next Deadline (DD/MM/YYYY)'] = '15/10/2026';
    exampleValues['Applicant 1 Name'] = 'Acme Pharmaceuticals Pvt. Ltd.';
    exampleValues['Applicant 1 Entity Type'] = 'Company';
    exampleValues['Applicant 1 Authorized Person'] = 'Rahul Sharma';
    exampleValues['Applicant 1 Address'] = '221B, Industrial Estate, New Delhi, India';
    if (cfg.hasAuthors) {
      exampleValues['Author 1 Name'] = 'Rahul Sharma';
      exampleValues['Author 1 Institution / Department'] = 'Department of Computer Science, Delhi University';
      exampleValues['Author 1 Address / Affiliation'] = '221B, Industrial Estate, New Delhi, India';
      exampleValues['Author 1 Nationality'] = 'Indian';
      exampleValues['Author 1 Country of Residence'] = 'India';
      exampleValues['Author 1 Gender'] = 'Male';
    }
    if (cfg.hasContributors) {
      exampleValues['Contributor 1 Name'] = 'Dr. Priya Sharma';
      exampleValues['Contributor 1 Institution / Department'] = 'School of Industrial Design, IIT Delhi';
      exampleValues['Contributor 1 Affiliation / Employee ID'] = 'Lead Designer / EMP-84920';
    }
    var example = cols.map(function (c) { return exampleValues.hasOwnProperty(c) ? exampleValues[c] : ''; });
    var lines = [cols.map(csvEscape).join(','), example.map(csvEscape).join(',')];
    return lines.join('\r\n') + '\r\n';
  }

  function parseCsvText(text) {
    var rows = []; var row = []; var field = ''; var inQuotes = false;
    for (var i = 0; i < text.length; i++) {
      var c = text[i];
      if (inQuotes) {
        if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else inQuotes = false; }
        else field += c;
      } else {
        if (c === '"') inQuotes = true;
        else if (c === ',') { row.push(field); field = ''; }
        else if (c === '\n') { row.push(field); rows.push(row); row = []; field = ''; }
        else if (c === '\r') { /* skip */ }
        else field += c;
      }
    }
    row.push(field); rows.push(row);
    while (rows.length && rows[rows.length - 1].length === 1 && rows[rows.length - 1][0] === '') rows.pop();
    if (!rows.length) return [];
    var headers = rows[0].map(function (h) { return (h || '').trim(); });
    var out = [];
    for (var r = 1; r < rows.length; r++) {
      var arr = rows[r];
      if (!arr || arr.every(function (v) { return (v || '').toString().trim() === ''; })) continue;
      var obj = {};
      headers.forEach(function (h, idx) { obj[h] = arr[idx] !== undefined ? arr[idx] : ''; });
      out.push(obj);
    }
    return out;
  }

  // ---- minimal in-browser XLSX (zip + deflate-raw) reader, first sheet only ----
  function readU32(dv, off) { return dv.getUint32(off, true); }
  function readU16(dv, off) { return dv.getUint16(off, true); }
  async function inflateEntry(bytes, method) {
    if (method === 0) return bytes;
    if (method === 8) {
      var stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
      return new Uint8Array(await new Response(stream).arrayBuffer());
    }
    throw new Error('Unsupported compression in this .xlsx file.');
  }
  async function readZipEntries(buffer, wantedNames) {
    var dv = new DataView(buffer);
    var bytes = new Uint8Array(buffer);
    var eocdOff = -1;
    var maxBack = Math.min(bytes.length, 65557);
    for (var i = bytes.length - 22; i >= bytes.length - maxBack && i >= 0; i--) {
      if (readU32(dv, i) === 0x06054b50) { eocdOff = i; break; }
    }
    if (eocdOff === -1) throw new Error('This does not look like a valid .xlsx file.');
    var totalEntries = readU16(dv, eocdOff + 10);
    var cdOffset = readU32(dv, eocdOff + 16);
    var found = {};
    var ptr = cdOffset;
    for (var e = 0; e < totalEntries; e++) {
      if (readU32(dv, ptr) !== 0x02014b50) throw new Error('Could not read this .xlsx file.');
      var method = readU16(dv, ptr + 10);
      var compSize = readU32(dv, ptr + 20);
      var nameLen = readU16(dv, ptr + 28);
      var extraLen = readU16(dv, ptr + 30);
      var commentLen = readU16(dv, ptr + 32);
      var localOffset = readU32(dv, ptr + 42);
      var name = new TextDecoder('utf-8').decode(bytes.slice(ptr + 46, ptr + 46 + nameLen));
      if (wantedNames.indexOf(name) !== -1) found[name] = { method: method, compSize: compSize, localOffset: localOffset };
      ptr += 46 + nameLen + extraLen + commentLen;
    }
    var out = {};
    for (var n = 0; n < wantedNames.length; n++) {
      var name2 = wantedNames[n];
      var meta = found[name2];
      if (!meta) continue;
      var lh = meta.localOffset;
      if (readU32(dv, lh) !== 0x04034b50) throw new Error('Could not read this .xlsx file.');
      var lhNameLen = readU16(dv, lh + 26);
      var lhExtraLen = readU16(dv, lh + 28);
      var dataStart = lh + 30 + lhNameLen + lhExtraLen;
      var compBytes = bytes.slice(dataStart, dataStart + meta.compSize);
      var raw = await inflateEntry(compBytes, meta.method);
      out[name2] = new TextDecoder('utf-8').decode(raw);
    }
    return out;
  }
  function colLettersToIndex(ref) {
    var m = ref.match(/^([A-Z]+)(\d+)$/);
    if (!m) return null;
    var col = 0;
    for (var i = 0; i < m[1].length; i++) col = col * 26 + (m[1].charCodeAt(i) - 64);
    return col - 1;
  }
  function parseSharedStrings(xml) {
    if (!xml) return [];
    var doc = new DOMParser().parseFromString(xml, 'application/xml');
    var sis = doc.getElementsByTagName('si');
    var arr = [];
    for (var i = 0; i < sis.length; i++) {
      var ts = sis[i].getElementsByTagName('t');
      var s = '';
      for (var j = 0; j < ts.length; j++) s += ts[j].textContent;
      arr.push(s);
    }
    return arr;
  }
  function parseSheetRows(xml, shared) {
    var doc = new DOMParser().parseFromString(xml, 'application/xml');
    var rowEls = doc.getElementsByTagName('row');
    var rows = [];
    for (var r = 0; r < rowEls.length; r++) {
      var cellEls = rowEls[r].getElementsByTagName('c');
      var rowArr = [];
      for (var c = 0; c < cellEls.length; c++) {
        var cell = cellEls[c];
        var ref = cell.getAttribute('r');
        var idx = ref ? colLettersToIndex(ref) : c;
        var type = cell.getAttribute('t');
        var value = '';
        if (type === 'inlineStr') {
          var isEl = cell.getElementsByTagName('is')[0];
          value = isEl ? isEl.textContent : '';
        } else {
          var vEl = cell.getElementsByTagName('v')[0];
          var raw = vEl ? vEl.textContent : '';
          if (type === 's') { var si = parseInt(raw, 10); value = shared[si] !== undefined ? shared[si] : ''; }
          else value = raw;
        }
        rowArr[idx] = value;
      }
      rows.push(rowArr);
    }
    return rows;
  }
  async function parseXlsxArrayBuffer(buffer) {
    var files = await readZipEntries(buffer, ['xl/sharedStrings.xml', 'xl/worksheets/sheet1.xml']);
    var shared = parseSharedStrings(files['xl/sharedStrings.xml']);
    var sheetXml = files['xl/worksheets/sheet1.xml'];
    if (!sheetXml) throw new Error('Could not find the first worksheet in this file.');
    var rows = parseSheetRows(sheetXml, shared);
    if (!rows.length) return [];
    var headers = rows[0].map(function (h) { return (h || '').toString().trim(); });
    var out = [];
    for (var i = 1; i < rows.length; i++) {
      var rowArr = rows[i];
      if (!rowArr || rowArr.every(function (v) { return v === undefined || v === ''; })) continue;
      var obj = {};
      headers.forEach(function (h, idx) { obj[h] = rowArr[idx] !== undefined ? rowArr[idx] : ''; });
      out.push(obj);
    }
    return out;
  }

  function parseImportDate(value) {
    if (value === null || value === undefined || value === '') return null;
    var s = String(value).trim();
    if (/^\d+(\.\d+)?$/.test(s)) {
      var n = parseFloat(s);
      if (n > 20000 && n < 80000) {
        var epoch = Date.UTC(1899, 11, 30);
        var d = new Date(epoch + Math.round(n) * 86400000);
        return d.toISOString().slice(0, 10);
      }
    }
    if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
    return parseDateLoose(s);
  }

  function parseDateLoose(text) {
    if (!text) return null;
    var s = String(text).trim();
    var mYmd = s.match(/^(\d{4})[\/\-.](\d{1,2})[\/\-.](\d{1,2})$/);
    if (mYmd) {
      var y = +mYmd[1], m = +mYmd[2], d = +mYmd[3];
      if (m >= 1 && m <= 12 && d >= 1 && d <= 31) {
        return y + '-' + String(m).padStart(2, '0') + '-' + String(d).padStart(2, '0');
      }
    }
    var mDmy = s.match(/^(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{2,4})$/);
    if (mDmy) {
      var dd = +mDmy[1], mm = +mDmy[2], yy = +mDmy[3];
      if (yy < 100) yy += 2000;
      if (mm >= 1 && mm <= 12 && dd >= 1 && dd <= 31) {
        return yy + '-' + String(mm).padStart(2, '0') + '-' + String(dd).padStart(2, '0');
      }
    }
    var months = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'];
    var m1 = s.match(/(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+(\d{4})/i);
    if (m1) {
      var monIdx = months.findIndex(function (mo) { return mo.indexOf(m1[2].toLowerCase()) === 0; });
      if (monIdx >= 0) return m1[3] + '-' + String(monIdx + 1).padStart(2, '0') + '-' + String(+m1[1]).padStart(2, '0');
    }
    var m2 = s.match(/(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})/i);
    if (m2) {
      var monIdx2 = months.findIndex(function (mo) { return mo.indexOf(m2[1].toLowerCase()) === 0; });
      if (monIdx2 >= 0) return m2[3] + '-' + String(monIdx2 + 1).padStart(2, '0') + '-' + String(+m2[2]).padStart(2, '0');
    }
    return null;
  }

  function matchStatusKey(label, ipType) {
    if (!label) return null;
    var norm = label.trim().toLowerCase();
    var exact = null, partial = null;
    statusDefsForType(ipType).forEach(function (s) {
      if (s.label.toLowerCase() === norm) exact = s.key;
      else if (!partial && (s.label.toLowerCase().indexOf(norm) !== -1 || norm.indexOf(s.label.toLowerCase()) !== -1)) partial = s.key;
    });
    return exact || partial;
  }
  function matchFromList(label, list) {
    if (!label) return null;
    var norm = label.trim().toLowerCase();
    var found = null;
    list.forEach(function (t) { if (!found && t.toLowerCase() === norm) found = t; });
    return found;
  }

  function mapImportRow(row, rowNum, ipType) {
    var cfg = ipConfig(ipType);
    var defaultStatusKey = statusDefsForType(ipType)[0].key;
    var errors = [], warnings = [];
    var code = getField(row, 'code');
    var clientName = getField(row, 'clientname');
    var brand = getField(row, 'brand');
    var markTypeRaw = getField(row, 'marktype');
    var cls = getField(row, 'class');
    var appno = getField(row, 'applicationno');
    var statusRaw = getField(row, 'status');
    var desc = getField(row, 'description');
    var action = getField(row, 'nextstep');
    var actionDateRaw = getField(row, 'nextdeadline');
    var renewDateRaw = getField(row, 'renewaldate');

    if (!brand) errors.push('missing ' + cfg.brandLabel);
    if (!appno) errors.push('missing ' + cfg.appnoLabel);
    if (!clientName) errors.push('missing Client Name');

    var markType = '';
    if (cfg.markTypeMode === 'select') {
      markType = matchFromList(markTypeRaw, cfg.markTypeOptions) || cfg.markTypeOptions[0];
      if (markTypeRaw && !matchFromList(markTypeRaw, cfg.markTypeOptions)) warnings.push('unrecognized ' + cfg.markTypeLabel + ' "' + markTypeRaw + '" — set to ' + cfg.markTypeOptions[0]);
    } else if (cfg.markTypeMode === 'text') {
      markType = markTypeRaw;
    }

    var cls2 = cls;
    if (cfg.clsMode === 'select') {
      cls2 = matchFromList(cls, cfg.clsOptions) || cfg.clsOptions[0];
      if (cls && !matchFromList(cls, cfg.clsOptions)) warnings.push('unrecognized ' + cfg.clsLabel + ' "' + cls + '" — set to ' + cfg.clsOptions[0]);
    }

    var statusKey = matchStatusKey(statusRaw, ipType) || defaultStatusKey;
    if (statusRaw && !matchStatusKey(statusRaw, ipType)) warnings.push('unrecognized Status "' + statusRaw + '" — set to ' + statusDef(defaultStatusKey).label);
    if (!statusRaw) warnings.push('no Status given — set to ' + statusDef(defaultStatusKey).label);

    var actionDate = actionDateRaw ? parseImportDate(actionDateRaw) : null;
    if (actionDateRaw && !actionDate) warnings.push('could not read deadline date "' + actionDateRaw + '"');
    var renewDate = null;
    if (cfg.hasRenewal) {
      renewDate = renewDateRaw ? parseImportDate(renewDateRaw) : null;
      if (renewDateRaw && !renewDate) warnings.push('could not read renewal date "' + renewDateRaw + '"');
    }

    var applicants = [];
    for (var n = 1; n <= 10; n++) {
      var pname = getPersonField(row, 'Applicant', n, 'name');
      if (!pname) continue;
      var etRaw = getPersonField(row, 'Applicant', n, 'entityType');
      var et = matchFromList(etRaw, ENTITY_TYPES) || 'Individual';
      applicants.push({
        name: pname, entityType: et,
        authorizedPerson: getPersonField(row, 'Applicant', n, 'authorized'),
        address: getPersonField(row, 'Applicant', n, 'address'),
        nationality: getPersonField(row, 'Applicant', n, 'nationality'),
        countryOfResidence: getPersonField(row, 'Applicant', n, 'country'),
        gender: matchFromList(getPersonField(row, 'Applicant', n, 'gender'), GENDER_OPTIONS) || ''
      });
    }

    var authors = [];
    if (cfg.hasAuthors) {
      for (var m = 1; m <= 10; m++) {
        var aname = getPersonField(row, 'Author', m, 'name');
        if (!aname) continue;
        authors.push({
          name: aname,
          institution: getPersonField(row, 'Author', m, 'institution'),
          address: getPersonField(row, 'Author', m, 'address'),
          nationality: getPersonField(row, 'Author', m, 'nationality'),
          countryOfResidence: getPersonField(row, 'Author', m, 'country'),
          gender: matchFromList(getPersonField(row, 'Author', m, 'gender'), GENDER_OPTIONS) || ''
        });
      }
    }

    var contributors = [];
    if (cfg.hasContributors) {
      for (var k = 1; k <= 10; k++) {
        var cname = getPersonField(row, 'Contributor', k, 'name') || (k === 1 ? getPersonField(row, 'Researcher', 1, 'name') : '');
        if (!cname) continue;
        contributors.push({
          name: cname,
          institution: getPersonField(row, 'Contributor', k, 'institution') || getPersonField(row, 'Researcher', k, 'institution'),
          affiliation: getPersonField(row, 'Contributor', k, 'affiliation') || getPersonField(row, 'Researcher', k, 'affiliation')
        });
      }
    }

    var assignedTo = userCan('edit_matter') ? (getField(row, 'assignedto') || '') : '';

    // Financial columns are read only for a role entitled to them; the server
    // discards them for anyone else regardless (backend/roles.py).
    var financials = {};
    if (userCan('view_financials')) {
      financials.officialFee = getField(row, 'officialfee') || '';
      financials.professionalFee = getField(row, 'professionalfee') || '';
      financials.amountPaid = getField(row, 'amountreceived') || getField(row, 'amountpaid') || '';
      var payRaw = getField(row, 'paymentstatus') || '';
      financials.paymentStatus = matchFromList(payRaw, PAYMENT_STATUSES) || (payRaw ? '' : PAYMENT_STATUSES[0]);
      if (payRaw && !financials.paymentStatus) {
        warnings.push('unrecognised payment status "' + payRaw + '" — left blank');
      }
      financials.invoiceRef = getField(row, 'invoicereference') || getField(row, 'invoiceref') || '';
    }

    var draft = {
      code: code, clientName: clientName, brand: brand, markType: markType, cls: cls2, appno: appno,
      assignedTo: assignedTo, financials: financials,
      status: statusKey, desc: desc, action: action || statusDef(statusKey).suggestedAction,
      actionDate: actionDate, renewDate: renewDate, applicants: applicants, authors: authors, contributors: contributors
    };
    return { rowNum: rowNum, draft: draft, errors: errors, warnings: warnings, ok: errors.length === 0 };
  }

  async function handleImportFile(file) {
    modalState.fileError = null;
    modalState.fileName = file.name;
    try {
      var rows;
      if (/\.xlsx$/i.test(file.name)) {
        var buf = await file.arrayBuffer();
        rows = await parseXlsxArrayBuffer(buf);
      } else {
        var text = await file.text();
        rows = parseCsvText(text);
      }
      if (!rows.length) {
        modalState.fileError = 'No data rows found in this file.';
        renderModal();
        return;
      }
      var mapped = rows.map(function (r, i) { return mapImportRow(r, i + 2, modalState.ipType); });
      modalState.rows = mapped;
      modalState.stage = 'preview';
      renderModal();
    } catch (err) {
      modalState.fileError = (err && err.message) ? err.message : 'Could not read this file.';
      if (/\.xlsx$/i.test(file.name)) modalState.fileError += ' Try re-saving it as CSV and uploading that instead.';
      renderModal();
    }
  }

  function commitImport() {
    var ipType = modalState.ipType || view.ipType;
    var valid = (modalState.rows || []).filter(function (r) { return r.ok; });
    if (!valid.length) return;
    var newState = JSON.parse(JSON.stringify(state));
    var createdClients = [];
    valid.forEach(function (r) {
      var d = r.draft;
      var client = newState.clients.find(function (c) { return c.name.toLowerCase() === d.clientName.toLowerCase(); });
      var clientId;
      if (client) { clientId = client.id; }
      else {
        clientId = nextClientId(newState);
        newState.clients.push({ id: clientId, name: d.clientName });
        newState.nextClientSeq = (newState.nextClientSeq || newState.clients.length + 1) + 1;
        createdClients.push(d.clientName);
      }
      var record = {
        id: nextRecordId(newState), clientId: clientId, ipType: ipType, code: d.code, brand: d.brand,
        cls: d.cls, appno: d.appno, markType: d.markType, status: d.status, desc: d.desc, action: d.action,
        actionDate: d.actionDate, renewDate: d.renewDate, applicants: d.applicants, authors: d.authors || [], contributors: d.contributors || [], logoUrl: '', timeline: [],
        assignedTo: d.assignedTo || ''
      };
      Object.keys(d.financials || {}).forEach(function (k) { record[k] = d.financials[k]; });
      newState.records.push(record);
      newState.nextRecordSeq = (newState.nextRecordSeq || newState.records.length + 1) + 1;
    });
    var skipped = (modalState.rows || []).length - valid.length;
    var typeLabel = ipConfig(ipType).label.toLowerCase();
    var summary = 'Imported ' + valid.length + ' ' + typeLabel + (valid.length === 1 ? '' : 's') + ' via file' +
      (skipped ? ' (' + skipped + ' row' + (skipped === 1 ? '' : 's') + ' skipped)' : '') +
      (createdClients.length ? ' — new client' + (createdClients.length === 1 ? '' : 's') + ': ' + createdClients.join(', ') : '');
    pushLog(newState, summary);
    view.ipType = ipType;
    view.clientId = '__all__';
    view.dashboardClientId = '__all__';
    view.ledgerPage = 1;
    view.statusFilter = {};
    view.search = '';
    closeModal();
    persist(newState, valid.length + ' matter' + (valid.length === 1 ? '' : 's') + ' imported');
  }

  /* Real browser download via Blob + a temporary <a download> click. This works fine
     outside Claude's sandbox (a plain hosted page), so it's the primary path whenever
     window.claude isn't present — the read-only textarea is now truly last-resort,
     used only if Blob/URL.createObjectURL themselves throw (very old/locked-down
     browsers). */
  function triggerBrowserDownload(filename, text, mime) {
    try {
      var blob = new Blob([text], { type: mime || 'text/plain;charset=utf-8' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
      return true;
    } catch (e) {
      return false;
    }
  }

  async function downloadTemplate() {
    var ipType = modalState.ipType || view.ipType;
    var csv = buildTemplateCsv(ipType);
    var filename = 'lextria-' + ipType + '-import-template.csv';
    if (window.claude && window.claude.use) {
      var dl = await window.claude.use('downloads');
      if (dl) {
        try {
          await dl.save({ filename: filename, data: csv });
          return;
        } catch (err) {
          if (err && err.code === 'declined') return;
          // fall through to a real browser download below
        }
      }
    }
    if (!triggerBrowserDownload(filename, csv, 'text/csv;charset=utf-8')) {
      toast('Could not save the template — use "view as text" to copy it instead.');
    }
  }

  /* ===================== Export ===================== */
  function getExportScopeRecords(scope) {
    var clientRecords = recordsFor(view.clientId, view.ipType);
    if (scope === 'scope') return clientRecords;
    var showClient = view.clientId === '__all__';
    var activeStatuses = Object.keys(view.statusFilter).filter(function (k) { return view.statusFilter[k]; });
    return clientRecords.filter(function (r) {
      if (activeStatuses.length && activeStatuses.indexOf(r.status) === -1) return false;
      return matchesSearch(r, view.search, view.searchField, showClient);
    }).sort(function (a, b) { return cmpRecords(a, b, view.sortKey, view.sortDir); });
  }
  function computeExportColumns(records, ipType) {
    var cfg = ipConfig(ipType);
    var cols = [
      { key: 'code', label: 'Code', get: function (r) { return r.code || ''; } },
      { key: 'client', label: 'Client', get: function (r) { var c = clientById(r.clientId); return c ? c.name : ''; } },
      { key: 'ipType', label: 'IP Type', get: function (r) { return ipConfig(r.ipType || ipType).label; } },
      { key: 'brand', label: cfg.brandLabel, get: function (r) { return r.brand || ''; } }
    ];
    if (cfg.markTypeMode !== 'hidden') {
      cols.push({ key: 'markType', label: cfg.markTypeLabel || 'Mark Type / Article', get: function (r) { return r.markType || ''; } });
    }
    cols.push(
      { key: 'cls', label: cfg.clsLabel, get: function (r) { return r.cls !== null && r.cls !== undefined ? r.cls : ''; } },
      { key: 'appno', label: cfg.appnoLabel, get: function (r) { return r.appno || ''; } },
      { key: 'status', label: 'Status', get: function (r) { return statusDef(r.status).label; } },
      { key: 'statusTier', label: 'Status Tier', get: function (r) { return statusDef(r.status).tier || ''; } },
      { key: 'desc', label: cfg.descLabel, get: function (r) { return r.desc || ''; } },
      { key: 'action', label: 'Next Step / Notes', get: function (r) { return r.action || ''; } },
      { key: 'actionDate', label: 'Next Deadline', get: function (r) { return r.actionDate || ''; } },
      { key: 'deadlineDays', label: 'Days Until Deadline', get: function (r) { return r.actionDate ? daysUntil(r.actionDate) : ''; } }
    );
    if (cfg.hasRenewal) {
      cols.push({ key: 'renewDate', label: 'Renewal Date', get: function (r) { return r.renewDate || ''; } });
    }
    if (cfg.hasLogo) {
      cols.push({ key: 'logoUrl', label: 'Logo / Asset URL', get: function (r) { return r.logoUrl || ''; } });
    }
    if (userCan('edit_matter')) {
      cols.push({ key: 'assignedTo', label: 'Assigned To', get: function (r) { return r.assignedTo || ''; } });
    }
    // Financial columns are offered only to a role that receives the values;
    // for anyone else the fields are not even present on the record.
    if (userCan('view_financials')) {
      cols.push(
        { key: 'officialFee', label: 'Official Fee', get: function (r) { return r.officialFee || ''; } },
        { key: 'professionalFee', label: 'Professional Fee', get: function (r) { return r.professionalFee || ''; } },
        { key: 'amountPaid', label: 'Amount Received', get: function (r) { return r.amountPaid || ''; } },
        { key: 'paymentStatus', label: 'Payment Status', get: function (r) { return r.paymentStatus || ''; } },
        { key: 'invoiceRef', label: 'Invoice Reference', get: function (r) { return r.invoiceRef || ''; } }
      );
    }

    var maxApplicants = 0;
    records.forEach(function (r) { maxApplicants = Math.max(maxApplicants, (r.applicants || []).length); });
    var _loop = function (i) {
      cols.push({ key: 'app' + i + 'name', label: 'Applicant ' + (i + 1) + ' Name', get: function (r) { var a = (r.applicants || [])[i]; return a ? a.name || '' : ''; } });
      cols.push({ key: 'app' + i + 'type', label: 'Applicant ' + (i + 1) + ' Entity Type', get: function (r) { var a = (r.applicants || [])[i]; return a ? a.entityType || '' : ''; } });
      cols.push({ key: 'app' + i + 'auth', label: 'Applicant ' + (i + 1) + ' Authorized Person', get: function (r) { var a = (r.applicants || [])[i]; return a ? a.authorizedPerson || '' : ''; } });
      cols.push({ key: 'app' + i + 'address', label: 'Applicant ' + (i + 1) + ' Address', get: function (r) { var a = (r.applicants || [])[i]; return a ? a.address || '' : ''; } });
      cols.push({ key: 'app' + i + 'nationality', label: 'Applicant ' + (i + 1) + ' Nationality', get: function (r) { var a = (r.applicants || [])[i]; return a ? a.nationality || '' : ''; } });
      cols.push({ key: 'app' + i + 'country', label: 'Applicant ' + (i + 1) + ' Country of Residence', get: function (r) { var a = (r.applicants || [])[i]; return a ? a.countryOfResidence || '' : ''; } });
      cols.push({ key: 'app' + i + 'gender', label: 'Applicant ' + (i + 1) + ' Gender', get: function (r) { var a = (r.applicants || [])[i]; return a ? a.gender || '' : ''; } });
    };
    for (var i = 0; i < maxApplicants; i++) { _loop(i); }

    if (cfg.hasAuthors) {
      var maxAuthors = 0;
      records.forEach(function (r) { maxAuthors = Math.max(maxAuthors, (r.authors || []).length); });
      var _loopAuth = function (j) {
        cols.push({ key: 'auth' + j + 'name', label: 'Author ' + (j + 1) + ' Name', get: function (r) { var a = (r.authors || [])[j]; return a ? a.name || '' : ''; } });
        cols.push({ key: 'auth' + j + 'institution', label: 'Author ' + (j + 1) + ' Institution / Department', get: function (r) { var a = (r.authors || [])[j]; return a ? a.institution || '' : ''; } });
        cols.push({ key: 'auth' + j + 'address', label: 'Author ' + (j + 1) + ' Address / Affiliation', get: function (r) { var a = (r.authors || [])[j]; return a ? a.address || '' : ''; } });
        cols.push({ key: 'auth' + j + 'nationality', label: 'Author ' + (j + 1) + ' Nationality', get: function (r) { var a = (r.authors || [])[j]; return a ? a.nationality || '' : ''; } });
        cols.push({ key: 'auth' + j + 'country', label: 'Author ' + (j + 1) + ' Country of Residence', get: function (r) { var a = (r.authors || [])[j]; return a ? a.countryOfResidence || '' : ''; } });
        cols.push({ key: 'auth' + j + 'gender', label: 'Author ' + (j + 1) + ' Gender', get: function (r) { var a = (r.authors || [])[j]; return a ? a.gender || '' : ''; } });
      };
      for (var j = 0; j < maxAuthors; j++) { _loopAuth(j); }
    }

    if (cfg.hasContributors) {
      var maxContributors = 0;
      records.forEach(function (r) { maxContributors = Math.max(maxContributors, (r.contributors || []).length); });
      var _loopContrib = function (k) {
        cols.push({ key: 'contrib' + k + 'name', label: 'Contributor ' + (k + 1) + ' Name', get: function (r) { var c = (r.contributors || [])[k]; return c ? c.name || '' : ''; } });
        cols.push({ key: 'contrib' + k + 'institution', label: 'Contributor ' + (k + 1) + ' Institution / Department', get: function (r) { var c = (r.contributors || [])[k]; return c ? c.institution || '' : ''; } });
        cols.push({ key: 'contrib' + k + 'affiliation', label: 'Contributor ' + (k + 1) + ' Affiliation / Employee ID', get: function (r) { var c = (r.contributors || [])[k]; return c ? c.affiliation || '' : ''; } });
      };
      for (var k = 0; k < maxContributors; k++) { _loopContrib(k); }
    }

    cols.push(
      { key: 'timelineCount', label: 'Stage Transitions Count', get: function (r) { return (r.timeline || []).length; } },
      { key: 'latestTransition', label: 'Latest Stage Transition', get: function (r) {
        var t = (r.timeline || [])[0];
        if (!t) return '—';
        return (t.fromStatusLabel || t.fromStatus) + ' ➔ ' + (t.toStatusLabel || t.toStatus) + ' (' + (fmtDate(t.effectiveDate) || t.effectiveDate || '') + ')';
      } },
      { key: 'latestTransitionRemarks', label: 'Latest Transition Remarks', get: function (r) {
        var t = (r.timeline || [])[0];
        return t ? (t.remarks || '') : '';
      } },
      { key: 'auditTrailFull', label: 'Full Audit Trail History', get: function (r) {
        var list = r.timeline || [];
        if (!list.length) return 'No transitions recorded';
        return list.map(function (t, idx) {
          return '[' + (idx + 1) + '] ' + (t.fromStatusLabel || t.fromStatus) + ' ➔ ' + (t.toStatusLabel || t.toStatus) +
            ' | Effective: ' + (t.effectiveDate || '—') +
            (t.deadline ? ' | Deadline: ' + t.deadline : '') +
            (t.remarks ? ' | Remarks: ' + t.remarks : '') +
            (t.timestamp ? ' | Logged: ' + t.timestamp : '');
        }).join(' ;; ');
      } }
    );

    return cols;
  }
  function radioRow(name, value, isChecked, label) {
    return '<label class="radio-row"><input type="radio" name="' + name + '" value="' + value + '" data-action="' + name + '"' + (isChecked ? ' checked' : '') + '>' +
      '<span>' + label + '</span></label>';
  }
  function renderExportModal() {
    var cfg = ipConfig(view.ipType);
    var records = getExportScopeRecords(modalState.scope);
    var columns = computeExportColumns(records, view.ipType);
    var checked = modalState.columns || {};
    var nextChecked = {};
    columns.forEach(function (c) { nextChecked[c.key] = checked.hasOwnProperty(c.key) ? checked[c.key] : true; });
    modalState.columns = nextChecked;

    var scopeCount = getExportScopeRecords('scope').length;
    var filteredCount = getExportScopeRecords('filtered').length;
    var scopeName = view.clientId === '__all__' ? 'all clients' : 'this client';

    var html = '<div class="modal-overlay" data-action="overlay-close"><div class="modal" role="dialog" aria-modal="true">';
    html += '<div class="modal-header"><h2>Export ' + escapeHtml(cfg.label.toLowerCase()) + 's</h2><button class="btn-ghost" data-action="close-modal">✕</button></div>';
    html += '<div class="modal-body">';

    html += '<div class="field" style="margin-bottom:18px;"><label>What to export</label>';
    html += radioRow('export-scope', 'filtered', modalState.scope === 'filtered', 'Visible rows only (' + filteredCount + ') — respects your current search and status filters');
    html += radioRow('export-scope', 'scope', modalState.scope === 'scope', 'Everything in this view (' + scopeCount + ') — ' + scopeName + ', filters ignored');
    html += '</div>';

    html += '<div class="field" style="margin-bottom:18px;"><label>Columns <span class="hint">(pick exactly what you need)</span></label>';
    html += '<div style="display:flex;gap:14px;font-size:12px;margin:2px 0 8px;">' +
      '<button type="button" class="btn-ghost" style="padding:2px 4px;" data-action="export-cols-all">Select all</button>' +
      '<button type="button" class="btn-ghost" style="padding:2px 4px;" data-action="export-cols-none">Select none</button></div>';
    html += '<div class="check-list">';
    columns.forEach(function (c) {
      html += '<label class="check-item"><input type="checkbox" data-action="export-col-toggle" data-col="' + c.key + '"' + (modalState.columns[c.key] ? ' checked' : '') + '>' + escapeHtml(c.label) + '</label>';
    });
    html += '</div></div>';

    html += '<div class="field"><label>Format</label>';
    html += radioRow('export-format', 'csv', modalState.format === 'csv', 'CSV — opens in Excel or Sheets, and can be re-imported here later');
    html += radioRow('export-format', 'json', modalState.format === 'json', 'JSON — for other systems or developers');
    html += '</div>';

    if (modalState.exportFallback) {
      html += '<div class="parse-banner"><strong>Could not trigger a direct download</strong>Copy the text below and save it yourself as ' + escapeHtml(modalState.exportFallback.filename) + '.</div>';
      html += '<textarea readonly class="export-fallback">' + escapeHtml(modalState.exportFallback.text) + '</textarea>';
    }

    html += '</div>';
    var selCount = columns.filter(function (c) { return modalState.columns[c.key]; }).length;
    html += '<div class="modal-footer"><span class="export-meta">' + records.length + ' row' + (records.length === 1 ? '' : 's') + ' &middot; ' + selCount + ' column' + (selCount === 1 ? '' : 's') + '</span>';
    html += '<div class="right-actions"><button class="btn btn-secondary" data-action="close-modal">Cancel</button>' +
      '<button class="btn btn-primary" data-action="export-run"' + (records.length && selCount ? '' : ' disabled') + '>Export</button></div></div>';
    html += '</div></div>';
    return html;
  }
  function slugify(text) {
    return (text || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '') || 'export';
  }
  async function runExport() {
    var records = getExportScopeRecords(modalState.scope);
    var columns = computeExportColumns(records, view.ipType).filter(function (c) { return modalState.columns[c.key]; });
    if (!records.length || !columns.length) return;
    var text, ext;
    if (modalState.format === 'json') {
      var arr = records.map(function (r) {
        var obj = {};
        columns.forEach(function (c) { obj[c.label] = c.get(r); });
        return obj;
      });
      text = JSON.stringify(arr, null, 2);
      ext = 'json';
    } else {
      var lines = [columns.map(function (c) { return csvEscape(c.label); }).join(',')];
      records.forEach(function (r) {
        lines.push(columns.map(function (c) { return csvEscape(c.get(r)); }).join(','));
      });
      text = lines.join('\r\n') + '\r\n';
      ext = 'csv';
    }
    var clientPart = view.clientId === '__all__' ? 'all-clients' : slugify(clientById(view.clientId) ? clientById(view.clientId).name : 'client');
    var filename = 'lextria-' + view.ipType + 's-' + clientPart + '-' + todayIso() + '.' + ext;

    if (window.claude && window.claude.use) {
      var dl = await window.claude.use('downloads');
      if (dl) {
        try {
          await dl.save({ filename: filename, data: text });
          closeModal();
          toast('Exported ' + records.length + ' row' + (records.length === 1 ? '' : 's') + '.');
          return;
        } catch (err) {
          if (err && err.code === 'declined') return;
          // fall through to a real browser download below
        }
      }
    }
    var mime = ext === 'json' ? 'application/json;charset=utf-8' : 'text/csv;charset=utf-8';
    if (triggerBrowserDownload(filename, text, mime)) {
      closeModal();
      toast('Exported ' + records.length + ' row' + (records.length === 1 ? '' : 's') + '.');
    } else {
      showExportFallback(filename, text);
    }
  }
  function showExportFallback(filename, text) {
    modalState.exportFallback = { filename: filename, text: text };
    renderModal();
  }

  /* ===================== Event delegation ===================== */
  function attachHandlers() {
    document.body.addEventListener('click', function (e) {
      var el = e.target.closest('[data-action]');
      if (!el) return;
      var action = el.getAttribute('data-action');
      switch (action) {
        case 'set-mode':
          view.mode = el.getAttribute('data-mode');
          if (view.mode === 'settings' && userCan('manage_users')) loadUsers();
          renderAll();
          break;
        case 'set-iptype':
          view.ipType = el.getAttribute('data-iptype');
          view.expandedId = null;
          view.ledgerPage = 1;
          view.statusFilter = {};
          renderAll();
          break;
        case 'set-deadline-client':
          view.deadlineClientFilter = el.getAttribute('data-client');
          view.deadlinesPage = 1;
          renderAll();
          break;
        case 'toggle-expand':
          if (e.target.closest('select') || e.target.closest('button')) return;
          var id = el.getAttribute('data-id');
          view.expandedId = view.expandedId === id ? null : id;
          renderAll();
          break;
        case 'sort':
          e.stopPropagation();
          var key = el.getAttribute('data-key');
          if (view.sortKey === key) view.sortDir *= -1; else { view.sortKey = key; view.sortDir = 1; }
          view.ledgerPage = 1;
          renderAll();
          break;
        case 'clear-status-filter':
          view.statusFilter = {};
          view.ledgerPage = 1;
          renderAll();
          break;
        case 'toggle-status-filter':
          var st = el.getAttribute('data-status');
          view.statusFilter[st] = !view.statusFilter[st];
          view.ledgerPage = 1;
          renderAll();
          break;
        case 'pager-prev': {
          var scopeP = el.getAttribute('data-scope');
          var kP = pagerPageKey(scopeP);
          view[kP] = Math.max(1, (view[kP] || 1) - 1);
          renderAll();
          break;
        }
        case 'pager-next': {
          var scopeN = el.getAttribute('data-scope');
          var kN = pagerPageKey(scopeN);
          view[kN] = (view[kN] || 1) + 1;
          renderAll();
          break;
        }
        case 'pager-goto': {
          var scopeG = el.getAttribute('data-scope');
          view[pagerPageKey(scopeG)] = parseInt(el.getAttribute('data-page'), 10) || 1;
          renderAll();
          break;
        }
        case 'toggle-password': {
          var targetId = el.getAttribute('data-target');
          var inp = document.getElementById(targetId);
          if (!inp) break;
          var showIcon = el.querySelector('.pw-icon-show');
          var hideIcon = el.querySelector('.pw-icon-hide');
          // Direct DOM manipulation only — deliberately no renderAll()/renderGate() here. Both the
          // gate and the settings login form rebuild their HTML from scratch on every render, which
          // would wipe out whatever passphrase the user had already typed.
          if (inp.type === 'password') {
            inp.type = 'text';
            if (showIcon) showIcon.style.display = 'none';
            if (hideIcon) hideIcon.style.display = '';
            el.setAttribute('aria-label', 'Hide passphrase');
          } else {
            inp.type = 'password';
            if (showIcon) showIcon.style.display = '';
            if (hideIcon) hideIcon.style.display = 'none';
            el.setAttribute('aria-label', 'Show passphrase');
          }
          break;
        }
        case 'open-add':
          openAddModal();
          break;
        case 'open-edit':
          e.stopPropagation();
          openEditModal(el.getAttribute('data-id'));
          break;
        case 'open-import':
          openImportModal();
          break;
        case 'open-export':
          openExportModal();
          break;
        case 'export-cols-all':
          Object.keys(modalState.columns).forEach(function (k) { modalState.columns[k] = true; });
          renderModal();
          break;
        case 'export-cols-none':
          Object.keys(modalState.columns).forEach(function (k) { modalState.columns[k] = false; });
          renderModal();
          break;
        case 'export-run':
          runExport();
          break;
        case 'gate-submit':
          attemptUnlock();
          break;
        case 'signin-submit':
          attemptSignIn();
          break;
        case 'change-password':
          submitPasswordChange();
          break;
        case 'user-suspend':
          setUserActive(el.getAttribute('data-userid'), el.getAttribute('data-active') === '1');
          break;
        case 'user-add':
          submitNewUser();
          break;
        case 'user-delete':
          deleteUser(el.getAttribute('data-userid'));
          break;
        case 'sign-out':
          signOut();
          break;
        case 'login-edit':
          settingsDraft = { editingLogin: true, newPass: '', confirmPass: '', error: '' };
          renderAll();
          break;
        case 'login-cancel':
          settingsDraft = { editingLogin: false, newPass: '', confirmPass: '', error: '' };
          renderAll();
          break;
        case 'login-save':
          submitLoginSave();
          break;
        case 'login-disable':
          disableLogin();
          settingsDraft = { editingLogin: false, newPass: '', confirmPass: '', error: '' };
          break;
        case 'lock-now':
          lockNow();
          break;
        case 'deduplicate-records':
          deduplicateRecords();
          break;
        case 'clear-all-records':
          clearAllRecords();
          break;
        case 'close-modal':
          closeModal();
          break;
        case 'overlay-close':
          if (e.target === el) closeModal();
          break;
        case 'save-record':
          saveRecord();
          break;
        case 'commit-stage-transition':
          commitStageTransition();
          break;
        case 'delete-record':
          confirmDelete();
          break;
        case 'confirm-delete-yes':
          deleteRecordConfirmed(modalState.draft.id);
          break;
        case 'confirm-delete-no':
          openEditModal(modalState.draft.id);
          break;
        case 'download-template':
          downloadTemplate();
          break;
        case 'import-back':
          modalState.stage = 'idle';
          modalState.fileError = null;
          renderModal();
          break;
        case 'import-commit':
          commitImport();
          break;
        case 'add-applicant':
          e.stopPropagation();
          modalState.draft.applicants = modalState.draft.applicants || [];
          modalState.draft.applicants.push({ name: '', entityType: 'Individual', authorizedPerson: '' });
          renderModal();
          break;
        case 'remove-applicant':
          e.stopPropagation();
          var rmIdx = parseInt(el.getAttribute('data-idx'), 10);
          modalState.draft.applicants.splice(rmIdx, 1);
          renderModal();
          break;
        case 'add-author':
          e.stopPropagation();
          modalState.draft.authors = modalState.draft.authors || [];
          modalState.draft.authors.push({ name: '', institution: '', address: '', nationality: '', countryOfResidence: '', gender: '' });
          renderModal();
          break;
        case 'remove-author':
          e.stopPropagation();
          var rmAuthorIdx = parseInt(el.getAttribute('data-idx'), 10);
          modalState.draft.authors.splice(rmAuthorIdx, 1);
          renderModal();
          break;
        case 'add-contributor':
          e.stopPropagation();
          modalState.draft.contributors = modalState.draft.contributors || [];
          modalState.draft.contributors.push({ name: '', institution: '', affiliation: '' });
          renderModal();
          break;
        case 'remove-contributor':
          e.stopPropagation();
          var rmContribIdx = parseInt(el.getAttribute('data-idx'), 10);
          modalState.draft.contributors.splice(rmContribIdx, 1);
          renderModal();
          break;
        case 'dashboard-goto':
          view.ipType = el.getAttribute('data-iptype');
          view.clientId = view.dashboardClientId;
          view.mode = 'ledger';
          view.ledgerPage = 1;
          view.expandedId = null;
          view.statusFilter = {};
          renderAll();
          break;
        case 'scroll-needs':
          var sec = document.getElementById('needs-deadline-section');
          if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
          break;
      }
    });

    document.body.addEventListener('change', function (e) {
      var el = e.target;
      if (el.matches('[data-action="change-client"]')) {
        if (el.value === '__new__') {
          openAddModal();
          modalState.draft.clientId = '__new__';
          renderModal();
          el.value = view.clientId;
        } else {
          view.clientId = el.value;
          view.expandedId = null;
          view.ledgerPage = 1;
          renderAll();
        }
        return;
      }
      if (el.matches('[data-action="change-status"]')) {
        var rId = el.getAttribute('data-id');
        var newSt = el.value;
        var rec = recordById(rId);
        if (!rec) return;
        if (isForwardTransition(rec.ipType, rec.status, newSt)) {
          el.value = rec.status;
          openStageTransitionModal(rec, newSt);
        } else {
          changeStatus(rId, newSt);
        }
        return;
      }
      if (el.matches('[data-stage-field]')) {
        var stgField = el.getAttribute('data-stage-field');
        if (modalState && modalState.mode === 'stage-transition') {
          modalState[stgField] = el.value;
          if (modalState.errors && modalState.errors[stgField]) {
            delete modalState.errors[stgField];
            renderModal();
          }
        }
        return;
      }
      if (el.matches('[data-action="import-file-input"]')) {
        if (el.files && el.files[0]) handleImportFile(el.files[0]);
        return;
      }
      if (el.matches('[data-applicant-field]')) {
        var aIdx = parseInt(el.getAttribute('data-applicant-idx'), 10);
        var aField = el.getAttribute('data-applicant-field');
        modalState.draft.applicants[aIdx][aField] = el.value;
        if (aField === 'entityType') renderModal();
        return;
      }
      if (el.matches('[data-author-field]')) {
        var authIdx = parseInt(el.getAttribute('data-author-idx'), 10);
        var authField = el.getAttribute('data-author-field');
        modalState.draft.authors[authIdx][authField] = el.value;
        return;
      }
      if (el.matches('[data-contributor-field]')) {
        var cIdx = parseInt(el.getAttribute('data-contributor-idx'), 10);
        var cField = el.getAttribute('data-contributor-field');
        modalState.draft.contributors[cIdx][cField] = el.value;
        return;
      }
      if (el.matches('[data-action="logo-file-input"]')) {
        if (el.files && el.files[0]) handleLogoFile(el.files[0]);
        return;
      }
      if (el.matches('[data-action="dashboard-change-client"]')) {
        view.dashboardClientId = el.value;
        renderAll();
        return;
      }
      if (el.matches('[data-userfield]')) {
        usersState.draft[el.getAttribute('data-userfield')] = el.value;
        return;
      }
      if (el.matches('[data-field]')) {
        var fld = el.getAttribute('data-field');
        if (fld === 'stageEffectiveDate' || fld === 'stageDeadline' || fld === 'stageRemarks') {
          if (modalState) modalState[fld] = el.value;
          return;
        }
        updateDraftField(fld, el.value);
        if (fld === 'clientId' || fld === 'status') {
          if (fld === 'status' && modalState && modalState.mode === 'edit' && modalState.initialStatus) {
            modalState.stageDeadline = calculateSuggestedDeadline(modalState.draft.ipType, el.value);
          }
          renderModal();
        }
        return;
      }
      if (el.matches('[data-action="search-field"]')) {
        view.searchField = el.value;
        view.ledgerPage = 1;
        renderAll();
        return;
      }
      if (el.matches('[data-action="pagesize-radio"]')) {
        setPageSize(parseInt(el.value, 10));
        return;
      }
      if (el.matches('[data-action="export-scope"]')) {
        modalState.scope = el.value;
        modalState.exportFallback = null;
        renderModal();
        return;
      }
      if (el.matches('[data-action="export-format"]')) {
        modalState.format = el.value;
        modalState.exportFallback = null;
        renderModal();
        return;
      }
      if (el.matches('[data-action="export-col-toggle"]')) {
        modalState.columns[el.getAttribute('data-col')] = el.checked;
        renderModal();
        return;
      }
      if (el.matches('[data-action="theme-radio"]')) {
        setLocalPref(LOCAL_KEYS.theme, el.value);
        applyTheme(el.value);
        renderAll();
        return;
      }
      if (el.matches('[data-action="notify-toggle"]')) {
        handleNotifyToggle(el.checked);
        return;
      }
      if (el.matches('[data-action="lock-refresh-toggle"]')) {
        setLocalPref(LOCAL_KEYS.lockOnRefresh, el.checked ? 'on' : 'off');
        toast(el.checked ? 'Auto-lock enabled: refreshing will require login.' : 'Auto-lock disabled.');
        renderAll();
        return;
      }
    });

    document.body.addEventListener('input', function (e) {
      var el = e.target;
      if (el.matches('[data-action="search"]')) {
        view.search = el.value;
        view.ledgerPage = 1;
        renderAll();
        var input = document.querySelector('[data-action="search"]');
        if (input) { input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
        return;
      }
      if (el.matches('[data-stage-field]')) {
        var stgField2 = el.getAttribute('data-stage-field');
        if (modalState && modalState.mode === 'stage-transition') {
          modalState[stgField2] = el.value;
          if (modalState.errors && modalState.errors[stgField2]) {
            delete modalState.errors[stgField2];
            var errEl = el.parentNode.querySelector('.error-msg');
            if (errEl) errEl.remove();
            var parentField = el.closest('.field');
            if (parentField) parentField.classList.remove('has-error');
          }
        }
        return;
      }
      if (el.matches('[data-applicant-field]')) {
        var aIdx2 = parseInt(el.getAttribute('data-applicant-idx'), 10);
        var aField2 = el.getAttribute('data-applicant-field');
        modalState.draft.applicants[aIdx2][aField2] = el.value;
        return;
      }
      if (el.matches('[data-author-field]')) {
        var authIdx2 = parseInt(el.getAttribute('data-author-idx'), 10);
        var authField2 = el.getAttribute('data-author-field');
        modalState.draft.authors[authIdx2][authField2] = el.value;
        return;
      }
      if (el.matches('[data-contributor-field]')) {
        var cIdx2 = parseInt(el.getAttribute('data-contributor-idx'), 10);
        var cField2 = el.getAttribute('data-contributor-field');
        modalState.draft.contributors[cIdx2][cField2] = el.value;
        return;
      }
      if (el.matches('[data-pwfield]')) {
        pwState[el.getAttribute('data-pwfield')] = el.value;
        return;
      }
      if (el.matches('[data-userfield]')) {
        usersState.draft[el.getAttribute('data-userfield')] = el.value;
        return;
      }
      if (el.matches('[data-field]') && el.tagName !== 'SELECT') {
        var fld2 = el.getAttribute('data-field');
        if (fld2 === 'stageEffectiveDate' || fld2 === 'stageDeadline' || fld2 === 'stageRemarks') {
          if (modalState) modalState[fld2] = el.value;
          return;
        }
        updateDraftField(fld2, el.value);
        if (fld2 === 'logoUrl') updateLogoPreview(fld2);
        return;
      }
      if (el.matches('[data-settings-field]')) {
        settingsDraft[el.getAttribute('data-settings-field')] = el.value;
        settingsDraft.error = '';
        return;
      }
    });
  }

  function confirmDelete() {
    var d = modalState.draft;
    modalState.confirmingDelete = true;
    var root = document.getElementById('modal-root');
    root.innerHTML = '<div class="modal-overlay"><div class="modal" style="max-width:420px;">' +
      '<div class="modal-header"><h2>Remove this matter?</h2></div>' +
      '<div class="modal-body"><p style="margin:0;font-size:13.5px;color:var(--ink-secondary);">This removes <strong>' + escapeHtml(d.brand) + '</strong> (' + escapeHtml(d.appno) + ') from the ledger. This can\'t be undone from here.</p></div>' +
      '<div class="modal-footer"><span></span><div class="right-actions"><button class="btn btn-secondary" data-action="confirm-delete-no">Cancel</button>' +
      '<button class="btn btn-danger" data-action="confirm-delete-yes">Remove</button></div></div>' +
      '</div></div>';
  }

  /* ===================== Init ===================== */
  async function init() {
    applyTheme(getLocalPref(LOCAL_KEYS.theme, 'system'));
    attachHandlers();
    await initPersistence();
    renderAll();
    renderGate();
    maybeNotifyDeadlines();
    // Fire-and-forget: the accounts list only appears in Settings, and
    // loadUsers re-renders once it arrives.
    if (userCan('manage_users')) loadUsers();
    loadAssignees();
  }
  init();
})();
