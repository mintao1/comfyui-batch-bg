"""模拟 ComfyUI 的 /upload/image /prompt /history /view 接口，用于测试。"""
from __future__ import annotations

import io
import uuid

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from PIL import Image


def create_fake_comfy(fail_nodes: set[str] | None = None) -> FastAPI:
    app = FastAPI()
    app.state.uploaded = {}
    app.state.prompts = {}
    fail_nodes = fail_nodes or set()

    @app.get("/system_stats")
    async def stats():
        return {"system": {"comfyui_version": "fake"}}

    @app.post("/upload/image")
    async def upload(image: UploadFile = File(...), overwrite: str = Form("false"), type: str = Form("input")):
        app.state.uploaded[image.filename] = await image.read()
        return {"name": image.filename, "subfolder": "", "type": type}

    @app.post("/prompt")
    async def prompt(req: Request):
        body = await req.json()
        wf = body["prompt"]
        for node in wf.values():
            if node["class_type"] in ("LoadImage",) and node["inputs"]["image"] not in app.state.uploaded:
                return JSONResponse({"error": "image not found", "node_errors": {}}, status_code=400)
        pid = uuid.uuid4().hex
        app.state.prompts[pid] = wf
        return {"prompt_id": pid, "number": len(app.state.prompts), "node_errors": {}}

    @app.get("/history/{pid}")
    async def history(pid: str):
        wf = app.state.prompts.get(pid)
        if wf is None:
            return {}
        if any(n["class_type"] in fail_nodes for n in wf.values()):
            return {pid: {"outputs": {}, "status": {"status_str": "error", "completed": False, "messages": [
                ["execution_error", {"node_type": "RMBG", "exception_message": "model missing"}]]}}}
        save_id = next(k for k, n in wf.items() if n["class_type"] == "SaveImage")
        return {pid: {"outputs": {save_id: {"images": [{"filename": f"{pid}.png", "subfolder": "batch_bg", "type": "output"}]}},
                      "status": {"status_str": "success", "completed": True, "messages": []}}}

    @app.get("/view")
    async def view(filename: str, subfolder: str = "", type: str = "output"):
        wf = app.state.prompts[filename.removesuffix(".png")]
        comp = next(n for n in wf.values() if n["class_type"] in ("EmptyImage", "ImageScale"))
        w, h = comp["inputs"]["width"], comp["inputs"]["height"]
        buf = io.BytesIO()
        Image.new("RGB", (w, h), "white").save(buf, "PNG")
        return Response(buf.getvalue(), media_type="image/png")

    return app
