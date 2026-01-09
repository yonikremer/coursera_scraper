import re

def sanitize_filename(filename: str) -> str:
    """Remove invalid characters from the filename, convert to lowercase with underscores."""
    if not filename:
        return "untitled"
    # Replace invalid characters and punctuation with underscores.
    sanitized = re.sub(r'[<>:"/\\|?*,!]', '_', filename)
    # Handle ellipsis and multiple dots (replace with single underscore).
    sanitized = re.sub(r'\.{2,}', '_', sanitized)
    # Replace spaces and hyphens with underscores.
    sanitized = sanitized.replace(' ', '_').replace('-', '_')
    # Convert to lowercase.
    sanitized = sanitized.lower()
    # Remove multiple consecutive underscores.
    sanitized = re.sub(r'_+', '_', sanitized)
    # Strip leading/trailing underscores.
    sanitized = sanitized.strip('_')
    return sanitized or "untitled"

def extract_slug(item_url: str) -> str:
    """Extract a meaningful slug from Coursera URL."""
    if not item_url:
        return ""
    # Remove query parameters.
    url = item_url.split('?')[0]
    # Split by /.
    parts = [p for p in url.split('/') if p]
    if not parts:
        return ""
    
    # If it ends in /attempt, /submission, /view, etc., skip that part.
    if parts[-1].lower() in ['attempt', 'submission', 'view', 'instructions', 'gradedlab', 'ungradedlab']:
        slug = parts[-2] if len(parts) >= 2 else parts[-1]
    else:
        slug = parts[-1]
        
    return sanitize_filename(slug)
