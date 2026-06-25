from rest_framework import serializers
from .models import TicketType,  User, Exhibitor, Registration, UploadBatch, UploadBatchRecord, UploadFieldMapping, BadgeAllocation
from django.db.models import Sum

class BadgeAllocationListSerializer(serializers.ModelSerializer):
    ticket_name     = serializers.CharField(source="ticket_type.ticket_name")
    ticket_code     = serializers.CharField(source="ticket_type.ticket_code")
    used_count      = serializers.SerializerMethodField()
    available_count = serializers.SerializerMethodField()
 
    class Meta:
        model = BadgeAllocation
        fields = [
            "id", "ticket_type", "ticket_name", "ticket_code",
            "allocated_count", "used_count", "available_count", "remarks",
        ]
 
    def get_used_count(self, obj):
        return Registration.objects.filter(
            exhibitor=obj.exhibitor, ticket_type=obj.ticket_type
        ).exclude(status="cancelled").count()
 
    def get_available_count(self, obj):
        return obj.allocated_count - self.get_used_count(obj)




class TicketTypeSerializer(serializers.ModelSerializer):
    """
    Adds three computed read-only fields so the admin Ticket Management table
    can show allocation vs usage at a glance.
    """
 
    # Sum of all BadgeAllocation.allocated_count for this ticket type
    total_allocated = serializers.SerializerMethodField()
 
    # Confirmed registrations against this ticket type (global)
    total_used = serializers.SerializerMethodField()
 
    # Seats still free to be allocated to additional exhibitors
    unallocated_count = serializers.SerializerMethodField()
 
    class Meta:
        model = TicketType
        fields = [
            "id", "ticket_name", "ticket_code", "total_tickets", "status",
            "description",
            "total_allocated",   # NEW
            "total_used",        # NEW
            "unallocated_count", # NEW
        ]
 
    def get_total_allocated(self, obj):
        return (
            BadgeAllocation.objects.filter(ticket_type=obj)
            .aggregate(total=Sum("allocated_count"))["total"] or 0
        )
 
    def get_total_used(self, obj):
        return (
            Registration.objects.filter(ticket_type=obj, status="confirmed").count()
        )
 
    def get_unallocated_count(self, obj):
        total_alloc = self.get_total_allocated(obj)
        return max(0, obj.total_tickets - total_alloc)


class BadgeAllocationListSerializer(serializers.ModelSerializer):
    ticket_name = serializers.CharField(source="ticket_type.ticket_name")
    ticket_code = serializers.CharField(source="ticket_type.ticket_code")
    used_count = serializers.SerializerMethodField()
    available_count = serializers.SerializerMethodField()

    # Make remarks optional
    remarks = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )

    class Meta:
        model = BadgeAllocation
        fields = [
            "id",
            "ticket_type",
            "ticket_name",
            "ticket_code",
            "allocated_count",
            "used_count",
            "available_count",
            "remarks",
        ]

    def get_used_count(self, obj):
        return Registration.objects.filter(
            exhibitor=obj.exhibitor,
            ticket_type=obj.ticket_type,
        ).exclude(status="cancelled").count()

    def get_available_count(self, obj):
        return obj.allocated_count - self.get_used_count(obj)



class BadgeAllocationSerializer(serializers.Serializer):
    exhibitor_id = serializers.IntegerField()
    ticket_type_id = serializers.IntegerField()
    allocated_count = serializers.IntegerField()
    remarks = serializers.CharField(required=False, allow_blank=True)

    def validate_allocated_count(self, value):
        if value <= 0:
            raise serializers.ValidationError("Allocated count must be greater than 0")
        return value



class UploadFieldMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model = UploadFieldMapping
        fields = ["id", "source_column", "target_field"]


class UploadBatchRecordSerializer(serializers.ModelSerializer):
    ticket_type_name = serializers.SerializerMethodField()

    class Meta:
        model = UploadBatchRecord
        fields = [
            "id",
            "row_number",
            "first_name",
            "last_name",
            "email",
            "job_title",
            "company_name",
            "phone_number",
            "country_of_residence",
            "nationality",
            "ticket_type",
            "ticket_type_name",
            "validation_status",
            "error_message",
        ]

    def get_ticket_type_name(self, obj):
        return obj.ticket_type.ticket_name if obj.ticket_type else None


class UploadBatchSerializer(serializers.ModelSerializer):
    records = UploadBatchRecordSerializer(many=True, read_only=True)
    mappings = UploadFieldMappingSerializer(many=True, read_only=True)
    created_by = serializers.CharField(source="exhibitor.user.get_full_name", read_only=True)

    class Meta:
        model = UploadBatch
        fields = [
            "id",
            "batch_name",
            "file_name",
            "total_records",
            "valid_records",
            "invalid_records",
            "processed_records",
            "progress_percentage",
            "status",
            "uploaded_at",
            "records",
            "mappings",
            "created_by",
        ]


class UploadBatchListSerializer(serializers.ModelSerializer):
    class Meta:
        model = UploadBatch
        fields = [
            "id",
            "batch_name",
            "file_name",
            "total_records",
            "valid_records",
            "invalid_records",
            "status",
            "uploaded_at",
        ]


# ------------------------------------------------------------
# RecordEditSerializer doesn't exist in your serializers.py.
# Defining it here since BulkUploadRecordEditView needs it.
# Move it to serializers.py if you'd rather keep it there.
# ------------------------------------------------------------
class RecordEditSerializer(serializers.ModelSerializer):
    class Meta:
        model = UploadBatchRecord
        fields = [
            "first_name",
            "last_name",
            "email",
            "job_title",
            "company_name",
            "phone_number",
            "country_of_residence",
            "nationality",
            "ticket_type",
        ]
        extra_kwargs = {field: {"required": False} for field in fields}






class RegistrationCreateSerializer(serializers.ModelSerializer):

    class Meta:

        model = Registration

        fields = [
            "first_name",
            "last_name",
            "email",
            "company_name",
            "phone_number",
            "ticket_type",
            "country_of_residence",
            "nationality",
            "job_title",
        ]



class RegistrationUpdateSerializer(serializers.ModelSerializer):

    class Meta:
        model = Registration
        fields = [
            "first_name",
            "last_name",
            "email",
            "company_name",
            "phone_number",
            "ticket_type",
            "country_of_residence",
            "nationality",
            "job_title",
            "status",
        ]








class RegistrationListSerializer(serializers.ModelSerializer):

    ticket_name = serializers.CharField(
        source="ticket_type.ticket_name",
        read_only=True
    )
    ticket_type_id = serializers.IntegerField(   # ← flat ID for modal select
        source="ticket_type.id",
        read_only=True
    )
    full_name = serializers.SerializerMethodField()
    invitation_link = serializers.SerializerMethodField()
    batch_name = serializers.CharField(
        source="upload_batch.batch_name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = Registration
        fields = [
            "id",
            "urn",
            "full_name",
            "first_name",           # ← was missing
            "last_name",            # ← was missing
            "phone_number",         # ← was missing
            "nationality",          # ← was missing
            "country_of_residence", # ← was missing
            "ticket_type_id",       # ← was missing (needed for select)
            "job_title",
            "email",
            "company_name",
            "ticket_name",
            "invitation_link",
            "status",
            "batch_name",
        ]

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}"

    def get_invitation_link(self, obj):
        if hasattr(obj, "invitation"):
            return obj.invitation.invitation_link
        return None
        

class ExhibitorLoginSerializer(
    serializers.Serializer
):

    username = serializers.CharField()

    password = serializers.CharField(
        write_only=True
    )





class ExhibitorDetailSerializer(serializers.ModelSerializer):

    username = serializers.CharField(
        source="user.username"
    )

    role = serializers.CharField(
        source="user.role"
    )

    class Meta:

        model = Exhibitor

        fields = [
            "id",
            "company_name",
            "contact_person",
            "contact_email",
            "contact_phone",
            "status",
            "created_at",
            "updated_at",
            "username",
            "role"
        ]


class ExhibitorListSerializer(serializers.ModelSerializer):

    username = serializers.CharField(source="user.username")

    class Meta:

        model = Exhibitor

        fields = [
            "id",
            "company_name",
            "contact_person",
            "contact_email",
            "contact_phone",
            "status",
            "username",
            "created_at"
        ]




class CreateExhibitorSerializer(serializers.Serializer):

    username = serializers.CharField(max_length=150)

    password = serializers.CharField(write_only=True)

    company_name = serializers.CharField(max_length=255)

    contact_person = serializers.CharField(max_length=255)

    contact_email = serializers.EmailField()

    contact_phone = serializers.CharField(max_length=20)

    def validate_username(
        self,
        value
    ):

        if User.objects.filter(
            username=value
        ).exists():

            raise serializers.ValidationError(
                "Username already exists."
            )

        return value

    def validate_contact_email(
        self,
        value
    ):

        if User.objects.filter(
            email=value
        ).exists():

            raise serializers.ValidationError(
                "Email already exists."
            )

        return value


class TicketTypeCreateSerializer(serializers.Serializer):

    ticket_name = serializers.CharField(
        max_length=100
    )

    ticket_code = serializers.CharField(
        max_length=50
    )

    total_tickets = serializers.IntegerField(min_value=1) 

    description = serializers.CharField(
        required=False,
        allow_blank=True
    )

    def validate_ticket_code(
        self,
        value
    ):

        if TicketType.objects.filter(
            ticket_code=value
        ).exists():

            raise serializers.ValidationError(
                "Ticket code already exists"
            )

        return value



class TicketTypeUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketType
        fields = ["ticket_name", "ticket_code", "total_tickets", "status", "description"]
 
    def validate_total_tickets(self, value):
        if self.instance:
            total_allocated = (
                BadgeAllocation.objects.filter(ticket_type=self.instance)
                .aggregate(total=Sum("allocated_count"))["total"] or 0
            )
            if value < total_allocated:
                raise serializers.ValidationError(
                    f"Cannot reduce total tickets to {value}. "
                    f"{total_allocated} badge(s) are already allocated to exhibitors. "
                    f"You can only set a value of {total_allocated} or higher."
                )
        return value


class TicketTypeListSerializer(serializers.ModelSerializer):
    total_allocated   = serializers.SerializerMethodField()
    total_used        = serializers.SerializerMethodField()
    unallocated_count = serializers.SerializerMethodField()

    class Meta:
        model = TicketType
        fields = [
            "id", "ticket_name", "ticket_code", "total_tickets", "status",
            "description",
            "total_allocated",
            "total_used",
            "unallocated_count",
        ]

    def get_total_allocated(self, obj):
        return (
            BadgeAllocation.objects.filter(ticket_type=obj)
            .aggregate(total=Sum("allocated_count"))["total"] or 0
        )

    def get_total_used(self, obj):
        return Registration.objects.filter(
            ticket_type=obj
        ).exclude(status="cancelled").count()

    def get_unallocated_count(self, obj):
        return max(0, obj.total_tickets - self.get_total_allocated(obj))
        


class ExhibitorCreateSerializer(serializers.Serializer):

    username = serializers.CharField()
    password = serializers.CharField()

    company_name = serializers.CharField()
    contact_person = serializers.CharField()
    contact_email = serializers.EmailField()
    contact_phone = serializers.CharField()

    def validate_username(self, value):

        if User.objects.filter(
            username=value
        ).exists():

            raise serializers.ValidationError(
                "Username already exists"
            )

        return value

    def validate_contact_email(self, value):

        if User.objects.filter(
            email=value
        ).exists():

            raise serializers.ValidationError(
                "Email already exists"
            )

        return value

class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()