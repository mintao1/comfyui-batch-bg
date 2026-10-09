"""工作流模板：API 格式 JSON，值为 "{{KEY}}" 的字段会被替换（保留类型）。"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

PLACEHOLDER = re.compile(r"^\{\{(\w+)\}\}$")

WORKFLOW_FILES = {
    "white": "white_bg.json",
    "replace_image": "replace_bg_image.json",
    "replace_prompt": "replace_bg_prompt.json",
}


def load_workflow(workflows_dir: Path, mode: str) -> dict[str, Any]:
    path = workflows_dir / WORKFLOW_FILES[mode]
    return json.loads(path.read_text(encoding="utf-8"))


def render(template: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, str):
            m = PLACEHOLDER.match(node)
            if m:
                key = m.group(1)
                if key not in values:
                    raise KeyError(f"工作流占位符 {key} 没有提供值")
                return copy.deepcopy(values[key])
        return node

    return walk(template)


def pick_output_image(workflow: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
    """优先取 SaveImage 节点的输出，其次取任意带图片的输出。"""
    save_nodes = [nid for nid, n in workflow.items() if isinstance(n, dict) and n.get("class_type") == "SaveImage"]
    for nid in save_nodes + list(outputs):
        images = (outputs.get(nid) or {}).get("images") or []
        if images:
            return images[0]
    raise ValueError("ComfyUI 输出中没有图片")


def generation_size(width: int, height: int, target: int = 1024) -> tuple[int, int]:
    """把原图比例换算成 SD 生成尺寸：面积约 target²，边长为 64 的倍数。"""
    scale = (target * target / (width * height)) ** 0.5
    w = max(512, round(width * scale / 64) * 64)
    h = max(512, round(height * scale / 64) * 64)
    return w, h
