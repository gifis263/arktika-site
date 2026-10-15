/* Токен входа на вкладку + состояние кнопок «Вход/Регистрация» в шапке.
 *
 * Сессия хранится в sessionStorage браузера: он уникален для каждой вкладки,
 * поэтому две вкладки могут быть авторизованы под разными пользователями и не
 * «заражают» друг друга (в отличие от общей cookie-сессии).
 */
(function () {
  "use strict";

  const TOKEN_KEY = "arktika_token";

  const tokenStore = {
    get() { try { return sessionStorage.getItem(TOKEN_KEY); } catch (_) { return null; } },
    set(t) { try { if (t) sessionStorage.setItem(TOKEN_KEY, t); } catch (_) { /* игнорируем */ } },
    clear() { try { sessionStorage.removeItem(TOKEN_KEY); } catch (_) { /* игнорируем */ } },
  };
  window.arktikaToken = tokenStore;

  // Если сервер вернул нас с токеном в адресе (например, после входа через VK),
  // сохраняем его в текущей вкладке и убираем из строки браузера.
  try {
    const params = new URLSearchParams(location.search);
    const urlToken = params.get("token");
    if (urlToken) {
      tokenStore.set(urlToken);
      params.delete("token");
      const rest = params.toString();
      history.replaceState(null, "", location.pathname + (rest ? "?" + rest : "") + location.hash);
    }
  } catch (_) { /* игнорируем */ }

  // Подмешиваем токен в заголовок X-Auth-Token для всех запросов к нашему серверу.
  if (!window.__arktikaFetchPatched) {
    window.__arktikaFetchPatched = true;
    const originalFetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
      init = init || {};
      let sameOrigin = false;
      try {
        const url = typeof input === "string" ? input : (input && input.url) || "";
        sameOrigin = new URL(url, location.origin).origin === location.origin;
      } catch (_) { /* оставляем как есть */ }
      if (sameOrigin) {
        const token = tokenStore.get();
        if (token) {
          const headers = new Headers(init.headers || {});
          if (!headers.has("X-Auth-Token")) headers.set("X-Auth-Token", token);
          init.headers = headers;
        }
        init.credentials = init.credentials || "same-origin";
      }
      return originalFetch(input, init);
    };
  }

  function init() {
    const actions = document.querySelector(".auth-actions");
    if (!actions) return;

    fetch("/api/auth/me")
      .then((r) => r.json())
      .then((data) => {
        if (!data.authenticated) return;
        const u = data.user || {};
        const name = u.full_name || u.name || "Пользователь";
        const home = u.home || "/pages/cabinet.html";
        const roleLabel = u.role_label || "Личный кабинет";
        const pending = u.approval_status === "pending";
        const pendingNote = pending
          ? `<span class="auth-link" style="cursor:default;color:#b07d00" title="Аккаунт на модерации">⏳ На модерации</span>`
          : "";
        actions.innerHTML =
          `<span class="auth-link" style="cursor:default" title="${name}">👤 ${name.split(" ")[0]}</span>` +
          pendingNote +
          `<a class="auth-link auth-link--primary" href="${pending ? "/pages/auth.html" : home}">${pending ? "Статус" : roleLabel}</a>` +
          `<button class="auth-link" type="button" id="logoutBtn" style="cursor:pointer">Выйти</button>`;
        const btn = document.getElementById("logoutBtn");
        if (btn) {
          btn.addEventListener("click", async () => {
            tokenStore.clear();
            try { await fetch("/api/auth/logout", { method: "POST" }); } catch (_) { /* игнорируем */ }
            location.href = "/index.html";
          });
        }
      })
      .catch(() => { /* не критично для отображения страницы */ });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
