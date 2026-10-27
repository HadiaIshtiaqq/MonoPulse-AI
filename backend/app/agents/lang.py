"""Languages for captions and reels: English, Roman Urdu (Urdu in Latin letters, the way
Pakistan texts), Urdu script, or English mixed with Roman Urdu.

Without a model the structural words (openings, endings, tips, labels, greetings) come from
these lists, written the way people actually post; product names and the brand's own facts
stay as the site writes them. With Nemotron the whole script or caption is written in the
language. Urdu is shaped (letters joined, right to left) before it's drawn.
"""
from __future__ import annotations

import re

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
except ImportError:  # shaping is optional; Latin text never needs it
    arabic_reshaper = None
    get_display = None

LANGUAGES = {"en": "English", "roman": "Roman Urdu", "ur": "Urdu", "mix": "English + Roman Urdu"}
ARABIC = re.compile(r"[؀-ۿﭐ-﷿ﹰ-﻿]")


def shape(text: str) -> str:
    """Urdu/Arabic as it must be drawn by a renderer without complex text layout: letters
    joined and in visual (right to left) order. Anything else is returned unchanged."""
    if not text or not ARABIC.search(text) or not arabic_reshaper:
        return text
    return get_display(arabic_reshaper.reshape(text))


def pools(lang: str) -> str:
    """Which word lists a language uses: mix takes Roman Urdu openings and endings, English tips."""
    return "roman" if lang == "mix" else lang if lang in ("roman", "ur") else "en"


HOOKS = {
    "roman": {
        "products": ["{n} cheezein jo aap ko pasand aayengi", "Hamari {n} favourite picks", "Yeh {n} dekhe bina mat jana"],
        "countdown": ["Hamare top {n}, abhi", "Top {n}: aap ka #1 kaunsa?"],
        "tips": ["{name} ko {verb} ke {n} tareeqay", "{name}: {n} kaam ki tips"],
        "poll": ["Yeh ya woh?", "Aap kaunsa loge?", "Faisla aap ka"],
        "story": ["{brand} hi kyun?", "Milo {brand} se", "{brand} ke baare mein {n} baatein"],
    },
    "ur": {
        "products": ["{n} چیزیں جو آپ کو پسند آئیں گی", "ہماری {n} پسندیدہ چیزیں"],
        "countdown": ["ہمارے ٹاپ {n}", "ٹاپ {n}: آپ کا نمبر ون کون سا؟"],
        "tips": ["{name} کو {verb} کے {n} طریقے", "{name}: {n} کام کی ٹپس"],
        "poll": ["یہ یا وہ؟", "آپ کون سا لیں گے؟"],
        "story": ["{brand} ہی کیوں؟", "ملیے {brand} سے"],
    },
}
ENDINGS = {
    "roman": {"products": ["Aap ka favourite kaunsa?", "Comment mein batao"], "countdown": ["Aap ka #1 kaunsa hai?"],
              "tips": ["Kaunsi tip try karoge?", "Save kar lo, kaam aayegi"], "poll": ["A ya B? Comment karo", "Vote karo neeche"],
              "story": ["Aao, khud dekh lo", "Yeh hain hum"]},
    "ur": {"products": ["آپ کا پسندیدہ کون سا؟"], "countdown": ["آپ کا نمبر ون کون سا ہے؟"], "tips": ["کون سی ٹپ آزمائیں گے؟"],
           "poll": ["اے یا بی؟ کمنٹ کریں"], "story": ["آئیں، خود دیکھیں"]},
}
VERBS = {"roman": {"wear": "pehnne", "food": "enjoy karne", "other": "use karne"},
         "ur": {"wear": "پہننے", "food": "مزے سے کھانے", "other": "استعمال کرنے"}}
TIPS = {
    "roman": {
        "wear": ["Baaki look simple rakho", "Ek statement accessory add karo", "Shaam ke liye heels ke saath", "Din mein flats ke saath",
                 "Ek rang ko lead karne do", "Thand mein layer karo"],
        "food": ["Garam garam khao", "Doston ke saath share karo", "Thandi drink ke saath try karo", "Dessert ke liye jagah rakho",
                 "Rush se pehle order karo", "Table ke liye side add karo"],
        "other": ["Baad ke liye save karo", "Pehle zaroorat wali cheez lo", "Team se mashwara lo", "Apni favourite ke saath pair karo",
                  "Is hafte try karo", "Dost ke saath share karo"],
    },
    "ur": {
        "wear": ["باقی لُک سادہ رکھیں", "ایک نمایاں ایکسیسری شامل کریں", "شام کے لیے ہیلز کے ساتھ", "دن میں فلیٹس کے ساتھ",
                 "ایک رنگ کو نمایاں رکھیں", "سردی میں لیئر کریں"],
        "food": ["گرم گرم کھائیں", "دوستوں کے ساتھ شیئر کریں", "ٹھنڈی ڈرنک کے ساتھ آزمائیں", "میٹھے کے لیے جگہ رکھیں",
                 "رش سے پہلے آرڈر کریں", "ٹیبل کے لیے سائیڈ لیں"],
        "other": ["بعد کے لیے سیو کریں", "پہلے ضرورت کی چیز لیں", "ٹیم سے مشورہ کریں", "اپنی پسندیدہ چیز کے ساتھ ملائیں",
                  "اس ہفتے آزمائیں", "دوست کے ساتھ شیئر کریں"],
    },
}
TIP_LABEL = {"en": "Tip {i}", "roman": "Tip {i}", "ur": "ٹپ {i}"}

GREETINGS = {  # occasion key -> (Roman Urdu, Urdu)
    "eid_fitr": ("Eid Mubarak", "عید مبارک"), "eid_adha": ("Eid ul Adha Mubarak", "عید الاضحیٰ مبارک"),
    "ramadan": ("Ramzan Mubarak", "رمضان مبارک"), "mothers": ("Happy Mother's Day", "ماں کا دن مبارک"),
    "fathers": ("Happy Father's Day", "والد کا دن مبارک"), "womens": ("Happy Women's Day", "خواتین کا عالمی دن مبارک"),
    "independence": ("Jashn-e-Azadi Mubarak", "جشنِ آزادی مبارک"), "anniversary": ("Saalgirah Mubarak", "سالگرہ مبارک"),
    "new_year": ("Naya Saal Mubarak", "نیا سال مبارک"), "sale": ("Sale shuru!", "سیل شروع!"),
}
OCCASION_LINES = {"roman": ["Tayyari shuru?", "Aap ke liye khaas", "Sab ke saath celebrate karo"],
                  "ur": ["تیاری شروع؟", "آپ کے لیے خاص", "سب کے ساتھ جشن منائیں"]}
FROM_BRAND = {"roman": "{brand} ki taraf se {greeting}", "ur": "{brand} کی طرف سے {greeting}"}


def greeting(key: str, lang: str, english: str) -> str:
    pair = GREETINGS.get(key)
    if not pair or pools(lang) == "en":
        return english
    return pair[0] if pools(lang) == "roman" else pair[1]


# --------------------------------------------------------------------------- trending reel formats
# Formats people know from their feeds. They never claim facts: "Rate these" asks the audience,
# it doesn't say they're bestsellers.

TRENDS = {
    "pov": {
        "label": "POV",
        "hook": {"en": {"wear": "POV: you found the outfit everyone will ask about", "food": "POV: it's Friday night and you deserve this",
                        "other": "POV: you finally found the one"},
                 "roman": {"wear": "POV: sab poochenge kahan se liya", "food": "POV: Friday raat aur yeh saamne",
                           "other": "POV: aakhir mil hi gaya"},
                 "ur": {"wear": "پی او وی: سب پوچھیں گے کہاں سے لیا", "food": "پی او وی: جمعے کی رات اور یہ سامنے",
                        "other": "پی او وی: آخر مل ہی گیا"}},
        "end": {"en": "Tag someone who needs this", "roman": "Usko tag karo jisko yeh chahiye", "ur": "اسے ٹیگ کریں جسے یہ چاہیے"},
    },
    "sign": {
        "label": "Your sign",
        "hook": {"en": "This is your sign to try {brand}", "roman": "Yeh aap ka sign hai {brand} try karne ka",
                 "ur": "یہ آپ کا اشارہ ہے {brand} آزمانے کا"},
        "end": {"en": "Consider this your sign", "roman": "Bas, sign mil gaya", "ur": "بس، اشارہ مل گیا"},
    },
    "rate": {
        "label": "Rate it",
        "hook": {"en": "Rate these, 1 to 10", "roman": "Inko 1 se 10 rate karo", "ur": "انہیں 1 سے 10 ریٹ کریں"},
        "tag": {"en": "1-10?", "roman": "1-10?", "ur": "1-10?"},
        "end": {"en": "Drop your ratings below", "roman": "Apni rating comment karo", "ur": "اپنی ریٹنگ کمنٹ کریں"},
    },
    "wait": {
        "label": "Wait for it",
        "hook": {"en": "Wait for the last one", "roman": "Last wala zaroor dekhna", "ur": "آخری والا ضرور دیکھیں"},
        "last": {"en": "The last one", "roman": "Last wala", "ur": "آخری والا"},
        "end": {"en": "Worth the wait?", "roman": "Wait karna banta tha na?", "ur": "انتظار بنتا تھا نا؟"},
    },
    "local": {
        "label": "From {city}",
        "hook": {"en": "Tell me you're from {city} without telling me", "roman": "Bina bataye batao ke {city} se ho",
                 "ur": "بتائے بغیر بتائیں کہ آپ {city} سے ہیں"},
        "end": {"en": "Tag a friend from {city}", "roman": "Apne {city} wale dost ko tag karo", "ur": "اپنے {city} والے دوست کو ٹیگ کریں"},
    },
}

# --------------------------------------------------------------------------- trending caption lines

OPENERS = {
    "en": ["POV: you just found your new favourite.", "This is your sign.", "Not us obsessing over this again.",
           "Main character energy, unlocked.", "Run, don't walk."],
    "roman": ["Yeh dekh ke dil khush ho gaya.", "Scene on hai!", "Sach batao, yeh chahiye na?", "Yeh wala toh banta hai.",
              "Bas, yehi chahiye tha."],
    "ur": ["یہ دیکھ کر دل خوش ہو گیا۔", "سچ بتائیں، یہ چاہیے نا؟", "بس، یہی چاہیے تھا۔", "یہ والا تو بنتا ہے۔"],
}
CLOSERS = {
    "en": ["Tag someone who needs to see this.", "Save this for later.", "Tell us in the comments."],
    "roman": ["Usko tag karo jisko yeh dikhana hai.", "Save kar lo, baad mein kaam aayega.", "Comment mein batao, kaisa laga?"],
    "ur": ["اسے ٹیگ کریں جسے یہ دکھانا ہے۔", "کمنٹ میں بتائیں، کیسا لگا؟"],
}
