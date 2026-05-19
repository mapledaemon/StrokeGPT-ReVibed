MOTION_TAG_SUGGESTIONS = (
    "intense",
    "full shaft",
    "mid shaft",
    "tip",
    "base",
    "teasing",
    "slow",
    "edging",
    "smooth",
    "steady",
    "deep",
    "shallow",
    "pulsing",
    "ramping",
)

INTERNAL_MOTION_TAGS = frozenset({
    "built-in",
    "program",
    "funscript",
    "program-section",
    "crop",
})


def motion_tag_suggestions():
    return list(MOTION_TAG_SUGGESTIONS)


def normalize_motion_tag(value, *, max_length=40):
    tag = " ".join(str(value or "").split()).strip().lower()
    return tag[:max_length]


def safe_motion_tags(value, *, max_tags=20, max_length=40):
    if not isinstance(value, list):
        return ()
    tags = []
    seen = set()
    for item in value[:max_tags]:
        tag = normalize_motion_tag(item, max_length=max_length)
        if not tag or tag in seen:
            continue
        tags.append(tag)
        seen.add(tag)
    return tuple(tags)
