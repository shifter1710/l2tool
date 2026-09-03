(() => {
  const storageKey = "l2tool-theme";
  const draftKey = "l2tool-draft";
  const root = document.documentElement;
  const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const pendingLabels = {
    "/analyze": "Разбираем заявку…",
    "/secondary": "Запускаем второй этап…",
    "/batch": "Обрабатываем таблицу…",
  };

  function storedTheme() {
    try {
      const value = window.localStorage.getItem(storageKey);
      return value === "light" || value === "dark" ? value : null;
    } catch (_error) {
      return null;
    }
  }

  function saveTheme(theme) {
    try {
      window.localStorage.setItem(storageKey, theme);
    } catch (_error) {
      // The theme still works for the current page when storage is unavailable.
    }
  }

  function preferredTheme() {
    return storedTheme() || (systemTheme.matches ? "dark" : "light");
  }

  function applyTheme(theme) {
    root.dataset.theme = theme;
    root.style.colorScheme = theme;

    const toggle = document.querySelector("[data-theme-toggle]");
    if (!toggle) return;

    const dark = theme === "dark";
    const label = toggle.querySelector("[data-theme-label]");
    const icon = toggle.querySelector(".theme-icon");
    toggle.setAttribute("aria-pressed", String(dark));
    toggle.setAttribute("aria-label", dark ? "Включить светлую тему" : "Включить тёмную тему");
    if (label) label.textContent = dark ? "Светлая тема" : "Тёмная тема";
    if (icon) icon.textContent = dark ? "☀" : "☾";
  }

  applyTheme(preferredTheme());

  async function copyText(value) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      return;
    }

    const temporary = document.createElement("textarea");
    temporary.value = value;
    temporary.setAttribute("readonly", "");
    temporary.style.position = "fixed";
    temporary.style.opacity = "0";
    document.body.appendChild(temporary);
    temporary.select();
    const copied = document.execCommand("copy");
    temporary.remove();
    if (!copied) throw new Error("copy failed");
  }

  function scrollIntoFeedback() {
    const target =
      document.getElementById("secondary-result") ||
      document.getElementById("result") ||
      document.querySelector(".alert");
    target?.scrollIntoView({
      behavior: reducedMotion.matches ? "auto" : "smooth",
      block: "start",
    });
  }

  function formPath(form) {
    try {
      return new URL(form.action).pathname;
    } catch (_error) {
      return "";
    }
  }

  function markPending(form) {
    const label = pendingLabels[formPath(form)];
    const button = form.querySelector('button[type="submit"]');
    if (!label || !button || button.dataset.pendingLabel) return;
    button.dataset.pendingLabel = button.innerHTML;
    button.setAttribute("aria-busy", "true");
    button.disabled = true;
    button.textContent = label;
  }

  function resetPending(form) {
    const button = form.querySelector("button[data-pending-label]");
    if (!button) return;
    button.innerHTML = button.dataset.pendingLabel;
    button.removeAttribute("data-pending-label");
    button.removeAttribute("aria-busy");
    button.disabled = false;
  }

  let draftHint = null;
  let draftTimer = 0;

  function removeDraftHint() {
    draftHint?.remove();
    draftHint = null;
  }

  function saveDraft(field) {
    window.clearTimeout(draftTimer);
    draftTimer = window.setTimeout(() => {
      try {
        window.sessionStorage.setItem(draftKey, field.value);
      } catch (_error) {
        // Drafts are best-effort; storage may be unavailable.
      }
    }, 300);
  }

  function offerDraftRestore(field) {
    let draft = null;
    try {
      draft = window.sessionStorage.getItem(draftKey);
    } catch (_error) {
      return;
    }
    if (!draft || !draft.trim() || field.value) return;

    draftHint = document.createElement("div");
    draftHint.className = "draft-hint";
    const text = document.createElement("span");
    text.textContent = "В этой вкладке остался черновик заявки.";
    const restore = document.createElement("button");
    restore.type = "button";
    restore.textContent = "Восстановить";
    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.textContent = "Скрыть";
    draftHint.append(text, restore, dismiss);
    field.closest("label")?.after(draftHint);

    restore.addEventListener("click", () => {
      field.value = draft;
      removeDraftHint();
      field.focus();
    });
    dismiss.addEventListener("click", removeDraftHint);
  }

  document.addEventListener("DOMContentLoaded", () => {
    applyTheme(preferredTheme());
    scrollIntoFeedback();

    const toggle = document.querySelector("[data-theme-toggle]");
    toggle?.addEventListener("click", () => {
      const nextTheme = root.dataset.theme === "dark" ? "light" : "dark";
      saveTheme(nextTheme);
      applyTheme(nextTheme);
    });

    document.querySelectorAll("[data-copy-link]").forEach((button) => {
      button.addEventListener("click", async () => {
        const label = button.querySelector("[data-copy-label]");
        const originalLabel = "Копировать";

        try {
          await copyText(button.dataset.copyLink || "");
          button.classList.add("is-copied");
          if (label) label.textContent = "Скопировано";
        } catch (_error) {
          button.classList.add("copy-failed");
          if (label) label.textContent = "Не удалось";
        }

        window.setTimeout(() => {
          button.classList.remove("is-copied", "copy-failed");
          if (label) label.textContent = originalLabel;
        }, 1800);
      });
    });

    document.querySelectorAll("[data-confirm-delete]").forEach((form) => {
      form.addEventListener("submit", (event) => {
        const sourceName = form.dataset.confirmDelete || "этот источник";
        if (!window.confirm(`Удалить сохранённый пример для «${sourceName}»?`)) {
          event.preventDefault();
        }
      });
    });

    const ticketField = document.querySelector(
      '.ticket-form textarea[name="ticket_text"]',
    );
    if (ticketField) {
      offerDraftRestore(ticketField);
      ticketField.addEventListener("input", () => {
        removeDraftHint();
        saveDraft(ticketField);
      });
    }

    // Файл скачивается без перезагрузки страницы: возвращаем кнопке
    // рабочее состояние, когда пользователь снова обращается к форме.
    document.querySelectorAll('form[action$="/batch"]').forEach((form) => {
      form.addEventListener("focusin", () => resetPending(form));
    });
  });

  document.addEventListener(
    "submit",
    (event) => {
      if (event.target instanceof HTMLFormElement) markPending(event.target);
    },
    true,
  );

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || !(event.ctrlKey || event.metaKey)) return;
    const field = event.target;
    if (field instanceof HTMLTextAreaElement && field.form) {
      event.preventDefault();
      field.form.requestSubmit();
    }
  });

  systemTheme.addEventListener?.("change", (event) => {
    if (!storedTheme()) applyTheme(event.matches ? "dark" : "light");
  });
})();
