import uuid
 
import pandas as pd
from celery import shared_task
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
 
from .models import Exhibitor, Registration, TicketType, UploadBatch, UploadBatchRecord
 
DB_BATCH_SIZE = 5000
PROGRESS_UPDATE_EVERY = 5000
 
# SQLite hard-limits IN clauses to 999 bind variables.
# Postgres has no such limit, but chunking works fine on both.
SQLITE_SAFE_IN_LIMIT = 900
 
 
# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
 
def _read_dataframe(file_obj, file_name):
    name = file_name.lower()
 
    if name.endswith(".csv"):
        return pd.read_csv(file_obj, dtype=str, keep_default_na=False)
 
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(file_obj, engine="openpyxl", dtype=str)
 
    raise ValueError("Only CSV and Excel files are supported.")
 
 
def _get_ticket_type_map():
    ticket_types = cache.get("active_ticket_types")
 
    if not ticket_types:
        ticket_types = {
            t.ticket_name.strip().lower(): t.id
            for t in TicketType.objects.filter(status="active")
        }
        cache.set("active_ticket_types", ticket_types, 3600)
 
    return ticket_types
 
 
def _fetch_existing_emails_chunked(email_set):
    """
    BUG FIX 1 — 'too many SQL variables':
    SQLite crashes when you pass 1000+ values into a single IN clause.
    This splits the lookup into chunks of 900, which is safe on SQLite
    and has no downside on Postgres.
    """
    emails = list(email_set)
    existing = set()
 
    for i in range(0, len(emails), SQLITE_SAFE_IN_LIMIT):
        chunk = emails[i : i + SQLITE_SAFE_IN_LIMIT]
        existing.update(
            e.lower()
            for e in Registration.objects.filter(
                email__in=chunk
            ).values_list("email", flat=True)
        )
 
    return existing
 
 
# ─────────────────────────────────────────────────────────────
# Task 1 — parse + validate the uploaded file
# ─────────────────────────────────────────────────────────────
 
import pandas as pd
import numpy as np
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

DB_BATCH_SIZE = 5000
PROGRESS_UPDATE_EVERY = 10000  # Less frequent = faster

@shared_task(bind=True, max_retries=2)
def process_bulk_upload(self, batch_id, mappings):
    try:
        batch = UploadBatch.objects.select_related("exhibitor").get(id=batch_id)
        batch.status = "processing"
        batch.save(update_fields=["status"])

        with batch.uploaded_file.open("rb") as f:
            df = _read_dataframe(f, batch.file_name)

        if df.empty:
            batch.status = "failed"
            batch.save(update_fields=["status"])
            return {"error": "File is empty."}

        # ── 1. Rename & normalize ──────────────────────────────────────
        df = df.rename(columns={s: t for s, t in mappings.items()})
        df = df.fillna("")

        expected_cols = [
            "first_name", "last_name", "email", "job_title", "company_name",
            "phone_number", "country_of_residence", "nationality", "ticket_type",
        ]
        for col in expected_cols:
            if col not in df.columns:
                df[col] = ""

        # Strip required string columns once, vectorized
        for col in ["first_name", "last_name", "email", "ticket_type"]:
            df[col] = df[col].astype(str).str.strip()

        df["email_lower"] = df["email"].str.lower()
        total = len(df)

        # ── 2. Pre-load ALL lookups into memory (zero per-row queries) ──
        ticket_type_map = _get_ticket_type_map()  # {name_lower: id}

        batch_emails = set(df["email_lower"]) - {""}
        existing_emails = _fetch_existing_emails_chunked(batch_emails)

        # ── 3. Vectorized validation — no Python loop ──────────────────

        # Map ticket types
        df["ticket_type_id_val"] = df["ticket_type"].str.lower().map(ticket_type_map)

        # Duplicate emails WITHIN this batch (keep first, flag rest)
        df["is_batch_duplicate"] = df["email_lower"].duplicated(keep="first") & (df["email_lower"] != "")

        # Boolean error columns — all vectorized
        err_no_first   = df["first_name"].eq("")
        err_no_last    = df["last_name"].eq("")
        err_no_email   = df["email"].eq("")
        err_bad_email  = ~err_no_email & ~df["email"].str.match(
            r"^[^\s@]+@[^\s@]+\.[^\s@]+$"
        )
        err_email_exists = df["email_lower"].isin(existing_emails) & ~err_no_email
        err_duplicate    = df["is_batch_duplicate"]
        err_no_ticket    = df["ticket_type_id_val"].isna()

        # Build error messages vectorized
        def build_errors(row):
            """Called only on INVALID rows — much smaller set."""
            msgs = []
            if row["err_no_first"]:   msgs.append("First name is required.")
            if row["err_no_last"]:    msgs.append("Last name is required.")
            if row["err_no_email"]:   msgs.append("Email is required.")
            elif row["err_bad_email"]: msgs.append("Invalid email format.")
            if row["err_email_exists"]: msgs.append("Email already exists in registrations.")
            if row["err_duplicate"]:  msgs.append("Duplicate email within this upload.")
            if row["err_no_ticket"]:  msgs.append("Ticket type is required or not recognized.")
            return " | ".join(msgs)

        # Attach error flag columns temporarily
        df["err_no_first"]     = err_no_first
        df["err_no_last"]      = err_no_last
        df["err_no_email"]     = err_no_email
        df["err_bad_email"]    = err_bad_email
        df["err_email_exists"] = err_email_exists
        df["err_duplicate"]    = err_duplicate
        df["err_no_ticket"]    = err_no_ticket

        any_error = (
            err_no_first | err_no_last | err_no_email |
            err_bad_email | err_email_exists | err_duplicate | err_no_ticket
        )
        df["validation_status"] = np.where(any_error, "invalid", "valid")

        # Build error messages only for invalid rows
        invalid_mask = any_error
        df["error_message"] = None
        if invalid_mask.any():
            df.loc[invalid_mask, "error_message"] = (
                df[invalid_mask].apply(build_errors, axis=1)
            )

        # ticket_type_id: NaN → None for DB
        df["ticket_type_id_val"] = df["ticket_type_id_val"].where(
            df["ticket_type_id_val"].notna(), other=None
        )

        valid_count   = int((df["validation_status"] == "valid").sum())
        invalid_count = int((df["validation_status"] == "invalid").sum())

        # ── 4. Clear old records, bulk_create in chunks ────────────────
        UploadBatchRecord.objects.filter(batch=batch).delete()

        records = [
            UploadBatchRecord(
                batch=batch,
                row_number=i + 2,
                first_name=row.first_name,
                last_name=row.last_name,
                email=row.email,
                job_title=row.job_title,
                company_name=row.company_name,
                phone_number=row.phone_number,
                country_of_residence=row.country_of_residence,
                nationality=row.nationality,
                ticket_type_id=(
                    int(row.ticket_type_id_val)
                    if row.ticket_type_id_val is not None
                    and not (isinstance(row.ticket_type_id_val, float) and np.isnan(row.ticket_type_id_val))
                    else None
                ),
                validation_status=row.validation_status,
                error_message=row.error_message,
            )
            for i, row in enumerate(df.itertuples(index=False))
        ]

        # bulk_create in chunks + update progress
        for chunk_start in range(0, len(records), DB_BATCH_SIZE):
            chunk = records[chunk_start: chunk_start + DB_BATCH_SIZE]
            UploadBatchRecord.objects.bulk_create(chunk, batch_size=DB_BATCH_SIZE)

            processed_so_far = min(chunk_start + DB_BATCH_SIZE, total)
            UploadBatch.objects.filter(id=batch.id).update(
                processed_records=processed_so_far,
                progress_percentage=int((processed_so_far / total) * 100),
            )

        # ── 5. Final batch update ──────────────────────────────────────
        batch.valid_records     = valid_count
        batch.invalid_records   = invalid_count
        batch.processed_records = total
        batch.total_records     = total
        batch.progress_percentage = 100
        batch.status = "validated"
        batch.save(update_fields=[
            "valid_records", "invalid_records", "processed_records",
            "total_records", "progress_percentage", "status",
        ])

        return {"valid": valid_count, "invalid": invalid_count, "total": total}

    except Exception as exc:
        UploadBatch.objects.filter(id=batch_id).update(status="failed")
        raise self.retry(exc=exc, countdown=10) 
 
# ─────────────────────────────────────────────────────────────
# Task 2 — commit valid records to Registration
# ─────────────────────────────────────────────────────────────
 
@shared_task(bind=True)
def commit_bulk_upload(self, batch_id, exhibitor_id):
    try:
        # ── 1. Acquire lock and load data ──────────────────────────────
        with transaction.atomic():
            batch = UploadBatch.objects.select_for_update().get(id=batch_id)

            # Guard against duplicate task execution (e.g. Celery retry storms)
            if batch.status == "completed":
                return {"skipped": True, "reason": "Already committed."}
            if batch.status == "failed":
                return {"skipped": True, "reason": "Batch marked failed."}

            exhibitor = Exhibitor.objects.get(id=exhibitor_id)
            valid_records = list(
                batch.records.filter(validation_status="valid")
                .select_related("ticket_type")
            )

            if not valid_records:
                batch.status = "failed"
                batch.save(update_fields=["status"])
                return {"error": "No valid records found."}
        # Lock released — safe to do expensive work below

        # ── 2. Deduplicate against committed registrations ──────────────
        incoming_emails = {r.email.lower() for r in valid_records}
        already_exists = set(
            Registration.objects.filter(email__in=incoming_emails)
            .values_list("email", flat=True)
        )
        skipped = [r for r in valid_records if r.email.lower() in already_exists]
        to_insert = [r for r in valid_records if r.email.lower() not in already_exists]

        if not to_insert:
            UploadBatch.objects.filter(id=batch_id).update(status="completed")
            return {"inserted": 0, "skipped": len(skipped), "reason": "All emails already registered."}

        # ── 3. Bulk insert ──────────────────────────────────────────────
        created_ids = []
        with transaction.atomic():
            buffer = []
            for record in to_insert:
                buffer.append(
                    Registration(
                        exhibitor=exhibitor,
                        ticket_type=record.ticket_type,
                        first_name=record.first_name,
                        last_name=record.last_name,
                        email=record.email,
                        job_title=record.job_title,
                        company_name=record.company_name,
                        phone_number=record.phone_number,
                        country_of_residence=record.country_of_residence,
                        nationality=record.nationality,
                        registered_via="bulk_upload",
                        status="confirmed",
                        terms_accepted=True,
                        urn=f"_tmp_{uuid.uuid4().hex}",
                        upload_batch=batch,
                    )
                )
                if len(buffer) >= DB_BATCH_SIZE:
                    created = Registration.objects.bulk_create(buffer, batch_size=DB_BATCH_SIZE)
                    created_ids.extend([r.id for r in created if r.id])
                    buffer = []

            if buffer:
                created = Registration.objects.bulk_create(buffer, batch_size=DB_BATCH_SIZE)
                created_ids.extend([r.id for r in created if r.id])

        # ── 4. URN update in its own atomic block ───────────────────────
        if created_ids:
            with transaction.atomic():
                regs = Registration.objects.filter(id__in=created_ids, urn__startswith="_tmp_")
                for reg in regs:
                    reg.urn = f"GF2026-{reg.id:06d}"
                Registration.objects.bulk_update(regs, ["urn"], batch_size=DB_BATCH_SIZE)

        # ── 5. Mark complete ────────────────────────────────────────────
        UploadBatch.objects.filter(id=batch_id).update(status="completed")

        return {
            "inserted": len(created_ids),
            "skipped_duplicates": len(skipped),
        }

    except Exception as exc:
        UploadBatch.objects.filter(id=batch_id).update(status="failed")
        raise