/* TuDoanh Radar — giao diện điện thoại. JS thuần, đọc data/latest.json do job sau phiên ghi.
   Không tính toán gì ở đây: mọi con số đã được job tính, giao diện chỉ hiển thị — để thứ anh
   thấy trên màn hình đúng bằng thứ đã rung chuông (nguyên tắc KingStock). */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const CFG = window.TD_CONFIG || {};
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (n, d) => (n == null || isNaN(n)) ? "—" : Number(n).toLocaleString("vi-VN", { minimumFractionDigits: d == null ? 1 : d, maximumFractionDigits: d == null ? 1 : d });
  const ty = (v, d) => fmt(v / 1e9, d == null ? 1 : d);          // VND → tỷ
  const nty = (v) => fmt(v / 1e12, 1);                            // VND → nghìn tỷ
  const sign = (n) => n > 0 ? "+" : n < 0 ? "−" : "";
  const abs = Math.abs;
  const cls = (n) => n >= 0 ? "up" : "down";
  const dmy = (iso) => iso ? iso.slice(0, 10).split("-").reverse().join("/") : "—";
  const qlabel = (q) => q ? q.replace(/(\d{4})Q(\d)/, "Q$2/$1") : "—";
  const qend = (q) => { const m = /(\d{4})Q(\d)/.exec(q || ""); if (!m) return "—"; return ["31/03", "30/06", "30/09", "31/12"][+m[2] - 1] + "/" + m[1]; };

  let D = null;                 // latest.json
  let boardMode = "day";
  let curBroker = null;
  let diffSel = "ALL";
  let settings = {};
  let disabled = new Set();

  // ---------------------------------------------------------------- tải dữ liệu
  async function load() {
    try {
      const r = await fetch("data/latest.json", { cache: "no-cache" });
      if (!r.ok) throw new Error("Chưa có data/latest.json — job sau phiên chưa chạy lần nào");
      D = await r.json();
    } catch (err) {
      $("noticeText").textContent = err.message; $("noticeDot").style.background = "var(--down)";
      $("brokerBoard").innerHTML = `<div class="err">${esc(err.message)}</div>`;
      return;
    }
    settings = Object.assign({}, D.settings || {});
    disabled = new Set(settings.brokers_disabled || []);
    const active = D.brokers.filter((b) => b.quarter);
    const q = active.length ? active.map((b) => b.quarter).sort().pop() : null;
    $("qchip").textContent = qlabel(q);
    const lag = q ? Math.round((new Date(D.trade_date) - new Date(qend(q).split("/").reverse().join("-"))) / 864e5) : null;
    $("noticeText").innerHTML = q
      ? `Danh mục chốt <b>${qend(q)}</b>${lag != null ? " · trễ " + lag + " ngày" : ""}. Giá kết phiên <b>${dmy(D.trade_date)}</b>. Lãi/lỗ là <b>ước tính</b> với giả định CTCK chưa giao dịch thêm.`
      : "Chưa có báo cáo nào được chốt — bóc BCTC trên máy tính trước.";
    if (D.source && !D.source.dnse_ok) { $("noticeDot").style.background = "var(--down)"; $("noticeText").innerHTML += ` <b style="color:var(--down)">Nguồn giá DNSE lỗi: ${esc(D.source.dnse_error)}</b>`; }
    if (!(D.source && D.source.dnse_ok)) $("noticeDot").style.background = "var(--flag)";
    if (D.source && D.source.unsettled && D.source.unsettled.length) {
      // Chỉ xảy ra khi ép chạy (--force) lúc nguồn còn thiếu — giá các mã này là giữa phiên
      $("noticeDot").style.background = "var(--flag)";
      $("noticeText").innerHTML += ` <b style="color:var(--flag)">${D.source.unsettled.length} mã dùng giá chưa chốt (${esc(D.source.unsettled.slice(0, 6).join(", "))}${D.source.unsettled.length > 6 ? "…" : ""}).</b>`;
    }
    renderAll();
    fetchSettingsFromWorker();
  }
  function renderAll() { renderOver(); buildPicks(); renderPort(); buildDiffPicks(); renderDiff(); renderAlerts(); renderTrack(); renderSettings(); }
  const activeBrokers = () => D.brokers.filter((b) => !disabled.has(b.symbol));

  // ---------------------------------------------------------------- tab 1
  function renderOver() {
    const ind = D.industry || {};
    const list = activeBrokers();
    const nToday = list.filter((b) => b.today).length;
    $("overStats").innerHTML = `
      <div class="stat"><div class="k">Kết phiên ${dmy(D.trade_date).slice(0, 5)}</div><div class="v num ${cls(ind.today_change)}">${sign(ind.today_change)}${ty(abs(ind.today_change), 0)}<span class="u"> tỷ</span></div></div>
      <div class="stat"><div class="k">Lãi so giá vốn</div><div class="v num ${cls(ind.vs_cost_change)}">${sign(ind.vs_cost_change)}${ty(abs(ind.vs_cost_change), 0)}<span class="u"> tỷ</span></div></div>
      <div class="stat"><div class="k">Quy mô tự doanh</div><div class="v num">${nty(ind.size_total)}<span class="u"> ngh.tỷ</span></div></div>`;
    $("overH2").textContent = `${list.length} công ty chứng khoán`;
    const key = boardMode === "day" ? (b) => b.today && b.today.change : (b) => b.vs_cost && b.vs_cost.change;
    const sorted = list.slice().sort((a, b) => ((key(b) == null ? -Infinity : key(b)) - (key(a) == null ? -Infinity : key(a))));
    let max = 0; sorted.forEach((b) => { const v = key(b); if (v != null && abs(v) > max) max = abs(v); });
    $("brokerBoard").innerHTML = sorted.map((b) => {
      const main = key(b), other = boardMode === "day" ? (b.vs_cost && b.vs_cost.change) : (b.today && b.today.change);
      const hasAlert = (b.alerts || []).some((a) => a.hot);
      let right;
      if (b.pending) right = `<div class="v" style="font-size:12px;color:var(--text-mute);font-weight:500">chưa có số liệu</div><div class="dbar"></div><div class="d"><span class="chip flag">chờ bóc BCTC</span></div>`;
      else if (main == null) right = `<div class="v" style="font-size:12px;color:var(--text-mute);font-weight:500">không tính được</div><div class="dbar"></div><div class="d" style="color:var(--text-mute)">${b.detail ? "thiếu giá gốc" : "không thuyết minh mã"}</div>`;
      else {
        const pos = main >= 0, w = max ? abs(main) / max * 50 : 0;
        right = `<div class="v num ${cls(main)}">${sign(main)}${ty(abs(main), 0)} tỷ</div>
          <div class="dbar"><i style="${pos ? "left:50%;width:" + w + "%;background:var(--up)" : "right:50%;width:" + w + "%;background:var(--down)"}"></i></div>
          ${other == null ? `<div class="d" style="color:var(--text-mute)">${boardMode === "day" ? "so giá vốn" : "hôm nay"}: không tính được</div>`
            : `<div class="d num ${cls(other)}">${boardMode === "day" ? "so giá vốn " : "hôm nay "}${sign(other)}${ty(abs(other), 0)} tỷ</div>`}`;
      }
      const sub = b.pending ? `<span style="color:var(--text-mute)">mới thêm · chưa chốt báo cáo nào</span>`
        : `${b.size ? nty(b.size) + " ngh.tỷ" : "—"}${b.manual ? ` <span class="chip man">nhập tay</span>` : b.detail ? "" : ` · <span style="color:var(--text-mute)">không thuyết minh chi tiết</span>`}`;
      return `<button type="button" class="brow ${hasAlert ? "alert" : ""}" data-b="${b.symbol}">
        <div class="bmain"><div class="bsym"><span class="s">${b.symbol}</span><span class="n">${esc(b.name)}</span></div><div class="bsize num">${sub}</div></div>
        <div class="bpnl">${right}</div></button>`;
    }).join("") || `<div class="empty">Chưa có công ty nào.</div>`;
    $("overNote").innerHTML = `<b>Số "hôm nay" tính trên ${nToday} / ${list.length} công ty</b>Công ty không thuyết minh từng mã (hoặc chưa chốt báo cáo) không có gì để nhân với giá, nên hiện "không tính được" thay vì bịa số. Sàn có 50 CTCK niêm yết — thêm/bớt ở màn hình máy tính.`;
  }
  document.querySelectorAll(".seg.mini button").forEach((m) => m.addEventListener("click", () => {
    boardMode = m.dataset.mode;
    document.querySelectorAll(".seg.mini button").forEach((x) => x.setAttribute("aria-pressed", x === m ? "true" : "false"));
    renderOver();
  }));
  $("brokerBoard").addEventListener("click", (e) => { const b = e.target.closest("[data-b]"); if (b) openBroker(b.dataset.b); });

  // ---------------------------------------------------------------- tab 2
  const pickRow = $("pickRow");
  function buildPicks() {
    const list = activeBrokers();
    if (!list.some((b) => b.symbol === curBroker)) curBroker = (list.find((b) => b.detail) || list[0] || {}).symbol || null;
    pickRow.innerHTML = list.map((b) => `<button type="button" class="pick" data-s="${b.symbol}" aria-pressed="${b.symbol === curBroker}">${b.symbol}</button>`).join("");
  }
  pickRow.addEventListener("click", (e) => { const p = e.target.closest(".pick"); if (!p) return; curBroker = p.dataset.s; buildPicks(); renderPort(); });
  const srcChip = (s) => s === "manual" ? `<span class="chip man">nhập tay</span>` : s === "implied" ? `<span class="chip est">KL ước tính</span>` : `<span class="chip disc">công bố</span>`;
  function renderPort() {
    const b = D.brokers.find((x) => x.symbol === curBroker), body = $("portBody");
    if (!b) { body.innerHTML = `<div class="empty"><b>Chưa theo dõi công ty nào</b></div>`; return; }
    if (b.pending) { body.innerHTML = `<div class="empty"><b>${b.symbol} — chưa có báo cáo nào đã chốt</b>Mở màn hình máy tính, chạy bóc BCTC quý gần nhất của ${b.symbol} rồi duyệt. Sau khi chốt, danh mục hiện ở đây và cập nhật giá từ 15:20 hôm sau.</div>`; return; }
    const tot = b.totals || {};
    if (!b.detail) {
      body.innerHTML = `<div class="sumcard"><div class="sumtop">
        <div class="hero"><div class="k">Kết phiên ${dmy(D.trade_date)}</div><div class="big" style="font-size:18px;color:var(--text-mute);font-weight:600">không tính được</div></div>
        <div class="sumgrid">
          <div><span class="k">Tài sản tài chính ngắn hạn</span><span class="v num">${tot.st_fin_assets ? nty(tot.st_fin_assets) + " ngh.tỷ" : "—"}</span></div>
          <div><span class="k">AFS · HTM (VNDirect)</span><span class="v num">${tot.afs ? ty(tot.afs, 0) : "—"} · ${tot.htm ? ty(tot.htm, 0) : "—"} tỷ</span></div>
        </div></div></div>
        <div class="empty"><b>${b.symbol} không thuyết minh chi tiết từng mã</b>Báo cáo ${qlabel(b.quarter)} chỉ gộp thành một dòng, nên số tổng bên trên là từ VNDirect còn lãi/lỗ hôm nay không có gì để nhân với giá. Nếu biết danh mục từ nguồn khác, nhập tay ở màn hình máy tính — app sẽ gắn nhãn <span class="chip man">nhập tay</span>.</div>`;
      return;
    }
    const t = b.today, sq = b.since_quarter, vc = b.vs_cost;
    const whole = b.holdings.reduce((s, h) => s + (h.fair_value || 0), 0) + (b.other_fair || 0);
    const top = b.holdings.slice().sort((x, y) => (y.fair_value || 0) - (x.fair_value || 0)).slice(0, 5);
    const comp = top.map((h, i) => `<i style="width:${(h.fair_value || 0) / whole * 100}%;background:var(--c${i + 1})" title="${h.ticker}"></i>`).join("")
      + `<i class="other" style="width:${(whole - top.reduce((s, h) => s + (h.fair_value || 0), 0)) / whole * 100}%" title="Khác"></i>`;
    const leg = top.map((h, i) => `<span><i style="background:var(--c${i + 1})"></i>${h.ticker} ${fmt((h.fair_value || 0) / whole * 100, 1)}%</span>`).join("")
      + `<span><i class="other"></i>Khác ${fmt((whole - top.reduce((s, h) => s + (h.fair_value || 0), 0)) / whole * 100, 1)}%</span>`;
    const costCell = vc ? (vc.n_missing ? `<span class="v" style="font-size:12px;color:var(--text-mute);font-weight:500">${ty(vc.cost, 0)} tỷ · thiếu ${vc.n_missing} mã</span>` : `<span class="v num">${ty(vc.cost, 0)} tỷ</span>`) : `<span class="v" style="font-size:12px;color:var(--text-mute);font-weight:500">không có trong BCTC</span>`;
    const vcCell = vc ? `<span class="v num ${cls(vc.change)}">${sign(vc.change)}${ty(abs(vc.change), 1)} tỷ</span>` : `<span class="v" style="font-size:12px;color:var(--text-mute);font-weight:500">không tính được</span>`;
    body.innerHTML = `<div class="sumcard"><div class="sumtop">
      <div class="hero"><div class="k">Kết phiên ${dmy(D.trade_date)} · ${b.n_tracked} mã theo dõi được</div>
        <div class="big num ${cls(t.change)}">${sign(t.change)}${ty(abs(t.change), 1)}<span class="u">tỷ</span></div>
        <div class="pct num ${cls(t.change)}">${sign(t.pct)}${fmt(abs(t.pct), 2)}% <span>so với kết phiên hôm trước</span></div></div>
      <div class="sumgrid">
        <div><span class="k">Giá trị hôm nay</span><span class="v num">${ty(t.value, 0)} tỷ</span></div>
        <div><span class="k">Từ cuối quý ${qend(b.quarter)}</span><span class="v num ${cls(sq.change)}">${sign(sq.change)}${ty(abs(sq.change), 1)} tỷ</span></div>
        <div><span class="k">Giá gốc</span>${costCell}</div>
        <div><span class="k">Lãi/lỗ so giá vốn</span>${vcCell}</div>
      </div>
      <div class="compbar" role="img" aria-label="Tỷ trọng danh mục">${comp}</div><div class="legend">${leg}</div>
      <div class="srcline" style="padding:0">"Khác" = ${ty(b.other_fair, 0)} tỷ trái phiếu, cổ phiếu không nêu tên, chứng chỉ quỹ… — không có giá hằng ngày nên không nằm trong số hôm nay.</div>
    </div></div>
    <div class="hhead"><div>Mã</div><div>Khối lượng · giá gốc</div><div style="text-align:right">Hôm nay</div></div>
    <div id="hold">${b.holdings.map((h) => `<button type="button" class="hrow" data-t="${h.ticker}">
      <div class="hsym"><span class="s mono">${h.ticker}</span><span class="num" style="font-size:10.5px;color:var(--text-mute)">${ty(h.market_value, 1)} tỷ</span></div>
      <div class="hmid"><div class="kl"><span class="num">${fmt(h.quantity / 1e6, 2)} tr cp</span>${srcChip(h.quantity_source)}</div>
        <div>giá gốc ${h.cost_value ? `<span class="num">${ty(h.cost_value, 1)}</span> tỷ${h.cost_source === "manual" ? ` <span class="chip man">nhập tay</span>` : ""}` : `<span style="color:var(--text-mute)">không có</span>`}</div></div>
      <div class="hval">${h.stale_days > 0
        ? `<span class="v num" style="color:var(--text-mute)">0 tỷ</span><span class="c" style="color:var(--text-mute)">chưa khớp từ ${dmy(h.trade_date).slice(0, 5)}</span>`
        : `<span class="v num ${cls(h.d1)}">${sign(h.d1)}${ty(abs(h.d1), 1)} tỷ</span><span class="c num ${cls(h.d1)}">${sign(h.p1)}${fmt(abs(h.p1), 1)}%</span>`}</div></button>`).join("")}</div>
    <div class="srcline">BCTC ${b.stmt_type === "rieng" ? "riêng lẻ" : "hợp nhất"} ${qlabel(b.quarter)} · chốt ${dmy(b.approved_at)}</div>`;
    $("hold").addEventListener("click", (e) => { const r = e.target.closest("[data-t]"); if (r) openSheet(b, b.holdings.find((h) => h.ticker === r.dataset.t)); });
  }
  function openBroker(sym) { curBroker = sym; buildPicks(); renderPort(); switchTab("port"); const i = activeBrokers().findIndex((b) => b.symbol === sym); if (i > 3) pickRow.scrollLeft = (i - 2) * 58; }

  // ---------------------------------------------------------------- tab 3
  const diffPick = $("diffPickRow");
  function buildDiffPicks() {
    if (diffSel !== "ALL" && !activeBrokers().some((b) => b.symbol === diffSel)) diffSel = "ALL";
    diffPick.innerHTML = `<button type="button" class="pick" data-s="ALL" aria-pressed="${diffSel === "ALL"}">Toàn ngành</button>` + activeBrokers().map((b) => `<button type="button" class="pick" data-s="${b.symbol}" aria-pressed="${b.symbol === diffSel}">${b.symbol}</button>`).join("");
  }
  diffPick.addEventListener("click", (e) => { const p = e.target.closest(".pick"); if (!p) return; diffSel = p.dataset.s; buildDiffPicks(); renderDiff(); });
  const kindChip = { new: "new", add: "add", cut: "cut", out: "out", hold: "cut" };
  function diffRow(sym, chip, txt, val, up) {
    return `<div class="hrow" style="cursor:default"><div class="hsym"><span class="s mono">${sym}</span></div><div class="hmid">${chip ? `<div class="kl">${chip}</div>` : ""}<div>${txt}</div></div><div class="hval"><span class="v num ${up === null ? "" : up ? "up" : "down"}">${val}</span></div></div>`;
  }
  function renderDiff() {
    const body = $("diffBody"), ind = D.industry || {};
    if (diffSel === "ALL") {
      const ru = ind.rollup || [];
      body.innerHTML = `<div class="sechead"><h2>Toàn ngành · quý gần nhất so quý trước</h2><div class="meta">${ind.n_with_diff} công ty đủ 2 quý</div></div>
        <div class="stats"><div class="stat"><div class="k">Mua ròng</div><div class="v num up">+${ty(ind.buy, 0)}<span class="u"> tỷ</span></div></div>
        <div class="stat"><div class="k">Bán ròng</div><div class="v num down">−${ty(ind.sell, 0)}<span class="u"> tỷ</span></div></div>
        <div class="stat"><div class="k">Gom nhiều nhất</div><div class="v num">${ru.length && ru[0].net > 0 ? ru[0].ticker : "—"}</div></div></div>
        ${ru.length ? `<div class="hhead"><div>Mã</div><div>Số CTCK thay đổi</div><div style="text-align:right">Giá trị ròng</div></div>` + ru.slice(0, 30).map((r) => diffRow(r.ticker, "", [r.n_new && `${r.n_new} mua mới`, r.n_add && `${r.n_add} gom thêm`, r.n_cut && `${r.n_cut} bán bớt`, r.n_out && `${r.n_out} bán hết`].filter(Boolean).join(" · "), `${sign(r.net)}${ty(abs(r.net), 0)} tỷ`, r.net >= 0)).join("")
          : `<div class="empty"><b>Chưa công ty nào đủ hai quý đã chốt</b>Cần duyệt thêm quý trước ở màn hình máy tính thì mới so sánh được.</div>`}`;
      return;
    }
    const b = D.brokers.find((x) => x.symbol === diffSel);
    if (b.pending) { body.innerHTML = `<div class="empty"><b>${b.symbol} — chưa có báo cáo nào đã chốt</b></div>`; return; }
    if (!b.detail) { body.innerHTML = `<div class="empty"><b>${b.symbol} không thuyết minh chi tiết từng mã</b>Không có danh mục theo mã ở hai quý nên không so sánh được.</div>`; return; }
    const d = b.diff;
    if (!d) { body.innerHTML = `<div class="empty"><b>${b.symbol} mới có ${qlabel(b.quarter)} đã chốt</b>Cần duyệt thêm quý trước ở màn hình máy tính thì tab này mới so sánh được. Đây là trạng thái bình thường ngay sau mùa công bố BCTC.</div>`; return; }
    body.innerHTML = `<div class="sechead"><h2>${b.symbol} · ${qlabel(d.prev_quarter)} → ${qlabel(b.quarter)}</h2><div class="meta">${qend(d.prev_quarter)} so ${qend(b.quarter)}</div></div>
      <div class="stats"><div class="stat"><div class="k">Mua ròng</div><div class="v num up">+${ty(d.buy, 0)}<span class="u"> tỷ</span></div></div>
      <div class="stat"><div class="k">Bán ròng</div><div class="v num down">−${ty(d.sell, 0)}<span class="u"> tỷ</span></div></div>
      <div class="stat"><div class="k">Số mã</div><div class="v num">${d.n0}<span class="u"> → ${d.n1}</span></div></div></div>
      <div class="hhead"><div>Mã</div><div>Khối lượng ${qend(d.prev_quarter).slice(0, 5)} → ${qend(b.quarter).slice(0, 5)}</div><div style="text-align:right">Giá trị</div></div>
      ${d.rows.map((r) => {
        const txt = r.kind === "new" ? `Mua mới ${r.q1 ? fmt(r.q1 / 1e6, 2) + " triệu cp" : ty(r.v1, 0) + " tỷ"}` : r.kind === "out" ? `Bán hết ${r.q0 ? fmt(r.q0 / 1e6, 2) + " triệu cp" : ty(r.v0, 0) + " tỷ"}`
          : r.kind === "hold" ? `Giữ nguyên ${r.q1 ? fmt(r.q1 / 1e6, 2) + " triệu cp" : ""}` : (r.q0 && r.q1) ? `${fmt(r.q0 / 1e6, 2)} → ${fmt(r.q1 / 1e6, 2)} triệu cp` : `${ty(r.v0, 0)} → ${ty(r.v1, 0)} tỷ (theo giá trị)`;
        return diffRow(r.ticker, `<span class="chip ${kindChip[r.kind]}">${r.label}</span>`, txt, r.kind === "hold" ? "—" : `${sign(r.value)}${ty(abs(r.value), 1)} tỷ`, r.kind === "hold" ? null : r.value >= 0);
      }).join("")}`;
  }

  // ---------------------------------------------------------------- tab 4
  function renderAlerts() {
    const al = D.alerts || [];
    $("alertMeta").textContent = `${dmy(D.trade_date)} · gửi một lượt sau phiên`;
    $("navCount").hidden = !al.length; $("navCount").textContent = al.length;
    $("alertList").innerHTML = al.length ? al.map((a) => `<div class="alert"><div class="rulebadge ${a.hot ? "hot" : ""}">${a.rule}</div><div class="abody"><div class="atitle">${esc(a.title)}</div><div class="ameta">${esc(a.body)}</div></div></div>`).join("")
      : `<div class="empty">Phiên ${dmy(D.trade_date)} không có gì vượt ngưỡng.</div>`;
    const p = D.push || {};
    fetch("data/state.json", { cache: "no-cache" }).then((r) => r.ok ? r.json() : null).then((st) => {
      if (!st) return;
      // Job đã chạy nhưng nguồn DNSE chưa chốt nến hôm đó → chưa ghi kết quả, chờ cron sau.
      // Đây là lý do số trên app vẫn là của phiên trước dù đã quá 15:20.
      if (st.unsettled && st.unsettled.trade_date > (D.trade_date || "")) {
        $("noticeDot").style.background = "var(--flag)";
        $("noticeText").innerHTML += ` <b style="color:var(--flag)">Phiên ${dmy(st.unsettled.trade_date)}: nguồn giá chưa chốt lúc ${st.unsettled.at.slice(11, 16)} (${st.unsettled.tickers.length} mã chưa có ATC) — job sẽ thử lại 15:50 / 16:30 / 18:00.</b>`;
      }
      if (!st.devices) return;
      const d = st.devices;
      const line = d.n ? `Job nhìn thấy <b>${d.n} máy</b> đã đăng ký (kiểm tra ${st.devices.checked_at.slice(11, 16)} ${dmy(d.checked_at)})${st.welcome ? " · đã gửi chào mừng " + dmy(st.welcome.at) : ""}`
        : `<b style="color:var(--down)">Job chưa thấy máy nào</b> — Secret PUSH_SUBS_FALLBACK trên GitHub chưa có hoặc trống (kiểm tra ${d.checked_at.slice(11, 16)} ${dmy(d.checked_at)})`;
      $("srcInfo").innerHTML += "<br>" + line;
    }).catch(() => {});
    $("srcInfo").innerHTML = `Chạy lúc ${D.generated_at ? D.generated_at.slice(11, 16) + " " + dmy(D.generated_at) : "—"} · giá ${D.source ? D.source.n_priced + "/" + D.source.n_tickers : "—"} mã` + (p.skipped ? " · chưa gửi thông báo (chạy thử)" : ` · đã gửi ${p.sent || 0} thông báo tới ${p.n_devices || 0} máy${p.gone ? ` · <b style="color:var(--down)">${p.gone} máy đã huỷ đăng ký — bấm Bật lại</b>` : ""}`);
  }
  function renderTrack() {
    const list = D.brokers;
    $("trackMeta").textContent = `${list.filter((b) => !disabled.has(b.symbol)).length} đang bật / ${list.length}`;
    $("trackList").innerHTML = list.map((b) => `<div class="trow ${disabled.has(b.symbol) ? "off" : ""}">
      <div class="nm"><span class="s">${b.symbol}</span><span class="n">${esc(b.name)}</span></div>
      ${b.pending ? `<span class="chip flag">chờ bóc BCTC</span>` : b.manual ? `<span class="chip man">nhập tay</span>` : b.detail ? `<span class="chip disc">${qlabel(b.quarter)}${b.diff ? " + " + qlabel(b.diff.prev_quarter) : ""}</span>` : `<span class="chip disc">chỉ số tổng</span>`}
      <div><button type="button" class="tbtn" data-tg="${b.symbol}">${disabled.has(b.symbol) ? "Bật" : "Tắt"}</button></div></div>`).join("");
  }
  $("trackList").addEventListener("click", (e) => {
    const b = e.target.closest("[data-tg]"); if (!b) return;
    const s = b.dataset.tg; disabled.has(s) ? disabled.delete(s) : disabled.add(s);
    settings.brokers_disabled = [...disabled]; saveSettings(); renderAll();
  });
  function renderSettings() {
    $("r1").value = settings.r1_pct; $("r1v").textContent = settings.r1_pct + "%"; $("r1min").textContent = ty(settings.r1_min_value, 0);
    $("r2").value = settings.r2_value / 1e9; $("r2v").textContent = ty(settings.r2_value, 0) + " tỷ";
    $("r4").value = settings.r4_pct; $("r4v").textContent = "±" + settings.r4_pct + "%";
  }
  $("r1").addEventListener("input", () => { settings.r1_pct = +$("r1").value; $("r1v").textContent = settings.r1_pct + "%"; });
  $("r2").addEventListener("input", () => { settings.r2_value = +$("r2").value * 1e9; $("r2v").textContent = ty(settings.r2_value, 0) + " tỷ"; });
  $("r4").addEventListener("input", () => { settings.r4_pct = +$("r4").value; $("r4v").textContent = "±" + settings.r4_pct + "%"; });
  ["r1", "r2", "r4"].forEach((id) => $(id).addEventListener("change", saveSettings));
  let saveTimer = null;
  async function saveSettings() {
    clearTimeout(saveTimer);
    if (!CFG.WORKER_URL) { $("setSaved").innerHTML = `Chưa cấu hình Worker — ngưỡng chỉ hiển thị. Sửa trong <span class="mono">site/data/settings.json</span> trên máy tính.`; return; }
    saveTimer = setTimeout(async () => {
      try {
        const body = {}; ["r1_pct", "r1_min_value", "r2_value", "r3_weight", "r3_pct", "r4_pct", "brokers_disabled"].forEach((k) => { if (settings[k] != null) body[k] = settings[k]; });
        const r = await fetch(CFG.WORKER_URL + "/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        $("setSaved").textContent = r.ok ? `Đã lưu · có hiệu lực từ lần chạy 15:20 kế tiếp` : `Lưu lỗi ${r.status}`;
      } catch (err) { $("setSaved").textContent = "Không kết nối được Worker: " + err.message; }
    }, 400);
  }
  async function fetchSettingsFromWorker() {
    if (!CFG.WORKER_URL) return;
    try {
      const r = await fetch(CFG.WORKER_URL + "/settings", { cache: "no-cache" });
      if (r.ok) { const s = await r.json(); if (s && Object.keys(s).length) { Object.assign(settings, s); disabled = new Set(settings.brokers_disabled || []); renderAll(); } }
    } catch (_) { /* Worker chưa có — dùng ngưỡng từ latest.json */ }
  }

  // ---------------------------------------------------------------- push
  const b64ToU8 = (s) => { const p = "=".repeat((4 - s.length % 4) % 4); const b = atob((s + p).replace(/-/g, "+").replace(/_/g, "/")); return Uint8Array.from(b, (c) => c.charCodeAt(0)); };
  /* Hai chế độ đăng ký thông báo:
     - Có Worker (CFG.WORKER_URL): bấm Bật là xong, địa chỉ tự gửi lên kho.
     - Không Worker (cách GitHub Pages như BCTC Radar): bấm Bật → hiện đoạn mã → anh dán vào
       GitHub Secret PUSH_SUBS_FALLBACK một lần mỗi máy. Job đọc Secret đó để gửi. */
  async function pushStatus() {
    const st = $("pushState"), txt = st.querySelector("span:last-child");
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) { txt.textContent = "Trình duyệt này không hỗ trợ thông báo đẩy"; $("pushBtn").disabled = true; return; }
    if (!CFG.VAPID_PUBLIC) { txt.textContent = "Chưa có VAPID_PUBLIC trong config.js"; $("pushBtn").disabled = true; return; }
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      st.classList.add("on");
      txt.textContent = CFG.WORKER_URL ? "Máy này đã đăng ký · máy chủ tạm của GitHub có thể đánh thức kể cả khi app đóng"
        : "Máy này đã tạo địa chỉ nhận · đảm bảo đoạn mã bên dưới đã được dán vào GitHub";
      $("pushBtn").textContent = "Đăng ký lại"; $("testBtn").hidden = !CFG.WORKER_URL;
      if (!CFG.WORKER_URL) showSubCode(sub);
    } else { st.classList.remove("on"); txt.textContent = "Máy này chưa đăng ký nhận thông báo"; }
  }
  function showSubCode(sub) {
    let box = $("subCode");
    if (!box) {
      box = document.createElement("div"); box.id = "subCode"; box.className = "empty"; box.style.margin = "8px 0 0";
      $("pushHelp").parentNode.insertBefore(box, $("pushHelp"));
    }
    const code = JSON.stringify([sub.toJSON()]);
    box.innerHTML = `<b>Đoạn mã đăng ký của máy này</b>Dán vào GitHub → Settings → Secrets and variables → Actions → <span class="mono">PUSH_SUBS_FALLBACK</span> (nhiều máy thì nối các đoạn trong cùng một mảng JSON). Làm một lần mỗi máy.
      <textarea id="subTxt" readonly style="width:100%;height:70px;margin-top:8px;font-family:IBM Plex Mono,monospace;font-size:10px;background:var(--surface);color:inherit;border:1px solid var(--line);border-radius:7px;padding:6px"></textarea>
      <div style="margin-top:6px"><button type="button" class="btn" id="copySub">Sao chép</button></div>`;
    $("subTxt").value = code;
    $("copySub").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(code); showToast("Đã sao chép", "Dán vào GitHub Secret PUSH_SUBS_FALLBACK."); }
      catch (_) { $("subTxt").select(); document.execCommand("copy"); showToast("Đã sao chép", ""); }
    });
  }
  const swReady = () => Promise.race([
    navigator.serviceWorker.ready,
    new Promise((_, rej) => setTimeout(() => rej(new Error("Phần chạy nền (service worker) chưa sẵn sàng — đóng hẳn app, mở lại rồi bấm lần nữa")), 8000)),
  ]);
  $("pushBtn").addEventListener("click", async () => {
    const st = $("pushState"), txt = st.querySelector("span:last-child"), btn = $("pushBtn");
    const say = (s) => { txt.textContent = s; };
    btn.disabled = true;
    try {
      if (Notification.permission === "denied") {
        say("Điện thoại đang CHẶN thông báo của app này. Mở Cài đặt → Ứng dụng → TuDoanh → Thông báo → bật, rồi bấm lại.");
        return;
      }
      say("Đang xin quyền thông báo… (nếu hiện hộp thoại, bấm Cho phép)");
      const perm = await Notification.requestPermission();
      if (perm !== "granted") { say("Anh chưa cho phép. Bấm lại và chọn Cho phép; nếu không thấy hộp thoại, bật trong Cài đặt → Ứng dụng → TuDoanh → Thông báo."); return; }
      say("Đang chuẩn bị phần chạy nền…");
      if (!navigator.serviceWorker.controller) { try { await navigator.serviceWorker.register("sw.js?v=8b8cca2f"); } catch (_) { /* thử tiếp */ } }
      const reg = await swReady();
      say("Đang tạo địa chỉ nhận với Google…");
      let sub = await reg.pushManager.getSubscription();
      if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToU8(CFG.VAPID_PUBLIC) });
      if (CFG.WORKER_URL) {
        const r = await fetch(CFG.WORKER_URL + "/subscribe", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.assign({ ua: navigator.userAgent.slice(0, 120) }, sub.toJSON())) });
        if (!r.ok) throw new Error("Worker trả lỗi " + r.status);
        showToast("Đã đăng ký máy này", "Từ giờ cảnh báo sau phiên sẽ tới đây. Bấm 'Gửi thử' để kiểm tra đường dây.");
      } else {
        showToast("Đã tạo địa chỉ nhận", "Sao chép đoạn mã bên dưới và dán vào GitHub — một lần cho máy này.");
      }
      await pushStatus();
    } catch (err) {
      say("Không đăng ký được: " + (err && err.message ? err.message : err) + " — chụp màn hình dòng này gửi lại.");
    } finally { btn.disabled = false; }
  });
  $("testBtn").addEventListener("click", async () => {
    try {
      const r = await fetch(CFG.WORKER_URL + "/test", { method: "POST" });
      showToast(r.ok ? "Đã yêu cầu gửi thử" : "Gửi thử lỗi " + r.status, r.ok ? "Thông báo thật sẽ tới trong vài giây, kể cả khi anh đóng app." : "");
    } catch (err) { alert(err.message); }
  });
  const toast = $("toast"); let toastTimer = null;
  function showToast(t, b) { $("toastTitle").textContent = t; $("toastBody").textContent = b || ""; toast.classList.add("on"); clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.classList.remove("on"), 5000); }
  toast.addEventListener("click", () => toast.classList.remove("on"));

  // ---------------------------------------------------------------- sheet
  const wrap = $("sheetWrap");
  function openSheet(b, h) {
    $("shSym").textContent = h.ticker; $("shSub").textContent = `${b.symbol} nắm giữ · ${h.asset_class}`;
    const vc = h.vs_cost, sq = h.since_q;
    $("shBody").innerHTML = `<dl class="kv">
      ${h.stale_days > 0
        ? `<dt><b>Kết phiên ${dmy(D.trade_date)}</b></dt><dd style="color:var(--text-mute);font-weight:500">không khớp lệnh — ${h.stale_days} ngày chưa có giao dịch</dd>
      <dt>Giá cuối cùng</dt><dd class="num">${fmt(h.close, 0)} đ <span style="color:var(--text-mute);font-weight:500">(phiên ${dmy(h.trade_date)})</span></dd>`
        : `<dt><b>Kết phiên ${dmy(D.trade_date)}</b></dt><dd class="num ${cls(h.d1)}" style="font-size:16px">${sign(h.d1)}${ty(abs(h.d1), 2)} tỷ · ${sign(h.p1)}${fmt(abs(h.p1), 1)}%</dd>
      <dt>Giá đóng cửa</dt><dd class="num">${fmt(h.close, 0)} đ (hôm trước ${fmt(h.prev_close, 0)})</dd>`}
      <dt>Khối lượng</dt><dd class="num">${fmt(h.quantity, 0)} cp</dd>
      <dt>Nguồn khối lượng</dt><dd>${h.quantity_source === "manual" ? `<span class="chip man">nhập tay</span>` : h.quantity_source === "implied" ? `<span class="chip est">ước tính từ giá</span>` : `<span class="chip disc">công bố trong BCTC</span>`}</dd>
      ${h.cost_value ? `<dt>Giá gốc${h.cost_source === "manual" ? ` <span class="chip man">nhập tay</span>` : ""}</dt><dd class="num">${ty(h.cost_value, 2)} tỷ</dd>` : `<dt>Giá gốc</dt><dd style="color:var(--text-mute);font-weight:500">không có trong BCTC</dd>`}
      <dt>Giá trị hợp lý ${qend(b.quarter)}</dt><dd class="num">${ty(h.fair_value, 2)} tỷ</dd>
      <dt>Giá trị hôm nay</dt><dd class="num">${ty(h.market_value, 2)} tỷ</dd>
      ${vc != null ? `<dt>Lãi/lỗ so giá vốn</dt><dd class="num ${cls(vc)}">${sign(vc)}${ty(abs(vc), 2)} tỷ</dd>` : `<dt>Lãi/lỗ so giá vốn</dt><dd style="color:var(--text-mute);font-weight:500">không tính được</dd>`}
      ${sq != null ? `<dt>Biến động từ cuối quý</dt><dd class="num ${cls(sq)}">${sign(sq)}${ty(abs(sq), 2)} tỷ</dd>` : ""}
      <dt>Tỷ trọng danh mục</dt><dd class="num">${fmt(h.weight * 100, 2)}%</dd></dl>
      ${h.quantity_source === "implied" ? `<div class="empty" style="margin:0"><b>Khối lượng này là suy ra</b>${b.symbol} không ghi số lượng trong thuyết minh. App lấy giá trị hợp lý chia cho giá đóng cửa ngày ${qend(b.quarter)} để có khối lượng gần đúng. Muốn sửa: nhập tay ở màn hình máy tính.</div>` : ""}`;
    wrap.classList.add("on");
  }
  const closeSheet = () => wrap.classList.remove("on");
  $("shClose").addEventListener("click", closeSheet);
  wrap.addEventListener("click", (e) => { if (e.target === wrap) closeSheet(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSheet(); });

  // ---------------------------------------------------------------- tab + boot
  const tabs = document.querySelectorAll('nav[role="tablist"] button');
  function switchTab(name) {
    tabs.forEach((x) => x.setAttribute("aria-selected", x.dataset.tab === name ? "true" : "false"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("on", p.id === "p-" + name));
    $("main").scrollTop = 0;
  }
  tabs.forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));
  function applyHash() {
    const m = /#port=([A-Z]{3})/.exec(location.hash);
    if (m && D) { openBroker(m[1]); return; }
    if (location.hash === "#alert") switchTab("alert");
  }
  window.addEventListener("hashchange", applyHash);

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js?v=8b8cca2f").catch(() => {});
  load().then(() => { applyHash(); pushStatus(); });
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") load(); });
})();
