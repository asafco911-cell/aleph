"""Failures in the document layer.

Library code raises; only CLI entry points decide process exit codes. A
sys.exit() inside a library kills a Streamlit session or a notebook kernel
instead of failing one request.
"""


class DocumentError(Exception):
    """A document is not what it claims to be, or cannot be parsed."""