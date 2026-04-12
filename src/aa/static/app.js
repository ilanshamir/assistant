/* AA Web UI - client-side logic */

// --- Sort state ---
// sortChain is an ordered list of {col, dir} entries. Click replaces the chain
// (or toggles direction if clicking the sole primary column). Shift-click
// appends a column or toggles its direction in place.
let sortChain = [{col: "priority", dir: "asc"}, {col: "due_date", dir: "asc"}];

function sortBy(e, col) {
  const isShift = e && e.shiftKey;
  if (isShift) {
    const idx = sortChain.findIndex(s => s.col === col);
    if (idx >= 0) {
      sortChain[idx].dir = sortChain[idx].dir === "asc" ? "desc" : "asc";
    } else {
      sortChain.push({col, dir: "asc"});
    }
  } else {
    if (sortChain.length === 1 && sortChain[0].col === col) {
      sortChain[0].dir = sortChain[0].dir === "asc" ? "desc" : "asc";
    } else {
      sortChain = [{col, dir: "asc"}];
    }
  }
  applySortChain();
}

function serializeSortChain() {
  return sortChain.map(s => (s.dir === "desc" ? "-" : "") + s.col).join(",");
}

function applySortChain() {
  document.getElementById("sort-field").value = serializeSortChain();
  // dir-field stays "asc" — directions are encoded per-column in sort-field.
  document.getElementById("dir-field").value = "asc";
  updateSortIndicators();
  htmx.trigger("#todo-tbody", "refreshTable");
}

function updateSortIndicators() {
  document.querySelectorAll("#todo-table thead th .sort-indicator").forEach(el => el.remove());
  const multi = sortChain.length > 1;
  sortChain.forEach((entry, idx) => {
    const th = document.querySelector(`#todo-table thead th[data-sort="${entry.col}"]`);
    if (!th) return;
    const sup = document.createElement("span");
    sup.className = "sort-indicator";
    const arrow = entry.dir === "desc" ? "↓" : "↑";
    sup.textContent = " " + arrow + (multi ? (idx + 1) : "");
    th.appendChild(sup);
  });
}

// --- Select all ---
function toggleSelectAll(el) {
  document.querySelectorAll(".todo-check").forEach(cb => cb.checked = el.checked);
  updateBulkToolbar();
}

function updateBulkToolbar() {
  const checked = document.querySelectorAll(".todo-check:checked");
  const toolbar = document.getElementById("bulk-toolbar");
  const count = document.getElementById("bulk-count");
  if (checked.length > 0) {
    toolbar.classList.remove("hidden");
    count.textContent = checked.length + " selected";
  } else {
    toolbar.classList.add("hidden");
  }
}

// --- Bulk actions ---
function getSelectedIds() {
  return Array.from(document.querySelectorAll(".todo-check:checked")).map(cb => cb.value);
}

function bulkAction(action) {
  const ids = getSelectedIds();
  if (!ids.length) return;

  let body = "ids=" + ids.join(",") + "&action=" + action;
  if (action === "priority") {
    const val = document.getElementById("bulk-priority").value;
    if (!val) return;
    body += "&value=" + val;
    document.getElementById("bulk-priority").value = "";
  } else if (action === "due") {
    const val = document.getElementById("bulk-due").value;
    if (!val) return;
    body += "&value=" + val;
    document.getElementById("bulk-due").value = "";
  } else if (action === "category" || action === "project") {
    const el = document.getElementById("bulk-" + action);
    const val = el.value.trim();
    if (!val) return;
    body += "&value=" + encodeURIComponent(val);
    el.value = "";
    const dl = document.getElementById("dl-bulk-" + action);
    if (dl && !dl.querySelector(`option[value="${CSS.escape(val)}"]`)) {
      const opt = document.createElement("option");
      opt.value = val;
      dl.appendChild(opt);
    }
  }

  fetch("/todos/bulk", {
    method: "POST",
    headers: {"Content-Type": "application/x-www-form-urlencoded", "Origin": location.origin},
    body: body,
  }).then(resp => {
    if (resp.ok) {
      htmx.trigger(document.body, "refreshTable");
      showToast("Done", "success");
    } else {
      showToast("Bulk action failed", "error");
    }
    document.getElementById("select-all").checked = false;
    updateBulkToolbar();
  });
}

// --- New todo ---
function showNewTodoRow() {
  const tbody = document.getElementById("todo-tbody");
  const existing = document.querySelector(".new-todo-row");
  if (existing) { existing.remove(); return; }

  const tr = document.createElement("tr");
  tr.className = "new-todo-row";
  tr.innerHTML = `
    <td class="col-check"></td>
    <td class="col-priority"><select class="inline-edit" id="new-priority">
      <option value="1">P1</option><option value="2">P2</option>
      <option value="3" selected>P3</option><option value="4">P4</option><option value="5">P5</option>
    </select></td>
    <td class="col-status"></td>
    <td class="col-title"><input class="inline-edit" id="new-title" placeholder="Title..." autofocus></td>
    <td class="col-due"><input class="inline-edit" id="new-due" type="date"></td>
    <td class="col-category"><input class="inline-edit" id="new-category" placeholder="Category"></td>
    <td class="col-project"><input class="inline-edit" id="new-project" placeholder="Project"></td>
  `;
  tbody.insertBefore(tr, tbody.firstChild);
  reorderRowIfNeeded(tr);

  const titleInput = document.getElementById("new-title");
  titleInput.focus();
  titleInput.addEventListener("keydown", function(e) {
    if (e.key === "Enter") saveNewTodo();
    if (e.key === "Escape") tr.remove();
  });
}

function saveNewTodo() {
  const title = document.getElementById("new-title").value.trim();
  if (!title) return;
  const body = new URLSearchParams({
    title: title,
    priority: document.getElementById("new-priority").value,
    due_date: document.getElementById("new-due").value,
    category: document.getElementById("new-category").value,
    project: document.getElementById("new-project").value,
  });

  fetch("/todos/new", {
    method: "POST",
    headers: {"Content-Type": "application/x-www-form-urlencoded", "Origin": location.origin},
    body: body.toString(),
  }).then(resp => {
    if (resp.ok) {
      htmx.trigger(document.body, "refreshTable");
      showToast("Todo created", "success");
    } else {
      showToast("Failed to create todo", "error");
    }
  });
}

// --- Detail expansion ---
function toggleDetail(todoId, el) {
  const existing = document.querySelector(`[data-detail-for="${todoId}"]`);
  if (existing) { existing.remove(); return; }
  // Close other details
  document.querySelectorAll(".todo-detail").forEach(d => d.remove());

  fetch(`/todos/${todoId}/detail`).then(r => r.text()).then(html => {
    const row = el.closest("tr");
    row.insertAdjacentHTML("afterend", html);
    htmx.process(document.querySelector(`[data-detail-for="${todoId}"]`));
  });
}

// --- Chat ---
let chatHistory = [];

function sendChat() {
  const input = document.getElementById("chat-input");
  const msg = input.value.trim();
  if (!msg) return;
  input.value = "";

  appendChatMessage("user", msg);
  chatHistory.push({role: "user", content: msg});

  const msgDiv = appendChatMessage("assistant", "");
  const bubble = msgDiv.querySelector(".chat-bubble");

  fetch("/chat", {
    method: "POST",
    headers: {"Content-Type": "application/json", "Origin": location.origin},
    body: JSON.stringify({message: msg, history: chatHistory}),
  }).then(resp => {
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let fullText = "";
    let buffer = "";

    function read() {
      reader.read().then(({done, value}) => {
        if (done) {
          chatHistory.push({role: "assistant", content: fullText});
          return;
        }
        buffer += decoder.decode(value, {stream: true});
        const lines = buffer.split("\n");
        buffer = lines.pop();

        let dataAccum = "";  // accumulate multi-line data fields
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            msgDiv.dataset.eventType = line.slice(7).trim();
            dataAccum = "";
          } else if (line.startsWith("data: ")) {
            dataAccum += (dataAccum ? "\n" : "") + line.slice(6);
          } else if (line === "") {
            // Empty line = end of SSE event, dispatch accumulated data
            if (dataAccum !== "") {
              const eventType = msgDiv.dataset.eventType || "text";
              if (eventType === "text") {
                fullText += dataAccum;
                bubble.textContent = fullText;
              } else if (eventType === "action") {
                try {
                  const action = JSON.parse(dataAccum);
                  addActionButton(msgDiv, action);
                } catch(e) {}
              } else if (eventType === "error") {
                bubble.textContent += "\n[Error: " + dataAccum + "]";
                bubble.style.color = "var(--danger)";
              }
              dataAccum = "";
              msgDiv.dataset.eventType = "";
            }
          }
        }
        // Scroll to bottom
        const container = document.getElementById("chat-messages");
        container.scrollTop = container.scrollHeight;
        read();
      });
    }
    read();
  }).catch(err => {
    bubble.textContent = "Error: " + err.message;
    bubble.style.color = "var(--danger)";
  });
}

function appendChatMessage(role, content) {
  const container = document.getElementById("chat-messages");
  const div = document.createElement("div");
  div.className = "chat-msg chat-" + role;
  div.innerHTML = `<div class="chat-bubble">${escapeHtml(content)}</div>`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

function addActionButton(msgDiv, action) {
  let actionsDiv = msgDiv.querySelector(".chat-actions");
  if (!actionsDiv) {
    actionsDiv = document.createElement("div");
    actionsDiv.className = "chat-actions";
    msgDiv.appendChild(actionsDiv);
  }
  const btn = document.createElement("button");
  btn.className = "action-btn";
  btn.onclick = () => executeAction(action);

  if (action.type === "create_todo") {
    btn.textContent = `Create: "${action.title}" P${action.priority || 3}`;
  } else if (action.type === "mark_done") {
    btn.textContent = `Done: ${action.todo_id}`;
  } else if (action.type === "set_priority") {
    btn.textContent = `Set P${action.priority}: ${action.todo_id}`;
  } else if (action.type === "set_due") {
    btn.textContent = `Due ${action.due}: ${action.todo_id}`;
  } else if (action.type === "delete_todo") {
    btn.textContent = `Delete: ${action.todo_id}`;
  }
  actionsDiv.appendChild(btn);
}

function executeAction(action) {
  fetch("/chat/action", {
    method: "POST",
    headers: {"Content-Type": "application/json", "Origin": location.origin},
    body: JSON.stringify(action),
  }).then(resp => resp.json()).then(data => {
    if (data.ok) {
      showToast(data.message || "Done", "success");
      htmx.trigger(document.body, "refreshTable");
    } else {
      showToast(data.error || "Failed", "error");
    }
  });
}

function clearChat() {
  document.getElementById("chat-messages").innerHTML = "";
  chatHistory = [];
}

function escapeHtml(text) {
  const d = document.createElement("div");
  d.textContent = text;
  return d.innerHTML;
}

// --- Toast ---
function showToast(msg, type) {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = "toast toast-" + type;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

// --- Chat resize ---
(function() {
  const panel = document.getElementById("chat-panel");
  const drag = document.getElementById("chat-drag");
  let startY, startH;

  drag.addEventListener("mousedown", e => {
    startY = e.clientY;
    startH = panel.offsetHeight;
    document.addEventListener("mousemove", onDrag);
    document.addEventListener("mouseup", () => {
      document.removeEventListener("mousemove", onDrag);
    }, {once: true});
    e.preventDefault();
  });

  function onDrag(e) {
    const h = startH - (e.clientY - startY);
    panel.style.height = Math.max(80, Math.min(window.innerHeight * 0.5, h)) + "px";
  }
})();

// --- htmx event handling ---
document.body.addEventListener("htmx:responseError", function() {
  showToast("Request failed", "error");
});

// --- Undo ---
function undoLast() {
  fetch("/todos/undo", {
    method: "POST",
    headers: {"Origin": location.origin},
  }).then(resp => {
    if (resp.ok) {
      htmx.trigger(document.body, "refreshTable");
      showToast("Undone", "success");
    } else {
      showToast("Undo failed", "error");
    }
  });
}

document.addEventListener("keydown", function(e) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !e.shiftKey && !e.altKey) {
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
    e.preventDefault();
    undoLast();
  }
});

// --- Column customization (resize + reorder) ---
// Persisted in localStorage. Widths keyed by col-* class, order is an array
// of col-* classes excluding col-check (which stays pinned leftmost).

const COL_WIDTHS_KEY = "aa.colWidths";
const COL_ORDER_KEY = "aa.colOrder";
let colWidths = {};
let colOrder = null;

function getColClass(el) {
  for (const cls of el.classList) {
    if (cls.startsWith("col-")) return cls;
  }
  return null;
}

function loadColState() {
  try { colWidths = JSON.parse(localStorage.getItem(COL_WIDTHS_KEY) || "{}"); }
  catch { colWidths = {}; }
  try {
    const raw = localStorage.getItem(COL_ORDER_KEY);
    colOrder = raw ? JSON.parse(raw) : null;
  } catch { colOrder = null; }
}

function saveColWidths() { localStorage.setItem(COL_WIDTHS_KEY, JSON.stringify(colWidths)); }
function saveColOrder() { localStorage.setItem(COL_ORDER_KEY, JSON.stringify(colOrder)); }

function applyColWidths() {
  const style = document.getElementById("col-width-overrides");
  if (!style) return;
  const rules = Object.entries(colWidths).map(([cls, w]) =>
    `.${cls} { width: ${w}px !important; min-width: ${w}px !important; max-width: ${w}px !important; }`
  );
  style.textContent = rules.join("\n");
}

function applyColOrderToRow(row) {
  if (!colOrder) return;
  const cells = Array.from(row.children);
  // Skip rows whose structure doesn't match (detail rows, empty-state, etc.)
  if (cells.length < 2) return;
  if (cells.some(c => c.hasAttribute("colspan"))) return;
  // Map only reorderable cells; the col-check cell stays pinned in place.
  const byClass = new Map();
  for (const c of cells) {
    const cls = getColClass(c);
    if (cls && cls !== "col-check") byClass.set(cls, c);
  }
  for (const cls of colOrder) {
    if (!byClass.has(cls)) return;
  }
  for (const c of byClass.values()) row.removeChild(c);
  for (const cls of colOrder) row.appendChild(byClass.get(cls));
}

function reorderRowIfNeeded(row) { applyColOrderToRow(row); }

function applyColOrder() {
  if (!colOrder) return;
  const headRow = document.querySelector("#todo-table thead tr");
  if (headRow) applyColOrderToRow(headRow);
  document.querySelectorAll("#todo-tbody > tr").forEach(applyColOrderToRow);
}

function getDefaultOrder() {
  return Array.from(document.querySelectorAll("#todo-table thead th"))
    .map(getColClass)
    .filter(cls => cls && cls !== "col-check");
}

// Resize
let resizeState = null;
function setupResize() {
  document.querySelectorAll("#todo-table thead th").forEach(th => {
    if (getColClass(th) === "col-check") return;
    if (th.querySelector(".resize-handle")) return;
    const h = document.createElement("div");
    h.className = "resize-handle";
    h.addEventListener("mousedown", e => startResize(e, th));
    h.addEventListener("click", e => e.stopPropagation());
    h.addEventListener("dblclick", e => {
      e.stopPropagation();
      const cls = getColClass(th);
      if (cls) { delete colWidths[cls]; saveColWidths(); applyColWidths(); }
    });
    th.appendChild(h);
  });
}

function startResize(e, th) {
  e.preventDefault();
  e.stopPropagation();
  const cls = getColClass(th);
  if (!cls) return;
  resizeState = { cls, startX: e.clientX, startWidth: th.getBoundingClientRect().width };
  document.body.classList.add("col-resizing");
  document.addEventListener("mousemove", doResize);
  document.addEventListener("mouseup", endResize, { once: true });
}

function doResize(e) {
  if (!resizeState) return;
  const w = Math.max(30, Math.round(resizeState.startWidth + (e.clientX - resizeState.startX)));
  colWidths[resizeState.cls] = w;
  applyColWidths();
}

function endResize() {
  if (!resizeState) return;
  saveColWidths();
  resizeState = null;
  document.body.classList.remove("col-resizing");
  document.removeEventListener("mousemove", doResize);
}

// Reorder (HTML5 drag-and-drop)
function setupReorder() {
  document.querySelectorAll("#todo-table thead th").forEach(th => {
    if (getColClass(th) === "col-check") return;
    th.draggable = true;
    th.addEventListener("dragstart", e => {
      if (resizeState) { e.preventDefault(); return; }
      const cls = getColClass(th);
      if (!cls) return;
      e.dataTransfer.setData("text/plain", cls);
      e.dataTransfer.effectAllowed = "move";
      th.classList.add("dragging");
    });
    th.addEventListener("dragend", () => th.classList.remove("dragging"));
    th.addEventListener("dragover", e => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      th.classList.add("drag-over");
    });
    th.addEventListener("dragleave", () => th.classList.remove("drag-over"));
    th.addEventListener("drop", e => {
      e.preventDefault();
      th.classList.remove("drag-over");
      const src = e.dataTransfer.getData("text/plain");
      const dst = getColClass(th);
      if (src && dst && src !== dst) moveColumn(src, dst);
    });
  });
}

function moveColumn(src, dst) {
  const order = (colOrder ? [...colOrder] : getDefaultOrder());
  const si = order.indexOf(src);
  if (si < 0) return;
  order.splice(si, 1);
  const di = order.indexOf(dst);
  if (di < 0) return;
  order.splice(di, 0, src);
  colOrder = order;
  saveColOrder();
  applyColOrder();
}

function resetColumns() {
  localStorage.removeItem(COL_WIDTHS_KEY);
  localStorage.removeItem(COL_ORDER_KEY);
  colWidths = {};
  colOrder = null;
  document.getElementById("col-width-overrides").textContent = "";
  location.reload();
}

function initColumns() {
  loadColState();
  applyColWidths();
  setupResize();
  setupReorder();
  applyColOrder();
}

document.addEventListener("DOMContentLoaded", () => {
  initColumns();
  updateSortIndicators();
});
document.body.addEventListener("htmx:afterSwap", e => {
  if (e.target && e.target.id === "todo-tbody") applyColOrder();
});
