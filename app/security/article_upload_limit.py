"""Bound article uploads before FastAPI's multipart parser creates temp files."""
import asyncio
import io

from starlette.responses import JSONResponse

MAX_BODY_BYTES = 10 * 1024 * 1024 + 64 * 1024
UPLOAD_TIMEOUT_SECONDS = 30
PREVIEW_PATH = '/api/v1/geo/content-imports/preview-file'


class ArticleUploadLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope['type'] != 'http' or scope.get('method') != 'POST'
                or scope.get('path') != PREVIEW_PATH):
            return await self.app(scope, receive, send)

        async def reject(status, message):
            await JSONResponse({'detail': message}, status_code=status)(scope, receive, send)

        for key, value in scope.get('headers', []):
            if key.lower() == b'content-length':
                try:
                    length = int(value)
                    if length < 0:
                        raise ValueError()
                except ValueError:
                    return await reject(400, '上传文件大小格式不正确')
                if length > MAX_BODY_BYTES:
                    return await reject(413, '导入文件不能超过 10 MiB')

        # Buffer only this bounded endpoint. Counting streamed bytes also
        # covers chunked bodies and a missing or dishonest Content-Length.
        body = io.BytesIO()
        try:
            async with asyncio.timeout(UPLOAD_TIMEOUT_SECONDS):
                while True:
                    message = await receive()
                    if message['type'] == 'http.disconnect':
                        return
                    chunk = message.get('body', b'')
                    if body.tell() + len(chunk) > MAX_BODY_BYTES:
                        return await reject(413, '导入文件不能超过 10 MiB')
                    body.write(chunk)
                    if not message.get('more_body', False):
                        break
        except TimeoutError:
            return await reject(408, '上传超时，请检查网络后重试')
        payload = body.getvalue()
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': payload, 'more_body': False}
            return await receive()

        await self.app(scope, replay, send)
