"use strict";
// Skeleton only. T13-T15 add rendering, the turn stream and the controls.
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const btn = $("#theme");
  btn.setAttribute("aria-pressed", String(theme === "light"));
  try { localStorage.setItem("theme", theme); } catch (e) { /* storage may be blocked */ }
}

function initTheme() {
  setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");
  $("#theme").addEventListener("click", () => {
    setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  });
}

initTheme();
