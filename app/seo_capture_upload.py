"""Bounded, structural image validation and metadata removal for manual evidence.

No decoder is invoked. PNG color/profile chunks needed by renderers are retained;
JPEG APP0 (JFIF) and APP14 (Adobe) are retained for color compatibility.
"""

import struct
import zlib


class UploadImageError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _invalid() -> None:
    raise UploadImageError("invalid_image")


def _png(data: bytes) -> tuple[bytes, int, int]:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        _invalid()
    pos, output, width, height, seen_idat, ended = 8, bytearray(data[:8]), 0, 0, False, False
    keep = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP", b"bKGD", b"pHYs", b"sBIT"}
    while pos + 12 <= len(data):
        size = int.from_bytes(data[pos:pos + 4], "big")
        kind = data[pos + 4:pos + 8]
        end = pos + 12 + size
        if end > len(data) or not all(65 <= x <= 90 or 97 <= x <= 122 for x in kind):
            _invalid()
        chunk = data[pos:end]
        if zlib.crc32(chunk[4:-4]) != int.from_bytes(chunk[-4:], "big"):
            _invalid()
        if pos == 8:
            if kind != b"IHDR" or size != 13:
                _invalid()
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", chunk[8:-4])
            if not width or not height or (depth, color) not in {
                (1, 0), (2, 0), (4, 0), (8, 0), (16, 0), (8, 2), (16, 2),
                (1, 3), (2, 3), (4, 3), (8, 3), (8, 4), (16, 4), (8, 6), (16, 6),
            } or compression or filtering or interlace not in (0, 1):
                _invalid()
        elif kind == b"IHDR" or (kind[0] & 32 == 0 and kind not in keep):
            _invalid()
        if kind == b"IDAT":
            seen_idat = True
        if kind == b"IEND":
            if size or not seen_idat or end != len(data):
                _invalid()
            ended = True
        if kind in keep:
            output.extend(chunk)
        pos = end
        if ended:
            break
    if not ended:
        _invalid()
    return bytes(output), width, height


_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def _jpeg(data: bytes) -> tuple[bytes, int, int]:
    if not data.startswith(b"\xff\xd8"):
        _invalid()
    out = bytearray(data[:2])
    pos, width, height, seen_scan = 2, 0, 0, False
    while pos < len(data):
        if data[pos] != 0xFF:
            _invalid()
        start = pos
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        if pos >= len(data):
            _invalid()
        marker = data[pos]
        pos += 1
        if marker == 0xD9:
            if not seen_scan or pos != len(data):
                _invalid()
            out.extend(b"\xff\xd9")
            return bytes(out), width, height
        if marker == 0x00 or marker == 0xD8 or 0xD0 <= marker <= 0xD7:
            _invalid()
        if pos + 2 > len(data):
            _invalid()
        size = int.from_bytes(data[pos:pos + 2], "big")
        end = pos + size
        if size < 2 or end > len(data):
            _invalid()
        segment = data[start:end]
        if marker in _SOF:
            if size < 8 or width:
                _invalid()
            height, width = struct.unpack(">HH", data[pos + 3:pos + 7])
            if not width or not height:
                _invalid()
        if not (0xE1 <= marker <= 0xEF or marker == 0xFE):
            out.extend(segment)
        pos = end
        if marker == 0xDA:
            if not width:
                _invalid()
            seen_scan = True
            scan_start = pos
            while pos < len(data):
                if data[pos] != 0xFF:
                    pos += 1
                    continue
                next_pos = pos + 1
                while next_pos < len(data) and data[next_pos] == 0xFF:
                    next_pos += 1
                if next_pos >= len(data):
                    _invalid()
                code = data[next_pos]
                if code == 0x00 or 0xD0 <= code <= 0xD7:
                    pos = next_pos + 1
                    continue
                out.extend(data[scan_start:pos])
                break
            else:
                _invalid()
    _invalid()


def _webp(data: bytes) -> tuple[bytes, int, int]:
    if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP" or int.from_bytes(data[4:8], "little") != len(data) - 8:
        _invalid()
    pos, chunks, width, height, image_seen, extended = 12, [], 0, 0, False, False
    while pos + 8 <= len(data):
        kind = data[pos:pos + 4]
        size = int.from_bytes(data[pos + 4:pos + 8], "little")
        end = pos + 8 + size + (size & 1)
        if end > len(data):
            _invalid()
        payload = data[pos + 8:pos + 8 + size]
        chunk = bytearray(data[pos:end])
        if kind == b"VP8X":
            if pos != 12 or size != 10 or extended or payload[0] & 0x02:
                _invalid()  # animated WebP is not a screenshot
            extended = True
            chunk[8] &= ~0x0C  # EXIF and XMP flags
            width = 1 + int.from_bytes(payload[4:7], "little")
            height = 1 + int.from_bytes(payload[7:10], "little")
        elif kind == b"VP8 ":
            if image_seen or size < 10 or payload[3:6] != b"\x9d\x01\x2a" or payload[0] & 1:
                _invalid()
            w = int.from_bytes(payload[6:8], "little") & 0x3FFF
            h = int.from_bytes(payload[8:10], "little") & 0x3FFF
            image_seen = True
            if not extended:
                width, height = w, h
        elif kind == b"VP8L":
            if image_seen or size < 5 or payload[0] != 0x2F or payload[4] & 0xE0:
                _invalid()
            bits = int.from_bytes(payload[1:5], "little")
            w, h = (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
            image_seen = True
            if not extended:
                width, height = w, h
        elif kind in {b"ANIM", b"ANMF"}:
            _invalid()
        if kind not in {b"EXIF", b"XMP "}:
            chunks.append(bytes(chunk))
        pos = end
    if pos != len(data) or not image_seen or not width or not height or (extended and (w > width or h > height)):
        _invalid()
    body = b"WEBP" + b"".join(chunks)
    return b"RIFF" + len(body).to_bytes(4, "little") + body, width, height


def clean_image(data: bytes, max_pixels: int) -> tuple[bytes, str, str, int, int]:
    """Return sanitized bytes, MIME type, extension and dimensions."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        cleaned, width, height = _png(data)
        mime, extension = "image/png", "png"
    elif data.startswith(b"\xff\xd8"):
        cleaned, width, height = _jpeg(data)
        mime, extension = "image/jpeg", "jpg"
    elif data.startswith(b"RIFF"):
        cleaned, width, height = _webp(data)
        mime, extension = "image/webp", "webp"
    else:
        raise UploadImageError("unsupported_image_type")
    if width * height > max_pixels:
        raise UploadImageError("image_too_large")
    return cleaned, mime, extension, width, height
