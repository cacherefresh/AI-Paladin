"""
Public utility helpers. No protected IP. Safe to share with BIG-AI.
"""


def slugify(text):
    out = []
    for ch in text.lower().strip():
        if ch.isalnum():
            out.append(ch)
        elif ch in " -_":
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def truncate(text, limit=80, suffix="..."):
    # BUG: does not account for the suffix length, so the result can exceed
    # `limit` by len(suffix).
    if len(text) <= limit:
        return text
    return text[:limit] + suffix


def title_case(text):
    small = {"a", "an", "the", "of", "in", "on", "and", "or", "to"}
    words = text.split()
    return " ".join(w.capitalize() if i == 0 or w.lower() not in small
                    else w.lower() for i, w in enumerate(words))
