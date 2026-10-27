"""Agent 7: short motion videos (Reels, Shorts, TikTok) from a post and the brand's own photos.

Nemotron writes the on-screen script (a hook, a few words per photo, a call to action); one of
five visual styles animates it at 1080x1920. Styles differ in layout, motion, typography,
transitions and pacing (slow cinematic zooms, fast cuts with caption blocks, floating cards,
an editorial magazine page, a scrapbook of polaroids), and a campaign's reels rotate through
them so they never all look alike. Frames are drawn with Pillow on several threads and piped
straight into ffmpeg, so a 12-second reel renders in seconds with no video editor.
"""
from . import render  # noqa: F401 - tests and callers tune render.FPS
from .core import FPS, H, KINDS, M, MAX_PHOTOS, MAX_SCENES, MAX_WAITING, ReelBusy, ReelEditError, ReelError, Scene, W, WORKERS, _render_slots, _seed, _slots, _waiting, log  # noqa: F401
from .story import ENDINGS, KIND_TOPIC, LANGUAGE_NOTES, LEAD_IN, Plan, REEL_SYSTEM, Shot, TIPS, TOPICS, _pick, _plan_story, _price, _site, _words, available_topics, default_cta, default_topic, flavour, humanize_lines, humanize_scenes, localize, media_url, photo_choices, plan_scenes, plan_story, post_occasion, product_shots, reel_photos, resolve_photo, scenes_from_edit, story_facts, tidy_line, to_edit, trend_formats, write_script  # noqa: F401
from .draw import _lines, caption_blocks, dotted, drop_shadow, ease_out, faded, ken_burns, line_images, logo_chip, mix, paste_center, pill, rounded, scaled, soft_glow, spring, sticker, text_block  # noqa: F401
from .colours import AUTO_PALETTES, HEX, PACES, PALETTES, Palette, _brand, _complement, _custom, _hex, _midnight, _pastel, choose_palette, hue_shift, palette_colors, palette_kit, palette_list  # noqa: F401
from .styles import Base, Cinematic, Magazine, POLAROID_ANGLES, Punch, STYLES, Scrapbook, Showcase, Style, choose_style  # noqa: F401
from .render import WHITE, ffmpeg_exe, make_reel, render_reel, resolve_options, style_list, tag_chip, timeline  # noqa: F401
