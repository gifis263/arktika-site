/* Личный кабинет участника (школьника) */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  function esc(s) {
    return String(s == null ? "" : s)
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
    let data = {};
    try { data = await res.json(); } catch (_) { /* пустой ответ */ }
    if (!res.ok) throw new Error(data.error || "Ошибка сервера");
    return data;
  }

  function alertBox(el, message, ok) {
    if (!el) return;
    el.textContent = message;
    el.className = "alert show " + (ok ? "alert--ok" : "alert--error");
  }

  function fmtDate(v) {
    if (!v) return "—";
    return String(v).replace("T", " ").slice(0, 16);
  }

  /* ------------------------- Навигация по разделам ------------------------ */
  function initMenu() {
    $$("#cabinetMenu button").forEach((btn) => {
      btn.addEventListener("click", () => {
        $$("#cabinetMenu button").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        $$(".panel").forEach((p) => p.classList.remove("active"));
        const panel = $("#panel-" + btn.dataset.section);
        if (panel) panel.classList.add("active");
        const load = sectionLoaders[btn.dataset.section];
        if (load) load();
      });
    });
  }

  /* -------------------------------- Сводка ------------------------------- */
  async function loadSummary() {
    const grid = $("#summaryGrid");
    try {
      const s = await api("/api/my/summary");
      const tile = (n, l) => `<div class="summary-tile"><div class="summary-tile__num">${esc(n)}</div><div class="summary-tile__label">${esc(l)}</div></div>`;
      grid.innerHTML =
        tile(s.profile_complete ? "✓" : "!") +
        tile(s.quiz_attempts) + tile(s.best_score + "%") +
        tile(s.projects) + tile(s.supervisors) +
        tile(s.certificates + s.awards) + tile(s.schedule);
      const labels = ["Профиль", "Попыток теста", "Лучший результат", "Проектов",
        "Руководителей", "Награды", "События ВКС"];
      grid.querySelectorAll(".summary-tile__label").forEach((el, i) => { el.textContent = labels[i]; });
      $("#profileProgress").style.width = (s.profile_complete ? 100 : 40) + "%";
    } catch (e) {
      grid.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
  }

  /* -------------------------------- Профиль ------------------------------ */
  async function loadProfile() {
    try {
      const { user } = await api("/api/profile");
      $("#userName").textContent = user.full_name || user.name || "Участник";
      $("#userEmail").textContent = user.email;
      ["full_name", "birth_date", "grade", "school", "region", "guardian_name", "guardian_contact"]
        .forEach((k) => { const el = $("#p_" + k); if (el) el.value = user[k] || ""; });
      $("#profileProgress").style.width = (user.profile_complete ? 100 : 40) + "%";
    } catch (e) { /* игнорируем */ }
  }

  function initProfileForm() {
    $("#profileForm").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const payload = {};
      ["full_name", "birth_date", "grade", "school", "region", "guardian_name", "guardian_contact"]
        .forEach((k) => { payload[k] = $("#p_" + k).value.trim(); });
      const box = $("#profileAlert");
      try {
        const d = await api("/api/profile", { json: payload });
        alertBox(box, d.message || "Сохранено.", true);
        $("#userName").textContent = d.user.full_name || d.user.name;
        $("#profileProgress").style.width = (d.user.profile_complete ? 100 : 40) + "%";
        loadSummary();
      } catch (e) { alertBox(box, e.message, false); }
    });
  }

  /* ------------------------------ Руководитель --------------------------- */
  async function loadSupervisors() {
    const box = $("#supervisorList");
    try {
      const { supervisors } = await api("/api/supervisors");
      if (!supervisors.length) {
        box.innerHTML = `<div class="empty">Руководитель пока не добавлен.</div>`;
        return;
      }
      box.innerHTML = supervisors.map((s) => `
        <div class="item">
          <div class="item__head">
            <div>
              <div class="item__title">${esc(s.teacher_name)}</div>
              <div class="item__meta">${esc(s.teacher_email)}${s.organization ? " · " + esc(s.organization) : ""}</div>
            </div>
            <div>
              <span class="badge ${s.status === "confirmed" ? "badge--evaluated" : "badge--review"}">
                ${s.status === "confirmed" ? "Подтверждён" : "Ожидает подтверждения"}
              </span>
              <button class="btn btn--ghost btn--sm" data-del="${s.id}" type="button" style="margin-left:.5rem">Удалить</button>
            </div>
          </div>
        </div>`).join("");
      box.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async () => {
        try { await api("/api/supervisors/" + b.dataset.del, { method: "DELETE" }); loadSupervisors(); loadSummary(); }
        catch (e) { alert(e.message); }
      }));
    } catch (e) { box.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  }

  function initSupervisorForm() {
    $("#supervisorForm").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const box = $("#supervisorAlert");
      const payload = {
        teacher_name: $("#s_name").value.trim(),
        teacher_email: $("#s_email").value.trim(),
        organization: $("#s_org").value.trim(),
      };
      try {
        const d = await api("/api/supervisors", { json: payload });
        let msg = d.message;
        if (d.confirm_url) msg += " Ссылка подтверждения (для прототипа): " + d.confirm_url;
        alertBox(box, msg, true);
        $("#supervisorForm").reset();
        loadSupervisors(); loadSummary();
      } catch (e) { alertBox(box, e.message, false); }
    });
  }

  /* ------------------------------ Тестирование --------------------------- */
  let quizTimerId = null;
  let quizState = null;

  async function loadAttempts() {
    const box = $("#attemptsList");
    try {
      const { attempts } = await api("/api/quiz/attempts");
      if (!attempts.length) { box.innerHTML = ""; return; }
      box.innerHTML = `<h3 class="card__title" style="font-size:1.1rem">История попыток</h3>` +
        attempts.map((a) => `
          <div class="item">
            <div class="item__head">
              <div>
                <div class="item__title">${a.score} из ${a.total} · ${Math.round(a.score / a.total * 100)}%</div>
                <div class="item__meta">${esc(fmtDate(a.created_at))}${a.duration_seconds ? " · " + a.duration_seconds + " c" : ""}</div>
              </div>
              <div>
                <span class="badge ${a.passed ? "badge--evaluated" : "badge--review"}">${a.passed ? "Пройден" : "Не пройден"}</span>
                ${a.certificate_number ? `<a class="btn btn--ghost btn--sm" style="margin-left:.5rem" href="/certificate/${esc(a.certificate_number)}.pdf" target="_blank">Сертификат</a>` : ""}
              </div>
            </div>
          </div>`).join("");
    } catch (e) { box.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  }

  async function startQuiz() {
    $("#quizIntro").style.display = "none";
    $("#quizResult").style.display = "none";
    $("#quizRun").style.display = "block";
    try {
      const d = await api("/api/quiz/questions?count=10");
      quizState = { token: d.token, startedAt: Date.now(), timeLimit: d.time_limit };
      $("#quizQuestions").innerHTML = d.questions.map((q, i) => `
        <div class="quiz-q">
          <div class="quiz-q__text">${i + 1}. ${esc(q.text)} <span class="muted" style="font-weight:400">(${esc(q.topic || "")})</span></div>
          ${q.options.map((o) => `
            <label class="quiz-opt">
              <input type="radio" name="q_${q.id}" value="${esc(o.key)}">
              <span>${esc(o.text)}</span>
            </label>`).join("")}
        </div>`).join("");
      $("#quizProgressText").textContent = `Вопросов: ${d.count}`;
      startTimer(d.time_limit);
    } catch (e) {
      $("#quizRun").style.display = "none";
      $("#quizIntro").style.display = "block";
      alert(e.message);
    }
  }

  function startTimer(seconds) {
    let left = seconds;
    const el = $("#quizTimer");
    el.classList.remove("warning");
    const render = () => {
      const m = String(Math.floor(left / 60)).padStart(2, "0");
      const s = String(left % 60).padStart(2, "0");
      el.textContent = `${m}:${s}`;
      if (left <= 60) el.classList.add("warning");
    };
    render();
    clearInterval(quizTimerId);
    quizTimerId = setInterval(() => {
      left -= 1;
      render();
      if (left <= 0) { clearInterval(quizTimerId); submitQuiz(true); }
    }, 1000);
  }

  async function submitQuiz(auto) {
    if (!quizState) return;
    clearInterval(quizTimerId);
    const answers = {};
    $$("#quizQuestions input[type=radio]:checked").forEach((r) => {
      answers[r.name.replace("q_", "")] = r.value;
    });
    const duration = Math.round((Date.now() - quizState.startedAt) / 1000);
    $("#quizRun").style.display = "none";
    $("#quizResult").style.display = "block";
    $("#quizResult").innerHTML = `<p class="muted">Проверяем ответы…</p>`;
    try {
      const d = await api("/api/quiz/submit", { json: { token: quizState.token, answers, duration } });
      renderQuizResult(d, auto);
      loadAttempts(); loadSummary(); loadAchievements();
    } catch (e) {
      $("#quizResult").innerHTML = `<div class="empty">${esc(e.message)}</div>
        <button class="btn btn--primary" type="button" onclick="location.reload()">Начать заново</button>`;
    }
    quizState = null;
  }

  function renderQuizResult(d, auto) {
    const pass = d.passed;
    let html = `<div class="quiz-result">
      <h3 class="card__title">${auto ? "Время вышло!" : "Тест завершён!"}</h3>
      <div class="quiz-result__score">${d.score} / ${d.total}</div>
      <p class="muted">${Math.round(d.score / d.total * 100)}% правильных ответов · ${pass ? "Порог пройден" : "Порог не пройден"}</p>`;
    if (d.certificate) {
      html += `<p style="margin-top:1rem">🎓 Сформирован электронный сертификат <strong>№ ${esc(d.certificate.number)}</strong>.</p>
        <a class="btn btn--primary" href="${esc(d.certificate.download_url)}" target="_blank">Скачать сертификат (PDF)</a>
        <a class="btn btn--ghost" href="${esc(d.certificate.verify_url)}" target="_blank">Проверить подлинность</a>`;
    }
    html += `</div><h3 class="card__title" style="font-size:1.1rem;margin-top:1.5rem">Разбор ответов</h3>`;
    d.details.forEach((det, i) => {
      html += `<div class="quiz-detail ${det.correct ? "ok" : "bad"}">
        <strong>${i + 1}. ${esc(det.text)}</strong><br>
        <span class="muted">${det.correct ? "✓ Верно" : "✗ Неверно"} · правильный ответ: ${esc(det.correct_option)}</span><br>
        <span class="muted">${esc(det.explanation || "")}</span>
      </div>`;
    });
    html += `<div class="form-actions" style="justify-content:center">
      <button class="btn btn--primary" type="button" id="againBtn">Пройти ещё раз</button></div>`;
    $("#quizResult").innerHTML = html;
    $("#againBtn").addEventListener("click", () => {
      $("#quizResult").style.display = "none";
      $("#quizIntro").style.display = "block";
    });
  }

  function initQuiz() {
    $("#startQuizBtn").addEventListener("click", startQuiz);
    $("#quizForm").addEventListener("submit", (e) => { e.preventDefault(); submitQuiz(false); });
    $("#cancelQuizBtn").addEventListener("click", () => {
      clearInterval(quizTimerId); quizState = null;
      $("#quizRun").style.display = "none";
      $("#quizIntro").style.display = "block";
    });
  }

  /* -------------------------------- Проект ------------------------------- */
  async function loadProjects() {
    const box = $("#projectList");
    try {
      const { projects } = await api("/api/projects");
      if (!projects.length) { box.innerHTML = `<div class="empty" style="margin-top:1rem">Проекты ещё не добавлены.</div>`; return; }
      box.innerHTML = projects.map((p) => `
        <div class="item">
          <div class="item__head">
            <div>
              <div class="item__title">${esc(p.title)}</div>
              <div class="item__meta">${esc(p.nomination)} · создан ${esc(fmtDate(p.created_at))}</div>
              <div class="item__meta">${p.file_name ? "📄 Работа прикреплена" : "📄 Нет файла работы"}${p.presentation_name ? " · 🖥 Презентация" : ""}${(p.video_url || p.video_name) ? " · 🎬 Видео" : ""}</div>
            </div>
            <div>
              <span class="badge badge--${esc(p.status)}">${esc(p.status_label)}</span>
              ${p.status === "draft" ? `<button class="btn btn--ghost btn--sm" data-submit="${p.id}" type="button" style="margin-left:.5rem">Отправить</button>` : ""}
            </div>
          </div>
        </div>`).join("");
      box.querySelectorAll("[data-submit]").forEach((b) => b.addEventListener("click", async () => {
        try { const d = await api(`/api/projects/${b.dataset.submit}/submit`, { method: "POST" }); alert(d.message); loadProjects(); loadSummary(); }
        catch (e) { alert(e.message); }
      }));
    } catch (e) { box.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  }

  function initProjectForm() {
    const form = $("#projectForm");
    async function send(status) {
      const box = $("#projectAlert");
      try {
        const fd = new FormData(form);
        fd.set("status", status);
        const res = await fetch("/api/projects", { method: "POST", body: fd, credentials: "same-origin" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Ошибка сохранения");
        alertBox(box, data.message, true);
        form.reset();
        loadProjects(); loadSummary();
      } catch (e) { alertBox(box, e.message, false); }
    }
    form.addEventListener("submit", (e) => { e.preventDefault(); send("review"); });
    $("#saveDraftBtn").addEventListener("click", () => send("draft"));
  }

  /* ------------------------------- Результаты ---------------------------- */
  async function loadResults() {
    const box = $("#resultsBox");
    try {
      const d = await api("/api/my/results");
      let html = `<div class="summary-grid">
        <div class="summary-tile"><div class="summary-tile__num">${d.quiz_attempts.length}</div><div class="summary-tile__label">Попыток теста</div></div>
        <div class="summary-tile"><div class="summary-tile__num">${d.best_score}%</div><div class="summary-tile__label">Лучший результат</div></div>
      </div>`;
      if (d.quiz_attempts.length) {
        html += `<h3 class="card__title" style="font-size:1.1rem">I этап — тестирование</h3>`;
        html += d.quiz_attempts.map((a) => `
          <div class="review">
            <div class="review__head"><span>${a.score} из ${a.total} (${a.passed ? "пройден" : "не пройден"})</span><span>${esc(fmtDate(a.created_at))}</span></div>
            <div class="review__comment">${a.certificate_number ? `Сертификат № ${esc(a.certificate_number)}` : "Сертификат не выдан"}</div>
          </div>`).join("");
      }
      html += `<h3 class="card__title" style="font-size:1.1rem;margin-top:1.5rem">II этап — проекты и рецензии</h3>`;
      if (!d.projects.length) {
        html += `<div class="empty">Проекты не поданы.</div>`;
      } else {
        d.projects.forEach((p) => {
          html += `<div class="item"><div class="item__head">
              <div><div class="item__title">${esc(p.title)}</div><div class="item__meta">${esc(p.nomination)}</div></div>
              <span class="badge badge--${esc(p.status)}">${esc(p.status_label)}</span></div>`;
          if (p.reviews.length) {
            p.reviews.forEach((r) => {
              html += `<div class="review"><div class="review__head"><span>${esc(r.expert_name || "Эксперт")} · ${esc(r.criteria || "")}</span><span>${r.score != null ? esc(r.score) + " балл(ов)" : ""}</span></div>
                <div class="review__comment">${esc(r.comment || "")}</div></div>`;
            });
          } else {
            html += `<div class="review__comment muted" style="margin-top:.5rem">Рецензии пока нет.</div>`;
          }
          html += `</div>`;
        });
      }
      box.innerHTML = html;
    } catch (e) { box.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  }

  /* ----------------------------- Расписание ВКС -------------------------- */
  async function loadSchedule() {
    const box = $("#scheduleBox");
    try {
      const { schedule } = await api("/api/my/schedule");
      if (!schedule.length) { box.innerHTML = `<div class="empty">Расписание ВКС-защиты пока не опубликовано.</div>`; return; }
      box.innerHTML = schedule.map((s) => `
        <div class="item">
          <div class="item__head">
            <div>
              <div class="item__title">${esc(s.title)}</div>
              <div class="item__meta">🗓 ${esc(fmtDate(s.scheduled_at))}${s.room ? " · " + esc(s.room) : ""}</div>
            </div>
            ${s.join_link ? `<a class="btn btn--primary btn--sm" href="${esc(s.join_link)}" target="_blank" rel="noopener">Подключиться</a>` : ""}
          </div>
        </div>`).join("");
    } catch (e) { box.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  }

  /* ------------------------------ Достижения ----------------------------- */
  async function loadAchievements() {
    const box = $("#achievementsBox");
    try {
      const { achievements } = await api("/api/my/achievements");
      if (!achievements.length) { box.innerHTML = `<div class="empty">Наград пока нет. Пройдите тестирование и подайте проект.</div>`; return; }
      const icons = { certificate: "📜", diploma: "🏆", thanks: "💌" };
      box.innerHTML = `<div class="achievements-grid">` + achievements.map((a) => `
        <div class="award-card">
          <div class="award-card__icon">${icons[a.kind] || "🎖"}</div>
          <div class="award-card__title">${esc(a.title)}</div>
          <div class="award-card__desc">${esc(a.description || "")}<br><span class="muted">${esc(fmtDate(a.issued_at))}</span></div>
          ${a.download_url ? `<a class="btn btn--ghost btn--sm" href="${esc(a.download_url)}" target="_blank">Скачать (PDF)</a>` : ""}
        </div>`).join("") + `</div>`;
    } catch (e) { box.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  }

  /* -------------------------------- Демо --------------------------------- */
  function initDemo() {
    $("#seedDemoBtn").addEventListener("click", async () => {
      try {
        const d = await api("/api/demo/seed", { method: "POST" });
        alertBox($("#overviewAlert"), d.message + " Перейдите в разделы «Результаты», «ВКС-защита», «Достижения».", true);
        loadSummary(); loadProjects(); loadResults(); loadSchedule(); loadAchievements();
      } catch (e) { alertBox($("#overviewAlert"), e.message, false); }
    });
  }

  const sectionLoaders = {
    overview: loadSummary,
    profile: loadProfile,
    supervisor: loadSupervisors,
    testing: loadAttempts,
    project: loadProjects,
    results: loadResults,
    schedule: loadSchedule,
    achievements: loadAchievements,
  };

  document.addEventListener("DOMContentLoaded", async () => {
    let me;
    try { me = await api("/api/auth/me"); } catch (_) { me = { authenticated: false }; }
    if (!me.authenticated) {
      location.href = "/pages/auth.html#login";
      return;
    }
    $("#userName").textContent = (me.user && (me.user.full_name || me.user.name)) || "Участник";
    $("#userEmail").textContent = (me.user && me.user.email) || "";

    initMenu();
    initProfileForm();
    initSupervisorForm();
    initQuiz();
    initProjectForm();
    initDemo();

    loadSummary();
    loadProfile();
    loadSupervisors();
    loadAttempts();
    loadProjects();
    loadResults();
    loadSchedule();
    loadAchievements();
  });
})();
