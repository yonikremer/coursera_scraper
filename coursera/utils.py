import re


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename to ensure strict compliance:
    - Lowercase only.
    - Only a-z, 0-9, and underscores.
    - Exactly one dot separating name and extension.
    """
    if not filename:
        return "untitled"

    # Separate extension if present
    parts = filename.rsplit(".", 1)

    if len(parts) == 2:
        name, ext = parts
        # If the 'extension' is too long or has invalid chars, treat it as part of the name
        # Standard extensions are usually short (2-4 chars), but we can be generous (e.g., .ipynb, .html)
        if len(ext) > 5 or not re.match(r"^[a-z0-9]+$", ext.lower()):
            name = filename
            ext = ""
    else:
        name = parts[0]
        ext = ""

    # Sanitize the name part
    # Replace non-alphanumeric characters with underscores
    name = re.sub(r"[^a-z0-9]+", "_", name.lower())
    # Remove multiple underscores
    name = re.sub(r"_+", "_", name)
    # Strip leading/trailing underscores
    name = name.strip("_")

    if not name:
        name = "untitled"

    # Sanitize extension (lowercase, alphanumeric only)
    if ext:
        ext = re.sub(r"[^a-z0-9]+", "", ext.lower())
        return f"{name}.{ext}"

    return name


def extract_slug(item_url: str) -> str:
    """Extract a meaningful slug from Coursera URL."""
    if not item_url:
        return ""
    # Remove query parameters.
    url = item_url.split("?")[0]
    # Split by /.
    parts = [p for p in url.split("/") if p]
    if not parts:
        return ""

    # If it ends in /attempt, /submission, /view, etc., skip that part.
    if parts[-1].lower() in [
        "attempt",
        "submission",
        "view",
        "instructions",
        "gradedlab",
        "ungradedlab",
    ]:
        slug = parts[-2] if len(parts) >= 2 else parts[-1]
    else:
        slug = parts[-1]

    return sanitize_filename(slug)
