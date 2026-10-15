/* Динамический контент сайта из админ-панели (публичные API). */
(function () {
  "use strict";

  const esc = (v) => String(v == null ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

  const fmtDate = (s) => {
    const d = String(s || "").slice(0, 10).split("-");
    return d.length === 3 ? d[2] + "." + d[1] + "." + d[0] : String(s || "");
  };

  async function getJSON(url) {
    const res = await fetch(url, { headers: { Accept: "application/json" } });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }

  const STAGE_LABEL = { planned: "Запланирован", active: "Идёт", finished: "Завершён" };
  const STAGE_BADGE = { planned: "draft", active: "accepted", finished: "evaluated" };

  function hideIfEmpty(box) {
    if (box.dataset.hide === "section") {
      const sec = box.closest("section");
      if (sec) sec.style.display = "none";
      return;
    }
    box.style.display = "none";
    const prev = box.previousElementSibling;
    if (prev && /^H[1-6]$/.test(prev.tagName)) prev.style.display = "none";
  }

  async function renderNews(box) {
    const { news } = await getJSON("/api/news");
    const items = news || [];
    if (!items.length) return;
    const limit = Number(box.dataset.limit) || 0;
    const list = limit ? items.slice(0, limit) : items;
    box.innerHTML = list.map((n) => `<article class="news-card">
      <div class="news-card__date">${esc(fmtDate(n.created_at))}</div>
      <h3 class="news-card__title">${esc(n.title)}</h3>
      <p class="news-card__text">${esc((n.body || "").slice(0, 180))}</p>
      <a href="/news/news-detail.html?id=${encodeURIComponent(n.id)}" class="news-card__link">Подробнее</a>
    </article>`).join("");
  }

  async function renderNewsDetail(box) {
    const id = new URLSearchParams(location.search).get("id");
    if (!id) return;
    const { news } = await getJSON("/api/news");
    const item = (news || []).find((n) => String(n.id) === String(id));
    if (!item) return;
    document.title = item.title + " — Новости";
    box.innerHTML = `
      <div class="news-card__date">${esc(fmtDate(item.created_at))}</div>
      <h1 style="color: var(--primary-blue); margin-bottom: 1.5rem; font-size: 2rem;">${esc(item.title)}</h1>
      ${item.image ? `<img src="${esc(item.image)}" alt="${esc(item.title)}" style="max-width:100%;border-radius:10px;margin-bottom:1.2rem">` : ""}
      ${String(item.body || "").split(/\n+/).filter(Boolean).map((p) =>
        `<p style="color: var(--text-dark); line-height: 1.8; margin-bottom: 1.2rem;">${esc(p)}</p>`).join("")}`;
  }

  async function renderMedia(box) {
    const { media } = await getJSON("/api/media");
    const items = media || [];
    if (!items.length) { hideIfEmpty(box); return; }
    box.innerHTML = items.map((m) => {
      const label = m.kind === "video" ? "Смотреть видео" : m.kind === "image" ? "Смотреть фото" : "Открыть";
      const link = m.url
        ? `<a href="${esc(m.url)}" class="news-card__link" target="_blank" rel="noopener">${label}</a>` : "";
      return `<div class="card">
        <h3 class="card__title">${esc(m.title)}</h3>
        <p class="card__text">${esc(m.description || "")}</p>
        ${link}
      </div>`;
    }).join("");
  }

  async function renderStages(box) {
    const { stages } = await getJSON("/api/stages");
    const items = stages || [];
    if (!items.length) { hideIfEmpty(box); return; }
    box.innerHTML = items.map((s) => `<div class="card">
      <h3 class="card__title">${esc(s.name)}</h3>
      <p class="card__text">${esc(fmtDate(s.start_date))}${s.end_date ? " — " + esc(fmtDate(s.end_date)) : ""}</p>
      <p class="card__text"><span class="badge badge--${esc(STAGE_BADGE[s.status] || "draft")}">${esc(STAGE_LABEL[s.status] || s.status || "")}</span></p>
    </div>`).join("");
  }

  async function renderNominations(box) {
    const { nominations } = await getJSON("/api/nominations");
    const items = nominations || [];
    if (!items.length) { hideIfEmpty(box); return; }
    box.innerHTML = items.map((n) => `<div class="card">
      <h3 class="card__title">${esc(n.name)}</h3>
      <p class="card__text">${esc(n.description || "")}</p>
    </div>`).join("");
  }

  async function renderCriteria(box) {
    const { criteria } = await getJSON("/api/criteria");
    const items = criteria || [];
    if (!items.length) return;
    box.innerHTML = items.map((c) => `<div class="card">
      <h3 class="card__title">${esc(c.name)}</h3>
      <p class="card__text">${esc(c.description || "")}</p>
      <p class="card__text"><span class="badge badge--soft">коэф. ${esc(c.weight)} · макс. ${esc(c.max_score)}</span></p>
    </div>`).join("");
  }

  async function renderBanners(box) {
    const { banners } = await getJSON("/api/banners");
    const b = (banners || [])[0];
    if (!b) { hideIfEmpty(box); return; }
    box.innerHTML = `<div class="card" style="text-align:center">
      <h3 class="card__title">${esc(b.title)}</h3>
      <p class="card__text">${esc(b.text || "")}</p>
      ${b.cta ? `<a href="${esc(b.link || "#")}" class="btn btn--primary">${esc(b.cta)}</a>` : ""}
    </div>`;
  }

  const RENDERERS = {
    news: renderNews,
    "news-detail": renderNewsDetail,
    media: renderMedia,
    stages: renderStages,
    nominations: renderNominations,
    criteria: renderCriteria,
    banners: renderBanners,
  };

  function init() {
    document.querySelectorAll("[data-site]").forEach((box) => {
      const fn = RENDERERS[box.dataset.site];
      if (fn) fn(box).catch(() => { /* оставляем статический контент */ });
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
