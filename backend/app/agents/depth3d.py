"""3D camera shots made on this computer: no GPU, no account, no daily limit.

A depth model (Depth Anything V2 Small, Apache-2.0, about 100 MB, run with ONNX Runtime on the
processor) works out how far away every part of the product photo is. The photo is then filmed
with a moving virtual camera: things near the lens move more than the background, so a dolly,
orbit or rise has real parallax, like a phone gliding past the product, plus a little handheld
sway. Each line of the script gets its own crop and camera move.

The model file is downloaded once from its public page and then works offline.
"""
from __future__ import annotations

import math
import random
import subprocess
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

from ..schemas import BrandKit
from .reels.core import WORKERS

MODEL = ("onnx-community/depth-anything-v2-small", "onnx/model.onnx")  # Apache-2.0 (the Base and Large models are not)
W, H, FPS = 1080, 1920, 30
MARGIN = 1.12  # the photo is filmed a little larger than the frame, so moves never show an edge
STEP = 24  # warp mesh cell, in pixels
MOVES = ["dolly_in", "dolly_out", "orbit_left", "orbit_right", "rise", "drift"]
_session = None
_lock = threading.Lock()


class DepthError(RuntimeError):
    pass


def available() -> bool:
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def model_path() -> str:
    """The depth model on disk, downloaded the first time it's needed."""
    import time

    from huggingface_hub import hf_hub_download

    try:
        return hf_hub_download(*MODEL, local_files_only=True)
    except Exception:  # noqa: BLE001 - not downloaded yet
        pass
    last: Exception | None = None
    for wait in (0, 5, 15):  # a dropped connection or a busy server gets two more tries
        time.sleep(wait)
        try:
            return hf_hub_download(*MODEL)
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise DepthError("The 3D model couldn't be downloaded (about 100 MB, once): the connection dropped or the download site "
                     "is busy. Try again in a minute; once it's downloaded, 3D shots work offline.") from last


def _model():
    global _session
    with _lock:
        if _session is None:
            try:
                import onnxruntime as ort
            except ImportError as exc:
                raise DepthError("3D shots need ONNX Runtime: pip install onnxruntime") from exc
            _session = ort.InferenceSession(model_path(), providers=["CPUExecutionProvider"])
        return _session


def depth_map(img: Image.Image):
    """How near each pixel is, 0 (far) to 1 (near), the size of `img`."""
    import numpy as np

    w = 518
    h = max(14, round(w * img.height / img.width / 14) * 14)
    x = np.asarray(img.convert("RGB").resize((w, h), Image.BICUBIC), np.float32) / 255
    x = ((x - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]).transpose(2, 0, 1)[None].astype(np.float32)
    session = _model()
    d = session.run(None, {session.get_inputs()[0].name: x})[0].squeeze()
    d = (d - d.min()) / max(1e-6, float(d.max() - d.min()))
    small = Image.fromarray((d * 255).astype(np.uint8))
    # Smoothed, so edges bend instead of tearing as the camera moves.
    return np.asarray(small.resize(img.size, Image.BILINEAR).filter(ImageFilter.GaussianBlur(9)), np.float32) / 255


def _sample(a, x, y):
    import numpy as np

    x = np.clip(x, 0, a.shape[1] - 1.001)
    y = np.clip(y, 0, a.shape[0] - 1.001)
    x0, y0 = x.astype(np.int32), y.astype(np.int32)
    fx, fy = x - x0, y - y0
    top = a[y0, x0] * (1 - fx) + a[y0, x0 + 1] * fx
    bottom = a[y0 + 1, x0] * (1 - fx) + a[y0 + 1, x0 + 1] * fx
    return top * (1 - fy) + bottom * fy


def camera(move: str, k: float) -> tuple[float, float, float]:
    """(zoom, sideways, upward) for a move at k (0 to 1, eased). Sideways and upward are in frame widths."""
    return {
        "dolly_in": (1.0 + 0.07 * k, 0.0, 0.0),
        "dolly_out": (1.07 - 0.07 * k, 0.0, 0.0),
        "orbit_left": (1.03, (0.5 - k) * 0.06, 0.0),
        "orbit_right": (1.03, (k - 0.5) * 0.06, 0.0),
        "rise": (1.02 + 0.03 * k, 0.0, (k - 0.5) * 0.05),
        "drift": (1.02 + 0.04 * k, (k - 0.5) * 0.035, (0.5 - k) * 0.02),
    }[move]


def shot_frame(crop: str, photo: str) -> Image.Image:
    """The photo for one shot, upright 9:16 with room for the camera to move."""
    img = ImageOps.exif_transpose(Image.open(photo)).convert("RGB")
    w, h = img.size
    if crop == "lower" and h > w:
        img = img.crop((0, int(h * 0.3), w, h))
    elif crop == "detail":
        img = img.crop((int(w * 0.18), int(h * 0.22), int(w * 0.82), int(h * 0.8)))
    return ImageOps.fit(img, (int(W * MARGIN), int(H * MARGIN)), Image.LANCZOS, centering=(0.5, 0.45))


def make_clip(photo: str, crop: str, move: str, seconds: float, out: Path, seed: int = 0, effect: str = "") -> Path:
    """One 3D camera shot of the photo, `seconds` long, at `out`. `effect`: rack_in | rack_out | sweep |
    none ("" = picked from the seed)."""
    import numpy as np

    from .reels.render import ffmpeg_exe

    pic = shot_frame(crop, photo)
    dep = depth_map(pic)
    sh, sw = dep.shape
    gx = np.arange(0, W + 1, STEP, dtype=np.float32)
    gy = np.arange(0, H + 1, STEP, dtype=np.float32)
    GX, GY = np.meshgrid(gx, gy)
    focus = float(np.percentile(dep, 40))  # the camera pivots around the middle distance
    rng = random.Random(seed)
    phase = rng.uniform(0, 6.28)
    frames = max(2, int(seconds * FPS))
    # One cinematic touch per shot: a focus pull (the sharp plane slides between the background and the
    # product, like a real lens) or a soft band of light drifting across. Never both, sometimes neither.
    effect = effect or rng.choice(["rack_in", "rack_out", "sweep", "sweep", "none"])
    depth_img = Image.fromarray((dep * 255).astype(np.uint8)) if effect.startswith("rack") else None
    # The pull always lands on the product, in the middle of the frame: from the background (rack_in) or
    # from the foreground (rack_out), arriving two thirds of the way through the shot and holding.
    subject = float(np.median(dep[int(sh * 0.3):int(sh * 0.75), int(sw * 0.3):int(sw * 0.7)]))
    start = float(np.percentile(dep, 10)) if effect == "rack_in" else float(np.percentile(dep, 95))
    band = None
    if effect == "sweep":
        bw = W * 2
        xs = np.arange(bw, dtype=np.float32)[None, :] + np.arange(H, dtype=np.float32)[:, None] * 0.35  # tilted
        glow = np.exp(-(((xs % bw) - bw / 2) / (W * 0.16)) ** 2) * 46  # soft edges, at most ~18% brighter
        band = Image.fromarray(glow.astype(np.uint8), "L")
        warm = Image.new("RGB", (W, H), (255, 236, 205))

    def frame(f: int) -> bytes:
        t = f / (frames - 1)
        k = 0.5 - 0.5 * math.cos(math.pi * t)  # ease in and out
        zoom, side, up = camera(move, k)
        # A phone held in a hand: a slow, small sway.
        side += 0.0025 * math.sin(2 * math.pi * 0.45 * t * seconds + phase)
        up += 0.0018 * math.sin(2 * math.pi * 0.31 * t * seconds + phase * 1.7)
        bx = (GX - W / 2) / zoom + sw / 2
        by = (GY - H / 2) / zoom + sh / 2
        d = _sample(dep, bx, by) - focus
        # Near things move more than far ones (parallax), and grow faster as the camera closes in.
        sx = bx - side * W * d - (bx - sw / 2) * (zoom - 1) * 0.8 * d
        sy = by - up * W * d - (by - sh / 2) * (zoom - 1) * 0.8 * d
        mesh = []
        for j in range(len(gy) - 1):
            for i in range(len(gx) - 1):
                mesh.append(((int(gx[i]), int(gy[j]), int(gx[i + 1]), int(gy[j + 1])),
                             (float(sx[j, i]), float(sy[j, i]), float(sx[j + 1, i]), float(sy[j + 1, i]),
                              float(sx[j + 1, i + 1]), float(sy[j + 1, i + 1]), float(sx[j, i + 1]), float(sy[j, i + 1]))))
        img = pic.transform((W, H), Image.MESH, mesh, Image.BICUBIC)
        if depth_img is not None:
            plane = start + (subject - start) * min(1.0, k * 1.5)
            seen = depth_img.transform((W, H), Image.MESH, mesh, Image.BILINEAR)
            # How far each pixel is from the sharp plane decides how soft it is.
            mask = seen.point(lambda v, p=plane * 255: min(255, max(0, int((abs(v - p) - 12) * 2.4))))
            img = Image.composite(img.filter(ImageFilter.GaussianBlur(4.5)), img, mask)
        elif band is not None:
            x = int((1 - t) * W)  # the light drifts from left to right
            img.paste(warm, (0, 0), band.crop((x, 0, x + W, H)))
        return img.tobytes()

    tmp = out.with_name(out.stem + ".part.mp4")
    enc = subprocess.Popen([ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p",
                            str(tmp)], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:  # Pillow warps outside the GIL
            # Only a few frames ahead of the encoder (each is 6 MB): pool.map would render them all at once
            # and run a small computer out of memory.
            ahead: deque = deque()
            for f in range(frames):
                ahead.append(pool.submit(frame, f))
                if len(ahead) >= WORKERS * 2:
                    enc.stdin.write(ahead.popleft().result())
            while ahead:
                enc.stdin.write(ahead.popleft().result())
        enc.stdin.close()
    except BrokenPipeError:
        pass
    err = enc.stderr.read().decode(errors="replace")
    if enc.wait() != 0:
        tmp.unlink(missing_ok=True)
        raise DepthError(f"The 3D shot couldn't be encoded: {err.strip()[:200]}")
    tmp.replace(out)
    return out


def moves_for(n: int, seed: int) -> list[str]:
    """A camera move per shot, never the same twice in a row."""
    rng = random.Random(seed)
    out: list[str] = []
    for _ in range(n):
        out.append(rng.choice([m for m in MOVES if not out or m != out[-1]]))
    return out


def make_ad(kit: BrandKit, photo: str, plan: list, lines: list[str], voice: str, out: Path, poster: Path, caption: str,
            seed: int, end: tuple[str, str, str] = ("", "", ""), style: str = "", moves: list[str] | None = None,
            music_bed: bool = True, spoken: list[str] | None = None) -> float:
    """A whole AI scenes ad filmed on this computer: a 3D shot per line (up to four), then the same
    edit as AI video shots: voice or music, captions, logo, end card."""
    from . import ugc_video

    if style == "aesthetic":
        lengths = ugc_video.aesthetic_durations(lines)
    else:
        lengths = [min(4.5, max(2.2, len(line.split()) / 2.6 + 0.8)) for line in lines]
    clips: list[str] = []
    try:
        for i, (scene, move) in enumerate(zip(plan, moves or moves_for(len(plan), seed))):
            clip = out.with_name(f"{out.stem}_3d{i}.mp4")
            make_clip(photo, scene.crop, move, max(lengths[i::len(plan)]) + 0.7, clip, seed + i)
            clips.append(str(clip))
        return ugc_video.make_scene_ad(kit, clips, lines, voice, out, poster, caption, seed, end, style, music_bed, spoken)
    finally:
        for c in clips:
            Path(c).unlink(missing_ok=True)

