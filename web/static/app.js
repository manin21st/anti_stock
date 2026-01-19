const API_BASE = "/api";
let userSellQty = {}; // Store manual input values to survive poll re-renders: { symbol: value }

// Utils
const formatCurrency = (val) => new Intl.NumberFormat('ko-KR', { style: 'currency', currency: 'KRW' }).format(val);
const formatComma = (val) => new Intl.NumberFormat('ko-KR').format(val); // 통화 기호 없는 콤마 포맷

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
    const tabBtns = Array.from(document.querySelectorAll('.tab-nav .tab-btn'));
    const tabContents = document.querySelectorAll('.tab-content');

    function switchTab(index) {
        if (index < 0 || index >= tabBtns.length) return;

        const btn = tabBtns[index];
        // Remove active class from all
        tabBtns.forEach(b => b.classList.remove('active'));
        tabContents.forEach(c => c.classList.remove('active'));

        // Add active class to clicked
        btn.classList.add('active');
        const tabId = btn.getAttribute('data-tab');
        const content = document.getElementById(tabId);
        if (content) {
            content.classList.add('active');
        }
    }

    tabBtns.forEach((btn, idx) => {
        btn.addEventListener('click', () => switchTab(idx));
    });

    // Swipe Swipe Logic
    let touchStartX = 0;
    let touchStartY = 0;
    let touchEndX = 0;
    let touchEndY = 0;

    document.addEventListener('touchstart', (e) => {
        // Ignore if touching an input, select, textarea
        if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName)) return;
        // Ignore specific overlays that handle their own touches
        if (e.target.closest('.chart-popup-overlay') || e.target.closest('.floating-popup')) return;

        touchStartX = e.changedTouches[0].clientX;
        touchStartY = e.changedTouches[0].clientY;
    }, { passive: true });

    document.addEventListener('touchend', (e) => {
        if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName)) return;
        if (e.target.closest('.chart-popup-overlay') || e.target.closest('.floating-popup')) return;

        touchEndX = e.changedTouches[0].clientX;
        touchEndY = e.changedTouches[0].clientY;
        handleSwipe();
    }, { passive: true });

    function handleSwipe() {
        const deltaX = touchEndX - touchStartX;
        const deltaY = touchEndY - touchStartY;

        // Thresholds
        const minSwipeDistance = 70;
        const maxVerticalDistance = 100;

        if (Math.abs(deltaX) > minSwipeDistance && Math.abs(deltaY) < maxVerticalDistance) {
            const currentBtn = document.querySelector('.tab-nav .tab-btn.active');
            const currentIndex = tabBtns.indexOf(currentBtn);

            if (deltaX < 0) {
                // Swipe Left -> Next Tab
                if (currentIndex < tabBtns.length - 1) {
                    switchTab(currentIndex + 1);
                }
            } else {
                // Swipe Right -> Previous Tab
                if (currentIndex > 0) {
                    switchTab(currentIndex - 1);
                }
            }
        }
    }
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
                    const pnl = Math.round(evalAmt - investedAmt);
                    const pnlClass = pnl >= 0 ? 'pnl-positive' : 'pnl-negative'; // Red for profit, Blue for loss (KR style)

                    // Decide input value: either user's current input or current held qty
                    if (userSellQty[pos.symbol] === undefined) {
                        userSellQty[pos.symbol] = pos.qty;
                    }

                    const tr = document.createElement("tr");
                    tr.innerHTML = `
                        <td style="text-align: left;">
                            <div class="symbol-cell-wrapper" style="display: flex; align-items: center; gap: 8px;">
                                <span style="font-weight: 600;">${pos.name || pos.symbol}</span>
                                <div class="chart-icon-badge" onclick="window.openChart('${pos.symbol}', '${pos.name || pos.symbol}')">📊</div>
                            </div>
                        </td>
                        <td style="text-align: center; color: var(--text-secondary);">${pos.symbol}</td>
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
                        <td style="text-align: right;">${formatComma(pos.avg_price)}</td>
                        <td style="text-align: right; color: var(--text-secondary);">${formatComma(investedAmt)}</td>
                        <td style="text-align: right; font-weight: 500;">${formatComma(pos.current_price)}</td>
                        <td style="text-align: right; font-weight: 500;">${formatComma(evalAmt)}</td>
                        <td style="text-align: right;" class="${pnlClass}">${formatComma(pnl)}</td>
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
    if (strategySelect && strategySelect.options.length === 1) {
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
        let envVal = config.env_type;
        if (envVal === "prod") envVal = "real"; // Normalize prod -> real
        const el = document.querySelector(`input[name="env_type"][value="${envVal}"]`);
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
