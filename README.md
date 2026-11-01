# videoservice

Thư viện Python để dùng dịch vụ tạo video riêng (ComfyUI + MiniMax H3) — dành cho nhóm bạn được mời.
Bạn cần **API key** (`vs_...`) và **URL dịch vụ** do chủ dịch vụ gửi riêng. Không có key thì thư viện không làm gì được.

> Sắp có: MCP server để dùng thẳng trong Claude Code ("làm cho tôi video 5 giây ...").

## Cài đặt

Cần Python 3.10 trở lên.

```bash
pip install git+https://github.com/lepdat/videoservice-client
```

Cập nhật bản mới:

```bash
pip install -U git+https://github.com/lepdat/videoservice-client
```

## Cấu hình

Đặt hai biến môi trường (hoặc truyền thẳng vào `Client(...)`):

```bash
export VIDEOSERVICE_URL="<URL chủ dịch vụ gửi>"
export VIDEOSERVICE_API_KEY="vs_..."
```

Trên Windows PowerShell: `$env:VIDEOSERVICE_URL = "..."` và `$env:VIDEOSERVICE_API_KEY = "vs_..."`.

## Dùng

```python
from videoservice import Client

c = Client()                      # đọc URL + key từ biến môi trường
print(c.balance())                # số dư, đang giữ, đã dùng hôm nay, giới hạn
print(c.pricing())                # bảng giá (VND)

paths = c.run(workflow, save_dir="out")   # gửi → chờ → tải kết quả về out/
```

`workflow` là workflow ComfyUI dạng **API format** (dict `{"<node_id>": {"class_type": ..., "inputs": {...}}}`).
Xem node dùng được: `c.list_nodes()` (lọc: `c._req("GET", "/nodes", params={"q": "video"})`), chi tiết một node:
`c.node_schema("SaveVideo")`.

Từng bước, nếu muốn tự điều khiển:

```python
job = c.submit(workflow, inputs={"anh.png": "duong/dan/anh.png"}, max_cost_vnd=20000)
status = c.wait(job["job_id"])           # queued → running → succeeded / failed / cancelled
files = c.download(job["job_id"], "out")
c.cancel(job["job_id"])                  # hủy job đang chạy, chỉ tính phần đã chạy
```

Lỗi từ dịch vụ là `VideoServiceError` với `code`, lời giải thích và gợi ý sửa; lỗi workflow nằm trong `e.errors`.

## Tiền

- Trả trước bằng chuyển khoản cho chủ dịch vụ; dùng đến đâu trừ đến đó theo **giây máy chạy thật** (gồm cả thời gian
  khởi động và nạp model).
- Khi gửi job, dịch vụ **giữ** trước số tiền tối đa; xong job chỉ trừ phần đã dùng, phần thừa trả lại.
  Đặt `max_cost_vnd` để giới hạn một job.
- Lỗi do hệ thống được hoàn tiền; lỗi do workflow vẫn tính phần đã chạy.
- Kết quả giữ 7 ngày; link tải có hạn 1 giờ (gọi lại `c.result(job_id)` để lấy link mới).

## Điều khoản

Video được tạo bằng MiniMax H3 — *Powered by MiniMax H3*, theo **MiniMax H3 Community License**. Khi nhận key, bạn đồng ý
với điều khoản chủ dịch vụ gửi kèm, gồm: không dùng dịch vụ hoặc video tạo ra ở EU, Anh, Hàn Quốc, Mỹ; không dùng video để
huấn luyện model AI khác; ghi rõ "do AI tạo" khi đăng công khai; tuân thủ chính sách sử dụng của MiniMax H3.
