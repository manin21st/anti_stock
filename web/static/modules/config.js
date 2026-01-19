let fullConfig = {};
let currentStrategy = null;
let activeStrategy = null; // Track the currently active strategy

// Load Config on Start
async function initConfigPage() {
    try {
        const res = await fetch('/api/lab1/config');
        fullConfig = await res.json();

        // 1. Identify Active Strategy from _meta
        if (fullConfig._meta && fullConfig._meta.active_strategy) {
            activeStrategy = fullConfig._meta.active_strategy;
        } else {
            // Fallback: First key if no meta
            const keys = Object.keys(fullConfig).filter(k => k !== '_meta');
            if (keys.length > 0) activeStrategy = keys[0];
        }

        renderStrategySelector();

        // Select active strategy by default if available
        if (activeStrategy && fullConfig[activeStrategy]) {
            selectStrategy(activeStrategy);
        } else {
            // Fallback selection
            const keys = Object.keys(fullConfig).filter(k => k !== '_meta');
            if (keys.length > 0) {
                selectStrategy(keys[0]);
            } else {
                const editorArea = document.getElementById('editor-area');
                if (editorArea) editorArea.style.display = 'none';
                currentStrategy = null;
            }
        }
    } catch (e) {
        console.error("Failed to load config", e);
        alert("설정 로드 실패: " + e);
    }
}

// Render Strategy Selector (Dropdown)
function renderStrategySelector() {
    const select = document.getElementById('strategy-select-dropdown');
    if (!select) return;

    select.innerHTML = '';

    // Filter out _meta key
    Object.keys(fullConfig).filter(k => k !== '_meta').forEach(key => {
        const option = document.createElement('option');
        option.value = key;
        // Show indicator if active
        if (key === activeStrategy) {
            option.textContent = `[실행중] ${key}`;
            option.style.fontWeight = 'bold';
            option.style.color = '#166534';
        } else {
            option.textContent = key;
        }

        if (key === currentStrategy) option.selected = true;
        select.appendChild(option);
    });

    // If list is empty
    if (select.options.length === 0) {
        const option = document.createElement('option');
        option.textContent = "(전략 없음)";
        select.appendChild(option);
        select.disabled = true;
    } else {
        select.disabled = false;
    }
}

// Select Strategy
function selectStrategy(key) {
    if (!key || !fullConfig[key]) return;

    // Check if switching to a non-active strategy
    if (activeStrategy && key !== activeStrategy) {
        if (confirm(`'${key}' 전략을 실행 전략으로 적용하시겠습니까?\n취소하면 편집 모드로만 열립니다.`)) {
            // User confirmed: Activate this strategy
            activeStrategy = key;

            // Update _meta
            if (!fullConfig._meta) fullConfig._meta = {};
            fullConfig._meta.active_strategy = activeStrategy;

            // Save immediately
            saveConfig(true);

            // Re-render dropdown to update [실행중] label
            renderStrategySelector();
            alert(`'${activeStrategy}' 전략이 실행 적용되었습니다.`);
        }
    }

    currentStrategy = key;

    // Show Editor
    const editorArea = document.getElementById('editor-area');
    if (editorArea) editorArea.style.display = 'block';

    // Sync Dropdown (in case called programmatically)
    const select = document.getElementById('strategy-select-dropdown');
    if (select && select.value !== key) {
        select.value = key;
    }

    renderVariables();
    renderConditionBlock('watch_conditions');
    renderConditionBlock('exit_conditions');
    renderConditionBlock('entry_conditions');
}

// --- Strategy Management ---

function createNewStrategy() {
    let baseName = "NewStrategy";
    let count = 1;
    // Check collision excluding _meta logic (though safe as name won't start with _)
    while (fullConfig[`${baseName}${count}`]) {
        count++;
    }
    const newName = `${baseName}${count}`;

    // Basic Template
    fullConfig[newName] = {
        variables: { ma_short: 5, ma_long: 20 },
        watch_conditions: { desc: "", code: "" },
        entry_conditions: { desc: "", code: "" },
        exit_conditions: { desc: "", code: "" }
    };

    renderStrategySelector();
    selectStrategy(newName);
}

function renameStrategyUI() {
    if (!currentStrategy) return;

    const newName = prompt("새로운 전략 이름을 입력하세요:", currentStrategy);
    if (newName) {
        renameStrategy(newName);
    }
}

function renameStrategy(newName) {
    if (!newName || newName.trim() === "") return;
    if (newName === currentStrategy) return;
    if (newName === '_meta') { alert("사용할 수 없는 이름입니다."); return; }

    if (fullConfig[newName]) {
        alert("이미 존재하는 전략 이름입니다.");
        return;
    }

    // Rename key
    fullConfig[newName] = fullConfig[currentStrategy];
    delete fullConfig[currentStrategy];

    // If renamed strategy was active, update activeStrategy
    if (currentStrategy === activeStrategy) {
        activeStrategy = newName;
        if (!fullConfig._meta) fullConfig._meta = {};
        fullConfig._meta.active_strategy = activeStrategy;
    }

    currentStrategy = newName;
    renderStrategySelector();
    selectStrategy(newName);
}

function deleteStrategy() {
    if (!currentStrategy) return;

    if (currentStrategy === activeStrategy) {
        alert("현재 실행 중인 전략은 삭제할 수 없습니다. 다른 전략을 먼저 실행 적용해주세요.");
        return;
    }

    if (confirm(`전략 '${currentStrategy}'을(를) 삭제하시겠습니까?`)) {
        delete fullConfig[currentStrategy];
        currentStrategy = null;

        const keys = Object.keys(fullConfig).filter(k => k !== '_meta');
        if (keys.length > 0) {
            // Try to select active if available, else first
            selectStrategy(activeStrategy && fullConfig[activeStrategy] ? activeStrategy : keys[0]);
        } else {
            const editorArea = document.getElementById('editor-area');
            if (editorArea) editorArea.style.display = 'none';
        }
        renderStrategySelector();
    }
}

// --- Variables ---

function renderVariables() {
    const tbody = document.getElementById('variables-body');
    if (!tbody) return;
    tbody.innerHTML = '';

    const vars = fullConfig[currentStrategy]?.variables || {};

    Object.entries(vars).forEach(([k, v]) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><input type="text" class="var-input" value="${k}" onchange="renameVariable('${k}', this.value)" style="background:transparent; border:none; border-bottom:1px solid #ddd;"></td>
            <td><input type="text" class="var-input" value="${v}" onchange="updateVariable('${k}', this.value)"></td>
            <td style="width: 40px;"><button class="delete-btn" onclick="deleteVariable('${k}')" style="position:static;"><i class="fas fa-trash-alt"></i></button></td>
        `;
        tbody.appendChild(tr);
    });

    // Add new variable row
    const addTr = document.createElement('tr');
    addTr.innerHTML = `
        <td colspan="3" style="text-align:center;">
            <button class="add-btn" onclick="addVariable()" style="width:auto; display:inline-flex; border:none; background:none; color:var(--primary-color);">
                <i class="fas fa-plus"></i> 변수 추가
            </button>
        </td>
    `;
    tbody.appendChild(addTr);
}

function updateVariable(key, val) {
    if (!fullConfig[currentStrategy]) return;

    // Auto-convert to number if possible
    if (!isNaN(val) && val.trim() !== '') {
        fullConfig[currentStrategy].variables[key] = Number(val);
    } else {
        fullConfig[currentStrategy].variables[key] = val;
    }
}

function renameVariable(oldKey, newKey) {
    if (oldKey === newKey) return;
    if (fullConfig[currentStrategy].variables[newKey]) {
        alert("이미 존재하는 변수명입니다.");
        renderVariables();
        return;
    }
    const val = fullConfig[currentStrategy].variables[oldKey];
    delete fullConfig[currentStrategy].variables[oldKey];
    fullConfig[currentStrategy].variables[newKey] = val;
    renderVariables();
}

function addVariable() {
    if (!fullConfig[currentStrategy]) return;
    const key = "new_var_" + Date.now().toString().slice(-4);
    fullConfig[currentStrategy].variables[key] = 0;
    renderVariables();
}

function deleteVariable(key) {
    if (!fullConfig[currentStrategy]) return;
    if (confirm(`변수 '${key}' 삭제?`)) {
        delete fullConfig[currentStrategy].variables[key];
        renderVariables();
    }
}

// --- Rules (Single Block) ---

function renderConditionBlock(section) {
    // section: 'watch_conditions', 'entry_conditions', 'exit_conditions'
    if (!fullConfig[currentStrategy]) return;

    const block = fullConfig[currentStrategy][section] || { desc: '', code: '', action: '' };

    // Bind to UI
    const descEl = document.getElementById(section + '_desc');
    const codeEl = document.getElementById(section + '_code');
    const actionEl = document.getElementById(section + '_action');

    if (descEl) descEl.value = block.desc || '';
    if (codeEl) codeEl.value = block.code || '';
    if (actionEl) actionEl.value = block.action || '';
}

function updateRuleBlock(section, field, val) {
    if (!fullConfig[currentStrategy]) return;

    if (!fullConfig[currentStrategy][section]) {
        fullConfig[currentStrategy][section] = {};
    }
    fullConfig[currentStrategy][section][field] = val;
}

// Tab Switching
function switchTab(section) {
    // Buttons
    document.querySelectorAll('.edit-tab-btn').forEach(btn => btn.classList.remove('active'));
    // Find button that triggered this or by logic? 
    // In this context, we can select by onclick attribute or pass 'this'
    // But simplified: just target by class if needed, or rely on event.target
    if (event && event.target) {
        event.target.classList.add('active');
    }

    // Content
    document.querySelectorAll('.edit-tab-content').forEach(content => content.classList.remove('active'));
    const content = document.getElementById(section);
    if (content) content.classList.add('active');
}

// Save Config
async function saveConfig(silent = false) {
    // Ensure _meta is up to date
    if (!fullConfig._meta) fullConfig._meta = {};
    if (activeStrategy) fullConfig._meta.active_strategy = activeStrategy;

    const btn = document.querySelector('.fab-save');
    const originalIcon = btn ? btn.innerHTML : '';

    try {
        if (btn && !silent) btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

        const res = await fetch('/api/lab1/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(fullConfig)
        });

        const data = await res.json();

        if (data.status === 'ok') {
            if (!silent) {
                // Visual Feedback
                if (btn) {
                    btn.innerHTML = '<i class="fas fa-check"></i>';
                    setTimeout(() => { btn.innerHTML = originalIcon; }, 1500);
                }
                alert("설정이 저장되었습니다.");
            } else {
                if (btn) btn.innerHTML = originalIcon;
            }
        } else {
            alert('저장 실패: ' + data.message);
            if (btn) btn.innerHTML = originalIcon;
        }
    } catch (e) {
        console.error(e);
        alert('저장 중 오류 발생');
        if (btn) btn.innerHTML = '<i class="fas fa-save"></i>';
    }
}

// Generate LLM Expression
async function generateExpression(section) {
    const descEl = document.getElementById(section + '_desc');
    if (!descEl) return;

    const desc = descEl.value;
    if (!desc || desc.trim() === '') {
        alert('먼저 조건 설명을 한글로 입력해주세요.');
        return;
    }

    const btn = document.getElementById(section + '_llm_btn');
    const originalHtml = btn ? btn.innerHTML : '';
    if (btn) {
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 생성 중...';
        btn.disabled = true;
    }

    try {
        const res = await fetch('/api/lab1/llm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: desc })
        });

        const data = await res.json();

        if (data.status === 'ok') {
            // [Upgrade] JSON (condition, action) handling
            if (data.result && typeof data.result === 'object' && (data.result.condition || data.result.action)) {
                // New Format
                if (data.result.condition) {
                    const codeEl = document.getElementById(section + '_code');
                    if (codeEl) {
                        codeEl.value = data.result.condition;
                        updateRuleBlock(section, 'code', data.result.condition);
                    }
                }

                const actionEl = document.getElementById(section + '_action');
                if (actionEl && data.result.action) {
                    actionEl.value = data.result.action;
                    updateRuleBlock(section, 'action', data.result.action);
                }
            } else if (data.result) {
                // Fallback for simple string result
                const codeEl = document.getElementById(section + '_code');
                if (codeEl) {
                    codeEl.value = data.result;
                    updateRuleBlock(section, 'code', data.result);
                }
            } else if (data.code) {
                // Legacy format fallback
                const codeEl = document.getElementById(section + '_code');
                if (codeEl) {
                    codeEl.value = data.code;
                    updateRuleBlock(section, 'code', data.code);
                }
            }
        } else {
            alert('생성 실패: ' + (data.message || '알 수 없는 오류'));
        }
    } catch (e) {
        console.error(e);
        alert('요청 중 오류 발생');
    } finally {
        if (btn) {
            btn.innerHTML = originalHtml;
            btn.disabled = false;
        }
    }
}

// Toggle Section
function toggleSection(id) {
    const card = document.getElementById(id);
    if (card) {
        card.classList.toggle('collapsed');
    }
}

// Init - Only run if we are on the config page
document.addEventListener('DOMContentLoaded', () => {
    // Check if we have the strategy container or dropdown
    if (document.getElementById('strategy-select-dropdown')) {
        initConfigPage();
    }
});
