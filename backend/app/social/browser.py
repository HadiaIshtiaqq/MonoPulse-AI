"""Posting the way a person, or Claude, does it: in a real browser where you're signed in.

No developer apps or API approvals: MonoPlus opens its own browser window with a saved profile
on this computer, you sign in to LinkedIn, Facebook, Instagram and X there once (MonoPlus never
sees your password), and from then on it can open each platform's composer, attach the post's
images or reel, type the caption, and either leave it for you to check and press Post ("review")
or press Post itself.

This only works where the window can show: the computer you run MonoPlus on. Platforms change
their pages, so every step looks for the button several ways and says plainly which step failed;
and their terms discourage automation, so keep the volume sensible and prefer review.
"""
from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import config
from ..schemas import Platform

log = logging.getLogger(__name__)

HOME = {
    Platform.LINKEDIN: "https://www.linkedin.com/feed/",
    Platform.FACEBOOK: "https://www.facebook.com/",
    Platform.INSTAGRAM: "https://www.instagram.com/",
    Platform.X: "https://x.com/home",
}
LOGIN = {
    Platform.LINKEDIN: "https://www.linkedin.com/login",
    Platform.FACEBOOK: "https://www.facebook.com/login",
    Platform.INSTAGRAM: "https://www.instagram.com/accounts/login/",
    Platform.X: "https://x.com/i/flow/login",
}
# A platform's session cookie means you're signed in there.
SESSION = {
    Platform.LINKEDIN: ("linkedin.com", "li_at"),
    Platform.FACEBOOK: ("facebook.com", "c_user"),
    Platform.INSTAGRAM: ("instagram.com", "sessionid"),
    Platform.X: ("x.com", "auth_token"),
}
STEP_MS = 20_000


class BrowserPostError(RuntimeError):
    pass


def available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


class BrowserPoster:
    """One browser, driven from one worker thread (Playwright objects belong to their thread)."""

    def __init__(self, profile: Path | None = None, headless: bool = False) -> None:
        self.profile = profile or (config.DATA_DIR / "browser-profile")
        self.headless = headless  # tests run without a window; people see what MonoPlus does
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="browser")
        self._pw = None
        self._ctx = None
        self.signed_in: dict[str, bool] = {}  # last known, so the scheduler never has to open a window to ask
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ the window

    def _context(self, headless: bool | None = None):
        headless = self.headless if headless is None else headless
        from playwright.sync_api import sync_playwright

        if self._ctx is not None:
            try:
                self._ctx.pages  # noqa: B018 - raises once the window was closed
                return self._ctx
            except Exception:  # noqa: BLE001
                self._ctx = None
        if self._pw is None:
            self._pw = sync_playwright().start()
        self.profile.mkdir(parents=True, exist_ok=True)
        self._ctx = self._pw.chromium.launch_persistent_context(
            str(self.profile), headless=headless, viewport=None, args=["--start-maximized"],
            ignore_default_args=["--enable-automation"])
        self._ctx.on("close", lambda *_: setattr(self, "_ctx", None))
        return self._ctx

    def _page(self):
        ctx = self._context()
        page = ctx.new_page()
        page.set_default_timeout(STEP_MS)
        page.bring_to_front()
        return page

    def _status(self) -> dict[str, bool]:
        ctx = self._ctx
        temporary = ctx is None
        if temporary:  # nothing open: read the saved profile without showing a window
            ctx = self._context(headless=True)
        try:
            cookies = ctx.cookies()
            found = {p.value: any(c["name"] == name and domain in c["domain"] and c["value"] for c in cookies)
                     for p, (domain, name) in SESSION.items()}
        finally:
            if temporary:
                ctx.close()
                self._ctx = None
        self.signed_in = found
        return found

    def _login(self, platform: Platform) -> None:
        page = self._page()
        page.goto(LOGIN[platform])

    # ------------------------------------------------------------------ posting

    def _post(self, platform: Platform, caption: str, files: list[Path], submit: bool) -> str:
        page = self._page()
        flow = {Platform.LINKEDIN: _linkedin, Platform.X: _x, Platform.FACEBOOK: _facebook, Platform.INSTAGRAM: _instagram}[platform]
        try:
            flow(page, caption, [str(f) for f in files], submit)
        except BrowserPostError:
            raise
        except Exception as exc:  # noqa: BLE001 - a timeout or a page that changed
            raise BrowserPostError(f"{platform.value.title()}'s page didn't behave as expected ({type(exc).__name__}). "
                                   "The window is still open, so you can finish the post there.") from exc
        if submit:
            page.wait_for_timeout(4000)  # let the platform finish uploading before the tab can close
            page.close()
            return f"Posted on {platform.value.title()} from your browser."
        return f"{platform.value.title()} is open with the post filled in. Check it and press Post in that window."

    def _read_instagram(self, username: str) -> dict:
        """Open a profile the way you would (no window needed) and read what's on it."""
        from ..scraper.instagram import READ_PROFILE_JS

        temporary = self._ctx is None
        ctx = self._context(headless=True) if temporary else self._ctx  # no window pops up just to read
        page = ctx.new_page()
        page.set_default_timeout(STEP_MS)
        try:
            page.goto(f"https://www.instagram.com/{username}/")
            page.wait_for_selector("header", timeout=STEP_MS)
            page.wait_for_timeout(1500)  # post thumbnails load after the header
            return page.evaluate(READ_PROFILE_JS)
        finally:
            page.close()
            if temporary:
                ctx.close()
                self._ctx = None

    # ------------------------------------------------------------------ async-friendly entry points

    async def read_instagram(self, username: str) -> dict:
        return await self.run(self._read_instagram, username)

    async def run(self, fn, *args):
        import asyncio

        return await asyncio.get_running_loop().run_in_executor(self.pool, fn, *args)

    async def status(self) -> dict[str, bool]:
        return await self.run(self._status)

    async def login(self, platform: Platform) -> None:
        await self.run(self._login, platform)

    async def post(self, platform: Platform, caption: str, files: list[Path], submit: bool) -> str:
        return await self.run(self._post, platform, caption, files, submit)


# --------------------------------------------------------------------------- page helpers


def _first_visible(*locators):
    """The first of several ways to find a control that's actually on the page."""
    for loc in locators:
        try:
            if loc.count() and loc.first.is_visible():
                return loc.first
        except Exception:  # noqa: BLE001
            continue
    return None


def _need(what: str, *locators):
    for _ in range(40):  # up to ~20 s for slow pages
        found = _first_visible(*locators)
        if found is not None:
            return found
        locators[0].page.wait_for_timeout(500)
    raise BrowserPostError(f"Couldn't find {what}. The platform may have changed its page, or you may need to sign in "
                           "again; the window is still open.")


def _type(page, box, caption: str) -> None:
    """Type into a rich editor line by line (Enter between lines), so line breaks survive."""
    box.click()
    for i, line in enumerate(caption.split("\n")):
        if line:
            page.keyboard.insert_text(line)
        if i < len(caption.split("\n")) - 1:
            page.keyboard.press("Enter")


def _signed_in_or_raise(page, platform: str) -> None:
    if re.search(r"/(login|signin|authwall|checkpoint|accounts/login|i/flow/login)", page.url):
        raise BrowserPostError(f"You're not signed in to {platform} in MonoPlus's browser yet. Sign in there first.")


def _attach_with_chooser(page, button, files: list[str]) -> None:
    with page.expect_file_chooser(timeout=STEP_MS) as chooser:
        button.click()
    chooser.value.set_files(files)


def _linkedin(page, caption: str, files: list[str], submit: bool) -> None:
    page.goto(HOME[Platform.LINKEDIN])
    _signed_in_or_raise(page, "LinkedIn")
    _need("LinkedIn's \"Start a post\" button",
          page.get_by_role("button", name=re.compile(r"start a post", re.I)),
          page.locator("button:has-text('Start a post')")).click()
    if files:
        add = _need("the button to add media", page.get_by_role("button", name=re.compile(r"add (a )?(media|photo|video)", re.I)),
                    page.locator("button[aria-label*='media' i], button[aria-label*='photo' i]"))
        _attach_with_chooser(page, add, files)
        nxt = _first_visible(page.get_by_role("button", name=re.compile(r"^(next|done)$", re.I)))
        if nxt is not None:
            nxt.click()
    box = _need("the post text box", page.locator("div[role='textbox'][contenteditable='true']"),
                page.locator(".ql-editor[contenteditable='true']"))
    _type(page, box, caption)
    if submit:
        _need("LinkedIn's Post button", page.get_by_role("button", name=re.compile(r"^post$", re.I))).click()


def _x(page, caption: str, files: list[str], submit: bool) -> None:
    page.goto("https://x.com/compose/post")
    _signed_in_or_raise(page, "X")
    if files:
        page.locator("input[data-testid='fileInput'], input[type='file']").first.set_input_files(files[:4])
    box = _need("the post text box", page.locator("[data-testid='tweetTextarea_0']"),
                page.locator("div[role='textbox'][contenteditable='true']"))
    _type(page, box, caption)
    if submit:
        _need("X's Post button", page.locator("[data-testid='tweetButton']"),
              page.get_by_role("button", name=re.compile(r"^post$", re.I))).click()


def _facebook(page, caption: str, files: list[str], submit: bool) -> None:
    page.goto(HOME[Platform.FACEBOOK])
    _signed_in_or_raise(page, "Facebook")
    _need("Facebook's \"What's on your mind\" box",
          page.get_by_role("button", name=re.compile(r"what's on your mind", re.I)),
          page.locator("span:has-text(\"What's on your mind\")")).click()
    dialog = page.get_by_role("dialog").last
    if files:
        file_input = dialog.locator("input[type='file']")
        if not file_input.count():
            _need("the photo/video button", dialog.get_by_role("button", name=re.compile(r"photo|video", re.I))).click()
        dialog.locator("input[type='file']").first.set_input_files(files)
    box = _need("the post text box", dialog.locator("div[role='textbox'][contenteditable='true']"))
    _type(page, box, caption)
    if submit:
        _need("Facebook's Post button", dialog.get_by_role("button", name=re.compile(r"^post$", re.I))).click()


def _instagram(page, caption: str, files: list[str], submit: bool) -> None:
    if not files:
        raise BrowserPostError("Instagram posts need an image or a reel.")
    page.goto(HOME[Platform.INSTAGRAM])
    _signed_in_or_raise(page, "Instagram")
    _need("Instagram's New post button", page.locator("svg[aria-label='New post']"),
          page.get_by_role("link", name=re.compile(r"^(new post|create)$", re.I))).click()
    menu_post = _first_visible(page.get_by_role("link", name=re.compile(r"^post$", re.I)),
                               page.locator("span:has-text('Post')"))
    if menu_post is not None:
        menu_post.click()
    pick = _need("\"Select from computer\"", page.get_by_role("button", name=re.compile(r"select from (computer|device)", re.I)))
    _attach_with_chooser(page, pick, files)
    for _ in range(2):  # crop, then filters
        _need("Instagram's Next button", page.get_by_role("button", name=re.compile(r"^next$", re.I)),
              page.locator("div[role='button']:has-text('Next')")).click()
        page.wait_for_timeout(800)
    box = _need("the caption box", page.locator("div[aria-label^='Write a caption']"),
                page.locator("div[role='textbox'][contenteditable='true']"))
    _type(page, box, caption)
    if submit:
        _need("Instagram's Share button", page.get_by_role("button", name=re.compile(r"^share$", re.I)),
              page.locator("div[role='button']:has-text('Share')")).click()
        page.wait_for_timeout(6000)


poster = BrowserPoster()
