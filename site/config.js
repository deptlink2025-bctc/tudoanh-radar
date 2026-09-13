/* Cấu hình giao diện — sửa hai dòng này sau khi deploy Worker và sinh khoá VAPID.
   VAPID_PUBLIC lấy từ:  venv\Scripts\python -m job.gen_vapid  (phải trùng với Secret trên GitHub)
   WORKER_URL là địa chỉ Cloudflare Worker, VD https://tudoanh-radar.<tên>.workers.dev  (để trống = chưa có) */
window.TD_CONFIG = {
  VAPID_PUBLIC: "",
  WORKER_URL: "",
};
