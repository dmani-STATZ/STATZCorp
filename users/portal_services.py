from datetime import timedelta
from django.utils import timezone
from django.db.models import Avg, Count, Q
from .models import (
    CalendarAnalyticsSnapshot,
    EventAttendance,
    NaturalLanguageScheduleRequest,
    PortalSection,
    ScheduledMicroBreak,
    WorkCalendarEvent,
    WorkCalendarTask,
)


def get_visible_sections(user):
    """
    Return portal sections visible to the current user with prefetched resources.
    """
    sections = PortalSection.objects.prefetch_related('resources').filter(is_active=True).order_by('-is_pinned', 'order', 'title')
    if not user or not user.is_authenticated:
        return [s for s in sections if s.visibility == 'public']
    visible = []
    for section in sections:
        if section.is_visible_to(user):
            visible.append(section)
    return visible


def serialize_resource(resource):
    return {
        'id': resource.id,
        'title': resource.title,
        'description': resource.description,
        'resource_type': resource.resource_type,
        'url': resource.get_absolute_url(),
        'icon': resource.icon,
        'tags': resource.tags,
        'is_featured': resource.is_featured,
        'metadata': resource.metadata,
    }


def serialize_section(section, user=None):
    can_edit = False
    if user and user.is_authenticated:
        can_edit = (
            section.editors.filter(pk=user.pk).exists()
            or user.is_staff
            or user.is_superuser
        )
    return {
        'id': section.id,
        'title': section.title,
        'slug': section.slug,
        'description': section.description,
        'layout': section.layout,
        'icon': section.icon,
        'configuration': section.configuration,
        'can_edit': can_edit,
        'resources': [serialize_resource(r) for r in section.resources.all()],
    }


def upcoming_events_for_user(user, days_ahead=14):
    """
    Determine relevant events for the user across the next timeframe.
    """
    if not user or not user.is_authenticated:
        return WorkCalendarEvent.objects.none()

    now = timezone.now()
    horizon = now + timedelta(days=days_ahead)
    base_queryset = WorkCalendarEvent.objects.select_related('organizer', 'section').prefetch_related('tasks', 'attendance_records')

    return base_queryset.filter(
        Q(organizer=user) | Q(attendance_records__user=user),
        start_at__lte=horizon,
        end_at__gte=now - timedelta(hours=1),
    ).distinct()


def serialize_event(event, user=None):
    attendance = None
    if user and user.is_authenticated:
        attendance = next((record for record in event.attendance_records.all() if record.user_id == user.id), None)

    can_edit = bool(user and user.is_authenticated and (event.organizer_id == user.id or user.is_staff or user.is_superuser))

    all_day = (
        event.start_at.hour == 0 and event.start_at.minute == 0 and event.start_at.second == 0 and
        event.end_at.hour == 0 and event.end_at.minute == 0 and event.end_at.second == 0
    )

    return {
        'id': event.id,
        'title': event.get_effective_title(),
        'kind': event.kind,
        'start': event.start_at.isoformat(),
        'end': event.end_at.isoformat(),
        'all_day': all_day,
        'priority': event.priority,
        'energy_required': event.energy_required,
        'focus_block': event.focus_block,
        'predicted_attendance': float(event.predicted_attendance or 0),
        'requires_travel': event.requires_travel,
        'location': event.location,
        'metadata': event.metadata,
        'tasks': [{'id': task.id, 'title': task.title} for task in event.tasks.all()],
        'attendance': attendance.status if attendance else None,
        'confidence': float(attendance.confidence_score) if attendance and attendance.confidence_score is not None else None,
        'organizer_name': event.organizer.get_full_name() or event.organizer.username,
        'can_edit': can_edit,
    }


def active_tasks_for_user(user, limit=8):
    """
    Return high-priority tasks that still need scheduling or completion.
    """
    if not user or not user.is_authenticated:
        return WorkCalendarTask.objects.none()
    base = WorkCalendarTask.objects.filter(owner=user).exclude(status='completed').order_by('-importance', 'due_date')
    return base[:limit]


def serialize_task(task):
    return {
        'id': task.id,
        'title': task.title,
        'description': task.description,
        'importance': task.importance,
        'energy_required': task.energy_required,
        'due_date': task.due_date.isoformat() if task.due_date else None,
        'estimated_minutes': task.estimated_minutes,
        'status': task.status,
    }


def latest_snapshot(user):
    if not user or not user.is_authenticated:
        return None
    return CalendarAnalyticsSnapshot.objects.filter(user=user).order_by('-range_end').first()


def serialize_snapshot(snapshot):
    if not snapshot:
        return None
    return {
        'range_start': snapshot.range_start.isoformat(),
        'range_end': snapshot.range_end.isoformat(),
        'meeting_hours': float(snapshot.meeting_hours),
        'focus_hours': float(snapshot.focus_hours),
        'ghost_meeting_rate': float(snapshot.ghost_meeting_rate),
        'context_switches': snapshot.context_switches,
        'wellness_breaks_inserted': snapshot.wellness_breaks_inserted,
        'suggestions': snapshot.suggestions,
        'recommendation_payload': snapshot.recommendation_payload,
    }


def upcoming_microbreaks(user, days_ahead=7):
    if not user or not user.is_authenticated:
        return ScheduledMicroBreak.objects.none()
    now = timezone.now()
    horizon = now + timedelta(days=days_ahead)
    return ScheduledMicroBreak.objects.filter(user=user, start_at__gte=now, start_at__lte=horizon).order_by('start_at')


def serialize_microbreak(break_obj):
    return {
        'id': break_obj.id,
        'label': break_obj.label,
        'start_at': break_obj.start_at.isoformat(),
        'end_at': break_obj.end_at.isoformat(),
        'insertion_mode': break_obj.insertion_mode,
        'related_event_id': break_obj.related_event_id,
        'notes': break_obj.notes,
    }


def outstanding_nlp_requests(user, limit=5):
    if not user or not user.is_authenticated:
        return []
    qs = NaturalLanguageScheduleRequest.objects.filter(user=user).order_by('-created_at')
    return list(qs[:limit])


def serialize_nlp_request(request_obj):
    return {
        'id': request_obj.id,
        'raw_text': request_obj.raw_text,
        'status': request_obj.status,
        'interpreted_start': request_obj.interpreted_start.isoformat() if request_obj.interpreted_start else None,
        'interpreted_end': request_obj.interpreted_end.isoformat() if request_obj.interpreted_end else None,
        'duration_minutes': request_obj.duration_minutes,
        'diagnostics': request_obj.diagnostics,
    }


def build_portal_context(user):
    sections = get_visible_sections(user)
    events = upcoming_events_for_user(user)
    tasks = active_tasks_for_user(user)
    snapshot = latest_snapshot(user)
    microbreaks = upcoming_microbreaks(user)
    nlp_requests = outstanding_nlp_requests(user)

    return {
        'sections': [serialize_section(section, user=user) for section in sections],
        'events': [serialize_event(event, user=user) for event in events],
        'tasks': [serialize_task(task) for task in tasks],
        'analytics': serialize_snapshot(snapshot),
        'microbreaks': [serialize_microbreak(b) for b in microbreaks],
        'nlp_requests': [serialize_nlp_request(r) for r in nlp_requests],
    }
