"""运行配置，全部可通过环境变量覆盖。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass
class Settings:
    comfyui_url: str = field(default_factory=lambda: _env("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/"))
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", str(BASE_DIR / "data"))))
    workflows_dir: Path = field(default_factory=lambda: Path(_env("WORKFLOWS_DIR", str(BASE_DIR / "workflows"))))
    frontend_dist: Path = field(default_factory=lambda: Path(_env("FRONTEND_DIST", str(BASE_DIR.parent / "frontend" / "dist"))))
    # 同时提交给 ComfyUI 的任务数（ComfyUI 本身串行执行，>1 只是让上传/下载与推理重叠）
    max_concurrency: int = field(default_factory=lambda: int(_env("MAX_CONCURRENCY", "2")))
    job_timeout: float = field(default_factory=lambda: float(_env("JOB_TIMEOUT", "600")))
    poll_interval: float = field(default_factory=lambda: float(_env("POLL_INTERVAL", "1.0")))
    max_upload_mb: int = field(default_factory=lambda: int(_env("MAX_UPLOAD_MB", "30")))
    # 抠图节点（ComfyUI-RMBG）使用的模型
    rmbg_model: str = field(default_factory=lambda: _env("RMBG_MODEL", "RMBG-2.0"))
    # 提示词生成背景时使用的 SD 模型（需存在于 ComfyUI/models/checkpoints）
    checkpoint: str = field(default_factory=lambda: _env("SD_CHECKPOINT", "sd_xl_base_1.0.safetensors"))
    cors_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in _env("CORS_ORIGINS", "*").split(",") if o.strip()]
    )

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def results_dir(self) -> Path:
        return self.data_dir / "results"
