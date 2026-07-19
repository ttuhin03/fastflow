// Fast-Flow marketing site — small interaction layer, no build step required.
(function () {
  'use strict';

  // Nav background on scroll
  var nav = document.getElementById('nav');
  function onScroll() {
    if (window.scrollY > 8) nav.classList.add('scrolled');
    else nav.classList.remove('scrolled');
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  // Reveal-on-scroll
  var revealEls = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add('in');
            io.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12 }
    );
    revealEls.forEach(function (el) { io.observe(el); });
  } else {
    revealEls.forEach(function (el) { el.classList.add('in'); });
  }

  // Quick-start tabs
  var tabButtons = document.querySelectorAll('.quickstart-tabs button');
  var panels = document.querySelectorAll('.quickstart-panel');
  tabButtons.forEach(function (btn) {
    btn.addEventListener('click', function () {
      tabButtons.forEach(function (b) { b.classList.remove('active'); });
      panels.forEach(function (p) { p.classList.remove('active'); });
      btn.classList.add('active');
      var target = document.querySelector('.quickstart-panel[data-panel="' + btn.dataset.tab + '"]');
      if (target) target.classList.add('active');
    });
  });

  // Copy install command
  var copyBtn = document.getElementById('copy-cmd');
  if (copyBtn) {
    copyBtn.addEventListener('click', function () {
      var text = 'docker compose up -d';
      if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(showCopied, showCopied);
      } else {
        showCopied();
      }
    });
  }
  function showCopied() {
    var original = copyBtn.innerHTML;
    copyBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 8.5l3 3 7-7"/></svg>';
    setTimeout(function () { copyBtn.innerHTML = original; }, 1500);
  }

  // Smooth-scroll for in-page anchors (native scroll-behavior handles most,
  // this just accounts for the fixed nav height)
  document.querySelectorAll('a[href^="#"]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      var id = a.getAttribute('href').slice(1);
      var el = document.getElementById(id);
      if (!el) return;
      e.preventDefault();
      var top = el.getBoundingClientRect().top + window.scrollY - 64;
      window.scrollTo({ top: top, behavior: 'smooth' });
    });
  });
})();
