#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FRAME = ROOT / "keyframes/KF_B01双人品牌顾问_竖屏720x1280.jpg"
MODEL = "alibaba/happyhorse-1.1"
BASE_URL = "https://openrouter.ai/api/v1"
AUDIT = ROOT / "audit"
OUTPUT = ROOT / "output"

SPEECH_1 = "选眼镜，不只是看款式。合适的镜框，要结合脸型、瞳距和日常使用场景；镜片，也要根据度数和用眼需求来选择。"
SPEECH_2 = "在南吴眼镜，我们会先了解你的需求，再进行专业验光和佩戴调整。让每一副眼镜，看得清楚，也戴得舒服。"

PROMPTS = {
    "S01_大睿口播": f"""Create one continuous 15-second vertical digital-human commercial shot from the supplied exact first frame. Preserve the exact identities, facial geometry, ages, hairstyles, eyeglasses, navy blazers, white shirts, body proportions and optical-store background of both people. Screen-left is Da Rui, the young East Asian man. Screen-right is Xiao Mo, the young East Asian woman.

Da Rui is the only speaker. He looks into the camera and speaks exactly this Mandarin Chinese line once, in a clear, calm, friendly young male voice at a natural professional pace: “{SPEECH_1}” His lip shapes must accurately synchronize to every syllable. He uses restrained natural facial expression, one or two blinks, subtle breathing and one very small open-palm gesture near waist level. No broad grin.

Xiao Mo does not speak at any time. She keeps her lips closed, listens naturally, breathes subtly, blinks once and gives one tiny acknowledging nod near the end. No lip movement that resembles speech and no large smile.

Camera and continuity: portrait 9:16, 720p, eye-level medium two-shot, stable 50mm perspective, almost imperceptible slow push-in, no cuts and no angle change. Warm premium optical boutique lighting. Keep both eyeglass frames structurally perfect and reflections realistic. Exactly two people throughout. No subtitles, no generated text, no logo, no other voices, no music and no background conversation; only Da Rui's clean Mandarin speech with extremely quiet shop room tone. No identity drift, face morphing, age change, extra people, duplicated limbs, deformed hands, broken glasses, mouth artifacts, frozen expression or camera shake.""",
    "S02_小墨口播": f"""Create one continuous 15-second vertical digital-human commercial shot from the supplied exact first frame. Preserve the exact identities, facial geometry, ages, hairstyles, eyeglasses, navy blazers, white shirts, body proportions and optical-store background of both people. Screen-left is Da Rui, the young East Asian man. Screen-right is Xiao Mo, the young East Asian woman.

Xiao Mo is the only speaker. She looks into the camera and speaks exactly this Mandarin Chinese line once, in a clear, warm, confident young female voice at a natural professional pace: “{SPEECH_2}” Her lip shapes must accurately synchronize to every syllable. Her expression is friendly but restrained, with a gentle closed-mouth smile only after she finishes; one or two natural blinks, subtle breathing and one small controlled hand gesture near waist level. No broad grin or laughter.

Da Rui does not speak at any time. He keeps his lips closed, listens naturally, breathes subtly, blinks once and gives one tiny acknowledging nod near the end. No lip movement that resembles speech and no smile with teeth.

Camera and continuity: portrait 9:16, 720p, eye-level medium two-shot, stable 50mm perspective, almost imperceptible slow push-in, no cuts and no angle change. Warm premium optical boutique lighting. Keep both eyeglass frames structurally perfect and reflections realistic. Exactly two people throughout. No subtitles, no generated text, no logo, no other voices, no music and no background conversation; only Xiao Mo's clean Mandarin speech with extremely quiet shop room tone. No identity drift, face morphing, age change, extra people, duplicated limbs, deformed hands, broken glasses, mouth artifacts, frozen expression or camera shake.""",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    path = Path("/Users/wangzirui/Library/Application Support/Claude/mcp-servers/multi-model-secrets.json")
    if path.exists():
        key = str(json.loads(path.read_text(encoding="utf-8")).get("openrouter_api_key", "")).strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")
    return key


def request_json(method: str, url: str, key: str, payload: dict | None = None) -> tuple[int, dict]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://openai.com/codex",
        "X-Title": "WLC Da Rui Xiao Mo 30s Digital Human",
    })
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {raw[:4000]}") from exc


def setup() -> None:
    AUDIT.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, prompt in PROMPTS.items():
        (ROOT / f"{name}_提示词.txt").write_text(prompt + "\n", encoding="utf-8")
    (ROOT / "口播文案.txt").write_text(f"大睿：{SPEECH_1}\n\n小墨：{SPEECH_2}\n", encoding="utf-8")


def preflight(key: str) -> dict:
    if not FRAME.exists():
        raise FileNotFoundError(FRAME)
    _, response = request_json("GET", f"{BASE_URL}/videos/models", key)
    _, auth = request_json("GET", f"{BASE_URL}/auth/key", key)
    model = next((m for m in response.get("data", []) if m.get("id") == MODEL), None)
    if model is None:
        raise RuntimeError(f"Model unavailable: {MODEL}")
    skus = model.get("pricing_skus") or {}
    price_per_second = float(skus.get("duration_seconds_720p", 0))
    snapshot = {
        "checked_at": now(),
        "model": model,
        "account": auth.get("data", {}),
        "requested": {"clips": 2, "seconds_each": 15, "total_seconds": 30, "resolution": "720p", "aspect_ratio": "9:16"},
        "price_per_second_usd": price_per_second,
        "estimated_total_usd": round(price_per_second * 30, 6),
        "frame": str(FRAME),
        "frame_bytes": FRAME.stat().st_size,
    }
    (AUDIT / "preflight.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot


def data_url(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def submit_one(key: str, name: str, prompt: str, estimate: float) -> dict:
    job_file = AUDIT / f"{name}_job.json"
    if job_file.exists():
        old = json.loads(job_file.read_text(encoding="utf-8"))
        if old.get("id"):
            raise RuntimeError(f"Existing job {old['id']} for {name}; refusing duplicate")
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "duration": 15,
        "resolution": "720p",
        "aspect_ratio": "9:16",
        "generate_audio": True,
        "frame_images": [{"type": "image_url", "image_url": {"url": data_url(FRAME)}, "frame_type": "first_frame"}],
    }
    status, result = request_json("POST", f"{BASE_URL}/videos", key, payload)
    record = {**result, "http_status": status, "submitted_at": now(), "name": name, "estimated_cost_usd": estimate, "frame": str(FRAME)}
    job_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def poll_one(key: str, name: str) -> dict:
    job = json.loads((AUDIT / f"{name}_job.json").read_text(encoding="utf-8"))
    job_id = job["id"]
    while True:
        _, result = request_json("GET", f"{BASE_URL}/videos/{job_id}", key)
        result["polled_at"] = now()
        (AUDIT / f"{name}_status.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"name": name, "id": job_id, "status": result.get("status"), "usage": result.get("usage")}, ensure_ascii=False), flush=True)
        if result.get("status") in {"completed", "failed", "cancelled", "expired"}:
            return result
        time.sleep(30)


def download(key: str, name: str, job_id: str) -> Path:
    target = OUTPUT / f"{name}_HappyHorse1.1_720P_15s.mp4"
    temp = target.with_suffix(".part")
    request = urllib.request.Request(f"{BASE_URL}/videos/{job_id}/content?index=0", headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(request, timeout=600) as response, temp.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    if temp.stat().st_size < 1024:
        raise RuntimeError(f"Downloaded file too small: {name}")
    temp.replace(target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["preflight", "submit", "poll", "run"])
    args = parser.parse_args()
    setup()
    key = load_key()
    snapshot = preflight(key)
    if args.action == "preflight":
        print(json.dumps({
            "model": MODEL,
            "pricing_skus": snapshot["model"].get("pricing_skus"),
            "estimated_total_usd": snapshot["estimated_total_usd"],
            "limit_remaining": snapshot["account"].get("limit_remaining"),
            "frame_bytes": snapshot["frame_bytes"],
        }, ensure_ascii=False, indent=2))
        return 0
    if args.action in {"submit", "run"}:
        for name, prompt in PROMPTS.items():
            job = submit_one(key, name, prompt, snapshot["estimated_total_usd"] / 2)
            print(json.dumps({"name": name, "id": job.get("id"), "status": job.get("status")}, ensure_ascii=False), flush=True)
        if args.action == "submit":
            return 0
    for name in PROMPTS:
        result = poll_one(key, name)
        if result.get("status") != "completed":
            raise RuntimeError(f"{name} failed: {json.dumps(result, ensure_ascii=False)}")
        path = download(key, name, result["id"])
        print(json.dumps({"name": name, "downloaded": str(path), "bytes": path.stat().st_size, "usage": result.get("usage")}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
