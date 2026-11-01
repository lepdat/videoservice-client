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

## Tạo video bằng một dòng

```python
from videoservice import text_to_video, image_to_video

path = text_to_video("Phố cổ Hà Nội lúc hoàng hôn", seconds=5, resolution="768P")
print(path)                                # h3_00001_.mp4

path = image_to_video("anh.png", "Con mèo vẫy đuôi", seconds=5)   # ảnh là khung hình đầu
```

Hàm gửi job, in tiến độ, chờ xong rồi tải video về và trả đường dẫn file (`pathlib.Path`). Không cần biết workflow ComfyUI.

- `resolution`: `"480P"` (mặc định) hoặc `"768P"`. **Tối đa 768P** (1344×768).
- `seconds`: số giây video (mặc định 5; giới hạn theo độ phân giải: `Client().list_templates()["limits"]`).
- `max_cost_vnd=30000`: giới hạn tiền cho job này. Dịch vụ giữ trước khoảng 1,5 lần giá ước tính (phần thừa trả
  lại); nếu giới hạn thấp hơn số tiền giữ đó thì hàm báo lỗi `max_cost_below_hold` và **không gửi job**, vì job có thể
  bị cắt giữa chừng mà vẫn mất tiền. Số tiền giữ của từng loại video: `hold_vnd` trong `Client().pricing()["h3_video"]`.
- `save_dir="out"`: thư mục lưu video (mặc định thư mục hiện tại).
- `portrait=True`: video dọc; `seed=2`: đổi để ra kết quả khác; `upscale="2K"`: xem [Cần video 2K?](#cần-video-2k).
- `image` của `image_to_video`: đường dẫn hoặc `bytes` ảnh PNG/JPG; ảnh được cắt giữa cho vừa khung video.
- `on_progress=None`: không in tiến độ.
- `client=Client(api_key=..., base_url=...)`: dùng key/URL khác thay vì biến môi trường.

Giá ước tính trước khi chạy: `Client().pricing()["h3_video"]`. Job lỗi thì hàm raise `VideoServiceError` (xem dưới).

### Cần video 2K?

Dịch vụ tạo tối đa 768P. Có hai cách lên 2K:

- `text_to_video(..., resolution="768P", upscale="2K")` (cả `image_to_video`): dịch vụ phóng video lên 1440p
  (768P → 2520×1440) bằng SeedVR2 ngay trong job, giữ nguyên tiếng; tối đa 10 giây video. Lâu và đắt hơn video thường
  nhiều lần (5 giây 2K mất ~10 phút, ~2.900đ, giữ trước ~4.300đ; 10 giây ~21 phút, ~5.900đ, giữ trước ~8.900đ),
  xem `Client().pricing()["h3_video"]`.
- Tự upscale video đã tải về (lên được cả 4K), ví dụ:
  - [Video2X](https://github.com/k4yt3x/video2x) (miễn phí, chạy trên GPU của máy bạn, dùng Real-ESRGAN / Real-CUGAN).
  - [Topaz Video AI](https://www.topazlabs.com/topaz-video-ai) (trả phí, dễ dùng).
  - Chỉ phóng to, không thêm chi tiết: `ffmpeg -i in.mp4 -vf scale=-2:1440:flags=lanczos -c:a copy out.mp4`.

## Tự điều khiển

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

Video MiniMax H3 dựng sẵn (không cần tự viết workflow):

```python
t = c.template("h3_t2v", prompt="Phố cổ Hà Nội lúc hoàng hôn", resolution="768P", seconds=5)
print(t["estimate"])                      # giá, tiền giữ, thời gian chờ ước tính
paths = c.run(t["workflow"], save_dir="out")
```

- `resolution`: `480P` hoặc `768P`; `seconds`: số giây video; `portrait=True`: video dọc; `upscale="2K"`: xem
  [Cần video 2K?](#cần-video-2k), chi phí trong `t["estimate"]`.
- `c.template("h3_i2v", image="anh.png", ...)` lấy ảnh làm khung hình đầu: gửi kèm
  `c.run(t["workflow"], save_dir="out", inputs={"anh.png": "duong/dan/anh.png"})`.
- Danh sách tham số: `c.list_templates()`.

Từng bước, nếu muốn tự điều khiển:

```python
job = c.submit(workflow, inputs={"anh.png": "duong/dan/anh.png"}, max_cost_vnd=20000)
status = c.wait(job["job_id"])           # queued → running → succeeded / failed / cancelled
files = c.download(job["job_id"], "out")
c.cancel(job["job_id"])                  # hủy job đang chạy, chỉ tính phần đã chạy
```

### Xem tiến độ

Mỗi job đều phải khởi động máy và nạp model (~30–50 giây), rồi mới tạo. Để biết job đang ở bước nào:

```python
from videoservice import Client, print_progress

c.wait(job["job_id"], on_progress=print_progress)    # cũng dùng được: c.run(workflow, on_progress=print_progress)
# job_ab12: Đang chờ máy (GPU), còn khoảng 90 giây
# job_ab12: Đang khởi động và nạp model, còn khoảng 88 giây
# job_ab12: Đang tạo: bước 3/8, còn khoảng 41 giây
# job_ab12: Đang giải mã và lưu kết quả, còn khoảng 12 giây
```

`on_progress` nhận dict của job, được gọi mỗi khi giai đoạn, bước hoặc vị trí trong hàng đổi. `c.job(job_id)["progress"]` cho biết tiến độ
hiện tại (hết `None` khi job đã xong):

- `stage`: `in_queue` (xếp hàng chờ tới lượt dùng GPU khi nhiều người cùng gửi, không tính tiền) → `waiting_for_machine` (chờ máy, không tính tiền) → `loading_model` → `generating` → `saving` (video 2K: thêm `upscaling` trước bước lưu cuối)
- `step` / `steps`: bước đang tạo (chỉ khi `generating`)
- `queue_position` / `wait_s`: vị trí trong hàng (1 = kế tiếp) và số giây ước tính tới lượt (chỉ khi `in_queue`).
  Xếp hàng quá 3 giờ thì job bị hủy (`queue_timeout`), không tính tiền.
- `eta_s`: số giây còn lại ước tính, `None` nếu chưa ước tính được. Lúc chờ máy chỉ tính trường hợp có GPU ngay; giờ
  đông có thể chờ hơn 15 phút, khi đó `eta_s` là `None` và `message` cho biết đã chờ bao lâu.
- `message`: mô tả ngắn bằng tiếng Việt

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
