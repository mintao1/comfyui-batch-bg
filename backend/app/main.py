"""FastAPI 入口：图片上传、批量任务、结果下载。"""
from __future__ import annotations

import io
import logging
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator, model_validator

from .comfy_client import ComfyClient
from .config import Settings
from .jobs import BatchOptions, JobManager, Upload, hex_to_int

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

ALLOWED_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "BMP": ".bmp"}


class BatchRequest(BaseModel):
    image_ids: list[str] = Field(min_length=1)
    mode: Literal["white", "replace_image", "replace_prompt"]
    bg_color: str = "#FFFFFF"
    background_id: str | None = None
    prompt: str = ""
    negative_prompt: str = "text, watermark, blurry, low quality, person"
    seed: int = -1
    steps: int = Field(25, ge=1, le=150)
    cfg: float = Field(7.0, ge=0, le=30)

    @field_validator("bg_color")
    @classmethod
    def _color(cls, v: str) -> str:
        hex_to_int(v)
        return v

    @model_validator(mode="after")
    def _mode_fields(self) -> "BatchRequest":
        if self.mode == "replace_image" and not self.background_id:
            raise ValueError("换背景（图片）模式需要 background_id")
        if self.mode == "replace_prompt" and not self.prompt.strip():
            raise ValueError("换背景（提示词）模式需要 prompt")
        return self


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = ComfyClient(settings.comfyui_url, transport=transport)
        manager = JobManager(settings, client)
        manager.start()
        app.state.manager = manager
        try:
            yield
        finally:
            await manager.stop()
            await client.close()

    app = FastAPI(title="ComfyUI 批量白底图 / 换背景", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"]
    )

    def mgr() -> JobManager:
        return app.state.manager

    @app.get("/api/health")
    async def health():
        try:
            stats = await mgr().client.system_stats()
            return {"ok": True, "comfyui": settings.comfyui_url, "system": stats.get("system", {})}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "comfyui": settings.comfyui_url, "error": str(e)}

    @app.post("/api/uploads")
    async def upload(files: list[UploadFile] = File(...)):
        limit = settings.max_upload_mb * 1024 * 1024
        saved, errors = [], []
        for f in files:
            data = await f.read()
            name = f.filename or "image"
            if len(data) > limit:
                errors.append({"filename": name, "error": f"超过 {settings.max_upload_mb}MB"})
                continue
            try:
                img = Image.open(io.BytesIO(data))
                img.load()
            except (UnidentifiedImageError, OSError):
                errors.append({"filename": name, "error": "不是有效的图片"})
                continue
            if img.format not in ALLOWED_FORMATS:
                errors.append({"filename": name, "error": f"不支持的格式 {img.format}"})
                continue
            uid = uuid.uuid4().hex[:12]
            # 按 EXIF 方向转正，统一存成 PNG，保证宽高与 ComfyUI LoadImage 读到的一致
            img = ImageOps.exif_transpose(img)
            path = settings.uploads_dir / f"{uid}.png"
            img.save(path, "PNG")
            up = Upload(id=uid, filename=name, path=path, width=img.width, height=img.height, size=len(data))
            mgr().uploads[uid] = up
            saved.append(up.public())
        return {"uploaded": saved, "errors": errors}

    @app.get("/api/uploads/{upload_id}/file")
    async def upload_file(upload_id: str):
        up = mgr().uploads.get(upload_id)
        if not up:
            raise HTTPException(404, "图片不存在")
        return FileResponse(up.path)

    @app.post("/api/batches")
    async def create_batch(req: BatchRequest):
        m = mgr()
        missing = [i for i in req.image_ids if i not in m.uploads]
        if req.background_id and req.background_id not in m.uploads:
            missing.append(req.background_id)
        if missing:
            raise HTTPException(400, f"图片不存在: {', '.join(missing)}")
        opts = BatchOptions(**req.model_dump(exclude={"image_ids"}))
        batch = m.create_batch(req.image_ids, opts)
        return m.batch_public(batch)

    @app.get("/api/batches")
    async def list_batches():
        m = mgr()
        batches = sorted(m.batches.values(), key=lambda b: b.created_at, reverse=True)
        return [m.batch_public(b) for b in batches]

    @app.get("/api/batches/{batch_id}")
    async def get_batch(batch_id: str):
        m = mgr()
        if batch_id not in m.batches:
            raise HTTPException(404, "批次不存在")
        return m.batch_public(m.batches[batch_id])

    @app.get("/api/batches/{batch_id}/download")
    async def download_batch(batch_id: str):
        m = mgr()
        batch = m.batches.get(batch_id)
        if not batch:
            raise HTTPException(404, "批次不存在")
        done = [m.tasks[t] for t in batch.task_ids if m.tasks[t].result_path]
        if not done:
            raise HTTPException(400, "该批次还没有完成的结果")
        buf = io.BytesIO()
        used: set[str] = set()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for t in done:
                arc = f"{Path(t.filename).stem}_{batch.options.mode}.png"
                if arc in used:
                    arc = f"{Path(t.filename).stem}_{t.id}_{batch.options.mode}.png"
                used.add(arc)
                zf.write(t.result_path, arc)
        buf.seek(0)
        headers = {"Content-Disposition": f'attachment; filename="batch_{batch_id}.zip"'}
        return StreamingResponse(buf, media_type="application/zip", headers=headers)

    @app.post("/api/tasks/{task_id}/retry")
    async def retry_task(task_id: str):
        m = mgr()
        task = m.tasks.get(task_id)
        if not task:
            raise HTTPException(404, "任务不存在")
        if task.status != "failed":
            raise HTTPException(400, "只有失败的任务可以重试")
        m.retry(task)
        return task.public()

    @app.get("/api/results/{task_id}")
    async def result(task_id: str, download: bool = False):
        task = mgr().tasks.get(task_id)
        if not task or not task.result_path:
            raise HTTPException(404, "结果不存在")
        name = f"{Path(task.filename).stem}_result.png" if download else None
        return FileResponse(task.result_path, media_type="image/png", filename=name)

    # 生产环境：直接托管前端构建产物
    if settings.frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")

    return app


app = create_app()
