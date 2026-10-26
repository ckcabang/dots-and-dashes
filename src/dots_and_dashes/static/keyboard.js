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
//        (on a Daily Log only; elsewhere Tab moves the focus on as usual)
//   Delete / Backspace  delete for good, after confirming
//   m  Migrate a Task to the day being planned
//   M  Migrate a Task to the planned day's month's task list
//   s  Schedule a Task: asks for a date (YYYY-MM-DD) or a month (YYYY-MM)
// The server decides the day being planned: tomorrow from 18:00, the night
// before, and otherwise today. Daily Migration can plan the other day; its
// choice is sent along.
//   Alt+ArrowUp / Alt+ArrowDown  reorder an untimed Entry (it re-Anchors)
// Untimed Entries can also be dragged. Timed Entries move only by changing
// their time, so they aren't draggable and the server refuses to move them.
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

  // Redraw the list an Entry is in from a fresh copy of the page, for a
  // change that reaches beyond the Entry's own line.
  async function redraw(list) {
    const selector = `#${list.id}`;
    await htmx.ajax("GET", location.pathname + location.search, {
      target: selector,
      select: selector,
      swap: "innerHTML",
    });
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

  // Notes nest only on a Daily Log.
  const canNest = (entry) => entry.matches("#entries > .entry[data-day]");

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
  // this page, so every list on the page is redrawn afterwards. A list the
  // fresh page no longer has is emptied. If the Task itself left the page, as
  // it does in Daily Migration, the selection moves on to the next Entry.
  async function migrate(entry, values) {
    const id = entry.dataset.id;
    const list = entries();
    const following = list.slice(list.indexOf(entry) + 1).map((e) => e.dataset.id);
    const migrated = await fetch(`/entries/${id}/migrate`, {
      method: "POST",
      body: new URLSearchParams(values),
    });
    if (!migrated.ok) {
      entry.focus();
      return;
    }
    const page = await fetch(location.pathname + location.search);
    const fresh = new DOMParser().parseFromString(await page.text(), "text/html");
    for (const list of document.querySelectorAll(".entries[id]")) {
      const redrawn = fresh.getElementById(list.id);
      list.replaceChildren(...(redrawn ? redrawn.children : []));
    }
    const next = [id, ...following].map(byId).find(Boolean) || entries().at(-1);
    next?.focus();
  }

  // The day Daily Migration chose to plan, if the page is one; elsewhere the
  // server's own choice stands.
  const plan = () => {
    const chosen = document.querySelector("[data-plan]")?.dataset.plan;
    return chosen ? { plan: chosen } : {};
  };

  function schedule(entry) {
    const when = prompt("Schedule to a date (YYYY-MM-DD) or a month (YYYY-MM):")?.trim();
    if (/^\d{4}-\d{2}$/.test(when)) migrate(entry, { to: "future", month: when, ...plan() });
    else if (/^\d{4}-\d{2}-\d{2}$/.test(when)) migrate(entry, { to: "date", date: when, ...plan() });
    else entry.focus();
  }

  async function remove(entry) {
    if (!confirm("Delete this Entry for good?")) return;
    const list = entries();
    const i = list.indexOf(entry);
    const neighbour = list[i + 1] || list[i - 1];
    const parent = hasNestedNotes(entry);
    const container = entry.parentElement;
    await htmx.ajax("DELETE", `/entries/${entry.dataset.id}`, {
      target: entry,
      swap: "outerHTML",
    });
    // A deleted parent's Nested Notes stand alone again, so redraw its list
    // to show them un-nested.
    if (parent) await redraw(container);
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
        save(entry, editor.value);
      } else if (event.key === "Escape") {
        event.preventDefault();
        entry.replaceChildren(...shown);
        entry.focus();
      }
    });
  }

  const isNested = (entry) => entry.classList.contains("entry--nested");
  const hasNestedNotes = (entry) =>
    !isNested(entry) && Boolean(entry.nextElementSibling?.classList.contains("entry--nested"));

  // A parent edited into a Note lets its Nested Notes stand alone, so its
  // list is redrawn to show them un-nested.
  async function save(entry, text) {
    const id = entry.dataset.id;
    const parent = hasNestedNotes(entry);
    const container = entry.parentElement;
    await act(entry, "POST", "", { text });
    if (parent) {
      await redraw(container);
      byId(id)?.focus();
    }
  }

  // An Entry and the Nested Notes under it, which move together.
  function block(list, entry) {
    const start = list.indexOf(entry);
    let end = start + 1;
    while (end < list.length && isNested(list[end])) end += 1;
    return list.slice(start, end);
  }

  // Move an untimed Entry to index `to` of the Daily Log without it and its
  // Nested Notes; the server redraws the Daily Log in its new order.
  async function reorder(entry, to) {
    const id = entry.dataset.id;
    await htmx.ajax("POST", `/entries/${id}/move`, {
      target: "#entries",
      swap: "innerHTML",
      values: { to: Math.max(0, to) },
    });
    byId(id)?.focus();
  }

  function reorderByKey(entry, key) {
    const list = entries();
    let to = list.indexOf(entry);
    if (key === "ArrowDown") {
      // Past the next Entry; the server keeps it clear of that one's Notes.
      to += 1;
    } else {
      do to -= 1; while (to > 0 && isNested(list[to]));
    }
    reorder(entry, to);
  }

  let dragged = null;
  document.addEventListener("dragstart", (event) => {
    dragged = event.target.closest?.("#entries > .entry") || null;
    if (dragged) event.dataTransfer.effectAllowed = "move";
  });
  document.addEventListener("dragover", (event) => {
    if (dragged) event.preventDefault();
  });
  document.addEventListener("drop", (event) => {
    const target = event.target.closest?.("#entries > .entry");
    if (!dragged || !target) return;
    event.preventDefault();
    const list = entries();
    const moving = block(list, dragged);
    const others = list.filter((entry) => !moving.includes(entry));
    if (!others.includes(target)) return;
    const box = target.getBoundingClientRect();
    const below = event.clientY > box.top + box.height / 2;
    reorder(dragged, others.indexOf(target) + (below ? 1 : 0));
  });
  document.addEventListener("dragend", () => {
    dragged = null;
  });

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
    m: (entry) => migrate(entry, { to: "day", ...plan() }),
    M: (entry) => migrate(entry, { to: "month", ...plan() }),
    s: schedule,
  };

  document.addEventListener("keydown", (event) => {
    const target = event.target;
    if (
      event.altKey &&
      (event.key === "ArrowUp" || event.key === "ArrowDown") &&
      target.matches("#entries > .entry[draggable=true]")
    ) {
      event.preventDefault();
      reorderByKey(target, event.key);
      return;
    }
    if (event.ctrlKey || event.metaKey || event.altKey) return;
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
      if (event.key === "Tab" && !canNest(target)) return;
      event.preventDefault();
      handler(target, event);
    }
  });

  // The autofocus attribute is not always honoured, so make sure typing
  // starts in the quick-entry box when nothing else has focus. A page with no
  // box, like Daily Migration, starts with its first Entry selected.
  document.addEventListener("DOMContentLoaded", () => {
    if (document.activeElement === document.body) (quickEntry() || entries()[0])?.focus();
  });
})();
