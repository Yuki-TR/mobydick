#!/usr/bin/env python3
"""LTX-2.5 sinematik motion prompt şablonu + doğrulayıcı (tek dosya, GPU'suz).

Kurallar iki kılavuzdan türetilmiştir ve kodda ``RULE_*`` sabitleri olarak
pinlenmiştir:

  A) LTX-2 prompting guide (babakarto/cineclaw — prompting-guide.md)
     * Altın kural: TEK akan paragraf, şimdiki zaman, kronolojik, 4-8 cümle,
       madde işareti/liste yok.
     * Sıra: shot type → scene/env → subject+action → camera movement →
       visual style → audio cues.
     * "One camera movement per shot."
     * Lens dili: 24mm / 35mm / 50mm / 85mm / macro / anamorphic.
     * Kaçınılacaklar: iç duygu adları, okunabilir metin/logo, 8-10 cümleyi
       aşan taşkın prompt, geçmiş zaman, soyut kavramlar, 3+ özne.
     * Ses ipuçları (diyalog tırnak içinde, ambient, müzik) koda gider.

  B) Prompt writing guide (billpar/ai-cinematic-pipeline — 03-prompt-writing-guide.md)
     * Yönetmen zihniyeti: duyguyu değil, onu doğuran fiziksel durumu yaz.
     * Negatif alan/hareketsizlik AÇIKÇA yazılır.
     * VOICEOVER satırları prompt'a GİRMEZ; post-production'da eklenir.
     * İki karakterli sahnelerde mutlak konum (metre, yön, örtüşme) bildirilir.
     * Negatif prompt kullanma, aspect-ratio metni yazma.

Ayrıca ilk render denemesindeki iki somut hatayı karşılayan kurallar:
  * nesneler ters yöne hareket ediyordu  → R-EXPLICIT-DIRECTION
  * kamera sadece karakterin etrafında dönüyordu, gerçek dramatik hareket
    yoktu                                               → R-SUBJECT-MOTION

Kullanım
--------
    from cinematic_prompt import ShotSpec, render_motion_prompt, validate_motion_prompt

    shot = ShotSpec(
        shot_type="medium wide",
        lens="35mm",
        subject="a weathered whaler in his fifties in a charcoal greatcoat",
        action="walks away from camera up the cobblestone slipway",
        environment="a night fishing village quay, wet cobblestones, fog",
        lighting="practical lantern light and a cold blue moon",
        camera_move="tracks behind him at shoulder height",
        direction="his back stays to the lens and he moves deeper into frame",
        style="photorealistic historical drama, 35mm film grain, muted desaturated palette",
        audio="distant rope creak, water against timber, no dialogue",
    )
    prompt = render_motion_prompt(shot)          # tek paragraf, LTX-2 sırası
    issues = validate_motion_prompt(prompt)      # [] ise modele gönderilebilir
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

__all__ = [
    "ShotSpec",
    "PromptIssue",
    "render_motion_prompt",
    "validate_motion_prompt",
    "assert_valid_motion_prompt",
    "SHORT_RULES",
    "SHOT_TYPES",
    "CAMERA_MOVES",
    "LENSES",
    "LIGHTING_KEYWORDS",
    "STYLE_MODIFIERS",
]

# ---------------------------------------------------------------------------
# Sözlükler (kılavuzlardan birebir)
# ---------------------------------------------------------------------------

#: Kısa adı → ilk cümlenin başında kullanılacak shot type ifadesi.
SHOT_TYPES: dict[str, str] = {
    "close_up": "A close-up",
    "medium_close_up": "A medium close-up",
    "medium": "A medium shot",
    "medium_wide": "A medium wide shot",
    "wide": "A wide shot",
    "extreme_wide": "An extreme wide shot",
    "aerial": "An aerial shot",
    "pov": "A point-of-view shot",
    "over_the_shoulder": "An over-the-shoulder shot",
    "insert": "An insert shot",
}

#: Tek seferde kullanılabilecek kamera hareketleri. Anahtar → fiil cümlesi.
CAMERA_MOVES: dict[str, str] = {
    "static": "The camera holds completely still at eye level",
    "dolly_in": "The camera dollies in at eye level, closing the distance slowly",
    "dolly_out": "The camera dollies out at eye level, opening the frame slowly",
    "pan_left": "The camera pans left at a constant height",
    "pan_right": "The camera pans right at a constant height",
    "tilt_up": "The camera tilts up from eye level to the rigging",
    "tilt_down": "The camera tilts down from the deck toward the waterline",
    "crane_up": "The camera cranes up and above the quay, gaining height",
    "crane_down": "The camera cranes down toward the deck edge",
    "track_left": "The camera tracks left alongside the subject at eye level",
    "track_right": "The camera tracks right alongside the subject at eye level",
    "handheld": "The camera holds in a handheld documentary grip at eye level",
    "steadicam": "The camera follows in a smooth steadicam float at eye level",
    "rack_focus": "The camera racks focus from the foreground to the subject behind",
}

#: Objektif → (kısa etiket, doğal dilde kullanım notu)
LENSES: dict[str, str] = {
    "24mm": "wide-angle",
    "35mm": "natural perspective",
    "50mm": "portrait-like with slight compression",
    "85mm": "strong background separation",
    "macro": "extreme close-up",
    "anamorphic": "anamorphic wide format with soft flares",
}

#: Işık anahtar kelimeleri — serbest metin, ama sözlük doğrulamada referans.
LIGHTING_KEYWORDS: tuple[str, ...] = (
    "golden hour", "overcast", "neon-lit", "dramatic side lighting", "backlit",
    "practical light", "practical lantern", "candlelit", "moonlight",
    "chiaroscuro", "high-key", "low-key", "harsh sunlight",
)

#: Stil ekleri.
STYLE_MODIFIERS: tuple[str, ...] = (
    "film grain", "35mm film stock", "raw footage", "handheld",
    "documentary style", "smooth, polished, commercial grade", "dreamy, soft focus",
    "ethereal", "high contrast, desaturated, noir", "vibrant, saturated, pop colors",
    "photorealistic", "shallow depth of field",
)

#: Süreye göre önerilen cümle aralığı (kılavuz "Duration Tips" + 4-8 cümle).
SENTENCE_BUDGET: dict[int, tuple[int, int]] = {
    6: (4, 6),
    8: (4, 8),
    10: (5, 8),
    14: (5, 8),
    20: (6, 8),
}

MIN_SENTENCES = 4
MAX_SENTENCES = 8

# ---------------------------------------------------------------------------
# Doğrulama sözlükleri
# ---------------------------------------------------------------------------

#: İç durum/duygu adları — fiziksel karşılığı yazılmalı.
EMOTION_WORDS: tuple[str, ...] = (
    "feels", "feel", "feeling", "felt", "emotion", "emotional", "sad", "sadly",
    "happy", "happiness", "angry", "anger", "afraid", "fear", "fearful", "anxious",
    "anxiety", "worried", "worry", "nervous", "melancholy", "melancholic",
    "wistful", "nostalgic", "hopeful", "longing", "lonely", "desperate", "despair",
    "triumphant", "tender", "eerie emotion", "romantic mood", "ominous mood",
)

#: Soyut / figüratif anlatım — yönlendirici fiziksel karşılık ister.
ABSTRACT_WORDS: tuple[str, ...] = (
    "metaphor", "metaphorical", "as if time", "like a memory", "symbolizing",
    "symbolises", "symbolizes", "seems to", "the idea of", "the feeling of",
    "a sense of", "poetic", "allegor",
)

#: Okunabilir metin/logo — model bunu bozar.
TEXT_WORDS: tuple[str, ...] = (
    "caption", "subtitles", "subtitle", "title card", "lower third", "watermark",
    "logo", "sign reading", "readable text", "on-screen text", "poster reading",
)

_BULLET_RE = re.compile(r"(?m)^\s*(?:[-*•]|\d+[.)])\s")
_LIST_MARKERS = ("\n", "—", " – ", "; ", "  ")
_ASPECT_RE = re.compile(
    r"\b(?:\d+\s*[:x×]\s*\d+(?::\d+)?|aspect\s*ratio|16:9|9:16|4:3|21:9|2\.39:1|4k|1080p|720p)\b",
    re.IGNORECASE,
)
_PAST_TENSE_RE = re.compile(r"\b[a-z]{3,}ed\b", re.IGNORECASE)
_PAST_FORMS = frozenset(
    """was were had been being went gone came coming saw seen took taken made making
    said told became begun began rose risen fell fallen held held stood stood lay
    lay sat sitting ran running drew drawn spoke spoken threw thrown caught caught
    bought brought sought sought thought thought slept slept woke woken
    """.split()
)
#: -ed'li ama fiil olmayan yaygın kelimeler (yanlış pozitifleri susturur).
_PAST_ALLOW = frozenset(
    (
        "red bed wed ded fled sled shred spread need seed feed speed indeed "
        "sacred aged naked wicked tired hatred kindred rugged "
        # -ed'li SIFAT/EDAT biçimleri (fiil değildir):
        "cramped desaturated muted saturated weathered closed soaked undressed "
        "bearded rigged clouded tattered soiled crusted layered "
        # -ed'li SIFAT/DURUM (yön kilitlerinde çok kullanılır, fiil değil):
        "unchanged unlit unfinished unchecked unbrushed unmarked unpaved "
    ).split()
)
_PAST_IRREGULAR_RE = re.compile(
    r"\b(?:" + "|".join(sorted(_PAST_FORMS)) + r")\b", re.IGNORECASE
)

#: Yön belirteçleri — R-EXPLICIT-DIRECTION (ters-hareket hatasının panzehiri).
DIRECTION_TOKENS: tuple[str, ...] = (
    "toward", "towards", "away from", "into the frame", "out of frame",
    "deeper into frame", "forward", "backward", "screen left", "screen right",
    "left", "right", "behind", "in front of", "up to", "down to", "across frame",
    "closer to", "further from", "past",
)

#: Özne hareketi fiilleri — R-SUBJECT-MOTION (dramatik hareket zorunluluğu).
MOTION_VERBS: tuple[str, ...] = (
    "walk", "walks", "running", "runs", "steps", "moves", "drifts", "turns",
    "reaches", "raises", "lowers", "grips", "pulls", "pushes", "lifts", "falls",
    "stumbles", "climbs", "leans", "bends", "opens", "closes", "unfurls", "sways",
    "shakes", "spills", "blows", "rolls", "slides", "collapses", "strikes",
    "whispers", "speaks", "stand",
    "stands", "sit", "sits", "lean", "leans", "brace", "braces", "crouch",
    "crouches", "gaze", "gazes", "stares", "watches", "listens", "kneel",
    "crank", "grind", "spin", "waves", "signal", "points", "shrug",
)

_VOICEOVER_RE = re.compile(r"\b(voice\s?over|narration|narrator|inner monologue)\b", re.IGNORECASE)
_NEGATIVE_RE = re.compile(
    r"\b(negative\s+prompt|no\s+negatives?\b|avoid\b|without\s+(?:any\s+)?(?:motion|camera|movement))",
    re.IGNORECASE,
)
_QUOTED_RE = re.compile(r"[\"“”']([^\"“”']{2,})[\"“”']")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

#: Kısa ad → kural açıklaması (testler ve hata mesajları pinliyor).
SHORT_RULES: dict[str, str] = {
    "R-SINGLE-PARAGRAPH": "prompt tek bir paragraf olmalı; madde/liste/newline yok",
    "R-SENTENCE-COUNT": f"cümle sayısı {MIN_SENTENCES}..{MAX_SENTENCES} aralığında olmalı",
    "R-PRESENT-TENSE": "geçmiş zaman kullanılmamalı; şimdiki zaman zorunlu",
    "R-SHOT-TYPE-FIRST": "ilk cümle shot type ile başlamalı",
    "R-STRUCTURE-ORDER": "sıra: shot type → ortam → özne+eylem → kamera → stil → ses",
    "R-LENS-VALID": f"lens sözlüğünden olmalı: {', '.join(LENSES)}",
    "R-ONE-CAMERA-MOVEMENT": "kare başına tek kamera hareketi",
    "R-CAMERA-MOVEMENT-PRESENT": "kamera hareketi cümlesi bulunmalı (static dahil)",
    "R-SUBJECT-MOTION": "öznenin fiziksel eylemi açık bir fiille verilmeli",
    "R-EXPLICIT-DIRECTION": "hareket yönü açıkça yazılmalı (ters-hareket hatasını önler)",
    "R-AUDIO-CUE": "ses ipucu (ambient/müzik/konuşma) cümlesi bulunmalı",
    "R-NO-EMOTION-ABSTRACTS": "iç duygu adı yerine fiziksel durum yazılmalı",
    "R-NO-ABSTRACT": "soyut/figüratif anlatım kullanılmamalı",
    "R-NO-TEXT-OR-LOGO": "karede okunabilir metin/logo istenmemeli",
    "R-NO-NEGATIVE-PROMPT": "negatif prompt kullanılmamalı",
    "R-NO-ASPECT-RATIO": "prompt içine aspect-ratio/çözünürlük metni girmemeli",
    "R-NO-VOICEOVER": "VOICEOVER satırları post-production'a ait, prompt'a girmez",
    "R-EXPLICIT-STILLNESS": "kamera sabit ise hareketsizlik açıkça yazılmalı",
    "R-MULTI-SUBJECT-LIMIT": "karede en fazla 2 özne olmalı",
    "R-SPATIAL-BLOCKING": "2 özne varsa mutlak konum (metre/yön) bildirilmeli",
}

#: ``_validate_keys`` tarafından üretilen mesajlar bu anahtarlara karşılık gelir.


@dataclass(frozen=True)
class PromptIssue:
    """Bir kural ihlali."""

    rule: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.rule}: {self.message}"


@dataclass(frozen=True)
class ShotSpec:
    """Bir sahne için sinematik yönetim girdileri (kılavuz sırasına göre).

    Alan sırası = prompt'un cümle sırası. Boş bırakılan alan üretilen paragrafta
    o cümleyi düşürür (yalnızca zorunlu alanlar zorunludur).
    """

    shot_type: str                       # SHOT_TYPES anahtarı
    subject: str                         # özne + kıyafet/fiziksel betimleme
    action: str                          # öznenin şimdiki zamandaki eylemi
    environment: str                     # mekân, hava, ışık, atmosfer
    camera_move: str                     # CAMERA_MOVES anahtarı
    lens: str = "35mm"                   # LENSES anahtarı
    lighting: str = ""                   # "practical lantern light and cold blue moon"
    direction: str = ""                  # hareket yönü ("toward camera", "away from camera")
    stillness: str = ""                  # negatif alan ("no hand movement, no blinking")
    blocking: str = ""                   # 2+ özne için mutlak konum
    style: str = ""                      # renk derecelendirme, film stock, dof
    audio: str = ""                      # ambient + müzik; diyalog tırnak içinde
    dialogue: str = ""                   # konuşulan replik (post-VO olmayan)

    def __post_init__(self) -> None:
        if self.shot_type not in SHOT_TYPES:
            raise KeyError(
                f"shot_type {self.shot_type!r} bilinmiyor; seçenekler: "
                f"{', '.join(SHOT_TYPES)}"
            )
        if self.camera_move not in CAMERA_MOVES:
            raise KeyError(
                f"camera_move {self.camera_move!r} bilinmiyor; seçenekler: "
                f"{', '.join(CAMERA_MOVES)}"
            )
        if self.lens not in LENSES:
            raise KeyError(
                f"lens {self.lens!r} bilinmiyor; seçenekler: {', '.join(LENSES)}"
            )


# ---------------------------------------------------------------------------
# Şablon: tek akan paragraf, kronolojik, LTX-2 sırası
# ---------------------------------------------------------------------------

def _article(word: str) -> str:
    """İngilizce indefinite article: 'an 85mm lens', 'a 35mm lens'."""
    head = word[:1].lower()
    return "an" if head in ("8", "a", "e", "i", "o", "u") else "a"


def _join(parts: Iterable[str]) -> str:
    """Cümle parçalarını TEK akan paragrafa çevirir (kılavuz A: altın kural).

    Her parça bir cümledir: aralarına ". " konur, sonda tek nokta bırakılır.
    """
    chunks = []
    for part in parts:
        text = part.strip().rstrip(".")
        if not text:
            continue
        text = text[0].upper() + text[1:]
        chunks.append(text)
    return ". ".join(chunks) + "."


def render_motion_prompt(shot: ShotSpec) -> str:
    """ShotSpec → tek paragraf LTX-2 motion prompt.

    Cümle sırası (kılavuz A): shot type → ortam/ışık → özne+eylem(+yön,
    +negatif alan, +blocking) → kamera → stil → ses. Tümü şimdiki zamanda.
    """
    if shot.dialogue.strip():
        audio = f'{shot.audio.rstrip(".")}, {shot.subject.split(" in ")[0]} says "{shot.dialogue.strip()}"'
    elif shot.audio.strip():
        audio = shot.audio
    else:
        audio = "Room tone only, no dialogue."

    sentences = [
        # 1) shot type + lens + özne + eylem
        f"{SHOT_TYPES[shot.shot_type]} on {_article(shot.lens)} {shot.lens} lens "
        f"({LENSES[shot.lens]}) of "
        f"{shot.subject.strip()} {shot.action.strip()}",
        # 2) ortam + ışık
        f"In {shot.environment.strip()}"
        + (f", {shot.lighting.strip()}" if shot.lighting.strip() else ""),
        # 3a) yön (ters-hareket panzehiri)
        f"Direction: {shot.direction.strip()}" if shot.direction.strip() else "",
        # 3b) negatif alan / hareketsizlik
        f"Stillness: {shot.stillness.strip()}" if shot.stillness.strip() else "",
        # 3c) 2+ özne için mutlak konum
        f"Blocking: {shot.blocking.strip()}" if shot.blocking.strip() else "",
        # 4) kamera (tek hareket — kılavuz A: "one camera movement per shot")
        CAMERA_MOVES[shot.camera_move],
        # 5) stil
        shot.style.strip() or "Photorealistic, 35mm film grain, natural color",
        # 6) ses
        audio.strip(),
    ]
    return _join(sentences)


# ---------------------------------------------------------------------------
# Doğrulayıcı
# ---------------------------------------------------------------------------

def split_sentences(text: str) -> list[str]:
    """Cümle ayrıştırma (kısaltma nokta sonrası bölmeyen basit kural)."""
    cleaned = re.sub(r"\s+", " ", text.strip())
    if not cleaned:
        return []
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(cleaned) if p.strip()]
    return parts


def _issue(rule: str, message: str) -> PromptIssue:
    return PromptIssue(rule, f"{SHORT_RULES[rule]} — {message}")


def _find_camera_moves(text: str) -> list[str]:
    low = text.lower()
    hits: list[str] = []
    aliases: dict[str, tuple[str, ...]] = {
        "dolly_in": ("dollies in", "dolly in", "pushes in", "push in", "dollying in"),
        "dolly_out": ("dollies out", "dolly out", "pulls back", "pull back", "dollying out"),
        "pan_left": ("pans left", "pan left", "panning left"),
        "pan_right": ("pans right", "pan right", "panning right"),
        "tilt_up": ("tilts up", "tilt up", "tilting up"),
        "tilt_down": ("tilts down", "tilt down", "tilting down"),
        "crane_up": ("cranes up", "crane up", "craning up", "rises above"),
        "crane_down": ("cranes down", "crane down", "craning down", "descends"),
        "track_left": ("tracks left", "track left", "tracking left"),
        "track_right": ("tracks right", "track right", "tracking right"),
        "orbit": ("orbits", "circles around", "arcs around"),
        "handheld": ("handheld",),
        "steadicam": ("steadicam",),
        "rack_focus": ("rack focus", "racks focus"),
        "static": ("holds completely still", "camera is static", "static shot", "locked off"),
    }
    for key, phrases in aliases.items():
        if any(p in low for p in phrases):
            hits.append(key)
    return hits


#: Kişi/özne rolü kelimeleri — R-MULTI-SUBJECT-LIMIT ve R-SPATIAL-BLOCKING.
PERSON_NOUNS: tuple[str, ...] = (
    "man", "men", "woman", "women", "boy", "girl", "child", "children", "sailor",
    "sailors", "whaler", "whalers", "harpooner", "harpooners", "captain",
    "stranger", "crew", "crewman", "figure", "figures", "person", "people",
    "watcher", "owner", "master", "crewman", "woman", "friend", "passenger",
    "passengers", "soldier", "soldiers", "nurse", "doctor", "worker", "workers",
    "shopkeeper", "mother", "father", "son", "daughter", "girl", "bystander",
    "silhouette", "silhouettes", "horseman", "riders", "rider", "crewmen",
)


def _count_subjects(text: str) -> int:
    """Karedeki bağımsız özne sayısı (en fazla 2 kabul edilir).

    Kişi rolü kelimelerinin kümeleri sayılır; "a cat" gibi tek özne için 1.
    """
    low = text.lower()
    if "no other" in low or re.search(r"\b(alone|empty of people|deserted of people)\b", low):
        return 1
    found = {noun for noun in PERSON_NOUNS if re.search(rf"\b{noun}\b", low)}
    if not found:
        return 1
    # "a" gibi belirsiz zamirler ek özne saymaz; en az 1.
    return max(1, len(found))


def _past_tense_words(text: str) -> list[str]:
    found: set[str] = set()
    for match in _PAST_TENSE_RE.finditer(text):
        word = match.group(0).lower()
        if word not in _PAST_ALLOW:
            found.add(word)
    for word in _PAST_IRREGULAR_RE.findall(text):
        found.add(word.lower())
    return sorted(found)


_ENV_RE = re.compile(
    r"\b(?:in|inside|on|at|against|within|across|beneath|under|along)\s+"
    r"(?:the|a|an)?\s*[^,.;]*"
    r"\b(?:sea|ocean|harbou?r|street|room|corridor|deck|forest|field|desert|sky|"
    r"night|morning|evening|city|village|ship|quay|beach|station|office|cabin|"
    r"canyon|mountain|square|pub|kitchen|warehouse|factory|chapel|cellar|attic|"
    r"platform|bridge|road|hill|river|island|prison|whaleboat|waterline|rigging|"
    r"planking|deckhouse|warehouse|dock|shore|tavern|stairwell|hold)\b",
    re.IGNORECASE,
)
_CAMERA_RE = re.compile(r"\bthe camera\b", re.IGNORECASE)
_STYLE_RE = re.compile(
    r"\b(?:photorealistic|film grain|film stock|noir|desaturated|documentary|"
    r"shallow depth of field|colour grade|color grade|graded|ethereal|vibrant|"
    r"commercial grade|raw footage|cel-shaded|stop-motion)\b",
    re.IGNORECASE,
)
_AUDIO_RE = re.compile(
    r"\b(?:sound|sounds|audio|noise|noises|room tone|ambient|hum|humming|"
    r"melancholic piano|no dialogue|whisper|whispers|footsteps|creak|creaks|"
    r"wind|rain|gulls|silence|roar|clatter|shouting|music)\b",
    re.IGNORECASE,
)


def _structure_positions(sentences: Sequence[str]) -> dict[str, int]:
    """Her yapı bölümünün İLK cümle indeksi (-1 = yok).

    Kılavuz A sırası cümle indeksleriyle denetlenir: subject(0) → env →
    camera → style → audio. Karakter ofseti yerine cümle indeksi kullanılır,
    çünkü aksi halde özne cümlesindeki "toward camera" ifadesi kamera
    bölümü sanılır. Ortam bölümü "at night ... rain" gibi kelimeler içerebildiği
    için ses bölümü yalnızca kamera cümlesinden SONRA aranır.
    """
    positions: dict[str, int] = {"subject": 0}
    for name, regex in (("env", _ENV_RE), ("camera", _CAMERA_RE),
                        ("style", _STYLE_RE)):
        positions[name] = next(
            (i for i, sentence in enumerate(sentences) if regex.search(sentence)), -1
        )
    floor = max(positions["camera"], positions["style"], 0)
    positions["audio"] = next(
        (i for i, sentence in enumerate(sentences) if i > floor and _AUDIO_RE.search(sentence)),
        -1,
    )
    return positions


def validate_motion_prompt(text: str, *, min_sentences: int = MIN_SENTENCES,
                           max_sentences: int = MAX_SENTENCES) -> list[PromptIssue]:
    """Prompt'u iki kılavuzdan türetilmiş kurallara karşı doğrular.

    Dönen liste boşsa prompt modele gönderilebilir. ``assert_valid_motion_prompt``
    yükseltme yapan sarmalayıcıdır.
    """
    issues: list[PromptIssue] = []
    raw = text.strip()
    if not raw:
        return [_issue("R-SINGLE-PARAGRAPH", "prompt boş")]

    # --- biçim: tek paragraf, liste yok ---------------------------------
    if "\n" in text.strip() or _BULLET_RE.search(text):
        issues.append(_issue("R-SINGLE-PARAGRAPH", "newline veya madde işareti bulundu"))
    for marker in ("; ", "  "):
        if marker in text:
            issues.append(
                _issue("R-SINGLE-PARAGRAPH", f"tek paragraf kuralı: {marker.strip()!r} ayırıcı")
            )
            break

    # --- cümle sayısı ---------------------------------------------------
    sentences = split_sentences(raw)
    if not (min_sentences <= len(sentences) <= max_sentences):
        issues.append(
            _issue("R-SENTENCE-COUNT", f"{len(sentences)} cümle ({min_sentences}..{max_sentences})")
        )

    # --- şimdiki zaman --------------------------------------------------
    past = _past_tense_words(raw)
    if past:
        issues.append(_issue("R-PRESENT-TENSE", "geçmiş zaman: " + ", ".join(past[:5])))

    # --- shot type ilk cümlede -----------------------------------------
    if sentences:
        first = sentences[0].lower()
        if not any(first.startswith(phrase.lower()) for phrase in SHOT_TYPES.values()):
            issues.append(
                _issue("R-SHOT-TYPE-FIRST", f"ilk cümle shot type ile başlamıyor: {sentences[0][:48]!r}")
            )

    # --- yapı sırası ----------------------------------------------------
    pos = _structure_positions(sentences)
    order = [("subject", pos["subject"]), ("env", pos["env"]), ("camera", pos["camera"]),
             ("style", pos["style"]), ("audio", pos["audio"])]
    present = [(name, value) for name, value in order if value >= 0]
    for (a_name, a_pos), (b_name, b_pos) in zip(present, present[1:]):
        if a_pos > b_pos:
            issues.append(
                _issue("R-STRUCTURE-ORDER", f"{a_name} bölümü {b_name} bölümünden sonra geliyor")
            )
            break

    # --- lens ------------------------------------------------------------
    if not re.search(r"\b\d{2,3}\s*mm\b|\bmacro\b|\banamorphic\b", raw, re.IGNORECASE):
        issues.append(_issue("R-LENS-VALID", "lens belirtilmemiş"))

    # --- kamera ----------------------------------------------------------
    moves = _find_camera_moves(raw)
    if not moves:
        issues.append(_issue("R-CAMERA-MOVEMENT-PRESENT", "kamera davranışı cümlesi yok"))
    elif len(moves) > 1:
        issues.append(
            _issue("R-ONE-CAMERA-MOVEMENT", "birden fazla hareket: " + ", ".join(sorted(moves)))
        )
    if moves == ["static"]:
        camera_at = pos["camera"]
        rest = " ".join(
            sentence for i, sentence in enumerate(sentences) if i != camera_at
        )
        if not re.search(
            r"(no hand movement|no blinking|no shift in weight|no reaction|"
            r"does not move|not moving|locked off|without moving|holds perfectly|"
            r"remains perfectly still|stays completely still)",
            rest,
            re.IGNORECASE,
        ):
            issues.append(
                _issue("R-EXPLICIT-STILLNESS", "sabit kamerada hareketsizlik açıkça yazılmamış")
            )

    # --- özne hareketi + yön -------------------------------------------
    low = raw.lower()
    if not any(re.search(rf"\b{verb}\w*\b", low) for verb in MOTION_VERBS):
        issues.append(
            _issue("R-SUBJECT-MOTION", "öznenin fiziksel eylemi fiil olarak yazılmamış")
        )
    # Yön yalnızca ÖZNE cümlesinde (ilk cümle) veya açık "Direction:" cümlesinde
    # aranır; "light from the left" gibi ışık ifadeleri yön sayılmaz.
    direction_scope = " ".join(
        sentence for sentence in sentences
        if sentence.lower().startswith("direction:")
    ) or (sentences[0] if sentences else "")
    if not any(token in direction_scope.lower() for token in DIRECTION_TOKENS):
        issues.append(
            _issue("R-EXPLICIT-DIRECTION", "hareket yönü belirtilmemiş (nesne ters yöne gidebilir)")
        )

    # --- ses -------------------------------------------------------------
    if not pos["audio"] >= 0 and not _QUOTED_RE.search(raw):
        issues.append(_issue("R-AUDIO-CUE", "ses/ortam ipucu cümlesi yok"))

    # --- yasaklar --------------------------------------------------------
    for word in EMOTION_WORDS:
        if re.search(rf"\b{re.escape(word)}\w*\b", low):
            issues.append(
                _issue("R-NO-EMOTION-ABSTRACTS", f"iç duygu ifadesi: {word!r}")
            )
            break
    for word in ABSTRACT_WORDS:
        if word in low:
            issues.append(_issue("R-NO-ABSTRACT", f"soyut anlatım: {word!r}"))
            break
    for word in TEXT_WORDS:
        if word in low:
            issues.append(_issue("R-NO-TEXT-OR-LOGO", f"metin/logo isteniyor: {word!r}"))
            break
    if _NEGATIVE_RE.search(raw):
        issues.append(_issue("R-NO-NEGATIVE-PROMPT", "negatif prompt dili kullanıldı"))
    if _ASPECT_RE.search(raw):
        issues.append(_issue("R-NO-ASPECT-RATIO", "aspect-ratio/çözünürlük metni var"))
    if _VOICEOVER_RE.search(raw):
        issues.append(
            _issue("R-NO-VOICEOVER", "VOICEOVER satırı post-production'a ait")
        )

    # --- özne sayısı / blocking -----------------------------------------
    scope = " ".join(
        sentence
        for i, sentence in enumerate(sentences)
        if i == 0 or sentence.lower().startswith("blocking:")
    )
    subjects = _count_subjects(scope)
    if subjects > 2:
        issues.append(_issue("R-MULTI-SUBJECT-LIMIT", f"{subjects} özne"))
    elif subjects == 2 and not re.search(r"\b\d+(\.\d+)?\s*(m\b|meters?|metres?)", low):
        issues.append(
            _issue("R-SPATIAL-BLOCKING", "2 özne var ama mutlak mesafe (metre) bildirilmemiş")
        )

    return issues


def assert_valid_motion_prompt(
    text: str, *, min_sentences: int = MIN_SENTENCES, max_sentences: int = MAX_SENTENCES
) -> str:
    """Geçerli ise prompt'u döndürür, değilse tüm ihlalleri tek hata ile yükseltir."""
    issues = validate_motion_prompt(
        text, min_sentences=min_sentences, max_sentences=max_sentences
    )
    if issues:
        raise ValueError("geçersiz motion prompt:\n  - " + "\n  - ".join(str(i) for i in issues))
    return text
