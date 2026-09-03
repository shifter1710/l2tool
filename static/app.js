(() => {
  const storageKey = "l2tool-theme";
  const root = document.documentElement;
  const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");

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

  document.addEventListener("DOMContentLoaded", () => {
    applyTheme(preferredTheme());

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
  });

  systemTheme.addEventListener?.("change", (event) => {
    if (!storedTheme()) applyTheme(event.matches ? "dark" : "light");
  });
})();
