"""Only static, trusted codes/messages cross the API boundary."""


class ShadowError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class ExcelError(ShadowError):
    def __init__(self, message="内部Excel格式或绑定校验失败"):
        super().__init__("EXCEL_INVALID_OR_TAMPERED", message)
