/* AA Web UI - client-side logic */

// --- Sort state ---
let currentSort = "priority,due_date";
let currentDir = "asc";

function sortBy(col) {
  if (currentSort === col) {
    currentDir = currentDir === "asc" ? "desc" : "asc";
  } else {
    currentSort = col;
    currentDir = "asc";
  }
  document.getElementById("sort-field").value = currentSort;
  document.getElementById("dir-field").value = currentDir;
  htmx.trigger("#todo-tbody", "refreshTable");
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
    <td></td>
    <td><select class="inline-edit" id="new-priority">
      <option value="1">P1</option><option value="2">P2</option>
      <option value="3" selected>P3</option><option value="4">P4</option><option value="5">P5</option>
    </select></td>
    <td><input class="inline-edit" id="new-title" placeholder="Title..." autofocus></td>
    <td><input class="inline-edit" id="new-due" type="date"></td>
    <td><input class="inline-edit" id="new-category" placeholder="Category"></td>
    <td><input class="inline-edit" id="new-project" placeholder="Project"></td>
  `;
  tbody.insertBefore(tr, tbody.firstChild);

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
