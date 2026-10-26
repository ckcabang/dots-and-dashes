// Keyboard handling for a Daily Log, a Monthly Log's task list and the Future
// Log: select Entries and act on them. Selection runs across every list on
// the page, so it moves from one Future Log month into the next.
//
// From the quick-entry box, Escape selects the last Entry and ArrowDown the
// first. On a selected Entry:
//   j / ArrowDown, k / ArrowUp  move the selection (up from the first returns to the box)
//   x  complete      c  cancel      o  reopen
//   e  edit (Enter saves, Escape abandons)
//   Tab  nest a Note under the Task or Event above it    Shift+Tab  un-nest it
//   Delete / Backspace  delete for good, after confirming
//   m  Migrate a Task to the day being planned: today, or tomorrow (the night
//      before) if it is already on today's Daily Log
//   M  Migrate a Task to this month's task list
//   s  Schedule a Task: asks for a date (YYYY-MM-DD) or a month (YYYY-MM)
(() => {
  const quickEntry = () => document.querySelector('input[aria-label="New entry"]');
  const ENTRY = ".entries > .entry";
  const entries = () => [...document.querySelectorAll(ENTRY)];
  const byId = (id) => document.getElementById(`entry-${id}`);

  function move(from, step) {
    const list = entries();
    const next = list[list.indexOf(from) + step];
    if (next) next.focus();
    else if (step < 0) quickEntry()?.focus();
  }

  // Ask the server to act on an Entry and swap in the line it sends back.
  async function act(entry, verb, path, values) {
    const id = entry.dataset.id;
    await htmx.ajax(verb, `/entries/${id}${path}`, {
      target: entry,
      swap: "outerHTML",
      values,
    });
    byId(id)?.focus();
  }

  // Nesting moves Entries around, so the server redraws the whole Daily Log;
  // the same Entry is then selected again.
  async function nest(entry, event) {
    const id = entry.dataset.id;
    const action = event.shiftKey ? "un-nest" : "nest";
    await htmx.ajax("POST", `/entries/${id}/${action}`, {
      target: "#entries",
      swap: "innerHTML",
    });
    byId(id)?.focus();
  }

  // Migrating moves the Task's Nested Notes away, and its copy may land on
  // this page, so every list on the page is redrawn afterwards.
  async function migrate(entry, values) {
    const id = entry.dataset.id;
    const migrated = await fetch(`/entries/${id}/migrate`, {
      method: "POST",
      body: new URLSearchParams(values),
    });
    if (!migrated.ok) {
      entry.focus();
      return;
    }
    const page = await fetch(location.pathname);
    const fresh = new DOMParser().parseFromString(await page.text(), "text/html");
    for (const list of document.querySelectorAll(".entries[id]")) {
      const redrawn = fresh.getElementById(list.id);
      if (redrawn) list.replaceChildren(...redrawn.children);
    }
    byId(id)?.focus();
  }

  const today = () => document.body.dataset.today;
  const dayAfter = (day) => {
    const next = new Date(`${day}T00:00:00Z`);
    next.setUTCDate(next.getUTCDate() + 1);
    return next.toISOString().slice(0, 10);
  };

  function migrateToPlannedDay(entry) {
    const day = entry.dataset.day;
    if (day && day >= today()) {
      migrate(entry, { to: "day", date: dayAfter(today()), night_before: "true" });
    } else {
      migrate(entry, { to: "day", date: today() });
    }
  }

  function schedule(entry) {
    const when = prompt("Schedule to a date (YYYY-MM-DD) or a month (YYYY-MM):")?.trim();
    if (/^\d{4}-\d{2}$/.test(when)) migrate(entry, { to: "future", month: when });
    else if (/^\d{4}-\d{2}-\d{2}$/.test(when)) migrate(entry, { to: "date", date: when });
    else entry.focus();
  }

  async function remove(entry) {
    if (!confirm("Delete this Entry for good?")) return;
    const list = entries();
    const i = list.indexOf(entry);
    const neighbour = list[i + 1] || list[i - 1];
    const parent = !entry.classList.contains("entry--nested");
    await htmx.ajax("DELETE", `/entries/${entry.dataset.id}`, {
      target: entry,
      swap: "outerHTML",
    });
    // A deleted parent's Nested Notes stand alone again (the database sets
    // their parent to null), so redraw the Daily Log to show them un-nested.
    if (parent && list[i + 1]?.classList.contains("entry--nested")) {
      await htmx.ajax("GET", location.pathname, {
        target: "#entries",
        select: "#entries",
        swap: "innerHTML",
      });
    }
    (byId(neighbour?.dataset.id) || quickEntry())?.focus();
  }

  function edit(entry) {
    const shown = [...entry.childNodes];
    const editor = document.createElement("input");
    editor.setAttribute("aria-label", "Edit entry");
    editor.autocomplete = "off";
    editor.value = entry.dataset.typed;
    entry.replaceChildren(editor);
    editor.focus();
    editor.addEventListener("keydown", (event) => {
      event.stopPropagation();
      if (event.key === "Enter" && editor.value.trim()) {
        event.preventDefault();
        act(entry, "POST", "", { text: editor.value });
      } else if (event.key === "Escape") {
        event.preventDefault();
        entry.replaceChildren(...shown);
        entry.focus();
      }
    });
  }

  const onEntry = {
    j: (entry) => move(entry, 1),
    ArrowDown: (entry) => move(entry, 1),
    k: (entry) => move(entry, -1),
    ArrowUp: (entry) => move(entry, -1),
    x: (entry) => act(entry, "POST", "/complete"),
    c: (entry) => act(entry, "POST", "/cancel"),
    o: (entry) => act(entry, "POST", "/reopen"),
    e: edit,
    Tab: nest,
    Delete: remove,
    Backspace: remove,
    m: migrateToPlannedDay,
    M: (entry) => migrate(entry, { to: "month", month: today().slice(0, 7) }),
    s: schedule,
  };

  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const target = event.target;
    if (target === quickEntry()) {
      const list = entries();
      const pick = { Escape: list.at(-1), ArrowDown: list[0] }[event.key];
      if (pick) {
        event.preventDefault();
        pick.focus();
      }
      return;
    }
    const handler = onEntry[event.key];
    if (handler && target.matches(ENTRY)) {
      event.preventDefault();
      handler(target, event);
    }
  });

  // The autofocus attribute is not always honoured, so make sure typing
  // starts in the quick-entry box when nothing else has focus.
  document.addEventListener("DOMContentLoaded", () => {
    if (document.activeElement === document.body) quickEntry()?.focus();
  });
})();
