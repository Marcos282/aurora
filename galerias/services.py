import uuid
import warnings
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image, ImageOps, UnidentifiedImageError


def store_photo(upload) -> str:
    if upload.size > 5 * 1024 * 1024:
        raise ValidationError("A foto deve ter ate 5 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(upload) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"} or image.width * image.height > 20_000_000:
                    raise ValidationError("Use JPEG, PNG ou WebP de ate 20 megapixels.")
                image.load()
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((1600, 1600))
                output = BytesIO()
                image.save(output, "WEBP", quality=82, method=4)
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValidationError("Imagem invalida ou excessivamente grande.") from exc
    return default_storage.save("photos/" + uuid.uuid4().hex + ".webp", ContentFile(output.getvalue()))
