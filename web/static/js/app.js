/**
 * AUREUS-SMC Institutional Frontend Engine
 * TradingView Lightweight Charts v4 Integration + Sub-millisecond WebSocket Pipeline
 */

let chart;
let candleSeries;
let ws;
let currentSymbol = "XAUUSD";
let currentTimeframe = "M1";

// SMC Chart Price Lines
let londonHighLine = null;
let londonLowLine = null;
let stopLossLine = null;
let takeProfitLine = null;
let breakEvenLine = null;

// Tracked markers (Swings, Sweeps, Entries)
let chartMarkers = [];

// Daily Decision & Setups Lines
let callEntryLine = null;
let callSLLine = null;
let callTPLine = null;
let putEntryLine = null;
let putSLLine = null;
let putTPLine = null;
let pivotPPLine = null;
let zonesVisible = false;
let currentBriefing = null;
let latestLiveBid = 4055.20;

document.addEventListener("DOMContentLoaded", () => {
    initChart();
    fetchBars(currentTimeframe);
    connectWebSocket();
    fetchSystemStatus();
    fetchMetrics();
    fetchTrades();
    fetchPositions();
    fetchDailyBriefing();
    setInterval(updateClock, 1000);
});

// 1. Initialize TradingView Lightweight Chart
function initChart() {
    const container = document.getElementById("tv-chart");
    if (!container) return;

    chart = LightweightCharts.createChart(container, {
        layout: {
            background: { color: "#151b2d" },
            textColor: "#94a3b8",
            fontSize: 11,
            fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto",
        },
        grid: {
            vertLines: { color: "rgba(35, 44, 69, 0.4)" },
            horzLines: { color: "rgba(35, 44, 69, 0.4)" },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
            vertLine: { color: "#d4af37", width: 1, style: 3 },
            horzLine: { color: "#d4af37", width: 1, style: 3 },
        },
        rightPriceScale: {
            borderColor: "#232c45",
            autoScale: true,
            scaleMargins: { top: 0.15, bottom: 0.15 },
        },
        timeScale: {
            borderColor: "#232c45",
            timeVisible: true,
            secondsVisible: false,
        },
    });

    candleSeries = chart.addCandlestickSeries({
        upColor: "#10b981",
        downColor: "#ef4444",
        borderVisible: false,
        wickUpColor: "#10b981",
        wickDownColor: "#ef4444",
    });

    window.addEventListener("resize", () => {
        chart.applyOptions({
            width: container.clientWidth,
            height: container.clientHeight,
        });
    });
}

// 2. High-Speed WebSocket Client
function connectWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    ws = new WebSocket(`${protocol}//${host}/ws/stream`);

    ws.onopen = () => {
        console.log("[WS] Connected to AUREUS-SMC High-Speed Pipeline.");
        document.getElementById("ws-status-badge").textContent = "WS CONNECTED";
        document.getElementById("ws-status-badge").className = "badge badge-live";
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleIncomingMessage(msg);
        } catch (err) {
            console.error("[WS] Message parse error:", err);
        }
    };

    ws.onclose = () => {
        console.warn("[WS] Disconnected. Reconnecting in 2s...");
        document.getElementById("ws-status-badge").textContent = "RECONNECTING";
        document.getElementById("ws-status-badge").className = "badge badge-state";
        setTimeout(connectWebSocket, 2000);
    };
}

// 3. Message Routing
function handleIncomingMessage(msg) {
    switch (msg.type) {
        case "TICK":
            handleTick(msg.data);
            break;
        case "BAR_UPDATE":
        case "BAR_CLOSED":
            handleBar(msg.data);
            break;
        case "LONDON_RANGE":
            renderLondonRange(msg.data.high, msg.data.low);
            break;
        case "LIQUIDITY_SWEEP":
            handleSweepEvent(msg.data);
            break;
        case "DISPLACEMENT":
            handleDisplacementEvent(msg.data);
            break;
        case "FVG":
            handleFVGEvent(msg.data);
            break;
        case "SIGNAL":
            handleSignalEvent(msg.data);
            break;
        case "STATE_CHANGE":
            updateStateUI(msg.data.current);
            break;
        default:
            break;
    }
}

// 4. Tick & Candle Stream Handlers
function handleTick(tick) {
    if (tick && tick.bid) latestLiveBid = tick.bid;
    document.getElementById("live-bid").textContent = tick.bid.toFixed(2);
    document.getElementById("live-ask").textContent = tick.ask.toFixed(2);
    document.getElementById("live-spread").textContent = `$${tick.spread.toFixed(2)}`;
}

function handleBar(barData) {
    if (barData.timeframe === currentTimeframe) {
        candleSeries.update({
            time: barData.time,
            open: barData.open,
            high: barData.high,
            low: barData.low,
            close: barData.close,
        });
    }
}

// 5. SMC Visualization Overlays
function renderLondonRange(high, low) {
    document.getElementById("radar-london-high").textContent = `$${high.toFixed(2)}`;
    document.getElementById("radar-london-low").textContent = `$${low.toFixed(2)}`;
    document.getElementById("step-london").className = "flow-step completed";

    // Draw London High
    if (londonHighLine) candleSeries.removePriceLine(londonHighLine);
    londonHighLine = candleSeries.createPriceLine({
        price: high,
        color: "#06b6d4",
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: "LONDON HIGH (BSL)",
    });

    // Draw London Low
    if (londonLowLine) candleSeries.removePriceLine(londonLowLine);
    londonLowLine = candleSeries.createPriceLine({
        price: low,
        color: "#06b6d4",
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        axisLabelVisible: true,
        title: "LONDON LOW (SSL)",
    });
}

function handleSweepEvent(data) {
    document.getElementById("step-sweep").className = "flow-step completed";
    document.getElementById("radar-sweep-status").textContent = `${data.direction} Swept @ ${data.extreme} (${data.pips} pips)`;
    addMarker({
        time: Math.floor(new Date(data.time).getTime() / 1000),
        position: data.direction === "BUY" ? "belowBar" : "aboveBar",
        color: "#f59e0b",
        shape: data.direction === "BUY" ? "arrowUp" : "arrowDown",
        text: `LIQUIDITY SWEEP (${data.direction})`,
    });
}

function handleDisplacementEvent(data) {
    document.getElementById("step-mss").className = "flow-step completed";
    document.getElementById("radar-mss-status").textContent = `MSS Break: ${data.broken_level} (${data.ratio}x ATR)`;
    addMarker({
        time: Math.floor(new Date(data.time).getTime() / 1000),
        position: data.direction === "BUY" ? "aboveBar" : "belowBar",
        color: "#8b5cf6",
        shape: "circle",
        text: `MSS / CHOCH (${data.direction})`,
    });
}

function handleFVGEvent(data) {
    document.getElementById("step-fvg").className = "flow-step completed";
    document.getElementById("radar-fvg-status").textContent = `CE 50%: $${data.ce.toFixed(2)} [${data.bottom}-${data.top}]`;
}

function handleSignalEvent(sig) {
    document.getElementById("step-execution").className = "flow-step completed";

    // Plot Order Entry Markers & Lines
    if (stopLossLine) candleSeries.removePriceLine(stopLossLine);
    stopLossLine = candleSeries.createPriceLine({
        price: sig.sl,
        color: "#ef4444",
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Dotted,
        axisLabelVisible: true,
        title: `STOP LOSS ($${sig.sl.toFixed(2)})`,
    });

    if (takeProfitLine) candleSeries.removePriceLine(takeProfitLine);
    takeProfitLine = candleSeries.createPriceLine({
        price: sig.tp,
        color: "#10b981",
        lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Dotted,
        axisLabelVisible: true,
        title: `TAKE PROFIT 1:3 ($${sig.tp.toFixed(2)})`,
    });

    addMarker({
        time: Math.floor(Date.now() / 1000),
        position: sig.direction === "BUY" ? "belowBar" : "aboveBar",
        color: sig.direction === "BUY" ? "#10b981" : "#ef4444",
        shape: sig.direction === "BUY" ? "arrowUp" : "arrowDown",
        text: `ENTRY ${sig.direction} @ ${sig.entry}`,
    });
}

function addMarker(marker) {
    chartMarkers.push(marker);
    candleSeries.setMarkers(chartMarkers);
}

// 6. REST API Polling & Metric Handlers
async function fetchSystemStatus() {
    try {
        const res = await fetch("/api/status");
        const data = await res.json();
        updateStateUI(data.state);
        document.getElementById("system-env-badge").textContent = `${data.environment} / ${data.broker_type}`;
    } catch (e) {
        console.error("Status fetch error:", e);
    }
}

async function fetchMetrics() {
    try {
        const res = await fetch("/api/metrics");
        const m = await res.json();
        document.getElementById("kpi-winrate").textContent = `${m.win_rate}%`;
        document.getElementById("kpi-pf").textContent = m.profit_factor.toFixed(2);
        document.getElementById("kpi-sharpe").textContent = m.sharpe_ratio.toFixed(2);
        document.getElementById("kpi-dd").textContent = `${m.max_drawdown_percent}%`;
        document.getElementById("kpi-netprofit").textContent = `$${m.net_profit.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
        document.getElementById("kpi-trades-count").textContent = m.total_trades;
    } catch (e) {
        console.error("Metrics error:", e);
    }
}

async function fetchTrades() {
    try {
        const res = await fetch("/api/trades");
        const trades = await res.json();
        const tbody = document.getElementById("trades-tbody");
        tbody.innerHTML = "";
        trades.forEach((t) => {
            const tr = document.createElement("tr");
            const pnlClass = t.net_pnl >= 0 ? "positive" : "negative";
            tr.innerHTML = `
                <td>${t.trade_id}</td>
                <td><strong>${t.side}</strong></td>
                <td>${t.volume.toFixed(2)}</td>
                <td>$${t.entry_price.toFixed(2)}</td>
                <td>$${t.exit_price.toFixed(2)}</td>
                <td>${t.r_multiple >= 0 ? "+" : ""}${t.r_multiple.toFixed(1)}R</td>
                <td class="${pnlClass}"><strong>$${t.net_pnl.toFixed(2)}</strong></td>
                <td><span class="badge badge-state">${t.close_reason}</span></td>
                <td>${new Date(t.close_time).toLocaleTimeString()}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error("Trades error:", e);
    }
}

async function fetchPositions() {
    try {
        const res = await fetch("/api/positions");
        const posList = await res.json();
        const tbody = document.getElementById("positions-tbody");
        tbody.innerHTML = "";
        if (posList.length === 0) {
            tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; color:#64748b;">No active market positions</td></tr>';
            return;
        }
        posList.forEach((p) => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>#${p.ticket}</td>
                <td><strong>${p.side}</strong></td>
                <td>${p.volume.toFixed(2)}</td>
                <td>$${p.entry_price.toFixed(2)}</td>
                <td>$${p.current_price.toFixed(2)}</td>
                <td>$${p.stop_loss.toFixed(2)}</td>
                <td>$${p.take_profit.toFixed(2)}</td>
                <td class="${p.unrealized_pnl >= 0 ? 'positive' : 'negative'}">$${p.unrealized_pnl.toFixed(2)}</td>
                <td>${p.break_even ? 'YES (BE locked)' : 'NO'}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error("Positions error:", e);
    }
}

function updateStateUI(state) {
    const el = document.getElementById("state-badge");
    if (!el) return;
    el.textContent = state;
    if (state.includes("CIRCUIT_BREAKER")) {
        el.className = "badge badge-live";
        el.style.backgroundColor = "rgba(239, 68, 68, 0.2)";
        el.style.color = "#ef4444";
    } else if (state.includes("SCANNING") || state.includes("PENDING")) {
        el.className = "badge badge-state";
    } else {
        el.className = "badge badge-paper";
    }
}

function updateClock() {
    const now = new Date();
    // Approximate New York EST/EDT display
    const nyTimeStr = now.toLocaleTimeString("en-US", { timeZone: "America/New_York", hour12: false });
    document.getElementById("live-clock").textContent = `${nyTimeStr} NY (EST/EDT)`;
}

async function fetchBars(tf) {
    try {
        const res = await fetch(`/api/bars?timeframe=${tf}&count=120`);
        const data = await res.json();
        if (data && data.length > 0) {
            candleSeries.setData(data);
            chart.timeScale().fitContent();
        }
    } catch (e) {
        console.error("Bars fetch error:", e);
    }
}

function setTimeframe(tf, btnElement) {
    currentTimeframe = tf;
    document.querySelectorAll(".btn-tf").forEach((b) => b.classList.remove("active"));
    if (btnElement) btnElement.classList.add("active");
    fetchBars(tf);
}

function switchTab(tabId) {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach((p) => (p.style.display = "none"));

    if (tabId === "trades") {
        document.getElementById("tab-trades-btn").classList.add("active");
        document.getElementById("pane-trades").style.display = "block";
    } else if (tabId === "positions") {
        document.getElementById("tab-pos-btn").classList.add("active");
        document.getElementById("pane-positions").style.display = "block";
    } else if (tabId === "document") {
        document.getElementById("tab-doc-btn").classList.add("active");
        document.getElementById("pane-document").style.display = "block";
    }
}

// 6. Daily Decision Engine & Setups CALL / PUT
async function fetchDailyBriefing() {
    try {
        const res = await fetch("/api/daily-briefing");
        if (!res.ok) throw new Error("Network response was not ok");
        const data = await res.json();
        currentBriefing = data;
        updateBriefingUI(data);
    } catch (e) {
        console.error("Error fetching daily briefing:", e);
    }
}

async function recalculateBriefing() {
    const btn = document.getElementById("btn-recalculate");
    const origText = btn ? btn.textContent : "";
    if (btn) {
        btn.textContent = "⏳ Calculando...";
        btn.disabled = true;
    }

    try {
        const res = await fetch("/api/daily-briefing/recalculate", { method: "POST" });
        if (!res.ok) throw new Error("Failed to recalculate briefing");
        const data = await res.json();
        currentBriefing = data;
        updateBriefingUI(data);
        triggerFlashEffect();
        showToast(`✅ ¡Informe y Setups actualizados a las ${data.calculation_time || "N/A"}! (Spot: $${data.parameters.current_session_price.toFixed(2)} USD)`);

        if (zonesVisible) {
            // Refresh drawn lines
            clearZonesFromChart();
            drawZonesOnChart(data);
        }
    } catch (e) {
        console.error("Error recalculating daily briefing:", e);
        showToast("❌ Error al recalcular informe");
    } finally {
        if (btn) {
            btn.textContent = origText || "🔄 Actualizar Análisis y Setups Ahora";
            btn.disabled = false;
        }
    }
}

function showToast(msg) {
    const t = document.getElementById("toast-notification");
    if (!t) return;
    t.textContent = msg;
    t.style.display = "flex";
    setTimeout(() => {
        t.style.display = "none";
    }, 4500);
}

function triggerFlashEffect() {
    const card = document.querySelector(".decision-card");
    if (card) {
        card.classList.remove("flash-update");
        void card.offsetWidth;
        card.classList.add("flash-update");
    }
    document.querySelectorAll(".setup-box").forEach(b => {
        b.classList.remove("flash-update");
        void b.offsetWidth;
        b.classList.add("flash-update");
    });
}

function openDailyDataModal() {
    const modal = document.getElementById("modal-daily-data");
    if (!modal) return;
    
    if (currentBriefing && currentBriefing.parameters) {
        const p = currentBriefing.parameters;
        setVal("m-open", p.us_open_spot);
        setVal("m-current", p.current_session_price);
        setVal("m-min", p.session_min);
        setVal("m-max", p.session_max);
        setVal("m-atr", p.atr_daily);
        setVal("m-vpoc", p.session_vpoc);
        setVal("m-hour", currentBriefing.calculation_time || "");
    }
    modal.style.display = "flex";
}

function closeDailyDataModal() {
    const modal = document.getElementById("modal-daily-data");
    if (modal) modal.style.display = "none";
}

function setVal(id, val) {
    const el = document.getElementById(id);
    if (el && val !== undefined && val !== null) el.value = val;
}

function useLivePriceInModal() {
    const input = document.getElementById("m-current");
    if (input) {
        input.value = latestLiveBid.toFixed(2);
        showToast(`⚡ Precio actual en vivo cargado: $${latestLiveBid.toFixed(2)} USD`);
    }
}

async function saveAndRecalculateModal() {
    const openPrice = parseFloat(document.getElementById("m-open").value) || null;
    const currentPrice = parseFloat(document.getElementById("m-current").value) || null;
    const minPrice = parseFloat(document.getElementById("m-min").value) || null;
    const maxPrice = parseFloat(document.getElementById("m-max").value) || null;
    const atr = parseFloat(document.getElementById("m-atr").value) || null;
    const vpoc = parseFloat(document.getElementById("m-vpoc").value) || null;
    const hour = document.getElementById("m-hour").value || null;

    const payload = {
        mode: "custom",
        open_price: openPrice,
        current_price: currentPrice,
        min_price: minPrice,
        max_price: maxPrice,
        atr: atr,
        vpoc: vpoc,
        operating_hour: hour
    };

    try {
        const res = await fetch("/api/daily-briefing/recalculate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        if (!res.ok) throw new Error("Recalculate error");
        const data = await res.json();
        currentBriefing = data;
        updateBriefingUI(data);
        triggerFlashEffect();
        closeDailyDataModal();
        showToast(`💾 ¡Parámetros de tu documento guardados y aplicados a las ${data.calculation_time}!`);

        if (zonesVisible) {
            clearZonesFromChart();
            drawZonesOnChart(data);
        }
    } catch (e) {
        console.error("Save modal error:", e);
        showToast("❌ Error al guardar y recalcular");
    }
}

async function resetToLivePure() {
    try {
        const res = await fetch("/api/daily-briefing/recalculate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mode: "reset_live" })
        });
        if (!res.ok) throw new Error("Reset error");
        const data = await res.json();
        currentBriefing = data;
        updateBriefingUI(data);
        triggerFlashEffect();
        closeDailyDataModal();
        showToast("🔄 Restablecido a modo Mercado en Vivo Puro (24/7)");

        if (zonesVisible) {
            clearZonesFromChart();
            drawZonesOnChart(data);
        }
    } catch (e) {
        console.error("Reset live error:", e);
    }
}

function updateBriefingUI(data) {
    if (!data) return;

    // Subtitle timestamp
    const subtitle = document.getElementById("briefing-time-subtitle");
    if (subtitle) {
        subtitle.textContent = `Precios y niveles tomados a las ${data.calculation_time || "N/A"} (${data.session || "Sesión Matutina"})`;
    }

    // SETUP A: CALL
    if (data.call_setup) {
        setText("call-setup-title", data.call_setup.title);
        setText("call-condition", data.call_setup.condition);
        setText("call-entry", `$${data.call_setup.entry_price.toFixed(2)} USD`);
        setText("call-sl", `$${data.call_setup.stop_loss.toFixed(2)} USD`);
        setText("call-tp", `$${data.call_setup.take_profit.toFixed(2)} USD`);
        setText("call-zone", data.call_setup.zone);
        setText("call-obj", data.call_setup.objective);
    }

    // SETUP B: PUT
    if (data.put_setup) {
        setText("put-setup-title", data.put_setup.title);
        setText("put-condition", data.put_setup.condition);
        setText("put-entry", `$${data.put_setup.entry_price.toFixed(2)} USD`);
        setText("put-sl", `$${data.put_setup.stop_loss.toFixed(2)} USD`);
        setText("put-tp", `$${data.put_setup.take_profit.toFixed(2)} USD`);
        setText("put-zone", data.put_setup.zone);
        setText("put-obj", data.put_setup.objective);
    }

    // Parametros Operativos
    if (data.parameters) {
        setText("p-open", `$${data.parameters.us_open_spot.toFixed(2)} USD`);
        setText("p-current", `$${data.parameters.current_session_price.toFixed(2)} USD`);
        setText("p-range", `$${data.parameters.session_min.toFixed(2)} - $${data.parameters.session_max.toFixed(2)} USD`);
        setText("p-traversed", `$${data.parameters.range_traversed.toFixed(2)} USD`);
        setText("p-atr", `$${data.parameters.atr_daily.toFixed(2)} USD`);
        setText("p-consumption", `${data.parameters.range_consumption_pct.toFixed(1)}%`);
        setText("p-vpoc", `$${data.parameters.session_vpoc.toFixed(2)} USD`);
    }

    // Niveles Pivote
    if (data.pivots) {
        setText("piv-r3", `$${data.pivots.r3.toFixed(2)}`);
        setText("piv-r2", `$${data.pivots.r2.toFixed(2)}`);
        setText("piv-r1", `$${data.pivots.r1.toFixed(2)}`);
        setText("piv-pp", `$${data.pivots.pp.toFixed(2)}`);
        setText("piv-s1", `$${data.pivots.s1.toFixed(2)}`);
        setText("piv-s2", `$${data.pivots.s2.toFixed(2)}`);
        setText("piv-s3", `$${data.pivots.s3.toFixed(2)}`);
    }

    // COT Institucional
    if (data.cot) {
        setText("cot-longs", data.cot.longs.toLocaleString());
        setText("cot-shorts", data.cot.shorts.toLocaleString());
        setText("cot-net", `+${data.cot.net.toLocaleString()} (${data.cot.change})`);
        setText("cot-interp", data.cot.interpretation);
    }

    // Documento Operativo Completo
    const docEl = document.getElementById("daily-document-content");
    if (docEl && data.markdown_document) {
        docEl.innerHTML = formatMarkdownToHTML(data.markdown_document);
    }
}

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

function clearZonesFromChart() {
    if (callEntryLine) { candleSeries.removePriceLine(callEntryLine); callEntryLine = null; }
    if (callSLLine) { candleSeries.removePriceLine(callSLLine); callSLLine = null; }
    if (callTPLine) { candleSeries.removePriceLine(callTPLine); callTPLine = null; }
    if (putEntryLine) { candleSeries.removePriceLine(putEntryLine); putEntryLine = null; }
    if (putSLLine) { candleSeries.removePriceLine(putSLLine); putSLLine = null; }
    if (putTPLine) { candleSeries.removePriceLine(putTPLine); putTPLine = null; }
    if (pivotPPLine) { candleSeries.removePriceLine(pivotPPLine); pivotPPLine = null; }
}

function drawZonesOnChart(data) {
    if (!candleSeries || !data) return;

    if (data.call_setup) {
        callEntryLine = candleSeries.createPriceLine({
            price: data.call_setup.entry_price,
            color: "#10b981",
            lineWidth: 2,
            lineStyle: LightweightCharts.LineStyle.Solid,
            axisLabelVisible: true,
            title: "CALL ENTRY",
        });
        callSLLine = candleSeries.createPriceLine({
            price: data.call_setup.stop_loss,
            color: "#ef4444",
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            axisLabelVisible: true,
            title: "CALL SL",
        });
        callTPLine = candleSeries.createPriceLine({
            price: data.call_setup.take_profit,
            color: "#10b981",
            lineWidth: 2,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            axisLabelVisible: true,
            title: "CALL TP (1:3)",
        });
    }

    if (data.put_setup) {
        putEntryLine = candleSeries.createPriceLine({
            price: data.put_setup.entry_price,
            color: "#f59e0b",
            lineWidth: 2,
            lineStyle: LightweightCharts.LineStyle.Solid,
            axisLabelVisible: true,
            title: "PUT ENTRY",
        });
        putSLLine = candleSeries.createPriceLine({
            price: data.put_setup.stop_loss,
            color: "#ef4444",
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            axisLabelVisible: true,
            title: "PUT SL",
        });
        putTPLine = candleSeries.createPriceLine({
            price: data.put_setup.take_profit,
            color: "#06b6d4",
            lineWidth: 2,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            axisLabelVisible: true,
            title: "PUT TP (1:3)",
        });
    }

    if (data.pivots && data.pivots.pp) {
        pivotPPLine = candleSeries.createPriceLine({
            price: data.pivots.pp,
            color: "#8b5cf6",
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.SparseDotted,
            axisLabelVisible: true,
            title: "PIVOT PP",
        });
    }
}

function toggleZonesOnChart() {
    if (zonesVisible) {
        clearZonesFromChart();
        zonesVisible = false;
    } else {
        if (!currentBriefing) {
            fetchDailyBriefing().then(() => {
                if (currentBriefing) {
                    drawZonesOnChart(currentBriefing);
                    zonesVisible = true;
                }
            });
        } else {
            drawZonesOnChart(currentBriefing);
            zonesVisible = true;
        }
    }
}

function formatMarkdownToHTML(md) {
    if (!md) return "";
    let html = md
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

    // Headings
    html = html.replace(/^### (.*$)/gim, '<h3 style="color:#d4af37; margin:14px 0 6px 0; font-size:15px;">$1</h3>');
    html = html.replace(/^## (.*$)/gim, '<h2 style="color:#d4af37; margin:16px 0 8px 0; font-size:16px; border-bottom:1px solid #232c45; padding-bottom:4px;">$1</h2>');
    html = html.replace(/^# (.*$)/gim, '<h1 style="color:#d4af37; margin:18px 0 10px 0; font-size:18px; border-bottom:1px solid #d4af37; padding-bottom:6px;">$1</h1>');

    // Bold
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong style="color:#ffffff;">$1</strong>');

    // Lists
    html = html.replace(/^\s*-\s+(.*$)/gim, '<div style="margin-left:14px; margin-bottom:4px;">• $1</div>');

    // Line breaks
    html = html.replace(/\n\n/g, '<div style="height:8px;"></div>');
    html = html.replace(/\n/g, "<br>");

    return html;
}
