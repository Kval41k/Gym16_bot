"""Shared log redaction and strict decoding of user-supplied raster images."""
import io
import logging
import re
import warnings
import csv
import traceback
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from config import settings


def redact(value):
    if not isinstance(value, str):
        return value
    for secret in (settings.BOT_TOKEN, settings.DATABASE_URL, settings.BOT_STORAGE_URL):
        if secret:
            value = value.replace(secret, "[REDACTED]")
    value = re.sub(r"bot\d{6,12}:[A-Za-z0-9_-]+", "bot[REDACTED]", value)
    return re.sub(r"([?&](?:sign|hash|token)=)[^&\s]+", r"\1[REDACTED]", value, flags=re.I)


def install_log_redaction():
    old_factory = logging.getLogRecordFactory()
    if getattr(old_factory, "gym16_redaction", False):
        return
    def factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        record.msg = redact(str(record.msg))
        if isinstance(record.args, dict):
            record.args = {key: redact(value if isinstance(value, (str, int, float, bool, type(None))) else str(value)) for key, value in record.args.items()}
        elif isinstance(record.args, tuple):
            record.args = tuple(redact(value if isinstance(value, (str, int, float, bool, type(None))) else str(value)) for value in record.args)
        if record.exc_info:
            record.exc_text = redact(''.join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return record
    factory.gym16_redaction = True
    logging.setLogRecordFactory(factory)


def clean_image(content):
    """Decode and re-encode: reject faked signatures, remove EXIF and active metadata."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as source:
                if source.width * source.height > 20_000_000 or max(source.size) > 10000:
                    raise ValueError("Изображение слишком большое. Уменьшите его до 20 мегапикселей.")
                if source.format not in {"JPEG", "PNG", "WEBP", "GIF", "BMP"}:
                    raise ValueError("Используйте JPEG, PNG или WebP. HEIC сначала преобразуйте в JPEG.")
                source.verify()
            with Image.open(io.BytesIO(content)) as source:
                image = ImageOps.exif_transpose(source)
                output = io.BytesIO()
                if "A" in image.getbands() or (image.mode == "P" and "transparency" in image.info):
                    clean = image.convert("RGBA")
                    clean.info.clear()
                    clean.save(output, format="PNG")
                    return output.getvalue(), "png"
                clean = image.convert("RGB")
                clean.info.clear()
                clean.save(output, format="JPEG", quality=90)
                return output.getvalue(), "jpg"
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Файл повреждён или не является допустимым изображением.") from exc


def csv_cell(value):
    if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


class SafeCSVWriter:
    def __init__(self, stream):
        self.writer = csv.writer(stream)
    def writerow(self, row):
        return self.writer.writerow([csv_cell(value) for value in row])


def safe_csv_writer(stream):
    return SafeCSVWriter(stream)


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"}:
            return await self.app(scope, receive, send)
        limit = 11 * 1024 * 1024 if scope["path"] == "/api/upload" else 512 * 1024
        headers = dict(scope.get("headers", []))
        if b"content-length" in headers:
            try:
                size = int(headers[b"content-length"])
                if size < 0:
                    raise ValueError()
            except ValueError:
                return await JSONResponse({"detail": "Некорректный размер запроса"}, 400)(scope, receive, send)
            if size > limit:
                return await JSONResponse({"detail": "Запрос слишком большой"}, 413)(scope, receive, send)
        total = 0
        exceeded = False
        response_started = False
        async def bounded_send(message):
            nonlocal response_started
            if exceeded:
                if not response_started:
                    response_started = True
                    await JSONResponse({"detail": "Запрос слишком большой"}, 413)(scope, receive, send)
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)
        async def bounded_receive():
            nonlocal total, exceeded
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    exceeded = True
                    raise HTTPException(413, "Запрос слишком большой")
            return message
        try:
            await self.app(scope, bounded_receive, bounded_send)
        except HTTPException as error:
            if error.status_code != 413:
                raise
            if not response_started:
                await JSONResponse({"detail": "Запрос слишком большой"}, 413)(scope, receive, send)


install_log_redaction()
