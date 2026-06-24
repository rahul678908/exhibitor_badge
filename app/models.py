from django.contrib.auth.models import AbstractUser
from django.db import models

# ==========================
# User Model
# ==========================



class User(AbstractUser):

    ROLE_CHOICES = (
        ("admin", "Admin"),
        ("exhibitor", "Exhibitor"),
    )

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES
    )

    phone = models.CharField(
        max_length=20,
        blank=True,
        null=True
    )

    def __str__(self):
        return self.username

# ==========================
# Exhibitor
# ==========================

class Exhibitor(models.Model):

    STATUS_CHOICES = (
        ("active", "Active"),
        ("inactive", "Inactive"),
    )

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="exhibitor_profile"
    )

    company_name = models.CharField(max_length=255)

    contact_person = models.CharField(max_length=255)

    contact_email = models.EmailField()

    contact_phone = models.CharField(max_length=20)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="active"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    @property
    def total_allocated_badges(self):
        return (
            self.badge_allocations.aggregate(
                total=models.Sum("allocated_count")
            )["total"]
            or 0
        )

    @property
    def total_used_badges(self):
        return self.registrations.filter(
            status="confirmed"
        ).count()

    @property
    def available_badges(self):
        return (
            self.total_allocated_badges
            - self.total_used_badges
        )

    def __str__(self):
        return self.company_name

# ==========================
# Ticket Types
# ==========================

class TicketType(models.Model):

    STATUS_CHOICES = (
        ("active", "Active"),
        ("inactive", "Inactive"),
    )

    ticket_name = models.CharField(
        max_length=100
    )

    ticket_code = models.CharField(
        max_length=50,
        unique=True
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    total_tickets = models.PositiveIntegerField(
        default=0
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="active"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return self.ticket_name

# ==========================
# Registration
# ==========================

import uuid


class Registration(models.Model):

    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("invited", "Invited"),
        ("pending", "Pending"),
        ("confirmed", "Confirmed"),
        ("cancelled", "Cancelled"),
    )

    REGISTERED_VIA = (
        ("single_badge", "Single Badge"),
        ("bulk_upload", "Bulk Upload"),
        ("invitation", "Invitation"),
    )

    exhibitor = models.ForeignKey(
        Exhibitor,
        on_delete=models.CASCADE,
        related_name="registrations"
    )

    ticket_type = models.ForeignKey(
        TicketType,
        on_delete=models.PROTECT
    )

    # Tracks which bulk upload batch committed this registration.
    # Null for single_badge and invitation registrations.
    upload_batch = models.ForeignKey(
        "UploadBatch",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="committed_registrations",
    )

    urn = models.CharField(
        max_length=50,
        unique=True,
        blank=True
    )

    first_name = models.CharField(
        max_length=100
    )

    last_name = models.CharField(
        max_length=100
    )

    email = models.EmailField(
        unique=True
    )

    job_title = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    company_name = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    phone_number = models.CharField(
        max_length=30,
        blank=True,
        null=True
    )

    country_of_residence = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    nationality = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    terms_accepted = models.BooleanField(
        default=False
    )

    registered_via = models.CharField(
        max_length=30,
        choices=REGISTERED_VIA
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending"
    )

    is_deleted = models.BooleanField(
        default=False
    )

    deleted_at = models.DateTimeField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def save(self, *args, **kwargs):

        is_new = self.pk is None

        super().save(*args, **kwargs)

        if is_new and not self.urn:
            self.urn = f"GF2026-{self.id:06d}"

            Registration.objects.filter(
                pk=self.pk
            ).update(
                urn=self.urn
            )

    def __str__(self):
        return f"{self.first_name} {self.last_name}"
# ==========================
# Invitations
# ==========================

from django.conf import settings
from django.utils.crypto import get_random_string


class Invitation(models.Model):

    STATUS_CHOICES = (
        ("sent", "Sent"),
        ("opened", "Opened"),
        ("completed", "Completed"),
        ("expired", "Expired"),
    )

    registration = models.OneToOneField(
        Registration,
        on_delete=models.CASCADE,
        related_name="invitation"
    )

    token = models.CharField(
        max_length=100,
        unique=True
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="sent"
    )

    sent_at = models.DateTimeField(
        auto_now_add=True
    )

    opened_at = models.DateTimeField(
        null=True,
        blank=True
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True
    )

    def save(self, *args, **kwargs):

        if not self.token:
            self.token = get_random_string(40)

        super().save(*args, **kwargs)

    @property
    def invitation_link(self):

        return (
            f"{settings.FRONTEND_URL}"
            f"/register/{self.token}"
        )

    def __str__(self):
        return self.registration.email

# ==========================
# Badge Allocation
# ==========================

class BadgeAllocation(models.Model):

    exhibitor = models.ForeignKey(
        Exhibitor,
        on_delete=models.CASCADE,
        related_name="badge_allocations"
    )

    ticket_type = models.ForeignKey(
        TicketType,
        on_delete=models.CASCADE
    )

    allocated_count = models.PositiveIntegerField()

    allocated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True
    )

    remarks = models.TextField(
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        unique_together = (
            "exhibitor",
            "ticket_type"
        )

    @property
    def used_count(self):

        return Registration.objects.filter(
            exhibitor=self.exhibitor,
            ticket_type=self.ticket_type,
            status="confirmed"
        ).count()

    @property
    def available_count(self):

        return (
            self.allocated_count
            - self.used_count
        )

    def __str__(self):
        return (
            f"{self.exhibitor.company_name}"
            f" - {self.ticket_type.ticket_name}"
        )

# ==========================
# Upload Batch
# ==========================

class UploadBatch(models.Model):

    STATUS_CHOICES = (
        ("uploaded", "Uploaded"),
        ("processing", "Processing"),
        ("validated", "Validated"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    )

    exhibitor = models.ForeignKey(
        Exhibitor,
        on_delete=models.CASCADE
    )

    batch_name = models.CharField(
        max_length=255
    )

    uploaded_file = models.FileField(
        upload_to="bulk_uploads/"
    )

    file_name = models.CharField(
        max_length=255
    )

    total_records = models.IntegerField(
        default=0
    )

    processed_records = models.IntegerField(
        default=0
    )

    valid_records = models.IntegerField(
        default=0
    )

    invalid_records = models.IntegerField(
        default=0
    )

    progress_percentage = (
        models.IntegerField(
            default=0
        )
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="uploaded"
    )

    uploaded_at = models.DateTimeField(
        auto_now_add=True
    )
    
# ==========================
# Upload Batch Records
# ==========================

from django.db import models

class UploadBatchRecord(models.Model):
    VALIDATION_CHOICES = (
        ("pending", "Pending"),
        ("valid", "Valid"),
        ("invalid", "Invalid"),
    )

    batch = models.ForeignKey(
        UploadBatch,
        on_delete=models.CASCADE,
        related_name="records"
    )
    row_number = models.PositiveIntegerField()
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    job_title = models.CharField(max_length=255)
    company_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=30)
    country_of_residence = models.CharField(max_length=100)
    nationality = models.CharField(max_length=100)
    
    ticket_type = models.ForeignKey(
        TicketType,
        on_delete=models.SET_NULL,
        null=True
    )
    validation_status = models.CharField(
        max_length=20,
        choices=VALIDATION_CHOICES,
        default="pending"
    )
    error_message = models.TextField(
        blank=True,
        null=True
    )
    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:  # Indented correctly inside the model
        indexes = [
            # Standard index for searching users/duplicates by email
            models.Index(fields=["email"]),
            
            # Composite index optimized for filtering a batch's specific statuses 
            # (e.g., batch.records.filter(validation_status="invalid"))
            models.Index(fields=["batch", "validation_status"]),
        ]
        
        constraints = [
            # Ensures row 5 doesn't accidentally get saved twice for the same upload
            models.UniqueConstraint(
                fields=["batch", "row_number"], 
                name="unique_batch_row"
            )
        ]


# ==========================
# Activity Logs
# ==========================

class ActivityLog(models.Model):

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    action = models.CharField(max_length=255)

    table_name = models.CharField(max_length=100)

    record_id = models.PositiveIntegerField()

    description = models.TextField()

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return self.action


# ==========================
# Upload Field Mapping
# ==========================
class UploadFieldMapping(models.Model):

    batch = models.ForeignKey(
        UploadBatch,
        on_delete=models.CASCADE,
        related_name="mappings"
    )

    source_column = models.CharField(
        max_length=255
    )

    target_field = models.CharField(
        max_length=255
    )

    def __str__(self):
        return (
            f"{self.source_column}"
            f" -> "
            f"{self.target_field}"
        )



# ==========================
# Export Logs
# ==========================

class ExportLog(models.Model):

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    export_type = models.CharField(max_length=100)

    record_count = models.PositiveIntegerField()

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return self.export_type