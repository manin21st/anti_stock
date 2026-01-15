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
                    if (btnViewChart) btnViewChart.style.display = "inline-block";
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

    if (btnViewChart) {
        btnViewChart.addEventListener("click", () => {
            const symbol = document.getElementById("bt-symbol").value;
            if (symbol) window.openChart(symbol);
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

            if (!lastBacktestResult || (!lastBacktestResult.history && !lastBacktestResult.detailed_logs)) {
                alert("먼저 백테스트를 실행해주세요.");
                return;
            }

            if (confirm("현재 결과를 엑셀로 다운로드하시겠습니까?")) {
                updateStatusText("엑셀 생성 중...", "#f59e0b");

                // Use detailed_logs (per-bar) for full fidelity, or history (trades only) if that's what we have
                // We want the detailed view (Grid view), so detailed_logs is preferred.
                const exportData = lastBacktestResult.detailed_logs || lastBacktestResult.history;

                const config = {
                    symbol: document.getElementById("bt-symbol").value,
                    start: document.getElementById("bt-start-date").value,
                    end: document.getElementById("bt-end-date").value,
                    strategy_id: document.getElementById("bt-strategy-select").value,
                    initial_cash: document.getElementById("bt-initial-cash").value
                };

                try {
                    const response = await fetch(`${API_BASE}/backtest/export`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            history: exportData,
                            config: config
                        })
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

    data.forEach(row => {
        const tr = document.createElement("tr");
        // Unique Key for Intraday
        const uniqueKey = row.time ? `${row.date} ${row.time}` : row.date;
        tr.setAttribute("data-date", uniqueKey);

        // Format numbers (Default from Market Data)
        const close = formatComma(row.close);
        const ma5 = row.ma5 ? formatComma(Math.round(row.ma5)) : "-";
        const ma20 = row.ma20 ? formatComma(Math.round(row.ma20)) : "-";
        const vol = formatComma(row.volume);
        const avgVol = row.vol_ma20 ? formatComma(Math.round(row.vol_ma20)) : "-";

        tr.innerHTML = `
            <td>${uniqueKey}</td>
            <td class="text-right">${close}</td>
            
            <!-- Tech Indicators (Initial: Market Data / Update: Strategy Data) -->
            <td class="text-right ma-short-cell">${ma5}</td>
            <td class="text-right ma-long-cell">${ma20}</td>
            <td class="text-right vol-cell">${vol}</td>
            <td class="text-right avg-vol-cell">${avgVol}</td>
            
            <td class="text-right adx-cell">-</td>
            <td class="text-right slope-cell">-</td>
            
            <!-- Decision Metrics -->
            <td class="text-right border-left rr-cell">-</td>
            <td class="text-right weight-cell">-</td>
            <td class="text-center action-cell" style="font-size: 0.9em;">-</td>
            <td class="log-cell" style="font-size: 0.85em; color: #666; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"></td>
            
            <!-- Trade Info -->
            <td class="border-left text-center side-cell"></td>
            <td class="text-right qty-cell"></td>
            <td class="text-right price-cell"></td>
            <td class="text-right pnl-cell"></td>
        `;
        tbody.appendChild(tr);
    });
}

let lastBacktestResult = null; // Store last result for export

function runBacktestWebSocket() {
    const btnRun = document.getElementById("btn-run-backtest");
    const progressBar = document.getElementById("bt-progress-bar");
    const progressText = document.getElementById("bt-progress-text");
    const statusDiv = document.getElementById("bt-status");

    btnRun.disabled = true;
    if (statusDiv) statusDiv.textContent = "백테스트 실행 중...";

    // Reset Metrics
    updateRealtimeMetrics({
        qty: 0, avg_price: 0, buy_amt: 0, eval_amt: 0, eval_pnl: 0, return_rate: 0, trade_count: 0
    });

    // Clear last result
    lastBacktestResult = null;

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
            // renderMetrics(msg.result.metrics); // Not used

            // Save result for export
            lastBacktestResult = msg.result;

            // Populate full table with rich data from detailed_logs (every bar)
            if (msg.result.detailed_logs) {
                msg.result.detailed_logs.forEach(log => updateTableRow(log));
            } else if (msg.result.history) {
                // Fallback
                msg.result.history.forEach(trade => updateTableRow(trade));
            }

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
        const sideCell = tr.querySelector('.side-cell');
        const qtyCell = tr.querySelector('.qty-cell');
        const priceCell = tr.querySelector('.price-cell');
        const pnlCell = tr.querySelector('.pnl-cell');

        // Tech & Decision Cells
        const adxCell = tr.querySelector('.adx-cell');
        const slopeCell = tr.querySelector('.slope-cell');
        const rrCell = tr.querySelector('.rr-cell');
        const weightCell = tr.querySelector('.weight-cell');
        const actionCell = tr.querySelector('.action-cell');
        const logCell = tr.querySelector('.log-cell');

        // MA/Vol Cells (Update with actual strategy values if available)
        const maShortCell = tr.querySelector('.ma-short-cell');
        const maLongCell = tr.querySelector('.ma-long-cell');
        const volCell = tr.querySelector('.vol-cell');
        const avgVolCell = tr.querySelector('.avg-vol-cell');

        // 1. Basic Trade Info
        sideCell.textContent = trade.side === "1" ? "매수" : (trade.side === "2" ? "매도" : trade.side);
        // Map 1/2 back to text if needed, or use what came from server. 
        // Backtester sends "BUY"/"SELL"/"SKIP" or "1"/"2". Check Backtester._log_trade.
        // It sends "BUY", "SELL", "SKIP".

        let sideText = trade.side;
        if (trade.side === "BUY") sideText = "매수";
        else if (trade.side === "SELL") sideText = "매도";
        else if (trade.side === "SKIP") sideText = "보류";

        sideCell.textContent = sideText;
        sideCell.className = `border-left text-center side-cell ${trade.side === "BUY" ? "trade-buy" : (trade.side === "SELL" ? "trade-sell" : "trade-skip")}`;

        if (trade.qty !== undefined && trade.qty !== null) qtyCell.textContent = formatComma(trade.qty);
        if (trade.price !== undefined && trade.price !== null) priceCell.textContent = formatComma(Math.round(trade.price));

        if (trade.pnl_pct !== undefined && trade.pnl_pct !== null) {
            const pnl = parseFloat(trade.pnl_pct).toFixed(2);
            pnlCell.innerHTML = `<span class="${pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}">${pnl}%</span>`;
        }

        // 2. Tech Indicators
        if (trade.ma_short) maShortCell.textContent = formatComma(Math.round(trade.ma_short));
        if (trade.ma_long) maLongCell.textContent = formatComma(Math.round(trade.ma_long));
        if (trade.volume) volCell.textContent = formatComma(trade.volume);
        if (trade.avg_vol) avgVolCell.textContent = formatComma(Math.round(trade.avg_vol));

        // 3. Decision Metrics
        if (trade.adx) adxCell.textContent = Math.round(trade.adx);
        if (trade.slope) slopeCell.textContent = parseFloat(trade.slope).toFixed(1);

        if (trade.rr_ratio) {
            const rr = parseFloat(trade.rr_ratio).toFixed(2);
            // Highlight good RR
            rrCell.innerHTML = `<span class="${rr >= 2.0 ? 'pnl-positive' : ''}">${rr}</span>`;
        }

        if (trade.perf_weight) weightCell.textContent = parseFloat(trade.perf_weight).toFixed(2);

        if (trade.action) {
            actionCell.textContent = trade.action;
            // Style Action
            if (trade.action === "BUY") actionCell.style.color = "#ef4444";
            else if (trade.action === "SELL") actionCell.style.color = "#3b82f6";
            else if (trade.action === "HOLD" || trade.action === "FAIL") actionCell.style.color = "#f59e0b";
        }

        if (trade.msg) {
            logCell.textContent = trade.msg;
            logCell.title = trade.msg; // Tooltip
        }

        // Highlights (Text Color)
        if (trade.side === "BUY") {
            tr.classList.add("row-buy");
        } else if (trade.side === "SELL") {
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

    setVal("bt-qty", formatComma(d.qty));
    setVal("bt-avg", formatComma(Math.round(d.avg_price)));
    setVal("bt-buy-amt", formatComma(Math.round(d.buy_amt)));
    setVal("bt-eval-amt", formatComma(Math.round(d.eval_amt)));
    setVal("bt-eval-pnl", formatComma(Math.round(d.eval_pnl)));

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
