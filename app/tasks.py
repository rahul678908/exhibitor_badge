import uuid

import numpy as np
import pandas as pd
from celery import shared_task
from django.core.cache import cache
from django.db import transaction

from .models import (
    BadgeAllocation,   # ✅ NEW
    Exhibitor,
    Registration,
    TicketType,
    UploadBatch,
    UploadBatchRecord,
)

DB_BATCH_SIZE = 5_000
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
    SQLite crashes when you pass 1000+ values into a single IN clause.
    Split into chunks of 900 — safe on both SQLite and Postgres.
    """
    emails = list(email_set)
    existing = set()
    for i in range(0, len(emails), SQLITE_SAFE_IN_LIMIT):
        chunk = emails[i: i + SQLITE_SAFE_IN_LIMIT]
        existing.update(
            e.lower()
            for e in Registration.objects.filter(
                email__in=chunk
            ).values_list("email", flat=True)
        )
    return existing


def _build_errors(row):
    msgs = []
    if row["err_no_first"]:
        msgs.append("First name is required.")
    if row["err_digit_first"]:
        msgs.append("First name must not contain numbers.")
    if row["err_no_last"]:
        msgs.append("Last name is required.")
    if row["err_digit_last"]:
        msgs.append("Last name must not contain numbers.")
    if row["err_no_email"]:
        msgs.append("Email is required.")
    elif row["err_bad_email"]:
        msgs.append("Invalid email format.")
    if row["err_email_exists"]:
        msgs.append("Email already exists in registrations.")
    if row["err_duplicate"]:
        msgs.append("Duplicate email within this upload.")
    if row["err_no_ticket"]:
        msgs.append("Ticket type is required or not recognized.")
    if row["err_quota_exceeded"]:
        msgs.append("Requested records exceed available ticket balance.")
    if row["err_exhibitor_quota_exceeded"]:   # ✅ NEW
        msgs.append(
            "Exceeds your allocated badge quota for this ticket type. "
            "Please contact the administrator to increase your quota."
        )
    return " | ".join(msgs)

# ─────────────────────────────────────────────────────────────
# Task 1 — parse + validate the uploaded file
# ─────────────────────────────────────────────────────────────

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

        for col in ["first_name", "last_name", "email", "ticket_type"]:
            df[col] = df[col].astype(str).str.strip()

        df["email_lower"] = df["email"].str.lower()
        total = len(df)

        # ── 2. Pre-load ALL lookups into memory (zero per-row queries) ──
        ticket_type_map = _get_ticket_type_map()

        batch_emails = set(df["email_lower"]) - {""}
        existing_emails = _fetch_existing_emails_chunked(batch_emails)

        # Global pool: TicketType.total_tickets minus already-confirmed registrations.
        quota_map = {
            t.id: t.total_tickets - Registration.objects.filter(
                ticket_type=t, status="confirmed"
            ).count()
            for t in TicketType.objects.filter(status="active")
        }

        # ✅ NEW — exhibitor's own allocation per ticket type
        exhibitor = batch.exhibitor

        allocation_map = {
            a.ticket_type_id: a.allocated_count
            for a in BadgeAllocation.objects.filter(exhibitor=exhibitor)
        }

        # ✅ NEW — exhibitor's existing usage per ticket type, excluding cancelled.
        # Matches get_exhibitor_allocation() semantics used elsewhere — NOT
        # BadgeAllocation.used_count, which only counts "confirmed".
        exhibitor_used_counts = {}
        for tid in Registration.objects.filter(
            exhibitor=exhibitor
        ).exclude(status="cancelled").values_list("ticket_type_id", flat=True):
            exhibitor_used_counts[tid] = exhibitor_used_counts.get(tid, 0) + 1

        exhibitor_quota_map = {
            tid: allocation_map[tid] - exhibitor_used_counts.get(tid, 0)
            for tid in allocation_map
        }
        # A ticket_type_id absent here means this exhibitor has no BadgeAllocation
        # row for it at all — every row using it is invalid for that reason.

        # ── 3. Vectorized validation ───────────────────────────────────
        df["ticket_type_id_val"] = df["ticket_type"].str.lower().map(ticket_type_map)
        df["is_batch_duplicate"] = (
            df["email_lower"].duplicated(keep="first") & (df["email_lower"] != "")
        )

        df["err_no_first"]     = df["first_name"].eq("")
        df["err_no_last"]      = df["last_name"].eq("")
        df["err_no_email"]     = df["email"].eq("")
        df["err_digit_first"]  = df["first_name"].str.contains(r"\d", regex=True) & ~df["err_no_first"]
        df["err_digit_last"]   = df["last_name"].str.contains(r"\d", regex=True) & ~df["err_no_last"]
        df["err_bad_email"]    = (
            ~df["err_no_email"]
            & ~df["email"].str.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
        )
        df["err_email_exists"] = df["email_lower"].isin(existing_emails) & ~df["err_no_email"]
        df["err_duplicate"]    = df["is_batch_duplicate"]
        df["err_no_ticket"]    = df["ticket_type_id_val"].isna()

        # ── 4. Per-row quota check (must be sequential) ─────────────────
        # A row only consumes a seat from EITHER pool if it passes BOTH
        # checks — a row invalid for either reason never actually takes a seat.
        remaining_quota = dict(quota_map)
        remaining_exhibitor_quota = dict(exhibitor_quota_map)   # ✅ NEW

        err_quota_exceeded_list = []
        err_exhibitor_quota_exceeded_list = []   # ✅ NEW

        # ✅ FIXED — if no allocation row exists, fall back to global pool only
        for _, row in df.iterrows():
            tid = row["ticket_type_id_val"]

            already_invalid = (
                row["err_no_first"]     or
                row["err_no_last"]      or
                row["err_digit_first"]  or
                row["err_digit_last"]   or
                row["err_no_email"]     or
                row["err_bad_email"]    or
                row["err_email_exists"] or
                row["err_duplicate"]    or
                row["err_no_ticket"]
            )

            if already_invalid or pd.isna(tid):
                err_quota_exceeded_list.append(False)
                err_exhibitor_quota_exceeded_list.append(False)
                continue

            tid = int(tid)

            global_ok = tid in remaining_quota and remaining_quota[tid] > 0

            # ✅ If no allocation row exists for this exhibitor+ticket, skip
            # the exhibitor quota check and rely on global pool only
            has_allocation = tid in remaining_exhibitor_quota
            exhibitor_ok = (not has_allocation) or (remaining_exhibitor_quota[tid] > 0)

            err_quota_exceeded_list.append(not global_ok)
            err_exhibitor_quota_exceeded_list.append(has_allocation and not exhibitor_ok)

            if global_ok and exhibitor_ok:
                remaining_quota[tid] -= 1
                if has_allocation:
                    remaining_exhibitor_quota[tid] -= 1

        df["err_quota_exceeded"] = err_quota_exceeded_list
        df["err_exhibitor_quota_exceeded"] = err_exhibitor_quota_exceeded_list

        # ── 5. Final valid/invalid determination ───────────────────────
        any_error = (
            df["err_no_first"]      |
            df["err_no_last"]       |
            df["err_digit_first"]   |
            df["err_digit_last"]    |
            df["err_no_email"]      |
            df["err_bad_email"]     |
            df["err_email_exists"]  |
            df["err_duplicate"]     |
            df["err_no_ticket"]     |
            df["err_quota_exceeded"]           |
            df["err_exhibitor_quota_exceeded"]    # ✅ NEW
        )

        df["validation_status"] = np.where(any_error, "invalid", "valid")

        df["error_message"] = None
        if any_error.any():
            df.loc[any_error, "error_message"] = df[any_error].apply(_build_errors, axis=1)

        df["ticket_type_id_val"] = df["ticket_type_id_val"].where(
            df["ticket_type_id_val"].notna(), other=None
        )

        valid_count   = int((df["validation_status"] == "valid").sum())
        invalid_count = int((df["validation_status"] == "invalid").sum())

        # ── 6. Clear old records, bulk-create in chunks ────────────────
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
                    and not (
                        isinstance(row.ticket_type_id_val, float)
                        and np.isnan(row.ticket_type_id_val)
                    )
                    else None
                ),
                validation_status=row.validation_status,
                error_message=row.error_message,
            )
            for i, row in enumerate(df.itertuples(index=False))
        ]

        for chunk_start in range(0, len(records), DB_BATCH_SIZE):
            chunk = records[chunk_start: chunk_start + DB_BATCH_SIZE]
            UploadBatchRecord.objects.bulk_create(chunk, batch_size=DB_BATCH_SIZE)
            processed_so_far = min(chunk_start + DB_BATCH_SIZE, total)
            UploadBatch.objects.filter(id=batch.id).update(
                processed_records=processed_so_far,
                progress_percentage=int((processed_so_far / total) * 100),
            )

        # ── 7. Final batch update ──────────────────────────────────────
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

        # ── 2. Deduplicate against committed registrations ─────────────
        incoming_emails = {r.email.lower() for r in valid_records}
        already_exists = set(
            Registration.objects.filter(email__in=incoming_emails)
            .values_list("email", flat=True)
        )
        skipped  = [r for r in valid_records if r.email.lower() in already_exists]
        to_insert = [r for r in valid_records if r.email.lower() not in already_exists]

        # ── 3. Re-check quota at commit time (race-condition guard) ─────
        # Global pool — same source as process_bulk_upload.
        quota_remaining = {}
        for t in TicketType.objects.filter(status="active"):
            confirmed = Registration.objects.filter(
                ticket_type=t, status="confirmed"
            ).count()
            quota_remaining[t.id] = t.total_tickets - confirmed

        # ✅ NEW — this exhibitor's own allocation, re-checked fresh too
        allocation_map = {
            a.ticket_type_id: a.allocated_count
            for a in BadgeAllocation.objects.filter(exhibitor=exhibitor)
        }
        exhibitor_used_counts = {}
        for tid in Registration.objects.filter(
            exhibitor=exhibitor
        ).exclude(status="cancelled").values_list("ticket_type_id", flat=True):
            exhibitor_used_counts[tid] = exhibitor_used_counts.get(tid, 0) + 1

        exhibitor_remaining = {
            tid: allocation_map[tid] - exhibitor_used_counts.get(tid, 0)
            for tid in allocation_map
        }

        quota_approved = []
        quota_rejected = []

        for record in to_insert:
            tid = record.ticket_type_id

            global_ok = tid in quota_remaining and quota_remaining[tid] > 0

            # ✅ Same fallback — no allocation row = rely on global pool only
            has_allocation = tid in exhibitor_remaining
            exhibitor_ok = (not has_allocation) or (exhibitor_remaining[tid] > 0)

            if global_ok and exhibitor_ok:
                quota_remaining[tid] -= 1
                if has_allocation:
                    exhibitor_remaining[tid] -= 1
                quota_approved.append(record)
            else:
                quota_rejected.append(record)

        if quota_rejected:
            UploadBatchRecord.objects.filter(
                id__in=[r.id for r in quota_rejected]
            ).update(
                validation_status="invalid",
                error_message=(
                    "Requested records exceed the available ticket balance or your "
                    "allocated badge quota. Please contact your admin to allocate "
                    "more badges or choose a different ticket type."
                ),
            )

        to_insert = quota_approved

        if not to_insert:
            UploadBatch.objects.filter(id=batch_id).update(status="completed")
            return {
                "inserted": 0,
                "skipped_duplicates": len(skipped),
                "quota_rejected": len(quota_rejected),
                "reason": "All records skipped — duplicates or quota exhausted.",
            }

        # ── 4. Bulk insert ─────────────────────────────────────────────
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
                    Registration.objects.bulk_create(buffer, batch_size=DB_BATCH_SIZE)
                    created_ids.extend(
                        Registration.objects.filter(
                            upload_batch=batch,
                            urn__in=[r.urn for r in buffer],
                        ).values_list("id", flat=True)
                    )
                    buffer = []

            if buffer:
                Registration.objects.bulk_create(buffer, batch_size=DB_BATCH_SIZE)
                created_ids.extend(
                    Registration.objects.filter(
                        upload_batch=batch,
                        urn__in=[r.urn for r in buffer],
                    ).values_list("id", flat=True)
                )

        # ── 5. URN update in its own atomic block ───────────────────────
        if created_ids:
            with transaction.atomic():
                regs = Registration.objects.filter(id__in=created_ids, urn__startswith="_tmp_")
                for reg in regs:
                    reg.urn = f"GF2026-{reg.id:06d}"
                Registration.objects.bulk_update(regs, ["urn"], batch_size=DB_BATCH_SIZE)

        # ── 6. Mark complete ────────────────────────────────────────────
        UploadBatch.objects.filter(id=batch_id).update(status="completed")

        return {
            "inserted": len(created_ids),
            "skipped_duplicates": len(skipped),
            "quota_rejected": len(quota_rejected),   # ✅ NEW — surface this too
        }

    except Exception as exc:
        UploadBatch.objects.filter(id=batch_id).update(status="failed")
        raise