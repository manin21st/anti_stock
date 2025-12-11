const API_BASE = "/api";

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
            } else {
                statusEl.textContent = "대기 중 (전략 없음)";
                statusEl.className = "status-stopped"; // Use stopped style or a new standby style
                statusEl.style.backgroundColor = "#f59e0b"; // Orange/Yellow for standby
            }

            if (btnStart) btnStart.disabled = true;
            if (btnStop) btnStop.disabled = false;
            // Restart is always enabled
            if (btnRestart) btnRestart.disabled = false;
        } else {
            statusEl.textContent = "중지됨";
            statusEl.className = "status-stopped";
            statusEl.style.backgroundColor = ""; // Reset style
            if (btnStart) btnStart.disabled = false;
            if (btnStop) btnStop.disabled = true;
            if (btnRestart) btnRestart.disabled = false;
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

                    const tr = document.createElement("tr");
                    tr.innerHTML = `
                        <td>${pos.name || pos.symbol}</td>
                        <td>${pos.symbol}</td>
                        <td>${pos.qty}</td>
                        <td>${formatCurrency(pos.avg_price)}</td>
                        <td>${formatCurrency(investedAmt)}</td>
                        <td>${formatCurrency(pos.current_price)}</td>
                        <td>${formatCurrency(evalAmt)}</td>
                        <td class="${pnlClass}">${formatCurrency(pnl)}</td>
                        <td class="${pnlClass}">${pos.pnl_pct.toFixed(2)}%</td>
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
        const keys = Object.keys(currentConfig).filter(key =>
            key !== "system" &&
            key !== "active_strategy" &&
            typeof currentConfig[key] === 'object'
        );

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
            <input type="text" name="${strategyKey}.${key}" value="${value}">
        `;
        form.appendChild(div);
    }
}

// System Config & Control
async function loadSystemConfig() {
    const res = await fetch(`${API_BASE}/system_config`);
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

    if (config.universe && Array.isArray(config.universe)) {
        universeInput.value = config.universe.join(", ");
    }

    // Toggle Visibility
    const toggleScannerUI = () => {
        if (autoScannerCheckbox.checked) {
            scannerModeGroup.style.display = "block";
            universeGroup.style.opacity = "0.5";
            universeInput.disabled = true;
        } else {
            scannerModeGroup.style.display = "none";
            universeGroup.style.opacity = "1";
            universeInput.disabled = false;
        }
    };

    autoScannerCheckbox.addEventListener("change", toggleScannerUI);
    toggleScannerUI(); // Initial state
}

async function sendControl(command) {
    await fetch(`${API_BASE}/control`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: command })
    });
    setTimeout(updateStatus, 1000); // Wait a bit then update status
}

async function saveSystemConfig() {
    const env_type = document.querySelector('input[name="env_type"]:checked').value;
    const market_type = document.querySelector('input[name="market_type"]:checked').value;

    const use_auto_scanner = document.getElementById("use_auto_scanner").checked;
    const scanner_mode = document.querySelector('input[name="scanner_mode"]:checked').value;

    const universeStr = document.getElementById("universe-input").value;
    const universe = universeStr.split(",").map(s => s.trim()).filter(s => s.length > 0);

    await fetch(`${API_BASE}/system_config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            env_type,
            market_type,
            use_auto_scanner,
            scanner_mode,
            universe
        })
    });
}

// Event Listeners
document.getElementById("save-config").addEventListener("click", async () => {
    const strategySelect = document.getElementById("strategy-select");
    const selectedStrategy = strategySelect.value;

    if (!selectedStrategy) {
        alert("전략을 선택해주세요.");
        return;
    }

    const form = document.getElementById("config-form");
    const inputs = form.querySelectorAll("input");
    const newConfigFragment = {};

    // Set active strategy
    newConfigFragment["active_strategy"] = selectedStrategy;

    inputs.forEach(input => {
        const parts = input.name.split(".");
        if (parts.length === 2) {
            if (!newConfigFragment[parts[0]]) newConfigFragment[parts[0]] = {};

            let val;
            if (input.type === "checkbox") {
                val = input.checked;
            } else {
                val = isNaN(Number(input.value)) ? input.value : Number(input.value);
            }
            newConfigFragment[parts[0]][parts[1]] = val;
        }
    });

    try {
        const res = await fetch(`${API_BASE}/config`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(newConfigFragment)
        });
        if (res.ok) {
            alert("전략 설정이 저장되었습니다!");
            await loadConfig();
        } else {
            const err = await res.json();
            alert(`설정 저장 실패: ${err.message || "알 수 없는 오류"}`);
        }
    } catch (e) {
        alert(`통신 오류: ${e.message}`);
    }
});

document.getElementById("btn-start").onclick = () => {
    console.log("Start button clicked");
    sendControl("start");
};
document.getElementById("btn-stop").onclick = () => {
    console.log("Stop button clicked");
    sendControl("stop");
};
document.getElementById("btn-restart").onclick = async () => {
    console.log("Restart button clicked");
    if (confirm("설정을 저장하고 시스템을 재시작하시겠습니까?")) {
        await saveSystemConfig();
        await sendControl("restart");
        alert("재시작 요청을 보냈습니다. 잠시 후 상태가 변경됩니다.");
    }
};

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
    const statusDiv = document.getElementById("data-status");
    const strategySelect = document.getElementById("bt-strategy-select");

    // Populate Strategy Select
    Object.keys(strategyNames).forEach(key => {
        if (key === "common") return;
        const opt = document.createElement("option");
        opt.value = key;
        opt.textContent = strategyNames[key];
        strategySelect.appendChild(opt);
    });

    // Default dates
    const today = new Date();
    const oneMonthAgo = new Date();
    oneMonthAgo.setMonth(today.getMonth() - 1);

    // Format YYYY-MM-DD
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
            const start = document.getElementById("bt-start-date").value.replace(/-/g, "");
            const end = document.getElementById("bt-end-date").value.replace(/-/g, "");

            statusDiv.textContent = "데이터 확인 중...";
            statusDiv.style.color = "#aaa";

            try {
                // 1. Check existence
                const resCheck = await fetch(`${API_BASE}/backtest/check_data`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ symbol, start, end })
                });
                const dataCheck = await resCheck.json();

                if (dataCheck.exists) {
                    statusDiv.textContent = "데이터가 준비되었습니다.";
                    statusDiv.style.color = "#4ade80"; // green
                    btnRun.disabled = false;
                } else {
                    statusDiv.textContent = "데이터 다운로드 필요. 다운로드 시작...";

                    // 2. Download
                    const resDown = await fetch(`${API_BASE}/backtest/download`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ symbol, start, end })
                    });
                    const dataDown = await resDown.json();

                    if (dataDown.status === "ok") {
                        statusDiv.textContent = `다운로드 완료 (데이터 ${dataDown.count}건).`;
                        statusDiv.style.color = "#4ade80";
                        btnRun.disabled = false;
                    } else {
                        statusDiv.textContent = `다운로드 실패: ${dataDown.message}`;
                        statusDiv.style.color = "#f87171";
                    }
                }
            } catch (e) {
                statusDiv.textContent = `통신 오류: ${e.message}`;
                statusDiv.style.color = "#f87171";
            }
        });
    }

    // Run Backtest Button
    if (btnRun) {
        btnRun.addEventListener("click", async (e) => {
            e.preventDefault(); // Prevent form submission

            const symbol = document.getElementById("bt-symbol").value;
            const start = document.getElementById("bt-start-date").value.replace(/-/g, "");
            const end = document.getElementById("bt-end-date").value.replace(/-/g, "");
            const strategy_id = strategySelect.value;
            const initial_cash = document.getElementById("bt-initial-cash").value;

            if (!strategy_id) {
                alert("전략을 선택해주세요.");
                return;
            }

            btnRun.textContent = "실행 중...";
            btnRun.disabled = true;

            try {
                const res = await fetch(`${API_BASE}/backtest/run`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        strategy_id, symbol, start, end, initial_cash
                    })
                });
                const data = await res.json();

                if (data.status === "ok") {
                    renderBacktestResults(data.result);
                } else {
                    alert(`백테스트 실패: ${data.message}`);
                }
            } catch (e) {
                alert(`오류 발생: ${e.message}`);
            } finally {
                btnRun.textContent = "백테스트 실행";
                btnRun.disabled = false;
            }
        });
    }

    // View Chart Button
    if (btnViewChart) {
        btnViewChart.addEventListener("click", () => {
            // Switch to chart tab
            document.querySelector('[data-tab="tab-chart"]').click();

            // Trigger chart load with backtest params
            const symbol = document.getElementById("bt-symbol").value;
            document.getElementById("chart-symbol").value = symbol;

            // Force Daily timeframe for backtest view as we mostly run daily backtests
            const timeframeSelect = document.getElementById("chart-timeframe");
            if (timeframeSelect) {
                timeframeSelect.value = "D";
            }

            if (window.lastBacktestResult) {
                console.log("Loading backtest trades into chart...");

                document.getElementById("btn-load-chart").click();

                setTimeout(() => {
                    if (window.chartApi) {
                        window.chartApi.setMarkers(window.lastBacktestResult.history);
                    }
                }, 1000);
            }
        });
    }
}

function renderBacktestResults(result) {
    // Show content
    document.getElementById("bt-results-placeholder").style.display = "none";
    document.getElementById("bt-results-content").style.display = "flex";

    // Metrics
    const m = result.metrics;
    document.getElementById("bt-total-return").textContent = `${m.total_return}%`;
    document.getElementById("bt-total-return").className = m.total_return >= 0 ? "value pnl-positive" : "value pnl-negative";

    document.getElementById("bt-final-asset").textContent = formatCurrency(m.total_asset);
    document.getElementById("bt-mdd").textContent = `${m.mdd}%`;
    document.getElementById("bt-trade-count").textContent = m.trade_count;

    // Trade Table
    const tbody = document.querySelector("#bt-trade-table tbody");
    tbody.innerHTML = "";

    // Reverse order (newest first)
    const history = [...result.history].reverse();

    history.forEach(trade => {
        const tr = document.createElement("tr");
        const typeClass = trade.side === "BUY" ? "type-buy" : "type-sell";
        tr.innerHTML = `
            <td>${trade.timestamp}</td>
            <td class="${typeClass}">${trade.side}</td>
            <td>${trade.symbol}</td>
            <td>${trade.qty}</td>
            <td>${formatCurrency(trade.price)}</td>
        `;
        tbody.appendChild(tr);
    });

    // Save for Chart
    window.lastBacktestResult = result;
}
