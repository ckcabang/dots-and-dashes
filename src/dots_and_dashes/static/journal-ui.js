// Feedback that keeps the page in step with what the User is doing. Nothing
// here changes an Entry: keyboard.js and the server own that.
//
// - The quick-entry box shows the Entry type its Prefix will create, as it is
//   typed (". " Task, "o " Event, "- " Note; no Prefix is a Task).
// - On a Daily Log, the progress line counts Completed Tasks against Open and
//   Completed ones, and the empty hint shows while the day has no Entries.
//   Both follow every change to the list, however it was made.
(() => {
  // Signifiers, then an optional type, then spaces: journal.py's _PREFIX.
  const PREFIX = /^[*!]*([.o-]?) +/;
  const TYPES = { ".": "task", o: "event", "-": "note" };

  function typeOf(text) {
    if (!text.trim()) return "";
    const match = PREFIX.exec(text);
    return (match && TYPES[match[1]]) || "task";
  }

  function watchQuickEntry(box) {
    const show = () => {
      const type = typeOf(box.value);
      if (type) box.dataset.type = type;
      else delete box.dataset.type;
    };
    box.addEventListener("input", show);
    box.form?.addEventListener("reset", () => setTimeout(show));
    show();
  }

  function trackDailyLog(list) {
    const progress = document.getElementById("day-progress");
    const emptyHint = document.getElementById("empty-hint");

    const update = () => {
      const entries = list.querySelectorAll(":scope > .entry");
      if (emptyHint) emptyHint.hidden = entries.length > 0;
      if (!progress) return;

      const tasks = list.querySelectorAll(":scope > .entry--task");
      let done = 0;
      let counted = 0;
      for (const task of tasks) {
        if (task.dataset.state === "completed") done += 1;
        if (task.dataset.state === "completed" || task.dataset.state === "open") counted += 1;
      }
      progress.hidden = counted === 0;
      const finished = counted > 0 && done === counted;
      progress.classList.toggle("progress--done", finished);
      progress.querySelector(".progress-bar > span").style.width =
        counted ? `${Math.round((100 * done) / counted)}%` : "0%";
      progress.querySelector(".progress-label").textContent = finished
        ? "All tasks done"
        : `${done} of ${counted} done`;
    };

    new MutationObserver(update).observe(list, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["data-state", "class"],
    });
    update();
  }

  for (const box of document.querySelectorAll('input[aria-label="New entry"]')) watchQuickEntry(box);
  const dailyLog = document.querySelector("#entries");
  if (dailyLog && document.getElementById("day-progress")) trackDailyLog(dailyLog);
})();
