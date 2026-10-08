"""Scan Inbox exception types."""


class ScanInboxError(Exception):
    """Base for Scan Inbox filing errors."""


class ScanInboxAlreadyDone(ScanInboxError):
    pass


class ScanInboxNotFound(ScanInboxError):
    pass


class ScanInboxTooLarge(ScanInboxError):
    pass


class ScanInboxNotPdf(ScanInboxError):
    pass


class ScanInboxDestinationError(ScanInboxError):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class ScanInboxNameConflict(ScanInboxError):
    pass


class ScanInboxWritesDisabled(ScanInboxError):
    pass


class ScanInboxLookupError(ScanInboxError):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)
