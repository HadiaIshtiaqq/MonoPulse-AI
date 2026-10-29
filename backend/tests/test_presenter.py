"""The free AI presenter, the voices (accents, languages, Urdu) and Urdu captions."""
import os
import time
import wave

import numpy as np
import pytest

from app.agents import avatar, speech, ugc, ugc_video
from test_core import _kit
from test_features import _campaign_with_posts, _png_bytes, client, offline  # noqa: F401 - fixtures


def test_every_presenter_draws():
    for ch in avatar.CHARACTERS:
        img = avatar.preview(ch, size=200)
        assert img.size[0] <= 200 and img.getbbox()
    assert {c.gender for c in avatar.CHARACTERS} == {"female", "male"} and any(c.style == "hijab" for c in avatar.CHARACTERS)


def test_lips_follow_the_voice(tmp_path):
    rate = 22050
    t = np.arange(int(rate * 1.0)) / rate
    tone = (np.sin(2 * np.pi * 300 * t) * 12000).astype(np.int16)
    silence = np.zeros(int(rate * 0.5), np.int16)
    path = tmp_path / "v.wav"
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(np.concatenate([silence, tone, silence]).tobytes())
    frames = avatar.lipsync(str(path), 60)
    assert frames[5][0] < 0.08 and frames[5][1] == "closed"  # silent: mouth shut
    assert max(level for level, _ in frames[18:45]) > 0.5  # speaking: mouth open
    assert frames[58][0] < 0.2  # closes again


def test_voices_cover_accents_languages_and_say_which_are_clear_for_ads():
    voices = speech.voice_list()
    accents = {v["accent"] for v in voices}
    assert {"English · American", "English · British", "English · Scottish", "Urdu · Pakistani"} <= accents
    assert len({v["language"] for v in voices}) >= 8
    urdu = [v for v in voices if v["language"] == "ur"]
    assert {v["gender"] for v in urdu} == {"female", "male"} and all(v["clear"] for v in urdu)
    assert not next(v for v in voices if v["key"] == "en-gb-alba")["clear"]  # built on a research-licensed voice


def test_urdu_lines_hand_english_words_to_an_english_voice():
    assert speech.runs("یہ ہے Chicken Crispy Roll، صرف Rs. 450 میں") == [
        (True, "یہ ہے"), (False, "Chicken Crispy Roll،"), (True, "صرف"), (False, "Rs. 450"), (True, "میں")]


def test_scripts_in_urdu_and_roman_urdu_keep_the_real_facts():
    from app.schemas import Product

    p = Product(name="Seeded Sourdough", price="Rs. 900", url="https://b.example/p", image_url="https://b.example/p.jpg")
    for lang in ("ur", "roman"):
        for fmt in ugc.FORMATS:
            lines = ugc.template_script(_kit(), p, fmt, lang)
            assert "Seeded Sourdough" in " ".join(lines) and "Rs. 900" in " ".join(lines), (lang, fmt)
    assert any(ugc_video.lang_mod.ARABIC.search(x) for x in ugc.template_script(_kit(), p, "pov", "ur"))


def test_urdu_captions_run_right_to_left_with_english_kept_in_order():
    words = ["پہلی", "نظر:", "Light", "Khaddar", "Suit"]
    xs = ugc_video._positions(words, [100, 100, 80, 120, 90], 0, 490, True)
    assert xs[0] > xs[1] > xs[2]  # Urdu from the right
    assert xs[2] < xs[3] < xs[4]  # the English run left to right


needs_speech = pytest.mark.skipif(not speech.tts_available() or bool(os.environ.get("CI")), reason="voice not installed, or on CI")


@needs_speech
def test_a_presenter_ad_end_to_end(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ugc_video, "FPS", 4)
    monkeypatch.setattr(avatar, "FPS", 4)
    from app import config
    from app.schemas import Product

    c = _campaign_with_posts(days=1)
    (config.MEDIA_DIR / "up_presenterphoto.png").write_bytes(_png_bytes(size=(800, 800)))
    c.brand.products = [Product(name="Seeded Sourdough", price="$9", url="https://b.example/p", image_url="/media/up_presenterphoto.png")]
    info = client.get(f"/api/campaigns/{c.id}/ugc").json()
    assert info["presenters"] and info["voices"]
    assert client.get(info["presenters"][1]["preview"]).headers["content-type"] == "image/png"
    r = client.post(f"/api/campaigns/{c.id}/ugc", json={"product": 0, "format": "pov", "engine": "presenter", "character": "ali",
                                                        "lines": ["POV: you just found the Seeded Sourdough", "Just $9"]})
    assert r.status_code == 202, r.text
    for _ in range(240):
        j = client.get(f"/api/ugc-jobs/{r.json()['job_id']}").json()
        if j["status"] != "running":
            break
        time.sleep(0.5)
    assert j["status"] == "done", j
    assert j["result"]["avatar"] == "Ali" and j["result"]["voice"] and j["result"]["engine"] == "presenter"
    assert client.get(j["result"]["video_url"]).content[4:8] == b"ftyp"
