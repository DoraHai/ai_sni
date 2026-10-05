"""Pure Python image fixtures exercise validation and metadata removal."""

import struct
import zlib

import pytest

from app.seo_capture_upload import UploadImageError, clean_image
from app.seo_page_capture import capture_storage_path


def chunk(kind, payload):
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def png(width=2, height=3, metadata=True):
    header = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    text = b"".join(chunk(kind, b"secret") for kind in (b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"tIME")) if metadata else b""
    pixels = chunk(b"IDAT", zlib.compress((b"\x00" + b"\x00" * (width * 3)) * min(height, 3)))
    return b"\x89PNG\r\n\x1a\n" + header + text + pixels + chunk(b"IEND", b"")


def jpeg(width=2, height=3, metadata=True):
    def segment(marker, payload):
        return b"\xff" + bytes([marker]) + struct.pack(">H", len(payload) + 2) + payload
    meta = (segment(0xE1, b"Exif\x00\x00secret") + segment(0xE2, b"XMP secret") +
            segment(0xFE, b"comment")) if metadata else b""
    huffman = lambda table: bytes([table]) + b"\x01" + b"\x00" * 15 + b"\x00"
    return (b"\xff\xd8" + segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00") + meta +
            segment(0xDB, b"\x00" + b"\x01" * 64) +
            segment(0xC0, b"\x08" + struct.pack(">HH", height, width) + b"\x01\x01\x11\x00") +
            segment(0xC4, huffman(0x00) + huffman(0x10)) +
            segment(0xDA, b"\x01\x01\x00\x00\x3f\x00") + b"\x3f\xff\xd9")


def webp(width=2, height=3, metadata=True, extended=True, lossless=False):
    def little3(value):
        return value.to_bytes(3, "little")
    def riff_chunk(kind, payload):
        return kind + struct.pack("<I", len(payload)) + payload + (b"\x00" if len(payload) & 1 else b"")
    header = riff_chunk(b"VP8X", b"\x0c\x00\x00\x00" + little3(width - 1) + little3(height - 1)) if extended else b""
    if lossless:
        bits = (width - 1) | ((height - 1) << 14)
        image = riff_chunk(b"VP8L", b"\x2f" + bits.to_bytes(4, "little"))
    else:
        image = riff_chunk(b"VP8 ", b"\x00\x00\x00\x9d\x01\x2a" + struct.pack("<HH", width, height))
    meta = riff_chunk(b"EXIF", b"secret") + riff_chunk(b"XMP ", b"private") if metadata else b""
    body = b"WEBP" + header + image + meta
    return b"RIFF" + struct.pack("<I", len(body)) + body


@pytest.mark.parametrize("fixture,mime,extension", [
    (png, "image/png", "png"), (jpeg, "image/jpeg", "jpg"),
    (webp, "image/webp", "webp"),
    (lambda: webp(lossless=True), "image/webp", "webp"),
])
def test_dimensions_and_metadata_removal(fixture, mime, extension):
    cleaned, actual_mime, actual_extension, width, height = clean_image(fixture(), 100)
    assert (actual_mime, actual_extension, width, height) == (mime, extension, 2, 3)
    assert b"secret" not in cleaned and b"private" not in cleaned
    assert clean_image(cleaned, 100) == (cleaned, mime, extension, 2, 3)
    if mime == "image/webp":
        assert int.from_bytes(cleaned[4:8], "little") == len(cleaned) - 8
        if cleaned[12:16] == b"VP8X":
            assert cleaned[20] & 0x0C == 0
    if mime == "image/jpeg":
        assert b"JFIF" in cleaned and b"Exif" not in cleaned


@pytest.mark.parametrize("data,code", [
    (b"GIF89a", "unsupported_image_type"),
    (png()[:-3], "invalid_image"),
    (png()[:35] + b"x" + png()[36:], "invalid_image"),
    (jpeg()[:-2], "invalid_image"),
    (webp()[:-1], "invalid_image"),
    (png(100, 100), "image_too_large"),
])
def test_rejections(data, code):
    with pytest.raises(UploadImageError) as exc:
        clean_image(data, 100)
    assert exc.value.code == code


def test_storage_keys_are_flat_and_format_specific(tmp_path, monkeypatch):
    from app import seo_page_capture
    monkeypatch.setattr(seo_page_capture, "__file__", "C:/outside/app/seo_page_capture.py")
    for extension in ("png", "jpg", "webp"):
        key = "a" * 32 + "." + extension
        assert capture_storage_path(str(tmp_path), key).parent == tmp_path.resolve()
    for key in ("../secret.png", "a" * 32 + ".svg", "a" * 32 + ".png/../evil"):
        with pytest.raises(ValueError):
            capture_storage_path(str(tmp_path), key)
