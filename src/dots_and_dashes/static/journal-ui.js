// Keeps a Daily Log's progress line and empty hint in step with its list,
// however the list changed. Nothing here changes an Entry or decides what
// counts: the Journal's day_progress does, so the progress line is redrawn
// from a fresh copy of the page, as keyboard.js redraws a list.
(() => {
  const list = document.getElementById("entries");
  if (!list || !document.getElementById("day-progress")) return;
  const emptyHint = document.getElementById("empty-hint");
  let pending;

  const update = () => {
    if (emptyHint) emptyHint.hidden = list.querySelector(":scope > .entry") !== null;
    // One redraw for a burst of changes, such as a whole list swapped in.
    clearTimeout(pending);
    pending = setTimeout(() => {
      htmx.ajax("GET", location.pathname + location.search, {
        target: "#day-progress",
        select: "#day-progress",
        swap: "outerHTML",
      });
    }, 150);
  };

  new MutationObserver(update).observe(list, { childList: true, subtree: true });
})();
