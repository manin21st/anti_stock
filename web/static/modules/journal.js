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

        const price = formatComma(Math.round(item.price));
        const amt = formatComma(Math.round(item.price * item.qty));

        // PnL & Cost Logic
        let pnlText = "-";
        let costText = "-";
        let avgPriceText = "-";

        // Cost (Fees) - Display if available (usually in meta)
        if (item.meta && item.meta.fees !== undefined) {
            const fees = Math.round(item.meta.fees);
            if (fees > 0) costText = formatComma(fees);
        }

        // Avg Price - Display if available (meta.old_avg_price)
        if (item.side === "SELL" && item.meta && item.meta.old_avg_price) {
            avgPriceText = formatComma(Math.round(item.meta.old_avg_price));
        }

        // PnL
        if (item.pnl !== undefined && item.pnl !== null) {
            const val = Math.round(item.pnl);
            pnlText = formatComma(val);
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
        const nameHtml = `
            <div class="symbol-cell-wrapper">
                <span style="font-weight: 500;">${item.name || item.symbol}</span>
                <div class="chart-icon-badge" onclick="window.openChart('${item.symbol}', '${item.name || item.symbol}')">📊</div>
            </div>
            <div style="font-size: 11px; color: #888;">${item.symbol}</div>
        `;

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
