"""UGC videos: every ad looks different, the AI voice sets the pace, and real-person clips get
captions that follow what was said (spelled like the script)."""
import os
import subprocess
from types import SimpleNamespace

import pytest

from app.agents import speech, ugc_video
from app.agents.reels.render import ffmpeg_exe
from test_core import _kit
from test_features import _png_bytes


def test_ads_get_different_mixes_and_never_repeat_a_move_back_to_back():
    mixes = [ugc_video.choose_mix(6, seed) for seed in range(40)]
    assert len({(m.look, m.caption) for m in mixes}) >= 12  # plenty of different looks
    assert {m.look for m in mixes} == set(ugc_video.LOOKS) and {m.caption for m in mixes} == set(ugc_video.CAPTIONS)
    for m in mixes:
        assert all(a != b for a, b in zip(m.motions, m.motions[1:]))
    nxt = ugc_video.choose_mix(4, 7, avoid={"look": "card", "caption": "box"})
    assert nxt.look != "card" and nxt.caption != "box"  # the next ad differs from the last one
    chosen = ugc_video.choose_mix(4, 7, look="polaroid", caption="pop")
    assert (chosen.look, chosen.caption) == ("polaroid", "pop")


def test_spoken_text_reads_like_a_person_would_say_it():
    assert ugc_video.for_speech("POV: you found it for Rs. 6,990") == "P O V: you found it for 6,990 rupees"
    assert ugc_video.for_speech("$9 & 20% off 🔥") == "9 dollars  and  20 percent off"


def test_captions_use_the_scripts_spelling_but_only_for_words_actually_said():
    heard = [SimpleNamespace(text=t, start=i * 0.5, end=i * 0.5 + 0.4) for i, t in enumerate(
        ["Puff.", "You", "just", "found", "the", "chicken", "crispy", "roll.", "Just", "450", "robies.", "Honestly", "amazing."])]
    words = ugc_video.align_to_script(heard, ["POV: you just found the Chicken Crispy Roll", "Just Rs. 450", "Tap the link in bio"])
    text = " ".join(t for t, _, _ in words)
    assert "Chicken Crispy Roll" in text and "POV:" in text
    assert "Honestly amazing." in text  # said off-script: kept as heard
    assert "rupees" in text and "robies" not in text
    split = [SimpleNamespace(text=w, start=i * 0.4, end=i * 0.4 + 0.3) for i, w in enumerate(
        ["P", "-O", "-V,", "you", "just", "found", "the", "seat", "at", "Sourdo,", "Just", "$9"])]
    fixed = [w for w, _, _ in ugc_video.align_to_script(split, ["POV: you just found the Seeded Sourdough", "Just $9"])]
    assert fixed[0] == "POV:" and "Seeded" in fixed and "Sourdough" in fixed and "seat" not in fixed
    pieces = [SimpleNamespace(text=w, start=i * 0.3, end=i * 0.3 + 0.2) for i, w in enumerate(["Just", "12", ",990", "rupees"])]
    assert [w for w, _, _ in ugc_video.align_to_script(pieces, [])] == ["Just", "12,990", "rupees"]
    assert "Tap" not in text and "bio" not in text  # in the script but never said: not added
    assert [round(s, 1) for _, s, _ in words] == [round(i * 0.5, 1) for i in range(len(heard))]  # timings untouched


def test_product_mentions_bring_in_the_product_photo():
    words = [("The", 0.0, 0.2), ("Chicken", 0.3, 0.6), ("Crispy", 0.6, 0.9), ("Roll", 0.9, 1.2), ("costs", 3.0, 3.3), ("450", 3.4, 3.8)]
    spans = ugc_video.mentions(words, ["Chicken Crispy Roll", "Rs. 450"])
    assert spans[0][0] == 0.3 and any(s[0] == 3.4 for s in spans)


@pytest.mark.parametrize("look", ugc_video.LOOKS)
def test_every_layout_renders(tmp_path, monkeypatch, look):
    monkeypatch.setattr(ugc_video, "FPS", 3)
    photo = tmp_path / "p.png"
    photo.write_bytes(_png_bytes(size=(800, 1000)))
    mix = ugc_video.choose_mix(2, 5, look=look)
    out = tmp_path / "ad.mp4"
    secs = ugc_video.render_product_ad(_kit(), str(photo), ["First look: the loaf", "Just $9"], out, tmp_path / "ad.jpg", mix,
                                       end=("Seeded Sourdough", "$9", "Link in bio"))
    assert secs > 4 and out.read_bytes()[4:8] == b"ftyp"


# Downloads the voice and Whisper's model (about 200 MB) on first run, so it's skipped on CI.
needs_speech = pytest.mark.skipif(not (speech.tts_available() and speech.whisper_available()) or bool(os.environ.get("CI")),
                                  reason="speech engines not installed, or running on CI")


@needs_speech
def test_a_real_person_style_clip_end_to_end(tmp_path, monkeypatch):
    """Stand-in for a recorded person: a video whose sound is the AI voice reading the script."""
    monkeypatch.setattr(ugc_video, "FPS", 6)
    script = ["POV: you just found the Seeded Sourdough", "Just $9", "Tap the link in bio"]
    wav = tmp_path / "voice.wav"
    speech.speak([ugc_video.for_speech(s) for s in script], wav)
    clip = tmp_path / "clip.mp4"
    subprocess.run([ffmpeg_exe(), "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0x885533:s=720x1280:r=24", "-i", str(wav),
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip)], check=True)
    photo = tmp_path / "p.png"
    photo.write_bytes(_png_bytes(size=(600, 600)))
    out = tmp_path / "ad.mp4"
    secs, said = ugc_video.make_person_ad(_kit(), str(clip), script, str(photo), ["Seeded Sourdough", "$9"], out, tmp_path / "ad.jpg",
                                          "box", 3, ("Seeded Sourdough", "$9", "Link in bio"))
    assert out.read_bytes()[4:8] == b"ftyp" and secs > 3
    assert "Sourdough" in said[0] and "link" in said[0].lower()
    probe = subprocess.run([ffmpeg_exe(), "-i", str(out)], capture_output=True, text=True, errors="replace").stderr
    assert "Audio: aac" in probe and "1080x1920" in probe  # the person's own sound, upright 9:16


def test_a_browser_recording_without_a_duration_is_measured(tmp_path):
    """MediaRecorder's WebM files carry no duration in their header."""
    clip = tmp_path / "rec.webm"
    subprocess.run([ffmpeg_exe(), "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x568:r=15", "-f", "lavfi",
                    "-i", "sine=frequency=440", "-t", "3", "-c:v", "libvpx", "-c:a", "libopus", "-live", "1", "-f", "webm", str(clip)], check=True)
    assert 2.5 <= ugc_video.probe_duration(str(clip)) <= 3.5
    bad = tmp_path / "x.webm"
    bad.write_bytes(b"not a video")
    with pytest.raises(ugc_video.VideoError):
        ugc_video.probe_duration(str(bad))
