# ComfyUI 批量白底图 / 换背景

一个前后端分离的小工具：在网页里批量上传图片，调用 ComfyUI 自动抠图，然后

- **白底图**：合成到白色（或任意纯色）背景上；
- **换背景 · 图片**：合成到你上传的背景图上（自动按原图尺寸居中缩放裁剪）；
- **AI 生成背景**：用 SD 模型按提示词生成背景，再合成主体。

输出尺寸与原图一致，支持逐张下载、批次 ZIP 打包下载、失败重试。

```
浏览器 (Vue 3 + Vite)
   │  /api
   ▼
后端 (FastAPI) ── 任务队列 ── ComfyUI HTTP API
   │                          /upload/image → /prompt → /history → /view
   └─ data/uploads, data/results
```

## 目录结构

```
backend/
  app/
    main.py          # FastAPI 路由
    jobs.py          # 上传记录、批次、异步任务队列
    comfy_client.py  # ComfyUI API 客户端
    workflows.py     # 工作流模板渲染
    config.py        # 环境变量配置
  workflows/         # ComfyUI API 格式的工作流模板
    white_bg.json
    replace_bg_image.json
    replace_bg_prompt.json
  tests/             # pytest（自带一个假的 ComfyUI，不需要 GPU）
frontend/            # Vue 3 + Vite
Dockerfile, docker-compose.yml
```

## 准备 ComfyUI

1. 启动 ComfyUI（默认 `http://127.0.0.1:8188`）。如果后端和 ComfyUI 不在同一台机器，用 `--listen 0.0.0.0` 启动。
2. 安装抠图节点 [ComfyUI-RMBG](https://github.com/1038lab/ComfyUI-RMBG)（ComfyUI-Manager 里搜索 `RMBG` 即可），首次运行会自动下载 `RMBG-2.0` 模型。
3. （仅「AI 生成背景」需要）把 SD 模型放到 `ComfyUI/models/checkpoints/`，默认文件名 `sd_xl_base_1.0.safetensors`，可用 `SD_CHECKPOINT` 改。

## 本地开发

```bash
# 后端
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
COMFYUI_URL=http://127.0.0.1:8188 uvicorn app.main:app --reload --port 8000

# 前端（另开终端）
cd frontend
npm install
npm run dev        # http://localhost:5173 ，/api 自动代理到 8000
```

运行测试：`cd backend && pytest`

## 生产部署

```bash
# 方式一：Docker
COMFYUI_URL=http://<comfyui地址>:8188 docker compose up -d --build
# 打开 http://localhost:8000

# 方式二：直接运行
cd frontend && npm install && npm run build
cd ../backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
# 后端检测到 frontend/dist 会自动托管前端页面
```

## 配置（环境变量）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `COMFYUI_URL` | `http://127.0.0.1:8188` | ComfyUI 地址 |
| `RMBG_MODEL` | `RMBG-2.0` | RMBG 节点模型（也可用 `INSPYRENET`、`BEN`、`BEN2`） |
| `SD_CHECKPOINT` | `sd_xl_base_1.0.safetensors` | AI 生成背景用的模型 |
| `MAX_CONCURRENCY` | `2` | 同时在途的任务数 |
| `JOB_TIMEOUT` | `600` | 单张图片最长等待秒数 |
| `MAX_UPLOAD_MB` | `30` | 单张上传上限 |
| `DATA_DIR` | `backend/data` | 上传与结果的存储目录 |
| `CORS_ORIGINS` | `*` | 允许跨域的来源，逗号分隔 |

## 自定义工作流

`backend/workflows/` 下是 ComfyUI **API 格式**的 JSON（在 ComfyUI 里开启开发者模式后「Save (API Format)」导出）。
值恰好为 `{{KEY}}` 的字段会被后端替换，类型保持不变（数字仍是数字）：

| 占位符 | 含义 |
| --- | --- |
| `{{INPUT_IMAGE}}` | 已上传到 ComfyUI 的原图文件名 |
| `{{WIDTH}}` / `{{HEIGHT}}` | 原图尺寸 |
| `{{RMBG_MODEL}}` | 抠图模型 |
| `{{BG_COLOR}}` | 背景色（整数，如白色 `16777215`） |
| `{{BG_IMAGE}}` | 背景图文件名 |
| `{{CHECKPOINT}}` `{{PROMPT}}` `{{NEGATIVE}}` `{{SEED}}` `{{STEPS}}` `{{CFG}}` `{{GEN_WIDTH}}` `{{GEN_HEIGHT}}` | AI 背景生成参数 |

想换别的抠图节点（如 BiRefNet、rembg）、加上光影融合（IC-Light）或放大，只要改模板即可，后端会取 `SaveImage` 节点的输出作为结果。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 检查 ComfyUI 连接 |
| POST | `/api/uploads` | 批量上传（multipart，字段 `files`） |
| POST | `/api/batches` | 创建批次：`{image_ids, mode, bg_color?, background_id?, prompt?, negative_prompt?, seed?, steps?, cfg?}` |
| GET | `/api/batches` / `/api/batches/{id}` | 查询批次与任务状态 |
| GET | `/api/batches/{id}/download` | 下载批次结果 ZIP |
| POST | `/api/tasks/{id}/retry` | 重试失败任务 |
| GET | `/api/results/{task_id}` | 结果图（`?download=true` 作为附件下载） |

`mode` 取值：`white`、`replace_image`、`replace_prompt`。

## 说明

- 任务和上传记录保存在内存中，后端重启后列表会清空（文件仍在 `data/` 目录）。
- 上传的图片会按 EXIF 方向转正并统一存为 PNG。
