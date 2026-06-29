/* dashboard.js — Live dashboard: fetches /api/dashboard and /api/events/recent every 30s */
(function () {
  'use strict';

  var REFRESH_MS = 30000;

  /* ── Helpers ──────────────────────────────────────────────── */

  function timeAgo(ts) {
    var diff = Math.floor(Date.now() / 1000) - ts;
    if (diff < 5)   return 'just now';
    if (diff < 60)  return diff + 's ago';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
  }

  function fmtSeconds(s) {
    if (!s || s <= 0) return '—';
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var sec = s % 60;
    if (h > 0) return h + 'h ' + m + 'm';
    if (m > 0) return m + 'm ' + sec + 's';
    return sec + 's';
  }

  function setMetric(key, val) {
    document.querySelectorAll('[data-metric="' + key + '"]').forEach(function (el) {
      el.textContent = (val !== null && val !== undefined) ? String(val) : '—';
    });
  }

  function setProgress(id, pct, dangerThreshold, warnThreshold) {
    var fill = document.getElementById(id);
    if (!fill) return;
    var p = Math.min(100, Math.max(0, pct || 0));
    fill.style.width = p + '%';
    fill.className = fill.className.replace(/\s*fill--\w+/g, '');
    if (p >= (dangerThreshold || 80)) fill.className += ' fill--danger';
    else if (p >= (warnThreshold || 50)) fill.className += ' fill--warn';
  }

  /* ── Status banner ────────────────────────────────────────── */

  function updateBanner(data) {
    var dot    = document.getElementById('statusDot');
    var text   = document.getElementById('statusText');
    var banner = document.getElementById('statusBanner');
    if (!dot || !text || !banner) return;

    var s = data.status || 'unknown';
    var map = {
      ok:       { dot: 'dot--ok',       text: '● All Systems Operational',  cls: 'status-banner--ok' },
      partial:  { dot: 'dot--degraded', text: '⚠ Partial Degradation',       cls: 'status-banner--partial' },
      degraded: { dot: 'dot--error',    text: '✕ System Degraded',           cls: 'status-banner--degraded' },
    };
    var info = map[s] || { dot: '', text: 'Status Unknown', cls: 'status-banner--unknown' };

    dot.className  = 'status-banner-dot ' + info.dot;
    text.textContent = info.text;
    banner.className = 'status-banner ' + info.cls;
  }

  /* ── AI providers ─────────────────────────────────────────── */

  function updateProviders(providers) {
    if (!providers) return;
    Object.keys(providers).forEach(function (name) {
      var info = providers[name];
      var row  = document.querySelector('[data-provider="' + name + '"]');
      if (!row) return;
      var badge = row.querySelector('.provider-state-badge');
      if (!badge) return;
      var state = (info.state || 'unknown').toLowerCase();
      badge.textContent = state.replace('_', ' ');
      badge.className   = 'provider-state-badge state--' + state;
    });
  }

  /* ── Redis ───────────────────────────────────────────────── */

  function updateRedis(redis) {
    var dot  = document.getElementById('redisDot');
    var text = document.getElementById('redisText');
    if (!dot || !text) return;
    var ok = redis && redis.connected;
    dot.style.background = ok ? 'var(--green)' : 'var(--red)';
    text.textContent = ok ? 'Connected' : 'Unavailable — in-memory fallback active';
  }

  /* ── Thread pool ─────────────────────────────────────────── */

  function updatePool(pool) {
    if (!pool) return;
    setMetric('pool_max_workers', pool.max_workers);
    setMetric('pool_pending',     pool.pending_tasks);
    setMetric('pool_capacity',    pool.queue_capacity);
    var pct = pool.saturation_pct || 0;
    setMetric('pool_saturation',  pct.toFixed(1) + '%');
    setProgress('saturationFill', pct, 80, 50);
  }

  /* ── GitHub API ──────────────────────────────────────────── */

  function updateGhApi(gh) {
    if (!gh) return;
    var rem = gh.remaining !== undefined ? gh.remaining : (gh.remaining || 0);
    setMetric('gh_api_remaining', typeof rem === 'number' ? rem.toLocaleString() : rem);
    var resets = gh.resets_in !== undefined ? gh.resets_in : (gh.resets_in || 0);
    setMetric('gh_api_resets_human', fmtSeconds(resets));
    var pct = Math.min(100, ((rem || 0) / 5000) * 100);
    setProgress('ghRlFill', pct, 10, 30);
  }

  /* ── Events by type ──────────────────────────────────────── */

  var TYPE_LABELS = {
    pull_request:  'Pull Request',
    issues:        'Issues',
    issue_comment: 'Issue Comment',
    push:          'Push',
    check_run:     'Check Run',
  };

  function updateEventTypes(types) {
    var list = document.getElementById('eventTypesList');
    if (!list || !types) return;
    var html = '';
    var order = ['pull_request', 'push', 'issues', 'issue_comment', 'check_run'];
    order.forEach(function (key) {
      var c = types[key] || { queued: 0, success: 0, error: 0 };
      var label = TYPE_LABELS[key] || key;
      html += '<div class="event-type-row">' +
        '<span class="event-type-name">' + label + '</span>' +
        '<span class="event-type-counts">' +
          '<span class="count-badge count--queued">' + (c.queued || 0) + ' q</span>' +
          '<span class="count-badge count--ok">' + (c.success || 0) + ' ✓</span>' +
          (c.error > 0 ? '<span class="count-badge count--err">' + c.error + ' ✗</span>' : '') +
        '</span>' +
      '</div>';
    });
    list.innerHTML = html || '<div class="loading-placeholder">No data yet</div>';
  }

  /* ── Update all dashboard metrics ───────────────────────── */

  function applyDashboard(data) {
    updateBanner(data);
    updateProviders(data.providers);
    updateRedis(data.redis);
    updatePool(data.thread_pool);
    updateGhApi(data.github_api);
    updateEventTypes(data.event_types);

    var m = data.metrics || {};
    setMetric('github_app_id',      data.github_app_id);
    setMetric('webhook_received',   m.webhook_received);
    setMetric('webhook_duplicates', m.webhook_duplicates);
    setMetric('events_dropped',     m.events_dropped);
    setMetric('events_total',       m.events_total);
    setMetric('events_error',       m.events_error);
    setMetric('success_rate',       m.success_rate_pct !== undefined ? m.success_rate_pct + '%' : '—');
    setMetric('uptime_human',       data.uptime_human);
    setMetric('version',            data.version);

    var now = new Date().toLocaleTimeString();
    var lu  = document.getElementById('lastUpdated');
    var luf = document.getElementById('lastUpdatedFooter');
    if (lu)  lu.textContent  = now;
    if (luf) luf.textContent = now;
  }

  /* ── Events table ────────────────────────────────────────── */

  var EVENT_COLORS = {
    pull_request:  'pull_request',
    push:          'push',
    issues:        'issues',
    issue_comment: 'issue_comment',
    check_run:     'check_run',
  };

  function applyEvents(evData) {
    var tbody = document.getElementById('eventsTableBody');
    var count = document.getElementById('eventsCount');
    if (!tbody) return;

    var events = (evData && evData.events) ? evData.events : [];
    if (count) count.textContent = events.length + ' event' + (events.length !== 1 ? 's' : '');

    if (events.length === 0) {
      tbody.innerHTML = '<tr class="table-empty-row"><td colspan="5">No webhook events recorded yet — they appear here as webhooks arrive.</td></tr>';
      return;
    }

    tbody.innerHTML = events.map(function (ev) {
      var statusCls = (ev.status === 'accepted' || ev.status === 'ok') ? 'badge--ok' : 'badge--warn';
      var evColor   = EVENT_COLORS[ev.event] || '';
      return '<tr>' +
        '<td><span class="event-type-badge" data-event="' + (ev.event || '') + '">' + (ev.event || '—') + '</span></td>' +
        '<td class="repo-cell">' + escHtml(ev.repo || '—') + '</td>' +
        '<td class="mono">' + escHtml(ev.delivery_id || '—') + '</td>' +
        '<td class="time-cell">' + (ev.timestamp ? timeAgo(ev.timestamp) : '—') + '</td>' +
        '<td><span class="status-badge ' + statusCls + '">' + escHtml(ev.status || '—') + '</span></td>' +
      '</tr>';
    }).join('');
  }

  function escHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* ── Fetch and refresh ───────────────────────────────────── */

  function refresh() {
    Promise.all([
      fetch('/api/dashboard').then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); }),
      fetch('/api/events/recent').then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); }),
    ]).then(function (results) {
      applyDashboard(results[0]);
      applyEvents(results[1]);
      /* Re-init Lucide icons in dynamically added content */
      if (typeof lucide !== 'undefined') { lucide.createIcons(); }
    }).catch(function (err) {
      console.warn('[dashboard] refresh failed:', err);
    });
  }

  /* ── Boot ────────────────────────────────────────────────── */

  document.addEventListener('DOMContentLoaded', function () {
    /* First load */
    refresh();

    /* Bind manual refresh button */
    var btn = document.getElementById('refreshBtn');
    if (btn) {
      btn.addEventListener('click', function () {
        var icon = btn.querySelector('[data-lucide="refresh-cw"]');
        if (icon) { icon.style.animation = 'spin 0.6s linear'; }
        refresh();
        setTimeout(function () {
          if (icon) { icon.style.animation = ''; }
        }, 600);
      });
    }

    /* Auto-refresh */
    setInterval(refresh, REFRESH_MS);
  });

}());
