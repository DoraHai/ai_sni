"""Isolated PDF parser: stdin bytes in, bounded JSON out; no application imports."""
import io
import json
import sys


def main():
    # Production is Linux. OS limits apply before importing the PDF parser or
    # resolving compressed object streams, not after allocating their output.
    if sys.platform != 'win32':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    from pypdf import PdfReader

    raw = sys.stdin.buffer.read(10 * 1024 * 1024 + 1)
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise ValueError('PDF input exceeds the import limit')
    reader = PdfReader(io.BytesIO(raw))
    max_pages = int(sys.argv[1])
    if len(reader.pages) > max_pages:
        print(json.dumps({'error': f'PDF documents cannot exceed {max_pages} pages'}))
        return
    parts, size = [], 0
    for page in reader.pages:
        part = page.extract_text() or ''
        size += len(part) + 2
        if size > 500_000:
            print(json.dumps({'error': 'PDF 正文过长，请拆分为 50 万字以内的文件'}))
            return
        parts.append(part)
    metadata = reader.metadata or {}
    title = getattr(metadata, 'title', None) or metadata.get('/Title')
    print(json.dumps({'text': '\n\n'.join(parts), 'title': str(title)[:300] if title else None},
                     ensure_ascii=True))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Never emit parser exception contents, PDF text or filesystem paths.
        raise SystemExit(1) from None
