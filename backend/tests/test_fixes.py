"""The rough edges, smoothed: AI video that can't film falls back to the 3D camera, jobs outlive a
restart, voiced ads get music underneath, Roman Urdu is spoken from Urdu letters, 3D shots get a focus
pull or a light sweep, and older campaigns are matched as duplicates by their website."""
import asyncio
import subprocess
import time
import wave
from datetime import datetime, timedelta, timezone

import numpy as np
from PIL import Image

from app import config
from app.agents import depth3d, scenes, speech, ugc, ugc_video
from app.agents.reels.render import ffmpeg_exe
from app.jobbook import JobBook
from app.schemas import Product
from test_features import _campaign_with_posts, _png_bytes, client, offline  # noqa: F401 - fixtures


def _fake_depth(img):
    return np.tile(np.linspace(0, 1, img.height, dtype=np.float32)[:, None], (1, img.width))


def _fake_speak(lines, out_wav, voice="", gap=0.22):
    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"\x00\x00" * int(22050 * 1.2 * len(lines)))
    return [1.2 for _ in lines]


def test_when_ai_video_cant_film_the_3d_camera_does(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ugc_video, "FPS", 6)
    monkeypatch.setattr(depth3d, "FPS", 6)
    monkeypatch.setattr(depth3d, "model_path", lambda: "unused")
    monkeypatch.setattr(depth3d, "depth_map", _fake_depth)
    monkeypatch.setattr(speech, "tts_available", lambda: True)
    monkeypatch.setattr(speech, "speak", _fake_speak)

    def busy(*a, **kw):
        raise scenes.SceneError("Hugging Face's free video GPUs are busy.")

    monkeypatch.setattr(scenes, "generate", busy)
    c = _campaign_with_posts(days=1)
    photo = config.MEDIA_DIR / "up_fallback.png"
    photo.write_bytes(_png_bytes(size=(900, 1200)))
    c.brand.products = [Product(name="Kurta", price="Rs.6,000", image_url="/media/up_fallback.png")]
    r = client.post(f"/api/campaigns/{c.id}/ugc", json={"product": 0, "lines": ["the kurta", "Rs.6,000"], "engine": "scenes",
                                                        "source": "ai", "music": False})
    assert r.status_code == 202, r.text
    for _ in range(1200):
        j = client.get(f"/api/ugc-jobs/{r.json()['job_id']}").json()
        if j["status"] != "running":
            break
        time.sleep(0.25)
    assert j["status"] == "done", j
    assert j["result"]["source"] == "local" and "3D camera" in j["note"]


def test_jobs_outlive_a_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    jobs = JobBook("ugc")
    now = datetime.now(timezone.utc)
    jobs["a"] = {"status": "done", "result": {"id": "ad1"}, "at": now}
    jobs["b"] = {"status": "running", "step": "Filming", "at": now}
    jobs["old"] = {"status": "done", "at": now - timedelta(days=2)}
    jobs.save()
    again = JobBook("ugc")  # after a restart
    assert again["a"]["result"] == {"id": "ad1"} and "old" not in again
    assert again["b"]["status"] == "error" and "restarted" in again["b"]["error"]


def test_voiced_ads_have_music_underneath_and_it_runs_under_the_end_card(monkeypatch, tmp_path):
    monkeypatch.setattr(ugc_video, "FPS", 6)
    monkeypatch.setattr(speech, "speak", _fake_speak)
    clip = tmp_path / "c.mp4"
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=280x416:r=16:d=2", "-pix_fmt", "yuv420p",
                    str(clip)], check=True)
    out = tmp_path / "ad.mp4"
    ugc_video.make_scene_ad(_kit(), [str(clip)], ["one two", "three"], "en-us-ljspeech", out, tmp_path / "p.jpg", "box", 2,
                            ("Kurta", "Rs.1", "Link in bio"), music_bed=True)
    # Decode the sound: after the voice stops (2.4 s), the music is still playing under the end card.
    pcm = subprocess.run([ffmpeg_exe(), "-loglevel", "error", "-ss", "2.8", "-t", "1.0", "-i", str(out), "-f", "s16le", "-ac", "1", "-"],
                         capture_output=True).stdout
    level = np.abs(np.frombuffer(pcm, np.int16)).mean()
    assert level > 20
    assert not out.with_suffix(".mix.wav").exists() and not out.with_suffix(".bed.wav").exists()


def test_roman_urdu_is_spoken_from_urdu_letters(monkeypatch):
    from app.llm import router

    monkeypatch.setattr(type(router), "enabled", property(lambda self: True))

    async def fake(purpose, system, user, **kw):
        assert purpose == "transliterate" and "Latin letters" in system
        return {"lines": ["یہ ہے Black Kurta", "Rs.6,000"]}

    monkeypatch.setattr(router, "complete_json", fake)
    assert asyncio.run(ugc.to_urdu_script(["Yeh hai Black Kurta", "Rs.6,000"])) == ["یہ ہے Black Kurta", "Rs.6,000"]

    async def wrong(purpose, system, user, **kw):
        return {"lines": ["only one"]}

    monkeypatch.setattr(router, "complete_json", wrong)
    assert asyncio.run(ugc.to_urdu_script(["a", "b"])) is None  # doesn't fit: the voice reads the Roman Urdu instead


def test_3d_shots_get_a_focus_pull_or_a_light_sweep(monkeypatch, tmp_path):
    monkeypatch.setattr(depth3d, "FPS", 6)
    monkeypatch.setattr(depth3d, "depth_map", _fake_depth)
    photo = tmp_path / "p.png"
    img = Image.new("RGB", (600, 900), (120, 60, 90))
    for y in range(0, 900, 30):
        img.paste((230, 200, 120), (0, y, 600, y + 4))  # stripes, so blur shows
    img.save(photo)
    frames = {}
    for effect in ("none", "rack_in", "sweep"):
        out = depth3d.make_clip(str(photo), "full", "dolly_in", 1.0, tmp_path / f"{effect}.mp4", 1, effect)
        raw = subprocess.run([ffmpeg_exe(), "-loglevel", "error", "-i", str(out), "-vframes", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                             capture_output=True).stdout
        frames[effect] = np.frombuffer(raw, np.uint8).reshape(depth3d.H, depth3d.W).astype(np.float32)
    # A pull from the background starts with the background (the top here) sharp and the foreground soft.
    sharp = lambda a: np.abs(np.diff(a, axis=0)).mean()  # noqa: E731
    assert sharp(frames["rack_in"][-300:]) < sharp(frames["none"][-300:]) * 0.8
    assert sharp(frames["rack_in"][:200]) > sharp(frames["rack_in"][-300:])
    assert frames["sweep"].mean() > frames["none"].mean()  # the light adds brightness


def test_older_campaigns_are_matched_as_duplicates_by_their_website(client):  # noqa: F811
    a, b = _campaign_with_posts(days=1), _campaign_with_posts(days=1)
    a.source_input, b.source_input = "", "https://www.tartinebakery.com/?utm_source=ig"
    a.brand.website_url = "https://tartinebakery.com/"
    rows = {c["id"]: c for c in client.get("/api/campaigns").json()}
    assert rows[a.id]["source"] == rows[b.id]["source"] == "tartinebakery.com"


def _kit():
    from test_core import _kit as kit

    return kit()
