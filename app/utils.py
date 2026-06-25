import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from .models import BadgeAllocation, Registration

from django.db.models import Sum


def get_exhibitor_allocation(exhibitor, ticket_type):
    """
    Locks the BadgeAllocation row (if any) so concurrent badge creation
    can't race past the per-exhibitor quota for this ticket type.

    Returns (allocated, used, available).
    allocated == 0 means this exhibitor has no allocation row for this
    ticket_type at all (i.e. they haven't been given any badges of this type).

    NOTE: uses .exclude(status="cancelled") to match the semantics of every
    global TicketType.total_tickets check elsewhere in the codebase — NOT
    BadgeAllocation.used_count, which only counts "confirmed" and would let
    exhibitors over-invite against their own allocation.
    """
    try:
        allocation = BadgeAllocation.objects.select_for_update().get(
            exhibitor=exhibitor, ticket_type=ticket_type
        )
        allocated = allocation.allocated_count
    except BadgeAllocation.DoesNotExist:
        allocated = 0

    used = Registration.objects.select_for_update().filter(
        exhibitor=exhibitor, ticket_type=ticket_type
    ).exclude(status="cancelled").count()

    return allocated, used, allocated - used


def get_exhibitor_ticket_quota(exhibitor, ticket_type):
    """
    Locks the allocation row so concurrent badge creation can't race past the quota.
    Returns (allocated, used, available).
    """
    try:
        allocation = TicketAllocation.objects.select_for_update().get(
            exhibitor=exhibitor, ticket_type=ticket_type
        )
        allocated = allocation.allocated_count
    except TicketAllocation.DoesNotExist:
        allocated = 0  # nothing assigned yet

    used = Registration.objects.select_for_update().filter(
        exhibitor=exhibitor, ticket_type=ticket_type
    ).exclude(status="cancelled").count()

    return allocated, used, allocated - used


def enforce_exhibitor_quota(exhibitor, ticket_type, requested_count=1):
    allocated, used, available = get_exhibitor_ticket_quota(exhibitor, ticket_type)

    if allocated == 0:
        raise ValidationError(
            f"You have not been allocated any '{ticket_type.ticket_name}' badges yet. "
            f"Please contact the administrator to request an allocation."
        )

    if requested_count > available:
        raise ValidationError(
            f"You have only {available} '{ticket_type.ticket_name}' badge(s) remaining "
            f"out of your allocated {allocated}. Please contact the administrator to increase your quota."
        )

def verify_recaptcha(token):
    response = requests.post(
        "https://www.google.com/recaptcha/api/siteverify",
        data={
            "secret": settings.RECAPTCHA_SECRET_KEY,
            "response": token,
        },
    )

    return response.json()