document.addEventListener("DOMContentLoaded", () => {
  const path = location.pathname;

  // Форма подачи проекта: сохраняет карточку и загружает файлы на Flask backend.
  if (path.endsWith("/pages/submit-project.html")) {
    const form = document.querySelector("form");
    if (form) {
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const inputs = form.querySelectorAll("input[type='text'], select, textarea, input[type='file']");
        const [titleEl, nominationEl, ideaEl, fileEl] = inputs;
        const body = new FormData();
        body.append("title", titleEl?.value || "");
        body.append("nomination", nominationEl?.value || "");
        body.append("abstract", ideaEl?.value || "");
        if (fileEl?.files?.[0]) body.append("file", fileEl.files[0]);
        try {
          const response = await fetch("/api/projects", {
            method: "POST", body, credentials: "same-origin",
          });
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || "Не удалось отправить заявку.");
          alert(result.message + " Номер заявки: " + result.project_id +
            "\nСледите за статусом в личном кабинете.");
          form.reset();
        } catch (error) {
          alert(error.message || "Ошибка соединения с сервером.");
        }
      });
    }
  }

  // Форма обратной связи.
  if (path.endsWith("/pages/contacts.html")) {
    const form = document.querySelector("form");
    if (form) form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const fields = form.querySelectorAll("input, textarea");
      const payload = { name: fields[0]?.value, email: fields[1]?.value,
        subject: fields[2]?.value, message: fields[3]?.value };
      try {
        const response = await fetch("/api/contact", { method: "POST",
          headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload) });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "Не удалось отправить сообщение.");
        alert(result.message); form.reset();
      } catch (error) { alert(error.message || "Ошибка соединения с сервером."); }
    });
  }
});
