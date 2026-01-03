document.addEventListener('DOMContentLoaded', () => {
    // Wait for App to initialize, or hook into tab switch?
    // We can init once locally.
    initWatchlist();
});

let stockMasterList = []; // {code, name}
let currentWatchlist = []; // [code, ...]
let watchlistData = {}; // {code: {price, change_rate, ma20, sparkline[]}}
let searchFilter = "";

async function initWatchlist() {
    setupEventListeners();
    await loadStockMaster();
    await loadWatchlist();
    // Start polling data? Or wait for tab?
    // Ideally poll only when tab is active.
    // For now, load once.
    await refreshWatchlistData();

    // Auto-refresh data every 5 seconds if tab is active
    setInterval(() => {
        const tab = document.getElementById('tab-watchlist');
        if (tab && tab.style.display === 'block') {
            refreshWatchlistData();
        }
    }, 5000);
}

function setupEventListeners() {
    // Search Input
    const searchInput = document.getElementById('stock-search-input');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            searchFilter = e.target.value.toLowerCase();
            renderStockSelectionList();
        });
    }

    // Buttons
    document.getElementById('btn-refresh-stocks')?.addEventListener('click', loadStockMaster);
    document.getElementById('btn-add-stock')?.addEventListener('click', addSelectedStocksToWatchlist);
    document.getElementById('btn-remove-stock')?.addEventListener('click', removeSelectedStocksFromWatchlist);
    document.getElementById('btn-save-watchlist')?.addEventListener('click', saveWatchlist);
    document.getElementById('wl-check-all')?.addEventListener('change', toggleCheckAll);
    document.getElementById('btn-import-wl')?.addEventListener('click', importBrokerWatchlist);
}

// 1. Load Master List
async function loadStockMaster() {
    const listContainer = document.getElementById('stock-list-container');
    if (listContainer) listContainer.innerHTML = '<div style="padding:20px; text-align:center;">로딩 중...</div>';

    try {
        const res = await fetch('/api/stocks');
        const list = await res.json();
        stockMasterList = list; // [{code, name}]
        renderStockSelectionList();
    } catch (e) {
        console.error("Failed to load stocks:", e);
        if (listContainer) listContainer.innerHTML = '<div style="color:red; padding:10;">로드 실패</div>';
    }
}

// 2. Render Left Panel List
function renderStockSelectionList() {
    const container = document.getElementById('stock-list-container');
    const countEl = document.getElementById('stock-list-count');
    if (!container) return;

    container.innerHTML = '';

    // Filter
    let filtered = stockMasterList;
    if (searchFilter) {
        filtered = stockMasterList.filter(s =>
            s.name.includes(searchFilter) || s.code.includes(searchFilter)
        );
    }

    // Virtual render or Limit? If list is huge (3000 items), filtering helps.
    // Let's cap at 100 items for DOM performance if no filter
    const displayList = filtered.slice(0, 200);

    displayList.forEach(stock => {
        const div = document.createElement('div');
        div.className = 'stock-list-item';
        // Check if already in watchlist
        const exists = currentWatchlist.includes(stock.code);

        div.innerHTML = `
            <input type="checkbox" class="stock-select-cb" value="${stock.code}" data-name="${stock.name}" ${exists ? 'disabled checked' : ''}>
            <div class="symbol-cell-wrapper" style="flex: 1;">
                <span style="font-weight:500;">${stock.name}</span>
                <span style="color:#888; font-size:13px;">${stock.code}</span>
            </div>
        `;
        container.appendChild(div);
    });

    if (countEl) countEl.innerText = filtered.length;
}

// 3. Load Watchlist
async function loadWatchlist() {
    try {
        const res = await fetch('/api/watchlist');
        const list = await res.json();
        currentWatchlist = list || [];
        renderWatchlistTable();
    } catch (e) {
        console.error("Failed to load watchlist:", e);
    }
}

// 4. Import Broker Watchlist
async function importBrokerWatchlist() {
    if (!confirm("증권사(HTS) 관심종목을 가져오시겠습니까?")) return;

    try {
        const btn = document.getElementById('btn-import-wl');
        if (btn) btn.disabled = true;

        const res = await fetch('/api/watchlist/import', { method: 'POST' });
        const result = await res.json();

        if (result.status === 'ok') {
            alert(`관심종목을 가져왔습니다.\n총: ${result.total}개, 신규추가: ${result.added}개`);
            await loadWatchlist();
            refreshWatchlistData();
        } else {
            alert("가져오기 실패: " + result.message);
        }
    } catch (e) {
        alert("API 에러: " + e);
    } finally {
        const btn = document.getElementById('btn-import-wl');
        if (btn) btn.disabled = false;
    }
}

// 5. Add/Remove Logic
function addSelectedStocksToWatchlist() {
    const checkboxes = document.querySelectorAll('.stock-select-cb:checked:not(:disabled)');
    const toAdd = Array.from(checkboxes).map(cb => cb.value);

    if (toAdd.length === 0) return;

    // Add unique
    toAdd.forEach(code => {
        if (!currentWatchlist.includes(code)) {
            currentWatchlist.push(code);
        }
    });

    renderWatchlistTable();
    renderStockSelectionList(); // Re-render left to update disabled state
}

function removeSelectedStocksFromWatchlist() {
    const checkboxes = document.querySelectorAll('.wl-item-cb:checked');
    const toRemove = Array.from(checkboxes).map(cb => cb.value);

    if (toRemove.length === 0) return;

    if (!confirm(`${toRemove.length}개 종목을 목록에서 삭제하시겠습니까?`)) return;

    currentWatchlist = currentWatchlist.filter(code => !toRemove.includes(code));

    renderWatchlistTable();
    renderStockSelectionList();
}

async function saveWatchlist() {
    try {
        const res = await fetch('/api/watchlist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ watchlist: currentWatchlist })
        });
        const ans = await res.json();
        if (ans.status === 'ok') alert('저장되었습니다.');
        else alert('저장 실패: ' + ans.message);
    } catch (e) {
        alert('Err: ' + e);
    }
}

// 6. Data Refresh
async function refreshWatchlistData() {
    if (currentWatchlist.length === 0) return;

    try {
        const res = await fetch('/api/market/data', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbols: currentWatchlist })
        });
        const result = await res.json();
        if (result.status === 'ok') {
            // Update local cache
            result.data.forEach(item => {
                watchlistData[item.code] = item;
            });
            renderWatchlistTable(); // Re-render with new data
        }
    } catch (e) {
        console.error("Data refresh fail:", e);
    }
}

// 7. Render Watchlist Table
function renderWatchlistTable() {
    const tbody = document.getElementById('watchlist-body');
    if (!tbody) return;

    tbody.innerHTML = '';

    // Sort by Name
    const sortedList = [...currentWatchlist].sort((a, b) => {
        const nameA = getStockName(a);
        const nameB = getStockName(b);
        return nameA.localeCompare(nameB, 'ko');
    });

    sortedList.forEach((code, idx) => {
        const data = watchlistData[code] || { price: 0, change_rate: 0, ma20: 0, sparkline: [] };
        const name = getStockName(code);

        const tr = document.createElement('tr');

        // Color classes
        const changeClass = data.change_rate > 0 ? 'row-buy' : (data.change_rate < 0 ? 'row-sell' : '');
        const changeSign = data.change_rate > 0 ? '+' : '';

        // Sparkline SVG
        const sparklineSvg = generateSparkline(data.sparkline, data.change_rate >= 0);

        tr.innerHTML = `
            <td style="text-align:center;"><input type="checkbox" class="wl-item-cb" value="${code}"></td>
            <td style="text-align:center; color: #888; font-size: 13px;">${idx + 1}</td>
            <td style="text-align:left;">
                <div class="symbol-cell-wrapper">
                    <span style="font-weight:600;">${name}</span>
                    <div class="chart-icon-badge" onclick="window.openChart('${code}', '${name}', 'D')">📊</div>
                    ${data.is_held ? `<span style="background-color: #dcfce7; color: #166534; font-size: 11px; padding: 2px 4px; border-radius: 4px; font-weight: normal; margin-left: 5px;">보유</span>` : ''}
                </div>
            </td>
            <td style="text-align:center; color:#666;">${code}</td>
            <td style="text-align:right; font-weight:bold; color: #111;">${data.price.toLocaleString()}</td>
            <td style="text-align:right;" class="${changeClass}">${changeSign}${data.change_rate}%</td>
            <td style="text-align:right;">${data.ma20.toLocaleString()}</td>
            <td style="text-align:center; padding: 2px;">${sparklineSvg}</td>
        `;
        tbody.appendChild(tr);
    });
}

function getStockName(code) {
    const found = stockMasterList.find(s => s.code === code);
    return found ? found.name : dataNameFromCache(code) || code;
}
function dataNameFromCache(code) {
    if (watchlistData[code] && watchlistData[code].name) return watchlistData[code].name;
    return null;
}

function toggleCheckAll(e) {
    const checked = e.target.checked;
    document.querySelectorAll('.wl-item-cb').forEach(cb => cb.checked = checked);
}

// Sparkline Generator
function generateSparkline(data, isUp) {
    if (!data || data.length < 2) return '';

    const width = 120;
    const height = 30;
    const margin = 2;

    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;

    const points = data.map((val, i) => {
        const x = (i / (data.length - 1)) * (width - 2 * margin) + margin;
        // SVG y=0 is top. High value should be low y.
        const normalized = (val - min) / range;
        const y = height - margin - (normalized * (height - 2 * margin));
        return `${x},${y}`;
    }).join(' ');

    const color = isUp ? '#ef4444' : '#3b82f6';

    return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
        <polyline points="${points}" fill="none" stroke="${color}" stroke-width="1.5" />
    </svg>`;
}
