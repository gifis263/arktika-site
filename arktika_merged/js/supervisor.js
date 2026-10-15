/* Кабинет руководителя */
(function () {
  "use strict";

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);

  function esc(v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  async function api(url, options = {}) {
    const opts = Object.assign({ credentials: "same-origin" }, options);
    if (opts.json !== undefined) {
      opts.method = opts.method || "POST";
      opts.headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
      opts.body = JSON.stringify(opts.json);
    }
    const res = await fetch(url, opts);
    if (res.status === 401) { location.href = "/pages/auth.html#login"; return {}; }
    let data = {};
    try { data = await res.json(); } catch (_) { /* пусто */ }
    if (!res.ok) throw new Error(data.error || "Ошибка сервера");
    return data;
  }

  const linkBadge = (s) => {
    const map = { confirmed: ["badge--approved", "Подтверждён"],
      pending: ["badge--pending", "Ожидает подтверждения"] };
    const [cls, label] = map[s] || ["badge--soft", s || "—"];
    return `<span class="badge ${cls}">${esc(label)}</span>`;
  };

  function initMenu() {
    $$("#consoleMenu button").forEach((btn) => {
      btn.addEventListener("click", () => {
        $$("#consoleMenu button").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        $$(".panel").forEach((p) => p.classList.remove("active"));
        const panel = $("#panel-" + btn.dataset.section);
        if (panel) panel.classList.add("active");
      });
    });
  }

  async function loadUser() {
    try {
      const { user } = await api("/api/auth/me");
      $("#userName").textContent = (user.full_name || user.name) || "Руководитель";
      $("#userRole").textContent = user.role_label || "Руководитель";
      if (user.approval_status === "pending") {
        $("#pendingNote").innerHTML = `<div class="alert show alert--error">Ваша заявка на модерации оргкомитетом. Часть функций станет доступна после одобрения.</div>`;
      }
    } catch (_) { /* не критично */ }
  }

  async function loadSummary() {
    try {
      const s = await api("/api/supervisor/summary");
      const tile = (n, l) => `<div class="kpi"><div class="kpi__num">${esc(n)}</div><div class="kpi__label">${esc(l)}</div></div>`;
      $("#kpiGrid").innerHTML =
        tile(s.participants, "Участников всего") +
        tile(s.confirmed, "Подтверждено") +
        tile(s.projects, "Проектов") +
        tile(s.certificate_ready ? "Да" : "Нет", "Сертификат доступен");
    } catch (e) {
      $("#kpiGrid").innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
  }

  async function loadParticipants() {
    const box = $("#participantsBox");
    box.innerHTML = '<div class="empty">Загрузка…</div>';
    try {
      const { participants } = await api("/api/supervisor/participants");
      if (!participants.length) {
        box.innerHTML = '<div class="empty">Пока нет прикреплённых участников.</div>';
        return;
      }
      box.innerHTML = participants.map((p) => {
        const projects = (p.projects || []).map((pr) => {
          let action;
          if (pr.supervisor_confirmed) {
            action = `<span class="badge badge--approved">Заявка подтверждена</span>
              <button class="btn btn--ghost btn--sm" data-unconfirm="${pr.id}" type="button">Снять подтверждение</button>`;
          } else if (pr.status === "draft") {
            action = `<span class="muted">Черновик — участник ещё не отправил заявку.</span>`;
          } else {
            action = `<button class="btn btn--primary btn--sm" data-confirm="${pr.id}" type="button">Подтвердить заявку</button>`;
          }
          return `<div class="review"><div class="review__head"><span>${esc(pr.title)}</span>
           <span class="badge badge--${esc(pr.status)}">${esc(pr.status_label)}</span></div>
           <div class="review__comment">Номинация: ${esc(pr.nomination || "—")} · ${esc(pr.created_at || "")}</div>
           <div style="margin-top:.6rem; display:flex; gap:.6rem; align-items:center; flex-wrap:wrap">${action}</div></div>`;
        }).join("") || '<p class="muted">Проекты не загружены.</p>';
        return `<div class="item">
          <div class="item__head">
            <div>
              <div class="item__title">${esc(p.name)}</div>
              <div class="item__meta">${esc(p.school || "—")} · ${esc(p.grade || "")} · ${esc(p.region || "")}</div>
              <div class="item__meta">${esc(p.email || "")}</div>
            </div>
            ${linkBadge(p.link_status)}
          </div>
          <div style="margin-top:.8rem">${projects}</div>
        </div>`;
      }).join("");
      box.querySelectorAll("[data-confirm]").forEach((b) =>
        b.addEventListener("click", () => setConfirm(b.dataset.confirm, true)));
      box.querySelectorAll("[data-unconfirm]").forEach((b) =>
        b.addEventListener("click", () => setConfirm(b.dataset.unconfirm, false)));
    } catch (e) {
      box.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
  }

  async function setConfirm(pid, state) {
    try {
      await api("/api/supervisor/projects/" + pid + "/confirm",
        { method: state ? "POST" : "DELETE" });
      loadParticipants();
      loadSummary();
    } catch (e) {
      alert(e.message);
    }
  }

  function initCertificate() {
    $("#certBtn").addEventListener("click", async () => {
      const alert = $("#certAlert");
      try {
        const res = await fetch("/api/supervisor/certificate.pdf", { credentials: "same-origin" });
        if (!res.ok) {
          const d = await res.json().catch(() => ({}));
          throw new Error(d.error || "Сертификат пока недоступен.");
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        window.open(url, "_blank");
        setTimeout(() => URL.revokeObjectURL(url), 60000);
        alert.className = "alert show alert--ok";
        alert.textContent = "Сертификат сформирован.";
      } catch (e) {
        alert.className = "alert show alert--error";
        alert.textContent = e.message;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initMenu();
    initCertificate();
    loadUser();
    loadSummary();
    loadParticipants();
  });
})();
