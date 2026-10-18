"""Bounded, exact multipart admission. Leave each file cursor unchanged."""
from starlette.datastructures import UploadFile
from app.security.seo_advisor_work import deny

UPLOADS = {
    '/api/v1/seo/qa/research/file-preview': ('file', 5 * 1024 * 1024, {'pdf', 'docx'}, set()),
    '/api/v1/seo/backlinks/import': ('file', 2 * 1024 * 1024, {'csv', 'xlsx'}, set()),
    '/api/v1/seo/site/page-captures/upload': ('file', 10 * 1024 * 1024, {'png', 'jpg', 'jpeg', 'webp'}, {'tenant_id', 'site_id', 'relation_type', 'relation_id'}),
}


async def request_body(request, rule):
    spec = UPLOADS.get(rule.template)
    if spec is None:
        return await request.json() if await request.body() else {}
    key, maximum, extensions, fields = spec
    form = await request.form(max_files=1, max_fields=20)
    if len(form.multi_items()) != len(form) or set(form) - ({key} | fields):
        deny('ADVISOR_WRITE_FIELD_FORBIDDEN')
    upload = form.get(key)
    if not isinstance(upload, UploadFile) or (upload.filename or '').rsplit('.', 1)[-1].lower() not in extensions:
        deny('ADVISOR_INVALID_OBJECT_FILE', 422)
    position = upload.file.tell()
    try:
        await upload.seek(0)
        data = await upload.read(maximum + 1)
        if not data or len(data) > maximum:
            deny('ADVISOR_OBJECT_FILE_TOO_LARGE', 413)
    finally:
        await upload.seek(position)
    return {name: value for name, value in form.items() if name != key}
