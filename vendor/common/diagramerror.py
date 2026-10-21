class DiagramError(Exception):
    """Error in a diagram source that should be reported with a source position."""

    def __init__(self, message: str, line: int = 1, column: int = 1):
        super().__init__(message)
        self.line = line
        self.column = column
