import io
import time
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from app.workflows import generation_size, render

from .fake_comfy import create_fake_comfy


def png(w=40, h=30, color="red") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def make_client(tmp_path):
    def _make(fail_nodes=None):
        fake = create_fake_comfy(fail_nodes)
        settings = Settings(data_dir=tmp_path, frontend_dist=tmp_path / "nope", poll_interval=0.01, job_timeout=5)
        app = create_app(settings, transport=httpx.ASGITransport(app=fake))
        return TestClient(app), fake

    return _make


def wait_batch(client, batch_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        b = client.get(f"/api/batches/{batch_id}").json()
        if b["finished"]:
            return b
        time.sleep(0.02)
    raise AssertionError("batch did not finish")


def upload(client, *blobs):
    files = [("files", (f"img{i}.png", b, "image/png")) for i, b in enumerate(blobs)]
    return client.post("/api/uploads", files=files).json()


def test_white_background_batch(make_client):
    client, fake = make_client()
    with client:
        res = upload(client, png(40, 30), png(20, 50), b"not an image")
        assert len(res["uploaded"]) == 2 and len(res["errors"]) == 1
        ids = [u["id"] for u in res["uploaded"]]

        b = client.post("/api/batches", json={"image_ids": ids, "mode": "white", "bg_color": "#fff"}).json()
        b = wait_batch(client, b["id"])
        assert b["counts"]["done"] == 2

        wf = next(iter(fake.state.prompts.values()))
        assert wf["3"]["inputs"]["color"] == 0xFFFFFF
        assert isinstance(wf["3"]["inputs"]["width"], int)

        t = b["tasks"][1]
        img = Image.open(io.BytesIO(client.get(t["result_url"]).content))
        assert img.size == (20, 50)

        z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/batches/{b['id']}/download").content))
        assert sorted(z.namelist()) == ["img0_white.png", "img1_white.png"]


def test_replace_with_image_and_prompt(make_client):
    client, fake = make_client()
    with client:
        ids = [u["id"] for u in upload(client, png(), png(64, 64, "blue"))["uploaded"]]
        b = client.post("/api/batches", json={"image_ids": ids[:1], "mode": "replace_image", "background_id": ids[1]}).json()
        assert wait_batch(client, b["id"])["counts"]["done"] == 1

        b = client.post("/api/batches", json={"image_ids": ids[:1], "mode": "replace_prompt", "prompt": "beach", "seed": 7}).json()
        assert wait_batch(client, b["id"])["counts"]["done"] == 1
        wf = list(fake.state.prompts.values())[-1]
        assert wf["14"]["inputs"]["seed"] == 7 and wf["11"]["inputs"]["text"] == "beach"


def test_validation(make_client):
    client, _ = make_client()
    with client:
        ids = [u["id"] for u in upload(client, png())["uploaded"]]
        assert client.post("/api/batches", json={"image_ids": ids, "mode": "replace_image"}).status_code == 422
        assert client.post("/api/batches", json={"image_ids": ids, "mode": "replace_prompt"}).status_code == 422
        assert client.post("/api/batches", json={"image_ids": ["x"], "mode": "white"}).status_code == 400
        assert client.post("/api/batches", json={"image_ids": ids, "mode": "white", "bg_color": "zz"}).status_code == 422


def test_comfy_error_and_retry(make_client):
    client, _ = make_client(fail_nodes={"RMBG"})
    with client:
        ids = [u["id"] for u in upload(client, png())["uploaded"]]
        b = wait_batch(client, client.post("/api/batches", json={"image_ids": ids, "mode": "white"}).json()["id"])
        t = b["tasks"][0]
        assert t["status"] == "failed" and "model missing" in t["error"]
        assert client.post(f"/api/tasks/{t['id']}/retry").json()["status"] == "queued"


def test_render_and_sizes():
    assert render({"a": "{{X}}", "b": ["{{X}}", "k{{X}}"]}, {"X": 3}) == {"a": 3, "b": [3, "k{{X}}"]}
    with pytest.raises(KeyError):
        render({"a": "{{Y}}"}, {})
    w, h = generation_size(4000, 3000)
    assert w % 64 == 0 and h % 64 == 0 and w > h
