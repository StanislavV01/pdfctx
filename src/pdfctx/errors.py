class PdfctxError(Exception):
    """An error whose message is safe and useful to show to a user or an agent."""


class NotFound(PdfctxError):
    """The requested document, section, block or table does not exist."""
