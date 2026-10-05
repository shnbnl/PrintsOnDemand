"""Shop-owned payment QR image handling.

The generated initial image is a distinct, non-scannable development placeholder.
Shops must replace it with their actual payment QR before accepting transfers.
It is stored in the database, never in a public upload directory.
"""

from hashlib import sha256
from io import BytesIO
from random import Random

from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 20_000_000


class PaymentQRError(ValueError):
    pass


def development_qr(name: str) -> tuple[bytes, str, str]:
    """Create a unique visual stand-in; no payment data is encoded."""
    random = Random(int(sha256(name.encode("utf-8")).hexdigest(), 16))
    size = 25
    image = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(image)
    for y in range(size):
        for x in range(size):
            if random.randrange(3) == 0:
                draw.point((x, y), fill="#09284d")
    image = image.resize((300, 300), Image.Resampling.NEAREST)
    output = BytesIO()
    image.save(output, format="PNG")
    data = output.getvalue()
    return data, "image/png", sha256(data).hexdigest()


def normalize_payment_qr(upload) -> tuple[bytes, str, str]:
    raw = upload.stream.read(MAX_UPLOAD_BYTES + 1)
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise PaymentQRError("Choose an image smaller than 5 MB.")
    try:
        with Image.open(BytesIO(raw)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP"}:
                raise PaymentQRError("Choose a PNG, JPEG, or WebP image.")
            if source.width * source.height > MAX_PIXELS:
                raise PaymentQRError("Choose an image smaller than 20 megapixels.")
            source.verify()
        with Image.open(BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            output = BytesIO()
            if "A" in image.getbands():
                image.convert("RGBA").save(output, format="PNG", optimize=True)
                mime = "image/png"
            else:
                image.convert("RGB").save(output, format="PNG", optimize=True)
                mime = "image/png"
    except PaymentQRError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as error:
        raise PaymentQRError("Choose a valid PNG, JPEG, or WebP image.") from error
    data = output.getvalue()
    if len(data) > 2 * 1024 * 1024:
        raise PaymentQRError("The processed image is too large; choose a smaller image.")
    return data, mime, sha256(data).hexdigest()
