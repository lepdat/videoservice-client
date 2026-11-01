"""
Thư viện bạn bè cài để dùng dịch vụ.

    from videoservice import Client
    c = Client(api_key="vs_...")
    print(c.balance())
    job = c.submit(workflow)                 # workflow ComfyUI dạng API format (dict)
    c.wait(job["job_id"])                    # chờ đến khi xong
    paths = c.download(job["job_id"], "out") # tải file kết quả vào thư mục out/

hoặc gọn hơn:  paths = c.run(workflow, save_dir="out")
"""
import base64
import os
import time
from pathlib import Path

import requests

# URL do chủ dịch vụ gửi riêng cùng API key.
DEFAULT_URL = os.environ.get("VIDEOSERVICE_URL", "")

FINAL_STATUSES = ("succeeded", "failed", "cancelled")


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

    def wait(self, job_id: str, poll_every: float = 5, max_wait: float = 1800) -> dict:
        """Chờ job kết thúc, trả trạng thái cuối. Không tự raise khi job failed: xem job['error']."""
        deadline = time.time() + max_wait
        while time.time() < deadline:
            j = self.job(job_id)
            if j["status"] in FINAL_STATUSES:
                return j
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

    def run(self, workflow: dict, save_dir: str | Path = ".", **submit_kw) -> list[Path]:
        """Gửi, chờ, tải về. Job lỗi thì raise VideoServiceError kèm lỗi của job."""
        job_id = self.submit(workflow, **submit_kw)["job_id"]
        j = self.wait(job_id)
        if j["status"] != "succeeded":
            raise VideoServiceError(200, {"error": j.get("error") or {"code": j["status"], "message": j["status"]}})
        return self.download(job_id, save_dir)
