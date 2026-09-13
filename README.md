# TuDoanh Radar — theo dõi danh mục tự doanh CTCK

App theo dõi danh mục tự doanh của các công ty chứng khoán niêm yết: cổ phiếu nắm giữ, giá trị
kết phiên hôm nay, lãi/lỗ so giá vốn, thay đổi theo quý, cảnh báo cuối ngày lên điện thoại.

**Không có máy chủ.** Chi phí vận hành ≈ 45.000 đ/quý (Claude đọc ảnh BCTC), còn lại 0 đ.

```
MÁY TÍNH (4 lần/năm)      start-review.bat → tải PDF → Claude đọc ảnh → đối chiếu → ANH DUYỆT → chốt
                                                                                        ↓ git push
GITHUB ACTIONS (15:20 T2–T6)   giá DNSE → tính danh mục → 4 quy tắc → Web Push → commit site/data/*.json
                                                                                        ↓
CLOUDFLARE PAGES               giao diện điện thoại (site/) đọc site/data/latest.json
CLOUDFLARE WORKER              nhận đăng ký thông báo + cất ngưỡng cảnh báo (KV)
```

Vì sao phải đọc ảnh: BCTC quý của CTCK là **PDF scan** không có text (đã kiểm chứng VCI, SSI,
SHS Q2/2026). Chi tiết từng mã không có ở API nào. Xem `docs` trong kế hoạch gốc.

## Cấu trúc

| Thư mục | Chạy ở đâu | Việc gì |
|---|---|---|
| `ingest/` | máy tính | tải PDF, tìm trang, đọc ảnh (Claude), đối chiếu, màn hình duyệt (`localhost:8100`), xuất `holdings.json` |
| `job/` | GitHub Actions | giá, định giá, so quý, cảnh báo, push |
| `site/` | Cloudflare Pages | PWA điện thoại; `site/data/` là dữ liệu job ghi |
| `worker/` | Cloudflare Worker | 50 dòng nhận đăng ký push + cài đặt |
| `common/` | cả hai | client DNSE, VNDirect finfo, quý, cấu hình |
| `tests/` | máy tính | `pytest`, không cần mạng |

## Cài đặt trên máy tính (một lần)

1. Cài Python 3.12, git.
2. Chạy `install.bat`. Nó tạo `venv`, cài thư viện, tạo `.env`, chạy test.
3. Mở `.env`, điền `ANTHROPIC_API_KEY` (lấy tại console.anthropic.com, nạp tối thiểu 5 USD). Lưu UTF-8.
4. Chạy `start-review.bat` → trình duyệt mở `http://localhost:8100`.

## Mỗi quý (khoảng ngày 20–30 sau khi hết quý)

1. Mở `start-review.bat`, bấm **Bắt đầu quý này**. Máy tự tải PDF, tìm trang, đọc ảnh, đối chiếu
   cho mọi công ty đang bật (~1–2 phút/công ty, chạy nền).
2. Dòng nào **Chờ anh duyệt** → bấm **Duyệt**: bên trái là ảnh trang gốc, bên phải là bảng.
   Sửa ô sai (mang nhãn *nhập tay*), bỏ dòng thừa, bấm **Chốt báo cáo**. App tự xuất
   `site/data/holdings.json` và `git push`.
3. Dòng **Kẹt**: dán URL PDF (trang IR đổi cấu trúc) hoặc gõ số trang (không tìm được bảng), bấm Chạy.
4. Công ty không thuyết minh từng mã (SSI): chốt với 0 dòng — app chỉ giữ số tổng từ VNDirect.

Cần 2 quý liên tiếp đã chốt thì tab **Thay đổi** mới so sánh được.

## Deploy lần đầu (một lần, ~30 phút)

### GitHub
1. Tạo repo **private**, push toàn bộ thư mục này lên nhánh `main`.
2. Sinh khoá thông báo: `venv\Scripts\python -m job.gen_vapid` → 3 dòng.
3. Repo → Settings → Secrets and variables → Actions → thêm:
   `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`, `WORKER_URL`, `WORKER_TOKEN`
   (và `PUSH_SUBS_FALLBACK` để trống).
4. Actions → bật workflow `daily`. Bấm **Run workflow** một lần để kiểm tra.

### Cloudflare Worker (miễn phí, không cần thẻ)
```
cd worker
npx wrangler login
npx wrangler kv namespace create SUBS        # dán id vào wrangler.toml
npx wrangler secret put TOKEN                # chuỗi bất kỳ dài, dùng lại làm WORKER_TOKEN trên GitHub
npx wrangler deploy                          # in ra https://tudoanh-radar.<tên>.workers.dev
```
Sửa `ALLOW_ORIGIN` trong `wrangler.toml` thành địa chỉ Pages (bước dưới) rồi deploy lại.

### Cloudflare Pages
Workers & Pages → Create → Pages → Connect to Git → chọn repo → Build output directory: `site`
(không có lệnh build). Địa chỉ dạng `https://tudoanh-radar.pages.dev`. Mỗi lần job commit
`site/data/*.json`, Pages tự deploy lại.

### Nối giao diện
Sửa `site/config.js`: `VAPID_PUBLIC` = khoá public ở bước 2, `WORKER_URL` = địa chỉ Worker. Commit.

### Trên điện thoại
Mở địa chỉ Pages bằng Chrome → menu → **Thêm vào màn hình chính** → mở app → tab Cảnh báo →
**Bật thông báo trên máy này** → **Gửi thử**. Thông báo thật đến trong ~1 phút.

## Chạy tay khi cần

```
venv\Scripts\python -m job.run_daily --dry-run     # in kết quả, không ghi, không gửi
venv\Scripts\python -m job.run_daily --force --no-push
venv\Scripts\python -m job.push --test             # gửi thông báo thử từ máy tính (cần .env đủ khoá)
venv\Scripts\python -m ingest.export               # xuất + push holdings.json
venv\Scripts\python -m pytest tests -q
```

## Nguyên tắc số liệu (đừng phá)

- Mọi con số truy về một dòng trong `holdings.json`, mỗi dòng mang nhãn nguồn
  `disclosed` (công bố) / `implied` (KL suy từ giá trị ÷ giá cuối quý) / `manual` (nhập tay).
- Chỉ báo cáo **đã chốt** mới được xuất, mới hiện trên app, mới dùng để cảnh báo.
- Không tính được thì hiện đúng chữ đó. Không bịa.
- Giá DNSE trả theo **nghìn đồng**; `common/dnse.py` đã nhân 1000 — mọi nơi khác dùng VND.
- "Hôm nay" = so kết phiên hôm trước. "So giá vốn" = lãi/lỗ trên giấy. Không dùng "chưa thực hiện".

## Rủi ro đã biết

- DNSE và VNDirect finfo là API không chính thức. Lỗi → `site/data/state.json` ghi `dnse_error`,
  giao diện hiện chấm đỏ, thứ Hai không có nhịp tim.
- Trang IR của CTCK đổi cấu trúc → kẹt bước tải → dán URL tay. Chỉ SHS, SSI đã xác minh; các URL
  khác trong `ingest/brokers.py` cần sửa dần khi gặp.
- GitHub cron có thể trễ 10–30 phút; có cron dự phòng 08:50 UTC.
