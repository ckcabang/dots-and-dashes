// Keyboard handling for a Daily Log: select Entries and act on them.
//
// From the quick-entry box, Escape selects the last Entry and ArrowDown the
// first. On a selected Entry:
//   j / ArrowDown, k / ArrowUp  move the selection (up from the first returns to the box)
//   x  complete      c  cancel      o  reopen
//   e  edit (Enter saves, Escape abandons)
//   Delete / Backspace  delete for good, after confirming
(() => {
  const quickEntry = () => document.querySelector('input[aria-label="New entry"]');
  const entries = () => [...document.querySelectorAll("#entries > .entry")];
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

  async function remove(entry) {
    if (!confirm("Delete this Entry for good?")) return;
    const list = entries();
    const i = list.indexOf(entry);
    const neighbour = list[i + 1] || list[i - 1];
    await htmx.ajax("DELETE", `/entries/${entry.dataset.id}`, {
      target: entry,
      swap: "outerHTML",
    });
    (neighbour || quickEntry())?.focus();
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
    Delete: remove,
    Backspace: remove,
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
    if (handler && target.matches("#entries > .entry")) {
      event.preventDefault();
      handler(target);
    }
  });

  // The autofocus attribute is not always honoured, so make sure typing
  // starts in the quick-entry box when nothing else has focus.
  document.addEventListener("DOMContentLoaded", () => {
    if (document.activeElement === document.body) quickEntry()?.focus();
  });
})();
