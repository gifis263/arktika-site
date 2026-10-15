/* Движок тестирования для страницы pages/quiz.html.
   Использует серверный банк вопросов, таймер и автоматическую проверку. */
(function () {
  "use strict";

  const state = { token: null, questions: [], index: 0, answers: {}, timeLeft: 0, timer: null };

  const $ = (s) => document.querySelector(s);

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function fmt(sec) {
    const m = String(Math.floor(sec / 60)).padStart(2, "0");
    const s = String(sec % 60).padStart(2, "0");
    return `${m}:${s}`;
  }

  async function loadQuiz() {
    const qc = $("#quiz-container");
    if (!qc) return;
    try {
      const res = await fetch("/api/quiz/questions?count=10", { credentials: "same-origin" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Не удалось загрузить вопросы.");
      state.token = data.token;
      state.questions = data.questions;
      state.index = 0;
      state.answers = {};
      state.timeLeft = data.time_limit || 900;
      $("#quiz-title").textContent = "Тест «Арктика. Первые шаги»";
      $("#result-container").style.display = "none";
      $("#question-container").style.display = "block";
      $("#controls").style.display = "flex";
      renderQuestion();
      startTimer();
    } catch (e) {
      $("#question-container").innerHTML = `<p style="color:#b3261e">${esc(e.message)}</p>`;
    }
  }

  function renderQuestion() {
    const q = state.questions[state.index];
    if (!q) return;
    $("#question-text").textContent = q.text;
    $("#answers-container").innerHTML = q.options.map((o) => `
      <label style="display:flex;align-items:center;gap:.6rem;padding:.6rem .8rem;border:1px solid var(--border-color);border-radius:8px;margin-bottom:.5rem;cursor:pointer">
        <input type="radio" name="answer" value="${esc(o.key)}" ${state.answers[q.id] === o.key ? "checked" : ""}>
        <span>${esc(o.text)}</span>
      </label>`).join("");
    $("#answers-container").querySelectorAll("input").forEach((inp) => {
      inp.addEventListener("change", () => { state.answers[q.id] = inp.value; });
    });
    const total = state.questions.length;
    $("#quiz-progress").textContent = `Вопрос ${state.index + 1} из ${total} · ⏱ ${fmt(state.timeLeft)}`;
    $("#progress-bar").style.width = ((state.index + 1) / total * 100) + "%";
    $("#prev-btn").disabled = state.index === 0;
    const last = state.index === total - 1;
    $("#next-btn").style.display = last ? "none" : "inline-block";
    $("#finish-btn").style.display = last ? "inline-block" : "none";
  }

  function startTimer() {
    clearInterval(state.timer);
    state.timer = setInterval(() => {
      state.timeLeft -= 1;
      const total = state.questions.length;
      $("#quiz-progress").textContent = `Вопрос ${state.index + 1} из ${total} · ⏱ ${fmt(Math.max(state.timeLeft, 0))}`;
      if (state.timeLeft <= 0) { clearInterval(state.timer); finishQuiz(); }
    }, 1000);
  }

  async function finishQuiz() {
    clearInterval(state.timer);
    $("#question-container").style.display = "none";
    $("#controls").style.display = "none";
    $("#result-container").style.display = "block";
    $("#score-display").textContent = "…";
    $("#result-text").textContent = "Проверяем ответы";
    try {
      const res = await fetch("/api/quiz/submit", {
        method: "POST", headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ token: state.token, answers: state.answers }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.error || "Ошибка проверки.");
      $("#score-display").textContent = `${d.score} / ${d.total}`;
      let text = `${Math.round(d.score / d.total * 100)}% правильных ответов. ` +
        (d.passed ? "Порог пройден!" : "Попробуйте ещё раз.");
      $("#result-text").textContent = text;
      const rc = $("#result-container");
      let extra = rc.querySelector(".cert-box");
      if (extra) extra.remove();
      if (d.certificate) {
        const box = document.createElement("p");
        box.className = "cert-box";
        box.style.marginTop = "1rem";
        box.innerHTML = `Сертификат № ${esc(d.certificate.number)}.
          <a class="news-card__link" href="${esc(d.certificate.download_url)}" target="_blank">Скачать PDF</a>`;
        rc.appendChild(box);
      }
    } catch (e) {
      $("#score-display").textContent = "—";
      $("#result-text").textContent = e.message;
    }
  }

  function resetQuiz() { loadQuiz(); }
  function prevQuestion() { if (state.index > 0) { state.index -= 1; renderQuestion(); } }
  function nextQuestion() {
    if (state.index < state.questions.length - 1) {
      const q = state.questions[state.index];
      const checked = document.querySelector("input[name=answer]:checked");
      if (checked) state.answers[q.id] = checked.value;
      state.index += 1;
      renderQuestion();
    }
  }

  window.prevQuestion = prevQuestion;
  window.nextQuestion = nextQuestion;
  window.finishQuiz = finishQuiz;
  window.resetQuiz = resetQuiz;

  document.addEventListener("DOMContentLoaded", loadQuiz);
})();
