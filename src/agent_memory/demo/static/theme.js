"use strict";
// Runs in <head> before first paint so a saved light theme does not flash dark.
try {
  const t = localStorage.getItem("theme");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
} catch (e) { /* storage may be blocked */ }
