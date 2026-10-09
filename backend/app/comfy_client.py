"""ComfyUI HTTP API 的最小异步客户端。"""
from __future__ import annotations

import asyncio
import mimetypes
import uuid
from pathlib import Path
from typing import Any

import httpx


class ComfyUIError(RuntimeError):
    pass


class ComfyClient:
    def __init__(self, base_url: str, timeout: float = 60.0, transport: httpx.AsyncBaseTransport | None = None):
        self.client_id = uuid.uuid4().hex
        self._http = httpx.AsyncClient(base_url=base_url, timeout=timeout, transport=transport)

    async def close(self) -> None:
        await self._http.aclose()

    async def system_stats(self) -> dict[str, Any]:
        r = await self._http.get("/system_stats")
        r.raise_for_status()
        return r.json()

    async def upload_image(self, path: Path, name: str) -> str:
        """上传到 ComfyUI 的 input 目录，返回 LoadImage 节点可用的文件名。"""
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        with path.open("rb") as f:
            r = await self._http.post(
                "/upload/image",
                files={"image": (name, f, mime)},
                data={"overwrite": "true", "type": "input"},
            )
        if r.status_code != 200:
            raise ComfyUIError(f"上传图片到 ComfyUI 失败: HTTP {r.status_code} {r.text[:300]}")
        d = r.json()
        return f"{d['subfolder']}/{d['name']}" if d.get("subfolder") else d["name"]

    async def queue_prompt(self, workflow: dict[str, Any]) -> str:
        r = await self._http.post("/prompt", json={"prompt": workflow, "client_id": self.client_id})
        if r.status_code != 200:
            raise ComfyUIError(f"提交工作流失败: HTTP {r.status_code} {r.text[:1000]}")
        d = r.json()
        if d.get("node_errors"):
            raise ComfyUIError(f"工作流节点错误: {d['node_errors']}")
        return d["prompt_id"]

    async def wait_for(self, prompt_id: str, timeout: float, poll_interval: float) -> dict[str, Any]:
        """轮询 /history 直到任务结束，返回 outputs。"""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            r = await self._http.get(f"/history/{prompt_id}")
            r.raise_for_status()
            entry = r.json().get(prompt_id)
            if entry:
                status = entry.get("status") or {}
                if status.get("status_str") == "error":
                    raise ComfyUIError(_execution_error(status))
                if status.get("completed", True):
                    outputs = entry.get("outputs") or {}
                    if not outputs:
                        raise ComfyUIError("ComfyUI 执行完成但没有输出")
                    return outputs
            if loop.time() > deadline:
                raise ComfyUIError(f"等待 ComfyUI 超时（{timeout:.0f}s）")
            await asyncio.sleep(poll_interval)

    async def download(self, image: dict[str, Any]) -> bytes:
        r = await self._http.get(
            "/view",
            params={
                "filename": image["filename"],
                "subfolder": image.get("subfolder", ""),
                "type": image.get("type", "output"),
            },
        )
        if r.status_code != 200:
            raise ComfyUIError(f"下载结果失败: HTTP {r.status_code}")
        return r.content


def _execution_error(status: dict[str, Any]) -> str:
    for msg in status.get("messages") or []:
        if isinstance(msg, list) and len(msg) == 2 and msg[0] == "execution_error":
            data = msg[1] or {}
            node = data.get("node_type", "?")
            return f"ComfyUI 执行出错（{node}）: {data.get('exception_message', '').strip()}"
    return "ComfyUI 执行出错"
