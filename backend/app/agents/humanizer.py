"""Agent 4: Anti-AI humanizer.

Built on two open-source projects (MIT, see third_party/NOTICE.md):
  * blader/humanizer: the pattern catalogue (based on Wikipedia's "Signs of AI writing")
    drives both the detector below and the Nemotron rewrite prompt.
  * lynote-ai/humanize-text: the "deep" mode reuses its translation-chain idea (a
    high-temperature LLM rewrite through distant languages, then back), run on Nemotron.

Modes
  light     deterministic rule pass only (instant, no model)
  standard  rule pass + a pattern-guided Nemotron 3 Ultra rewrite if tells remain
  deep      lynote-style chain EN -> ZH -> JA -> EN on Nemotron, then the standard pass

A fact guard rejects any step that drops a number, price, URL, @handle, #hashtag or brand
name, so humanizing can never change the offer.

The "AI-tell score" (0-100, lower reads more human) is our own transparent heuristic over
the same pattern catalogue. It is not a commercial AI-detector score.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

from ..llm import LLMError, router

# --------------------------------------------------------------------------- pattern catalogue
# (id, label, weight, regex). Weights follow blader/humanizer's ordering: staging patterns are
# strong on one sighting; "weak alone" patterns count for little by themselves.

_W = r"[^.!?\n]"
PATTERNS: list[tuple[str, str, float, str]] = [
    ("not_x_but_y", "“Not X, but Y” contrast", 12,
     rf"\b(?:it'?s|this is|that'?s|we'?re|they'?re) not (?:just |only |merely )?{_W}{{1,60}}?[,;:]\s*(?:it'?s|but|this is)\b"
     rf"|\bnot (?:just|only|merely) {_W}{{1,60}}?\bbut(?: also)?\b"),
    ("closer", "One-line dramatic closer", 10,
     r"(?:^|\n)\s*(?:that'?s the (?:real )?(?:win|point|magic|difference)|that distinction matters|read that again|let that sink in|the message was clear)[.!]?"),
    ("deep_saying", "Saying that sounds deep", 10,
     r"\b(?:the real question is|at its core|what really matters|the heart of the matter|fundamentally|the deeper issue)\b"),
    ("runup", "Staged run-up", 10,
     r"\b(?:let'?s dive in|let'?s explore|let'?s break (?:it|this) down|here'?s what you need to know|without further ado|here'?s the thing|the thing is|real talk|let'?s be honest)\b"),
    ("arguing", "Arguing with no one", 8,
     r"\b(?:don'?t get me wrong|to be clear|i'?m not saying|this is not to say|you might think)\b"),
    ("chatbot", "Chatbot residue", 15,
     r"\b(?:i hope this helps|great question|certainly!|of course!|let me know if|feel free to reach out|happy to help)\b"),
    ("ai_words", "Overused AI words", 6,
     r"\b(?:delve|delving|tapestry|testament|pivotal|crucial|meticulous(?:ly)?|intricate|interplay|bolster(?:ed)?|garner(?:ed)?|showcas(?:e|es|ing)|underscor(?:e|es|ing)|vibrant|enduring|landscape|realm|elevate[sd]?|unlock(?:s|ing)?|unleash(?:es|ing)?|seamless(?:ly)?|leverag(?:e|es|ing)|utiliz(?:e|es|ing)|synergy|paradigm|game[- ]changer|cutting[- ]edge|revolutioniz(?:e|es|ing)|transformative|journey|holistic|empower(?:s|ing)?|navigate the complexities)\b"),
    ("inflation", "Inflated significance", 10,
     r"\b(?:stands as a testament|a pivotal moment|plays a (?:key|crucial|vital) role|setting the stage for|evolving landscape|indelible mark|the future looks bright|exciting times ahead|in today'?s (?:fast-paced|ever-changing|ever-evolving|digital|modern))\b"),
    ("sales", "Sales-brochure language", 6,
     r"\b(?:nestled|in the heart of|breathtaking|must-visit|stunning|renowned|diverse array|rich (?:history|heritage|tradition)|commitment to excellence|look no further|world-class|second to none)\b"),
    ("copula", "Avoiding is / has", 5,
     r"\b(?:serves as|stands as|functions as|boasts|showcases)\b"),
    ("riders", "Shallow -ing rider", 5,
     r",\s*(?:highlighting|underscoring|emphasizing|ensuring|reflecting|symbolizing|fostering|cultivating|showcasing)\b"),
    ("hedging", "Stacked qualifiers", 4,
     r"\b(?:could potentially|might arguably|it'?s (?:also )?possible that|to be fair)\b"),
    ("transitions", "Essay transitions", 6,
     r"\b(?:furthermore|moreover|additionally|in conclusion|it'?s important to note|it is worth noting)\b"),
]
_PATTERN_RE = [(pid, label, w, re.compile(rx, re.IGNORECASE | re.MULTILINE)) for pid, label, w, rx in PATTERNS]

# --------------------------------------------------------------------------- rule pass
# Replacements merge blader/humanizer guidance with lynote-ai's AI-vocabulary table (minus its
# suggestions that are themselves tells, like "game-changing" or em-dash merging).
REPLACEMENTS: list[tuple[str, str]] = [
    (r"in today'?s (?:fast-paced|ever-changing|ever-evolving|digital|modern)[\w\s-]*?(?:world|landscape|age|era),?\s*", ""),
    (r"in the (?:ever-evolving|fast-paced|dynamic) (?:world|landscape|realm) of [\w\s]+?,\s*", ""),
    (r"\b(?:let'?s dive in|without further ado|here'?s what you need to know)[.:!]?\s*", ""),
    (r"\b(?:i hope this helps|feel free to reach out(?: with any questions)?|great question)[.!]?\s*", ""),
    (r",\s*look no further(?=[.!])", ""),
    (r"look no further[.!]?\s*", ""),
    (r"whether you'?re an? [\w\s-]+? or an? [\w\s-]+?,\s*", ""),
    (r"\bembark on (?:a|your) journey\b", "get started"),
    (r"\bembark on\b", "start"),
    (r"\bdelve(?:s)? into\b", "dig into"),
    (r"\bdive into\b", "get into"),
    (r"\bunlock(?:ing)? the (?:power|potential) of\b", "get more from"),
    (r"\bharness(?:ing)? the power of\b", "use"),
    (r"\bunleash(?:es|ing)?\b", "bring out"),
    (r"\bunlock(?:s)?\b", "get"),
    (r"\belevate(?:s)?\b", "upgrade"),
    (r"\bleverag(?:e|es|ing)\b", "use"),
    (r"\butiliz(?:e|es|ing)\b", "use"),
    (r"\bfacilitat(?:e|es|ing)\b", "help"),
    (r"\bsubsequently\b", "then"),
    (r"\bdemonstrat(?:e|es)\b", "show"),
    (r"\boptimiz(?:e|es)\b", "improve"),
    (r"\bstreamlin(?:e|es)\b", "simplify"),
    (r"\bmethodology\b", "method"),
    (r"\bencompass(?:es)?\b", "includes"),
    (r"\bmultifaceted\b", "varied"),
    (r"\bparamount\b", "essential"),
    (r"\bseamless(?:ly)?\b", "smooth"),
    (r"\bgame[- ]changer\b", "big deal"),
    (r"\bcutting[- ]edge\b", "new"),
    (r"\bstate[- ]of[- ]the[- ]art\b", "modern"),
    (r"\brevolutioniz(?:e|es|ing)\b", "change"),
    (r"\btransformative\b", "real"),
    (r"\bempower(?:s|ing)?\b", "help"),
    (r"\bfoster(?:s|ing)?\b", "build"),
    (r"\brobust\b", "solid"),
    (r"\bcomprehensive\b", "complete"),
    (r"\bmeticulous(?:ly)?\b", "careful"),
    (r"\bpivotal\b", "key"),
    (r"\bnavigat(?:e|ing) the complexities of\b", "deal with"),
    (r"\b(?:a )?testament to\b", "proof of"),
    (r"\btapestry\b", "mix"),
    (r"\brealm\b", "world"),
    (r"\bto the next level\b", "further"),
    (r"\bserves as\b", "is"),
    (r"\bstands as\b", "is"),
    (r"\bboasts\b", "has"),
    (r"\bnestled in\b", "in"),
    (r"\bin the heart of\b", "in"),
    (r"\bfurthermore,\s*", "Also, "),
    (r"\bmoreover,\s*", "Plus, "),
    (r"\badditionally,\s*", "Also, "),
    (r"\bin conclusion,\s*", ""),
    (r"\bit'?s important to note that\s*", ""),
    (r"\bit is worth noting that\s*", ""),
    (r"\bat its core,\s*", ""),
]
_COMPILED = [(re.compile(p, re.IGNORECASE), r) for p, r in REPLACEMENTS]

CONTRACTIONS = {
    "do not": "don't", "does not": "doesn't", "did not": "didn't", "is not": "isn't",
    "are not": "aren't", "cannot": "can't", "can not": "can't", "will not": "won't",
    "it is": "it's", "that is": "that's", "you are": "you're", "we are": "we're",
    "they are": "they're", "you will": "you'll", "we will": "we'll", "there is": "there's",
}
# Only contract mid-clause: "who we are." must not become "who we're."
_CONTRACTION_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in CONTRACTIONS) + r")\b(?=\s+[A-Za-z])", re.IGNORECASE
)
_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Step:
    name: str
    text: str
    score: float
    accepted: bool = True
    note: str = ""


@dataclass
class HumanizeResult:
    text: str
    before: float
    after: float
    used_llm: bool
    mode: str = "standard"
    patterns_before: list[dict] = field(default_factory=list)
    patterns_after: list[dict] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)


def detect(text: str) -> list[dict]:
    """Which tells appear, how often, and an example of each."""
    found = []
    for pid, label, weight, rx in _PATTERN_RE:
        hits = [m.group(0).strip() for m in rx.finditer(text)]
        if hits:
            found.append({"id": pid, "label": label, "count": len(hits), "example": hits[0][:60], "weight": weight})
    dashes = text.count("—") + text.count(" – ") + text.count(" -- ")
    if dashes:
        found.append({"id": "dashes", "label": "Dashes as connectors", "count": dashes, "example": "—", "weight": 5})
    if text.count("!") > 1:
        found.append({"id": "exclaim", "label": "Exclamation spam", "count": text.count("!"), "example": "!", "weight": 4})
    emoji = len(_EMOJI_RE.findall(text))
    if emoji > 2:
        found.append({"id": "emoji", "label": "Emoji spam", "count": emoji, "example": "", "weight": 3})
    stiff = _CONTRACTION_RE.findall(text)
    if stiff:
        found.append({"id": "stiff", "label": "Stiff, uncontracted verbs", "count": len(stiff), "example": stiff[0], "weight": 4})
    if re.search("[“”‘’]", text):
        found.append({"id": "curly", "label": "Curly quotes", "count": 1, "example": "“”", "weight": 1})
    return found


def ai_tell_score(text: str) -> float:
    """0 = reads human, 100 = full of LLM tells."""
    if not text.strip():
        return 0.0
    score = sum(min(p["weight"] * p["count"], p["weight"] * 3) for p in detect(text))
    sentences = [s for s in _SENT_SPLIT.split(text.strip()) if s]
    if len(sentences) >= 3:
        lengths = [len(s.split()) for s in sentences]
        # Human writing is "bursty": sentence lengths vary. Uniform length is a tell.
        cv = statistics.pstdev(lengths) / max(1.0, statistics.mean(lengths))
        score += max(0.0, 10.0 * (0.45 - cv) / 0.45)
    if len(text.split()) > 25 and re.search(r"\b(\w+), (\w+),? and (\w+)\b", text):
        score += 3.0  # forced triads
    return round(min(100.0, score), 1)


def _contract(match: re.Match) -> str:
    word = match.group(0)
    repl = CONTRACTIONS[word.lower()]
    return repl[0].upper() + repl[1:] if word[0].isupper() else repl


def rule_pass(text: str) -> str:
    out = text
    for rx, repl in _COMPILED:
        out = rx.sub(repl, out)
    out = _CONTRACTION_RE.sub(_contract, out)
    out = re.sub(r"\s*—\s*", ", ", out)
    out = re.sub(r"\s+(?:–|--)\s+", ", ", out)
    out = out.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    # Keep at most one exclamation mark.
    parts = out.split("!")
    if len(parts) > 2:
        out = parts[0] + "!" + ".".join(parts[1:])
        out = re.sub(r"\.\s*\.", ".", out)
    seen = 0

    def cap_emoji(m: re.Match) -> str:
        nonlocal seen
        seen += 1
        return m.group(0) if seen <= 2 else ""

    out = _EMOJI_RE.sub(cap_emoji, out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"[ \t]+([,.!?])", r"\1", out)
    out = re.sub(r",\s*,", ",", out)
    out = re.sub(r"(^|[.!?]\s+|\n)([a-z])", lambda m: m.group(1) + m.group(2).upper(), out.strip())
    return out


# --------------------------------------------------------------------------- fact guard

_FACT_RE = re.compile(r"https?://\S+|www\.\S+|[@#][\w.]+|[$€£₹]\s?\d[\d,.]*|\d[\d,.]*\s?%|\b\d[\d,.:/-]*\b")


def protected_tokens(text: str, extra: list[str] | None = None) -> set[str]:
    toks = {m.group(0).rstrip(".,!?)").lower() for m in _FACT_RE.finditer(text)}
    for e in extra or []:
        if e and e.lower() in text.lower():
            toks.add(e.lower())
    return {t for t in toks if t}


def missing_facts(original: str, candidate: str, extra: list[str] | None = None) -> list[str]:
    cand = candidate.lower().replace(" ", "")
    return sorted(t for t in protected_tokens(original, extra) if t.replace(" ", "") not in cand)


# --------------------------------------------------------------------------- model passes

REWRITE_SYSTEM = """You edit social media captions so they read like the business owner wrote them, not a chatbot.
Keep what it says. Do not add any fact, number, price, date, name, claim or offer that is not in the caption.
Keep every link, @handle, #hashtag, price and the call to action exactly.

Remove these patterns (from Wikipedia's "Signs of AI writing"), strongest first:
1. "Not X, but Y" / "it's not just X, it's Y" contrasts: state the point directly.
2. One-line dramatic closers and fragment rows ("That's the magic." "No shortcuts. No compromises.").
3. Sayings that sound deep ("at its core", "the real question is").
4. Staged run-ups ("Let's dive in", "Here's the thing", "Real talk").
5. Forced triads of adjectives or benefits.
6. Dashes as connectors: use commas, periods or parentheses. No em dashes.
7. Stock AI words: delve, elevate, unlock, unleash, seamless, journey, tapestry, testament, vibrant, pivotal, crucial, game-changer, cutting-edge, leverage, landscape, showcase.
8. Inflated significance and brochure language ("nestled", "in the heart of", "breathtaking", "the future looks bright").
9. "serves as / stands as / boasts": use is / has.
10. Chatbot residue and exclamation or emoji spam (max one "!" and two emoji).

Write like a person: contractions, specific words, sentences of uneven length, an opinion where the owner would have one.
Same language and roughly the same length. Return only the caption."""

CHAIN_SYSTEM = "You are a professional copywriter fluent in many languages who localizes marketing text."
CHAIN_PROMPT = ("Translate into {lang}, removing any AI-sounding phrasing and rewriting it the way a real person would say it. "
                "Keep every number, price, link, @handle, #hashtag and brand name exactly as written. Output only the result:\n{text}")
BACK_PROMPT = ("Translate this into natural, casual English for a social media caption, written the way the business owner talks. "
               "Keep every number, price, link, @handle, #hashtag and brand name exactly as written. "
               "No em dashes. Output only the caption:\n{text}")


def _clean_model_text(text: str) -> str:
    return text.strip().strip('"').strip()


async def _standard_rewrite(text: str, voice: str) -> str:
    prompt = (f"Brand voice: {voice}\n\n" if voice else "") + f"Caption:\n{text}"
    return _clean_model_text(await router.complete("humanize", REWRITE_SYSTEM, prompt, temperature=0.9, max_tokens=700))


async def _translation_chain(text: str) -> list[tuple[str, str]]:
    """lynote-ai/humanize-text's chain, on Nemotron: EN -> Chinese -> Japanese (with history) -> English."""
    zh = _clean_model_text(await router.complete("humanize", CHAIN_SYSTEM, CHAIN_PROMPT.format(lang="Chinese", text=text), temperature=1.2, max_tokens=900))
    ja = _clean_model_text(await router.complete(
        "humanize", CHAIN_SYSTEM,
        f"Earlier you turned this:\n{text}\ninto:\n{zh}\n\n" + CHAIN_PROMPT.format(lang="Japanese", text=zh), temperature=1.2, max_tokens=900))
    en = _clean_model_text(await router.complete("humanize", CHAIN_SYSTEM, BACK_PROMPT.format(text=ja), temperature=0.7, max_tokens=900))
    return [("Rewrite → Chinese", zh), ("Rewrite → Japanese", ja), ("Back to English", en)]


async def humanize(
    text: str,
    *,
    voice: str = "",
    use_llm: bool = True,
    threshold: float = 15.0,
    mode: str = "standard",
    protect: list[str] | None = None,
) -> HumanizeResult:
    if not use_llm:
        mode = "light"
    before = ai_tell_score(text)
    res = HumanizeResult(text=text, before=before, after=before, used_llm=False, mode=mode, patterns_before=detect(text))
    res.steps.append(Step("Original", text, before))

    def accept(name: str, candidate: str, note: str = "") -> None:
        candidate = rule_pass(candidate)
        lost = missing_facts(text, candidate, protect)
        score = ai_tell_score(candidate)
        if not candidate:
            res.steps.append(Step(name, candidate, score, accepted=False, note="empty output"))
        elif lost:
            res.steps.append(Step(name, candidate, score, accepted=False, note="dropped " + ", ".join(lost[:5])))
        elif score > res.after and name != "Rule pass":
            res.steps.append(Step(name, candidate, score, accepted=False, note="scored worse"))
        else:
            res.steps.append(Step(name, candidate, score, note=note))
            res.text, res.after = candidate, score

    accept("Rule pass", text)

    if mode in ("standard", "deep") and router.enabled:
        try:
            if mode == "deep":
                hops = await _translation_chain(res.text)
                for name, out in hops[:-1]:
                    res.steps.append(Step(name, out, 0.0, note="intermediate"))
                accept(hops[-1][0], hops[-1][1])
                res.used_llm = True
            if mode == "deep" or res.after > threshold:
                accept("Nemotron pattern rewrite", await _standard_rewrite(res.text, voice))
                res.used_llm = True
        except LLMError as exc:
            res.steps.append(Step("Nemotron", "", res.after, accepted=False, note=f"model unavailable: {exc}"[:200]))
    res.patterns_after = detect(res.text)
    return res
