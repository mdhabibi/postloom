/* Applies the saved theme before the page paints, so it never flashes the wrong one. */
"use strict";
(function () {
  let theme = "dark";
  try {
    const saved = localStorage.getItem("postloom-theme");
    if (saved === "light" || saved === "dark") theme = saved;
  } catch {
    // Storage can be unavailable (private windows); dark is the default.
  }
  document.documentElement.dataset.theme = theme;
})();
