"""Keep only the tags that describe WHO the subject is (identity, body, hair, face, outfit, accessories).

Pose, expression, framing, background and style tags are dropped so a style preset can supply its own."""
import re

COUNT_TAGS = {"1girl", "2girls", "3girls", "1boy", "2boys", "3boys", "1other", "multiple girls", "multiple boys"}

# Expression/face-state tags that contain an otherwise-kept word ("eyes", "mouth", "lips").
NOT_CHARACTER = {"closed eyes", "half-closed eyes", "one eye closed", "open mouth", "closed mouth", "parted lips",
                 "licking lips", "rolling eyes", "wide-eyed", "looking at viewer", "eyes visible through hair",
                 "hair over one eye", "hand in own hair", "v-shaped eyebrows", "raised eyebrows", "furrowed brow", "eyebrows visible through hair",
                 "eyebrow cut", "sparkling eyes", "empty eyes", "crazy eyes", "heart-shaped pupils", "hair flip", "floating hair", "wind lift", "glowing eyes"}

_WORDS = [
    # identity / body
    "girl", "boy", "woman", "man", "breasts", "skin", "muscular", "abs", "freckles", "mole", "scar", "tattoo",
    "makeup", "beard", "mustache", "facial hair", "fangs", "pointy ears", "animal ears", "ears", "horns", "tail",
    "wings", "halo", "thighs", "hips", "midriff", "navel", "collarbone", "curvy", "plump", "petite", "tall",
    # head
    "hair", "bangs", "ponytail", "twintails", "braid", "bun", "ahoge", "sidelocks", "bob cut", "eyes", "eyebrows",
    "eyelashes", "eyeliner", "eyeshadow", "lips", "lipstick", "nail polish", "pupils", "sclera", "heterochromia",
    # clothing
    "shirt", "top", "blouse", "sweater", "hoodie", "jacket", "coat", "vest", "dress", "skirt", "miniskirt", "pants",
    "shorts", "jeans", "leggings", "uniform", "suit", "kimono", "armor", "bodysuit", "leotard", "bikini",
    "swimsuit", "lingerie", "bra", "panties", "corset", "apron", "cape", "cloak", "robe", "sleeves", "sleeveless",
    "collar", "necktie", "bowtie", "tie", "scarf", "belt", "pocket", "zipper", "buttons", "frills", "lace", "cleavage",
    "turtleneck", "crop", "off shoulder", "strapless", "halterneck", "gloves", "mittens", "thighhighs", "kneehighs",
    "socks", "pantyhose", "stockings", "garter", "boots", "shoes", "heels", "sandals", "sneakers", "barefoot", "footwear", "legwear", "headwear", "handwear",
    # accessories
    "hat", "cap", "beret", "helmet", "hood", "headband", "hairband", "hairclip", "hair ornament", "ribbon", "bow",
    "earrings", "necklace", "choker", "pendant", "jewelry", "bracelet", "ring", "glasses", "sunglasses", "eyewear",
    "mask", "eyepatch", "bracer", "wristband", "armband", "piercing", "crown", "tiara", "veil",
    # emblems / affiliation
    "emblem", "logo", "insignia", "team rocket", "print", "letter",
]
_PATTERN = re.compile(r"\b(" + "|".join(re.escape(w) for w in sorted(_WORDS, key=len, reverse=True)) + r")s?\b")


def is_character_tag(tag):
    t = tag.lower().strip()
    if t in COUNT_TAGS:
        return True
    if t in NOT_CHARACTER or "background" in t or "sheet" in t or "view" in t:
        return False
    return bool(_PATTERN.search(t))


def character_only(tags):
    """Plain tag names: every detected named character, then appearance tags in tagger confidence order."""
    out = [t for t, _ in tags.get("character", [])]
    out += [t for t, _ in tags.get("general", []) if is_character_tag(t)]
    return out
