/* Переключатель темы. Сам атрибут data-theme ставится инлайновым скриптом
   в <head> каждой страницы - до отрисовки, чтобы не моргало белым.
   Здесь только кнопка и запоминание выбора. */
(() => {
  const root = document.documentElement;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "theme-switch";

  const paint = () => {
    const dark = root.dataset.theme === "dark";
    button.textContent = dark ? "☀" : "☾";
    button.title = dark ? "Светлая тема" : "Тёмная тема";
    button.setAttribute("aria-label", button.title);
  };

  button.addEventListener("click", () => {
    const next = root.dataset.theme === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) {}
    paint();
  });

  paint();
  document.body.appendChild(button);

  // Пока выбор не сделан вручную - следуем за системной темой
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  media.addEventListener("change", (e) => {
    let saved = null;
    try { saved = localStorage.getItem("theme"); } catch (err) {}
    if (saved) return;
    root.dataset.theme = e.matches ? "dark" : "light";
    paint();
  });
})();
