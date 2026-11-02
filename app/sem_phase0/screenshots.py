"""只处理本地PNG/JPEG字节；不访问图片内URL，不调用OCR。"""
from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass
from pathlib import PurePath

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 30 * 1024 * 1024
MAX_IMAGES = 10
MAX_PIXELS = 20_000_000
MAX_EDGE = 10_000


@dataclass(frozen=True)
class Screenshot:
    landing_page_id: str
    filename: str
    content_type: str
    data: bytes


def clean_screenshot(item: Screenshot) -> tuple[bytes, dict]:
    # Optional dependency only needed when accepting screenshots, never at app startup.
    from PIL import Image, ImageOps, UnidentifiedImageError

    suffix = PurePath(item.filename).suffix.lower()
    expected = {".png": ("PNG", "image/png"), ".jpg": ("JPEG", "image/jpeg"),
                ".jpeg": ("JPEG", "image/jpeg")}.get(suffix)
    if not expected or expected[1] != item.content_type or not 0 < len(item.data) <= MAX_IMAGE_BYTES:
        raise ValueError("截图类型/MIME/大小不符合内部输入契约")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(item.data)) as image:
                if (image.format != expected[0] or getattr(image, "n_frames", 1) != 1
                        or image.width * image.height > MAX_PIXELS
                        or max(image.size) > MAX_EDGE):
                    raise ValueError("截图签名、帧数或像素限制不符合契约")
                image.verify()
            with Image.open(io.BytesIO(item.data)) as image:
                image.load()
                displayed = ImageOps.exif_transpose(image)
                # New pixel-only image drops EXIF/GPS/ICC/comments/text metadata.
                pixels = displayed.convert("RGBA" if displayed.mode == "RGBA" else "RGB")
                clean = Image.new(pixels.mode, pixels.size)
                clean.paste(pixels)
                out = io.BytesIO()
                clean.save(out, format="PNG")
                data = out.getvalue()
                if len(data) > MAX_IMAGE_BYTES:
                    raise ValueError("清洗截图超限，请裁剪后重交")
                return data, {"original_sha256": hashlib.sha256(item.data).hexdigest(),
                              "clean_sha256": hashlib.sha256(data).hexdigest(),
                              "width": clean.width, "height": clean.height,
                              "mime": "image/png", "ocr_status": "not_connected"}
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError,
            Image.DecompressionBombWarning):
        raise ValueError("截图无法安全解码，请重交PNG/JPEG") from None
