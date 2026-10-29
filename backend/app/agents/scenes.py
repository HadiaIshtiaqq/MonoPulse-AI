"""AI scenes: real generated video of the product being worn, applied, held or eaten, like Flow or
Higgsfield ads, for free.

Each line of the script gets its own shot: the product photo is the first frame, and an open-source
image-to-video model (Wan 2.2, Apache-2.0) makes it move: the model turns in the outfit, a hand
smooths the cream on, steam rises off the burger. The model runs on Hugging Face's free ZeroGPU
hardware (this computer has no GPU for it); a free Hugging Face account (HF_TOKEN in
backend/.env) gets a bigger daily share. Only the product photo and the shot description are
sent, nothing else about the brand.

Faceless ads keep faces out of every shot: the photo is cropped below the shoulders and the shots
are about hands, fabric and texture, like most creator ads for skincare and clothes.

Aesthetic ads are the soft, slow kind ("aesthetic UGC"): close-ups in morning light, slow hands,
water and fabric moving, no faces, no voice, music and a few quiet words.
"""
from __future__ import annotations

import logging
import random
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from .. import config
from ..llm import LLMError, router
from ..schemas import BrandKit, Product
from .playbooks import playbook_key

log = logging.getLogger(__name__)

STYLES = {"worn": "Worn / used", "faceless": "Faceless (hands only)", "aesthetic": "Aesthetic (soft, music)"}
FACELESS = ("faceless", "aesthetic")
AESTHETIC_LOOK = ("soft natural morning light, slow motion, shallow depth of field, dreamy aesthetic, calm and elegant, "
                  "slow smooth camera movement, realistic, warm tones, sharp product details")
LOOK = ("handheld smartphone video, natural light, realistic, authentic UGC style, smooth motion, "
        "sharp product details, true colours")
NEGATIVE = ("text, subtitles, watermark, logo change, blurry, low quality, deformed hands, extra fingers, fused fingers, "
            "distorted face, morphing, flicker, cartoon, painting, static image, overexposed")
NO_FACE = "face, head, eyes, mouth, portrait"
SECONDS = 3.0  # per generated shot (GPU time is the free share); the edit slows or loops it to the voice

# Free Wan 2.2 image-to-video Spaces, tried in order (one busy or out of quota, the next is tried).
SPACES = ["zerogpu-aoti/wan2-2-fp8da-aoti-faster", "KingNish/wan2-2-fast"]


class SceneError(RuntimeError):
    pass


@dataclass
class Scene:
    prompt: str
    crop: str = "full"  # full | detail | lower (below the shoulders, for faceless)


# Shots per kind of product: (what happens, crop). "worn" shots may show the person in the photo;
# "faceless" shots never show a face.
SHOTS: dict[str, dict[str, list[tuple[str, str]]]] = {
    "fashion": {
        "worn": [("the person slowly turns to show the whole outfit, the fabric flows and sways naturally", "full"),
                 ("the person walks a few steps toward the camera wearing the outfit, relaxed and confident", "full"),
                 ("the camera moves slowly in on the fabric, embroidery and print details as the person adjusts the sleeve", "detail"),
                 ("the person poses and shifts their weight, the outfit drapes and moves, mirror selfie video", "full")],
        "faceless": [("a hand gently runs over the fabric, showing its texture and embroidery, close-up", "detail"),
                     ("the person turns slightly, the fabric sways, framed below the shoulders", "lower"),
                     ("slow push in on the stitching and print, a hand lifts the hem to show the fall of the fabric", "lower"),
                     ("hands smooth the outfit down and adjust the fit, close-up", "lower")]},
    "footwear": {
        "worn": [("the person walks on a city pavement wearing the shoes, camera low and following the steps", "lower"),
                 ("a foot slides into the shoe and taps the ground, close-up", "detail"),
                 ("the shoe flexes as the person steps forward, close-up at ground level", "detail")],
        "faceless": [("feet walk on a city pavement in the shoes, camera low and following the steps", "lower"),
                     ("a hand picks up the shoe and turns it to show the sole and stitching", "detail"),
                     ("the shoe flexes as the person steps forward, close-up at ground level", "detail")]},
    "jewellery": {
        "worn": [("the piece sparkles as soft light moves across it while it is worn, gentle movement", "full"),
                 ("a hand touches the jewellery, it catches the light, close-up", "detail"),
                 ("the person slowly turns, the jewellery glints, shallow depth of field", "full")],
        "faceless": [("a hand picks up the piece and it sparkles in the light, close-up", "detail"),
                     ("the jewellery catches the light as it is worn on the wrist, close-up, no face", "detail"),
                     ("slow orbit around the piece on a velvet surface as light moves across it", "full")]},
    "beauty": {
        "worn": [("a hand picks up the product and squeezes a little onto the fingertips, close-up, soft bathroom light", "full"),
                 ("fingers smooth the product onto skin, showing its creamy texture, close-up", "detail"),
                 ("the product is set down on a vanity as morning sunlight moves across it", "full")],
        "faceless": [("a hand picks up the product and squeezes a little onto the fingertips, close-up, soft bathroom light", "full"),
                     ("fingers rub the product onto the back of a hand, showing its smooth texture, close-up", "detail"),
                     ("the product rests on a bathroom shelf, water droplets, sunlight moves across it", "full")]},
    "food": {
        "worn": [("steam rises from the food, a hand reaches in and picks up a piece, close-up", "full"),
                 ("the food is lifted toward the camera, sauce drips, crispy texture, close-up", "detail"),
                 ("slow push in on the food on the table, warm restaurant light, steam rising", "full")],
        "faceless": [("steam rises from the food, a hand reaches in and picks up a piece, close-up", "full"),
                     ("the food is pulled apart by hand showing the inside, close-up", "detail"),
                     ("slow push in on the food on the table, warm restaurant light, steam rising", "full")]},
    "home": {
        "worn": [("a hand places the item on a table, sunlight through a window moves across it", "full"),
                 ("the camera glides slowly around the item in a cosy room", "full"),
                 ("a hand touches the surface to show the material, close-up", "detail")],
        "faceless": [("a hand places the item on a table, sunlight through a window moves across it", "full"),
                     ("the camera glides slowly around the item in a cosy room", "full"),
                     ("a hand touches the surface to show the material, close-up", "detail")]},
    "fitness": {
        "worn": [("the person uses the product during a workout, energetic movement, gym light", "full"),
                 ("close-up of hands gripping the product mid-workout", "detail"),
                 ("the product is picked up off the gym floor, camera follows", "full")],
        "faceless": [("hands grip and use the product during a workout, close-up", "detail"),
                     ("the product is picked up off the gym floor, camera follows, no face", "lower"),
                     ("slow push in on the product in a sunny gym", "full")]},
}
GENERIC = {
    "worn": [("a hand picks up the product and turns it to show it to the camera, close-up", "full"),
             ("the camera slowly orbits the product on a table, natural window light", "full"),
             ("hands open the box and lift the product out, close-up", "detail")],
    "faceless": [("a hand picks up the product and turns it to show it to the camera, close-up", "full"),
                 ("the camera slowly orbits the product on a table, natural window light", "full"),
                 ("hands open the box and lift the product out, close-up", "detail")]}


# Aesthetic shots: slow and soft, never a face.
AESTHETIC: dict[str, list[tuple[str, str]]] = {
    "fashion": [("the fabric sways gently in a soft breeze by a sunlit window, slow motion", "lower"),
                ("a hand slowly traces the embroidery, soft light moving across the fabric, close-up", "detail"),
                ("the outfit drapes and moves as the person slowly turns, framed below the shoulders, golden hour light", "lower"),
                ("sunlight and leaf shadows drift slowly over the fabric, close-up", "detail")],
    "footwear": [("the shoes rest on a sunlit floor as soft shadows drift across them, slow push in", "full"),
                 ("slow steps on a quiet morning street, camera low, soft light", "lower"),
                 ("a hand slowly sets the shoe down on a linen surface, close-up", "detail")],
    "jewellery": [("the piece glints as soft light slowly moves across it on silk fabric, close-up", "detail"),
                  ("a hand slowly lifts the piece and it sparkles in morning light", "detail"),
                  ("slow orbit around the piece resting among flowers, shallow depth of field", "full")],
    "beauty": [("the product rests on a marble vanity as morning sunlight and leaf shadows drift across it, slow push in", "full"),
               ("a slow drop of the product falls onto fingertips, soft light, close-up", "detail"),
               ("fingers slowly smooth the product onto the back of a hand, creamy texture, soft light, close-up", "detail"),
               ("water ripples slowly around the product beside fresh flowers, soft light", "full")],
    "food": [("steam rises slowly from the food in soft window light, slow push in", "full"),
             ("a hand slowly lifts a piece, warm light, shallow depth of field, close-up", "detail"),
             ("slow orbit around the food on a linen table, soft morning light", "full")],
    "home": [("soft morning light slowly moves across the item in a calm room", "full"),
             ("a hand slowly touches the surface, close-up, shallow depth of field", "detail"),
             ("slow camera glide past the item, sheer curtains moving in the breeze", "full")],
    "fitness": [("the product rests in soft morning light as the camera slowly pushes in", "full"),
                ("hands slowly pick up the product, calm light, close-up", "detail"),
                ("slow orbit around the product on a yoga mat in sunlight", "full")],
}
AESTHETIC_GENERIC = [("the product rests on a linen surface as morning sunlight and leaf shadows drift across it, slow push in", "full"),
                     ("a hand slowly picks up the product and turns it in soft light, close-up", "detail"),
                     ("slow orbit around the product beside fresh flowers, shallow depth of field", "full")]


def kind_of(kit: BrandKit, p: Product) -> str:
    return playbook_key(f"{p.category} {kit.industry}") or playbook_key(p.name)


def plan(kit: BrandKit, p: Product, n: int, style: str, seed: int) -> list[Scene]:
    """A shot for each line, in an order that changes from ad to ad and never repeats back to back."""
    style = style if style in STYLES else "worn"
    kind = kind_of(kit, p)
    shots = AESTHETIC.get(kind, AESTHETIC_GENERIC) if style == "aesthetic" else (SHOTS.get(kind) or GENERIC)[style]
    rng = random.Random(seed)
    order = shots[:1] + rng.sample(shots[1:], len(shots) - 1)  # the opener shows the whole product
    if rng.random() < 0.5 and len(order) > 2:
        order[1], order[2] = order[2], order[1]
    out = []
    for i in range(n):
        text, crop = order[i % len(order)]
        if i >= len(order):  # more lines than shots: the same moment, filmed from a new angle
            text += ", filmed from a different angle"
        out.append(Scene(text, crop))
    return out


DIRECTOR = """You are the director of a short vertical UGC video ad (Reels/TikTok). One shot per line of the on-screen
script. Every shot starts from the same product photo. For each line choose:
- "crop": "full" (the whole product), "detail" (a close-up of the middle) or "lower" (below the shoulders, no face);
- "move": the 3D camera move, one of {moves}; never the same move twice in a row;
- "shot": one sentence describing what happens in the shot for an image-to-video model (camera, light, motion of the
  product or hands). Describe only what the photo can show; no text, no new products, no claims.
Style: {style}. {style_rule}
Return JSON: {{"shots": [{{"crop": "...", "move": "...", "shot": "..."}}, ...]}} with exactly {n} shots."""
STYLE_RULES = {
    "worn": "The product is worn or used by the person in the photo; show the fit and how it moves.",
    "faceless": "Never show a face: use \"detail\" or \"lower\" crops only; hands, fabric and texture.",
    "aesthetic": "Soft and slow: morning light, slow motion, calm close-ups, never a face; \"detail\" or \"lower\" crops only.",
}


async def direct(kit: BrandKit, p: Product, lines: list[str], style: str, moves: list[str]) -> tuple[list[Scene], list[str]] | None:
    """Nemotron 3 Ultra directs the ad: a crop, a camera move and a shot description for each line.
    None without a model (or if its answer doesn't fit), and the planned shots are used instead."""
    if not router.enabled or not lines:
        return None
    n = len(lines)
    style = style if style in STYLES else "worn"
    system = DIRECTOR.format(moves=", ".join(moves), style=STYLES[style], style_rule=STYLE_RULES[style], n=n)
    facts = {"brand": kit.name, "industry": kit.industry, "product": p.name, "category": p.category, "price": p.price}
    try:
        data = await router.complete_json("ugc_director", system, f"Facts: {facts}\nScript lines:\n" + "\n".join(lines),
                                          temperature=0.7, max_tokens=700)
        shots = data.get("shots") if isinstance(data, dict) else None
    except (LLMError, AttributeError, ValueError) as exc:
        log.info("the director fell back to the planned shots: %s", exc)
        return None
    if not isinstance(shots, list) or len(shots) < n:
        return None
    plan, chosen = [], []
    allowed = ("detail", "lower") if style in FACELESS else ("full", "detail", "lower")
    for s in shots[:n]:
        if not isinstance(s, dict):
            return None
        crop = s.get("crop") if s.get("crop") in allowed else allowed[0]
        move = s.get("move") if s.get("move") in moves else moves[0]
        if chosen and move == chosen[-1]:  # the rule it was given, kept even if the answer broke it
            move = next(m for m in moves if m != move)
        text = re.sub(r"\s+", " ", str(s.get("shot") or "")).strip()[:240] or "slow push in on the product"
        plan.append(Scene(text, crop))
        chosen.append(move)
    return plan, chosen


def prompt_for(scene: Scene, style: str) -> str:
    extra = ", no face visible, framed below the shoulders" if style in FACELESS else ""
    return f"{scene.prompt}{extra}, {AESTHETIC_LOOK if style == 'aesthetic' else LOOK}"


def start_frame(photo: str, crop: str, out: Path) -> Path:
    """The shot's first frame: the product photo, upright 9:16, cropped for the shot."""
    img = ImageOps.exif_transpose(Image.open(photo)).convert("RGB")
    w, h = img.size
    if crop == "lower" and h > w:  # below the shoulders: drop the top of a portrait photo
        img = img.crop((0, int(h * 0.3), w, h))
    elif crop == "detail":  # a closer look at the middle of the product
        img = img.crop((int(w * 0.15), int(h * 0.2), int(w * 0.85), int(h * 0.85)))
    ImageOps.fit(img, (576, 1024), Image.LANCZOS, centering=(0.5, 0.45)).save(out, quality=93)
    return out


def smooth(clip: Path) -> None:
    """The model films at 16 frames a second, which looks jerky next to phone video: the frames in
    between are made from the motion (ffmpeg's motion interpolation), giving 30 smooth frames a
    second. If that fails, the clip stays as it was."""
    from .reels.render import ffmpeg_exe

    tmp = clip.with_suffix(".smooth.mp4")
    try:
        subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(clip),
                        "-vf", "minterpolate=fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-an", str(tmp)],
                       check=True, capture_output=True, timeout=180)
        tmp.replace(clip)
    except (OSError, subprocess.SubprocessError) as exc:
        log.info("couldn't smooth %s: %s", clip.name, exc)
        tmp.unlink(missing_ok=True)


def _tidy_error(exc: Exception) -> str:
    text = re.sub(r"<[^>]+>", "", str(exc)).strip()
    return text[:240] or type(exc).__name__


def generate(photo: str, scene: Scene, style: str, seed: int, out: Path) -> Path:
    """One generated shot (about 3 s) saved at `out`. Blocks for about a minute."""
    try:
        from gradio_client import Client, handle_file
    except ImportError as exc:
        raise SceneError("AI scenes need one more package: pip install gradio_client") from exc
    frame = start_frame(photo, scene.crop, out.with_suffix(".start.jpg"))
    prompt = prompt_for(scene, style)
    negative = NEGATIVE + (", " + NO_FACE if style in FACELESS else "") + (", fast motion, shaky" if style == "aesthetic" else "")
    errors = []
    try:
        for space in SPACES:
            try:
                client = Client(space, token=config.HF_TOKEN or None, verbose=False, analytics_enabled=False)
                kw = dict(input_image=handle_file(str(frame)), prompt=prompt, negative_prompt=negative,
                          duration_seconds=SECONDS, seed=seed, randomize_seed=False, api_name="/generate_video")
                if space.startswith("KingNish/"):
                    kw.update(height=1024, width=576, steps=4)
                else:
                    kw.update(steps=6)
                result = client.predict(**kw)
                video = result[0]["video"] if isinstance(result[0], dict) else result[0]
                shutil.copyfile(video, out)
                smooth(out)
                return out
            except Exception as exc:  # noqa: BLE001 - a busy or changed Space: try the next one
                log.info("scene on %s failed: %s", space, _tidy_error(exc))
                errors.append(_tidy_error(exc))
    finally:
        frame.unlink(missing_ok=True)
    quota = any(re.search(r"(?i)quota|gpu was available|zerogpu|exceeded", e) for e in errors)
    if quota:
        raise SceneError("Hugging Face's free video GPUs are busy or today's free share is used up. "
                         + ("Try again in a while." if config.HF_TOKEN else
                            "Add a free Hugging Face token (HF_TOKEN in backend/.env) for a bigger share, or film with the 3D camera."))
    raise SceneError(f"The AI video model couldn't film this shot right now: {errors[-1] if errors else 'no response'}")
