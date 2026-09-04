const money = (n) => new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 }).format(Number(n));
const escapeHtml = (value) => String(value).replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
let latestPlanSymbols = [];
let latestJournalRows = [];
let currentPlansBySymbol = {};
let selectedPlanWindow = "";
let selectedStrategy = "NEXT_DAY";
let selectedJournalWindow = "CLOSE_FINAL";
const windowLabels = {OPEN_0930:"OPEN 09:30",MIDDAY_1130:"MIDDAY 11:30",CLOSE_FINAL:"CLOSE FINAL",LEGACY:"LEGACY"};
const formatDate = (d) => new Date(d).toLocaleDateString("id-ID", { day: 'numeric', month: 'long', year: 'numeric' });
const formatDateTime = (d) => new Date(d).toLocaleString("id-ID", { day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' });
const signedPct = (value) => `${Number(value) >= 0 ? "+" : ""}${(Number(value || 0) * 100).toFixed(2)}%`;

function technicalEvidence(plan) {
  const i = plan.indicators || {}, s = plan.scan_settings || {};
  const rows = [
    ["Momentum 20D", signedPct(i.momentum_20d), Number(i.momentum_20d) > 0, "Perubahan harga dibanding 20 hari bursa lalu"],
    ["Relative volume", `${Number(i.relative_volume || 0).toFixed(2)}×`, Number(i.relative_volume) >= 1.2, "Volume terakhir ÷ median volume 20 hari"],
    ["Jarak dari VWAP 20D", signedPct(i.distance_to_vwap), Number(i.distance_to_vwap) >= 0, "Harga terhadap harga rata-rata tertimbang volume"],
    ["ATR 14D", `${(Number(i.atr_percent || 0) * 100).toFixed(2)}%`, Number(i.atr_percent) <= .06, "Ukuran volatilitas untuk menentukan stop"],
    ["Liquidity percentile", `${Number(i.liquidity_score || 0).toFixed(1)}/100`, Number(i.liquidity_score) >= 55, `Relatif seluruh IDX · median Rp${money(i.median_turnover_20d || 0)}/hari`],
    ["Gap", signedPct(i.gap_percent), Math.abs(Number(i.gap_percent)) < .02, "Selisih open terakhir terhadap close sebelumnya"],
    ["RSI 14", Number(i.rsi_14 || 0).toFixed(1), Number(i.rsi_14) <= 78, "Di atas 70 mulai panas; >78 diveto"],
    ["Jarak SMA20", signedPct(i.distance_to_sma20), Number(i.distance_to_sma20) <= .15, "Terlalu jauh meningkatkan risiko koreksi"],
    ["Green streak", `${Number(i.consecutive_green_days || 0)} hari`, Number(i.consecutive_green_days) <= 6, "Mencegah mengejar kenaikan beruntun"],
    // Phase 1: Broker Flow
    ["Broker Flow Score", i.broker_flow_score != null ? `${Number(i.broker_flow_score).toFixed(1)}/100` : "—",
      i.broker_flow_score != null && i.broker_flow_score !== 50, i.broker_flow_source === "idx_bandarmologi" ? "🏦 Real IDX bandarmologi data" : "🔴 Placeholder — belum ada data broker IDX"],
    // Phase 3: Foreign Flow
    ["Foreign Flow", i.foreign_flow_signal || "NEUTRAL",
      i.foreign_flow_signal === "ACCUMULATE", i.foreign_flow_signal === "ACCUMULATE" ? "🌏 Asing net beli 3+ hari dari 5" : i.foreign_flow_signal === "DISTRIBUTE" ? "⚠️ Asing net jual dominan" : "Netral — belum ada tren jelas"],
    // Phase 2: Fundamentals
    ["PER", i.per != null ? Number(i.per).toFixed(1) + "×" : "—",
      i.per != null && i.per < 20, i.per != null ? (i.per < 12 ? "Value territory (PER < 12)" : i.per < 20 ? "Normal range" : "Premium valuation") : "Data belum disync"],
    ["ROE", i.roe != null ? Number(i.roe).toFixed(1) + "%" : "—",
      i.roe != null && i.roe >= 15, i.roe != null ? (i.roe >= 20 ? "Excellent profitability" : i.roe >= 15 ? "Good ROE" : "Below average") : "Data belum disync"],
    ["DER", i.der != null ? Number(i.der).toFixed(2) + "×" : "—",
      i.der == null || i.der <= 3.0, i.der != null ? (i.der > 3.0 ? "🔴 Over-leveraged — dapat diveto engine" : i.der > 1.5 ? "Moderate leverage" : "Low leverage") : "Data belum disync"],
  ];
  const checks = Object.entries(plan.checks || {}).map(([name, pass]) => `<span class="evidence-check ${pass ? "pass" : "fail"}">${pass ? "✓" : "×"} ${escapeHtml(name.replaceAll("_", " "))}</span>`).join("");
  return `<div class="evidence-heading"><div><strong>Technical evidence at scan</strong><small>Snapshot tersimpan · bukan perubahan retroaktif</small></div><b>${Number(plan.ranking_score || 0).toFixed(2)} RANK</b></div>
    <div class="evidence-grid">${rows.map(([label,value,pass,help]) => `<div class="evidence-item ${pass ? "positive" : "negative"}"><span>${label}</span><b>${value}</b><small>${help}</small></div>`).join("")}</div>
    <div class="evidence-formula"><b>Mengapa masuk kandidat?</b><span>Ranking = Quant ${Number(plan.score).toFixed(1)} × 45% + ML ${(Number(plan.confidence) * 100).toFixed(1)}% × 55% = <strong>${Number(plan.ranking_score || 0).toFixed(2)}</strong>. Status ${plan.status} menentukan apakah actionable.</span></div>
    <div class="evidence-checks">${checks}</div>
    <div class="evidence-settings"><b>Setting scan:</b> Quant ≥ ${s.min_signal_score ?? "—"} · ML ≥ ${s.min_ml_probability != null ? Math.round(s.min_ml_probability * 100) + "%" : "—"} · R/R ≥ ${s.min_risk_reward ?? "—"} · Risk ${s.max_risk_per_trade != null ? (s.max_risk_per_trade * 100).toFixed(1) + "%" : "—"}</div>`;
}

async function load() {
  try {
    const params = new URLSearchParams({strategy:selectedStrategy});
    if (selectedPlanWindow) params.set("window",selectedPlanWindow);
    const response = await fetch(`/api/today/?${params}`);
    const data = await response.json();
    selectedStrategy = data.selected_strategy;
    const strategyLabels={NEXT_DAY:"DAILY / NEXT DAY",SWING:"SWING 3–5D",SCALP:"SCALP INTRADAY"};
    document.querySelector("#strategy-tabs").innerHTML=data.available_strategies.map(value=>`<button type="button" data-strategy="${value}" class="${value===selectedStrategy?"active":""}">${strategyLabels[value]}${value==="SCALP"&&!data.scalp_data_ready?' · COLLECTING':''}</button>`).join("");
    document.querySelectorAll("[data-strategy]").forEach(button=>button.onclick=()=>{selectedStrategy=button.dataset.strategy;selectedPlanWindow="";load();loadSystem();});
    selectedPlanWindow = data.selected_window;
    document.querySelector("#playbook-windows").innerHTML = ["OPEN_0930","MIDDAY_1130","CLOSE_FINAL"].map(value => `<button type="button" data-plan-window="${value}" class="${value === selectedPlanWindow ? "active" : ""}" ${data.available_windows.includes(value) ? "" : "disabled"}>${windowLabels[value]}</button>`).join("");
    document.querySelectorAll("[data-plan-window]").forEach(button => button.onclick = () => { selectedPlanWindow=button.dataset.planWindow; load(); });
    currentPlansBySymbol = Object.fromEntries(data.plans.map((plan) => [plan.symbol, plan]));
    document.querySelector("#regime").textContent = data.regime;
    const regimeCard = document.querySelector("#regime-card");
    regimeCard.className = `metric-state regime-${data.regime.toLowerCase()}`;
    document.querySelector("#regime-note").textContent = data.regime === "BULLISH" ? "Trend IHSG above SMA20 & SMA50" : data.regime === "HIGH_RISK" ? "Trend IHSG below SMA20 & SMA50" : "IHSG trend is mixed / neutral";
    document.querySelector("#active").textContent = data.plans.length;
    document.querySelector("#source").textContent = data.data.source.toUpperCase();
    document.querySelector("#freshness").textContent = data.data.freshest_candle_at
      ? `Latest candle ${formatDateTime(data.data.freshest_candle_at)}`
      : "No verified scan yet";
    document.querySelector("#subtitle").textContent = `${data.session.replaceAll("_", " ")} · ${new Date(data.date).toLocaleDateString("id-ID", { dateStyle: "full" })}`;
    document.querySelector("#plans").innerHTML = data.plans.length
      ? data.plans.map((plan, index) => `<article class="plan" data-plan-symbol="${escapeHtml(plan.symbol)}">
          <div class="ticker"><span class="rank">0${index + 1}</span><strong>${plan.symbol}</strong><span class="badge ${plan.status}">${plan.status}</span></div>
          <div class="plan-quant"><small>QUANT SCORE</small><strong>${plan.score}</strong><span>/100</span></div>
          <div class="live-price-box"><span><i></i> LIVE PRICE</span><strong data-current-price>Updating…</strong><small data-current-move>Vs Prev · —</small></div>
          <div class="levels"><span><small>ENTRY</small><b>${money(plan.entry_low)}–${money(plan.entry_high)}</b></span><span><small>STOP</small><b>${money(plan.stop_loss)}</b></span><span><small>TARGET</small><b>${money(plan.take_profit)}</b></span><span><small>R/R</small><b>${plan.risk_reward}</b></span></div>
          <div class="score"><strong>${Math.round(plan.confidence * 100)}%</strong><small> ML PROBABILITY</small><div class="checks">${Object.values(plan.checks).map((passed) => `<i class="${passed ? "ok" : ""}"></i>`).join("")}</div></div><div class="mini-chart" id="mini-${plan.symbol}"></div>
          <div class="insight-actions"><button type="button" class="technical-toggle" aria-expanded="false">⌁ Technical Evidence</button><button type="button" class="ai-insight-toggle" data-plan-id="${plan.id}" aria-expanded="false">✦ AI Insight</button><div class="paper-order-control"><button type="button" data-lot-step="-1">−</button><label><input type="number" class="paper-lots" min="1" max="${Math.max(1, Math.floor(plan.position_size / 100))}" value="1"><span>LOT</span></label><button type="button" data-lot-step="1">＋</button><button type="button" class="paper-buy ${plan.status === "READY" ? "" : "experimental"}" data-plan-id="${plan.id}">${plan.decision_window === "CLOSE_FINAL" ? "Queue Tomorrow" : (plan.status === "READY" ? "Paper Buy" : "Paper Test")}</button><small class="paper-estimate">≈ ${money(Number(plan.entry_high) * 100)}</small></div><small>${plan.commentary ? "Saved analysis" : "Call 9Router on demand"}</small></div>
          <div class="technical-evidence" hidden>${technicalEvidence(plan)}</div>
          <div class="plan-commentary" hidden><div class="insight-heading"><strong>AI Insight</strong><span>AI explains · Quant & risk stay authoritative</span></div><div class="insight-content">${plan.commentary ? marked.parse(plan.commentary) : ""}</div></div>
        </article>`).join("")
      : `<div class="empty">${selectedStrategy==="SCALP"&&!data.scalp_data_ready?"SCALP sedang mengumpulkan dataset 5 menit. Sistem tidak akan membuat probabilitas intraday palsu.":"Belum ada hasil untuk strategi ini. Jalankan market scan."}</div>`;
    if (data.plans.length && !data.plans.some((plan) => plan.status === "READY")) {
      document.querySelector("#plans").insertAdjacentHTML("afterbegin", '<div class="no-trade-banner"><b>NO TRADE</b><span>Tidak ada kandidat yang melewati seluruh ML, backtest, intraday, dan risk gate. Daftar di bawah hanya watchlist.</span></div>');
    }
    document.querySelectorAll(".plan").forEach((card, index) => {
      card.onclick = () => loadChart(data.plans[index].symbol);
    });
    if (data.plans.length) loadChart(data.plans[0].symbol);
    data.plans.forEach((plan) => loadMiniChart(plan.symbol));
    latestPlanSymbols = data.plans.map((plan) => plan.symbol);
    sendMarketSubscription();
    bindInsightButtons();
    bindTechnicalButtons();
    bindPaperButtons();
    loadDemoAccount();
    renderBandarmologi(data.plans);
    // Update IDX data metric card
    const idxStatus = document.querySelector("#idx-data-status");
    const idxNote = document.querySelector("#idx-data-note");
    if (idxStatus && data.plans.length) {
      const hasRealBF = data.plans.some(p => p.indicators?.broker_flow_source === "idx_bandarmologi");
      const hasFF = data.plans.some(p => p.indicators?.foreign_flow_signal && p.indicators.foreign_flow_signal !== "NEUTRAL");
      const hasFund = data.plans.some(p => p.indicators?.per != null);
      const count = [hasRealBF, hasFF, hasFund].filter(Boolean).length;
      idxStatus.textContent = count === 0 ? "PENDING" : count === 3 ? "LIVE" : `${count}/3`;
      idxStatus.style.color = count === 0 ? "var(--text-muted)" : count === 3 ? "var(--accent-lime)" : "var(--accent-gold)";
      if (idxNote) idxNote.textContent = [hasRealBF?"🏦 Broker":"❌ Broker", hasFF?"🌏 Asing":"❌ Asing", hasFund?"📊 Fund":"❌ Fund"].join(" · ");
    }
  } catch (_error) {
    document.querySelector("#live").textContent = "OFFLINE";
  }
}

function renderBandarmologi(plans) {
  const container = document.querySelector("#bandarmologi-cards");
  if (!container) return;
  if (!plans || plans.length === 0) {
    container.innerHTML = '<div class="empty">Run a market scan to load bandarmologi data.</div>';
    return;
  }
  container.innerHTML = plans.map(plan => {
    const i = plan.indicators || {};
    const bf = i.broker_flow_score != null ? Number(i.broker_flow_score) : null;
    const bfClass = bf !== null && bf !== 50 ? (bf >= 70 ? "bandar-high" : bf >= 50 ? "bandar-mid" : "bandar-low") : "bandar-neutral";
    const cr1 = i.cr1 != null ? `${Number(i.cr1).toFixed(1)}%` : "—";
    const cr3 = i.cr3 != null ? `${Number(i.cr3).toFixed(1)}%` : "—";
    const cr5 = i.cr5 != null ? `${Number(i.cr5).toFixed(1)}%` : "—";
    const ffSig = i.foreign_flow_signal || "NEUTRAL";
    const ffEmoji = ffSig === "ACCUMULATE" ? "🟢" : ffSig === "DISTRIBUTE" ? "🔴" : "🟡";
    const der = i.der != null ? Number(i.der).toFixed(2) + "×" : "—";
    const roe = i.roe != null ? Number(i.roe).toFixed(1) + "%" : "—";
    const per = i.per != null ? Number(i.per).toFixed(1) + "×" : "—";
    const auditOk = !plan.checks?.audit_risky;
    const isRealData = i.broker_flow_source === "idx_bandarmologi" || i.broker_flow_source === "stockbit";
    return `<div class="bandar-card ${bfClass}">
      <div class="bandar-card-header">
        <span class="bandar-symbol">${plan.symbol}</span>
        <span class="badge ${plan.status}">${plan.status}</span>
        ${isRealData ? '<span class="bandar-live-dot" title="Real IDX/Stockbit data">●</span>' : '<span class="bandar-pending-dot" title="No broker data yet">○</span>'}
      </div>
      <div class="bandar-score">${bf !== null ? Math.round(bf) : "—"}<small>/100</small></div>
      <div class="bandar-label">Institutional Score</div>
      <div class="bandar-cr-row">
        <div class="bandar-cr"><span>CR1</span><b>${cr1}</b></div>
        <div class="bandar-cr"><span>CR3</span><b>${cr3}</b></div>
        <div class="bandar-cr"><span>CR5</span><b>${cr5}</b></div>
      </div>
      <div class="bandar-meta">
        <span>${ffEmoji} Asing: <b>${ffSig}</b></span>
        <span>PER <b>${per}</b></span>
        <span>ROE <b>${roe}</b></span>
        <span>DER <b class="${i.der != null && i.der > 3 ? 'price-down' : ''}">${der}</b></span>
      </div>
      ${i.top_brokers && i.top_brokers.length > 0 ? `
      <div class="bandar-top-brokers" style="margin-top: 12px; font-size: 11px; border-top: 1px solid var(--border); padding-top: 8px;">
        <div style="color: var(--text-muted); margin-bottom: 4px;">Top Brokers (Net)</div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap;">
          ${i.top_brokers.slice(0, 3).map(b => `<span title="Net: ${b.net.toLocaleString()} IDR"><b>${b.code}</b> <span class="${b.net > 0 ? 'price-up' : 'price-down'}">${b.net > 0 ? 'B' : 'S'}</span></span>`).join('')}
        </div>
      </div>
      ` : ''}
    </div>`;
  }).join("");
}



function bindPaperButtons() {
  document.querySelectorAll(".paper-order-control").forEach((control) => {
    const input = control.querySelector(".paper-lots"), estimate = control.querySelector(".paper-estimate"), card = control.closest(".plan");
    const update = () => {
      input.value = Math.max(Number(input.min), Math.min(Number(input.max), Number(input.value) || 1));
      const plan = currentPlansBySymbol[card.dataset.planSymbol];
      estimate.textContent = `≈ ${money(Number(plan?.entry_high || 0) * 100 * Number(input.value))}`;
    };
    control.querySelectorAll("[data-lot-step]").forEach(step => step.onclick = (event) => { event.preventDefault(); event.stopPropagation(); input.value = Number(input.value) + Number(step.dataset.lotStep); update(); });
    input.onclick = (event) => event.stopPropagation(); input.onchange = update; input.oninput = update;
  });
  document.querySelectorAll(".paper-buy").forEach((button) => {
    button.onclick = async (event) => {
      event.preventDefault(); event.stopPropagation(); button.disabled = true;
      try {
        const lots = Number(button.closest(".paper-order-control").querySelector(".paper-lots").value);
        const response = await fetch(`/api/demo-buy/${button.dataset.planId}/`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({lots})});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Paper order rejected");
        await loadDemoAccount(); button.textContent = data.queued ? `⏳ Queued ${data.lots} Lot` : `✓ Filled ${data.lots} Lot`;
      } catch (error) { button.textContent = error.message; button.classList.add("paper-error"); }
      finally { button.disabled = false; }
    };
  });
}

let paperAccountState = null;
async function loadDemoAccount() {
  const response = await fetch("/api/demo-account/"); const data = await response.json();
  paperAccountState = data;
  const pnlClass = (n) => Number(n) > 0 ? "price-up" : Number(n) < 0 ? "price-down" : "price-flat";
  document.querySelector("#paper-summary").innerHTML = [["EQUITY",data.equity],["CASH",data.cash],["MARKET VALUE",data.market_value],["UNREALIZED P&L",data.unrealized_pnl],["REALIZED P&L",data.realized_pnl]].map(([label,value]) => `<article><small>${label}</small><strong data-paper-summary="${label}" class="${label.includes("P&L") ? pnlClass(value) : ""}">${money(value)}</strong></article>`).join("");
  document.querySelector("#paper-positions").innerHTML = data.positions.length ? `<div class="paper-table-wrap"><table class="paper-position-table"><thead><tr><th>Saham</th><th>Lot</th><th>Avg Entry</th><th>Harga Sekarang</th><th>Modal Beli</th><th>Nilai Pasar</th><th>Unrealized P&amp;L</th><th>Return</th><th>Aksi</th></tr></thead><tbody>${data.positions.map(p => { const invested=Number(p.entry_price)*Number(p.shares); const returnPct=invested ? Number(p.unrealized_pnl)/invested*100 : 0; return `<tr data-paper-symbol="${escapeHtml(p.symbol)}" data-paper-shares="${p.shares}" data-paper-entry="${p.entry_price}" data-paper-fee="${p.entry_fee}" title="Klik untuk buka di Live Trading Desk"><td data-label="Saham"><b>${escapeHtml(p.symbol)}</b></td><td data-label="Lot">${p.lots}</td><td data-label="Avg Entry">${money(p.entry_price)}</td><td data-label="Harga Sekarang"><strong data-paper-price>${money(p.current_price)}</strong></td><td data-label="Modal Beli">${money(invested)}</td><td data-label="Nilai Pasar" data-paper-value>${money(p.market_value)}</td><td data-label="Unrealized P&L"><strong data-paper-pnl class="${pnlClass(p.unrealized_pnl)}">${money(p.unrealized_pnl)}</strong></td><td data-label="Return"><strong data-paper-return class="${pnlClass(returnPct)}">${returnPct>=0?"+":""}${returnPct.toFixed(2)}%</strong></td><td data-label="Aksi"><div class="paper-close-control"><label><span>Lot ditutup</span><input type="number" min="1" max="${p.lots}" value="${p.lots}" aria-label="Jumlah lot yang ditutup"></label><small>dari ${p.lots}</small><button type="button" data-close-position="${p.id}">Tutup ${p.lots} Lot</button></div></td></tr>`; }).join("")}</tbody></table></div>` : '<div class="empty">Belum ada posisi. Paper Buy hanya tersedia ketika status READY dan harga berada di entry zone.</div>';
  document.querySelectorAll("[data-paper-symbol]").forEach(row => row.onclick = (event) => { if (event.target.closest(".paper-close-control")) return; document.querySelector("#live-symbol").value=row.dataset.paperSymbol; loadLive(true); });
  document.querySelectorAll(".paper-close-control input").forEach(input => input.oninput = () => { const safe=Math.max(1,Math.min(Number(input.max),Number(input.value)||1)); input.value=safe; input.closest(".paper-close-control").querySelector("button").textContent=`Tutup ${safe} Lot`; });
  document.querySelector("#paper-orders").innerHTML = data.orders?.length ? `<div class="paper-table-wrap"><table class="paper-order-table"><thead><tr><th>Waktu</th><th>Saham</th><th>Side</th><th>Status</th><th>Lot</th><th>Referensi</th><th>Fill</th><th>Slippage</th><th>Fee</th><th>Alasan</th></tr></thead><tbody>${data.orders.map(order => `<tr><td>${formatDateTime(order.submitted_at)}</td><td><b>${escapeHtml(order.symbol)}</b></td><td>${order.side}</td><td><span class="order-status ${order.status}">${order.status}</span></td><td>${order.filled_lots}/${order.requested_lots}</td><td>${money(order.reference_price)}</td><td>${order.fill_price ? money(order.fill_price) : "—"}</td><td>${(Number(order.slippage_percent)*100).toFixed(2)}%</td><td>${money(order.fee)}</td><td>${escapeHtml(order.reason)}</td></tr>`).join("")}</tbody></table></div>` : '<div class="empty">Belum ada order baru yang tercatat setelah fitur ledger diaktifkan.</div>';
  document.querySelectorAll("[data-close-position]").forEach(button => button.onclick = async () => { button.disabled=true; const input=button.closest(".paper-close-control").querySelector("input"); const response=await fetch(`/api/demo-close/${button.dataset.closePosition}/`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({lots:Number(input.value)})}); const result=await response.json(); if(response.ok) { await loadDemoAccount(); await loadJournal(); } else {button.textContent=result.error || "Rejected"; button.disabled=false;} });
  const editCapital = document.querySelector("#edit-paper-capital");
  const capitalEditor = document.querySelector("#paper-capital-editor"), capitalInput = document.querySelector("#paper-capital-input"), capitalMessage = document.querySelector("#paper-capital-message");
  editCapital.onclick = () => { capitalInput.value = Math.round(Number(data.starting_cash)); capitalMessage.textContent = ""; capitalEditor.hidden = false; capitalInput.focus(); };
  document.querySelector("#cancel-paper-capital").onclick = () => { capitalEditor.hidden = true; capitalMessage.textContent = ""; };
  document.querySelector("#save-paper-capital").onclick = async (event) => {
    const saveButton = event.currentTarget, value = Number(capitalInput.value);
    saveButton.disabled = true; saveButton.textContent = "Menyimpan…";
    const response = await fetch("/api/demo-account/config/", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({starting_cash:value})});
    const result = await response.json();
    if (response.ok) { capitalEditor.hidden = true; await loadDemoAccount(); }
    else capitalMessage.textContent = result.error || "Modal gagal diperbarui.";
    saveButton.disabled = false; saveButton.textContent = "Simpan";
  };
  sendMarketSubscription();
}

function bindTechnicalButtons() {
  document.querySelectorAll(".technical-toggle").forEach((button) => {
    button.onclick = (event) => {
      event.preventDefault(); event.stopPropagation();
      const panel = button.closest(".plan").querySelector(".technical-evidence");
      panel.hidden = !panel.hidden;
      button.classList.toggle("active", !panel.hidden);
      button.setAttribute("aria-expanded", String(!panel.hidden));
    };
  });
}

function bindInsightButtons() {
  document.querySelectorAll(".ai-insight-toggle").forEach((button) => {
    button.onclick = async (event) => {
      event.preventDefault();
      event.stopPropagation();
      const commentary = button.closest(".plan").querySelector(".plan-commentary");
      const content = commentary.querySelector(".insight-content");
      if (!commentary.hidden) {
        commentary.hidden = true;
        button.setAttribute("aria-expanded", "false");
        button.classList.remove("active");
        return;
      }
      commentary.hidden = false;
      button.setAttribute("aria-expanded", "true");
      button.classList.add("active");
      if (content.innerHTML.trim()) return;
      const originalLabel = button.textContent;
      button.disabled = true;
      button.textContent = "Generating…";
      content.innerHTML = '<div class="insight-loading">9Router sedang menganalisis output quant…</div>';
      try {
        const response = await fetch(`/api/plans/${button.dataset.planId}/insight/`, { method: "POST" });
        const data = await response.json();
        content.innerHTML = response.ok ? marked.parse(data.commentary) : `<div class="insight-error">${escapeHtml(data.error || "AI Insight gagal")}</div>`;
      } catch (error) {
        content.innerHTML = '<div class="insight-error">Tidak dapat menghubungi layanan AI.</div>';
      } finally {
        button.disabled = false;
        button.textContent = originalLabel;
      }
    };
  });
}

async function loadMiniChart(symbol) {
  const response = await fetch(`/api/chart/${symbol}/`);
  const candles = await response.json();
  if (!candles.length) return;
  const values = candles.slice(-45).map((c) => Number(c.close));
  const low = Math.min(...values), high = Math.max(...values), span = high - low || 1;
  const points = values.map((price, index) => `${(index / (values.length - 1)) * 220},${54 - ((price - low) / span) * 48}`).join(" ");
  const node = document.querySelector(`#mini-${symbol}`);
  if (node) node.innerHTML = `<svg viewBox="0 0 220 60" preserveAspectRatio="none"><polyline points="${points}"/></svg>`;
}

let currentChartSymbol = "";
let currentChartRange = "1y";
let currentChartZoom = 1;
let chartFitMode = true;
const chartRangeLabels = { "5d": "5 days", "1mo": "1 month", "3mo": "3 months", "1y": "1 year", "5y": "5 years" };

async function loadChart(symbol, range = currentChartRange) {
  currentChartSymbol = symbol;
  currentChartRange = range;
  const chartNode = document.querySelector("#chart");
  chartNode.innerHTML = '<div class="empty">Loading price history…</div>';
  const response = await fetch(`/api/chart/${encodeURIComponent(symbol)}/?range=${range}`);
  const candles = await response.json();
  document.querySelector("#chart-title").textContent = `${symbol} · ${chartRangeLabels[range]}`;
  document.querySelectorAll("#chart-ranges button").forEach((button) => button.classList.toggle("active", button.dataset.range === range));
  if (!response.ok || !Array.isArray(candles) || !candles.length) {
    chartNode.innerHTML = `<div class="empty">${candles.error || "No chart data available"}</div>`;
    return;
  }
  const closes = candles.map((c) => Number(c.close));
  const sma = (period) => closes.map((_, index) => index + 1 < period ? null : closes.slice(index + 1 - period, index + 1).reduce((a, b) => a + b, 0) / period);
  const sma20 = sma(20), sma50 = sma(50);
  const plan = currentPlansBySymbol[symbol];
  const planLevels = plan ? [Number(plan.stop_loss), Number(plan.entry_low), Number(plan.entry_high), Number(plan.take_profit)] : [];
  const rawLow = Math.min(...closes, ...planLevels), rawHigh = Math.max(...closes, ...planLevels);
  const padding = Math.max((rawHigh - rawLow) * 0.08, rawHigh * 0.005);
  const low = rawLow - padding, high = rawHigh + padding, span = high - low || 1;
  const y = (price) => 184 - ((Number(price) - low) / span) * 166;
  const x = (index) => ((index + .5) / candles.length) * 1000;
  const linePoints = (values) => values.map((price, index) => price == null ? null : `${x(index)},${y(price)}`).filter(Boolean).join(" ");
  const candleWidth = Math.max(1.2, Math.min(9, 720 / candles.length));
  const candleSvg = candles.map((c, index) => {
    const open = Number(c.open), close = Number(c.close), highPrice = Number(c.high), lowPrice = Number(c.low), cx = x(index);
    const top = Math.min(y(open), y(close)), height = Math.max(1.5, Math.abs(y(open) - y(close)));
    return `<g class="candle ${close >= open ? "up" : "down"}"><line x1="${cx}" y1="${y(highPrice)}" x2="${cx}" y2="${y(lowPrice)}"/><rect x="${cx - candleWidth / 2}" y="${top}" width="${candleWidth}" height="${height}"/></g>`;
  }).join("");
  const maxVolume = Math.max(...candles.map((c) => Number(c.volume)), 1);
  const volumes = candles.map((c, index) => { const height = Number(c.volume) / maxVolume * 38; return `<rect class="volume-bar" x="${x(index) - candleWidth / 2}" y="${238 - height}" width="${candleWidth}" height="${height}"/>`; }).join("");
  const last = candles[candles.length - 1];
  const overlays = plan ? `<g class="trade-overlays">
      <rect class="entry-zone" x="0" y="${y(plan.entry_high)}" width="1000" height="${Math.max(2, y(plan.entry_low) - y(plan.entry_high))}"/>
      <line class="level-line target-line" x1="0" y1="${y(plan.take_profit)}" x2="1000" y2="${y(plan.take_profit)}"/><text class="level-label target-label" x="994" y="${y(plan.take_profit)-4}" text-anchor="end">TARGET</text>
      <line class="level-line stop-line" x1="0" y1="${y(plan.stop_loss)}" x2="1000" y2="${y(plan.stop_loss)}"/><text class="level-label stop-label" x="994" y="${y(plan.stop_loss)-4}" text-anchor="end">STOP</text>
      <text class="level-label entry-label" x="994" y="${y(plan.entry_high)-4}" text-anchor="end">ENTRY ZONE</text>
    </g>` : "";
  const planLegend = plan ? `<div class="chart-plan-legend"><span class="entry">Entry ${money(plan.entry_low)}–${money(plan.entry_high)}</span><span class="target">Target ${money(plan.take_profit)}</span><span class="stop">Stop ${money(plan.stop_loss)}</span><b class="badge ${plan.status}">${plan.status}</b><small>Level model · bukan jaminan hasil</small></div>` : "";
  const chartViewport = Math.max(320, chartNode.clientWidth - 24);
  const naturalPlotWidth = Math.max(chartViewport, candles.length * 10);
  const plotWidth = chartFitMode ? chartViewport : Math.max(chartViewport, naturalPlotWidth * currentChartZoom);
  document.querySelector("#chart").innerHTML = `<div class="chart-scroll"><svg viewBox="0 0 1000 250" preserveAspectRatio="none" style="width:${plotWidth}px" role="img" aria-label="Candlestick chart with volume and technical overlays"><line class="grid" x1="0" y1="18" x2="1000" y2="18"/><line class="grid" x1="0" y1="101" x2="1000" y2="101"/><line class="grid" x1="0" y1="184" x2="1000" y2="184"/><line class="volume-divider" x1="0" y1="194" x2="1000" y2="194"/>${volumes}${overlays}${candleSvg}<polyline class="sma sma20" points="${linePoints(sma20)}"/><polyline class="sma sma50" points="${linePoints(sma50)}"/><line class="chart-crosshair" x1="0" y1="0" x2="0" y2="238" hidden/></svg></div><div class="chart-tooltip" hidden></div>${planLegend}<div class="chart-meta"><b>Last ${money(last.close)}</b><span>H ${money(last.high)}</span><span>L ${money(last.low)}</span><span>Vol ${money(last.volume)}</span><span class="legend-sma20">— SMA20</span><span class="legend-sma50">— SMA50</span><span>↔ drag/scroll chart · hover for OHLC</span></div>`;
  const scrollNode = chartNode.querySelector(".chart-scroll"), svg = scrollNode.querySelector("svg"), tooltip = chartNode.querySelector(".chart-tooltip"), crosshair = svg.querySelector(".chart-crosshair");
  const inspectCandle = (event) => {
    const svgRect = svg.getBoundingClientRect(), chartRect = chartNode.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(.9999, (event.clientX - svgRect.left) / svgRect.width));
    const index = Math.min(candles.length - 1, Math.floor(ratio * candles.length)), candle = candles[index];
    const crossX = ((index + .5) / candles.length) * 1000;
    crosshair.hidden = false; crosshair.setAttribute("x1", crossX); crosshair.setAttribute("x2", crossX);
    tooltip.hidden = false; tooltip.style.left = `${Math.min(chartRect.width - 175, Math.max(8, event.clientX - chartRect.left + 12))}px`; tooltip.style.top = "14px";
    tooltip.innerHTML = `<b>${formatDateTime(candle.time)}</b><span>O ${money(candle.open)} · H ${money(candle.high)}</span><span>L ${money(candle.low)} · C ${money(candle.close)}</span><span>Volume ${money(candle.volume)}</span>`;
  };
  scrollNode.addEventListener("mousemove", inspectCandle);
  scrollNode.addEventListener("mouseleave", () => { tooltip.hidden = true; crosshair.hidden = true; dragging = false; scrollNode.classList.remove("dragging"); });
  scrollNode.addEventListener("wheel", (event) => { if (Math.abs(event.deltaY) > Math.abs(event.deltaX)) { event.preventDefault(); scrollNode.scrollLeft += event.deltaY; } }, {passive:false});
  let dragging = false, dragStart = 0, scrollStart = 0;
  scrollNode.addEventListener("mousedown", (event) => { dragging = true; dragStart = event.clientX; scrollStart = scrollNode.scrollLeft; scrollNode.classList.add("dragging"); });
  scrollNode.addEventListener("mousemove", (event) => { if (dragging) scrollNode.scrollLeft = scrollStart - (event.clientX - dragStart); });
  scrollNode.addEventListener("mouseup", () => { dragging = false; scrollNode.classList.remove("dragging"); });
  // The decision-relevant view opens on the latest candles; history remains to the left.
  requestAnimationFrame(() => { scrollNode.scrollLeft = scrollNode.scrollWidth - scrollNode.clientWidth; });
}

document.querySelector("#scan").onclick = async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = "Scanning…";
  
  const offline = document.querySelector("#offline").checked;
  const isVerbose = true;
  
  if (isVerbose) {
    const terminal = document.querySelector("#scan-terminal");
    terminal.style.display = "flex";
    document.querySelector("#terminal-logs").innerHTML = "";
  }
  
  try {
    const minMlProbability = Number(document.querySelector("#ml-threshold").value);
    const response = await fetch("/api/scan/", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      offline,
      verbose: isVerbose,
      min_ml_probability: minMlProbability,
      max_risk_per_trade: Number(document.querySelector("#risk-per-trade").value) / 100,
      max_daily_loss: Number(document.querySelector("#daily-loss-limit").value) / 100,
      min_risk_reward: Number(document.querySelector("#minimum-rr").value),
      min_signal_score: Number(document.querySelector("#quant-score-gate").value),
      min_profit_factor: Number(document.querySelector("#profit-factor-gate").value),
      strategy: selectedStrategy,
    }) });
    if (!response.ok) throw new Error("Market scan failed");
    await load();
  } catch (err) {
    console.error(err);
  } finally {
    button.disabled = false;
    button.textContent = "Run Market Scan";
  }
};

document.querySelector("#close-terminal").onclick = () => {
  document.querySelector("#scan-terminal").style.display = "none";
};

const protocol = location.protocol === "https:" ? "wss" : "ws";
const socket = new WebSocket(`${protocol}://${location.host}/ws/market/`);
let planRefreshTimer = null;
socket.onopen = () => {
  document.querySelector("#live").textContent = "LIVE";
  document.querySelector("#live-card").classList.add("is-live");
  sendMarketSubscription();
};
socket.onmessage = (event) => {
  try {
    const data = JSON.parse(event.data);
    if (data.type === "log") {
      const terminal = document.querySelector("#scan-terminal");
      if (terminal.style.display === "none") terminal.style.display = "flex";
      
      const logs = document.querySelector("#terminal-logs");
      const p = document.createElement("div");
      p.className = "terminal-log-entry";
      p.textContent = data.message;
      logs.appendChild(p);
      logs.scrollTop = logs.scrollHeight;
    } else if (data.event === "market.snapshot") {
      applyMarketSnapshot(data);
    } else if (data.event === "plans.updated") {
      // Collapse duplicate/bursty plan events into a single dashboard refresh.
      window.clearTimeout(planRefreshTimer);
      planRefreshTimer = window.setTimeout(() => {
        load();
        loadScanner();
        loadJournal();
      }, 350);
    }
  } catch (e) {
    console.warn("Ignored malformed market WebSocket event", e);
  }
};

function sendMarketSubscription() {
  if (typeof socket === "undefined" || socket.readyState !== WebSocket.OPEN) return;
  const liveSymbol = document.querySelector("#live-symbol")?.value?.toUpperCase().trim() || "";
  const tickerSymbols=[...document.querySelectorAll("[data-tape-symbol]")].map(node=>node.dataset.tapeSymbol);
  const paperSymbols=(paperAccountState?.positions || []).map(position=>position.symbol);
  const symbols = [...new Set([...paperSymbols, ...latestPlanSymbols, ...latestJournalRows.map((row) => row.symbol), ...tickerSymbols])].slice(0, 40);
  socket.send(JSON.stringify({action:"subscribe", symbols, live_symbol:liveSymbol}));
}

function applyMarketSnapshot(data) {
  const prices = data.prices || {};
  document.querySelectorAll("[data-plan-symbol]").forEach((card) => {
    const quote=prices[card.dataset.planSymbol]; if(!quote) return;
    const reference=Number(quote.previous_close || currentPlansBySymbol[card.dataset.planSymbol]?.indicators?.close || 0);
    const move=reference ? (Number(quote.price)/reference-1)*100 : 0;
    const priceNode=card.querySelector("[data-current-price]"), moveNode=card.querySelector("[data-current-move]");
    priceNode.textContent=money(quote.price); priceNode.className=move>0?"price-up":move<0?"price-down":"price-flat";
    moveNode.textContent=`Vs Prev · ${move>0?"+":""}${move.toFixed(2)}%`; moveNode.className=priceNode.className;
  });
  document.querySelectorAll("[data-journal-symbol]").forEach((row) => {
    const quote=prices[row.dataset.journalSymbol]; if(!quote) return;
    const move=(Number(quote.price)/Number(row.dataset.reference)-1)*100;
    row.querySelector("[data-journal-current]").textContent=money(quote.price);
    const moveNode=row.querySelector("[data-journal-live]"); moveNode.textContent=`${move>0?"+":""}${move.toFixed(2)}%`; moveNode.className=move>0?"price-up":move<0?"price-down":"price-flat";
  });
  let paperMarketValue=0, paperUnrealized=0;
  document.querySelectorAll("[data-paper-symbol]").forEach((row)=>{
    const quote=prices[row.dataset.paperSymbol];
    const state=(paperAccountState?.positions || []).find(position=>position.symbol===row.dataset.paperSymbol);
    const price=Number(quote?.price ?? state?.current_price ?? 0), shares=Number(row.dataset.paperShares), entry=Number(row.dataset.paperEntry), fee=Number(row.dataset.paperFee || 0);
    if(!price || !shares)return;
    const value=price*shares, invested=entry*shares, pnl=(price-entry)*shares-fee, returnPct=invested?pnl/invested*100:0;
    paperMarketValue+=value; paperUnrealized+=pnl;
    row.querySelector("[data-paper-price]").textContent=money(price); row.querySelector("[data-paper-value]").textContent=money(value);
    const pnlNode=row.querySelector("[data-paper-pnl]"), returnNode=row.querySelector("[data-paper-return]");
    pnlNode.textContent=money(pnl); pnlNode.className=pnl>0?"price-up":pnl<0?"price-down":"price-flat";
    returnNode.textContent=`${returnPct>=0?"+":""}${returnPct.toFixed(2)}%`; returnNode.className=pnlNode.className;
  });
  if(paperAccountState && document.querySelectorAll("[data-paper-symbol]").length){
    const cash=Number(paperAccountState.cash), realized=Number(paperAccountState.realized_pnl), values={"EQUITY":cash+paperMarketValue,"CASH":cash,"MARKET VALUE":paperMarketValue,"UNREALIZED P&L":paperUnrealized,"REALIZED P&L":realized};
    document.querySelectorAll("[data-paper-summary]").forEach(node=>{const value=values[node.dataset.paperSummary];node.textContent=money(value);if(node.dataset.paperSummary.includes("P&L"))node.className=value>0?"price-up":value<0?"price-down":"price-flat";});
  }
  const liveSymbol=document.querySelector("#live-symbol")?.value?.toUpperCase().trim(), quote=prices[liveSymbol];
  if(quote) document.querySelector("#live-decision").innerHTML=`<div class="live-strip ${data.market_active?"":"market-idle"}"><strong>${liveSymbol} · ${money(quote.price)}</strong><span>High ${money(quote.high)}</span><span>Low ${money(quote.low)}</span><span>Volume ${money(quote.volume)}</span><span>${data.market_active?"STREAM LIVE":"FINAL CLOSE"}</span><span>${formatDateTime(quote.market_time)}</span></div>`;
  document.querySelectorAll("[data-tape-symbol]").forEach((item)=>{const q=prices[item.dataset.tapeSymbol];if(!q)return;const move=(Number(q.price)/Number(q.previous_close)-1)*100;item.querySelector("[data-tape-price]").textContent=money(q.price);const n=item.querySelector("[data-tape-move]");n.textContent=`${move>0?"▲ +":move<0?"▼ ":"• "}${move.toFixed(2)}%`;n.className=move>0?"up":move<0?"down":"flat";});
}
socket.onclose = () => {
  document.querySelector("#live").textContent = "OFFLINE";
  document.querySelector("#live-card").classList.remove("is-live");
};
load();

let scannerPage = 1;
async function loadScanner() {
  const query = encodeURIComponent(document.querySelector("#stock-search").value);
  const status = encodeURIComponent(document.querySelector("#status-filter").value);
  const response = await fetch(`/api/scanner/?page=${scannerPage}&size=50&q=${query}&status=${status}`);
  const data = await response.json();
  document.querySelector("#scanner-body").innerHTML = data.results.map((row) => {
    const bfScore = row.indicators?.broker_flow_score;
    const bfClass = bfScore != null && bfScore !== 50 ? (bfScore >= 65 ? "badge-bandar-high" : bfScore >= 45 ? "badge-bandar-mid" : "badge-bandar-low") : "badge-bandar-none";
    const bfText = bfScore != null && bfScore !== 50 ? `${Number(bfScore).toFixed(0)}` : "—";
    const ffSig = row.indicators?.foreign_flow_signal || "NEUTRAL";
    const ffEmoji = ffSig === "ACCUMULATE" ? "↑↑" : ffSig === "DISTRIBUTE" ? "↓↓" : "→";
    const ffClass = ffSig === "ACCUMULATE" ? "price-up" : ffSig === "DISTRIBUTE" ? "price-down" : "";
    const der = row.indicators?.der;
    const roe = row.indicators?.roe;
    const per = row.indicators?.per;
    const fundText = per != null ? `${Number(per).toFixed(0)}×` : "—";
    const fundClass = der != null && der > 3 ? "price-down" : per != null && per < 15 && roe != null && roe >= 15 ? "price-up" : "";
    return `<tr><td>${row.symbol}</td><td>${row.name || "—"}</td><td>${row.price ? money(row.price) : "—"}</td><td>${row.confidence ? Math.round(row.confidence * 100) + "%" : "—"}</td><td>${row.score ? Number(row.score).toFixed(2) : "—"}</td><td><span class="badge-bandar ${bfClass}">${bfText}</span></td><td><span class="${ffClass}">${ffEmoji} ${ffSig}</span></td><td><span class="${fundClass}">PER ${fundText}</span></td><td><span class="badge ${row.status}">${row.status}</span></td></tr>`;
  }).join("");
  document.querySelector("#page-label").textContent = `Page ${data.page} · ${data.total} stocks`;
  document.querySelector("#prev-page").disabled = scannerPage === 1;
  document.querySelector("#next-page").disabled = scannerPage * data.size >= data.total;
}

async function loadSystem() {
  const response = await fetch(`/api/system/?strategy=${selectedStrategy}`);
  const data = await response.json();
  const model = data.model, test = data.backtest;
  const quality = data.engine_quality;
  document.querySelector("#engine-quality").textContent = `${quality.score}%`;
  document.querySelector("#engine-quality-note").textContent = `${quality.grade} · adjusted from ${quality.evaluated} proofs`;
  document.querySelector("#quality-card").className = `metric-state quality-${quality.grade.toLowerCase()}`;
  document.querySelector("#min-ml-threshold").textContent = `${Math.round(Number(document.querySelector("#ml-threshold").value) * 100)}%`;
  document.querySelector("#model-metrics").innerHTML = `<article><label>UNIVERSE</label><strong>${money(data.universe)}</strong><small>Active IDX shares</small></article><article><label>ML SAMPLES</label><strong>${money(model?.samples || 0)}</strong><small>${model?.name || "No model"}</small></article><article><label>MEAN AUC</label><strong>${model?.metrics?.mean_auc || "—"}</strong><small>Walk-forward evaluation</small></article><article><label>PROFIT FACTOR</label><strong>${test?.profit_factor || "—"}</strong><small>${test ? `${test.trades} tested trades` : "Not backtested for this strategy"}</small></article><article><label>MAX DRAWDOWN</label><strong class="${test && Number(test.max_drawdown)<-.2?'price-down':''}">${test ? `${(Number(test.max_drawdown)*100).toFixed(1)}%` : "—"}</strong><small>${test ? "Peak-to-trough equity loss" : "Awaiting matched backtest"}</small></article>`;
  const auc = Number(model?.metrics?.mean_auc || 0);
  const profitFactor = test ? Number(test.profit_factor) : null;
  const verdict = document.querySelector("#model-verdict");
  const profitFactorGate = Number(data.limits.min_profit_factor);
  const trades = Number(test?.trades || 0), expectancy = Number(test?.expectancy || 0), maxDrawdown = Math.abs(Number(test?.max_drawdown || 1));
  const validated = auc >= 0.55 && profitFactor !== null && profitFactor >= Math.max(1.2, profitFactorGate) && expectancy > 0 && maxDrawdown <= 0.20 && trades >= 100;
  verdict.className = `model-verdict ${validated ? "pass" : "caution"}`;
  verdict.innerHTML = validated
    ? `<b>VALIDATED EDGE</b><span>AUC, PF, expectancy, drawdown, dan minimal 100 transaksi OOS melewati gate.</span>`
    : `<b>EDGE BELUM KUAT</b><span>${test ? `Audit OOS: ${trades}/100 transaksi · AUC ${auc.toFixed(4)} · PF ${profitFactor.toFixed(3)} · drawdown ${(maxDrawdown*100).toFixed(1)}%. Hasil yang menjanjikan tetap belum dianggap terbukti sebelum sampelnya cukup.` : `${data.strategy_label} belum memiliki backtest strategi yang sepadan; Profit Factor dan drawdown tidak dipinjam dari strategi lain.`} Risk engine tetap memaksa WAIT.</span>`;
  document.querySelector("#folds").innerHTML = (model?.metrics?.walk_forward || []).map((fold) => `<article><b>${formatDate(fold.split)}</b><span>AUC ${fold.auc}</span><span>Accuracy ${fold.accuracy}</span><span>Precision ${fold.precision}</span><span>${money(fold.samples)} samples</span></article>`).join("");
  renderLine("#equity-chart", test?.equity_curve || [], "#c95050");
}

function renderLine(selector, values, color = "#1f8a5b") {
  const node = document.querySelector(selector);
  if (!values.length) { node.innerHTML = '<div class="empty">No verified observations yet.</div>'; return; }
  const low = Math.min(...values), high = Math.max(...values), span = high - low || 1;
  const points = values.map((value, index) => `${(index / (values.length - 1)) * 1000},${240 - ((value - low) / span) * 210}`).join(" ");
  node.innerHTML = `<svg viewBox="0 0 1000 250" preserveAspectRatio="none"><polyline style="fill:none;stroke:${color};stroke-width:3;vector-effect:non-scaling-stroke" points="${points}"/></svg>`;
}

function renderInteractiveLive(candles) {
  const node = document.querySelector("#live-chart"), values = candles.map(candle => Number(candle.close));
  if (!values.length) { node.innerHTML = '<div class="empty">No intraday observations yet.</div>'; return; }
  const low = Math.min(...candles.map(c => Number(c.low))), high = Math.max(...candles.map(c => Number(c.high))), span = high - low || 1;
  const xAt = index => candles.length === 1 ? 500 : (index / (candles.length - 1)) * 1000;
  const yAt = value => 230 - ((Number(value) - low) / span) * 200;
  const points = values.map((value, index) => `${xAt(index)},${yAt(value)}`).join(" ");
  node.innerHTML = `<svg viewBox="0 0 1000 250" preserveAspectRatio="none" aria-label="Interactive intraday price chart"><polyline class="live-price-line" points="${points}"/><line class="live-crosshair-x" x1="0" x2="0" y1="20" y2="235" hidden/><line class="live-crosshair-y" x1="0" x2="1000" y1="0" y2="0" hidden/><circle class="live-hover-point" cx="0" cy="0" r="6" hidden/></svg><div class="live-chart-tooltip" hidden></div>`;
  const vertical=node.querySelector(".live-crosshair-x"), horizontal=node.querySelector(".live-crosshair-y"), marker=node.querySelector(".live-hover-point"), tooltip=node.querySelector(".live-chart-tooltip");
  const show = event => {
    const rect=node.getBoundingClientRect(), clientX=event.touches?.[0]?.clientX ?? event.clientX, localX=Math.max(0,Math.min(rect.width,clientX-rect.left));
    const index=Math.max(0,Math.min(candles.length-1,Math.round((localX/rect.width)*(candles.length-1)))), candle=candles[index], x=xAt(index), y=yAt(candle.close);
    vertical.setAttribute("x1",x); vertical.setAttribute("x2",x); horizontal.setAttribute("y1",y); horizontal.setAttribute("y2",y); marker.setAttribute("cx",x); marker.setAttribute("cy",y);
    [vertical,horizontal,marker,tooltip].forEach(element => element.hidden=false);
    tooltip.innerHTML=`<b>${formatDateTime(candle.time)}</b><span>Close <strong>${money(candle.close)}</strong></span><span>High ${money(candle.high)} · Low ${money(candle.low)}</span><span>Volume ${money(candle.volume)}</span>`;
    tooltip.style.left=`${Math.min(rect.width-175,Math.max(8,localX+12))}px`; tooltip.style.top=`${Math.max(8,(y/250)*rect.height-55)}px`;
  };
  node.onmousemove=show; node.ontouchmove=show; node.onmouseleave=()=>[vertical,horizontal,marker,tooltip].forEach(element => element.hidden=true);
}

async function loadJournal() {
  const response = await fetch(`/api/predictions/?window=${selectedJournalWindow}`);
  const data = await response.json();
  document.querySelector("#journal-windows").innerHTML = ["ALL","OPEN_0930","MIDDAY_1130","CLOSE_FINAL","LEGACY"].filter(value => value === "ALL" || data.available_windows.includes(value)).map(value => `<button type="button" data-journal-window="${value}" class="${value === selectedJournalWindow ? "active" : ""}">${value === "ALL" ? "ALL" : windowLabels[value]}</button>`).join("");
  document.querySelectorAll("[data-journal-window]").forEach(button => button.onclick=()=>{selectedJournalWindow=button.dataset.journalWindow;loadJournal();});
  const verifiedPercent = data.accuracy == null ? null : Math.round(data.accuracy * 100);
  const activeRows = data.results.filter((row) => row.was_correct == null);
  const historyRows = data.results.filter((row) => row.was_correct != null);
  const paperRows = data.paper_results || [];
  document.querySelector("#journal-pending-count").textContent = `${activeRows.length} active`;
  document.querySelector("#journal-accuracy").textContent = verifiedPercent == null ? "No verified history" : `${verifiedPercent}% verified accuracy · ${historyRows.length} records`;
  document.querySelector("#proof-ratio").textContent = data.evaluated ? `${Math.round(data.accuracy * data.evaluated)}/${data.evaluated}` : "—";
  document.querySelector("#proof-note").textContent = data.evaluated ? `${verifiedPercent}% correct on evaluated history` : "Waiting for evaluated calls";
  document.querySelector("#proof-card").classList.toggle("has-proof", Boolean(data.evaluated));
  latestJournalRows = activeRows;
  const renderActive = rows => rows.length ? rows.map((row) => `<tr data-journal-symbol="${escapeHtml(row.symbol)}" data-reference="${row.reference_price}"><td>${formatDate(row.signal_date)}</td><td>${escapeHtml(row.symbol)}</td><td><span class="badge ${row.decision}">${row.decision}</span></td><td>${Math.round(row.probability * 100)}%</td><td>${money(row.reference_price)}</td><td data-journal-current>${row.last_stored_price ? money(row.last_stored_price) : "Menunggu data"}</td><td data-journal-live>—</td><td>Pending</td><td>—</td><td>⏳</td></tr>`).join("") : '<tr><td colspan="10" class="journal-empty">Tidak ada prediksi aktif.</td></tr>';
  const renderHistory = rows => rows.length ? rows.map((row) => { const move=Number(row.realized_return||0)*100; return `<tr><td>${formatDate(row.signal_date)}</td><td>${escapeHtml(row.symbol)}</td><td><span class="badge ${row.decision}">${row.decision}</span></td><td>${Math.round(row.probability * 100)}%</td><td>${money(row.reference_price)}</td><td><strong>${money(row.realized_price)}</strong></td><td class="${move>0?"price-up":move<0?"price-down":"price-flat"}">${move>=0?"+":""}${move.toFixed(2)}%</td><td>${row.was_correct ? "✓" : "✕"}</td></tr>`; }).join("") : '<tr><td colspan="8" class="journal-empty">Belum ada prediksi yang selesai dievaluasi.</td></tr>';
  document.querySelector("#journal-active-body").innerHTML = renderActive(activeRows);
  document.querySelector("#journal-history-body").innerHTML = renderHistory(historyRows);
  const paperProfit=paperRows.filter(row=>Number(row.realized_pnl)>0).length, paperPnl=paperRows.reduce((sum,row)=>sum+Number(row.realized_pnl||0),0);
  document.querySelector("#paper-proof-summary").textContent=paperRows.length ? `${paperProfit}/${paperRows.length} profitable · ${money(paperPnl)}` : "No closed trades";
  document.querySelector("#paper-history-body").innerHTML=paperRows.length ? paperRows.map(row=>{const pnl=Number(row.realized_pnl||0),ret=Number(row.return||0)*100;return `<tr><td>${formatDateTime(row.closed_at)}</td><td><b>${escapeHtml(row.symbol)}</b></td><td>${row.lots}</td><td>${money(row.entry_price)}</td><td>${money(row.exit_price)}</td><td>${money(row.exit_fee)}</td><td class="${pnl>0?"price-up":pnl<0?"price-down":"price-flat"}">${money(pnl)}</td><td class="${ret>0?"price-up":ret<0?"price-down":"price-flat"}">${ret>=0?"+":""}${ret.toFixed(2)}%</td><td>${pnl>0?"✓ PROFIT":"✕ LOSS"}</td></tr>`;}).join("") : '<tr><td colspan="9" class="journal-empty">Belum ada posisi paper yang ditutup setelah ledger SELL diaktifkan.</td></tr>';
  sendMarketSubscription();
}

let dashboardPriceRequestRunning = false;
async function refreshDashboardPrices() {
  if (!isIdxFeedWindow()) return;
  if (dashboardPriceRequestRunning) return;
  const symbols = [...new Set([...latestPlanSymbols, ...latestJournalRows.map((row) => row.symbol)])].slice(0, 30);
  if (!symbols.length) return;
  dashboardPriceRequestRunning = true;
  try {
    const response = await fetch(`/api/live-prices/?symbols=${encodeURIComponent(symbols.join(","))}&t=${Date.now()}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) return;
    document.querySelectorAll("[data-plan-symbol]").forEach((card) => {
      const quote = data.prices[card.dataset.planSymbol];
      if (quote) {
        const plan = currentPlansBySymbol[card.dataset.planSymbol];
        const reference = Number(quote.previous_close || plan?.indicators?.close || 0);
        const move = reference ? (Number(quote.price) / reference - 1) * 100 : 0;
        const priceNode = card.querySelector("[data-current-price]");
        const moveNode = card.querySelector("[data-current-move]");
        priceNode.textContent = money(quote.price);
        priceNode.className = move > 0 ? "price-up" : move < 0 ? "price-down" : "price-flat";
        moveNode.textContent = `Vs Prev · ${move > 0 ? "+" : ""}${move.toFixed(2)}%`;
        moveNode.className = move > 0 ? "price-up" : move < 0 ? "price-down" : "price-flat";
        const box = card.querySelector(".live-price-box");
        box.classList.remove("quote-flash"); void box.offsetWidth; box.classList.add("quote-flash");
      }
    });
    document.querySelectorAll("[data-journal-symbol]").forEach((row) => {
      const quote = data.prices[row.dataset.journalSymbol];
      if (!quote) return;
      const move = (quote.price / Number(row.dataset.reference) - 1) * 100;
      row.querySelector("[data-journal-current]").textContent = money(quote.price);
      const moveNode = row.querySelector("[data-journal-live]");
      moveNode.textContent = `${move > 0 ? "+" : ""}${move.toFixed(2)}%`;
      moveNode.className = move > 0 ? "price-up" : move < 0 ? "price-down" : "price-flat";
    });
  } catch (error) {
    console.warn("Dashboard live-price refresh failed", error);
  } finally {
    dashboardPriceRequestRunning = false;
  }
}

let liveTimer;
let liveRequest = null;
function isIdxFeedWindow() {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", {timeZone:"Asia/Jakarta",weekday:"short",hour:"2-digit",minute:"2-digit",hour12:false}).formatToParts(new Date()).filter(part => part.type !== "literal").map(part => [part.type,part.value]));
  if (["Sat","Sun"].includes(parts.weekday)) return false;
  const minute=Number(parts.hour)*60+Number(parts.minute), friday=parts.weekday === "Fri";
  const firstEnd=friday ? 11*60+30 : 12*60, secondStart=friday ? 14*60 : 13*60+30;
  return (minute >= 8*60+57 && minute <= firstEnd) || (minute >= secondStart-3 && minute <= 15*60+49);
}

async function loadLive(force = false) {
  if (!force && !isIdxFeedWindow()) {
    document.querySelector("#live-decision").innerHTML = '<div class="live-strip market-idle"><strong>MARKET CLOSED</strong><span>Auto-feed berhenti · aktif kembali 3 menit sebelum sesi IDX</span></div>';
    return;
  }
  const symbol = document.querySelector("#live-symbol").value.toUpperCase().trim();
  if (!symbol) return;
  if (liveRequest) liveRequest.abort();
  liveRequest = new AbortController();
  let response, data;
  try {
    response = await fetch(`/api/intraday/${symbol}/?t=${Date.now()}`, {
      cache: "no-store",
      signal: liveRequest.signal,
    });
    data = await response.json();
  } catch (error) {
    if (error.name !== "AbortError") console.warn("Live quote refresh failed", error);
    return;
  }
  if (!response.ok || !data.candles.length) { document.querySelector("#live-chart").innerHTML = `<div class="empty">${data.error || "No intraday data"}</div>`; return; }
  renderInteractiveLive(data.candles);
  const last = data.candles[data.candles.length - 1];
  document.querySelector("#live-decision").innerHTML = `<div class="live-strip"><strong>${symbol} · ${money(last.close)}</strong><span>High ${money(last.high)}</span><span>Low ${money(last.low)}</span><span>Volume ${money(last.volume)}</span><span>Candle ${formatDateTime(last.time)}</span><span>Checked ${new Date().toLocaleTimeString("id-ID")}</span></div>`;
}

// Dashboard navigation has been removed in favor of a full-width unified layout.
document.querySelector("#stock-search").oninput = () => { scannerPage = 1; loadScanner(); };
document.querySelector("#status-filter").onchange = () => { scannerPage = 1; loadScanner(); };
document.querySelector("#prev-page").onclick = () => { scannerPage--; loadScanner(); };
document.querySelector("#next-page").onclick = () => { scannerPage++; loadScanner(); };
document.querySelector("#load-live").onclick = () => { sendMarketSubscription(); loadLive(true); };
document.querySelector("#ml-threshold").onchange = (event) => {
  const percent = Math.round(Number(event.target.value) * 100);
  document.querySelector("#min-ml-threshold").textContent = `${percent}%`;
  localStorage.setItem("quantaraMlGate", event.target.value);
  saveRiskControls();
};
const savedMlGate = localStorage.getItem("quantaraMlGate");
if (["0.50", "0.55", "0.60", "0.65"].includes(savedMlGate)) {
  document.querySelector("#ml-threshold").value = savedMlGate;
  document.querySelector("#min-ml-threshold").textContent = `${Math.round(Number(savedMlGate) * 100)}%`;
}

const riskProfiles = {
  conservative: { risk: 0.5, loss: 1.0, rr: 2.0, score: 72, ml: "0.65", pf: 1.25, note: "Conservative · fewer setups, tighter capital protection" },
  balanced: { risk: 1.0, loss: 2.0, rr: 1.5, score: 65, ml: "0.65", pf: 1.0, note: "Balanced · default research profile" },
  exploratory: { risk: 1.0, loss: 3.0, rr: 1.3, score: 58, ml: "0.55", pf: 1.0, note: "Exploratory · more candidates, lower evidence threshold" },
};

function setRiskControls(values, profile = "custom") {
  document.querySelector("#risk-per-trade").value = values.risk;
  document.querySelector("#daily-loss-limit").value = values.loss;
  document.querySelector("#minimum-rr").value = values.rr;
  document.querySelector("#quant-score-gate").value = values.score;
  document.querySelector("#profit-factor-gate").value = values.pf ?? 1.0;
  document.querySelector("#ml-threshold").value = values.ml;
  document.querySelector("#min-ml-threshold").textContent = `${Math.round(Number(values.ml) * 100)}%`;
  document.querySelector("#risk-profile-note").textContent = values.note || "Custom profile · applied on next scan";
  document.querySelectorAll("[data-risk-profile]").forEach((button) => button.classList.toggle("active", button.dataset.riskProfile === profile));
}

function saveRiskControls() {
  localStorage.setItem("quantaraRiskControls", JSON.stringify({
    risk: Number(document.querySelector("#risk-per-trade").value),
    loss: Number(document.querySelector("#daily-loss-limit").value),
    rr: Number(document.querySelector("#minimum-rr").value),
    score: Number(document.querySelector("#quant-score-gate").value),
    pf: Number(document.querySelector("#profit-factor-gate").value),
    ml: document.querySelector("#ml-threshold").value,
    note: "Custom profile · applied on next scan",
  }));
}

document.querySelectorAll("[data-risk-profile]").forEach((button) => {
  button.onclick = () => {
    const name = button.dataset.riskProfile;
    setRiskControls(riskProfiles[name], name);
    saveRiskControls();
  };
});
document.querySelectorAll("#risk-per-trade, #daily-loss-limit, #minimum-rr, #quant-score-gate, #profit-factor-gate").forEach((input) => {
  input.onchange = () => { saveRiskControls(); setRiskControls({
    risk: document.querySelector("#risk-per-trade").value,
    loss: document.querySelector("#daily-loss-limit").value,
    rr: document.querySelector("#minimum-rr").value,
    score: document.querySelector("#quant-score-gate").value,
    pf: document.querySelector("#profit-factor-gate").value,
    ml: document.querySelector("#ml-threshold").value,
    note: "Custom profile · applied on next scan",
  }); };
});
try {
  const savedRiskControls = JSON.parse(localStorage.getItem("quantaraRiskControls"));
  if (savedRiskControls) setRiskControls(savedRiskControls);
} catch (_error) {
  localStorage.removeItem("quantaraRiskControls");
}
document.querySelectorAll("#chart-ranges button").forEach((button) => {
  button.onclick = () => {
    currentChartRange = button.dataset.range;
    chartFitMode = true;
    currentChartZoom = 1;
    if (currentChartSymbol) loadChart(currentChartSymbol, currentChartRange);
  };
});
document.querySelectorAll("#chart-zoom button").forEach((button) => {
  button.onclick = () => {
    if (!currentChartSymbol) return;
    if (button.dataset.zoom === "fit") { chartFitMode = true; currentChartZoom = 1; }
    else {
      chartFitMode = false;
      currentChartZoom = Math.max(.6, Math.min(3, currentChartZoom + (button.dataset.zoom === "in" ? .35 : -.35)));
    }
    loadChart(currentChartSymbol, currentChartRange);
  };
});
document.querySelector("#live-symbol").addEventListener("keydown", (event) => {
  if (event.key === "Enter") { sendMarketSubscription(); loadLive(true); }
});
loadScanner();
loadSystem();
loadJournal();
loadLive(false);

let marketTapeRequestRunning = false;
async function loadMarketTape(force = false) {
  if (!force && !isIdxFeedWindow()) return;
  if (marketTapeRequestRunning) return;
  marketTapeRequestRunning = true;
  try {
    const response = await fetch(`/api/market-ticker/?t=${Date.now()}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || !data.results.length) return;
    const items = data.results.map((row) => {
      const direction = row.change_percent > 0 ? "up" : row.change_percent < 0 ? "down" : "flat";
      const arrow = row.change_percent > 0 ? "▲" : row.change_percent < 0 ? "▼" : "•";
      const sign = row.change_percent > 0 ? "+" : "";
      return `<span class="tape-item" data-tape-symbol="${escapeHtml(row.symbol)}"><b>${escapeHtml(row.symbol)}</b><span data-tape-price>${money(row.price)}</span><strong data-tape-move class="${direction}">${arrow} ${sign}${row.change_percent.toFixed(2)}%</strong></span>`;
    }).join("");
    const track = document.querySelector("#market-tape-track");
    track.innerHTML = `<div class="tape-set">${items}</div><div class="tape-set" aria-hidden="true">${items}</div>`;
    // Dynamic content can retain the animation's old zero-width timeline in
    // WebKit. Recreate it after layout so it starts without user interaction.
    const oneSetWidth = track.firstElementChild.scrollWidth;
    track.style.setProperty("--tape-duration", `${Math.max(35, oneSetWidth / 55)}s`);
    track.style.animation = "none";
    void track.offsetWidth;
    track.style.animation = "";
    sendMarketSubscription();
  } catch (error) {
    console.warn("Market tape refresh failed", error);
  } finally {
    marketTapeRequestRunning = false;
  }
}

loadMarketTape(true);

function updateMarketTimer() {
  const now = new Date();
  const options = { timeZone: 'Asia/Jakarta', weekday: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };
  const formatter = new Intl.DateTimeFormat('en-US', options);
  const parts = formatter.formatToParts(now);
  const h = parseInt(parts.find(p => p.type === 'hour').value);
  const m = parseInt(parts.find(p => p.type === 'minute').value);
  const s = parseInt(parts.find(p => p.type === 'second').value);
  const weekday = parts.find(p => p.type === 'weekday').value;
  const isFriday = weekday === "Fri";
  const isWeekend = weekday === "Sat" || weekday === "Sun";
  const nowSeconds = h * 3600 + m * 60 + s;
  const sessionOne = { start: 9 * 3600, end: (isFriday ? 11.5 : 12) * 3600 };
  const sessionTwo = { start: (isFriday ? 14 : 13.5) * 3600, end: 15 * 3600 + 49 * 60 + 59 };
  const clock = `${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")} WIB`;
  const countdown = (seconds) => {
    const value = Math.max(0, Math.floor(seconds));
    const hours = Math.floor(value / 3600);
    const minutes = Math.floor((value % 3600) / 60);
    const secs = value % 60;
    return `${hours ? hours + "j " : ""}${minutes}m ${secs}d`;
  };
  const oneCard = document.querySelector("#session-one");
  const twoCard = document.querySelector("#session-two");
  oneCard.className = "session-card";
  twoCard.className = "session-card";
  document.querySelector("#session-one-hours").textContent = isFriday ? "09:00–11:30" : "09:00–12:00";
  document.querySelector("#session-two-hours").textContent = isFriday ? "14:00–15:49" : "13:30–15:49";
  let phase = "REGULAR MARKET CLOSED";
  let oneState = nowSeconds < sessionOne.start ? "Belum buka" : "Selesai";
  let twoState = nowSeconds < sessionTwo.start ? "Belum buka" : "Selesai";
  if (isWeekend) {
    phase = "BEI LIBUR · AKHIR PEKAN";
    oneState = twoState = "Libur";
  } else if (nowSeconds < sessionOne.start) {
    phase = `SESI 1 BUKA DALAM ${countdown(sessionOne.start - nowSeconds)}`;
    oneState = `Buka ${countdown(sessionOne.start - nowSeconds)}`;
    oneCard.classList.add("next");
  } else if (nowSeconds <= sessionOne.end) {
    phase = `SESI 1 AKTIF · TERSISA ${countdown(sessionOne.end - nowSeconds)}`;
    oneState = `Tutup ${countdown(sessionOne.end - nowSeconds)}`;
    oneCard.classList.add("active");
  } else if (nowSeconds < sessionTwo.start) {
    phase = `ISTIRAHAT · SESI 2 BUKA ${countdown(sessionTwo.start - nowSeconds)}`;
    twoState = `Buka ${countdown(sessionTwo.start - nowSeconds)}`;
    twoCard.classList.add("next");
  } else if (nowSeconds <= sessionTwo.end) {
    phase = `SESI 2 AKTIF · TERSISA ${countdown(sessionTwo.end - nowSeconds)}`;
    twoState = `Tutup ${countdown(sessionTwo.end - nowSeconds)}`;
    twoCard.classList.add("active");
  } else if (nowSeconds <= 16 * 3600 + 15 * 60) {
    phase = `REGULAR SELESAI · PASCAPENUTUPAN HINGGA 16:15`;
  }
  document.querySelector("#market-phase").textContent = phase;
  document.querySelector("#market-timer").textContent = clock;
  document.querySelector("#session-one-state").textContent = oneState;
  document.querySelector("#session-two-state").textContent = twoState;
}
setInterval(updateMarketTimer, 1000);
updateMarketTimer();
