/* Cấu hình giao diện — sửa hai dòng này sau khi deploy Worker và sinh khoá VAPID.
   VAPID_PUBLIC lấy từ:  venv\Scripts\python -m job.gen_vapid  (phải trùng với Secret trên GitHub)
   WORKER_URL là địa chỉ Cloudflare Worker, VD https://tudoanh-radar.<tên>.workers.dev  (để trống = chưa có) */
window.TD_CONFIG = {
  VAPID_PUBLIC: "BMWrL-L4Mr2R1X80kM5a85bkY3fZOnjXZcjRK1y9TmntX_-kTSusbQj6T3eiD4tFFwvTP9-87KYcNrigGj0hj6o",
  WORKER_URL: "",
};
