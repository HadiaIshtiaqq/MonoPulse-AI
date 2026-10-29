"""AI scenes: shots planned for the product, faceless kept faceless, the free GPUs tried in turn, and
the generated clips edited to the voice. No network: the video model is replaced by a test clip."""
import shutil
import subprocess
import sys
import time
import types
import wave

import pytest
from PIL import Image

from app import config
from app.agents import scenes, speech, ugc_video
from app.agents.reels.render import ffmpeg_exe
from app.schemas import Product
from test_core import _kit
from test_features import _campaign_with_posts, _png_bytes, client, offline  # noqa: F401 - fixtures

KURTA = Product(name="Black Cambric Kurta", price="Rs.6,000", category="Women kurta", image_url="https://b.example/k.jpg")


def _fashion():
    kit = _kit()
    kit.industry = "Fashion and clothing"
    return kit


def test_shots_fit_the_product_and_change_from_ad_to_ad():
    kit = _fashion()
    worn = scenes.plan(kit, KURTA, 3, "worn", 1)
    assert scenes.kind_of(kit, KURTA) == "fashion" and "turns" in worn[0].prompt  # the opener shows the whole outfit
    orders = {tuple(s.prompt for s in scenes.plan(kit, KURTA, 3, "worn", seed)) for seed in range(12)}
    assert len(orders) > 1
    faceless = scenes.plan(kit, KURTA, 4, "faceless", 3)
    assert all(s.crop in ("lower", "detail") for s in faceless)
    assert all("no face visible" in scenes.prompt_for(s, "faceless") for s in faceless)
    long = scenes.plan(kit, KURTA, 6, "worn", 2)
    assert len(long) == 6 and "different angle" in long[5].prompt
    food = _kit()
    food.industry = "Restaurant and food"
    assert "steam" in " ".join(s.prompt for s in scenes.plan(food, Product(name="Crispy Roll", image_url="x"), 3, "worn", 0))


def test_faceless_start_frame_drops_the_top_of_the_photo(tmp_path):
    photo = tmp_path / "p.png"
    img = Image.new("RGB", (600, 1000), (200, 30, 30))
    img.paste((30, 30, 200), (0, 0, 600, 250))  # the "face" end of a portrait photo
    img.save(photo)
    out = scenes.start_frame(str(photo), "lower", tmp_path / "s.jpg")
    frame = Image.open(out)
    assert frame.size == (576, 1024)
    r, g, b = frame.getpixel((288, 10))
    assert r > 150 and b < 100  # the top band is gone


def _fake_gradio(monkeypatch, outcomes):
    """gradio_client stand-in: each Space either raises or returns a clip path."""
    calls = []

    class Client:
        def __init__(self, space, token=None, **kw):
            self.space, self.token = space, token

        def predict(self, **kw):
            calls.append((self.space, self.token, kw))
            result = outcomes[self.space]
            if isinstance(result, Exception):
                raise result
            return (result, 1)

    monkeypatch.setitem(sys.modules, "gradio_client", types.SimpleNamespace(Client=Client, handle_file=lambda p: p))
    return calls


def _clip(path, seconds=2.0, color="red"):
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:s=280x416:r=16:d={seconds}",
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def test_the_next_free_gpu_is_tried_and_quota_is_explained(tmp_path, monkeypatch):
    photo = tmp_path / "p.png"
    photo.write_bytes(_png_bytes(size=(600, 900)))
    clip = _clip(tmp_path / "made.mp4")
    busy = RuntimeError('No GPU was available after 60s. <a href="https://huggingface.co/join">Create a free account</a>')
    calls = _fake_gradio(monkeypatch, {scenes.SPACES[0]: busy, scenes.SPACES[1]: str(clip)})
    monkeypatch.setattr(config, "HF_TOKEN", "")
    out = scenes.generate(str(photo), scenes.Scene("a hand picks it up"), "faceless", 5, tmp_path / "shot.mp4")
    assert out.exists() and [c[0] for c in calls] == scenes.SPACES
    kw = calls[-1][2]
    assert "no face visible" in kw["prompt"] and "face" in kw["negative_prompt"] and kw["seed"] == 5
    assert not (tmp_path / "shot.start.jpg").exists()  # the start frame is cleaned up

    _fake_gradio(monkeypatch, {s: busy for s in scenes.SPACES})
    with pytest.raises(scenes.SceneError, match="Connect a free Hugging Face account"):
        scenes.generate(str(photo), scenes.Scene("x"), "worn", 1, tmp_path / "shot2.mp4")
    calls = _fake_gradio(monkeypatch, {s: busy for s in scenes.SPACES})
    monkeypatch.setattr(config, "HF_TOKEN", "hf_" + "a" * 34)
    with pytest.raises(scenes.SceneError) as err:
        scenes.generate(str(photo), scenes.Scene("x"), "worn", 1, tmp_path / "shot3.mp4")
    assert "<a" not in str(err.value) and calls[0][1] == config.HF_TOKEN


def test_spoken_words_follow_each_line():
    words = ugc_video.spoken_words(["POV: you found it", "Just Rs.6,000"], [2.0, 1.5])
    assert [w for w, _, _ in words] == ["POV:", "you", "found", "it", "Just", "Rs.6,000"]
    assert all(s < e for _, s, e in words) and all(words[i][2] <= words[i + 1][1] + 1e-9 for i in range(len(words) - 1))
    assert words[3][2] <= 2.0 and words[4][1] >= 2.0 and words[-1][2] <= 3.5


def _fake_speak(lines, out_wav, voice="", gap=0.22):
    durations = [1.2 for _ in lines]
    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"\x00\x00" * int(22050 * sum(durations)))
    return durations


def test_scenes_are_cut_to_the_voice(tmp_path, monkeypatch):
    monkeypatch.setattr(ugc_video, "FPS", 6)
    monkeypatch.setattr(speech, "speak", _fake_speak)
    clips = [str(_clip(tmp_path / "a.mp4", 0.6, "red")), str(_clip(tmp_path / "b.mp4", 2.0, "blue"))]
    out = tmp_path / "ad.mp4"
    seconds = ugc_video.make_scene_ad(_kit(), clips, ["One two", "Three four", "Five six"], "en-us-ljspeech", out,
                                      tmp_path / "ad.jpg", "box", 3, ("Kurta", "Rs.6,000", "Link in bio"))
    assert out.exists() and 3.4 <= ugc_video.probe_duration(str(out)) <= 6.0 and seconds > 3.4
    assert not out.with_suffix(".voice.wav").exists() and not out.with_suffix(".scenes.mp4").exists()


def test_an_ai_scenes_ad_end_to_end(client, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(ugc_video, "FPS", 6)
    monkeypatch.setattr(speech, "speak", _fake_speak)
    monkeypatch.setattr(speech, "tts_available", lambda: True)
    clip = _clip(tmp_path / "gen.mp4", 1.5)
    filmed = []

    def fake_generate(photo, scene, style, seed, out):
        filmed.append((scene.prompt, style))
        if len(filmed) == 2:  # the free share runs out mid-ad: the ad is still made from what was filmed
            raise scenes.SceneError("Hugging Face's free video GPUs are busy")
        shutil.copyfile(clip, out)
        return out

    monkeypatch.setattr(scenes, "generate", fake_generate)
    c = _campaign_with_posts(days=1)
    photo = config.MEDIA_DIR / "up_scenephoto.png"
    photo.write_bytes(_png_bytes(size=(900, 1200)))
    c.brand.products = [Product(name="Black Cambric Kurta", price="Rs.6,000", image_url="/media/up_scenephoto.png")]
    overview = client.get(f"/api/campaigns/{c.id}/ugc").json()
    assert {s["key"] for s in overview["scenes"]["styles"]} == {"worn", "faceless", "aesthetic"}
    planned = client.post(f"/api/campaigns/{c.id}/ugc/scenes", json={"product": 0, "lines": 9, "style": "faceless"}).json()["scenes"]
    assert len(planned) == 4 and all(s["prompt"] for s in planned)
    lines = ["POV: you just found the Black Cambric Kurta", "Just Rs.6,000", "Link in bio"]
    r = client.post(f"/api/campaigns/{c.id}/ugc", json={"product": 0, "lines": lines, "engine": "scenes", "style": "faceless",
                                                        "source": "ai", "scenes": [{"prompt": "hands smooth the kurta", "crop": "lower"}]})
    assert r.status_code == 202, r.text
    for _ in range(120):
        j = client.get(f"/api/ugc-jobs/{r.json()['job_id']}").json()
        if j["status"] != "running":
            break
        time.sleep(0.25)
    assert j["status"] == "done", j
    ad = j["result"]
    assert ad["engine"] == "scenes" and ad["look"] == "faceless" and ad["voice"] and ad["seconds"] > 3
    assert filmed[0] == ("hands smooth the kurta", "faceless") and len(filmed) == 2
    assert client.get(ad["video_url"]).content[4:8] == b"ftyp"
    assert not list(config.MEDIA_DIR.glob("*_scene*.mp4"))  # generated shots don't pile up
    assert client.delete(f"/api/campaigns/{c.id}/ugc/{ad['id']}").status_code == 204


def test_aesthetic_ads_are_slow_faceless_and_have_their_own_script():
    from app.agents import ugc

    kit = _fashion()
    plan = scenes.plan(kit, KURTA, 4, "aesthetic", 5)
    prompts = [scenes.prompt_for(s, "aesthetic") for s in plan]
    assert all("no face visible" in p and "slow motion" in p for p in prompts)
    assert all(s.crop in ("lower", "detail") for s in plan)
    lines = ugc.template_script(kit, KURTA, "aesthetic")
    assert lines[0] == "the Black Cambric Kurta" and "every detail, up close" in lines
    assert not any(line.endswith("!") for line in lines)


def test_composed_music_fits_the_ad(tmp_path):
    from app.agents import music

    out = music.compose(5.0, tmp_path / "m.wav", seed=4)
    with wave.open(str(out)) as wf:
        assert wf.getnchannels() == 2 and abs(wf.getnframes() / wf.getframerate() - 5.0) < 0.01


def test_an_aesthetic_ad_has_music_not_a_voice(client, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(ugc_video, "FPS", 6)
    monkeypatch.setattr(speech, "tts_available", lambda: False)  # no voice installed: aesthetic ads don't need one

    def no_voice(*a, **kw):
        raise AssertionError("an aesthetic ad has no voice")

    monkeypatch.setattr(speech, "speak", no_voice)
    clip = _clip(tmp_path / "gen.mp4", 1.5)

    def fake_generate(photo, scene, style, seed, out):
        assert style == "aesthetic"
        shutil.copyfile(clip, out)
        return out

    monkeypatch.setattr(scenes, "generate", fake_generate)
    c = _campaign_with_posts(days=1)
    photo = config.MEDIA_DIR / "up_aesphoto.png"
    photo.write_bytes(_png_bytes(size=(900, 1200)))
    c.brand.products = [Product(name="Black Cambric Kurta", price="Rs.6,000", image_url="/media/up_aesphoto.png")]
    r = client.post(f"/api/campaigns/{c.id}/ugc", json={"product": 0, "format": "aesthetic", "lines": ["the kurta", "Rs.6,000"],
                                                        "engine": "scenes", "style": "aesthetic", "source": "ai"})
    assert r.status_code == 202, r.text
    for _ in range(120):
        j = client.get(f"/api/ugc-jobs/{r.json()['job_id']}").json()
        if j["status"] != "running":
            break
        time.sleep(0.25)
    assert j["status"] == "done", j
    ad = j["result"]
    assert ad["look"] == "aesthetic" and ad["caption"] == "soft" and not ad["voice"]
    path = config.MEDIA_DIR / ad["video_url"].removeprefix("/media/")
    probe = subprocess.run([ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True, errors="replace").stderr
    assert "Audio:" in probe and ugc_video.probe_duration(str(path)) > 5.5  # two unhurried shots and the end card
    assert client.delete(f"/api/campaigns/{c.id}/ugc/{ad['id']}").status_code == 204


def test_3d_camera_shots_are_made_on_this_computer(client, monkeypatch):  # noqa: F811
    """The default way to film AI scenes: depth from the photo, a moving camera, no service at all."""
    import numpy as np

    from app.agents import depth3d

    monkeypatch.setattr(ugc_video, "FPS", 6)
    monkeypatch.setattr(depth3d, "FPS", 6)
    monkeypatch.setattr(depth3d, "model_path", lambda: "unused")
    # A stand-in depth map: the bottom of the photo is near, the top far.
    monkeypatch.setattr(depth3d, "depth_map", lambda img: np.tile(np.linspace(0, 1, img.height, dtype=np.float32)[:, None], (1, img.width)))
    monkeypatch.setattr(speech, "tts_available", lambda: False)

    def no_ai(*a, **kw):
        raise AssertionError("3D shots don't use the AI video service")

    monkeypatch.setattr(scenes, "generate", no_ai)
    assert len(set(depth3d.moves_for(6, 1))) > 1
    assert all(a != b for a, b in zip(depth3d.moves_for(8, 2), depth3d.moves_for(8, 2)[1:]))
    c = _campaign_with_posts(days=1)
    photo = config.MEDIA_DIR / "up_3dphoto.png"
    photo.write_bytes(_png_bytes(size=(900, 1200)))
    c.brand.products = [Product(name="Black Cambric Kurta", price="Rs.6,000", image_url="/media/up_3dphoto.png")]
    assert client.get(f"/api/campaigns/{c.id}/ugc").json()["scenes"]["local"] is True
    r = client.post(f"/api/campaigns/{c.id}/ugc", json={"product": 0, "format": "aesthetic", "lines": ["the kurta", "Rs.6,000"],
                                                        "engine": "scenes", "style": "aesthetic"})
    assert r.status_code == 202, r.text
    for _ in range(240):
        j = client.get(f"/api/ugc-jobs/{r.json()['job_id']}").json()
        if j["status"] != "running":
            break
        time.sleep(0.25)
    assert j["status"] == "done", j
    ad = j["result"]
    assert ad["source"] == "local" and ad["look"] == "aesthetic" and ad["seconds"] > 5
    assert not list(config.MEDIA_DIR.glob("*_3d*.mp4"))  # the shots are cleaned up
    assert client.delete(f"/api/campaigns/{c.id}/ugc/{ad['id']}").status_code == 204


def test_the_camera_moves_stay_inside_the_photo():
    from app.agents import depth3d

    for move in depth3d.MOVES:
        for k in (0.0, 0.5, 1.0):
            zoom, side, up = depth3d.camera(move, k)
            assert 1.0 <= zoom <= 1.08 and abs(side) <= 0.031 and abs(up) <= 0.026, (move, k)


def test_nemotron_directs_the_shots_and_its_answer_is_kept_in_bounds(monkeypatch):
    import asyncio

    from app.agents import depth3d
    from app.llm import router

    monkeypatch.setattr(type(router), "enabled", property(lambda self: True))
    seen = {}

    async def fake_json(purpose, system, user, **kw):
        seen.update(purpose=purpose, system=system, user=user)
        return {"shots": [{"crop": "full", "move": "orbit_left", "shot": "a hand slowly traces the embroidery"},
                          {"crop": "detail", "move": "orbit_left", "shot": "slow push in on the stitching"},
                          {"crop": "lower", "move": "teleport", "shot": ""}]}

    monkeypatch.setattr(router, "complete_json", fake_json)
    plan, moves = asyncio.run(scenes.direct(_fashion(), KURTA, ["one", "two", "three"], "faceless", depth3d.MOVES))
    assert seen["purpose"] == "ugc_director" and "Never show a face" in seen["system"] and "Black Cambric Kurta" in seen["user"]
    assert plan[0].prompt == "a hand slowly traces the embroidery"
    assert [s.crop for s in plan] == ["detail", "detail", "lower"]  # faceless: no "full" crop, whatever it said
    assert moves[0] == "orbit_left" and moves[1] != "orbit_left" and moves[2] in depth3d.MOVES
    assert plan[2].prompt  # an empty description gets a sensible one

    async def too_few(*a, **kw):
        return {"shots": [{"crop": "full", "move": "rise", "shot": "x"}]}

    monkeypatch.setattr(router, "complete_json", too_few)
    assert asyncio.run(scenes.direct(_fashion(), KURTA, ["one", "two"], "worn", depth3d.MOVES)) is None
