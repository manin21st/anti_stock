const API_BASE = "/api";
let userSellQty = {}; // Store manual input values to survive poll re-renders: { symbol: value }

// Utils
const formatCurrency = (val) => new Intl.NumberFormat('ko-KR', { style: 'currency', currency: 'KRW' }).format(val);

// Strategy Name Mapping
const strategyNames = {
    "common": "공통 설정",
    "ma_trend": "이동평균 추세 추종",
    "bollinger_mr": "볼린저 밴드 평균 회귀",
    "breakout": "전고점 돌파",
    "vwap_scalping": "VWAP 스캘핑"
};

// Tabs Logic
function initTabs() {
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            // Remove active class from all
            tabBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));

            // Add active class to clicked
            btn.classList.add('active');
            const tabId = btn.getAttribute('data-tab');
            document.getElementById(tabId).classList.add('active');
        });
    });
}

// Status & Portfolio
async function updateStatus() {
    try {
        const res = await fetch(`${API_BASE}/status`);
        const data = await res.json();

        const statusEl = document.getElementById("status-indicator");
        const btnStart = document.getElementById("btn-start");
        const btnStop = document.getElementById("btn-stop");
        const btnRestart = document.getElementById("btn-restart");

        if (data.is_running) {
            if (data.active_strategies && data.active_strategies.length > 0) {
                statusEl.textContent = "실행 중";
                statusEl.className = "status-running";
                statusEl.style.backgroundColor = ""; // Reset inline style from standby
            } else {
                statusEl.textContent = "대기 중 (전략 없음)";
                statusEl.className = "status-stopped"; // Use stopped style or a new standby style
                statusEl.style.backgroundColor = "#f59e0b"; // Orange/Yellow for standby
            }

            if (btnStart) {
                btnStart.textContent = "재시작"; // Running -> Restart
                btnStart.classList.add("btn-success");
                btnStart.classList.remove("btn-primary");
                btnStart.disabled = false;
            }
            if (btnStop) btnStop.disabled = false;
        } else {
            statusEl.textContent = "중지됨";
            statusEl.className = "status-stopped";
            statusEl.style.backgroundColor = ""; // Reset style

            if (btnStart) {
                btnStart.textContent = "시작"; // Stopped -> Start
                btnStart.classList.add("btn-primary");
                btnStart.classList.remove("btn-success");
                btnStart.disabled = false;
            }
            if (btnStop) btnStop.disabled = true;
        }

        // Active Strategy Display
        const activeStrategyEl = document.getElementById("active-strategy");
        if (data.active_strategies && data.active_strategies.length > 0) {
            const names = data.active_strategies.map(id => strategyNames[id] || id).join(", ");
            activeStrategyEl.textContent = `전략: ${names}`;
        } else {
            activeStrategyEl.textContent = "전략: 없음";
        }

        if (data.portfolio) {
            document.getElementById("total-asset").textContent = formatCurrency(data.portfolio.total_asset);
            if (document.getElementById("stock-eval")) {
                document.getElementById("stock-eval").textContent = formatCurrency(data.portfolio.total_eval_amt || 0);
            }
            document.getElementById("cash").textContent = formatCurrency(data.portfolio.cash);

            // New Deposit Metrics
            if (document.getElementById("deposit-d1")) {
                document.getElementById("deposit-d1").textContent = formatCurrency(data.portfolio.deposit_d1 || 0);
            }
            if (document.getElementById("deposit-d2")) {
                document.getElementById("deposit-d2").textContent = formatCurrency(data.portfolio.deposit_d2 || 0);
            }

            const tbody = document.querySelector("#positions-table tbody");
            tbody.innerHTML = "";

            if (data.portfolio.positions && data.portfolio.positions.length > 0) {
                data.portfolio.positions.forEach(pos => {
                    // Calculate derived metrics
                    const investedAmt = pos.qty * pos.avg_price;
                    const evalAmt = pos.qty * pos.current_price;
                    const pnl = evalAmt - investedAmt;
                    const pnlClass = pnl >= 0 ? 'pnl-positive' : 'pnl-negative'; // Red for profit, Blue for loss (KR style)

                    // Decide input value: either user's current input or current held qty
                    if (userSellQty[pos.symbol] === undefined) {
                        userSellQty[pos.symbol] = pos.qty;
                    }

                    const tr = document.createElement("tr");
                    tr.innerHTML = `
                        <td style="text-align: left;">${pos.name || pos.symbol}</td>
                        <td style="text-align: center; color: var(--text-secondary); font-size: 0.9em;">${pos.symbol}</td>
                        <td style="text-align: right; font-weight: 600;">${pos.qty}</td>
                        <td>
                            <div style="display: flex; align-items: center; justify-content: center; gap: 6px;">
                                <input type="number" id="sell-qty-${pos.symbol}" value="${userSellQty[pos.symbol]}" min="1" max="${pos.qty}" 
                                       oninput="userSellQty['${pos.symbol}'] = this.value"
                                       style="width: 65px; height: 28px; padding: 0 5px; border-radius: 4px; border: 1px solid #ccc; background: #fff; color: #000; font-size: 14px; font-weight: 500; text-align: center;">
                                <button onclick="sellImmediate('${pos.symbol}', event)" class="btn-danger" 
                                        style="padding: 4px 8px; font-size: 13px; font-weight: 500; border-radius: 4px; height: 28px; line-height: 1;">매도</button>
                            </div>
                        </td>
                        <td style="text-align: right;">${formatCurrency(pos.avg_price)}</td>
                        <td style="text-align: right; color: var(--text-secondary);">${formatCurrency(investedAmt)}</td>
                        <td style="text-align: right; font-weight: 500;">${formatCurrency(pos.current_price)}</td>
                        <td style="text-align: right; font-weight: 500;">${formatCurrency(evalAmt)}</td>
                        <td style="text-align: right;" class="${pnlClass}">${formatCurrency(pnl)}</td>
                        <td style="text-align: center;" class="${pnlClass}">${pos.pnl_pct.toFixed(2)}%</td>
                        <td style="text-align: right;">${pos.holding_days}일</td>
                    `;
                    tbody.appendChild(tr);
                });
            } else {
                const tr = document.createElement("tr");
                tr.innerHTML = `<td colspan="9" style="text-align: center; color: var(--text-secondary);">보유 종목이 없습니다.</td>`;
                tbody.appendChild(tr);
            }
        }
    } catch (e) {
        console.error("Failed to fetch status", e);
    }
}

// Config
let currentConfig = {};

async function loadConfig() {
    const res = await fetch(`${API_BASE}/config`);
    currentConfig = await res.json();

    const strategySelect = document.getElementById("strategy-select");

    // Populate Strategy Selector if empty
    if (strategySelect.options.length === 1) {
        let keys = [];
        if (currentConfig.strategies_list) {
            keys = currentConfig.strategies_list;
        } else {
            // Fallback for older backend
            keys = Object.keys(currentConfig).filter(key =>
                key !== "system" &&
                key !== "database" &&
                key !== "active_strategy" &&
                key !== "strategies_list" &&
                typeof currentConfig[key] === 'object'
            );
        }

        // Sort: common first, then others
        keys.sort((a, b) => {
            if (a === "common") return -1;
            if (b === "common") return 1;
            return a.localeCompare(b);
        });

        keys.forEach(key => {
            const option = document.createElement("option");
            option.value = key;
            option.textContent = strategyNames[key] || key;
            strategySelect.appendChild(option);
        });
    }

    // Handle Selection Change
    strategySelect.onchange = () => {
        const selectedStrategy = strategySelect.value;
        renderConfigForm(selectedStrategy);
    };

    // Initial render if a strategy is already selected or active
    if (currentConfig.active_strategy) {
        strategySelect.value = currentConfig.active_strategy;
        renderConfigForm(currentConfig.active_strategy);
    } else if (strategySelect.value) {
        renderConfigForm(strategySelect.value);
    }
}

function renderConfigForm(strategyKey) {
    const form = document.getElementById("config-form");
    form.innerHTML = "";

    if (!strategyKey || !currentConfig[strategyKey]) return;

    const strategyConfig = currentConfig[strategyKey];

    for (const [key, value] of Object.entries(strategyConfig)) {
        if (key === 'enabled') continue; // Skip enabled
        if (key === 'id') continue; // Skip id

        const div = document.createElement("div");
        div.className = "config-field";
        div.innerHTML = `
            <label>${key}</label>
            <input type="text" name="${strategyKey}.${key}" value="${value}" 
                   onblur="saveStrategyConfigField(this)" onchange="saveStrategyConfigField(this)">
        `;
        form.appendChild(div);
    }
}

// Strategy Auto-Save Helper
async function saveStrategyConfigField(input) {
    const strategyName = document.getElementById("strategy-select").value;
    if (!strategyName) return;

    const parts = input.name.split(".");
    if (parts.length !== 2) return;

    const key = parts[1];
    let val = isNaN(Number(input.value)) ? input.value : Number(input.value);

    // Patch save - we retrieve current config to make sure we don't overwrite with partial data
    // actually API accepts partial update via merge, but let's stick to full object update if needed
    // The existing API /config merges the input. So we can send just { strategy: { key: value } }

    // Construct the payload as expected by the backend logic in server.py
    // The server expects "StrategyName": { ...config... } or "active_strategy": ...
    // Let's create a fragment
    const fragment = {};
    fragment[strategyName] = {};
    fragment[strategyName][key] = val;

    try {
        await fetch(`${API_BASE}/config`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(fragment)
        });

        // Update local state to reflect change immediately
        if (currentConfig && currentConfig[strategyName]) {
            currentConfig[strategyName][key] = val;
        }

        console.log(`Auto-saved strategy config: ${key}=${val}`);
    } catch (e) {
        console.error("Auto-save failed:", e);
    }
}

// System Config & Control
let saveTimeout;
function autoSaveSystem() {
    clearTimeout(saveTimeout);
    saveTimeout = setTimeout(saveSystemConfig, 500);
}

async function loadSystemConfig() {
    // Load Settings
    const res = await fetch(`${API_BASE}/system/settings`);
    const config = await res.json();

    // Set Radio Buttons
    if (config.env_type) {
        const el = document.querySelector(`input[name="env_type"][value="${config.env_type}"]`);
        if (el) el.checked = true;
    }
    if (config.market_type) {
        const el = document.querySelector(`input[name="market_type"][value="${config.market_type}"]`);
        if (el) el.checked = true;
    }

    // Auto Scanner & Universe
    const autoScannerCheckbox = document.getElementById("use_auto_scanner");
    const scannerModeGroup = document.getElementById("scanner-mode-group");
    const universeGroup = document.getElementById("universe-group");
    const universeInput = document.getElementById("universe-input");

    if (config.use_auto_scanner !== undefined) {
        autoScannerCheckbox.checked = config.use_auto_scanner;
    }

    if (config.scanner_mode) {
        const el = document.querySelector(`input[name="scanner_mode"][value="${config.scanner_mode}"]`);
        if (el) el.checked = true;
    }

    if (universeInput && config.universe && Array.isArray(config.universe)) {
        universeInput.value = config.universe.join(", ");
    }

    // Telegram Alerts
    if (config.telegram) {
        if (config.telegram.enable_trade_alert !== undefined) {
            document.getElementById("enable_trade_alert").checked = config.telegram.enable_trade_alert;
        }
        if (config.telegram.enable_system_alert !== undefined) {
            document.getElementById("enable_system_alert").checked = config.telegram.enable_system_alert;
        }
    }

    // Toggle Visibility
    const toggleScannerUI = () => {
        if (autoScannerCheckbox.checked) {
            scannerModeGroup.style.display = "block";
            if (universeGroup) universeGroup.style.opacity = "0.5";
            if (universeInput) universeInput.disabled = true;
        } else {
            scannerModeGroup.style.display = "none";
            if (universeGroup) universeGroup.style.opacity = "1";
            if (universeInput) universeInput.disabled = false;
        }
    };

    autoScannerCheckbox.addEventListener("change", toggleScannerUI);
    toggleScannerUI(); // Initial state

    // ... (omitted lines) ...


    // Text Inputs: Blur triggers save
    if (universeInput) {
        universeInput.addEventListener("blur", autoSaveSystem);
    }


    document.getElementById("enable_trade_alert").addEventListener("change", autoSaveSystem);
    document.getElementById("enable_system_alert").addEventListener("change", autoSaveSystem);
}

// ... (omitted) ...

async function saveSystemConfig() {
    const env_type = document.querySelector('input[name="env_type"]:checked').value;
    const market_type = document.querySelector('input[name="market_type"]:checked').value;

    const use_auto_scanner = document.getElementById("use_auto_scanner").checked;
    const scanner_mode = document.querySelector('input[name="scanner_mode"]:checked').value;

    let universe = [];
    const universeInput = document.getElementById("universe-input");
    if (universeInput) {
        const universeStr = universeInput.value;
        universe = universeStr.split(",").map(s => s.trim()).filter(s => s.length > 0);
    }

    const enable_trade_alert = document.getElementById("enable_trade_alert").checked;
    const enable_system_alert = document.getElementById("enable_system_alert").checked;


    await fetch(`${API_BASE}/system_config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            env_type,
            market_type,
            use_auto_scanner,
            scanner_mode,
            universe,
            telegram: {
                enable_trade_alert,
                enable_system_alert
            }
        })
    });
}

// Event Listeners
// Helper to save everything before start/restart
async function saveAllAndGetReady() {
    // 1. Save System Config
    await saveSystemConfig();

    // 2. Save Current Strategy Config just in case (though auto-saved)
    const strategySelect = document.getElementById("strategy-select");
    const selectedStrategy = strategySelect.value;
    if (selectedStrategy) {
        // Collect current form values
        const form = document.getElementById("config-form");
        const inputs = form.querySelectorAll("input");
        const fragment = {};
        fragment[selectedStrategy] = {};

        // Also set active strategy
        fragment["active_strategy"] = selectedStrategy;

        inputs.forEach(input => {
            const parts = input.name.split(".");
            if (parts.length === 2 && parts[0] === selectedStrategy) {
                let val = isNaN(Number(input.value)) ? input.value : Number(input.value);
                fragment[selectedStrategy][parts[1]] = val;
            }
        });

        await fetch(`${API_BASE}/config`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(fragment)
        });
    }
}

async function sendControl(command) {
    await fetch(`${API_BASE}/control`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: command })
    });
    setTimeout(updateStatus, 1000); // Wait a bit then update status
}

document.getElementById("btn-start").onclick = async () => {
    const btn = document.getElementById("btn-start");
    const originalText = btn.textContent; // "시작" or "재시작"
    const isRestart = originalText === "재시작";

    try {
        console.log(`${originalText} button clicked`);
        btn.disabled = true;
        btn.textContent = "저장 중...";

        // Force Save All
        await saveAllAndGetReady();

        if (isRestart) {
            btn.textContent = "재시작"; // Restore text for confirm
            if (confirm("시스템을 재시작하시겠습니까?")) {
                btn.textContent = "요청 중...";
                await sendControl("restart");
                alert("재시작 요청을 보냈습니다. (잠시 후 수치가 갱신됩니다)");
            } else {
                // Cancelled
                btn.disabled = false;
            }
        } else {
            btn.textContent = "시작 요청 중...";
            await sendControl("start");
            // Status update will re-enable button
        }
    } catch (e) {
        console.error("Start/Restart Error:", e);
        alert(`오류가 발생했습니다: ${e.message}`);
        btn.textContent = originalText;
        btn.disabled = false;
    }
};

document.getElementById("btn-stop").onclick = () => {
    console.log("Stop button clicked");
    sendControl("stop");
};
// Removed btn-restart listener as the button is gone

// Logs WebSocket
const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
const ws = new WebSocket(`${protocol}//${location.host}/ws/logs`);
ws.onmessage = (event) => {
    const logViewer = document.getElementById("log-viewer");
    const div = document.createElement("div");
    div.className = "log-entry";
    div.textContent = event.data;
    logViewer.appendChild(div);
    logViewer.scrollTop = logViewer.scrollHeight;
};

// Init
console.log("App.js initializing...");
(async () => {
    initTabs(); // Initialize Tabs

    try {
        console.log("Loading config...");
        await loadConfig();
    } catch (e) {
        console.error("Error loading config:", e);
    }

    try {
        console.log("Loading system config...");
        await loadSystemConfig();
    } catch (e) {
        console.error("Error loading system config:", e);
    }

    try {
        console.log("Initializing backtest...");
        initBacktest();
    } catch (e) {
        console.error("Error initializing backtest:", e);
    }

    try {
        console.log("Initializing journal...");
        initJournal();
    } catch (e) {
        console.error("Error initializing journal:", e);
    }

    try {
        console.log("Initializing checklist...");
        initChecklist();
    } catch (e) {
        console.error("Error initializing checklist:", e);
    }

    try {
        console.log("Updating status...");
        await updateStatus();
    } catch (e) {
        console.error("Error updating status:", e);
    }

    setInterval(updateStatus, 2000);
    console.log("Init complete. Polling started.");
})();

// Backtest Logic
function initBacktest() {
    const btnCheck = document.getElementById("btn-check-data");
    const btnRun = document.getElementById("btn-run-backtest");
    const btnViewChart = document.getElementById("btn-view-chart");
    const statusDiv = document.getElementById("bt-status"); // Changed ID in HTML
    const strategySelect = document.getElementById("bt-strategy-select");

    // Load Stock Master List for Autocomplete
    loadStockMasterList();

    // Populate Strategy Select
    Object.keys(strategyNames).forEach(key => {
        if (key === "common" || key === "system") return;
        const opt = document.createElement("option");
        opt.value = key;
        opt.textContent = strategyNames[key];
        strategySelect.appendChild(opt);
    });

    // Default dates
    const today = new Date();
    const oneMonthAgo = new Date();
    oneMonthAgo.setMonth(today.getMonth() - 1);

    const pad = (n) => n.toString().padStart(2, '0');
    const toYMD = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

    if (document.getElementById("bt-end-date")) {
        document.getElementById("bt-end-date").value = toYMD(today);
        document.getElementById("bt-start-date").value = toYMD(oneMonthAgo);
    }

    // Check Data Button
    if (btnCheck) {
        btnCheck.addEventListener("click", async () => {
            const symbol = document.getElementById("bt-symbol").value;
            const startStr = document.getElementById("bt-start-date").value.replace(/-/g, "");
            const endStr = document.getElementById("bt-end-date").value.replace(/-/g, "");

            updateStatusText("데이터 확인 중...", "#aaa");

            try {
                // 1. Check existence
                const strategy_id = document.getElementById("bt-strategy-select").value;
                const resCheck = await fetch(`${API_BASE}/backtest/check_data`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ symbol, start: startStr, end: endStr, strategy_id })
                });
                const dataCheck = await resCheck.json();

                if (!dataCheck.exists) {
                    updateStatusText("데이터 다운로드 중...", "#f59e0b");
                    // strategy_id already declared
                    const resDown = await fetch(`${API_BASE}/backtest/download`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ symbol, start: startStr, end: endStr, strategy_id })
                    });
                    const dataDown = await resDown.json();
                    if (dataDown.status !== "ok") {
                        throw new Error(dataDown.message);
                    }
                }

                // 2. Fetch Data for Table
                updateStatusText("데이터 로딩 중...", "#3b82f6");
                // strategy_id already declared
                const resData = await fetch(`${API_BASE}/backtest/data`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ symbol, start: startStr, end: endStr, strategy_id })
                });
                const jsonData = await resData.json();

                if (jsonData.status === "ok") {
                    renderDataTable(jsonData.data, strategy_id);
                    updateStatusText("데이터 준비 완료", "#10b981");
                    btnRun.disabled = false;
                } else {
                    throw new Error(jsonData.message);
                }

            } catch (e) {
                updateStatusText(`오류: ${e.message}`, "#ef4444");
                console.error(e);
            }
        });
    }

    // Run Backtest Button (WebSocket)
    if (btnRun) {
        btnRun.addEventListener("click", (e) => {
            e.preventDefault();
            runBacktestWebSocket();
        });
    }

    // Excel Download Button
    const btnExcel = document.getElementById("btn-download-excel");
    if (btnExcel) {
        btnExcel.addEventListener("click", async (e) => {
            e.preventDefault(); // Prevent default link behavior
            const symbol = document.getElementById("bt-symbol").value;
            const start = document.getElementById("bt-start-date").value.replace(/-/g, "");
            const end = document.getElementById("bt-end-date").value.replace(/-/g, "");
            const strategy_id = document.getElementById("bt-strategy-select").value;
            const initial_cash = document.getElementById("bt-initial-cash").value;

            if (confirm("엑셀 다운로드를 시작하시겠습니까? (백테스트가 재실행되므로 시간이 걸릴 수 있습니다.)")) {
                updateStatusText("엑셀 생성 중...", "#f59e0b");
                try {
                    const response = await fetch(`${API_BASE}/backtest/export`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ symbol, start, end, strategy_id, initial_cash })
                    });

                    if (response.ok) {
                        const blob = await response.blob();
                        const url = window.URL.createObjectURL(blob);
                        const a = document.createElement("a");
                        a.href = url;
                        // Content-Disposition header handles filename usually, but we can try to guess or use what server sent
                        // Using a generic name or extracting from header requires parsing
                        const header = response.headers.get('Content-Disposition');
                        let filename = `backtest_${symbol}_${strategy_id}.xlsx`;
                        if (header && header.indexOf('filename=') !== -1) {
                            // Simple parse
                            const parts = header.split('filename=');
                            let f = parts[1].replace(/"/g, '');
                            if (f) filename = f;
                        }

                        a.download = filename;
                        document.body.appendChild(a);
                        a.click();
                        a.remove();
                        window.URL.revokeObjectURL(url);
                        updateStatusText("다운로드 완료", "#10b981");
                    } else {
                        const err = await response.json();
                        throw new Error(err.message || "Download failed");
                    }
                } catch (e) {
                    console.error("Download Error", e);
                    updateStatusText(`다운로드 실패: ${e.message}`, "#ef4444");
                    alert("다운로드 중 오류가 발생했습니다.");
                }
            }
        });
    }

    function updateStatusText(text, color) {
        if (statusDiv) {
            statusDiv.textContent = text;
            statusDiv.style.color = color || "inherit";
        }
    }

    async function loadStockMasterList() {
        try {
            const res = await fetch(`${API_BASE}/stocks`);
            const stocks = await res.json();
            // stocks: [{code, name}, ...]

            // Init Autocomplete for Backtest
            setupAutocomplete("bt-symbol", "bt-symbol-list", stocks);

            // Init Autocomplete for Journal
            setupAutocomplete("journal-symbol", "journal-symbol-list", stocks);

            console.log(`Loaded ${stocks.length} stocks for search.`);
        } catch (e) {
            console.error("Failed to load stock list:", e);
        }
    }

    function setupAutocomplete(inpId, listId, stockData) {
        const inp = document.getElementById(inpId);
        const listDiv = document.getElementById(listId);

        if (!inp || !listDiv) return;

        let currentFocus = -1;

        inp.addEventListener("input", function (e) {
            const val = this.value;
            closeAllLists();
            if (!val) return false;

            currentFocus = -1;
            listDiv.style.display = "block";

            let count = 0;
            const maxItems = 50;

            for (let i = 0; i < stockData.length; i++) {
                if (count >= maxItems) break;

                const code = stockData[i].code;
                const name = stockData[i].name;

                if (code.includes(val) || name.toUpperCase().includes(val.toUpperCase())) {
                    const item = document.createElement("div");
                    item.innerHTML = `<strong>${name}</strong> <span style='font-size:0.9em; color:#888;'>(${code})</span>`;
                    item.innerHTML += `<input type='hidden' value='${code}'>`;

                    item.addEventListener("click", function (e) {
                        inp.value = this.getElementsByTagName("input")[0].value;
                        closeAllLists();
                    });
                    listDiv.appendChild(item);
                    count++;
                }
            }

            if (count === 0) {
                const empty = document.createElement("div");
                empty.textContent = "검색 결과 없음";
                empty.style.color = "#aaa";
                empty.style.padding = "10px";
                listDiv.appendChild(empty);
            }
        });

        inp.addEventListener("keydown", function (e) {
            let x = listDiv.getElementsByTagName("div");
            if (e.keyCode == 40) { // Down
                currentFocus++;
                addActive(x);
            } else if (e.keyCode == 38) { // Up
                currentFocus--;
                addActive(x);
            } else if (e.keyCode == 13) { // Enter
                e.preventDefault();
                if (currentFocus > -1) {
                    if (x) x[currentFocus].click();
                } else {
                    closeAllLists();
                }
            }
        });

        function addActive(x) {
            if (!x) return false;
            removeActive(x);
            if (currentFocus >= x.length) currentFocus = 0;
            if (currentFocus < 0) currentFocus = (x.length - 1);
            x[currentFocus].classList.add("autocomplete-active");
            x[currentFocus].scrollIntoView({ block: "nearest" });
        }

        function removeActive(x) {
            for (let i = 0; i < x.length; i++) {
                x[i].classList.remove("autocomplete-active");
            }
        }

        function closeAllLists(elmnt) {
            listDiv.innerHTML = "";
            listDiv.style.display = "none";
        }

        document.addEventListener("click", function (e) {
            if (e.target !== inp) {
                closeAllLists();
            }
        });
    }
}

function renderDataTable(data, strategyId) {
    const tbody = document.querySelector("#bt-trade-table tbody");
    tbody.innerHTML = "";

    // Toggle MA Trend Column
    const maTrendCols = document.querySelectorAll(".col-ma-trend");
    if (strategyId === 'ma_trend') {
        maTrendCols.forEach(el => el.style.display = "");
    } else {
        maTrendCols.forEach(el => el.style.display = "none");
    }

    data.forEach(row => {
        const tr = document.createElement("tr");
        // Unique Key for Intraday
        const uniqueKey = row.time ? `${row.date} ${row.time}` : row.date;
        tr.setAttribute("data-date", uniqueKey);

        // Format numbers
        const close = Number(row.close).toLocaleString();
        const ma5 = row.ma5 ? Math.round(row.ma5).toLocaleString() : "-";
        const ma20 = row.ma20 ? Math.round(row.ma20).toLocaleString() : "-";
        const vol = Number(row.volume).toLocaleString();

        // MA Trend Specific
        let maTrendCell = "";
        if (strategyId === 'ma_trend') {
            const vma20 = row.vol_ma20 ? Math.round(row.vol_ma20).toLocaleString() : "-";
            maTrendCell = `<td class="text-right">${vma20}</td>`;
        }

        tr.innerHTML = `
            <td>${uniqueKey}</td>
            <td class="text-right">${close}</td>
            <td class="text-right">${ma5}</td>
            <td class="text-right">${ma20}</td>
            <td class="text-right">${vol}</td>
            ${maTrendCell}
            <!-- Trade Columns (Empty initially) -->
            <td class="border-left type-cell"></td>
            <td class="text-right qty-cell"></td>
            <td class="text-right price-cell"></td>
        `;
        tbody.appendChild(tr);
    });
}

function runBacktestWebSocket() {
    const btnRun = document.getElementById("btn-run-backtest");
    const progressBar = document.getElementById("bt-progress-bar");
    const progressText = document.getElementById("bt-progress-text");
    const statusDiv = document.getElementById("bt-status");

    btnRun.disabled = true;
    if (statusDiv) statusDiv.textContent = "백테스트 실행 중...";

    // Reset Metrics
    // Reset Metrics
    updateRealtimeMetrics({
        qty: 0, avg_price: 0, buy_amt: 0, eval_amt: 0, eval_pnl: 0, return_rate: 0, trade_count: 0
    });

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${location.host}/ws/backtest`);

    ws.onopen = () => {
        console.log("Backtest WS Connected");
        // Send Config
        const symbol = document.getElementById("bt-symbol").value;
        const start = document.getElementById("bt-start-date").value.replace(/-/g, "");
        const end = document.getElementById("bt-end-date").value.replace(/-/g, "");
        const strategy_id = document.getElementById("bt-strategy-select").value;
        const initial_cash = document.getElementById("bt-initial-cash").value;

        ws.send(JSON.stringify({
            strategy_id, symbol, start, end, initial_cash
        }));
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);

        if (msg.type === "progress") {
            const payload = msg.data;
            // Payload is dict { percent, qty, avg_price, ... }
            if (progressBar) progressBar.style.width = `${payload.percent}%`;
            if (progressText) progressText.textContent = `${payload.percent}%`;

            // Update Real-time Metrics
            updateRealtimeMetrics(payload);
        }
        else if (msg.type === "trade_event") {
            updateTableRow(msg.data);
        }
        else if (msg.type === "result") {
            // Finalize
            if (progressBar) progressBar.style.width = "100%";
            if (progressText) progressText.textContent = "100%";
            renderMetrics(msg.result.metrics);
            if (statusDiv) statusDiv.textContent = "완료";
            btnRun.disabled = false;
            ws.close();
        }
        else if (msg.type === "error") {
            alert(`오류: ${msg.message}`);
            if (statusDiv) statusDiv.textContent = "오류 발생";
            btnRun.disabled = false;
            ws.close();
        }
    };

    ws.onerror = (e) => {
        console.error("WS Error", e);
        if (statusDiv) statusDiv.textContent = "통신 오류";
        btnRun.disabled = false;
    };
}

function updateTableRow(trade) {
    // trade.timestamp is "YYYYMMDD HHMMSS" or "YYYYMMDD "
    // Match with data-date
    const dateKey = trade.timestamp.trim();

    // Find row
    const tr = document.querySelector(`tr[data-date="${dateKey}"]`);
    if (tr) {
        // Update cells
        const typeCell = tr.querySelector('.type-cell');
        const qtyCell = tr.querySelector('.qty-cell');
        const priceCell = tr.querySelector('.price-cell');

        typeCell.textContent = trade.side;
        typeCell.className = `border-left type-cell ${trade.side === "BUY" ? "trade-buy" : "trade-sell"}`;

        qtyCell.textContent = trade.qty;
        priceCell.textContent = Math.round(trade.price).toLocaleString();

        // Highlights (Text Color)
        if (trade.side === "BUY") {
            tr.classList.add("row-buy");
        } else {
            tr.classList.add("row-sell");
        }

        // Auto Scroll
        tr.scrollIntoView({ behavior: "smooth", block: "center" });
    }
}

function updateRealtimeMetrics(d) {
    const setVal = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    };

    setVal("bt-qty", d.qty);
    setVal("bt-avg", Math.round(d.avg_price).toLocaleString());
    setVal("bt-buy-amt", Math.round(d.buy_amt).toLocaleString());
    setVal("bt-eval-amt", Math.round(d.eval_amt).toLocaleString());
    setVal("bt-eval-pnl", Math.round(d.eval_pnl).toLocaleString());

    // PnL Color
    const pnlEl = document.getElementById("bt-eval-pnl");
    if (pnlEl) {
        pnlEl.className = "value " + (d.eval_pnl > 0 ? "pnl-positive" : (d.eval_pnl < 0 ? "pnl-negative" : ""));
    }

    // Return Rate
    const rateEl = document.getElementById("bt-return-rate");
    if (rateEl) {
        rateEl.textContent = `${d.return_rate.toFixed(2)}%`;
        rateEl.className = "value " + (d.return_rate >= 0 ? "pnl-positive" : "pnl-negative");
    }

    setVal("bt-trade-count", d.trade_count);
}
// Removed renderMetrics as we use updateRealtimeMetrics
function renderMetrics(m) {
    // Final update with result metrics if needed?
    // Usually progress callback sends the last state anyway.
    // result.metrics has total_return, etc.
    // We can just rely on the last progress update.
}

// ==========================================
// Trading Journal Logic
// ==========================================
function initJournal() {
    const btnSearch = document.getElementById("btn-journal-search");
    const btnSync = document.getElementById("btn-journal-sync");

    // Default Dates (This month)
    const today = new Date();
    const firstDay = new Date(today.getFullYear(), today.getMonth(), 1);

    const pad = (n) => n.toString().padStart(2, '0');
    const toYMD = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

    if (document.getElementById("journal-start")) {
        document.getElementById("journal-start").value = toYMD(firstDay);
        document.getElementById("journal-end").value = toYMD(today);
    }

    // Search Button
    if (btnSearch) {
        btnSearch.addEventListener("click", () => {
            loadJournalData();
        });
    }

    // Sync Button
    if (btnSync) {
        btnSync.addEventListener("click", async () => {
            if (confirm("증권사 서버와 동기화를 진행하시겠습니까? (누락된 체결 내역 확인)")) {
                await syncJournal();
            }
        });
    }

    // Load initial data if tab is active? Or just wait for user?
    // Let's load active month by default
    // loadJournalData(); 
}

async function loadJournalData() {
    const start = document.getElementById("journal-start").value.replace(/-/g, "");
    const end = document.getElementById("journal-end").value.replace(/-/g, "");
    const symbol = document.getElementById("journal-symbol").value;

    const tbody = document.getElementById("journal-list");
    tbody.innerHTML = '<tr><td colspan="9" style="text-align: center;">로딩 중...</td></tr>';

    const qs = new URLSearchParams({ start, end, symbol }).toString();

    try {
        const res = await fetch(`${API_BASE}/journal/trades?${qs}`);
        const json = await res.json();

        if (json.status === "ok") {
            renderJournalTable(json.data);
            updateJournalSummary(json.data);
        } else {
            tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: red;">오류: ${json.message}</td></tr>`;
        }
    } catch (e) {
        console.error(e);
        tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: red;">통신 오류</td></tr>`;
    }
}

async function syncJournal() {
    const start = document.getElementById("journal-start").value.replace(/-/g, "");
    const end = document.getElementById("journal-end").value.replace(/-/g, "");
    const btnSync = document.getElementById("btn-journal-sync");

    const originalText = btnSync.innerHTML;
    btnSync.disabled = true;
    btnSync.innerHTML = "동기화 중...";

    try {
        const res = await fetch(`${API_BASE}/journal/sync`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ start, end }) // Sync currently uses date range
        });
        const json = await res.json();

        if (json.status === "ok") {
            alert(`동기화 완료: ${json.count}건 추가됨`);
            loadJournalData(); // Reload table
        } else {
            alert(`동기화 실패: ${json.message}`);
        }
    } catch (e) {
        console.error(e);
        alert("통신 오류 발생");
    } finally {
        btnSync.disabled = false;
        btnSync.innerHTML = originalText;
    }
}

function renderJournalTable(data) {
    const tbody = document.getElementById("journal-list");
    tbody.innerHTML = "";

    if (data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="11" style="text-align: center;">데이터가 없습니다.</td></tr>';
        return;
    }

    data.forEach(item => {
        const tr = document.createElement("tr");

        // Style specific columns
        const sideClass = item.side === "BUY" ? "trade-buy" : "trade-sell";
        const sideLabel = item.side === "BUY" ? "매수" : "매도";

        const price = Math.round(item.price).toLocaleString();
        const amt = Math.round(item.price * item.qty).toLocaleString();

        // PnL & Cost Logic
        let pnlText = "-";
        let costText = "-";
        let avgPriceText = "-";

        // Cost (Fees) - Display if available (usually in meta)
        if (item.meta && item.meta.fees !== undefined) {
            const fees = Math.round(item.meta.fees);
            if (fees > 0) costText = fees.toLocaleString();
        }

        // Avg Price - Display if available (meta.old_avg_price)
        if (item.side === "SELL" && item.meta && item.meta.old_avg_price) {
            avgPriceText = formatCurrency(Math.round(item.meta.old_avg_price));
        }

        // PnL
        if (item.pnl !== undefined && item.pnl !== null) {
            const val = Math.round(item.pnl);
            pnlText = val.toLocaleString();
            if (val > 0) pnlText = `<span class="pnl-positive">${pnlText}</span>`;
            else if (val < 0) pnlText = `<span class="pnl-negative">${pnlText}</span>`;
        }

        // Yield Calculation
        let yieldText = "-";
        if (item.side === "SELL" && item.pnl !== undefined && item.pnl !== null) {
            const pnl = Number(item.pnl);
            const totalAmt = Number(item.price * item.qty);
            const principal = totalAmt - pnl;

            if (principal !== 0) {
                const yieldPct = (pnl / principal) * 100;
                const yieldFormatted = yieldPct.toFixed(2) + "%";

                if (yieldPct > 0) {
                    yieldText = `<span class="pnl-positive">+${yieldFormatted}</span>`;
                } else if (yieldPct < 0) {
                    yieldText = `<span class="pnl-negative">${yieldFormatted}</span>`;
                } else {
                    yieldText = `<span class="pnl-neutral">0.00%</span>`;
                }
            }
        }

        // Check for sync strategy default
        let strategyName = strategyNames[item.strategy_id] || item.strategy_id;

        // Format Stock Name/Symbol
        const nameHtml = item.name
            ? `<div style="font-weight: 500;">${item.name}</div><div style="font-size: 11px; color: #888;">${item.symbol}</div>`
            : `<div style="font-weight: 500;">${item.symbol}</div>`;

        tr.innerHTML = `
            <td>${item.timestamp.replace('T', ' ')}</td>
            <td>${nameHtml}</td>
            <td class="${sideClass}">${sideLabel}</td>
            <td class="text-right" style="color:#666;">${avgPriceText}</td>
            <td class="text-right">${price}</td>
            <td class="text-right">${item.qty}</td>
            <td class="text-right">${amt}</td>
            <td class="text-right">${yieldText}</td>
            <td class="text-right" style="font-weight:bold;">${pnlText}</td>
            <td class="text-right" style="color:#888;">${costText}</td>
            <td>${strategyName}</td>
            <td style="color: #aaa; word-break: break-all; font-size: 11px; line-height: 1.2;">${item.order_id || '-'}</td>
        `;
        tbody.appendChild(tr);
    });
}

function updateJournalSummary(data) {
    // Calculate metrics from realization events
    let totalPnl = 0;
    let winCount = 0;
    let lossCount = 0;
    let realizedCount = 0;

    let grossProfit = 0;
    let grossLoss = 0;

    data.forEach(item => {
        if (item.pnl !== undefined && item.pnl !== null) {
            const pnl = Number(item.pnl);
            totalPnl += pnl;
            realizedCount++;

            if (pnl > 0) {
                winCount++;
                grossProfit += pnl;
            } else {
                lossCount++;
                grossLoss += Math.abs(pnl);
            }
        }
    });

    // Win Rate
    let winRate = 0;
    if (realizedCount > 0) {
        winRate = (winCount / realizedCount) * 100;
    }

    // Profit Factor
    let pf = 0;
    if (grossLoss === 0) {
        pf = grossProfit > 0 ? 99.99 : 0; // Infinite or 0
    } else {
        pf = grossProfit / grossLoss;
    }

    // DOM Updates
    if (document.getElementById("j-total-pnl")) {
        const pnlText = formatCurrency(totalPnl);
        const el = document.getElementById("j-total-pnl");
        el.textContent = pnlText;
        el.className = "value " + (totalPnl >= 0 ? "pnl-positive" : "pnl-negative");
    }

    if (document.getElementById("j-win-rate")) {
        document.getElementById("j-win-rate").textContent = `${winRate.toFixed(1)}%`;
    }

    if (document.getElementById("j-trade-count")) {
        // Show Total Events / Realized Trades
        // e.g. "110 (31)"
        document.getElementById("j-trade-count").textContent = `${data.length} w/ ${realizedCount} PnL`;
    }

    if (document.getElementById("j-profit-factor")) {
        document.getElementById("j-profit-factor").textContent = pf.toFixed(2);
    }
}

// --- TPS Monitoring Logic ---
function updateTpsStats() {
    // Only update if Settings tab is active
    const settingsTab = document.getElementById('tab-settings');
    if (!settingsTab || !settingsTab.classList.contains('active')) return;

    fetch('/api/tps/stats')
        .then(res => res.json())
        .then(data => {
            const led = document.getElementById('tps-status-led');
            const text = document.getElementById('tps-status-text');

            if (data.status === 'running') {
                if (led) led.className = 'led-on'; // Green
                if (text) {
                    text.textContent = '정상 가동중';
                    text.style.color = '#4ade80';
                }

                const cur = document.getElementById('tps-current');
                const cli = document.getElementById('tps-clients');
                const tok = document.getElementById('tps-tokens');

                if (cur) cur.textContent = data.current_tps;
                if (cli) cli.textContent = data.active_clients;

                // Tokens: Try multiple keys
                let tokens = data.tokens_left;
                if (tokens === undefined) tokens = data.remaining_tokens;
                if (tokens === undefined) tokens = data.estimated_local_tokens;

                if (tok) tok.textContent = tokens !== undefined ? parseFloat(tokens).toFixed(2) : "--";
            } else {
                if (led) led.className = 'led-off';
                if (text) {
                    text.textContent = '연결 실패';
                    text.style.color = '#ef4444';
                }
            }
        })
        .catch(err => {
            const led = document.getElementById('tps-status-led');
            const text = document.getElementById('tps-status-text');
            if (led) led.className = 'led-off';
            if (text) {
                text.textContent = '서버 응답 없음';
                text.style.color = '#ef4444';
            }
        });
}

// Start Polling (3s interval)
setInterval(updateTpsStats, 3000);

// Initialize TPS controls
document.addEventListener('DOMContentLoaded', () => {
    // Download Log Button
    const btnDownloadTps = document.getElementById('btn-download-tps-log');
    if (btnDownloadTps) {
        btnDownloadTps.addEventListener('click', () => {
            window.open('/api/tps/logs/download', '_blank');
        });
    }

    // Trigger update immediately when tab switches to settings
    const settingTabBtn = document.querySelector('button[data-tab="tab-settings"]');
    if (settingTabBtn) {
        settingTabBtn.addEventListener('click', () => {
            setTimeout(updateTpsStats, 100);
        });
    }
});

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
// Manual Trade Functions
async function sellImmediate(symbol, event) {
    const qtyInput = document.getElementById(`sell-qty-${symbol}`);
    const qty = parseInt(qtyInput.value);
    const btn = event.currentTarget; // 현재 클릭된 버튼

    if (isNaN(qty) || qty <= 0) {
        alert("올바른 수량을 입력해주세요.");
        return;
    }

    if (!confirm(`${symbol} 종목을 ${qty}주 시장가로 매도하시겠습니까?`)) {
        return;
    }

    try {
        // 버튼 비활성화 및 텍스트 변경
        const originalText = btn.innerText;
        btn.disabled = true;
        btn.innerText = "처리중...";

        const res = await fetch(`${API_BASE}/order/sell_immediate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ symbol, qty })
        });

        const data = await res.json();
        if (data.status === "ok") {
            console.log(`Sell order placed: ${symbol} ${qty}`);
            // 즉시 상태 갱신을 유도하기 위해 updateStatus를 기다릴 수도 있지만, 
            // 2초 폴링이 있으므로 버튼 상태만 유지하다가 폴링 결과로 자연스럽게 버튼이 다시 그려짐
        } else {
            alert(`매도 실패: ${data.message}`);
            btn.disabled = false;
            btn.innerText = originalText;
        }
    } catch (e) {
        console.error("Sell order error:", e);
        alert(`오류가 발생했습니다: ${e.message}`);
        btn.disabled = false;
        btn.innerText = "매도";
    }
}
