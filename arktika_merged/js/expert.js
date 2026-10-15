/* Кабинет эксперта */
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

  function alertBox(el, msg, ok) {
    if (!el) return;
    el.className = "alert show " + (ok ? "alert--ok" : "alert--error");
    el.textContent = msg;
  }

  function statusBadge(s, label) {
    return `<span class="badge badge--${esc(s)}">${esc(label || s)}</span>`;
  }

  function showSection(section) {
    $$(".panel").forEach((p) => p.classList.remove("active"));
    const panel = $("#panel-" + section);
    if (panel) panel.classList.add("active");
    $$("#consoleMenu button").forEach((b) => b.classList.toggle("active", b.dataset.section === section));
    if (section === "ranking") loadRanking();
  }

  function initMenu() {
    $$("#consoleMenu button").forEach((btn) => {
      btn.addEventListener("click", () => showSection(btn.dataset.section));
    });
  }

  async function loadUser() {
    try {
      const { user } = await api("/api/auth/me");
      $("#userName").textContent = (user.full_name || user.name) || "Эксперт";
      $("#userRole").textContent = (user.role_label || "Эксперт") + (user.expertise ? " · " + user.expertise : "");
    } catch (_) { /* не критично */ }
  }

  let assignmentsCache = [];

  async function loadWorks() {
    const box = $("#worksBox");
    box.innerHTML = '<div class="empty">Загрузка…</div>';
    try {
      const { assignments } = await api("/api/expert/assignments");
      assignmentsCache = assignments || [];
      if (!assignmentsCache.length) {
        box.innerHTML = '<div class="empty">Нет назначенных работ. Нажмите «Распределить работы автоматически» в обзоре.</div>';
        updateKpi();
        return;
      }
      box.innerHTML = `<div class="table-wrap"><table class="data-table">
        <thead><tr><th>№</th><th>Работа</th><th>Участник</th><th>Номинация</th><th>Статус</th><th>Балл</th><th></th></tr></thead>
        <tbody>${assignmentsCache.map((a) => `<tr>
          <td>${a.project_id}</td>
          <td><strong>${esc(a.title)}</strong><div class="muted">${esc(a.mode === "auto" ? "авто" : "вручную")}</div></td>
          <td>${esc(a.participant_name || "—")}<div class="muted">${esc(a.school || "")}</div></td>
          <td>${esc(a.nomination || "—")}</td>
          <td>${a.evaluated ? '<span class="badge badge--evaluated">Оценена</span>' : statusBadge(a.status, a.status_label)}</td>
          <td>${a.total_score != null ? esc(a.total_score) : "—"}</td>
          <td>
            <button class="btn btn--primary btn--sm" data-eval="${a.project_id}" type="button">${a.evaluated ? "Изменить" : "Оценить"}</button>
            <button class="btn btn--ghost btn--sm" data-remove="${a.assignment_id}" type="button">Снять</button>
          </td>
        </tr>`).join("")}</tbody></table></div>`;
      box.querySelectorAll("[data-eval]").forEach((b) =>
        b.addEventListener("click", () => { openProject(Number(b.dataset.eval)); showSection("evaluate"); }));
      box.querySelectorAll("[data-remove]").forEach((b) =>
        b.addEventListener("click", () => removeAssignment(Number(b.dataset.remove))));
      updateKpi();
    } catch (e) {
      box.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
  }

  function updateKpi() {
    const total = assignmentsCache.length;
    const done = assignmentsCache.filter((a) => a.evaluated).length;
    const avg = done ? (assignmentsCache.reduce((s, a) => s + (a.total_score || 0), 0) / done).toFixed(1) : "—";
    const tile = (n, l) => `<div class="kpi"><div class="kpi__num">${esc(n)}</div><div class="kpi__label">${esc(l)}</div></div>`;
    $("#kpiGrid").innerHTML = tile(total, "Назначено работ") + tile(done, "Оценено") +
      tile(total - done, "Осталось") + tile(avg, "Средний балл");
  }

  async function removeAssignment(aid) {
    if (!confirm("Снять назначение с этой работы?")) return;
    try {
      await api("/api/expert/assignments/" + aid, { method: "DELETE" });
      loadWorks();
    } catch (e) { alertBox($("#overviewAlert"), e.message, false); }
  }

  function initActions() {
    $("#autoBtn").addEventListener("click", async () => {
      try {
        const d = await api("/api/expert/assignments/auto", { json: {} });
        alertBox($("#overviewAlert"), d.message, true);
        loadWorks();
      } catch (e) { alertBox($("#overviewAlert"), e.message, false); }
    });
    $("#refreshBtn").addEventListener("click", () => { loadWorks(); loadRanking(); });
    $("#openProjectBtn").addEventListener("click", () => {
      const id = Number($("#evalProjectId").value);
      if (!id) { alertBox($("#overviewAlert"), "Укажите номер проекта.", false); return; }
      openProject(id);
      showSection("evaluate");
    });
  }

  let currentProject = null;

  async function openProject(pid) {
    const box = $("#evalBox");
    box.innerHTML = '<div class="empty">Загрузка…</div>';
    try {
      const d = await api("/api/expert/project/" + pid);
      currentProject = d;
      const saved = d.scores || {};
      const ev = d.evaluation || {};
      box.innerHTML = `
        <div class="card" style="margin-bottom:1rem">
          <h3>${esc(d.project.title)}</h3>
          <p class="muted">${esc(d.project.nomination || "")} · Автор: ${esc(d.project.participant_name || "—")} · ${esc(d.project.school || "")}</p>
          <p>${esc(d.project.abstract || "")}</p>
        </div>
        <div id="criteriaBox">${d.criteria.map((c) => {
          const s = saved[String(c.id)] || {};
          const val = s.score != null ? s.score : Math.round(c.max_score / 2);
          return `<div class="score-row" data-crit="${c.id}">
            <div class="score-row__head">
              <span class="score-row__name">${esc(c.name)}</span>
              <span class="score-row__weight">коэф. ${esc(c.weight)} · макс. ${esc(c.max_score)}</span>
            </div>
            ${c.description ? `<div class="muted">${esc(c.description)}</div>` : ""}
            <input type="range" min="0" max="${c.max_score}" step="1" value="${val}" data-range>
            <div>Балл: <span class="score-value" data-val>${val}</span> из ${c.max_score}</div>
            <textarea placeholder="Комментарий по критерию">${esc(s.comment || "")}</textarea>
          </div>`;
        }).join("")}</div>
        <div class="field field--full" style="margin-top:1rem">
          <label for="evalComment">Общий комментарий</label>
          <textarea id="evalComment" placeholder="Комментарий к работе">${esc(ev.comment || "")}</textarea>
        </div>
        <div class="field field--full">
          <label for="evalReco">Рекомендация</label>
          <input id="evalReco" maxlength="2000" placeholder="Например: рекомендовать к защите" value="${esc(ev.recommendation || "")}">
        </div>
        <div class="form-actions">
          <button class="btn btn--primary" id="saveEvalBtn" type="button">Сохранить оценку</button>
          <span class="muted" id="evalTotalNote"></span>
        </div>
        <div class="alert" id="evalAlert"></div>`;

      box.querySelectorAll(".score-row").forEach((row) => {
        const range = row.querySelector("[data-range]");
        const val = row.querySelector("[data-val]");
        range.addEventListener("input", () => { val.textContent = range.value; });
      });
      $("#saveEvalBtn").addEventListener("click", saveEvaluation);
      updateTotalNote();
    } catch (e) {
      box.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
  }

  function updateTotalNote() {
    if (!currentProject) return;
    const crits = currentProject.criteria;
    let total = 0;
    crits.forEach((c) => {
      const row = document.querySelector(`.score-row[data-crit="${c.id}"]`);
      if (!row) return;
      const v = Number(row.querySelector("[data-range]").value);
      total += (Math.min(v, c.max_score) / c.max_score) * c.weight;
    });
    $("#evalTotalNote").textContent = "Предварительный балл: " + (total * 100).toFixed(1);
  }

  async function saveEvaluation() {
    if (!currentProject) return;
    const scores = {};
    currentProject.criteria.forEach((c) => {
      const row = document.querySelector(`.score-row[data-crit="${c.id}"]`);
      scores[String(c.id)] = {
        score: Number(row.querySelector("[data-range]").value),
        comment: row.querySelector("textarea").value,
      };
    });
    try {
      const d = await api("/api/expert/evaluations", { json: {
        project_id: currentProject.project.id,
        scores,
        comment: $("#evalComment").value,
        recommendation: $("#evalReco").value,
      }});
      alertBox($("#evalAlert"), `${d.message} Итоговый балл: ${d.total_score}.`, true);
      loadWorks();
      showSection("works");
    } catch (e) { alertBox($("#evalAlert"), e.message, false); }
  }

  async function loadRanking() {
    const box = $("#rankingBox");
    box.innerHTML = '<div class="empty">Загрузка…</div>';
    try {
      const { ranking } = await api("/api/expert/ranking");
      if (!ranking.length) { box.innerHTML = '<div class="empty">Пока нет оценённых работ.</div>'; return; }
      box.innerHTML = `<div class="table-wrap"><table class="data-table">
        <thead><tr><th>Место</th><th>Работа</th><th>Номинация</th><th>Средний балл</th><th>Оценок</th></tr></thead>
        <tbody>${ranking.map((r) => `<tr class="rank-${r.rank}">
          <td><strong>${r.rank}</strong></td><td>${esc(r.title)}</td>
          <td>${esc(r.nomination || "—")}</td><td>${esc(r.avg_score)}</td><td>${r.reviews}</td>
        </tr>`).join("")}</tbody></table></div>`;
    } catch (e) {
      box.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    initMenu();
    initActions();
    loadUser();
    loadWorks();
  });
})();
