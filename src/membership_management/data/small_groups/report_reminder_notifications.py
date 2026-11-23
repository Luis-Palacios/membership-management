"""Small group reports' side of the weekly report reminder emails (report-reminder-emails spec,
*Contracts → membership-management*): the event the worker's trigger writes once per church week, and
(stage 3) the consumer that turns it into notification requests for the leaders who still owe a report.
"""

REMINDER_DUE = "small_group_report.reminder_due"
# The notifications/ category: the "Weekly report reminders" switch in My profile.
CATEGORY = "report_reminder"
_TEMPLATE = "report.reminder"
