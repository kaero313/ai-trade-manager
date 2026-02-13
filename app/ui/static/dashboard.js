(() => {
  const REFRESH_MS = 15000;
  const numberFmt = new Intl.NumberFormat("ko-KR");
  const pctFmt = new Intl.NumberFormat("ko-KR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  const byId = (id) => document.getElementById(id);
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

  let latestSnapshot = null;
  let toggleInFlight = false;

  const formatKrw = (value) => {
    if (!Number.isFinite(value)) {
      return "KRW -";
    }
    return `KRW ${numberFmt.format(Math.round(value))}`;
  };

  const formatSignedKrw = (value) => {
    if (!Number.isFinite(value)) {
      return "-";
    }
    const sign = value > 0 ? "+" : "";
    return `${sign}KRW ${numberFmt.format(Math.round(value))}`;
  };

  const formatPct = (value) => {
    if (!Number.isFinite(value)) {
      return "-";
    }
    const sign = value > 0 ? "+" : "";
    return `${sign}${pctFmt.format(value)}%`;
  };

  const formatQty = (value) => {
    if (!Number.isFinite(value)) {
      return "-";
    }
    return Number(value).toFixed(8).replace(/\.?0+$/, "");
  };

  const setTrendClass = (el, value) => {
    if (!el) {
      return;
    }
    el.classList.remove("up", "down");
    if (Number.isFinite(value) && value > 0) {
      el.classList.add("up");
    } else if (Number.isFinite(value) && value < 0) {
      el.classList.add("down");
    }
  };

  const renderPulse = (symbols) => {
    const list = byId("pulseList");
    const meta = byId("pulseMeta");
    if (!list) {
      return;
    }

    list.innerHTML = "";
    if (!Array.isArray(symbols) || symbols.length === 0) {
      const li = document.createElement("li");
      li.innerHTML =
        '<span class="mono">-</span><div class="pulse-track"><span style="width:0%;"></span></div><span class="pulse-change">-</span>';
      list.appendChild(li);
      if (meta) {
        meta.textContent = "Top 0";
      }
      return;
    }

    symbols.forEach((item) => {
      const li = document.createElement("li");
      const market = document.createElement("span");
      market.className = "mono";
      market.textContent = item.market || "-";

      const track = document.createElement("div");
      track.className = "pulse-track";
      const fill = document.createElement("span");
      const intensity = clamp(Number(item.intensity_pct || 0), 0, 100);
      fill.style.width = `${intensity}%`;
      track.appendChild(fill);

      const change = document.createElement("span");
      change.className = "pulse-change";
      const changePct = Number(item.change_pct);
      change.textContent = formatPct(changePct);
      setTrendClass(change, changePct);

      li.appendChild(market);
      li.appendChild(track);
      li.appendChild(change);
      list.appendChild(li);
    });

    if (meta) {
      meta.textContent = `Top ${symbols.length}`;
    }
  };

  const renderThroughput = (throughput) => {
    const bars = byId("throughputBars");
    if (!bars) {
      return;
    }

    const buckets = Array.isArray(throughput) ? throughput.slice(0, 12) : [];
    while (buckets.length < 12) {
      buckets.push(0);
    }

    const maxValue = Math.max(...buckets, 1);
    bars.innerHTML = "";
    buckets.forEach((value) => {
      const bar = document.createElement("span");
      const height = value > 0 ? clamp((value / maxValue) * 100, 12, 100) : 12;
      bar.style.height = `${Math.round(height)}%`;
      bar.title = `${value} orders`;
      bars.appendChild(bar);
    });
  };

  const renderAlerts = (alerts) => {
    const list = byId("alertsList");
    if (!list) {
      return;
    }
    list.innerHTML = "";

    const rows = Array.isArray(alerts) && alerts.length > 0 ? alerts : [
      { level: "ok", title: "Stable", message: "No critical alerts.", minutes_ago: null },
    ];

    rows.forEach((item) => {
      const level = ["ok", "warn", "danger"].includes(item.level) ? item.level : "ok";
      const li = document.createElement("li");
      li.className = `alert-item ${level}`;

      const main = document.createElement("div");
      main.className = "alert-main";
      const title = document.createElement("strong");
      title.textContent = item.title || "Alert";
      const msg = document.createElement("p");
      msg.textContent = item.message || "-";
      main.appendChild(title);
      main.appendChild(msg);

      const age = document.createElement("span");
      age.className = "mono";
      if (Number.isFinite(item.minutes_ago)) {
        age.textContent = `${Math.max(0, item.minutes_ago)}m`;
      } else {
        age.textContent = "now";
      }

      li.appendChild(main);
      li.appendChild(age);
      list.appendChild(li);
    });
  };

  const renderPositions = (positions, maxPositions) => {
    const tbody = byId("positionsBody");
    const meta = byId("positionsMeta");
    if (!tbody) {
      return;
    }

    tbody.innerHTML = "";
    const rows = Array.isArray(positions) ? positions : [];
    if (meta) {
      meta.textContent = `${rows.length} / ${Number.isFinite(maxPositions) ? maxPositions : 0}`;
    }

    if (rows.length === 0) {
      const tr = document.createElement("tr");
      tr.innerHTML = '<td class="mono" colspan="5">No open positions.</td>';
      tbody.appendChild(tr);
      return;
    }

    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const pnlPct = Number(row.pnl_pct);

      const symbolTd = document.createElement("td");
      symbolTd.className = "mono";
      symbolTd.textContent = row.market || "-";

      const qtyTd = document.createElement("td");
      qtyTd.className = "mono";
      qtyTd.textContent = formatQty(Number(row.qty));

      const avgTd = document.createElement("td");
      avgTd.className = "mono";
      avgTd.textContent = Number.isFinite(Number(row.avg_price))
        ? numberFmt.format(Math.round(Number(row.avg_price)))
        : "-";

      const nowTd = document.createElement("td");
      nowTd.className = "mono";
      nowTd.textContent = Number.isFinite(Number(row.now_price))
        ? numberFmt.format(Math.round(Number(row.now_price)))
        : "-";

      const pnlTd = document.createElement("td");
      pnlTd.className = "mono";
      pnlTd.textContent = formatPct(pnlPct);
      setTrendClass(pnlTd, pnlPct);

      tr.appendChild(symbolTd);
      tr.appendChild(qtyTd);
      tr.appendChild(avgTd);
      tr.appendChild(nowTd);
      tr.appendChild(pnlTd);
      tbody.appendChild(tr);
    });
  };

  const renderRisk = (risk) => {
    const usage = Number(risk.capital_usage_pct || 0);
    const limit = Number(risk.capital_limit_pct || 0);
    const floatingLoss = Number(risk.floating_loss_pct || 0);
    const maxDailyLoss = Number(risk.max_daily_loss_pct || 0);
    const usedPositions = Number(risk.used_positions || 0);
    const maxPositions = Number(risk.max_positions || 0);

    const usageText = byId("riskCapitalText");
    const usageBar = byId("riskCapitalBar");
    const dailyText = byId("riskDailyLossText");
    const dailyBar = byId("riskDailyLossBar");
    const posText = byId("riskPositionText");
    const posBar = byId("riskPositionBar");

    if (usageText) {
      usageText.textContent = `${pctFmt.format(usage)}% / ${pctFmt.format(limit)}%`;
    }
    if (usageBar) {
      usageBar.style.width = `${clamp(limit > 0 ? (usage / limit) * 100 : 0, 0, 100)}%`;
    }
    if (dailyText) {
      dailyText.textContent = `${pctFmt.format(floatingLoss)}% / ${pctFmt.format(maxDailyLoss)}%`;
    }
    if (dailyBar) {
      dailyBar.style.width = `${clamp(maxDailyLoss > 0 ? (floatingLoss / maxDailyLoss) * 100 : 0, 0, 100)}%`;
    }
    if (posText) {
      posText.textContent = `${usedPositions} / ${maxPositions}`;
    }
    if (posBar) {
      posBar.style.width = `${clamp(maxPositions > 0 ? (usedPositions / maxPositions) * 100 : 0, 0, 100)}%`;
    }
  };

  const renderSnapshot = (snapshot) => {
    latestSnapshot = snapshot;

    const strategyChip = byId("strategyChip");
    if (strategyChip) {
      strategyChip.textContent = snapshot.strategy_text || strategyChip.textContent;
    }

    const scheduleLabel = byId("scheduleLabel");
    if (scheduleLabel) {
      scheduleLabel.textContent = snapshot.schedule_text || "KST 24H";
    }

    const syncLabel = byId("lastSyncLabel");
    if (syncLabel) {
      syncLabel.textContent = `Last Sync ${snapshot.synced_at || "-"}`;
    }

    const metrics = snapshot.metrics || {};
    const status = snapshot.status || {};
    const risk = snapshot.risk || {};

    const totalAssetValue = byId("totalAssetValue");
    if (totalAssetValue) {
      totalAssetValue.textContent = formatKrw(Number(metrics.total_asset_krw));
    }
    const totalAssetDelta = byId("totalAssetDelta");
    if (totalAssetDelta) {
      const pnl = Number(metrics.unrealized_pnl_krw);
      totalAssetDelta.textContent = formatSignedKrw(pnl);
      setTrendClass(totalAssetDelta, pnl);
    }

    const dailyPnlValue = byId("dailyPnlValue");
    if (dailyPnlValue) {
      const pnl = Number(metrics.daily_realized_pnl_krw);
      dailyPnlValue.textContent = formatSignedKrw(pnl);
      setTrendClass(dailyPnlValue, pnl);
    }

    const dailyPnlWins = byId("dailyPnlWins");
    if (dailyPnlWins) {
      dailyPnlWins.textContent = `${Number(metrics.wins || 0)} Wins`;
    }
    const dailyPnlLosses = byId("dailyPnlLosses");
    if (dailyPnlLosses) {
      dailyPnlLosses.textContent = `${Number(metrics.losses || 0)} Loss`;
    }

    const capitalUsage = Number(metrics.capital_usage_pct || 0);
    const capitalLimit = Number(metrics.capital_limit_pct || 0);
    const capitalUsageValue = byId("capitalUsageValue");
    if (capitalUsageValue) {
      capitalUsageValue.textContent = `${pctFmt.format(capitalUsage)}%`;
    }
    const capitalUsageLimit = byId("capitalUsageLimit");
    if (capitalUsageLimit) {
      capitalUsageLimit.textContent = `Limit ${pctFmt.format(capitalLimit)}%`;
    }
    const capitalUsageState = byId("capitalUsageState");
    if (capitalUsageState) {
      let stateText = "Safe";
      if (capitalLimit > 0 && capitalUsage >= capitalLimit) {
        stateText = "Over";
      } else if (capitalLimit > 0 && capitalUsage >= capitalLimit * 0.8) {
        stateText = "Warning";
      }
      capitalUsageState.textContent = stateText;
    }

    const botStateValue = byId("botStateValue");
    const running = Boolean(status.running);
    if (botStateValue) {
      botStateValue.textContent = running ? "Running" : "Stopped";
    }
    const botHeartbeat = byId("botHeartbeatValue");
    if (botHeartbeat) {
      const age = Number(status.heartbeat_age_sec);
      botHeartbeat.textContent = Number.isFinite(age) ? `Heartbeat ${age}s` : "Heartbeat -";
    }
    const botActionBtn = byId("botActionBtn");
    if (botActionBtn) {
      botActionBtn.textContent = running ? "Pause" : "Run";
    }

    renderPulse(snapshot.symbols || []);
    renderThroughput(snapshot.throughput || []);
    renderAlerts(snapshot.alerts || []);
    renderPositions(snapshot.positions || [], Number(risk.max_positions || 0));
    renderRisk(risk);
  };

  const renderLoadError = (error) => {
    console.error(error);
    const syncLabel = byId("lastSyncLabel");
    if (syncLabel) {
      syncLabel.textContent = "Last Sync failed";
    }
    renderAlerts([
      {
        level: "danger",
        title: "Dashboard API Error",
        message: "Failed to fetch /api/dashboard",
        minutes_ago: null,
      },
    ]);
  };

  const fetchSnapshot = async () => {
    const response = await fetch("/api/dashboard", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
  };

  const refresh = async () => {
    try {
      const snapshot = await fetchSnapshot();
      renderSnapshot(snapshot);
    } catch (error) {
      renderLoadError(error);
    }
  };

  const toggleBot = async () => {
    if (toggleInFlight) {
      return;
    }
    const running = Boolean(latestSnapshot?.status?.running);
    const endpoint = running ? "/api/bot/stop" : "/api/bot/start";
    const btn = byId("botActionBtn");

    try {
      toggleInFlight = true;
      if (btn) {
        btn.disabled = true;
      }
      await fetch(endpoint, { method: "POST" });
      await refresh();
    } catch (error) {
      renderLoadError(error);
    } finally {
      toggleInFlight = false;
      if (btn) {
        btn.disabled = false;
      }
    }
  };

  const botActionBtn = byId("botActionBtn");
  if (botActionBtn) {
    botActionBtn.addEventListener("click", toggleBot);
  }

  const settingsBtn = byId("settingsBtn");
  if (settingsBtn) {
    settingsBtn.addEventListener("click", () => {
      window.location.href = "/settings";
    });
  }

  refresh();
  const timerId = window.setInterval(refresh, REFRESH_MS);
  window.addEventListener("beforeunload", () => window.clearInterval(timerId));
})();
