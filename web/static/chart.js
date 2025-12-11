document.addEventListener('DOMContentLoaded', () => {
    console.log("Chart.js loaded");

    const chartContainer = document.getElementById('chart-container');
    const statusEl = document.getElementById('chart-status');
    const btnLoad = document.getElementById('btn-load-chart');
    const inputSymbol = document.getElementById('chart-symbol');
    const selectTimeframe = document.getElementById('chart-timeframe');
    const inputLookback = document.getElementById('chart-lookback');

    // Pagination State
    let allTradeEvents = [];
    let currentPage = 1;
    const itemsPerPage = 5;

    // Store last loaded data for debug purposes
    let lastLoadedData = null;
    let currentMarkers = []; // Keep track of markers

    function logStatus(msg) {
        if (statusEl) {
            statusEl.textContent = `상태: ${msg}`;
            // Flash effect
            statusEl.style.color = '#fff';
            setTimeout(() => statusEl.style.color = '#aaa', 500);
        }
        console.log(`[ChartStatus] ${msg}`);
    }

    if (!chartContainer) {
        console.error("Chart container not found!");
        return;
    }

    // Initialize Chart
    const chart = LightweightCharts.createChart(chartContainer, {
        width: chartContainer.clientWidth || 800,
        height: 600,
        layout: {
            background: { type: 'solid', color: '#1e1e1e' },
            textColor: '#d1d5db',
        },
        grid: {
            vertLines: { color: '#333' },
            horzLines: { color: '#333' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
        },
        rightPriceScale: {
            borderColor: '#485c7b',
        },
        timeScale: {
            borderColor: '#485c7b',
            timeVisible: true,
            secondsVisible: false,
            rightOffset: 12,
            barSpacing: 10, // Set bar spacing to ensure scrolling is needed for many bars
        },
        handleScroll: {
            mouseWheel: true,
            pressedMouseMove: true,
            horzTouchDrag: true,
            vertTouchDrag: true,
        },
        handleScale: {
            axisPressedMouseMove: true,
            mouseWheel: true,
            pinch: true,
        },
    });

    const candleSeries = chart.addCandlestickSeries({
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderVisible: false,
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350',
    });

    // Volume Series
    const volumeSeries = chart.addHistogramSeries({
        color: '#26a69a',
        priceFormat: {
            type: 'volume',
        },
        priceScaleId: 'volume', // Use a separate scale for volume
        scaleMargins: {
            top: 0.7, // Starts at 70% (Bottom 30%)
            bottom: 0,
        },
    });

    // RSI Series
    const rsiSeries = chart.addLineSeries({
        color: 'purple',
        lineWidth: 2,
        priceScaleId: 'rsi',
        scaleMargins: {
            top: 0.7, // Starts at 70% (Bottom 30%)
            bottom: 0,
        },
    });

    // Resize Observer to handle flex layout changes
    const resizeObserver = new ResizeObserver(entries => {
        if (entries.length === 0 || entries[0].target !== chartContainer) { return; }
        const newRect = entries[0].contentRect;
        chart.applyOptions({ width: newRect.width, height: newRect.height });
    });
    resizeObserver.observe(chartContainer);

    // Moving Average Series
    const maSeries = {};
    const maColors = {
        5: '#FF9800',   // Orange
        10: '#FFEB3B',  // Yellow
        20: '#4CAF50',  // Green
        60: '#2196F3',  // Blue
        120: '#9C27B0', // Purple
        200: '#F44336'  // Red
    };

    [5, 10, 20, 60, 120, 200].forEach(period => {
        maSeries[period] = chart.addLineSeries({
            color: maColors[period],
            lineWidth: 1,
            priceScaleId: 'right', // Share scale with candles
            crosshairMarkerVisible: false,
            lastValueVisible: false,
            priceLineVisible: false,
        });

        // Checkbox listener
        const checkbox = document.getElementById(`ma-${period}`);
        if (checkbox) {
            checkbox.addEventListener('change', (e) => {
                maSeries[period].applyOptions({
                    visible: e.target.checked
                });
            });
            // Set initial visibility
            maSeries[period].applyOptions({
                visible: checkbox.checked
            });
        }
    });

    // Configure 'volume' scale
    chart.priceScale('volume').applyOptions({
        scaleMargins: {
            top: 0.7,
            bottom: 0,
        },
        visible: false, // Hide volume scale axis
    });

    // Configure 'rsi' scale
    chart.priceScale('rsi').applyOptions({
        scaleMargins: {
            top: 0.7,
            bottom: 0,
        },
        visible: true,
    });

    // Adjust main price scale
    chart.priceScale('right').applyOptions({
        scaleMargins: {
            top: 0.05,
            bottom: 0.3, // Ends at 70% (Leaving 30% for Vol/RSI)
        },
    });

    // Event Listener
    if (btnLoad) {
        btnLoad.addEventListener('click', async () => {
            logStatus("조회 버튼 클릭됨");
            const symbol = inputSymbol.value;
            const timeframe = selectTimeframe.value;
            const lookback = inputLookback ? inputLookback.value : 300;

            if (!symbol) {
                alert("종목코드를 입력해주세요.");
                return;
            }

            logStatus(`데이터 요청 중... (${symbol}, ${timeframe}, ${lookback}건)`);
            await loadChartData(symbol, timeframe, lookback);
        });
    } else {
        console.error("Load button not found!");
    }

    // Inject Data Button
    const btnInject = document.getElementById('btn-inject-data');
    if (btnInject) {
        btnInject.addEventListener('click', async () => {
            if (!confirm("가상 매매 데이터를 생성하시겠습니까? (삼성전자 005930)\n최근 1시간 내의 임의 데이터 5건이 생성됩니다.")) return;
            try {
                const response = await fetch('/api/debug/inject_trades', { method: 'POST' });
                const result = await response.json();
                if (result.status === 'ok') {
                    alert(`생성 완료: ${result.count}건\n차트를 다시 조회합니다.`);
                    // Force symbol to 005930 for testing
                    if (inputSymbol) inputSymbol.value = '005930';
                    btnLoad.click(); // Reload chart
                } else {
                    alert('실패: ' + result.message);
                }
            } catch (e) {
                alert('요청 실패: ' + e.message);
            }
        });
    }

    // Debug Marker Button
    const btnDebugMarker = document.getElementById('btn-debug-marker');
    if (btnDebugMarker) {
        btnDebugMarker.addEventListener('click', () => {
            // Strategy: Read directly from the DOM to ensure WYSIWYG (What You See Is What You Get)
            // This avoids race conditions between input 'change' events and button 'click' events.

            const firstRowInput = document.querySelector('#chart-trade-list tr:first-child input[type="datetime-local"]');
            let markerTime = null;
            let source = "DOM";

            if (firstRowInput && firstRowInput.value) {
                // Case 1: Read from the visible input field
                const d = new Date(firstRowInput.value);
                if (!isNaN(d.getTime())) {
                    markerTime = d.getTime() / 1000;
                    console.log(`Debug Marker: Read time from Input: ${firstRowInput.value} -> ${markerTime}`);
                }
            }

            // Case 2: Fallback to internal data if DOM read fails
            if (!markerTime && allTradeEvents && allTradeEvents.length > 0) {
                source = "Data";
                const firstEvent = allTradeEvents[0];
                console.log("Debug Marker: Fallback to internal data:", firstEvent);

                if (firstEvent.timestamp) {
                    let ts = firstEvent.timestamp;
                    if (typeof ts === 'string' && ts.includes('.')) ts = ts.split('.')[0];
                    let d = new Date(ts);
                    if (isNaN(d.getTime()) && typeof ts === 'string') d = new Date(ts.replace(' ', 'T'));
                    if (isNaN(d.getTime()) && typeof firstEvent.timestamp === 'number') d = new Date(firstEvent.timestamp * (firstEvent.timestamp < 10000000000 ? 1000 : 1));

                    if (!isNaN(d.getTime())) {
                        markerTime = d.getTime() / 1000;
                    }
                }
            }

            if (markerTime) {
                // Handle Daily timeframe adjustment
                if (typeof currentChartTimeframe !== 'undefined' && currentChartTimeframe === 'D') {
                    const d = new Date(markerTime * 1000);
                    const pad = (n) => n.toString().padStart(2, '0');
                    markerTime = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
                }

                const debugMarker = {
                    time: markerTime,
                    position: 'aboveBar',
                    color: '#FFFF00', // Yellow
                    shape: 'arrowDown',
                    text: 'DEBUG',
                    id: 'debug_manual_' + Date.now()
                };
                currentMarkers.push(debugMarker);
                candleSeries.setMarkers(currentMarkers);
                console.log(`Debug marker added at: ${markerTime} (Source: ${source})`);
            } else {
                console.warn("매매 내역이 없거나 날짜를 읽을 수 없어 디버그 마커를 추가할 수 없습니다.");
            }
        });
    }

    // Pagination Controls
    const btnPrevPage = document.getElementById('btn-prev-page');
    const btnNextPage = document.getElementById('btn-next-page');
    const pageInfo = document.getElementById('page-info');

    if (btnPrevPage && btnNextPage) {
        btnPrevPage.addEventListener('click', () => {
            if (currentPage > 1) {
                currentPage--;
                renderTradeTable();
            }
        });

        btnNextPage.addEventListener('click', () => {
            const maxPage = Math.ceil(allTradeEvents.length / itemsPerPage);
            if (currentPage < maxPage) {
                currentPage++;
                renderTradeTable();
            }
        });
    }

    function renderTradeTable() {
        const tradeList = document.getElementById('chart-trade-list');
        if (!tradeList) return;

        tradeList.innerHTML = '';
        const maxPage = Math.ceil(allTradeEvents.length / itemsPerPage) || 1;

        // Update Controls
        if (pageInfo) pageInfo.textContent = `${currentPage} / ${maxPage}`;
        if (btnPrevPage) btnPrevPage.disabled = currentPage === 1;
        if (btnNextPage) btnNextPage.disabled = currentPage === maxPage;

        if (allTradeEvents.length === 0) {
            tradeList.innerHTML = '<tr><td colspan="5" style="padding:10px; text-align:center; color:#777;">매매 내역이 없습니다.</td></tr>';
            return;
        }

        const startIndex = (currentPage - 1) * itemsPerPage;
        const endIndex = startIndex + itemsPerPage;
        const pageItems = allTradeEvents.slice(startIndex, endIndex);

        pageItems.forEach(event => {
            const row = document.createElement('tr');
            row.style.borderBottom = '1px solid #333';

            // Add hover effect
            row.onmouseover = function () { this.style.backgroundColor = '#333'; };
            row.onmouseout = function () { this.style.backgroundColor = 'transparent'; };

            // Create editable time input
            let localISOTime = "";

            // Robust Date Parsing using Date object
            if (event.timestamp) {
                let ts = event.timestamp;
                // Strip microseconds if present
                if (typeof ts === 'string' && ts.includes('.')) {
                    ts = ts.split('.')[0];
                }

                let d = new Date(ts);

                // Fallback for Python string format "YYYY-MM-DD HH:mm:ss" (space instead of T)
                if (isNaN(d.getTime()) && typeof ts === 'string') {
                    const isoLike = ts.replace(' ', 'T');
                    d = new Date(isoLike);
                }

                // Fallback for numeric timestamp (seconds or milliseconds)
                if (isNaN(d.getTime()) && typeof event.timestamp === 'number') {
                    d = new Date(event.timestamp * (event.timestamp < 10000000000 ? 1000 : 1));
                }

                if (!isNaN(d.getTime())) {
                    const pad = (n) => n.toString().padStart(2, '0');
                    const year = d.getFullYear();
                    const month = pad(d.getMonth() + 1);
                    const day = pad(d.getDate());
                    const hour = pad(d.getHours());
                    const minute = pad(d.getMinutes());
                    const second = pad(d.getSeconds());
                    localISOTime = `${year}-${month}-${day}T${hour}:${minute}:${second}`;
                } else {
                    console.error("Invalid Date:", event.timestamp);
                    localISOTime = ""; // Keep empty to show error state in UI
                }
            } else {
                console.warn("Missing timestamp for event:", event);
            }

            const timeInput = document.createElement('input');
            timeInput.type = 'datetime-local';
            timeInput.value = localISOTime;
            timeInput.step = '1';
            timeInput.style.background = '#fff';
            timeInput.style.color = '#000';
            timeInput.style.border = '1px solid #ccc';
            timeInput.style.fontSize = '11px';
            timeInput.style.width = '160px';

            // Stop propagation to prevent row click
            timeInput.onclick = (e) => e.stopPropagation();

            timeInput.onchange = function (e) {
                const newTimeStr = e.target.value;
                if (!newTimeStr) return;

                const newDate = new Date(newTimeStr);
                let newMarkerTime = newDate.getTime() / 1000;

                // Apply Daily format if needed
                if (typeof currentChartTimeframe !== 'undefined' && currentChartTimeframe === 'D') {
                    const pad = (n) => n.toString().padStart(2, '0');
                    newMarkerTime = `${newDate.getFullYear()}-${pad(newDate.getMonth() + 1)}-${pad(newDate.getDate())}`;
                }

                // Find and update marker by ID
                const markerIndex = currentMarkers.findIndex(m => m.id === event.event_id);

                if (markerIndex !== -1) {
                    currentMarkers[markerIndex].time = newMarkerTime;

                    // Update the source event object in allTradeEvents
                    event.timestamp = newDate.toISOString();

                    // Also update the original array if needed
                    const originalEvent = allTradeEvents.find(e => e.event_id === event.event_id);
                    if (originalEvent) {
                        originalEvent.timestamp = newDate.toISOString();
                    }

                    currentMarkers.sort((a, b) => {
                        const timeA = typeof a.time === 'string' ? new Date(a.time).getTime() / 1000 : a.time;
                        const timeB = typeof b.time === 'string' ? new Date(b.time).getTime() / 1000 : b.time;
                        return timeA - timeB;
                    });
                    candleSeries.setMarkers(currentMarkers);
                    logStatus(`마커 시간 변경됨: ${newTimeStr} -> ${newMarkerTime}`);
                } else {
                    console.error("Marker not found for ID:", event.event_id);
                    alert("마커를 찾을 수 없습니다. (ID 오류)");
                }
            };

            const typeText = event.side === 'BUY' ? '매수' : '매도';
            const typeStyle = `color: ${event.side === 'BUY' ? '#26a69a' : '#ef5350'}; font-weight: bold;`;

            const price = parseFloat(event.price).toLocaleString();
            const qty = event.qty.toLocaleString();
            const amount = (event.price * event.qty).toLocaleString();

            const timeTd = document.createElement('td');
            timeTd.style.padding = '5px';
            timeTd.appendChild(timeInput);

            row.appendChild(timeTd);
            row.innerHTML += `
                <td style="padding: 5px; text-align: center; ${typeStyle}">${typeText}</td>
                <td style="padding: 5px; text-align: right;">${price}</td>
                <td style="padding: 5px; text-align: right;">${qty}</td>
                <td style="padding: 5px; text-align: right;">${amount}</td>
            `;
            tradeList.appendChild(row);
        });
    }

    let currentChartTimeframe = "1m"; // Global variable

    async function loadChartData(symbol, timeframe, lookback) {
        currentChartTimeframe = timeframe; // Store globally
        try {
            logStatus("API 호출 시작...");
            const response = await fetch(`/api/chart/data?symbol=${symbol}&timeframe=${timeframe}&lookback=${lookback}`);
            logStatus(`API 응답 수신 (Status: ${response.status})`);

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            logStatus("데이터 수신 완료. 파싱 중...");

            if (data.status === 'error') {
                logStatus(`서버 에러: ${data.message}`);
                alert('Error: ' + data.message);
                return;
            }

            // Store data globally for debug access
            lastLoadedData = data;

            // Update Candles
            if (data.candles && data.candles.length > 0) {
                logStatus(`${data.candles.length}개 캔들 렌더링...`);
                data.candles.sort((a, b) => (a.time > b.time ? 1 : -1));
                candleSeries.setData(data.candles);

                // Update Volume
                const volumeData = data.candles.map(c => ({
                    time: c.time,
                    value: c.volume,
                    color: c.close >= c.open ? '#26a69a' : '#ef5350'
                }));
                volumeSeries.setData(volumeData);

                logStatus(`렌더링 완료 (${data.candles.length}개)`);
            } else {
                logStatus("데이터 없음 (캔들 0개)");
                alert("해당 기간의 데이터가 없습니다.");
            }

            // Update RSI
            if (data.rsi && data.rsi.length > 0) {
                data.rsi.sort((a, b) => (a.time > b.time ? 1 : -1));
                rsiSeries.setData(data.rsi);
            }

            // Update Moving Averages
            if (data.ma_data) {
                for (const [key, seriesData] of Object.entries(data.ma_data)) {
                    const period = key.split('_')[1]; // ma_5 -> 5
                    if (maSeries[period] && seriesData.length > 0) {
                        seriesData.sort((a, b) => (a.time > b.time ? 1 : -1));
                        maSeries[period].setData(seriesData);
                    }
                }
            }

            // Update Markers
            currentMarkers = []; // Reset global markers
            if (data.markers) {
                data.markers.forEach((event, index) => {
                    // Ensure event_id exists
                    if (!event.event_id) {
                        event.event_id = `gen_${Date.now()}_${index}`;
                    }
                    let time = new Date(event.timestamp).getTime() / 1000;

                    // For Daily timeframe, use YYYY-MM-DD string to align with candles
                    if (timeframe === 'D') {
                        const d = new Date(event.timestamp);
                        const pad = (n) => n.toString().padStart(2, '0');
                        time = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
                    }

                    let color = '#2196F3';
                    let shape = 'circle';
                    let text = event.event_type;

                    if (event.side === 'BUY') {
                        color = '#26a69a';
                        shape = 'arrowUp';
                        text = 'Buy ' + event.qty;
                    } else if (event.side === 'SELL') {
                        color = '#ef5350';
                        shape = 'arrowDown';
                        text = 'Sell ' + event.qty;
                    }

                    currentMarkers.push({
                        time: time,
                        position: event.side === 'BUY' ? 'belowBar' : 'aboveBar',
                        color: color,
                        shape: shape,
                        text: text,
                        id: event.event_id // Add ID for lookup
                    });
                });
                candleSeries.setMarkers(currentMarkers);

                // Populate Trade History Table with Pagination
                allTradeEvents = [...data.markers].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
                currentPage = 1;
                renderTradeTable();

            } else {
                candleSeries.setMarkers([]);
                allTradeEvents = [];
                renderTradeTable();
            }

            // Scroll to the latest bar
            chart.timeScale().scrollToPosition(0, false);

        } catch (e) {
            console.error(e);
            logStatus(`오류 발생: ${e.message}`);
            alert('차트 데이터를 불러오는데 실패했습니다.');
        }
    }

    // Expose API for external control
    window.chartApi = {
        setMarkers: (events) => {
            currentMarkers = []; // Reset global markers
            if (!events || events.length === 0) {
                candleSeries.setMarkers([]);
                return;
            }

            events.forEach((event, index) => {
                // Ensure event_id exists
                if (!event.event_id) {
                    event.event_id = `bt_${Date.now()}_${index}`;
                }
                let time = new Date(event.timestamp).getTime() / 1000;

                // For Daily timeframe, use YYYY-MM-DD string to align with candles
                if (currentChartTimeframe === 'D') {
                    const d = new Date(event.timestamp);
                    const pad = (n) => n.toString().padStart(2, '0');
                    time = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
                }

                let color = '#2196F3';
                let shape = 'circle';
                let text = event.event_type || 'Trade';

                if (event.side === 'BUY') {
                    color = '#26a69a';
                    shape = 'arrowUp';
                    text = 'Buy ' + event.qty;
                } else if (event.side === 'SELL') {
                    color = '#ef5350';
                    shape = 'arrowDown';
                    text = 'Sell ' + event.qty;
                }

                currentMarkers.push({
                    time: time,
                    position: event.side === 'BUY' ? 'belowBar' : 'aboveBar',
                    color: color,
                    shape: shape,
                    text: text,
                    id: event.event_id
                });
            });

            // Sort markers by time
            currentMarkers.sort((a, b) => {
                const tA = typeof a.time === 'string' ? new Date(a.time).getTime() : a.time * 1000;
                const tB = typeof b.time === 'string' ? new Date(b.time).getTime() : b.time * 1000;
                return tA - tB;
            });

            candleSeries.setMarkers(currentMarkers);
            console.log(`[chartApi] Set ${currentMarkers.length} markers from external source.`);

            // Also update Trade Table
            allTradeEvents = [...events].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
            currentPage = 1;
            renderTradeTable();
        }
    };
});
