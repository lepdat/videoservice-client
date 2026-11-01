"""
MCP server để dùng dịch vụ thẳng trong Claude Code ("làm cho tôi video 5 giây ...").

    claude mcp add --scope user videoservice -e VIDEOSERVICE_URL=... -e VIDEOSERVICE_API_KEY=vs_... -- python -m videoservice.mcp_server

Mô tả tool là thứ agent đọc để tự quyết: tool nào tốn tiền, giá cỡ nào, giới hạn gì, nên gọi theo thứ tự nào.
Giá cụ thể lấy từ tool pricing / video_template lúc chạy (số trong mô tả chỉ để agent ước lượng).
"""
import functools
import json
import time
from pathlib import Path
from typing import Any

import requests
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import FINAL_STATUSES, Client, VideoServiceError

POLL_EVERY_S = 5
MAX_WAIT_S = 300  # mỗi lần gọi job_status chờ tối đa 5 phút, dưới timeout tool của Claude Code; lâu hơn thì gọi lại

INSTRUCTIONS = """\
Dịch vụ tạo video/ảnh riêng bằng ComfyUI (model MiniMax H3 cho video có tiếng), trả tiền trước bằng VND.

Cách làm một video theo yêu cầu người dùng:
1. balance: xem còn đủ tiền không.
2. Video H3 (từ mô tả, hoặc từ ảnh làm khung hình đầu): video_template dựng sẵn workflow kèm giá ước tính
   (estimate.price_vnd, hold_vnd, wait_s). Báo người dùng giá và thời gian chờ trước khi gửi nếu đắt hơn họ nghĩ.
   Cần workflow khác: tự dựng, nhưng XEM TRƯỚC list_nodes, node_schema (input/output từng node) và list_models
   (tên file model) chứ đừng đoán tên node hay tên input.
3. submit_workflow: gửi job (tốn tiền).
4. job_status với wait_seconds=300: chờ đến khi xong (gọi lại nếu chưa xong); kể cho người dùng tiến độ.
5. download_result: tải video về máy, báo đường dẫn file cho người dùng.
Lỗi trả về có code, message, hint (cách sửa) và errors (lỗi từng node của workflow): sửa theo đó rồi gửi lại.
"""


def _agent_errors(fn):
    """Lỗi dịch vụ thành lỗi tool agent đọc được (code, message, hint, errors) thay vì "Error executing tool"."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except VideoServiceError as e:
            raise ToolError(json.dumps(e.body, ensure_ascii=False)) from e
        except requests.RequestException as e:
            raise ToolError(f"Không kết nối được dịch vụ ({e}). Thử lại sau ít phút; vẫn lỗi thì kiểm tra"
                            " VIDEOSERVICE_URL hoặc hỏi chủ dịch vụ.") from e
        except OSError as e:
            raise ToolError(f"Lỗi đọc/ghi file trên máy: {e}") from e
    return wrapper


def build_server(client: Client | None = None) -> MCPServer:
    """client: mặc định Client() đọc VIDEOSERVICE_URL + VIDEOSERVICE_API_KEY, tạo lúc tool đầu tiên được gọi."""
    server = MCPServer("videoservice", instructions=INSTRUCTIONS)

    def svc() -> Client:
        nonlocal client
        if client is None:
            try:
                client = Client()
            except (KeyError, ValueError) as e:
                raise ToolError(f"Chưa cấu hình dịch vụ ({e}). Đặt VIDEOSERVICE_URL và VIDEOSERVICE_API_KEY"
                                " (chủ dịch vụ gửi riêng) cho MCP server videoservice rồi khởi động lại Claude Code.")
        return client

    def tool(fn):
        return server.tool()(_agent_errors(fn))

    @tool
    def balance() -> dict[str, Any]:
        """Số dư (VND): balance, held (đang giữ cho job chưa xong), available (dùng được), spent_today, daily_limit
        (giới hạn tiêu mỗi ngày), concurrency (số job chạy cùng lúc). Miễn phí."""
        return svc().balance()

    @tool
    def pricing() -> dict[str, Any]:
        """Bảng giá (VND). Tiền tính theo giây máy chạy thật, gồm khởi động và nạp model (~30–50 giây/job);
        chờ GPU không tính tiền. Workflow có node nạp model (H3...) chạy GPU (~4,6đ/giây), còn lại chạy CPU (rất rẻ).
        h3_video.estimates: giá, tiền giữ, thời gian ước tính của từng loại video H3. Miễn phí."""
        return svc().pricing()

    @tool
    def list_nodes(q: str | None = None, category: str | None = None) -> dict[str, Any]:
        """Node ComfyUI được phép dùng. Không lọc: số node theo nhóm + danh sách output node (workflow cần ít nhất
        một output node, ví dụ SaveVideo, để ra file). q: tìm theo tên/mô tả, ví dụ "video"; category: nhóm, ví dụ
        "image". Xem chi tiết một node bằng node_schema trước khi dùng nó. Miễn phí."""
        return svc().list_nodes(q=q, category=category)

    @tool
    def node_schema(class_type: str) -> dict[str, Any]:
        """Input (tên, kiểu, giá trị cho phép, mặc định) và output của một node, tên phân biệt hoa thường.
        Gọi cho mọi node trước khi tự dựng workflow. Miễn phí."""
        return svc().node_schema(class_type)

    @tool
    def list_models() -> dict[str, Any]:
        """Tên file model có sẵn (diffusion_models, text_encoders, vae, loras) để điền vào các node loader.
        Miễn phí."""
        return svc().list_models()

    @tool
    def video_template(name: str, prompt: str, resolution: str = "480P", seconds: float = 5, portrait: bool = False,
                       seed: int | None = None, upscale: str | None = None) -> dict[str, Any]:
        """Workflow video MiniMax H3 dựng sẵn (có tiếng) + giá ước tính, chưa gửi job, miễn phí.

        name: "h3_t2v" (từ mô tả) hoặc "h3_i2v" (ảnh là khung hình đầu: gửi ảnh qua inputs của submit_workflow,
        tên file lấy từ "inputs" của kết quả). prompt: mô tả video, viết tiếng Anh cho kết quả tốt hơn.
        resolution: "480P" hoặc "768P" (tối đa, 1344×768); seconds: tối đa 15. portrait=true: video dọc.
        seed: đổi để ra kết quả khác. upscale="2K": phóng lên 1440p trong cùng job, tối đa 10 giây video, lâu và đắt
        gấp nhiều lần. Giá cỡ (xem estimate để có số chính xác): 480P 5s ~400đ, chạy ~1,5 phút; 480P 15s ~1.000đ,
        ~4 phút; 768P 10s ~2.000đ, ~7 phút; 768P 15s ~4.100đ, ~9 phút (768P trên 10 giây chạy GPU H100, đắt hơn mỗi
        giây); 768P 5s + 2K ~2.900đ, ~10 phút. Kết quả: workflow, inputs, estimate (price_vnd, hold_vnd = tiền giữ
        trước ~1,5 lần giá, wait_s, runtime_s)."""
        params = {"prompt": prompt, "resolution": resolution, "seconds": seconds, "portrait": portrait or None,
                  "seed": seed, "upscale": upscale}
        return svc().template(name, **{k: v for k, v in params.items() if v is not None})

    @tool
    def submit_workflow(workflow: dict[str, Any], inputs: dict[str, str] | None = None,
                        max_cost_vnd: int | None = None) -> dict[str, Any]:
        """Gửi job chạy workflow ComfyUI dạng API format ({"<node_id>": {"class_type": ..., "inputs": {...}}}).
        TỐN TIỀN: giữ trước số tiền tối đa (hold), xong job chỉ trừ theo giây chạy thật, phần thừa trả lại; lỗi do
        hệ thống được hoàn tiền, lỗi do workflow vẫn tính phần đã chạy. Kiểm tra balance trước: tiền giữ phải nằm
        trong available và daily_limit (giới hạn tiêu mỗi ngày).

        inputs: {tên file trong workflow: đường dẫn file ảnh trên máy}, ví dụ {"first_frame.png": "anh/meo.png"};
        tổng tối đa 20 MB mỗi job.
        max_cost_vnd: giới hạn tiền cho job; phải ≥ hold_vnd của estimate, thấp hơn thì job có thể bị cắt giữa chừng
        mà vẫn mất tiền. Giới hạn: tối đa 768P (1344×768) và 15 giây video H3 (10 giây nếu upscale 2K); tối đa
        200 node; job chờ GPU quá 3 giờ thì bị hủy (không tính tiền). Trả job_id, estimated_cost, held, timeout_s;
        theo dõi bằng job_status."""
        missing = [p for p in (inputs or {}).values() if not Path(p).is_file()]
        if missing:
            raise ToolError(f"Không thấy file ảnh trên máy: {missing}. 'inputs' là {{tên file trong workflow:"
                            " đường dẫn file trên máy}}.")
        return svc().submit(workflow, inputs=inputs, max_cost_vnd=max_cost_vnd)

    @tool
    def job_status(job_id: str, wait_seconds: int = 0) -> dict[str, Any]:
        """Trạng thái job: queued → running → succeeded / failed / cancelled; progress có stage (in_queue,
        waiting_for_machine, loading_model, generating, upscaling, saving), message tiếng Việt, eta_s (giây còn lại
        ước tính); job lỗi thì error có code, message, hint. wait_seconds (tối đa 300): chờ tới khi job xong rồi
        mới trả, hết thời gian chờ thì trả trạng thái hiện tại. Giờ đông có thể chờ GPU hơn 15 phút. Miễn phí."""
        deadline = time.monotonic() + min(max(wait_seconds, 0), MAX_WAIT_S)
        while True:
            j = svc().job(job_id)
            if j["status"] in FINAL_STATUSES or time.monotonic() + POLL_EVERY_S > deadline:
                return j
            time.sleep(POLL_EVERY_S)

    @tool
    def download_result(job_id: str, save_dir: str = ".") -> dict[str, Any]:
        """Tải file kết quả của job đã succeeded vào save_dir (tương đối theo thư mục dự án đang mở), trả đường
        dẫn tuyệt đối từng file. Kết quả giữ 7 ngày trên dịch vụ. Miễn phí."""
        return {"files": [str(p.resolve()) for p in svc().download(job_id, save_dir)]}

    @tool
    def cancel_job(job_id: str) -> dict[str, Any]:
        """Hủy job đang chờ hoặc đang chạy; chỉ tính tiền phần đã chạy."""
        return svc().cancel(job_id)

    return server


def main():
    build_server().run()


if __name__ == "__main__":
    main()
