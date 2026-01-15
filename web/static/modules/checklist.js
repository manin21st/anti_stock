// Checklist Logic
let checklistVisible = false;

function toggleChecklist() {
    checklistVisible = !checklistVisible;
    const popup = document.getElementById('checklist-popup');
    if (popup) {
        popup.style.display = checklistVisible ? 'flex' : 'none';
        if (checklistVisible) {
            loadChecklist();
        }
    }
}

async function loadChecklist() {
    try {
        const res = await fetch('/api/checklist');
        const data = await res.json();
        if (data.status === 'ok') {
            renderChecklist(data.data);
        }
    } catch (e) {
        console.error("Failed to load checklist", e);
    }
}

function renderChecklist(items) {
    const list = document.getElementById('checklist-items');
    list.innerHTML = items.map(item => `
        <li class="checklist-item ${item.is_done ? 'done' : ''}" data-id="${item.id}">
            <input type="checkbox" ${item.is_done ? 'checked' : ''} onchange="toggleChecklistItem(${item.id}, this.checked)">
            <span>${item.text}</span>
            <button class="delete-btn" onclick="deleteChecklistItem(${item.id})">삭제</button>
        </li>
    `).join('');
}

async function addChecklistItem() {
    const input = document.getElementById('checklist-input');
    const text = input.value.trim();
    if (!text) return;

    try {
        const res = await fetch('/api/checklist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            input.value = '';
            loadChecklist();
        }
    } catch (e) {
        console.error("Failed to add item", e);
    }
}

function handleChecklistInput(e) {
    if (e.key === 'Enter') addChecklistItem();
}

async function toggleChecklistItem(id, isDone) {
    try {
        const res = await fetch('/api/checklist/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: id, is_done: isDone ? 1 : 0 })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            loadChecklist();
        }
    } catch (e) {
        console.error("Failed to update item", e);
    }
}

async function deleteChecklistItem(id) {
    if (!confirm('삭제하시겠습니까?')) return;
    try {
        const res = await fetch(`/api/checklist/${id}`, { method: 'DELETE' });
        const data = await res.json();
        if (data.status === 'ok') {
            loadChecklist();
        }
    } catch (e) {
        console.error("Failed to delete item", e);
    }
}

function initChecklist() {
    const popup = document.getElementById('checklist-popup');
    const header = document.getElementById('checklist-header');

    if (!popup || !header) return;

    let isDragging = false;
    let currentX;
    let currentY;
    let initialX;
    let initialY;
    let xOffset = 0;
    let yOffset = 0;

    header.addEventListener("mousedown", dragStart);
    document.addEventListener("mouseup", dragEnd);
    document.addEventListener("mousemove", drag);

    function dragStart(e) {
        initialX = e.clientX - xOffset;
        initialY = e.clientY - yOffset;

        if (e.target === header || e.target.parentNode === header) {
            isDragging = true;
        }
    }

    function dragEnd(e) {
        initialX = currentX;
        initialY = currentY;
        isDragging = false;
    }

    function drag(e) {
        if (isDragging) {
            e.preventDefault();
            currentX = e.clientX - initialX;
            currentY = e.clientY - initialY;

            xOffset = currentX;
            yOffset = currentY;

            setTranslate(currentX, currentY, popup);
        }
    }

    function setTranslate(xPos, yPos, el) {
        el.style.transform = `translate3d(${xPos}px, ${yPos}px, 0)`;
    }
}
