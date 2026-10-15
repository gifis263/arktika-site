(function () {
  'use strict';
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  if (document.getElementById('snowfall-layer')) return;

  function initSnowfall() {
    if (!document.body || document.getElementById('snowfall-layer')) return;
    const layer = document.createElement('div');
    layer.id = 'snowfall-layer';
    layer.setAttribute('aria-hidden', 'true');
    document.body.appendChild(layer);

    // Меньше снежинок на мобильных устройствах, чтобы не перегружать страницу.
    const count = Math.min(34, Math.max(14, Math.floor(window.innerWidth / 38)));
    for (let i = 0; i < count; i += 1) {
      const flake = document.createElement('span');
      flake.className = 'snowflake';
      flake.textContent = Math.random() > 0.45 ? '❄' : '·';
      flake.style.left = `${Math.random() * 100}%`;
      flake.style.opacity = `${0.3 + Math.random() * 0.5}`;
      flake.style.fontSize = `${7 + Math.random() * 10}px`;
      flake.style.setProperty('--drift', `${-35 + Math.random() * 70}px`);
      flake.style.animationDuration = `${10 + Math.random() * 13}s`;
      flake.style.animationDelay = `${-Math.random() * 23}s`;
      layer.appendChild(flake);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSnowfall, { once: true });
  } else {
    initSnowfall();
  }
})();
