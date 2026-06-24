from django.urls import path
from . views import *

urlpatterns = [



    # ── Send Invitations ─────────────────────────────────────────────────
    path("exhibitor/invitations/send/", SendInvitationAPIView.as_view(), name="invitation_send"),

    # ── Import Invitations ─────────────────────────────────────────────────
    # path("exhibitor/invitations/import/", InvitationImportFileView.as_view(), name="invitation_import"),

    # ── List Invitations ─────────────────────────────────────────────────
    path("exhibitor/invitations/", InvitationListAPIView.as_view(), name="invitation_list"),

    # ── Invitation Details ────────────────────────────────────────────────
    path("register/<str:token>/", InvitationRegisterDetailView.as_view(), name="invitation_register"),

    # ── Complete Registration ─────────────────────────────────────────────
    path("register/<str:token>/complete/", InvitationRegisterCompleteView.as_view(), name="invitation_complete"), 


    path("register/<str:token>/update-name/", InvitationRegisterUpdateNameView.as_view(), name="invitation_update_name"),


    # ────────────────────────────── Bulk Upload ──────────────────────────────────────
    # Step 1: Upload Excel file → creates UploadBatch + UploadBatchRecords
    path("exhibitor/bulk-upload/upload/", BulkUploadFileView.as_view(), name="bulk_upload_file"),
 

    # ────────────────────────────── Bulk Upload Mapping ──────────────────────────────────────
    # Step 2: Map fields → updates UploadBatch with field mappings
    path("exhibitor/bulk-upload/<int:batch_id>/map/", BulkUploadMapFieldsView.as_view(), name="bulk_upload_map"),
    

    # ────────────────────────────── Bulk Upload Review ──────────────────────────────────────
    # Step 3: Review validation results → shows valid/invalid records
    path("exhibitor/bulk-upload/<int:batch_id>/review/", BulkUploadReviewView.as_view(), name="bulk_upload_review"),
 

    # ────────────────────────────── Bulk Upload Record Edit ──────────────────────────────────────
    # Step 4: Edit a single invalid record and re-validate
    path("exhibitor/bulk-upload/record/<int:record_id>/edit/", BulkUploadRecordEditView.as_view(), name="bulk_upload_record_edit"),
 

    # ────────────────────────────── Bulk Upload Commit ──────────────────────────────────────
    # Step 5: Commit valid records → inserts into Registration table
    path("exhibitor/bulk-upload/<int:batch_id>/commit/", BulkUploadCommitView.as_view(), name="bulk_upload_commit"),
 

    # ────────────────────────────── Bulk Upload Status ──────────────────────────────────────
    # Utility: Check the status of a batch (processing, validated, failed)
    path("exhibitor/bulk-upload/batches/", BulkUploadBatchListView.as_view(), name="bulk_upload_batches"),
 

    # ────────────────────────────── Bulk Upload Progress ──────────────────────────────────────
    # Utility: Check the progress of a batch (percentage complete)
    path("exhibitor/bulk-upload/sample-template/", BulkUploadSampleTemplateView.as_view(), name="bulk_upload_sample"),

    # ────────────────────────────── Bulk Delete Registrations ──────────────────────────────────────
    path("exhibitor/registrations/bulk-delete/", RegistrationBulkDeleteView.as_view()),

    # ────────────────────────────── Bulk Upload Delete Registrations ──────────────────────────────────────
    path("exhibitor/bulk-upload/<int:batch_id>/delete-registrations/", BulkUploadDeleteRegistrationsView.as_view()),



    # ────────────────────────────── Registration Create ──────────────────────────────────────
    path("registrations/create/", RegistrationCreateAPIView.as_view(), name='registration_create'),

    # ────────────────────────────── Registration Update ──────────────────────────────────────
    path("registrations/<int:pk>/update/", RegistrationUpdateAPIView.as_view(), name="registration-update",),

    # ────────────────────────────── Registration Delete ──────────────────────────────────────
    path("registrations/<int:pk>/delete/", RegistrationDeleteAPIView.as_view(),name="registration-delete",),

    # ────────────────────────────── Exhibitor Dashboard ──────────────────────────────────────
    path("exhibitor/dashboard/", ExhibitorDashboardAPIView.as_view(), name='exhibitor_dashboard'),

    # ────────────────────────────── Registration List ──────────────────────────────────────
    path("exhibitor/registrations/", RegistrationListAPIView.as_view(), name='registration_list'),

    # ────────────────────────────── Exhibitor Login ──────────────────────────────────────
    path("exhibitor/login/", ExhibitorLoginAPIView.as_view(), name='exhibitor_login'),

    # ────────────────────────────── Exhibitor Create ──────────────────────────────────────
    path("admin/exhibitors/create/", CreateExhibitorAPIView.as_view(), name='create_exhibitor'),

    # ────────────────────────────── Exhibitor List ──────────────────────────────────────
    path("admin/exhibitors/", ExhibitorListAPIView.as_view(), name='exhibitor_list'),

    # ────────────────────────────── Exhibitor Details ──────────────────────────────────────
    path("admin/exhibitors/<int:pk>/", ExhibitorDetailAPIView.as_view(), name='exhibitor_detail'),

    # ────────────────────────────── Update Exhibitor ──────────────────────────────────────
    path("admin/tickets/create/", CreateTicketTypeAPIView.as_view(), name='create_ticket_type'),

    # ────────────────────────────── Ticket Type List ──────────────────────────────────────
    path("admin/tickets/", TicketTypeListAPIView.as_view(), name='ticket_type_list'),

    # ────────────────────────────── Ticket Type Details ──────────────────────────────────────
    path("admin/tickets/<int:pk>/", TicketTypeDetailAPIView.as_view(), name='ticket_type_detail'),

    # ────────────────────────────── Update Ticket Type ──────────────────────────────────────
    path("admin/tickets/<int:pk>/update/", UpdateTicketTypeAPIView.as_view(), name='update_ticket_type'),

    # ────────────────────────────── Delete Ticket Type ──────────────────────────────────────
    path("admin/tickets/<int:pk>/delete/", DeleteTicketTypeAPIView.as_view(), name='delete_ticket_type'),

    # ────────────────────────────── Super Admin Login ──────────────────────────────────────
    path('super-admin/login/', SuperAdminLoginView.as_view(), name='super_admin_login'),

    # ────────────────────────────── Super Admin Logout ──────────────────────────────────────
    path('super-admin/logout/', SuperAdminLogoutView.as_view(), name='super_admin_logout'),
]