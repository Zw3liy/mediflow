"""Local-only OCR: patient documents never go to an external recognition service."""
import csv
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

from PIL import Image, ImageOps, ImageFilter, UnidentifiedImageError
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
        if field in {'email', 'mobile', 'address'} and re.search(r'medical certificate', text, re.I):
            label = r'patient\s+' + label
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


DOCUMENT_LABELS = {
    'Patient full name': r'(?:patient full name|full name)',
    'Practitioner name': r'(?:practitioner name|doctor name)',
    'Date of first consultation': r'date of first consultation',
    'Follow-up consultation date': r'(?:and again on|follow.up consultation date)',
    'Unfit for duty from': r'(?:unfit for duty from|from)',
    'Unfit for duty to': r'(?:unfit for duty to|to)',
    'Nature of illness or injury': r'nature of illness or injury',
    'Work can be resumed on': r'work can be resumed on',
    'Certificate date': r'certificate date',
    'Comments': r'comments',
}


def suggest_document_fields(text):
    """Copy readable labelled values verbatim; never substitute clinic contacts for patient data."""
    fields = [{'label': 'Document type', 'value': 'Medical certificate' if re.search(r'medical certificate', text, re.I) else ''}]
    for label, pattern in DOCUMENT_LABELS.items():
        values = re.findall(r'^\s*' + pattern + r'\s*[:=]\s*([^\n]+)', text, re.I | re.M)
        values = [re.sub(r'[_.]{2,}', '', value).strip() for value in values]
        values = [value for value in values if len(value) >= 2 and re.search(r'[A-Za-z0-9]', value)]
        fields.append({'label': label, 'value': values[0][:2000] if len(set(values)) == 1 else ''})
    return fields


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
                # Normalize low contrast photos without changing the retained original.
                image = ImageOps.autocontrast(ImageOps.grayscale(image), cutoff=1)
                if image.width < 1600 and image.height < 2200:
                    image = image.resize((image.width * 2, image.height * 2), Image.Resampling.LANCZOS)
                image = image.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=3))
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValidationError('The image is damaged or too large. Take another photo.') from error
    with tempfile.TemporaryDirectory(prefix='mediflow-ocr-') as directory:
        input_path = Path(directory) / 'input.png'
        output = Path(directory) / 'scan'
        image.save(input_path)
        candidates = []
        for mode in ('3', '6'):
            output = Path(directory) / ('scan-' + mode)
            try:
                subprocess.run(['tesseract', str(input_path), str(output), '-l', 'eng', '--psm', mode, 'txt', 'pdf', 'tsv'],
                               check=True, timeout=15, capture_output=True, env=None)
                text = output.with_suffix('.txt').read_text(encoding='utf-8')[:100_000]
                with output.with_suffix('.tsv').open(encoding='utf-8') as stream:
                    words = [(float(row['conf']), len(row['text'])) for row in csv.DictReader(stream, delimiter='\t')
                             if row.get('text', '').strip() and float(row['conf']) >= 0]
                # Prefer confidently recognised characters, rather than a longer garbled result.
                score = sum((confidence - 40) * min(length, 20) for confidence, length in words)
                candidates.append((score, text, output.with_suffix('.pdf').read_bytes()))
            except (OSError, ValueError, KeyError, subprocess.SubprocessError):
                continue
        if not candidates:
            raise OCRUnavailable('Text recognition could not finish. Try a clearer photo.')
        _, text, pdf = max(candidates, key=lambda candidate: candidate[0])
    return {'original': content, 'content_type': content_type, 'sha256': hashlib.sha256(content).hexdigest(),
            'pdf': pdf, 'text': text, 'suggestions': suggest_patient_details(text),
            'document_fields': suggest_document_fields(text)}
