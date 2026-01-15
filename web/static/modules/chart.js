// Chart Global Variables
let chart, candleSeries, volumeSeries, rsiSeries, rsiOverbought, rsiOversold;
let maSeries = {};
let currentSymbol = null;
let currentInterval = '5m';

document.addEventListener('DOMContentLoaded', () => {
    const chartContainer = document.getElementById('chart-container');
    if (!chartContainer) return;

    // Initialize Chart
    chart = LightweightCharts.createChart(chartContainer, {
        width: chartContainer.clientWidth || 800,
        height: 450,
        layout: {
            background: { type: 'solid', color: '#1a1d21' },
            textColor: '#d1d5db',
        },
        grid: {
            vertLines: { color: '#2a2e33' },
            horzLines: { color: '#2a2e33' },
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
        },
    });

    // 1. Candle Series
    candleSeries = chart.addCandlestickSeries({
        upColor: '#ef5350',
        downColor: '#26a69a',
        borderVisible: false,
        wickUpColor: '#ef5350',
        wickDownColor: '#26a69a',
        priceScaleId: 'right',
    });
    candleSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.05, bottom: 0.45 },
    });

    // 2. Volume Series
    volumeSeries = chart.addHistogramSeries({
        color: '#26a69a',
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
    });
    volumeSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.6, bottom: 0.2 },
        visible: false,
    });

    // 3. MA Series
    const maColors = { 5: '#FF9800', 10: '#FFEB3B', 20: '#4CAF50', 60: '#2196F3', 120: '#9C27B0', 200: '#F44336' };
    [5, 10, 20, 60, 120, 200].forEach(period => {
        maSeries[period] = chart.addLineSeries({
            color: maColors[period],
            lineWidth: 1, // Reduced to 1px for detail
            priceScaleId: 'right',
            crosshairMarkerVisible: false,
            lastValueVisible: false,
            priceLineVisible: false,
            title: `MA${period}`,
        });
    });

    // 4. RSI Series
    rsiSeries = chart.addLineSeries({
        color: '#a855f7',
        lineWidth: 1,
        priceScaleId: 'rsi',
        title: 'RSI',
    });

    rsiOverbought = chart.addBaselineSeries({
        baseValue: 70,
        topFillColor1: 'rgba(239, 83, 80, 0.4)',
        topFillColor2: 'rgba(239, 83, 80, 0.1)',
        bottomFillColor1: 'rgba(0,0,0,0)',
        bottomFillColor2: 'rgba(0,0,0,0)',
        priceScaleId: 'rsi',
        lastValueVisible: false,
        priceLineVisible: false,
    });

    rsiOversold = chart.addBaselineSeries({
        baseValue: 30,
        topFillColor1: 'rgba(0,0,0,0)',
        topFillColor2: 'rgba(0,0,0,0)',
        bottomFillColor1: 'rgba(38, 166, 154, 0.1)',
        bottomFillColor2: 'rgba(38, 166, 154, 0.4)',
        priceScaleId: 'rsi',
        lastValueVisible: false,
        priceLineVisible: false,
    });

    chart.priceScale('rsi').applyOptions({
        scaleMargins: { top: 0.8, bottom: 0.05 },
        visible: true,
        autoScale: true,
    });

    const rsiAutoscale = () => ({ priceRange: { minValue: 0, maxValue: 100 } });
    rsiSeries.applyOptions({ autoscaleInfoProvider: rsiAutoscale });
    rsiOverbought.applyOptions({ autoscaleInfoProvider: rsiAutoscale });
    rsiOversold.applyOptions({ autoscaleInfoProvider: rsiAutoscale });

    // Resize
    const resizer = new ResizeObserver(entries => {
        if (entries[0]) {
            const { width, height } = entries[0].contentRect;
            chart.applyOptions({ width, height });
        }
    });
    resizer.observe(chartContainer);

    // [Fix] Inject FontAwesome if missing (for spinner icon)
    if (!document.querySelector('link[href*="font-awesome"]')) {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css';
        document.head.appendChild(link);
    }
});

// --- Loading Indicator Helper ---
function showLoading() {
    const container = document.getElementById('chart-container');
    if (!container) return;

    let loader = document.getElementById('chart-loader');
    if (!loader) {
        loader = document.createElement('div');
        loader.id = 'chart-loader';
        loader.style.position = 'absolute';
        loader.style.top = '0';
        loader.style.left = '0';
        loader.style.width = '100%';
        loader.style.height = '100%';
        loader.style.background = 'rgba(26, 29, 33, 0.8)';
        loader.style.display = 'flex';
        loader.style.justifyContent = 'center';
        loader.style.alignItems = 'center';
        loader.style.zIndex = '10';
        loader.style.color = '#3b82f6';
        loader.style.fontSize = '2rem';
        loader.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        container.style.position = 'relative';
        container.appendChild(loader);
    }
    loader.style.display = 'flex';
}

function hideLoading() {
    const loader = document.getElementById('chart-loader');
    if (loader) {
        loader.style.display = 'none';
    }
}

// --- Data Clearing Helper ---
function clearChart() {
    if (candleSeries) candleSeries.setData([]);
    if (volumeSeries) volumeSeries.setData([]);
    if (rsiSeries) rsiSeries.setData([]);
    if (rsiOverbought) rsiOverbought.setData([]);
    if (rsiOversold) rsiOversold.setData([]);

    // Clear MA Series
    Object.values(maSeries).forEach(series => {
        if (series) series.setData([]);
    });
}

async function loadChartData(symbol, timeframe) {
    try {
        const url = `/api/chart/data?symbol=${symbol}&timeframe=${timeframe}&lookback=500`;
        const res = await fetch(url);
        const data = await res.json();

        // Hide loading if error
        if (data.status === 'error') {
            hideLoading();
            return;
        }

        // Candle & Volume
        if (data.candles && data.candles.length > 0) {
            const candles = data.candles.sort((a, b) => a.time - b.time || (a.time > b.time ? 1 : -1));
            candleSeries.setData(candles);
            volumeSeries.setData(candles.map(c => ({
                time: c.time,
                value: c.volume,
                color: c.close >= c.open ? '#ef5350' : '#26a69a'
            })));
        }

        // MA
        if (data.ma_data) {
            [5, 10, 20, 60, 120, 200].forEach(p => {
                if (maSeries[p] && data.ma_data[`ma_${p}`]) {
                    const maData = data.ma_data[`ma_${p}`].sort((a, b) => a.time - b.time || (a.time > b.time ? 1 : -1));
                    maSeries[p].setData(maData);
                }
            });
        }

        // RSI
        if (data.rsi && data.rsi.length > 0) {
            const rsi = data.rsi.sort((a, b) => a.time - b.time || (a.time > b.time ? 1 : -1));
            rsiSeries.setData(rsi);
            rsiOverbought.setData(rsi);
            rsiOversold.setData(rsi);
        }

        chart.timeScale().fitContent();
        candleSeries.setMarkers([]);
    } catch (e) {
        console.error("Load failed", e);
    } finally {
        hideLoading(); // Always hide loading
    }
}

window.toggleMA = (p, v) => maSeries[p] && maSeries[p].applyOptions({ visible: v });

window.openChart = (symbol, name = "", interval = null) => {
    currentSymbol = symbol;
    if (interval) currentInterval = interval;
    const popup = document.getElementById('chart-popup');
    document.getElementById('popup-symbol-name').textContent = name || symbol;
    document.getElementById('popup-symbol-code').textContent = symbol;
    popup.style.display = 'flex';

    document.querySelectorAll('.interval-selector .small-btn').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('onclick').includes(`'${currentInterval}'`));
    });

    // Reset UI & Visibility
    [5, 10, 20, 60, 120, 200].forEach(p => {
        const cb = document.querySelector(`.ma-selector input[onchange*="(${p},"]`);
        if (cb) cb.checked = true;
        if (maSeries[p]) maSeries[p].applyOptions({ visible: true });
    });

    // Clear and Show Loading
    clearChart();
    showLoading();

    loadChartData(symbol, currentInterval);
};

window.closeChart = () => document.getElementById('chart-popup').style.display = 'none';

window.updateInterval = (interval) => {
    currentInterval = interval;
    document.querySelectorAll('.interval-selector .small-btn').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('onclick').includes(`'${interval}'`));
    });
    if (currentSymbol) {
        clearChart();
        showLoading();
        loadChartData(currentSymbol, interval);
    }
};
