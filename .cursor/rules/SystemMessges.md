To create a new system message (e.g., in the reports app):
    from users.models import SystemMessage

    # Create a message
    SystemMessage.create_message(
        user=report.report_request.user,
        title="Report Completed",
        message=f"Your report '{report.report_request.generated_name}' is ready to view.",
        priority="medium",
        source_app="reports",
        source_model="Report",
        source_id=str(report.id),
        action_url=reverse('reports:report-view', kwargs={'pk': report.pk})
    )

The system will:
1. Create the message
2. Update the counter in the UI
3. Show a modal on next login if unread
4. Prevent ignoring critical messages (5+ unread)