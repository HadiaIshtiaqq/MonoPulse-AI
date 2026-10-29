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
# Pages where a platform asks a person to prove who they are (a captcha, a code, a security check).
# MonoPlus never answers these: it stops and hands the window to you.
CHALLENGE = re.compile(r"/(auth_platform|challenge|checkpoint|recaptcha|captcha|two_factor|two_step_verification|"
                       r"account/access|suspended)", re.I)


class BrowserPostError(RuntimeError):
    pass


class VerificationNeeded(BrowserPostError):
    """The platform showed a human check. Only the person can answer it."""


def explain(exc: Exception) -> str:
    """A browser failure in words a person can act on. The full log goes to the server log, never the page."""
    log.warning("browser failed: %s", exc)
    text = str(exc)
    if re.search(r"has been closed|already in use|ProcessSingleton|SingletonLock|lock file", text, re.I):
        return ("MonoPlus's browser is already open in another window (perhaps one left from before), and only one "
                "can use your sign-ins at a time. Close every MonoPlus browser window, then try again.")
    if re.search(r"Executable doesn't exist|playwright install", text, re.I):
        return "The browser isn't installed yet. On this computer run: python -m playwright install chromium"
    if re.search(r"DISPLAY|headed|no display|XServer", text, re.I):
        return "This computer can't show a browser window (it looks like a server without a screen)."
    if re.search(r"Timeout", text):
        return "The browser took too long to respond. Try again in a moment."
    return f"The browser couldn't do that ({type(exc).__name__}). Close MonoPlus's browser windows and try again."


def installed_browser() -> str:
    """Path to an installed Chrome (or Edge) for the plain sign-in window, or "" when there's none."""
    import os
    import shutil

    if (config.BROWSER_CHANNEL or "").lower() in ("chromium", "playwright"):
        return ""
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome") or "", shutil.which("google-chrome-stable") or "", shutil.which("chrome") or "",
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", shutil.which("microsoft-edge") or "",
    ]
    return next((c for c in candidates if c and "%" not in c and os.path.isfile(c)), "")


def channels() -> list[str]:
    """Browsers to try for the window, in order. MONOPLUS_BROWSER=chromium forces Playwright's own."""
    choice = (config.BROWSER_CHANNEL or "auto").lower()
    if choice in ("chrome", "msedge"):
        return [choice, ""]
    if choice in ("chromium", "playwright"):
        return [""]
    return ["chrome", "msedge", ""]


def available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


class BrowserPoster:
    """One browser, driven from one worker thread (Playwright objects belong to their thread)."""

    def __init__(self, profile: Path | None = None, headless: bool = False) -> None:
        self.profile = profile or config.BROWSER_PROFILE_DIR
        self.headless = headless  # tests run without a window; people see what MonoPlus does
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="browser")
        self._pw = None
        self._ctx = None
        self.signed_in: dict[str, bool] = {}  # last known, so the scheduler never has to open a window to ask
        self.needs_check: dict[str, bool] = {}  # platforms showing you a security check in the window right now
        self.channel = ""  # which browser the window is: "chrome", "msedge" or "" (Playwright's own Chromium)
        self._signin = None  # the plain browser window you sign in with, while it's open (a subprocess.Popen)
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
        if self.signing_in():
            raise RuntimeError("The sign-in window is still open (the profile is already in use). Close it first.")
        if self._pw is None:
            self._pw = sync_playwright().start()
        self.profile.mkdir(parents=True, exist_ok=True)
        # Your installed Chrome (or Edge) first: a full browser, so the platforms' own sign-in and
        # security-check pages load as they do in your everyday browser (Playwright's test build
        # lacks parts of them, and Meta's check pages came up blank in it). The window says plainly
        # that it's automated: MonoPlus never hides that from a site.
        last: Exception | None = None
        for channel in channels():
            try:
                # chromium_sandbox: keep Chrome's own security sandbox on (Playwright turns it off by default).
                self._ctx = self._pw.chromium.launch_persistent_context(
                    str(self.profile), channel=channel or None, headless=headless, viewport=None, args=["--start-maximized"],
                    chromium_sandbox=True)
                self.channel = channel
                break
            except Exception as exc:  # noqa: BLE001 - not installed: try the next
                last = exc
        else:
            raise last or RuntimeError("no browser could start")
        self._ctx.on("close", lambda *_: setattr(self, "_ctx", None))
        return self._ctx

    def _page(self):
        ctx = self._context()
        page = ctx.new_page()
        page.set_default_timeout(STEP_MS)
        page.bring_to_front()
        return page

    def signing_in(self) -> bool:
        return self._signin is not None and self._signin.poll() is None

    def _status(self) -> dict[str, bool]:
        if self.signing_in():  # the profile is busy with your sign-in window: report what we last knew
            self.needs_check = {}
            return self.signed_in
        ctx = self._ctx
        temporary = ctx is None
        if temporary:  # nothing open: read the saved profile without showing a window
            ctx = self._context(headless=True)
        try:
            cookies = ctx.cookies()
            found = {p.value: any(c["name"] == name and domain in c["domain"] and c["value"] for c in cookies)
                     for p, (domain, name) in SESSION.items()}
            # A tab sitting on a platform's security check: signing in isn't finished until you answer it.
            self.needs_check = {p.value: any(domain in pg.url and CHALLENGE.search(pg.url) for pg in ctx.pages)
                                for p, (domain, _) in SESSION.items()} if not temporary else {}
        finally:
            if temporary:
                ctx.close()
                self._ctx = None
        self.signed_in = found
        return found

    def _login(self, platform: Platform) -> str:
        """Open the platform's sign-in page in a plain browser window on MonoPlus's profile.

        Signing in is yours to do, so it happens in a window nothing controls: platforms keep
        their human checks (Instagram's reCAPTCHA) away from remote-controlled browsers, and
        MonoPlus doesn't try to change that. You sign in, answer any check, close the window, and
        MonoPlus uses the saved sign-in to post. Returns "plain" or "controlled" (no Chrome/Edge found)."""
        exe = installed_browser()
        if exe:
            if self.signing_in():
                self._signin.terminate()  # one sign-in window at a time; this one shows the platform you asked for
                self._signin.wait(timeout=10)
            if self._ctx is not None:  # free the profile: two browsers can't share it
                try:
                    self._ctx.close()
                except Exception:  # noqa: BLE001
                    pass
                self._ctx = None
            import subprocess

            self.profile.mkdir(parents=True, exist_ok=True)
            self._signin = subprocess.Popen([exe, f"--user-data-dir={self.profile}", "--no-first-run", "--no-default-browser-check",
                                             "--new-window", LOGIN[platform]])
            return "plain"
        return self._login_controlled(platform)

    def _login_controlled(self, platform: Platform) -> str:
        """Without Chrome or Edge installed: the sign-in page in MonoPlus's own window, in its existing tab."""
        ctx = self._context()
        domain = SESSION[platform][0]
        page = next((pg for pg in ctx.pages if domain in pg.url), None)
        if page is None:
            page = ctx.pages[0] if len(ctx.pages) == 1 and ctx.pages[0].url in ("about:blank", "") else ctx.new_page()
            page.set_default_timeout(STEP_MS)
        page.bring_to_front()
        if not CHALLENGE.search(page.url):  # never navigate away from a check you're in the middle of
            page.goto(LOGIN[platform])
        return "controlled"

    # ------------------------------------------------------------------ posting

    def _post(self, platform: Platform, caption: str, files: list[Path], submit: bool) -> str:
        try:
            page = self._page()
        except Exception as exc:  # noqa: BLE001 - the browser wouldn't start
            raise BrowserPostError(explain(exc)) from exc
        flow = {Platform.LINKEDIN: _linkedin, Platform.X: _x, Platform.FACEBOOK: _facebook, Platform.INSTAGRAM: _instagram}[platform]
        try:
            flow(page, caption, [str(f) for f in files], submit)
            _check_for_challenge(page, platform.value.title())
        except VerificationNeeded:
            self.signed_in[platform.value] = False  # scheduled posts wait until you've answered it
            raise
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

    def _sign_out(self) -> None:
        """Close the browser and delete its profile: every sign-in it held is gone."""
        import shutil

        if self._ctx is not None:
            try:
                self._ctx.close()
            except Exception:  # noqa: BLE001
                pass
            self._ctx = None
        shutil.rmtree(self.profile, ignore_errors=True)
        self.signed_in = {}

    # ------------------------------------------------------------------ async-friendly entry points

    async def sign_out(self) -> None:
        await self.run(self._sign_out)

    async def read_instagram(self, username: str) -> dict:
        return await self.run(self._read_instagram, username)

    async def run(self, fn, *args):
        import asyncio

        return await asyncio.get_running_loop().run_in_executor(self.pool, fn, *args)

    async def status(self) -> dict[str, bool]:
        return await self.run(self._status)

    async def login(self, platform: Platform) -> str:
        return await self.run(self._login, platform)

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


def _check_for_challenge(page, platform: str) -> None:
    if CHALLENGE.search(page.url):
        raise VerificationNeeded(
            f"{platform} wants to check it's really you (a captcha or security check) in MonoPlus's browser window. "
            "Answer it there yourself; if the box looks blank, reload that page. Then come back and try again. "
            "Nothing was posted. If it keeps asking, post this one by hand for now: platforms check more often "
            "when posts come from an automated browser.")


def _need(what: str, *locators):
    page = locators[0].page
    for _ in range(40):  # up to ~20 s for slow pages
        _check_for_challenge(page, "The platform")
        found = _first_visible(*locators)
        if found is not None:
            return found
        page.wait_for_timeout(500)
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
    _check_for_challenge(page, platform)
    if re.search(r"/(login|signin|authwall|checkpoint|accounts/login|i/flow/login)", page.url):
        raise BrowserPostError(f"You're not signed in to {platform} in MonoPlus's browser yet. Sign in there first.")


def _attach_with_chooser(page, button, files: list[str]) -> None:
    with page.expect_file_chooser(timeout=STEP_MS) as chooser:
        button.click()
    chooser.value.set_files(files)


def _dismiss_prompts(page) -> None:
    """Close the platform's own friendly pop-ups ("Remember password?", "Turn on notifications?")
    that sit over the composer, by choosing the polite no. Never a security check: those stop posting."""
    for _ in range(3):
        later = _first_visible(page.get_by_role("button", name=re.compile(r"^(not now|maybe later|skip|no thanks)$", re.I)))
        if later is None:
            return
        later.click()
        page.wait_for_timeout(500)


def _linkedin(page, caption: str, files: list[str], submit: bool) -> None:
    page.goto(HOME[Platform.LINKEDIN])
    _signed_in_or_raise(page, "LinkedIn")
    _dismiss_prompts(page)
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
    _dismiss_prompts(page)
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
    _dismiss_prompts(page)
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


def move_old_profile() -> None:
    """Sign-ins used to be kept in the project's data folder; move them to where they live now."""
    old, new = config.DATA_DIR / "browser-profile", config.BROWSER_PROFILE_DIR
    if old.is_dir() and not new.exists() and old.resolve() != new.resolve():
        import shutil

        try:
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(new))
            log.info("moved the browser profile to %s", new)
        except OSError as exc:  # a browser still holding it open
            log.warning("couldn't move the browser profile out of the project yet (%s); using it where it is", exc)
            poster.profile = old  # your sign-ins stay usable; it moves on a later start


poster = BrowserPoster()
