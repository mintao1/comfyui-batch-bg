"""上传记录、批次与任务队列（内存存储，重启后清空）。"""
from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from .comfy_client import ComfyClient
from .config import Settings
from .workflows import generation_size, load_workflow, pick_output_image, render

log = logging.getLogger(__name__)

Mode = Literal["white", "replace_image", "replace_prompt"]
Status = Literal["queued", "running", "done", "failed"]


@dataclass
class Upload:
    id: str
    filename: str
    path: Path
    width: int
    height: int
    size: int

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "filename": self.filename,
            "width": self.width,
            "height": self.height,
            "size": self.size,
            "url": f"/api/uploads/{self.id}/file",
        }


@dataclass
class BatchOptions:
    mode: Mode
    bg_color: str = "#FFFFFF"
    background_id: str | None = None
    prompt: str = ""
    negative_prompt: str = ""
    seed: int = -1
    steps: int = 25
    cfg: float = 7.0


@dataclass
class Task:
    id: str
    batch_id: str
    image_id: str
    filename: str
    status: Status = "queued"
    error: str | None = None
    prompt_id: str | None = None
    result_path: Path | None = None
    started_at: float | None = None
    finished_at: float | None = None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "batch_id": self.batch_id,
            "image_id": self.image_id,
            "filename": self.filename,
            "status": self.status,
            "error": self.error,
            "source_url": f"/api/uploads/{self.image_id}/file",
            "result_url": f"/api/results/{self.id}" if self.result_path else None,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass
class Batch:
    id: str
    options: BatchOptions
    task_ids: list[str]
    created_at: float = field(default_factory=time.time)


class JobManager:
    def __init__(self, settings: Settings, client: ComfyClient):
        self.settings = settings
        self.client = client
        self.uploads: dict[str, Upload] = {}
        self.batches: dict[str, Batch] = {}
        self.tasks: dict[str, Task] = {}
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []

    # ---------- 生命周期 ----------
    def start(self) -> None:
        self.settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.settings.results_dir.mkdir(parents=True, exist_ok=True)
        for i in range(max(1, self.settings.max_concurrency)):
            self._workers.append(asyncio.create_task(self._worker(), name=f"comfy-worker-{i}"))

    async def stop(self) -> None:
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    # ---------- 批次 ----------
    def create_batch(self, image_ids: list[str], options: BatchOptions) -> Batch:
        batch_id = uuid.uuid4().hex[:12]
        task_ids = []
        for image_id in image_ids:
            up = self.uploads[image_id]
            task = Task(id=uuid.uuid4().hex[:12], batch_id=batch_id, image_id=image_id, filename=up.filename)
            self.tasks[task.id] = task
            task_ids.append(task.id)
        batch = Batch(id=batch_id, options=options, task_ids=task_ids)
        self.batches[batch_id] = batch
        for tid in task_ids:
            self._queue.put_nowait(tid)
        return batch

    def retry(self, task: Task) -> None:
        task.status, task.error, task.prompt_id = "queued", None, None
        task.started_at = task.finished_at = None
        self._queue.put_nowait(task.id)

    def batch_public(self, batch: Batch) -> dict[str, Any]:
        tasks = [self.tasks[t].public() for t in batch.task_ids]
        counts = {s: sum(1 for t in tasks if t["status"] == s) for s in ("queued", "running", "done", "failed")}
        return {
            "id": batch.id,
            "created_at": batch.created_at,
            "options": asdict(batch.options),
            "total": len(tasks),
            "counts": counts,
            "finished": counts["queued"] == 0 and counts["running"] == 0,
            "tasks": tasks,
        }

    # ---------- 执行 ----------
    async def _worker(self) -> None:
        while True:
            task_id = await self._queue.get()
            task = self.tasks.get(task_id)
            try:
                if task is not None and task.status == "queued":
                    await self._run(task)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - 任何错误都记录到任务上
                log.exception("task %s failed", task_id)
                if task is not None:
                    task.status, task.error = "failed", str(e) or e.__class__.__name__
                    task.finished_at = time.time()
            finally:
                self._queue.task_done()

    async def _run(self, task: Task) -> None:
        task.status, task.started_at = "running", time.time()
        batch = self.batches[task.batch_id]
        opts = batch.options
        up = self.uploads[task.image_id]

        values: dict[str, Any] = {
            "INPUT_IMAGE": await self.client.upload_image(up.path, up.path.name),
            "WIDTH": up.width,
            "HEIGHT": up.height,
            "RMBG_MODEL": self.settings.rmbg_model,
        }
        if opts.mode == "white":
            values["BG_COLOR"] = hex_to_int(opts.bg_color)
        elif opts.mode == "replace_image":
            bg = self.uploads[opts.background_id or ""]
            values["BG_IMAGE"] = await self.client.upload_image(bg.path, bg.path.name)
        elif opts.mode == "replace_prompt":
            gw, gh = generation_size(up.width, up.height)
            values.update(
                CHECKPOINT=self.settings.checkpoint,
                PROMPT=opts.prompt,
                NEGATIVE=opts.negative_prompt,
                SEED=opts.seed if opts.seed >= 0 else random.randint(0, 2**48),
                STEPS=opts.steps,
                CFG=opts.cfg,
                GEN_WIDTH=gw,
                GEN_HEIGHT=gh,
            )

        workflow = render(load_workflow(self.settings.workflows_dir, opts.mode), values)
        task.prompt_id = await self.client.queue_prompt(workflow)
        outputs = await self.client.wait_for(task.prompt_id, self.settings.job_timeout, self.settings.poll_interval)
        data = await self.client.download(pick_output_image(workflow, outputs))

        out = self.settings.results_dir / f"{task.id}.png"
        out.write_bytes(data)
        task.result_path = out
        task.status, task.finished_at = "done", time.time()


def hex_to_int(color: str) -> int:
    c = color.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        raise ValueError(f"无效颜色: {color}")
    return int(c, 16)
