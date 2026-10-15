/* Панель оргкомитета (администратора) */
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
    if (res.status === 403) { location.href = "/index.html"; return {}; }
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

  const STATUS_LABELS = { draft: "Черновик", review: "На проверке", accepted: "Допущена",
    expertise: "На экспертизе", evaluated: "Оценена" };
  const STATUS_ORDER = ["draft", "review", "accepted", "expertise", "evaluated"];
  const APPROVAL = { pending: ["badge--pending", "На модерации"], approved: ["badge--approved", "Одобрен"],
    blocked: ["badge--blocked", "Заблокирован"] };
  const ROLE_LABELS = { participant: "Участник", supervisor: "Руководитель", expert: "Эксперт",
    commission: "Член комиссии", admin: "Администратор", partner: "Партнёр" };

  /* ------------------------- Конфигурация ресурсов ------------------------ */
  const RESOURCES = {
    news: { title: "Новости", sub: "Публикации новостей на сайте.", label: "новость", fields: [
      { k: "title", label: "Заголовок", req: true },
      { k: "category", label: "Категория" },
      { k: "image", label: "Изображение (URL)" },
      { k: "body", label: "Текст", type: "textarea", req: true, full: true },
      { k: "published", label: "Опубликовано", type: "bool" }] },
    media: { title: "Медиатека", sub: "Видео, фото, документы.", label: "материал", fields: [
      { k: "title", label: "Название", req: true },
      { k: "kind", label: "Тип", type: "select", options: ["video", "image", "audio", "doc"] },
      { k: "url", label: "Ссылка", full: true },
      { k: "description", label: "Описание", type: "textarea", full: true }] },
    banners: { title: "Баннеры и CTA", sub: "Призывы к действию и баннеры на главной.", label: "баннер", fields: [
      { k: "title", label: "Заголовок", req: true },
      { k: "cta", label: "Текст кнопки" },
      { k: "link", label: "Ссылка" },
      { k: "text", label: "Текст", type: "textarea", full: true },
      { k: "active", label: "Активен", type: "bool" }] },
    stages: { title: "Этапы конкурса", sub: "Календарь этапов и их статусы.", label: "этап", fields: [
      { k: "name", label: "Название", req: true },
      { k: "start_date", label: "Начало", type: "date" },
      { k: "end_date", label: "Окончание", type: "date" },
      { k: "status", label: "Статус", type: "select", options: ["planned", "active", "finished"] },
      { k: "order_index", label: "Порядок", type: "number" },
      { k: "auto_advance", label: "Автопереход", type: "bool" }] },
    nominations: { title: "Номинации", sub: "Номинации конкурсных работ.", label: "номинацию", fields: [
      { k: "name", label: "Название", req: true },
      { k: "description", label: "Описание", type: "textarea", full: true },
      { k: "active", label: "Активна", type: "bool" }] },
    criteria: { title: "Критерии оценивания", sub: "Весовые коэффициенты и максимальные баллы.", label: "критерий", fields: [
      { k: "name", label: "Название", req: true },
      { k: "weight", label: "Коэффициент", type: "number", step: "0.01" },
      { k: "max_score", label: "Макс. балл", type: "number" },
      { k: "description", label: "Описание", type: "textarea", full: true },
      { k: "active", label: "Активен", type: "bool" }] },
    questions: { title: "Банк вопросов", sub: "Вопросы тестирования I этапа.", label: "вопрос", fields: [
      { k: "topic", label: "Тема" },
      { k: "difficulty", label: "Сложность", type: "select", options: ["лёгкий", "средний", "сложный"] },
      { k: "text", label: "Текст вопроса", type: "textarea", req: true, full: true },
      { k: "option_a", label: "Вариант A" }, { k: "option_b", label: "Вариант B" },
      { k: "option_c", label: "Вариант C" }, { k: "option_d", label: "Вариант D" },
      { k: "correct_option", label: "Верный вариант", type: "select", options: ["a", "b", "c", "d"] },
      { k: "explanation", label: "Пояснение", type: "textarea", full: true }] },
  };

  /* ---------------------------------------------------------------------- */
  function setPendingBadge(n) {
    const b = $("#pendingBadge");
    if (!b) return;
    if (n > 0) { b.textContent = n; b.style.display = "inline-block"; }
    else { b.style.display = "none"; }
  }

  async function refreshPendingBadge() {
    try { const s = await api("/api/admin/stats"); setPendingBadge(s.pending); } catch (_) { /* не критично */ }
  }

  async function loadUser() {
    try {
      const { user } = await api("/api/auth/me");
      $("#userName").textContent = (user.full_name || user.name) || "Администратор";
      $("#userRole").textContent = user.role_label || "Администратор";
    } catch (_) { /* не критично */ }
  }

  function initMenu() {
    $$("#consoleMenu button").forEach((btn) => {
      btn.addEventListener("click", () => {
        $$("#consoleMenu button").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        $$(".panel").forEach((p) => p.classList.remove("active"));
        const panel = $("#panel-" + btn.dataset.section);
        if (panel) panel.classList.add("active");
        const s = btn.dataset.section;
        if (s === "dashboard") loadDashboard();
        else if (s === "users") loadUsers();
        else if (s === "experts") loadExperts();
        else if (s === "projects") loadProjects();
        else if (s === "comments") loadComments();
        else if (s === "mailings") loadMailings();
        else if (s === "reports") loadReport();
        else if (s === "resource") openResource(btn.dataset.resource);
      });
    });
  }

  /* ------------------------------ Дашборд -------------------------------- */
  function bars(target, rows, labelKey, valueKey) {
    const el = $(target);
    if (!rows || !rows.length) { el.innerHTML = '<div class="muted">Нет данных.</div>'; return; }
    const max = Math.max(...rows.map((r) => r[valueKey] || 0)) || 1;
    el.innerHTML = rows.map((r) => `<div class="bar-row">
      <span class="bar-row__label" title="${esc(r[labelKey] || "—")}">${esc(r[labelKey] || "—")}</span>
      <span class="bar-row__track"><span class="bar-row__fill" style="width:${(r[valueKey] / max * 100).toFixed(1)}%"></span></span>
      <span class="bar-row__val">${esc(r[valueKey])}</span></div>`).join("");
  }

  async function loadDashboard() {
    try {
      const s = await api("/api/admin/stats");
      const tile = (n, l) => `<div class="kpi"><div class="kpi__num">${esc(n)}</div><div class="kpi__label">${esc(l)}</div></div>`;
      $("#dashKpi").innerHTML = tile(s.users.conn_users, "Пользователей") + tile(s.participants, "Участников") +
        tile(s.supervisors, "Руководителей") + tile(s.experts, "Экспертов") + tile(s.pending, "На модерации") +
        tile(s.projects, "Проектов") + tile(s.certificates, "Сертификатов") +
        tile(s.regions_count, "Регионов") + tile(s.schools_count, "Школ");
      const statusRows = STATUS_ORDER.map((k) => ({ name: STATUS_LABELS[k], c: (s.projects_by_status || {})[k] || 0 }));
      bars("#dashStatus", statusRows, "name", "c");
      bars("#dashNom", s.nominations || [], "nomination", "c");
      bars("#dashRegions", s.regions || [], "region", "c");
      bars("#dashSchools", s.schools || [], "school", "c");
      setPendingBadge(s.pending);
    } catch (e) {
      $("#dashKpi").innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
  }

  /* ---------------------------- Пользователи ----------------------------- */
  async function loadUsers() {
    const box = $("#usersBox");
    box.innerHTML = '<div class="empty">Загрузка…</div>';
    const params = new URLSearchParams();
    if ($("#userRoleFilter").value) params.set("role", $("#userRoleFilter").value);
    if ($("#userStatusFilter").value) params.set("status", $("#userStatusFilter").value);
    try {
      const { users } = await api("/api/admin/users?" + params.toString());
      if (!users.length) { box.innerHTML = '<div class="empty">Пользователи не найдены.</div>'; return; }
      box.innerHTML = `<div class="table-wrap"><table class="data-table">
        <thead><tr><th>ID</th><th>ФИО</th><th>Email</th><th>Роль</th><th>Организация</th><th>Статус</th><th>ПДн</th><th>Действия</th></tr></thead>
        <tbody>${users.map((u) => {
          const [cls, label] = APPROVAL[u.approval_status] || ["badge--soft", u.approval_status];
          return `<tr>
            <td>${u.id}</td><td>${esc(u.name)}<div class="muted">${esc(u.created_at || "")}</div></td>
            <td>${esc(u.email)}</td>
            <td><select data-role="${u.id}" class="role-sel">${Object.keys(ROLE_LABELS).map((r) =>
              `<option value="${r}" ${r === u.role ? "selected" : ""}>${ROLE_LABELS[r]}</option>`).join("")}</select></td>
            <td>${esc(u.organization || u.school || "—")}</td>
            <td><span class="badge ${cls}">${esc(label)}</span></td>
            <td>${u.consent_pdn ? "✅" : "—"}</td>
            <td class="actions">
              ${u.approval_status !== "approved" ? `<button class="btn btn--ghost btn--sm" data-act="approve" data-id="${u.id}" type="button">Одобрить</button>` : ""}
              ${u.approval_status !== "blocked" ? `<button class="btn btn--ghost btn--sm" data-act="block" data-id="${u.id}" type="button">Блок</button>` : ""}
              <button class="btn btn--ghost btn--sm" data-del="${u.id}" type="button">Удалить</button>
            </td></tr>`;
        }).join("")}</tbody></table></div>`;
      box.querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", async () => {
        try { await api(`/api/admin/users/${b.dataset.id}/${b.dataset.act}`, { json: {} }); loadUsers(); refreshPendingBadge(); }
        catch (e) { alert(e.message); }
      }));
      box.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async () => {
        if (!confirm("Удалить пользователя " + b.dataset.del + "?")) return;
        try { await api("/api/admin/users/" + b.dataset.del, { method: "DELETE" }); loadUsers(); refreshPendingBadge(); }
        catch (e) { alert(e.message); }
      }));
      box.querySelectorAll("[data-role]").forEach((sel) => sel.addEventListener("change", async () => {
        try { await api("/api/admin/users/" + sel.dataset.role, { method: "PATCH", json: { role: sel.value } });
          alert("Роль обновлена."); }
        catch (e) { alert(e.message); loadUsers(); }
      }));
    } catch (e) {
      box.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
  }

  /* ------------------------------ Эксперты ------------------------------- */
  async function loadExperts() {
    const box = $("#expertsBox");
    box.innerHTML = '<div class="empty">Загрузка…</div>';
    try {
      const { experts } = await api("/api/admin/experts");
      if (!experts.length) { box.innerHTML = '<div class="empty">Нет экспертов.</div>'; return; }
      box.innerHTML = `<div class="table-wrap"><table class="data-table">
        <thead><tr><th>ID</th><th>ФИО</th><th>Email</th><th>Организация</th><th>Нагрузка</th></tr></thead>
        <tbody>${experts.map((e) => `<tr><td>${e.id}</td><td>${esc(e.full_name || e.name)}</td>
          <td>${esc(e.email)}</td><td>${esc(e.organization || "—")}</td>
          <td><span class="badge badge--role">${e.loads}</span></td></tr>`).join("")}</tbody></table></div>`;
    } catch (e) {
      box.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
  }

  /* ------------------------------ Проекты -------------------------------- */
  async function loadProjects() {
    const box = $("#projectsBox");
    box.innerHTML = '<div class="empty">Загрузка…</div>';
    try {
      const { projects } = await api("/api/admin/projects");
      if (!projects.length) { box.innerHTML = '<div class="empty">Проектов пока нет.</div>'; return; }
      box.innerHTML = `<div class="table-wrap"><table class="data-table">
        <thead><tr><th>ID</th><th>Название</th><th>Участник</th><th>Номинация</th><th>Оценок</th><th>Статус</th></tr></thead>
        <tbody>${projects.map((p) => `<tr>
          <td>${p.id}</td><td>${esc(p.title)}<div class="muted">${esc(p.created_at || "")}</div></td>
          <td>${esc(p.participant_name || "—")}<div class="muted">${esc(p.school || "")}</div></td>
          <td>${esc(p.nomination || "—")}</td><td>${p.evaluations}</td>
          <td><select data-proj="${p.id}">${STATUS_ORDER.map((s) =>
            `<option value="${s}" ${s === p.status ? "selected" : ""}>${STATUS_LABELS[s]}</option>`).join("")}</select></td>
        </tr>`).join("")}</tbody></table></div>`;
      box.querySelectorAll("[data-proj]").forEach((sel) => sel.addEventListener("change", async () => {
        try { await api("/api/admin/projects/" + sel.dataset.proj, { method: "PATCH", json: { status: sel.value } }); }
        catch (e) { alert(e.message); }
      }));
    } catch (e) {
      box.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
  }

  /* ---------------------------- Комментарии ------------------------------ */
  async function loadComments() {
    const box = $("#commentsBox");
    box.innerHTML = '<div class="empty">Загрузка…</div>';
    try {
      const { comments } = await api("/api/admin/comments");
      if (!comments.length) { box.innerHTML = '<div class="empty">Нет комментариев.</div>'; return; }
      box.innerHTML = comments.map((c) => `<div class="item">
        <div class="item__head">
          <div><div class="item__title">${esc(c.author || "Гость")}</div>
          <div class="item__meta">${esc(c.created_at || "")} · <span class="badge badge--soft">${esc(c.status)}</span></div></div>
        </div>
        <p style="margin:.6rem 0">${esc(c.body)}</p>
        <div class="form-actions">
          <button class="btn btn--ghost btn--sm" data-mod="approved" data-id="${c.id}" type="button">Одобрить</button>
          <button class="btn btn--ghost btn--sm" data-mod="rejected" data-id="${c.id}" type="button">Отклонить</button>
        </div></div>`).join("");
      box.querySelectorAll("[data-mod]").forEach((b) => b.addEventListener("click", async () => {
        try { await api("/api/admin/comments/" + b.dataset.id, { method: "PATCH", json: { status: b.dataset.mod } }); loadComments(); }
        catch (e) { alert(e.message); }
      }));
    } catch (e) {
      box.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
  }

  /* ------------------------------ Рассылки ------------------------------- */
  async function loadMailings() {
    const box = $("#mailingsBox");
    box.innerHTML = '<div class="empty">Загрузка…</div>';
    try {
      const { mailings } = await api("/api/admin/mailings");
      if (!mailings.length) { box.innerHTML = '<div class="empty">Рассылок ещё не было.</div>'; return; }
      box.innerHTML = `<div class="table-wrap"><table class="data-table">
        <thead><tr><th>Дата</th><th>Канал</th><th>Тема</th><th>Аудитория</th><th>Получателей</th></tr></thead>
        <tbody>${mailings.map((m) => `<tr><td>${esc(m.created_at || "")}</td><td>${esc(m.channel)}</td>
          <td>${esc(m.subject)}</td><td>${esc(m.audience)}</td><td>${m.recipients_count}</td></tr>`).join("")}</tbody></table></div>`;
    } catch (e) {
      box.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
  }

  function initMailings() {
    const audience = $("#mAudience");
    const recipientWrap = $("#mRecipientWrap");
    const recipient = $("#mRecipient");
    const updateRecipient = () => {
      const specific = ["specific-email", "specific-nomination"].includes(audience.value);
      recipientWrap.hidden = !specific;
      recipient.required = specific;
      recipient.placeholder = audience.value === "specific-email"
        ? "email ученика, зарегистрированного на сайте" : "точное название номинации из заявки";
      recipientWrap.querySelector("label").textContent = audience.value === "specific-email"
        ? "Email конкретного ученика *" : "Точное название номинации *";
    };
    audience.addEventListener("change", updateRecipient);
    updateRecipient();
    $("#mailingForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      let target = audience.value;
      if (target === "specific-email") target = "email:" + recipient.value.trim();
      if (target === "specific-nomination") target = "nomination:" + recipient.value.trim();
      try {
        const d = await api("/api/admin/mailings", { json: {
          channel: $("#mChannel").value, audience: target,
          subject: $("#mSubject").value, body: $("#mBody").value } });
        alertBox($("#mailingAlert"), d.message, true);
        $("#mailingForm").reset();
        updateRecipient();
        loadMailings();
      } catch (e) { alertBox($("#mailingAlert"), e.message, false); }
    });
  }

  /* ------------------------------- Отчёты -------------------------------- */
  async function loadReport() {
    const box = $("#reportBox");
    box.innerHTML = '<div class="empty">Загрузка…</div>';
    try {
      const d = await api("/api/admin/report");
      const nomRows = d.by_nomination.map((r) => `<tr><td>${esc(r.nomination || "—")}</td>
        <td>${r.total}</td><td>${r.evaluated}</td><td>${r.in_work}</td></tr>`).join("");
      const regRows = d.by_region.map((r) => `<tr><td>${esc(r.region)}</td><td>${r.participants}</td></tr>`).join("");
      box.innerHTML = `<div class="two-col">
        <div class="card"><h3>По номинациям</h3><div class="table-wrap"><table class="data-table">
          <thead><tr><th>Номинация</th><th>Всего</th><th>Оценено</th><th>В работе</th></tr></thead>
          <tbody>${nomRows || '<tr><td colspan="4">Нет данных</td></tr>'}</tbody></table></div></div>
        <div class="card"><h3>По регионам</h3><div class="table-wrap"><table class="data-table">
          <thead><tr><th>Регион</th><th>Участников</th></tr></thead>
          <tbody>${regRows || '<tr><td colspan="2">Нет данных</td></tr>'}</tbody></table></div></div>
      </div><p class="muted" style="margin-top:1rem">Сформировано: ${esc(d.generated_at)}</p>`;
    } catch (e) {
      box.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
  }

  function downloadCsv(kind, filename) {
    fetch("/api/admin/export/" + kind + ".csv", { credentials: "same-origin" })
      .then((r) => { if (!r.ok) throw new Error("Ошибка выгрузки"); return r.blob(); })
      .then((blob) => {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 30000);
      })
      .catch((e) => alert(e.message));
  }

  /* -------------------------- Редактор ресурсов -------------------------- */
  let resourceKey = null;
  let editingId = null;

  function openResource(key) {
    if (!RESOURCES[key]) return;
    resourceKey = key;
    editingId = null;
    const cfg = RESOURCES[key];
    $("#resourceTitle").textContent = cfg.title;
    $("#resourceSubtitle").textContent = cfg.sub;
    $("#resourceSaveBtn").textContent = "Добавить";
    $("#resourceCancelBtn").style.display = "none";
    $("#resourceAlert").className = "alert";
    renderResourceFields(cfg, {});
    loadResourceItems();
  }

  function renderResourceFields(cfg, data) {
    const box = $("#resourceFields");
    box.innerHTML = cfg.fields.map((f) => {
      const val = data[f.k] != null ? data[f.k] : "";
      const cls = f.full ? "field field--full" : "field";
      if (f.type === "textarea") return `<div class="${cls}"><label for="rf_${f.k}">${esc(f.label)}${f.req ? " *" : ""}</label>
        <textarea id="rf_${f.k}" ${f.req ? "required" : ""}>${esc(val)}</textarea></div>`;
      if (f.type === "bool") return `<div class="${cls}"><label>${esc(f.label)}</label>
        <label style="font-weight:400"><input type="checkbox" id="rf_${f.k}" ${val ? "checked" : ""}> ${esc(f.label)}</label></div>`;
      if (f.type === "select") return `<div class="${cls}"><label for="rf_${f.k}">${esc(f.label)}${f.req ? " *" : ""}</label>
        <select id="rf_${f.k}">${(f.options || []).map((o) => `<option value="${esc(o)}" ${String(val) === String(o) ? "selected" : ""}>${esc(o)}</option>`).join("")}</select></div>`;
      const type = f.type === "number" ? "number" : (f.type === "date" ? "date" : "text");
      const step = f.step ? `step="${f.step}"` : "";
      return `<div class="${cls}"><label for="rf_${f.k}">${esc(f.label)}${f.req ? " *" : ""}</label>
        <input id="rf_${f.k}" type="${type}" ${step} value="${esc(val)}" ${f.req ? "required" : ""}></div>`;
    }).join("");
  }

  function collectResource(cfg) {
    const data = {};
    cfg.fields.forEach((f) => {
      const el = $("#rf_" + f.k);
      if (!el) return;
      if (f.type === "bool") data[f.k] = el.checked;
      else if (f.type === "number") data[f.k] = el.value === "" ? null : Number(el.value);
      else data[f.k] = el.value;
    });
    return data;
  }

  async function loadResourceItems() {
    const cfg = RESOURCES[resourceKey];
    const box = $("#resourceBox");
    box.innerHTML = '<div class="empty">Загрузка…</div>';
    try {
      const { items } = await api("/api/admin/" + resourceKey);
      if (!items.length) { box.innerHTML = '<div class="empty">Записей пока нет.</div>'; return; }
      const cols = cfg.fields.filter((f) => f.k !== "body" && f.k !== "description" && f.k !== "text" && f.k !== "explanation").slice(0, 5);
      box.innerHTML = `<div class="table-wrap"><table class="data-table">
        <thead><tr><th>ID</th>${cols.map((f) => `<th>${esc(f.label)}</th>`).join("")}<th></th></tr></thead>
        <tbody>${items.map((it) => `<tr>
          <td>${it.id}</td>
          ${cols.map((f) => `<td>${f.type === "bool" ? (it[f.k] ? "✅" : "—") : esc(String(it[f.k] == null ? "—" : it[f.k]).slice(0, 60))}</td>`).join("")}
          <td>
            <button class="btn btn--ghost btn--sm" data-edit="${it.id}" type="button">Изменить</button>
            <button class="btn btn--ghost btn--sm" data-rems="${it.id}" type="button">Удалить</button>
          </td></tr>`).join("")}</tbody></table></div>`;
      box.querySelectorAll("[data-edit]").forEach((b) => b.addEventListener("click", () => {
        const it = items.find((x) => x.id === Number(b.dataset.edit));
        editingId = it.id;
        renderResourceFields(cfg, it);
        $("#resourceSaveBtn").textContent = "Сохранить изменения";
        $("#resourceCancelBtn").style.display = "inline-block";
        window.scrollTo({ top: 0, behavior: "smooth" });
      }));
      box.querySelectorAll("[data-rems]").forEach((b) => b.addEventListener("click", async () => {
        if (!confirm("Удалить запись #" + b.dataset.rems + "?")) return;
        try { await api(`/api/admin/${resourceKey}/${b.dataset.rems}`, { method: "DELETE" }); loadResourceItems(); }
        catch (e) { alert(e.message); }
      }));
    } catch (e) {
      box.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
  }

  function initResourceForm() {
    $("#resourceForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      const cfg = RESOURCES[resourceKey];
      const data = collectResource(cfg);
      try {
        if (editingId) {
          await api(`/api/admin/${resourceKey}/${editingId}`, { method: "PATCH", json: data });
          alertBox($("#resourceAlert"), "Запись обновлена.", true);
        } else {
          await api("/api/admin/" + resourceKey, { json: data });
          alertBox($("#resourceAlert"), "Запись добавлена.", true);
        }
        editingId = null;
        $("#resourceSaveBtn").textContent = "Добавить";
        $("#resourceCancelBtn").style.display = "none";
        renderResourceFields(cfg, {});
        loadResourceItems();
      } catch (e2) { alertBox($("#resourceAlert"), e2.message, false); }
    });
    $("#resourceCancelBtn").addEventListener("click", () => {
      editingId = null;
      renderResourceFields(RESOURCES[resourceKey], {});
      $("#resourceSaveBtn").textContent = "Добавить";
      $("#resourceCancelBtn").style.display = "none";
      $("#resourceAlert").className = "alert";
    });
  }

  /* ---------------------------- Инициализация ---------------------------- */
  function initActions() {
    $("#usersFilterBtn").addEventListener("click", loadUsers);
    $("#usersExportBtn").addEventListener("click", () => downloadCsv("users", "users-export.csv"));
    $("#usersExportBtn2").addEventListener("click", () => downloadCsv("users", "users-export.csv"));
    $("#projectsExportBtn").addEventListener("click", () => downloadCsv("projects", "projects-export.csv"));
    $("#reportExportBtn").addEventListener("click", () => downloadCsv("report", "report-export.csv"));
    $("#autoAssignBtn").addEventListener("click", async () => {
      try { const d = await api("/api/expert/assignments/auto", { json: {} });
        alertBox($("#expertsAlert"), d.message, true); loadExperts(); }
      catch (e) { alertBox($("#expertsAlert"), e.message, false); }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initMenu();
    initActions();
    initMailings();
    initResourceForm();
    loadUser();
    loadDashboard();
  });
})();
