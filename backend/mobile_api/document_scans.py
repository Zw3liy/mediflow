"""Reception-only scanning and reviewed patient updates for the native app."""
import base64
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from auditlog.services import record_audit_event
from documents.models import PatientDocumentScan
from documents.ocr import OCRUnavailable, recognize_image, suggest_document_fields
from documents.storage import DocumentStorageError, get_document_storage
from patients.models import Patient
from .views import MobileBase

FIELDS = ('file_number', 'given_name', 'family_name', 'date_of_birth', 'mobile', 'email', 'address')


class ScanUnavailable(APIException):
    status_code = 503
    default_detail = 'Document scanning is temporarily unavailable. Try again shortly.'


class ReviewedPatientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = FIELDS
        validators = []  # Practice + file uniqueness is checked within the save transaction.

    def validate_date_of_birth(self, value):
        if value and value > timezone.localdate():
            raise serializers.ValidationError('Date of birth cannot be in the future.')
        return value


class DocumentFieldSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=100)
    value = serializers.CharField(max_length=2000, allow_blank=True)


class ReviewSerializer(serializers.Serializer):
    document_fields = DocumentFieldSerializer(many=True, required=False, max_length=50)
    confirmed = serializers.BooleanField()
    patient_id = serializers.UUIDField(required=False, allow_null=True)
    expected_patient_updated_at = serializers.DateTimeField(required=False)
    patient_details = ReviewedPatientSerializer()
    title = serializers.CharField(max_length=160)
    reviewed_text = serializers.CharField(max_length=100_000, allow_blank=True)

    def validate_confirmed(self, value):
        if not value:
            raise serializers.ValidationError('Review and confirm the patient details before saving.')
        return value


def scan_info(scan):
    return {'id': str(scan.pk), 'title': scan.title, 'patient_id': str(scan.patient_id) if scan.patient_id else None,
            'extracted_text': scan.extracted_text, 'reviewed_text': scan.reviewed_text,
            'suggestions': scan.suggestions, 'document_fields': scan.document_fields, 'reviewed_at': scan.reviewed_at,
            'created_at': scan.created_at}


class StaffScanBase(MobileBase):
    def check_staff(self, request):
        self.roles(request, ['owner', 'reception'])

    def get_scan(self, request, pk, *, lock=False):
        queryset = PatientDocumentScan.objects.filter(practice=request.auth.practice)
        if lock:
            queryset = queryset.select_for_update()
        scan = get_object_or_404(queryset, pk=pk)
        if scan.reviewed_at is None and scan.created_at < timezone.now() - timedelta(hours=24):
            raise ValidationError('This draft has expired. Please scan the document again.')
        return scan


class MobileDocumentScans(StaffScanBase):
    throttle_classes = [ScopedRateThrottle]

    def get_throttles(self):
        self.throttle_scope = 'document_scan' if self.request.method == 'POST' else None
        return super().get_throttles()

    def get(self, request):
        self.check_staff(request)
        patients = Patient.objects.filter(practice=request.auth.practice, active=True).order_by('family_name', 'given_name')
        return Response({'patients': [dict(ReviewedPatientSerializer(p).data, id=str(p.pk),
                                  name=f'{p.given_name} {p.family_name} · {p.file_number}', updated_at=p.updated_at) for p in patients[:500]],
                         'drafts': [scan_info(s) for s in PatientDocumentScan.objects.filter(
                             practice=request.auth.practice, reviewed_at__isnull=True,
                             created_at__gte=timezone.now() - timedelta(hours=24)).order_by('-created_at')[:100]],
                         'documents': [scan_info(s) for s in PatientDocumentScan.objects.filter(
                             practice=request.auth.practice, reviewed_at__isnull=False).order_by('-created_at')[:100]]})

    def post(self, request):
        self.check_staff(request)
        try:
            output = recognize_image(request.data.get('image_base64'))
        except OCRUnavailable as error:
            raise ScanUnavailable(str(error)) from error
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        scan = PatientDocumentScan(practice=request.auth.practice, uploaded_by=request.user,
            original_content_type=output['content_type'], original_sha256=output['sha256'],
            extracted_text=output['text'], reviewed_text=output['text'], suggestions=output['suggestions'],
            document_fields=output.get('document_fields', suggest_document_fields(output['text'])))
        prefix = f'practices/{scan.practice_id}/patient-scans/{scan.pk}/'
        scan.original_key = prefix + ('original.jpg' if output['content_type'] == 'image/jpeg' else 'original.png')
        scan.pdf_key = prefix + 'searchable.pdf'
        storage = get_document_storage()
        try:
            storage.save(object_key=scan.original_key, content=output['original'])
            storage.save(object_key=scan.pdf_key, content=output['pdf'])
            with transaction.atomic():
                scan.save()
                record_audit_event(practice=scan.practice, actor=request.user, action='patient_document.scanned',
                    object_type='patient_document_scan', object_id=scan.pk, purpose='Create private document review draft', outcome='success')
        except Exception as error:
            for key in (scan.original_key, scan.pdf_key):
                try:
                    storage.delete(object_key=key)
                except DocumentStorageError:
                    pass
            if isinstance(error, DocumentStorageError):
                raise ScanUnavailable() from error
            raise
        return Response(scan_info(scan), status=201)


class MobileDocumentScanReview(StaffScanBase):
    def get(self, request, pk):
        self.check_staff(request)
        return Response(scan_info(self.get_scan(request, pk)))

    def post(self, request, pk):
        self.check_staff(request)
        serializer = ReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            with transaction.atomic():
                scan = self.get_scan(request, pk, lock=True)
                if scan.reviewed_at is not None:
                    return Response(scan_info(scan))  # Retry cannot update demographics twice.
                patient_id = values.get('patient_id')
                patient = get_object_or_404(Patient.objects.select_for_update(), pk=patient_id,
                    practice=request.auth.practice, active=True) if patient_id else Patient(practice=request.auth.practice)
                if patient_id and values.get('expected_patient_updated_at') != patient.updated_at:
                    raise ValidationError('This patient record changed. Refresh the patient details and review again before saving.')
                if Patient.objects.filter(practice=request.auth.practice, file_number=values['patient_details']['file_number']).exclude(pk=patient.pk).exists():
                    raise ValidationError({'file_number': 'This file number already exists. Select that patient or use another number.'})
                changed = []
                for field, value in values['patient_details'].items():
                    if getattr(patient, field) != value:
                        changed.append(field)
                    setattr(patient, field, value)
                patient.full_clean()
                patient.save()
                scan.patient = patient
                scan.title = values['title']
                scan.reviewed_text = values['reviewed_text']
                scan.document_fields = values.get('document_fields', [])
                scan.reviewed_by = request.user
                scan.reviewed_at = timezone.now()
                scan.save(update_fields=['patient', 'title', 'reviewed_text', 'document_fields', 'reviewed_by', 'reviewed_at'])
                record_audit_event(practice=scan.practice, actor=request.user, action='patient_document.reviewed',
                    object_type='patient_document_scan', object_id=scan.pk,
                    purpose='Approve scan and patient demographics', outcome='success',
                    metadata={'patient_id': str(patient.pk), 'changed_fields': changed})
        except IntegrityError as error:
            raise ValidationError('This file number already exists. Select the existing patient.') from error
        except DjangoValidationError as error:
            raise ValidationError(error.message_dict if hasattr(error, 'message_dict') else error.messages) from error
        return Response(scan_info(scan))

    def delete(self, request, pk):
        self.check_staff(request)
        with transaction.atomic():
            scan = self.get_scan(request, pk, lock=True)
            if scan.reviewed_at:
                raise ValidationError('Saved patient documents cannot be discarded as drafts.')
            try:
                storage = get_document_storage()
                storage.delete(object_key=scan.original_key)
                storage.delete(object_key=scan.pdf_key)
            except DocumentStorageError as error:
                raise ScanUnavailable() from error
            record_audit_event(practice=scan.practice, actor=request.user, action='patient_document.discarded',
                object_type='patient_document_scan', object_id=scan.pk, purpose='Discard unreviewed scan', outcome='success')
            scan.delete()
        return Response(status=204)


class MobileDocumentScanDownload(StaffScanBase):
    def get(self, request, pk, kind):
        self.check_staff(request)
        scan = self.get_scan(request, pk)
        if kind not in {'original', 'pdf'}:
            raise ValidationError('Choose original or pdf.')
        key = scan.original_key if kind == 'original' else scan.pdf_key
        try:
            content = get_document_storage().read(object_key=key)
        except DocumentStorageError as error:
            raise ScanUnavailable() from error
        record_audit_event(practice=scan.practice, actor=request.user, action='patient_document.downloaded',
            object_type='patient_document_scan', object_id=scan.pk, purpose='Review scanned patient document', outcome='success', metadata={'kind': kind})
        return Response({'base64': base64.b64encode(content).decode('ascii'),
                         'content_type': scan.original_content_type if kind == 'original' else 'application/pdf'})
