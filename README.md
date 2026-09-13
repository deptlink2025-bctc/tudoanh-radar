# TuDoanh Radar — theo dõi danh mục tự doanh CTCK

App theo dõi danh mục tự doanh của các công ty chứng khoán niêm yết: cổ phiếu nắm giữ, giá trị
kết phiên hôm nay, lãi/lỗ so giá vốn, thay đổi theo quý, cảnh báo cuối ngày lên điện thoại.

**Không có máy chủ.** Chi phí vận hành ≈ 130.000 đ/quý (Claude đọc ảnh BCTC, ~0,3 USD/báo cáo × 15), còn lại 0 đ.

```
MÁY TÍNH (4 lần/năm)      start-review.bat → tải PDF → Claude đọc ảnh → đối chiếu → ANH DUYỆT → chốt
                                                                                        ↓ git push
GITHUB ACTIONS (15:20 T2–T6)   giá DNSE → tính danh mục → 4 quy tắc → Web Push → commit docs/data/*.json
                                                                                        ↓
GITHUB PAGES                   giao diện điện thoại (docs/) đọc docs/data/latest.json
(tuỳ chọn) CLOUDFLARE WORKER  nhận đăng ký thông báo một chạm + cất ngưỡng cảnh báo
```

Vì sao phải đọc ảnh: BCTC quý của CTCK là **PDF scan** không có text (đã kiểm chứng VCI, SSI,
SHS Q2/2026). Chi tiết từng mã không có ở API nào. Xem `docs` trong kế hoạch gốc.

## Cấu trúc

| Thư mục | Chạy ở đâu | Việc gì |
|---|---|---|
| `ingest/` | máy tính | tải PDF, tìm trang, đọc ảnh (Claude), đối chiếu, màn hình duyệt (`localhost:8100`), xuất `holdings.json` |
| `job/` | GitHub Actions | giá, định giá, so quý, cảnh báo, push |
| `docs/` | GitHub Pages | PWA điện thoại; `docs/data/` là dữ liệu job ghi |
| `worker/` | Cloudflare Worker (tuỳ chọn) | 50 dòng nhận đăng ký push + cài đặt |
| `common/` | cả hai | client DNSE, VNDirect finfo, quý, cấu hình |
| `tests/` | máy tính | `pytest`, không cần mạng |

## Cài đặt trên máy tính (một lần)

1. Cài Python 3.12, git.
2. Chạy `install.bat`. Nó tạo `venv`, cài thư viện, tạo `.env`, chạy test.
3. Mở `.env`, điền `ANTHROPIC_API_KEY` (lấy tại console.anthropic.com, nạp tối thiểu 5 USD). Lưu UTF-8.
4. Chạy `start-review.bat` → trình duyệt mở `http://localhost:8100`.

## Mỗi quý (khoảng ngày 20–30 sau khi hết quý)

1. Mở `start-review.bat`, bấm **Bắt đầu quý này**. Máy tự tải PDF, tìm trang, đọc ảnh, đối chiếu
   cho mọi công ty đang bật (~2–5 phút/công ty, chạy nền). Nguồn PDF: trang IR riêng (SSI, SHS, HCM) hoặc kho Vietstock cho mọi mã.
2. Dòng nào **Chờ anh duyệt** → bấm **Duyệt**: bên trái là ảnh trang gốc, bên phải là bảng.
   Sửa ô sai (mang nhãn *nhập tay*), bỏ dòng thừa, bấm **Chốt báo cáo**. App tự xuất
   `docs/data/holdings.json` và `git push`.
3. Dòng **Kẹt**: dán URL PDF (trang IR đổi cấu trúc) hoặc gõ số trang (không tìm được bảng), bấm Chạy.
4. Công ty không nêu tên mã (AGR, DSE, MBS, ORS, TCX, VIX…): chỉ có các dòng nhóm — app hiện quy mô và số tổng, "hôm nay" ghi không tính được.

Cần 2 quý liên tiếp đã chốt thì tab **Thay đổi** mới so sánh được.

## Deploy lần đầu — cách GitHub Pages, giống BCTC Radar (không cần Cloudflare, không dòng lệnh)

1. **Tạo repo public** tên `tudoanh-radar` trên github.com (Repositories → New → Public → Create).
   Public vì GitHub Pages miễn phí chỉ cho repo public — code và số liệu bóc từ BCTC công khai;
   mọi khoá nằm trong Secrets, không nằm trong repo.
2. **Đẩy code lên** — chạy hai lệnh trong PowerShell (lần đầu Windows mở trình duyệt hỏi đăng nhập GitHub):
   ```
   cd "C:\Claude code	udoanh-radar"
   git remote add origin https://github.com/<TÊN-GITHUB>/tudoanh-radar.git
   git push -u origin master:main
   ```
3. **Bật Pages**: repo → Settings → Pages → *Build and deployment*: Source = *Deploy from a branch*,
   Branch = `main`, thư mục **`/docs`** → Save. Vài phút sau có link `https://<tên>.github.io/tudoanh-radar/`.
4. **Nạp khoá**: Settings → Secrets and variables → Actions → *New repository secret*, tạo 3 cái
   (giá trị lấy trong `data/deploy_secrets.txt` trên máy tính): `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`.
5. **Bật job**: tab Actions → *I understand my workflows, go ahead and enable them* → workflow `daily` → *Run workflow* một lần.
6. **Điện thoại**: mở link Pages bằng Chrome → ⋮ → *Cài đặt ứng dụng* → mở từ màn hình chính → tab Cảnh báo →
   **Bật thông báo** → cho phép → bấm **Sao chép** đoạn mã hiện ra → về máy tính tạo Secret thứ 4:
   `PUSH_SUBS_FALLBACK` = đoạn mã đó (thêm máy thứ hai thì nối hai đoạn trong cùng một mảng `[ {...}, {...} ]`).
7. **Thử**: Actions → `daily` → *Run workflow* → `test_push` = true → điện thoại rung sau ~1 phút.

Ngưỡng cảnh báo: sửa `docs/data/settings.json` (xem `job/settings.py` cho các khoá), commit & push.

### Nâng cấp tuỳ chọn: Cloudflare Worker (bật thông báo một chạm, thanh trượt ngưỡng lưu được)
Xem `worker/`. Deploy xong điền `WORKER_URL` vào `docs/config.js` và thêm Secrets `WORKER_URL`, `WORKER_TOKEN`.

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

- DNSE và VNDirect finfo là API không chính thức. Lỗi → `docs/data/state.json` ghi `dnse_error`,
  giao diện hiện chấm đỏ, thứ Hai không có nhịp tim.
- Web IR của CTCK phần lớn dựng bằng JS hoặc chặn máy → dùng Vietstock (`ingest/vietstock.py`). Vietstock đổi API thì kẹt bước tải → dán URL PDF tay.
- GitHub cron có thể trễ 10–30 phút; có cron dự phòng 08:50 UTC.
