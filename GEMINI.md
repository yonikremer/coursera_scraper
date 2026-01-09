# Gemini Development Guidelines

## Exception Handling
- **NEVER** use broad `except Exception: pass` or `except Exception: continue` without a very specific reason. This is a very bad habit that must be avoided.
- **NEVER** use `except Exception: continue` in loops, as it can hide critical logic failures and lead to infinite loops or data corruption if unexpected errors occur.
- Always catch specific exceptions (e.g., `NoSuchElementException`, `requests.RequestException`).
- If a broad `Exception` must be caught, log it with at least a `print` or `logging.error` so bugs are not silently masked.
- Prioritize visibility of failures over silent continuation.

## Grammar and Style
- All code comments and documentation must use proper grammar, including correct usage of articles ("a", "an", "the").
- Comments must end with proper punctuation (periods).
