/* Applies the saved theme and text size before the page paints, so neither flashes. */
"use strict";
(function () {
  let theme = "dark";
  let size = "standard";
  try {
    const saved = localStorage.getItem("postloom-theme");
    if (saved === "light" || saved === "dark") theme = saved;
    const savedSize = localStorage.getItem("postloom-text-size");
    if (savedSize === "large" || savedSize === "larger") size = savedSize;
  } catch {
    // Storage can be unavailable (private windows); the defaults apply.
  }
  document.documentElement.dataset.theme = theme;
  document.documentElement.dataset.textSize = size;
})();
