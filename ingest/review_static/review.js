/* Màn hình duyệt — JS thuần, gọi API của review_server.py */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const api = async (path, opt) => {
    const r = await fetch("/api" + path, Object.assign({ headers: { "Content-Type": "application/json" } }, opt || {}));
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.detail || ("Lỗi " + r.status));
    return body;
  };
  const ty = (v) => v == null ? "" : (v / 1e9).toLocaleString("vi-VN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const parseTy = (s) => { const v = parseFloat(String(s || "").replace(/\./g, "").replace(",", ".")); return isNaN(v) ? null : Math.round(v * 1e9); };
  const parseInt_ = (s) => { const v = parseFloat(String(s || "").replace(/[\.\s]/g, "").replace(",", ".")); return isNaN(v) ? null : v; };
  const fmtInt = (v) => v == null ? "" : Math.round(v).toLocaleString("vi-VN");
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  let quarter = "";
  let queueData = null;
  let current = null;       // báo cáo đang duyệt
  let curPage = 1;
  let pollTimer = null;

  // ---------------------------------------------------------------- health
  api("/health").then((h) => {
    const el = $("health");
    el.textContent = h.api_key ? `Khoá Claude: có · ${h.extract_model}` : "Chưa có ANTHROPIC_API_KEY trong .env — bước 2, 3 sẽ kẹt";
    el.className = "pill " + (h.api_key ? "ok" : "bad");
  });

  // ---------------------------------------------------------------- hàng đợi
  const STEP_TEXT = {
    queued: "Đang chờ đến lượt", fetching: "Đang tải PDF từ trang IR", locating: "Đang tìm trang thuyết minh",
    extracting: "Đang đọc ảnh bằng Claude (1–3 phút)", validating: "Đang đối chiếu 4 kiểm tra",
  };
  function progHtml(rep) {
    const bars = [];
    for (let i = 1; i <= 5; i++) {
      let cls = "";
      if (!rep) cls = "";
      else if (rep.status === "approved") cls = "done";
      else if (rep.status === "review") cls = i <= 4 ? "done" : "wait";
      else if (rep.status === "stuck") { const si = { fetching: 1, locating: 2, extracting: 3, validating: 4 }[rep.stuck_step] || 1; cls = i < si ? "done" : i === si ? "stop" : ""; }
      else { const si = rep.step; cls = i < si ? "done" : i === si ? "run" : ""; }
      bars.push(`<i class="${cls}"></i>`);
    }
    return `<span class="prog">${bars.join("")}</span>`;
  }
  function statusText(rep) {
    if (!rep) return `<span class="t">Chưa bắt đầu quý này</span>`;
    if (rep.status === "approved") return `<span class="t">Đã chốt ${rep.approved_at ? rep.approved_at.slice(0, 10).split("-").reverse().join("/") : ""} · ${rep.n_rows} dòng${rep.n_rows === 0 ? " · chỉ giữ số tổng" : ""}</span>`;
    if (rep.status === "review") return `<span class="t"><b>Chờ anh duyệt</b> · ${rep.n_rows} dòng · ${rep.n_flag ? rep.n_flag + " dòng gắn cờ" : "sạch, không cờ"}${rep.n_missing ? " · " + rep.n_missing + " dòng thiếu số" : ""}</span>`;
    if (rep.status === "stuck") return `<span class="t"><b style="color:var(--down)">Kẹt</b> ở bước ${({ fetching: "tải PDF", locating: "tìm trang", extracting: "đọc ảnh", validating: "đối chiếu" })[rep.stuck_step] || rep.stuck_step} — ${esc(rep.stuck_reason)}</span>`;
    return `<span class="t">${STEP_TEXT[rep.status] || rep.status}${rep.note_pages ? " · trang " + rep.note_pages : ""}</span>`;
  }
  function actionsHtml(row) {
    const rep = row.report;
    if (!rep) return `<button class="tbtn" data-act="manual" data-b="${row.broker}">Nhập tay</button>`;
    if (rep.status === "approved") return `<button class="tbtn" data-act="open" data-id="${rep.id}">Mở lại</button>`;
    if (rep.status === "review") return `<button class="tbtn hot" data-act="open" data-id="${rep.id}">Duyệt</button>`;
    if (rep.status === "stuck") {
      if (rep.stuck_step === "fetching") return `<input placeholder="Dán URL PDF…" data-url="${rep.id}"><button class="tbtn" data-act="resume" data-id="${rep.id}">Chạy</button><button class="tbtn" data-act="manual" data-b="${row.broker}">Nhập tay</button>`;
      if (rep.stuck_step === "locating") return `<input placeholder="Số trang, VD: 23,24" data-pages="${rep.id}" style="width:150px"><button class="tbtn" data-act="resume" data-id="${rep.id}">Chạy</button>`;
      return `<button class="tbtn" data-act="resume" data-id="${rep.id}">Chạy lại</button>`;
    }
    return rep.running ? `<span class="small">đang chạy…</span>` : `<button class="tbtn" data-act="resume" data-id="${rep.id}">Chạy tiếp</button>`;
  }
  async function loadQueue() {
    queueData = await api("/queue" + (quarter ? "?quarter=" + quarter : ""));
    quarter = queueData.quarter;
    $("qLabel").textContent = queueData.label;
    const sel = $("qSel");
    sel.innerHTML = queueData.quarters.map((q) => `<option value="${q}" ${q === quarter ? "selected" : ""}>${q.replace(/(\d+)Q(\d)/, "Q$2/$1")}</option>`).join("") + `<option value="__new">Quý khác…</option>`;
    const reps = queueData.rows.filter((r) => r.report).map((r) => r.report);
    const c = (s) => reps.filter((r) => r.status === s).length;
    const running = reps.filter((r) => !["approved", "review", "stuck"].includes(r.status)).length;
    $("qSum").textContent = reps.length ? `${c("approved")} đã chốt · ${c("review")} chờ anh duyệt · ${running} đang chạy · ${c("stuck")} kẹt` : "Chưa bắt đầu — bấm nút bên phải";
    $("queue").innerHTML = queueData.rows.filter((r) => r.enabled).map((row) => `
      <div class="qrow">
        <div class="nm"><span class="s">${row.broker}</span><span class="n">${esc(row.name)}</span></div>
        <div class="qstat">${progHtml(row.report)}${statusText(row.report)}</div>
        <div class="qact">${actionsHtml(row)}</div>
      </div>`).join("") || `<div class="qrow"><div class="small">Chưa có công ty nào được bật.</div></div>`;
    clearTimeout(pollTimer);
    if (running) pollTimer = setTimeout(loadQueue, 3000);
  }
  $("qSel").addEventListener("change", (e) => {
    if (e.target.value === "__new") { const q = prompt("Nhập quý dạng 2026Q3:"); if (q) quarter = q.toUpperCase(); }
    else quarter = e.target.value;
    loadQueue().catch(alert);
  });
  $("startBtn").addEventListener("click", async () => {
    if (!confirm(`Bắt đầu tải và đọc BCTC ${queueData.label} cho mọi công ty đang bật?`)) return;
    await api("/start", { method: "POST", body: JSON.stringify({ quarter }) });
    loadQueue();
  });
  $("rerunStuckBtn").addEventListener("click", async () => {
    const stuck = queueData.rows.filter((r) => r.report && r.report.status === "stuck");
    for (const r of stuck) await api(`/report/${r.report.id}/resume`, { method: "POST", body: JSON.stringify({}) });
    loadQueue();
  });
  $("queue").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-act]"); if (!b) return;
    const id = b.dataset.id;
    try {
      if (b.dataset.act === "open") await openReport(id);
      else if (b.dataset.act === "resume") {
        const urlEl = document.querySelector(`input[data-url="${id}"]`), pgEl = document.querySelector(`input[data-pages="${id}"]`);
        await api(`/report/${id}/resume`, { method: "POST", body: JSON.stringify({ pdf_url: urlEl ? urlEl.value.trim() : "", pages: pgEl ? pgEl.value.trim() : "" }) });
        loadQueue();
      } else if (b.dataset.act === "manual") {
        const r = await api("/report/manual", { method: "POST", body: JSON.stringify({ broker: b.dataset.b, quarter }) });
        await loadQueue(); await openReport(r.id);
      }
    } catch (err) { alert(err.message); }
  });
  $("exportBtn").addEventListener("click", async () => {
    $("exportBtn").disabled = true;
    try { const r = await api("/export", { method: "POST" }); alert(`Đã ghi holdings.json (${r.reports} báo cáo đã chốt).\n${r.push}`); }
    catch (err) { alert(err.message); } finally { $("exportBtn").disabled = false; }
  });

  // ---------------------------------------------------------------- duyệt
  async function openReport(id) {
    current = await api("/report/" + id);
    $("reviewCard").hidden = false;
    $("rvTitle").textContent = `Duyệt số liệu · ${current.broker} · ${current.quarter.replace(/(\d+)Q(\d)/, "Q$2/$1")}`;
    const u = current.usage ? ` · ${current.usage.input} vào / ${current.usage.output} ra token` : "";
    $("rvMeta").textContent = `BCTC ${current.stmt_type === "rieng" ? "riêng lẻ" : "hợp nhất"} · ${current.page_count || "?"} trang · thuyết minh trang ${current.note_pages || "?"} · ${current.model_used || "chưa đọc"}${current.extracted_at ? " lúc " + current.extracted_at.slice(11, 16) : ""}${u}`;
    const nf = current.holdings.filter((h) => !h.deleted && h.flags).length;
    $("rvFlag").hidden = !nf; $("rvFlag").textContent = `${nf} dòng cần xem lại`;
    $("approveBtn").textContent = current.status === "approved" ? "Chốt lại (đã sửa)" : "Chốt báo cáo";
    $("rvMsg").hidden = true;
    renderChecks(); renderTable();
    // ảnh trang
    const pages = (current.note_pages || "").split(",").filter(Boolean).map(Number);
    $("pgNote").innerHTML = pages.map((p) => `<option value="${p}">thuyết minh tr.${p}</option>`).join("");
    showPage(pages[0] || 1);
    $("reviewCard").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function showPage(p) {
    if (!current.page_count) { $("pgImg").removeAttribute("src"); $("pgLabel").textContent = "không có PDF (nhập tay)"; return; }
    curPage = Math.min(Math.max(1, p), current.page_count);
    $("pgImg").src = `/api/report/${current.id}/page/${curPage}`;
    $("pgLabel").textContent = `trang ${curPage}/${current.page_count}`;
    $("pgInput").value = curPage;
  }
  $("pgPrev").addEventListener("click", () => showPage(curPage - 1));
  $("pgNext").addEventListener("click", () => showPage(curPage + 1));
  $("pgInput").addEventListener("change", (e) => showPage(parseInt(e.target.value, 10) || 1));
  $("pgNote").addEventListener("change", (e) => showPage(parseInt(e.target.value, 10)));
  $("rvClose").addEventListener("click", () => { $("reviewCard").hidden = true; current = null; });

  function renderChecks() {
    const cs = current.checks || [];
    $("checks").innerHTML = cs.length ? cs.map((c) => `<div class="check ${c.ok === null ? "na" : c.ok ? "ok" : "warn"}"><span class="m">${c.ok === null ? "–" : c.ok ? "✓" : "!"}</span><span>${esc(c.msg)}</span></div>`).join("")
      : `<div class="check na"><span class="m">–</span><span>Chưa đối chiếu (báo cáo nhập tay hoặc chưa qua bước 4)</span></div>`;
    const f = current.finfo || {};
    if (f.st_fin_assets) $("checks").insertAdjacentHTML("beforeend", `<div class="check na"><span class="m">i</span><span>VNDirect cùng kỳ: TSTC ngắn hạn ${ty(f.st_fin_assets)} tỷ · AFS ${ty(f.afs)} tỷ · HTM ${ty(f.htm)} tỷ · tổng tài sản ${ty(f.total_assets)} tỷ</span></div>`);
    $("notes").hidden = !current.notes; $("notes").textContent = current.notes ? "Ghi chú của model: " + current.notes : "";
  }
  function srcChip(s) { return s === "manual" ? `<span class="chip man">nhập tay</span>` : s === "implied" ? `<span class="chip est">ước tính</span>` : `<span class="chip disc">công bố</span>`; }
  function renderTable() {
    const closes = current.closes || {};
    $("tbody").innerHTML = current.holdings.map((h) => {
      const group = !h.ticker;
      const src = [h.quantity_source, h.cost_source, h.fair_source];
      const chips = src.includes("manual") ? srcChip("manual") : src.includes("implied") ? srcChip("implied") : srcChip("disclosed");
      const flags = (h.flags || "").split(";").filter(Boolean).map((f) => f === "qty_price_mismatch" ? `<span class="chip flag" title="KL × giá cuối quý lệch quá 15% so với GT hợp lý">KL×giá lệch</span>` : f === "unlisted" ? `<span class="chip bad">không niêm yết</span>` : `<span class="chip flag">${esc(f)}</span>`).join(" ");
      const px = closes[h.ticker] ? `<span class="small">giá 30/06: ${closes[h.ticker].toLocaleString("vi-VN")}</span>` : "";
      return `<tr data-id="${h.id}" class="${h.flags ? "flagged" : ""} ${h.deleted ? "deleted" : ""} ${group ? "group" : ""}">
        <td><input class="mono" data-f="ticker" value="${esc(h.ticker)}" style="width:70px;text-transform:uppercase" placeholder="(gộp)"></td>
        <td><select data-f="asset_class">${["FVTPL", "AFS", "HTM"].map((c) => `<option ${c === h.asset_class ? "selected" : ""}>${c}</option>`).join("")}</select></td>
        <td><span class="lbl" title="${esc(h.raw_label)}">${esc(h.raw_label)}</span>${px}</td>
        <td><input class="num" data-f="quantity" value="${fmtInt(h.quantity)}" placeholder="—"></td>
        <td><input class="num" data-f="cost_value" value="${ty(h.cost_value)}" placeholder="—"></td>
        <td><input class="num" data-f="fair_value" value="${ty(h.fair_value)}" placeholder="—"></td>
        <td style="text-align:center"><input type="checkbox" data-f="is_listed" ${h.is_listed ? "checked" : ""} title="Cổ phiếu đang niêm yết → theo dõi giá hằng ngày"></td>
        <td>${chips} ${flags}</td>
        <td><button class="tbtn" data-del="${h.id}" title="${h.deleted ? "Khôi phục" : "Bỏ dòng"}">${h.deleted ? "↺" : "×"}</button></td>
      </tr>`;
    }).join("") || `<tr><td colspan="9" class="small">Chưa có dòng nào — gõ thêm ở ô bên dưới.</td></tr>`;
  }
  $("tbody").addEventListener("change", async (e) => {
    const el = e.target, tr = el.closest("tr"), id = tr && tr.dataset.id, f = el.dataset.f;
    if (!id || !f) return;
    const body = {};
    if (f === "ticker" || f === "asset_class") body[f] = el.value;
    else if (f === "quantity") body.quantity = parseInt_(el.value);
    else if (f === "cost_value" || f === "fair_value") body[f] = parseTy(el.value);
    else if (f === "is_listed") body.is_listed = el.checked;
    if (body[f] === null && f !== "is_listed") return;
    try {
      const h = await api("/holding/" + id, { method: "PATCH", body: JSON.stringify(body) });
      const i = current.holdings.findIndex((x) => x.id == id); current.holdings[i] = h; renderTable();
    } catch (err) { alert(err.message); }
  });
  $("tbody").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-del]"); if (!b) return;
    const id = b.dataset.del, h0 = current.holdings.find((x) => x.id == id);
    const h = await api("/holding/" + id, { method: "PATCH", body: JSON.stringify({ deleted: !h0.deleted }) });
    const i = current.holdings.findIndex((x) => x.id == id); current.holdings[i] = h; renderTable();
  });
  $("addBtn").addEventListener("click", async () => {
    const t = $("nT").value.trim().toUpperCase(); if (!t) { $("nT").focus(); return; }
    try {
      const h = await api(`/report/${current.id}/holding`, { method: "POST", body: JSON.stringify({ ticker: t, asset_class: $("nC").value, quantity: parseInt_($("nQ").value), cost_value: parseTy($("nCost").value), fair_value: parseTy($("nFair").value) }) });
      current.holdings.push(h); renderTable();
      ["nT", "nQ", "nCost", "nFair"].forEach((i) => $(i).value = ""); $("nT").focus();
    } catch (err) { alert(err.message); }
  });
  $("rerunExtract").addEventListener("click", async () => { if (!confirm("Đọc ảnh lại sẽ XOÁ mọi dòng hiện có (kể cả sửa tay) và tốn phí API. Tiếp tục?")) return; await api(`/report/${current.id}/rerun/extracting`, { method: "POST" }); $("reviewCard").hidden = true; loadQueue(); });
  $("rerunValidate").addEventListener("click", async () => { await api(`/report/${current.id}/rerun/validating`, { method: "POST" }); $("reviewCard").hidden = true; loadQueue(); });
  $("approveBtn").addEventListener("click", async () => {
    const miss = current.holdings.filter((h) => !h.deleted && h.is_listed && h.ticker && h.fair_value == null).length;
    if (miss && !confirm(`${miss} dòng cổ phiếu niêm yết chưa có giá trị hợp lý — sẽ không tính được. Vẫn chốt?`)) return;
    $("approveBtn").disabled = true;
    try {
      const r = await api(`/report/${current.id}/approve`, { method: "POST" });
      const m = $("rvMsg"); m.hidden = false; m.className = "msg ok"; m.textContent = `Đã chốt. holdings.json: ${r.push}`;
      loadQueue();
    } catch (err) { const m = $("rvMsg"); m.hidden = false; m.className = "msg bad"; m.textContent = err.message; }
    finally { $("approveBtn").disabled = false; }
  });

  // ---------------------------------------------------------------- công ty
  async function loadBrokers() {
    const bs = await api("/brokers");
    $("bSum").textContent = `${bs.filter((b) => b.enabled).length} đang bật / ${bs.length} trong danh sách`;
    $("brokers").innerHTML = bs.map((b) => `
      <div class="qrow ${b.enabled ? "" : "off"}">
        <div class="nm"><span class="s">${b.symbol} <span class="small">${b.floor || ""}</span></span><span class="n">${esc(b.name)}</span></div>
        <div class="qstat"><input value="${esc(b.ir_url)}" data-ir="${b.symbol}" placeholder="Trang IR chứa link PDF (hỗ trợ {q} {y})" style="width:100%"></div>
        <div class="qact"><button class="tbtn" data-bact="ir" data-s="${b.symbol}">Lưu URL</button><button class="tbtn" data-bact="toggle" data-s="${b.symbol}" data-en="${b.enabled}">${b.enabled ? "Tắt" : "Bật"}</button><button class="tbtn" data-bact="del" data-s="${b.symbol}" style="color:var(--down)">Xoá hẳn</button></div>
      </div>`).join("");
  }
  $("brokers").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-bact]"); if (!b) return;
    const s = b.dataset.s;
    try {
      if (b.dataset.bact === "toggle") await api("/brokers", { method: "POST", body: JSON.stringify({ symbol: s, enabled: b.dataset.en !== "true" }) });
      else if (b.dataset.bact === "ir") await api("/brokers", { method: "POST", body: JSON.stringify({ symbol: s, enabled: true, ir_url: document.querySelector(`input[data-ir="${s}"]`).value.trim() }) });
      else if (b.dataset.bact === "del") { if (!confirm(`Xoá hẳn ${s} cùng mọi báo cáo đã duyệt? "Tắt" thì giữ lại được.`)) return; await api("/brokers/" + s, { method: "DELETE" }); }
      await loadBrokers(); await loadQueue();
    } catch (err) { alert(err.message); }
  });
  $("uniBtn").addEventListener("click", async () => {
    const box = $("uni"); box.hidden = false; box.innerHTML = `<div class="small">Đang lấy danh sách từ VNDirect…</div>`;
    try {
      const [uni, bs] = await Promise.all([api("/universe"), api("/brokers")]);
      const have = new Set(bs.map((b) => b.symbol));
      box.innerHTML = uni.filter((u) => !have.has(u.code)).map((u) => `<div class="urow"><span><b>${u.code}</b><span class="fl">${u.floor}</span><br><span class="small">${esc(u.name)}</span></span><button class="tbtn" data-add="${u.code}" data-n="${esc(u.name)}" data-fl="${u.floor}">+ Thêm</button></div>`).join("") || `<div class="small">Đã theo dõi hết.</div>`;
    } catch (err) { box.innerHTML = `<div class="small">Lỗi: ${esc(err.message)}</div>`; }
  });
  $("uni").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-add]"); if (!b) return;
    await api("/brokers", { method: "POST", body: JSON.stringify({ symbol: b.dataset.add, name: b.dataset.n, floor: b.dataset.fl, enabled: true }) });
    b.closest(".urow").remove(); await loadBrokers(); await loadQueue();
  });

  loadQueue().then(loadBrokers).catch((e) => alert(e.message));
})();
