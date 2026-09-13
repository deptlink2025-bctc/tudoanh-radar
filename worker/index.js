/* Cloudflare Worker — kho nhỏ cho hai thứ giao diện tĩnh không tự cất được:
   1. địa chỉ đẩy thông báo của từng điện thoại (POST /subscribe từ trang, GET /subs từ job)
   2. ngưỡng cảnh báo + công ty tắt (GET/PUT /settings)
   Ngoài ra POST /test đặt cờ để job gửi một thông báo thử ở lần chạy kế (hoặc gửi ngay nếu
   bật GitHub dispatch — xem README).

   Deploy một lần: npx wrangler deploy. KV binding tên SUBS. Biến môi trường:
     TOKEN        — job trên GitHub dùng để đọc /subs (Bearer)
     ALLOW_ORIGIN — địa chỉ trang Cloudflare Pages, VD https://tudoanh-radar.pages.dev
*/
const json = (obj, status = 200, extra = {}) =>
  new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json; charset=utf-8", ...extra } });

async function sha16(s) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 16);
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const origin = req.headers.get("Origin") || "";
    const allow = env.ALLOW_ORIGIN || "*";
    const cors = {
      "Access-Control-Allow-Origin": allow === "*" ? "*" : (origin === allow ? origin : allow),
      "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type,Authorization",
    };
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });

    const authed = req.headers.get("Authorization") === `Bearer ${env.TOKEN}`;
    const path = url.pathname.replace(/\/+$/, "");

    // --- điện thoại đăng ký ---
    if (path === "/subscribe" && req.method === "POST") {
      let sub;
      try { sub = await req.json(); } catch { return json({ error: "JSON hỏng" }, 400, cors); }
      if (!sub || !sub.endpoint || !sub.keys || !sub.keys.p256dh || !sub.keys.auth) return json({ error: "Thiếu endpoint/keys" }, 400, cors);
      const id = await sha16(sub.endpoint);
      await env.SUBS.put("sub:" + id, JSON.stringify({ endpoint: sub.endpoint, keys: sub.keys, ua: sub.ua || "", at: new Date().toISOString() }));
      return json({ ok: true, id }, 200, cors);
    }

    // --- job đọc danh sách / xoá địa chỉ chết ---
    if (path === "/subs" && req.method === "GET") {
      if (!authed) return json({ error: "unauthorized" }, 401, cors);
      const list = await env.SUBS.list({ prefix: "sub:" });
      const subs = [];
      for (const k of list.keys) { const v = await env.SUBS.get(k.name, "json"); if (v) subs.push(v); }
      return json(subs, 200, cors);
    }
    if (path.startsWith("/subs/") && req.method === "DELETE") {
      if (!authed) return json({ error: "unauthorized" }, 401, cors);
      await env.SUBS.delete("sub:" + path.slice(6));
      return json({ ok: true }, 200, cors);
    }

    // --- ngưỡng cảnh báo + công ty tắt ---
    if (path === "/settings" && req.method === "GET") {
      const s = await env.SUBS.get("settings", "json");
      return json(s || {}, 200, cors);
    }
    if (path === "/settings" && req.method === "PUT") {
      // Trang tĩnh gọi không có token (app cá nhân). Muốn khoá chặt: đặt PUT_TOKEN và gửi
      // header Authorization từ config.js — xem README.
      if (env.PUT_TOKEN && req.headers.get("Authorization") !== `Bearer ${env.PUT_TOKEN}`) return json({ error: "unauthorized" }, 401, cors);
      let body;
      try { body = await req.json(); } catch { return json({ error: "JSON hỏng" }, 400, cors); }
      const allowed = ["r1_pct", "r1_min_value", "r2_value", "r3_weight", "r3_pct", "r4_pct", "brokers_disabled"];
      const clean = {};
      for (const k of allowed) if (k in body) clean[k] = body[k];
      const prev = (await env.SUBS.get("settings", "json")) || {};
      await env.SUBS.put("settings", JSON.stringify({ ...prev, ...clean, updated_at: new Date().toISOString() }));
      return json({ ok: true }, 200, cors);
    }

    // --- gửi thử: đặt cờ; job đọc cờ và gửi test_payload rồi xoá ---
    if (path === "/test" && req.method === "POST") {
      await env.SUBS.put("test_requested", new Date().toISOString(), { expirationTtl: 86400 });
      if (env.GH_TOKEN && env.GH_REPO) {
        // Kích hoạt job ngay (workflow_dispatch) để thông báo thử tới trong ~1 phút thay vì đợi 15:20
        await fetch(`https://api.github.com/repos/${env.GH_REPO}/actions/workflows/daily.yml/dispatches`, {
          method: "POST",
          headers: { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "tudoanh-worker", "Content-Type": "application/json" },
          body: JSON.stringify({ ref: "main", inputs: { test_push: "true" } }),
        }).catch(() => {});
      }
      return json({ ok: true }, 200, cors);
    }
    if (path === "/test" && req.method === "GET") {
      if (!authed) return json({ error: "unauthorized" }, 401, cors);
      const v = await env.SUBS.get("test_requested");
      if (v) await env.SUBS.delete("test_requested");
      return json({ requested: !!v }, 200, cors);
    }

    return json({ ok: true, service: "tudoanh-radar worker" }, 200, cors);
  },
};
