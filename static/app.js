const API = "/api";

// ---------------- Tab switching ----------------
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => activateTab(btn.dataset.tab));
});

function activateTab(tab) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === tab));
}

// ---------------- Health / LLM status ----------------
async function checkHealth() {
  const el = document.getElementById("llm-status");
  try {
    const res = await fetch(`${API}/health`);
    const data = await res.json();
    if (data.llm_enabled) {
      el.textContent = "Claude 연동됨";
      el.classList.remove("offline");
    } else {
      el.textContent = "키워드 모드 (API 키 없음)";
      el.classList.add("offline");
    }
  } catch (e) {
    el.textContent = "서버 연결 실패";
    el.classList.add("offline");
  }
}

// ---------------- Category colors (stable per name) ----------------
const CATEGORY_PALETTE = [
  "#ef4444", "#f59e0b", "#10b981", "#3b82f6",
  "#8b5cf6", "#ec4899", "#14b8a6", "#f97316",
];

function categoryColor(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return CATEGORY_PALETTE[hash % CATEGORY_PALETTE.length];
}

function formatDue(dueDate, dueTime) {
  const [, m, d] = dueDate.split("-").map(Number);
  return dueTime ? `${m}/${d} ${dueTime}` : `${m}/${d}`;
}

// ---------------- Tasks ----------------
const taskForm = document.getElementById("task-form");
const taskInput = document.getElementById("task-input");
const taskCategorySelect = document.getElementById("task-category-select");
const taskGroups = document.getElementById("task-groups");

taskForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = taskInput.value.trim();
  if (!text) return;
  const category = taskCategorySelect.value || null;
  taskInput.value = "";
  taskInput.disabled = true;
  try {
    await fetch(`${API}/tasks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, category }),
    });
    taskCategorySelect.value = "";
    // A leftover tag filter would otherwise hide a freshly-added task that
    // doesn't happen to carry that tag, which looks exactly like every task
    // vanishing. Always show the new task by clearing the filter here.
    activeTagFilter = null;
    // A task can carry a due date/time now, so it may affect the calendar too.
    await Promise.all([loadTasks(), refreshCalendarViews()]);
  } finally {
    taskInput.disabled = false;
    taskInput.focus();
  }
});

function refreshCalendarViews() {
  return Promise.all([renderCalendarGrid(), loadBriefing()]);
}

async function loadTaskCategoryOptions() {
  const res = await fetch(`${API}/categories?kind=task`);
  const categories = await res.json();
  const current = taskCategorySelect.value;
  taskCategorySelect.innerHTML = `<option value="">자동 분류 (AI)</option>`;
  categories.forEach((cat) => {
    const opt = document.createElement("option");
    opt.value = cat;
    opt.textContent = cat;
    taskCategorySelect.appendChild(opt);
  });
  const newOpt = document.createElement("option");
  newOpt.value = "__new__";
  newOpt.textContent = "+ 새 카테고리 만들기...";
  taskCategorySelect.appendChild(newOpt);
  if (categories.includes(current)) taskCategorySelect.value = current;
  return categories;
}

// ---------------- Tag filter ----------------
const tagFilterEl = document.getElementById("tag-filter");
let activeTagFilter = null;

function renderTagFilter(allTasks) {
  const counts = {};
  allTasks.forEach((t) => (t.tags || []).forEach((tag) => (counts[tag] = (counts[tag] || 0) + 1)));
  const tags = Object.keys(counts).sort();

  if (tags.length === 0) {
    activeTagFilter = null;
    tagFilterEl.hidden = true;
    tagFilterEl.innerHTML = "";
    return;
  }

  tagFilterEl.hidden = false;
  const allChip = `<button class="tag-filter-chip${activeTagFilter ? "" : " active"}" data-tag="">전체</button>`;
  const tagChips = tags
    .map(
      (tag) =>
        `<button class="tag-filter-chip${activeTagFilter === tag ? " active" : ""}" data-tag="${escapeAttr(tag)}">#${escapeHtml(tag)} (${counts[tag]})</button>`
    )
    .join("");
  tagFilterEl.innerHTML = allChip + tagChips;

  tagFilterEl.querySelectorAll(".tag-filter-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeTagFilter = btn.dataset.tag || null;
      loadTasks();
    });
  });
}

async function loadTasks() {
  const [groups] = await Promise.all([
    fetch(`${API}/tasks?grouped=true`).then((r) => r.json()),
    loadTaskCategoryOptions(),
  ]);
  taskGroups.innerHTML = "";

  const categories = Object.keys(groups);
  renderTagFilter(categories.flatMap((c) => groups[c]));

  if (categories.length === 0) {
    taskGroups.innerHTML = `<div class="empty-state">아직 등록된 할 일이 없습니다.</div>`;
    return;
  }

  let renderedAny = false;

  categories.forEach((cat) => {
    let items = groups[cat];
    if (activeTagFilter) {
      items = items.filter((t) => (t.tags || []).includes(activeTagFilter));
      if (items.length === 0) return; // hide categories with no match while filtering
    }
    renderedAny = true;

    const card = document.createElement("div");
    card.className = "group-card";
    card.dataset.category = cat;
    card.innerHTML = `
      <div class="group-header">
        <h3><span class="category-name">${escapeHtml(cat)}</span> <span class="category-count">(${items.length})</span></h3>
        <button class="icon-btn rename-cat-btn" data-category="${escapeAttr(cat)}" title="카테고리 이름 변경">✏️</button>
      </div>
    `;

    if (items.length === 0) {
      const hint = document.createElement("div");
      hint.className = "group-drop-hint";
      hint.textContent = "여기로 할 일을 끌어다 놓으세요.";
      card.appendChild(hint);
    }

    items.forEach((t) => {
      const row = document.createElement("div");
      row.className = "task-item" + (t.completed ? " completed" : "");
      row.draggable = true;
      row.dataset.id = t.id;

      const dueBadge = t.due_date ? `<span class="due-badge">🕒 ${formatDue(t.due_date, t.due_time)}</span>` : "";
      const tagChips = (t.tags || []).map((tag) => `<span class="tag-chip">#${escapeHtml(tag)}</span>`).join("");
      const metaHtml = dueBadge || tagChips ? `<div class="task-meta">${dueBadge}${tagChips}</div>` : "";

      row.innerHTML = `
        <div class="task-left">
          <button class="check-btn ${t.completed ? "checked" : ""}" data-id="${t.id}" title="완료 처리"></button>
          <div class="task-text-wrap">
            <span class="task-text" data-id="${t.id}">${escapeHtml(t.text)}</span>
            ${metaHtml}
          </div>
        </div>
        <div class="task-actions">
          <button class="icon-btn edit-task-btn" data-id="${t.id}" title="할 일 수정">✏️</button>
          <button class="icon-btn schedule-btn" data-text="${escapeAttr(t.text)}" title="캘린더에 일정으로 추가">📅</button>
          <button class="delete-btn" data-id="${t.id}">삭제</button>
        </div>
      `;
      row.addEventListener("dragstart", (e) => {
        e.dataTransfer.setData("text/plain", String(t.id));
        row.classList.add("dragging");
      });
      row.addEventListener("dragend", () => row.classList.remove("dragging"));
      card.appendChild(row);
    });

    // Drop target behaviour for this category card.
    card.addEventListener("dragover", (e) => {
      e.preventDefault();
      card.classList.add("drag-over");
    });
    card.addEventListener("dragleave", () => card.classList.remove("drag-over"));
    card.addEventListener("drop", async (e) => {
      e.preventDefault();
      card.classList.remove("drag-over");
      const taskId = e.dataTransfer.getData("text/plain");
      if (!taskId) return;
      await fetch(`${API}/tasks/${taskId}/category`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category: cat }),
      });
      await loadTasks();
    });

    taskGroups.appendChild(card);
  });

  if (!renderedAny) {
    taskGroups.innerHTML = `
      <div class="empty-state">
        #${escapeHtml(activeTagFilter)} 태그가 달린 할 일이 없습니다.<br />
        <button class="ghost-btn" id="clear-tag-filter-btn" type="button" style="margin-top:8px;">전체 보기</button>
      </div>`;
    document.getElementById("clear-tag-filter-btn").addEventListener("click", () => {
      activeTagFilter = null;
      loadTasks();
    });
  }

  taskGroups.querySelectorAll(".check-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await fetch(`${API}/tasks/${btn.dataset.id}/toggle`, { method: "PATCH" });
      await Promise.all([loadTasks(), refreshCalendarViews()]);
    });
  });
  taskGroups.querySelectorAll(".delete-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await fetch(`${API}/tasks/${btn.dataset.id}`, { method: "DELETE" });
      await Promise.all([loadTasks(), refreshCalendarViews()]);
    });
  });
  taskGroups.querySelectorAll(".schedule-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      taskEventInput.value = btn.dataset.text;
      taskEventForm.hidden = false;
      taskEventInput.focus();
    });
  });

  taskGroups.querySelectorAll(".edit-task-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.id;
      const span = taskGroups.querySelector(`.task-text[data-id="${id}"]`);
      if (!span) return;
      startInlineEdit(span, span.textContent, async (newText) => {
        await fetch(`${API}/tasks/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: newText }),
        });
        await Promise.all([loadTasks(), refreshCalendarViews()]);
      });
    });
  });

  taskGroups.querySelectorAll(".rename-cat-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const oldName = btn.dataset.category;
      const nameSpan = btn.closest(".group-card")?.querySelector(".category-name");
      if (!nameSpan) return;
      startInlineEdit(nameSpan, oldName, async (newName) => {
        await fetch(`${API}/categories/rename`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: "task", old_name: oldName, new_name: newName }),
        });
        await loadTasks();
      });
    });
  });
}

// Replaces `el` with a text input pre-filled with `currentValue`; Enter or
// blur commits via `onCommit(newValue)` (skipped if unchanged/empty),
// Escape just re-renders the task list to restore the original content.
function startInlineEdit(el, currentValue, onCommit) {
  const input = document.createElement("input");
  input.type = "text";
  input.className = "inline-edit-input";
  input.value = currentValue;
  el.replaceWith(input);
  input.focus();
  input.select();

  let settled = false;
  const commit = async () => {
    if (settled) return;
    settled = true;
    const value = input.value.trim();
    if (!value || value === currentValue) {
      await loadTasks();
      return;
    }
    await onCommit(value);
  };
  const cancel = () => {
    if (settled) return;
    settled = true;
    loadTasks();
  };

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      commit();
    } else if (e.key === "Escape") {
      e.preventDefault();
      cancel();
    }
  });
  input.addEventListener("blur", commit);
}

// ---------------- New category (Tasks tab) ----------------
const newCategoryBtn = document.getElementById("new-category-btn");
const newCategoryForm = document.getElementById("new-category-form");
const newCategoryInput = document.getElementById("new-category-input");
const newCategoryCancel = document.getElementById("new-category-cancel");

let selectAfterCreate = false; // came from the "+ 새 카테고리 만들기..." dropdown option

newCategoryBtn.addEventListener("click", () => {
  newCategoryForm.hidden = !newCategoryForm.hidden;
  selectAfterCreate = false;
  if (!newCategoryForm.hidden) newCategoryInput.focus();
});
newCategoryCancel.addEventListener("click", () => {
  newCategoryForm.hidden = true;
  newCategoryInput.value = "";
  if (selectAfterCreate) taskCategorySelect.value = "";
  selectAfterCreate = false;
});
newCategoryForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = newCategoryInput.value.trim();
  if (!name) return;
  await fetch(`${API}/categories`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, kind: "task" }),
  });
  newCategoryInput.value = "";
  newCategoryForm.hidden = true;
  await loadTasks();
  if (selectAfterCreate) {
    taskCategorySelect.value = name; // straight into the task-add row, ready to use
    selectAfterCreate = false;
    taskInput.focus();
  }
});

// Picking "+ 새 카테고리 만들기..." from the task category dropdown opens the
// same inline form, so a new category can be created without leaving the row.
taskCategorySelect.addEventListener("change", () => {
  if (taskCategorySelect.value === "__new__") {
    taskCategorySelect.value = "";
    selectAfterCreate = true;
    newCategoryForm.hidden = false;
    newCategoryInput.focus();
  }
});

// ---------------- Quick "add as event" from Tasks tab ----------------
const taskEventToggleBtn = document.getElementById("task-event-toggle-btn");
const taskEventForm = document.getElementById("task-event-form");
const taskEventInput = document.getElementById("task-event-input");
const taskEventMsg = document.getElementById("task-event-msg");

taskEventToggleBtn.addEventListener("click", () => {
  taskEventForm.hidden = !taskEventForm.hidden;
  if (!taskEventForm.hidden) taskEventInput.focus();
});

taskEventForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = taskEventInput.value.trim();
  if (!text) return;
  taskEventInput.disabled = true;
  try {
    await fetch(`${API}/events`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    taskEventInput.value = "";
    taskEventMsg.textContent = `"${text}" 일정이 캘린더에 추가되었습니다. (캘린더 탭에서 확인)`;
    taskEventMsg.hidden = false;
    setTimeout(() => (taskEventMsg.hidden = true), 4000);
    // Keep the calendar tab's data fresh for whenever the user switches over.
    renderCalendarGrid();
    loadBriefing();
  } finally {
    taskEventInput.disabled = false;
  }
});

// ---------------- Calendar / Month grid ----------------
const eventForm = document.getElementById("event-form");
const eventInput = document.getElementById("event-input");
const briefingBox = document.getElementById("briefing-box");
const eventListEl = document.getElementById("event-list");
const briefingRangeEl = document.getElementById("briefing-range");
const calGrid = document.getElementById("calendar-grid");
const calMonthLabel = document.getElementById("cal-month-label");
const customRangeForm = document.getElementById("custom-range-form");
const customStartInput = document.getElementById("custom-start");
const customEndInput = document.getElementById("custom-end");

let currentPeriod = "daily";
let viewDate = new Date(); // the currently selected day; grid shows its month

// ---------------- Event draft (analyze → confirm) ----------------
const eventDraftCard = document.getElementById("event-draft-card");
const draftTitleEl = document.getElementById("draft-title");
const draftWhenEl = document.getElementById("draft-when");
const draftNoteEl = document.getElementById("draft-note");
const draftCategorySelect = document.getElementById("draft-category-select");
const draftCategoryBadge = document.getElementById("draft-category-badge");
const draftConfirmBtn = document.getElementById("draft-confirm-btn");
const draftCancelBtn = document.getElementById("draft-cancel-btn");

let currentDraft = null;

eventForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = eventInput.value.trim();
  if (!text) return;
  eventInput.disabled = true;
  try {
    const res = await fetch(`${API}/events/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) return;
    const draft = await res.json();
    showEventDraft(text, draft);
  } finally {
    eventInput.disabled = false;
  }
});

function showEventDraft(originalText, draft) {
  currentDraft = { ...draft, text: originalText };

  draftTitleEl.textContent = draft.title;
  const timeStr = draft.start_time ? `${draft.start_time}${draft.end_time ? " ~ " + draft.end_time : ""}` : "시간 미정";
  draftWhenEl.textContent = `${draft.date} · ${timeStr}`;

  draftNoteEl.textContent = draft.note ? `📍 ${draft.note}` : "";
  draftNoteEl.hidden = !draft.note;

  const options = [...draft.existing_categories];
  if (draft.category_is_new && !options.includes(draft.category)) options.push(draft.category);
  draftCategorySelect.innerHTML = options
    .map((c) => `<option value="${escapeAttr(c)}">${escapeHtml(c)}</option>`)
    .join("");
  draftCategorySelect.value = draft.category;

  updateDraftBadge();
  eventDraftCard.hidden = false;
}

function updateDraftBadge() {
  const isNew = !currentDraft.existing_categories.includes(draftCategorySelect.value);
  draftCategoryBadge.textContent = isNew ? "🆕 새 카테고리 제안" : "✅ 기존 카테고리 추천";
  draftCategoryBadge.classList.toggle("new", isNew);
}

draftCategorySelect.addEventListener("change", updateDraftBadge);

draftConfirmBtn.addEventListener("click", async () => {
  if (!currentDraft) return;
  draftConfirmBtn.disabled = true;
  try {
    await fetch(`${API}/events`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: currentDraft.text,
        title: currentDraft.title,
        date: currentDraft.date,
        start_time: currentDraft.start_time,
        end_time: currentDraft.end_time,
        note: currentDraft.note,
        category: draftCategorySelect.value,
      }),
    });
    eventDraftCard.hidden = true;
    currentDraft = null;
    eventInput.value = "";
    eventInput.focus();
    await Promise.all([renderCalendarGrid(), loadBriefing()]);
  } finally {
    draftConfirmBtn.disabled = false;
  }
});

draftCancelBtn.addEventListener("click", () => {
  eventDraftCard.hidden = true;
  currentDraft = null;
});

document.querySelectorAll(".period-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".period-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentPeriod = btn.dataset.period;
    if (currentPeriod === "custom") {
      customRangeForm.hidden = false;
      if (!customStartInput.value) customStartInput.value = toISODate(viewDate);
      if (!customEndInput.value) customEndInput.value = toISODate(viewDate);
    } else {
      customRangeForm.hidden = true;
      loadBriefing();
    }
  });
});

customRangeForm.addEventListener("submit", (e) => {
  e.preventDefault();
  if (!customStartInput.value || !customEndInput.value) return;
  loadBriefing();
});

document.getElementById("cal-prev").addEventListener("click", () => shiftMonth(-1));
document.getElementById("cal-next").addEventListener("click", () => shiftMonth(1));
document.getElementById("cal-today").addEventListener("click", () => {
  viewDate = new Date();
  renderCalendarGrid();
  loadBriefing();
});

function shiftMonth(dir) {
  viewDate = new Date(viewDate.getFullYear(), viewDate.getMonth() + dir, 1);
  renderCalendarGrid();
  loadBriefing();
}

function toISODate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

async function renderCalendarGrid() {
  const year = viewDate.getFullYear();
  const month = viewDate.getMonth(); // 0-indexed
  calMonthLabel.textContent = `${year}년 ${month + 1}월`;

  const firstOfMonth = new Date(year, month, 1);
  const lastOfMonth = new Date(year, month + 1, 0);
  const gridStart = new Date(firstOfMonth);
  gridStart.setDate(gridStart.getDate() - gridStart.getDay()); // back up to Sunday
  const gridEnd = new Date(lastOfMonth);
  gridEnd.setDate(gridEnd.getDate() + (6 - gridEnd.getDay())); // forward to Saturday

  const res = await fetch(`${API}/schedule?start=${toISODate(gridStart)}&end=${toISODate(gridEnd)}`);
  const { events, tasks } = await res.json();
  const itemsByDate = {};
  events.forEach((ev) => {
    (itemsByDate[ev.date] = itemsByDate[ev.date] || []).push({ category: ev.category, title: ev.title, kind: "event" });
  });
  tasks.forEach((t) => {
    (itemsByDate[t.due_date] = itemsByDate[t.due_date] || []).push({ category: t.category, title: t.text, kind: "task" });
  });

  calGrid.innerHTML = "";
  WEEKDAYS.forEach((w, i) => {
    const el = document.createElement("div");
    el.className = "cal-weekday" + (i === 0 ? " sun" : i === 6 ? " sat" : "");
    el.textContent = w;
    calGrid.appendChild(el);
  });

  const today = new Date();
  const cursor = new Date(gridStart);
  while (cursor <= gridEnd) {
    const iso = toISODate(cursor);
    const dayItems = itemsByDate[iso] || [];
    const cell = document.createElement("div");
    cell.className = "cal-cell";
    if (cursor.getMonth() !== month) cell.classList.add("other-month");
    if (sameDay(cursor, today)) cell.classList.add("today");
    if (sameDay(cursor, viewDate)) cell.classList.add("selected");

    const dotsHtml = dayItems
      .slice(0, 4)
      .map(
        (it) =>
          `<span class="cal-dot ${it.kind}" style="background:${categoryColor(it.category)}" title="${escapeAttr(it.title)}"></span>`
      )
      .join("");
    const moreHtml = dayItems.length > 4 ? `<span class="cal-more">+${dayItems.length - 4}</span>` : "";

    cell.innerHTML = `
      <span class="cal-daynum">${cursor.getDate()}</span>
      <div class="cal-dots">${dotsHtml}${moreHtml}</div>
    `;

    const clickedDate = new Date(cursor);
    cell.addEventListener("click", () => {
      viewDate = clickedDate;
      renderCalendarGrid();
      loadBriefing();
      openDayDetail(clickedDate);
    });

    calGrid.appendChild(cell);
    cursor.setDate(cursor.getDate() + 1);
  }
}

async function loadBriefing() {
  let url;
  if (currentPeriod === "custom") {
    if (!customStartInput.value || !customEndInput.value) return;
    url = `${API}/briefing/custom?start=${customStartInput.value}&end=${customEndInput.value}`;
  } else {
    url = `${API}/briefing/${currentPeriod}?ref=${toISODate(viewDate)}`;
  }
  const res = await fetch(url);
  const data = await res.json();

  briefingRangeEl.textContent = `${data.start} ~ ${data.end}`;
  briefingBox.textContent = data.briefing;
  renderAgenda(data.events, data.tasks);
}

function renderAgenda(events, tasks) {
  renderAgendaInto(eventListEl, events, tasks, () => Promise.all([loadBriefing(), loadTasks()]));
}

// Renders a sorted events+tasks list into `container` with complete/delete
// actions wired up; `onChange` re-fetches whatever should reflect the edit
// (used by both the period agenda and the day-detail modal).
function renderAgendaInto(container, events, tasks, onChange) {
  container.innerHTML = "";

  const combined = [
    ...events.map((e) => ({ kind: "event", date: e.date, time: e.start_time || "", data: e })),
    ...tasks.map((t) => ({ kind: "task", date: t.due_date, time: t.due_time || "", data: t })),
  ];
  combined.sort((a, b) => {
    if (a.date !== b.date) return a.date < b.date ? -1 : 1;
    const at = a.time || "99:99";
    const bt = b.time || "99:99";
    return at < bt ? -1 : at > bt ? 1 : 0;
  });

  if (combined.length === 0) {
    container.innerHTML = `<div class="empty-state">해당 기간에 일정/할 일이 없습니다.</div>`;
    return;
  }

  combined.forEach(({ kind, date, time, data }) => {
    const row = document.createElement("div");
    row.className = "event-item";
    const isTask = kind === "task";
    const timeStr = time || "시간 미정";
    const title = isTask ? data.text : data.title;
    const color = categoryColor(data.category);

    const leadingHtml = isTask
      ? `<button class="check-btn small ${data.completed ? "checked" : ""}" data-id="${data.id}" title="완료 처리"></button>`
      : `<span class="kind-icon">📅</span>`;

    row.innerHTML = `
      <div class="event-meta">
        <div>
          ${leadingHtml}
          <span class="tag" style="background:${color}22;color:${color}">${escapeHtml(data.category)}</span>
          <span class="event-title${isTask && data.completed ? " completed-text" : ""}">${escapeHtml(title)}</span>
        </div>
        <span class="event-sub">${date} · ${timeStr}${!isTask && data.note ? " · " + escapeHtml(data.note) : ""}</span>
      </div>
      <button class="delete-btn" data-kind="${kind}" data-id="${data.id}">삭제</button>
    `;
    container.appendChild(row);
  });

  container.querySelectorAll(".check-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await fetch(`${API}/tasks/${btn.dataset.id}/toggle`, { method: "PATCH" });
      await onChange();
    });
  });
  container.querySelectorAll(".delete-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const path = btn.dataset.kind === "task" ? `tasks/${btn.dataset.id}` : `events/${btn.dataset.id}`;
      await fetch(`${API}/${path}`, { method: "DELETE" });
      await Promise.all([renderCalendarGrid(), onChange()]);
    });
  });
}

// ---------------- Day detail modal ----------------
const dayDetailBackdrop = document.getElementById("day-detail-backdrop");
const dayDetailTitle = document.getElementById("day-detail-title");
const dayDetailBody = document.getElementById("day-detail-body");
const dayDetailClose = document.getElementById("day-detail-close");

const WEEKDAY_LONG = ["일", "월", "화", "수", "목", "금", "토"];

async function openDayDetail(dateObj) {
  const iso = toISODate(dateObj);
  dayDetailTitle.textContent = `${dateObj.getMonth() + 1}월 ${dateObj.getDate()}일 (${WEEKDAY_LONG[dateObj.getDay()]})`;
  dayDetailBody.innerHTML = `<div class="empty-state">불러오는 중...</div>`;
  dayDetailBackdrop.hidden = false;

  const res = await fetch(`${API}/schedule?start=${iso}&end=${iso}`);
  const { events, tasks } = await res.json();
  renderAgendaInto(dayDetailBody, events, tasks, async () => {
    await Promise.all([loadBriefing(), loadTasks()]);
    await openDayDetail(dateObj); // refresh the modal's own contents too
  });
}

function closeDayDetail() {
  dayDetailBackdrop.hidden = true;
}

dayDetailClose.addEventListener("click", closeDayDetail);
dayDetailBackdrop.addEventListener("click", (e) => {
  if (e.target === dayDetailBackdrop) closeDayDetail();
});

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function escapeAttr(str) {
  return escapeHtml(str).replace(/"/g, "&quot;");
}

// ---------------- Google Calendar ----------------
const googleStatusEl = document.getElementById("google-cal-status");
const googleConnectLink = document.getElementById("google-cal-connect-link");
const googleSyncBtn = document.getElementById("google-cal-sync-btn");

async function refreshGoogleStatus() {
  const res = await fetch(`${API}/google/status`);
  const { configured, connected } = await res.json();

  googleConnectLink.hidden = true;
  googleSyncBtn.hidden = true;

  if (!configured) {
    googleStatusEl.textContent = "Google 캘린더: 아직 설정 안 됨 (README 참고)";
  } else if (!connected) {
    googleStatusEl.textContent = "Google 캘린더: 연결 안 됨";
    const { url } = await fetch(`${API}/google/auth-url`).then((r) => r.json());
    googleConnectLink.href = url;
    googleConnectLink.textContent = "연결하기";
    googleConnectLink.hidden = false;
  } else {
    googleStatusEl.textContent = "Google 캘린더: 연결됨";
    googleSyncBtn.hidden = false;
  }
}

googleSyncBtn.addEventListener("click", async () => {
  googleSyncBtn.disabled = true;
  googleSyncBtn.textContent = "동기화 중...";
  try {
    const res = await fetch(`${API}/google/sync`, { method: "POST" });
    const data = await res.json();
    await refreshCalendarViews();
    googleSyncBtn.textContent = `동기화 완료 (${data.synced}건)`;
    setTimeout(() => (googleSyncBtn.textContent = "지금 동기화"), 3000);
  } catch (e) {
    googleSyncBtn.textContent = "동기화 실패";
    setTimeout(() => (googleSyncBtn.textContent = "지금 동기화"), 3000);
  } finally {
    googleSyncBtn.disabled = false;
  }
});

// ---------------- Init ----------------
checkHealth();
loadTasks();
renderCalendarGrid();
loadBriefing();
refreshGoogleStatus();
