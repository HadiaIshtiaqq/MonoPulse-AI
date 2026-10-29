"""Speech for video ads, all free and on this computer:

  * a voice that reads the script (Piper, an open-source voice generator; the voice is trained on
    the public-domain LJ Speech recordings, so it's fine for ads). Note: the Piper package itself is
    GPL-3.0: fine for running MonoPlus yourself; replace it before selling MonoPlus as closed software;
  * word-by-word timing of what a real person said in a video (Whisper, open-source speech
    recognition, through faster-whisper), for captions that follow the speaker.

Audio is decoded with ffmpeg. faster-whisper would otherwise decode with PyAV, whose library
Windows Smart App Control blocks on some PCs; MonoPlus never loads it.
"""
from __future__ import annotations

import io
import logging
import subprocess
import sys
import threading
import types
import wave
from dataclasses import dataclass
from pathlib import Path

import httpx

from .. import config

log = logging.getLogger(__name__)

VOICES = {  # key: (folder in rhasspy/piper-voices, file stem, label)
    "en-female": ("en/en_US/ljspeech/medium", "en_US-ljspeech-medium", "English (US), female"),
}
VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/{folder}/{stem}{ext}"
WHISPER_MODEL = config.WHISPER_MODEL
_voices: dict[str, object] = {}
_whisper = None
_lock = threading.Lock()


class SpeechError(RuntimeError):
    pass


def voice_dir() -> Path:
    return config.BROWSER_PROFILE_DIR.parent / "voices"


def tts_available() -> bool:
    try:
        import piper  # noqa: F401
        return True
    except Exception:  # noqa: BLE001 - not installed, or blocked
        return False


def whisper_available() -> bool:
    try:
        import ctranslate2  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _voice(key: str):
    """The Piper voice, downloaded once (about 60 MB) into MonoPlus's folder."""
    if key not in VOICES:
        raise SpeechError("Unknown voice.")
    with _lock:
        if key in _voices:
            return _voices[key]
        folder, stem, _ = VOICES[key]
        d = voice_dir()
        d.mkdir(parents=True, exist_ok=True)
        for ext in (".onnx", ".onnx.json"):
            target = d / f"{stem}{ext}"
            if not target.exists():
                log.info("downloading voice %s%s", stem, ext)
                with httpx.stream("GET", VOICE_URL.format(folder=folder, stem=stem, ext=ext), follow_redirects=True, timeout=300) as r:
                    r.raise_for_status()
                    part = target.with_suffix(target.suffix + ".part")
                    with open(part, "wb") as fh:
                        for chunk in r.iter_bytes(1 << 16):
                            fh.write(chunk)
                    part.replace(target)
        from piper import PiperVoice

        _voices[key] = PiperVoice.load(d / f"{stem}.onnx")
        return _voices[key]


def speak(lines: list[str], out_wav: Path, voice: str = "en-female", gap: float = 0.22) -> list[float]:
    """Read each line aloud into one WAV file, with a short pause after each. Returns how long each
    line takes (including its pause), so the video's shots can follow the voice."""
    v = _voice(voice)
    frames: list[bytes] = []
    durations: list[float] = []
    rate, width, channels = 22050, 2, 1
    for line in lines:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            v.synthesize_wav(line, wf)
        buf.seek(0)
        with wave.open(buf, "rb") as rf:
            rate, width, channels = rf.getframerate(), rf.getsampwidth(), rf.getnchannels()
            data = rf.readframes(rf.getnframes())
        pause = b"\x00" * int(rate * gap) * width * channels
        frames.append(data + pause)
        durations.append(len(data + pause) / (rate * width * channels))
    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        wf.writeframes(b"".join(frames))
    return durations


# --------------------------------------------------------------------------- listening

@dataclass
class Word:
    text: str
    start: float
    end: float


def decode_audio(path: str, rate: int = 16000):
    """The file's sound as 16 kHz mono float samples, decoded by ffmpeg."""
    import numpy as np

    from .reels.render import ffmpeg_exe

    proc = subprocess.run([ffmpeg_exe(), "-nostdin", "-loglevel", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(rate),
                           "-f", "s16le", "-"], capture_output=True, timeout=600)
    if proc.returncode != 0 or not proc.stdout:
        raise SpeechError("The video's sound couldn't be read." + (f" ({proc.stderr.decode(errors='replace')[:160]})" if proc.stderr else ""))
    return np.frombuffer(proc.stdout, np.int16).astype(np.float32) / 32768.0


def _model():
    global _whisper
    with _lock:
        if _whisper is None:
            try:
                import av  # noqa: F401
            except Exception:  # noqa: BLE001 - PyAV missing or blocked: faster-whisper only needs it to decode files, which ffmpeg does here
                sys.modules["av"] = types.ModuleType("av")
            from faster_whisper import WhisperModel

            _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8",
                                    download_root=str(config.BROWSER_PROFILE_DIR.parent / "whisper"))
        return _whisper


def transcribe(path: str, prompt: str = "") -> tuple[list[Word], str]:
    """Every word spoken in the file with its start and end time, plus the language heard. The
    script, when there is one, is given as a hint so names and prices come out right."""
    audio = decode_audio(path)
    segments, info = _model().transcribe(audio, word_timestamps=True, initial_prompt=prompt[:400] or None, vad_filter=False,
                                         beam_size=5)
    words = [Word(w.word.strip(), float(w.start), float(w.end)) for s in segments for w in (s.words or []) if w.word.strip()]
    return words, getattr(info, "language", "") or ""
