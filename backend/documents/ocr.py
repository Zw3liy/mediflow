"""Local-only OCR: patient documents never go to an external recognition service."""
import base64
import binascii
import hashlib
import io
import re
import subprocess
import tempfile
import warnings
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from .scanning import CLEAN_RESULT, get_document_scanner

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000


class OCRUnavailable(Exception):
    pass


def suggest_patient_details(text):
    """Only labelled, unambiguous demographic fields; never infer clinical facts."""
    labels = {
        'given_name': r'(?:given name|first name|forenames)',
        'family_name': r'(?:family name|last name|surname)',
        'file_number': r'(?:file number|patient number)',
        'mobile': r'(?:mobile|cell(?:phone)?|phone|telephone)(?: number)?',
        'email': r'(?:e-?mail)(?: address)?',
        'address': r'(?:residential address|street address|address)',
        'date_of_birth': r'(?:date of birth|dob|birth date)',
    }
    limits = {'given_name': 100, 'family_name': 100, 'file_number': 32, 'mobile': 32, 'email': 254, 'address': 500}
    result = {}
    for field, label in labels.items():
        values = re.findall(r'^\s*' + label + r'\s*[:=]\s*(.+?)\s*$', text, re.I | re.M)
        if len(set(values)) != 1:
            continue
        value = values[0].strip()
        if field == 'date_of_birth':
            # Numerical dates with ambiguous day/month order are deliberately left for review.
            formats = ['%Y-%m-%d', '%d %B %Y', '%d %b %Y']
            if re.fullmatch(r'\d{1,2}/\d{1,2}/\d{4}', value) and int(value.split('/')[0]) > 12:
                formats.append('%d/%m/%Y')
            for fmt in formats:
                try:
                    value = datetime.strptime(value, fmt).date().isoformat()
                    result[field] = value
                    break
                except ValueError:
                    continue
        elif field == 'email':
            try:
                validate_email(value)
                result[field] = value
            except ValidationError:
                pass
        elif len(value) <= limits[field]:
            result[field] = value
    return result


def recognize_image(encoded):
    if not isinstance(encoded, str) or not encoded or len(encoded) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
        raise ValidationError('Choose a JPEG or PNG image no larger than 8 MB.')
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValidationError('Invalid image upload.') from error
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise ValidationError('Choose an image no larger than 8 MB.')
    try:
        # Fail closed: OCR never parses a file before malware checking succeeds.
        if get_document_scanner().scan(content=content) != CLEAN_RESULT:
            raise ValidationError('This document failed the file safety check. Choose another image.')
    except ValidationError:
        raise
    except Exception as error:
        raise OCRUnavailable('File safety checking is unavailable. Try again shortly.') from error
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as source:
                if source.format not in {'JPEG', 'PNG'} or source.width * source.height > MAX_IMAGE_PIXELS or getattr(source, 'n_frames', 1) != 1:
                    raise ValidationError('Choose a single JPEG or PNG image up to 20 megapixels.')
                content_type = Image.MIME[source.format]
                source.load()
                image = ImageOps.exif_transpose(source).convert('RGB')
                image.thumbnail((2400, 3200))
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValidationError('The image is damaged or too large. Take another photo.') from error
    with tempfile.TemporaryDirectory(prefix='mediflow-ocr-') as directory:
        input_path = Path(directory) / 'input.png'
        output = Path(directory) / 'scan'
        image.save(input_path)
        try:
            subprocess.run(['tesseract', str(input_path), str(output), '-l', 'eng', '--psm', '3', 'txt', 'pdf'],
                           check=True, timeout=20, capture_output=True, env=None)
            text = output.with_suffix('.txt').read_text(encoding='utf-8')[:100_000]
            pdf = output.with_suffix('.pdf').read_bytes()
        except (OSError, subprocess.SubprocessError) as error:
            raise OCRUnavailable('Text recognition could not finish. Try a clearer photo.') from error
    return {'original': content, 'content_type': content_type, 'sha256': hashlib.sha256(content).hexdigest(),
            'pdf': pdf, 'text': text, 'suggestions': suggest_patient_details(text)}
