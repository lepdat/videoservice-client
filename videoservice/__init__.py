"""
Thư viện bạn bè cài để dùng dịch vụ.

    from videoservice import text_to_video, image_to_video
    path = text_to_video("Phố cổ Hà Nội lúc hoàng hôn", seconds=5, resolution="768P", max_cost_vnd=30000)
    path = image_to_video("anh.png", "Con mèo vẫy đuôi")

Tự điều khiển từng bước:

    from videoservice import Client
    c = Client(api_key="vs_...")
    print(c.balance())
    job = c.submit(workflow)                 # workflow ComfyUI dạng API format (dict)
    c.wait(job["job_id"], on_progress=print_progress)  # chờ đến khi xong, in từng giai đoạn
    paths = c.download(job["job_id"], "out") # tải file kết quả vào thư mục out/

hoặc gọn hơn:  paths = c.run(workflow, save_dir="out")
"""
import base64
import os
import time
from pathlib import Path
from typing import Callable

import requests

# URL do chủ dịch vụ gửi riêng cùng API key.
DEFAULT_URL = os.environ.get("VIDEOSERVICE_URL", "")

FINAL_STATUSES = ("succeeded", "failed", "cancelled")


def print_progress(job: dict) -> None:
    """In một dòng tiến độ, ví dụ "job_ab12: Đang tạo: bước 3/8, còn khoảng 40 giây". Dùng làm on_progress."""
    p = job.get("progress") or {}
    eta = f", còn khoảng {p['eta_s']} giây" if p.get("eta_s") is not None else ""
    print(f"{job['job_id']}: {p.get('message') or job['status']}{eta}", flush=True)


class VideoServiceError(Exception):
    """Lỗi từ dịch vụ: code (máy đọc), message + hint (người/agent đọc), errors (danh sách lỗi workflow)."""

    def __init__(self, status: int, body: dict):
        e = body.get("error") or {"code": "http_error", "message": str(body)}
        self.status = status
        self.code = e.get("code")
        self.hint = e.get("hint", "")
        self.errors = e.get("errors", [])
        self.body = e
        super().__init__(f"[{self.code}] {e.get('message')}" + (f" — {self.hint}" if self.hint else ""))


class Client:
    def __init__(self, api_key: str | None = None, base_url: str = DEFAULT_URL):
        self.api_key = api_key or os.environ["VIDEOSERVICE_API_KEY"]
        if not base_url:
            raise ValueError("Thiếu URL dịch vụ: đặt VIDEOSERVICE_URL hoặc truyền base_url=...")
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["x-api-key"] = self.api_key

    def _req(self, method: str, path: str, **kw):
        r = self.session.request(method, f"{self.base_url}{path}", timeout=kw.pop("timeout", 60), **kw)
        try:
            body = r.json()
        except ValueError:
            body = {"error": {"code": "http_error", "message": r.text[:500]}}
        if r.status_code >= 400:
            raise VideoServiceError(r.status_code, body)
        return body

    def balance(self) -> dict:
        return self._req("GET", "/balance")

    def pricing(self) -> dict:
        return self._req("GET", "/pricing")

    def list_nodes(self) -> dict:
        return self._req("GET", "/nodes")

    def node_schema(self, class_type: str) -> dict:
        return self._req("GET", f"/nodes/{class_type}")

    def list_models(self) -> dict:
        return self._req("GET", "/models")

    def list_templates(self) -> dict:
        return self._req("GET", "/templates")

    def template(self, name: str, **params) -> dict:
        """Workflow mẫu dựng sẵn, ví dụ template("h3_i2v", prompt="...", resolution="768P", seconds=5).

        Trả {workflow, inputs, ...}; gửi bằng submit(t["workflow"], inputs={tên trong t["inputs"]: đường dẫn ảnh}).
        """
        return self._req("GET", f"/templates/{name}", params=params)

    def submit(self, workflow: dict, inputs: dict[str, str | bytes | Path] | None = None,
               max_cost_vnd: int | None = None) -> dict:
        """Gửi job. inputs: {tên_file: bytes | đường dẫn file}. Trả {job_id, estimated_cost, held, timeout_s}."""
        encoded = None
        if inputs:
            encoded = {}
            for name, v in inputs.items():
                data = Path(v).read_bytes() if isinstance(v, (str, Path)) else v
                encoded[name] = base64.b64encode(data).decode()
        body = {"workflow": workflow, "inputs": encoded, "max_cost_vnd": max_cost_vnd}
        return self._req("POST", "/jobs", json=body, timeout=120)

    def job(self, job_id: str) -> dict:
        return self._req("GET", f"/jobs/{job_id}")

    def wait(self, job_id: str, poll_every: float = 5, max_wait: float = 1800,
             on_progress: Callable[[dict], None] | None = None) -> dict:
        """Chờ job kết thúc, trả trạng thái cuối. Không tự raise khi job failed: xem job['error'].

        on_progress(job) được gọi mỗi khi giai đoạn hoặc bước đổi; job["progress"] có stage (waiting_for_machine /
        loading_model / generating / saving), message, step/steps khi đang tạo, eta_s (giây còn lại ước tính, có thể
        None). In ra màn hình: on_progress=print_progress.
        """
        deadline = time.time() + max_wait
        last = None
        while time.time() < deadline:
            j = self.job(job_id)
            if j["status"] in FINAL_STATUSES:
                return j
            p = j.get("progress")
            if on_progress and p and (shown := (p["stage"], p.get("step"))) != last:
                last = shown
                on_progress(j)
            time.sleep(poll_every)
        raise TimeoutError(f"Quá {max_wait} giây mà job {job_id} chưa xong")

    def result(self, job_id: str) -> dict:
        """Danh sách file output kèm link tải có hạn."""
        return self._req("GET", f"/jobs/{job_id}/result")

    def download(self, job_id: str, save_dir: str | Path = ".") -> list[Path]:
        save_dir = Path(save_dir)
        paths = []
        for f in self.result(job_id)["files"]:
            dest = save_dir / f["name"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            with requests.get(f["url"], stream=True, timeout=300) as r:
                if r.status_code >= 400:
                    raise VideoServiceError(r.status_code, r.json())
                with open(dest, "wb") as out:
                    for chunk in r.iter_content(1 << 20):
                        out.write(chunk)
            paths.append(dest)
        return paths

    def cancel(self, job_id: str) -> dict:
        return self._req("POST", f"/jobs/{job_id}/cancel")

    def run(self, workflow: dict, save_dir: str | Path = ".",
            on_progress: Callable[[dict], None] | None = None, **submit_kw) -> list[Path]:
        """Gửi, chờ, tải về. Job lỗi thì raise VideoServiceError kèm lỗi của job. on_progress: xem wait()."""
        job_id = self.submit(workflow, **submit_kw)["job_id"]
        j = self.wait(job_id, on_progress=on_progress)
        if j["status"] != "succeeded":
            raise VideoServiceError(200, {"error": j.get("error") or {"code": j["status"], "message": j["status"]}})
        return self.download(job_id, save_dir)


def text_to_video(prompt: str, seconds: float = 5, resolution: str = "480P", *, save_dir: str | Path = ".",
                  max_cost_vnd: int | None = None, on_progress: Callable[[dict], None] | None = print_progress,
                  client: Client | None = None, **options) -> Path:
    """Tạo video H3 từ mô tả, chờ xong, tải về save_dir; trả đường dẫn file video.

    resolution: "480P" hoặc "768P" (tối đa). max_cost_vnd: giới hạn tiền cho job này.
    options: tham số khác của workflow mẫu h3_t2v, ví dụ portrait=True, seed=2 (xem Client().list_templates()).
    on_progress=None để không in tiến độ. client: mặc định Client() đọc URL + key từ biến môi trường.
    """
    return _make_video(client, "h3_t2v", None, prompt=prompt, seconds=seconds, resolution=resolution,
                       save_dir=save_dir, max_cost_vnd=max_cost_vnd, on_progress=on_progress, **options)


def image_to_video(image: str | Path | bytes, prompt: str, seconds: float = 5, resolution: str = "480P", *,
                   save_dir: str | Path = ".", max_cost_vnd: int | None = None,
                   on_progress: Callable[[dict], None] | None = print_progress, client: Client | None = None,
                   **options) -> Path:
    """Như text_to_video, nhưng ảnh (đường dẫn hoặc bytes PNG/JPG) là khung hình đầu, cắt giữa cho vừa khung video."""
    return _make_video(client, "h3_i2v", image, prompt=prompt, seconds=seconds, resolution=resolution,
                       save_dir=save_dir, max_cost_vnd=max_cost_vnd, on_progress=on_progress, **options)


def _make_video(client: Client | None, template: str, image: str | Path | bytes | None, *, save_dir: str | Path,
                max_cost_vnd: int | None, on_progress: Callable[[dict], None] | None, **params) -> Path:
    c = client or Client()
    t = c.template(template, **params)
    # Giới hạn thấp hơn tiền giữ thì dịch vụ rút ngắn timeout: job có thể bị cắt giữa chừng mà vẫn mất tiền.
    est = t["estimate"]
    if max_cost_vnd is not None and max_cost_vnd < est["hold_vnd"]:
        raise VideoServiceError(400, {"error": {
            "code": "max_cost_below_hold",
            "message": f"Video này cần giữ trước {est['hold_vnd']:,}đ (ước tính dùng {est['price_vnd']:,}đ, phần thừa"
                       f" trả lại); với max_cost_vnd={max_cost_vnd:,}đ job có thể bị cắt giữa chừng. Chưa gửi job.",
            "hint": f"Đặt max_cost_vnd ≥ {est['hold_vnd']:,}, hoặc giảm seconds / resolution."}})
    inputs = {name: image for name in t["inputs"]} or None
    paths = c.run(t["workflow"], save_dir=save_dir, on_progress=on_progress, inputs=inputs, max_cost_vnd=max_cost_vnd)
    return paths[0]
