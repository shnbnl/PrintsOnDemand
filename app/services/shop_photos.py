"""Validate and normalize small, public shop images before database storage."""

from hashlib import sha256
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.datastructures import FileStorage


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_STORED_BYTES = 2 * 1024 * 1024
MAX_SOURCE_PIXELS = 20_000_000
MAX_SIDE = 1024
ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP"}


class ShopPhotoError(ValueError):
    pass


def normalize_shop_photo(upload: FileStorage) -> tuple[bytes, str, str]:
    raw = upload.stream.read(MAX_UPLOAD_BYTES + 1)
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise ShopPhotoError("Choose an image smaller than 5 MB.")
    try:
        with Image.open(BytesIO(raw)) as source:
            if source.format not in ACCEPTED_FORMATS:
                raise ShopPhotoError("Choose a JPEG, PNG, or WebP image.")
            if source.width * source.height > MAX_SOURCE_PIXELS:
                raise ShopPhotoError("Choose an image smaller than 20 megapixels.")
            source.verify()
        with Image.open(BytesIO(raw)) as source:
            source.seek(0)
            image = ImageOps.exif_transpose(source)
            image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
            output = BytesIO()
            if "A" in image.getbands():
                image.convert("RGBA").save(output, format="PNG", optimize=True)
                mime = "image/png"
            else:
                image.convert("RGB").save(output, format="JPEG", quality=82, optimize=True)
                mime = "image/jpeg"
    except ShopPhotoError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as error:
        raise ShopPhotoError("Choose a valid JPEG, PNG, or WebP image.") from error
    result = output.getvalue()
    if len(result) > MAX_STORED_BYTES:
        raise ShopPhotoError("The processed image is too large; choose a smaller image.")
    return result, mime, sha256(result).hexdigest()
