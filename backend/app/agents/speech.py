"""Speech for video ads, all free and on this computer:

  * voices that read the script, in several accents and languages including Urdu (Piper, an
    open-source voice generator; see VOICE_LIST for which voices are licensed for paid ads). Note:
    the Piper package itself is GPL-3.0: fine for running MonoPlus yourself; replace it before
    selling MonoPlus as closed software;
  * word-by-word timing of what a real person said in a video (Whisper, open-source speech
    recognition, through faster-whisper), for captions that follow the speaker.

Audio is decoded with ffmpeg. faster-whisper would otherwise decode with PyAV, whose library
Windows Smart App Control blocks on some PCs; MonoPlus never loads it.
"""
from __future__ import annotations

import io
import logging
import re
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

@dataclass(frozen=True)
class Voice:
    key: str
    name: str
    accent: str  # "English · British", "Urdu · Pakistani"...
    gender: str
    folder: str  # in rhasspy/piper-voices
    stem: str
    clear: bool  # True: trained on recordings licensed for commercial use, start to finish
    license: str

    @property
    def language(self) -> str:
        return self.stem.split("_")[0]


# Every voice is free and runs on this computer. "clear" voices are trained, start to finish, on
# recordings whose licence allows commercial use (public domain, CC0, CC-BY, MIT, Apache): fine for
# paid ads. The others are built on a voice trained on research-licensed recordings ("lessac"), so
# they're labelled for testing: check before using them in paid ads.
VOICE_LIST = [
    Voice("en-us-ljspeech", "Linda", "English · American", "female", "en/en_US/ljspeech/medium", "en_US-ljspeech-medium", True, "Public domain"),
    Voice("en-us-kristin", "Kristin", "English · American", "female", "en/en_US/kristin/medium", "en_US-kristin-medium", True, "Public domain"),
    Voice("en-us-john", "John", "English · American", "male", "en/en_US/john/medium", "en_US-john-medium", True, "Public domain"),
    Voice("en-us-bryce", "Bryce", "English · American", "male", "en/en_US/bryce/medium", "en_US-bryce-medium", True, "Public domain"),
    Voice("en-us-norman", "Norman", "English · American", "male", "en/en_US/norman/medium", "en_US-norman-medium", True, "Public domain"),
    Voice("en-gb-cori", "Cori", "English · British", "female", "en/en_GB/cori/medium", "en_GB-cori-medium", True, "Public domain"),
    Voice("ur-pk-aegis", "Ayesha", "Urdu · Pakistani", "female", "ur/ur_PK/aegis_female/medium", "ur_PK-aegis_female-medium", True, "MIT"),
    Voice("ur-pk-fasih", "Fasih", "Urdu · Pakistani", "male", "ur/ur_PK/fasih/medium", "ur_PK-fasih-medium", True, "MIT"),
    Voice("it-serena", "Serena", "Italian", "female", "it/it_IT/serena/medium", "it_IT-serena-medium", True, "CC BY 4.0"),
    Voice("te-padmavathi", "Padmavathi", "Telugu", "female", "te/te_IN/padmavathi/medium", "te_IN-padmavathi-medium", True, "CC BY 4.0"),
    Voice("es-mx-claude", "Claudio", "Spanish · Mexican", "male", "es/es_MX/claude/high", "es_MX-claude-high", True, "Apache 2.0"),
    Voice("en-gb-alba", "Alba", "English · Scottish", "female", "en/en_GB/alba/medium", "en_GB-alba-medium", False, "CC BY 4.0"),
    Voice("en-gb-north", "Harry", "English · Northern English", "male", "en/en_GB/northern_english_male/medium",
          "en_GB-northern_english_male-medium", False, "CC BY-SA 4.0"),
    Voice("en-us-joe", "Joe", "English · American", "male", "en/en_US/joe/medium", "en_US-joe-medium", False, "CC0"),
    Voice("en-us-reza", "Reza", "English · Persian accent", "male", "en/en_US/reza_ibrahim/medium", "en_US-reza_ibrahim-medium", False, "CC0"),
    Voice("es-es-davefx", "David", "Spanish · Spain", "male", "es/es_ES/davefx/medium", "es_ES-davefx-medium", False, "CC0"),
    Voice("fr-siwis", "Siwis", "French", "female", "fr/fr_FR/siwis/medium", "fr_FR-siwis-medium", False, "CC BY 4.0"),
    Voice("de-thorsten", "Thorsten", "German", "male", "de/de_DE/thorsten/medium", "de_DE-thorsten-medium", False, "CC0"),
    Voice("pt-br-faber", "Faber", "Portuguese · Brazilian", "male", "pt/pt_BR/faber/medium", "pt_BR-faber-medium", False, "CC0"),
    Voice("ru-denis", "Denis", "Russian", "male", "ru/ru_RU/denis/medium", "ru_RU-denis-medium", False, "CC0"),
    Voice("fa-amir", "Amir", "Persian", "male", "fa/fa_IR/amir/medium", "fa_IR-amir-medium", False, "CC0"),
    Voice("ne-chitwan", "Chitwan", "Nepali", "male", "ne/ne_NP/chitwan/medium", "ne_NP-chitwan-medium", False, "CC0"),
]
VOICES = {v.key: v for v in VOICE_LIST}
VOICES["en-female"] = VOICES["en-us-ljspeech"]  # the key earlier versions used
DEFAULT_VOICE = "en-us-ljspeech"
# The English voice that reads names and Latin words inside an Urdu line (a code-switch, as people speak).
ENGLISH_PARTNER = {"female": "en-us-ljspeech", "male": "en-us-john"}
RATE = 22050
URDU_PUNCTUATION = str.maketrans("", "", "،؛؟۔")  # ، ؛ ؟ ۔
ARABIC_SCRIPT = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")


def voice_list() -> list[dict]:
    return [{"key": v.key, "name": v.name, "accent": v.accent, "gender": v.gender, "language": v.language, "clear": v.clear,
             "license": v.license} for v in VOICE_LIST]


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
        folder, stem = VOICES[key].folder, VOICES[key].stem
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


def _synth(voice_key: str, text: str):
    """One stretch of speech as 16-bit samples at RATE (voices have different native rates)."""
    import numpy as np

    v = _voice(voice_key)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        v.synthesize_wav(text, wf)
    buf.seek(0)
    with wave.open(buf, "rb") as rf:
        rate, channels = rf.getframerate(), rf.getnchannels()
        data = np.frombuffer(rf.readframes(rf.getnframes()), np.int16)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1).astype(np.int16)
    if rate != RATE and len(data):
        x = np.linspace(0, len(data) - 1, int(len(data) * RATE / rate))
        data = np.interp(x, np.arange(len(data)), data).astype(np.int16)
    return data


def runs(line: str) -> list[tuple[bool, str]]:
    """A line split into Urdu-script and Latin stretches: [(is_urdu, text)]. Digits and
    punctuation stay with the stretch they're in."""
    out: list[tuple[bool, str]] = []
    for word in line.split():
        urdu = bool(ARABIC_SCRIPT.search(word.translate(URDU_PUNCTUATION)))  # "Roll،" is an English word
        latin = bool(re.search(r"[A-Za-z]", word))
        kind = urdu if (urdu or latin) else (out[-1][0] if out else False)
        if out and out[-1][0] == kind:
            out[-1] = (kind, out[-1][1] + " " + word)
        else:
            out.append((kind, word))
    return out


def for_speech(line: str) -> str:
    """How English shorthand is read aloud: "POV" -> "P O V", "Rs. 6,990" -> "6,990 rupees"."""
    s = re.sub(r"\bPOV\b", "P O V", line)
    s = re.sub(r"\b(?:Rs\.?|PKR)\s?([\d,]+(?:\.\d+)?)", r"\1 rupees", s)
    s = re.sub(r"\$\s?([\d,]+(?:\.\d+)?)", r"\1 dollars", s)
    s = s.replace("%", " percent").replace("&", " and ")
    return re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", s).strip()


def speak(lines: list[str], out_wav: Path, voice: str = DEFAULT_VOICE, gap: float = 0.22) -> list[float]:
    """Read each line aloud into one WAV file, with a short pause after each. Returns how long each
    line takes (including its pause), so the video can follow the voice. With an Urdu voice, English
    words in a line (product names, "POV") are read by an English voice of the same gender."""
    import numpy as np

    if voice not in VOICES:
        raise SpeechError("Unknown voice.")
    v = VOICES[voice]
    urdu = v.language == "ur"
    partner = ENGLISH_PARTNER[v.gender]
    pieces, durations = [], []
    for line in lines:
        parts = runs(line) if urdu else [(False, line)]
        audio = []
        for is_urdu, text in parts:
            if urdu and not is_urdu:
                if not re.search(r"[A-Za-z0-9]", text):
                    continue
                audio.append(_synth(partner, for_speech(text)))
            else:
                audio.append(_synth(voice, text if urdu else (for_speech(text) if v.language == "en" else text)))
            audio.append(np.zeros(int(RATE * 0.04), np.int16))  # a breath between switched stretches
        audio.append(np.zeros(int(RATE * gap), np.int16))
        line_audio = np.concatenate(audio) if audio else np.zeros(int(RATE * gap), np.int16)
        pieces.append(line_audio)
        durations.append(len(line_audio) / RATE)
    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(np.concatenate(pieces).tobytes() if pieces else b"")
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
