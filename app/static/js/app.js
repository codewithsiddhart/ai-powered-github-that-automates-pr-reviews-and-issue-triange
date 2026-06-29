/* app.js — Shared UI logic: theme toggle, scroll animations */
(function () {
  'use strict';

  var THEME_KEY = 'gh-autopilot-theme';

  /* ── Theme ──────────────────────────────────────────────── */

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(THEME_KEY, theme);
  }

  function initTheme() {
    var saved = localStorage.getItem(THEME_KEY);
    applyTheme(saved === 'light' ? 'light' : 'dark');
  }

  function bindThemeToggle() {
    var btn = document.getElementById('themeToggle');
    if (!btn) return;
    btn.addEventListener('click', function () {
      var cur = document.documentElement.getAttribute('data-theme');
      applyTheme(cur === 'dark' ? 'light' : 'dark');
      /* Re-init icons after toggle (sun/moon switch) */
      if (typeof lucide !== 'undefined') { lucide.createIcons(); }
    });
  }

  /* ── Scroll animations via IntersectionObserver ─────────── */

  function initScrollAnimations() {
    if (!('IntersectionObserver' in window)) {
      /* Fallback: just make them all visible immediately */
      document.querySelectorAll('.feature-card, .step-card, .explainer-card').forEach(function (el) {
        el.classList.add('visible');
      });
      return;
    }

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });

    document.querySelectorAll('.feature-card, .step-card').forEach(function (el) {
      observer.observe(el);
    });
  }

  /* ── Smooth scroll ──────────────────────────────────────── */

  function initSmoothScroll() {
    document.querySelectorAll('a[href^="#"]').forEach(function (a) {
      a.addEventListener('click', function (e) {
        var target = document.querySelector(this.getAttribute('href'));
        if (target) {
          e.preventDefault();
          target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      });
    });
  }

  /* ── Boot ───────────────────────────────────────────────── */

  /* Apply theme immediately (before DOM ready) to prevent flash */
  initTheme();

  document.addEventListener('DOMContentLoaded', function () {
    bindThemeToggle();
    initSmoothScroll();
    initScrollAnimations();
  });

}());
