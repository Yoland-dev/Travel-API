"""Generate a printable PDF for an itinerary (reportlab)."""
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


def build_itinerary_pdf(itinerary):
    """Return the PDF bytes for an itinerary with its day-by-day plan."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, title=itinerary.title)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(itinerary.title, styles["Title"]),
        Paragraph(f"{itinerary.destination.name}, {itinerary.destination.country}", styles["Heading2"]),
        Paragraph(f"{itinerary.start_date} to {itinerary.end_date} ({itinerary.duration_days} days)", styles["Normal"]),
        Paragraph(f"Budget: ${itinerary.budget} | Spent: ${itinerary.actual_spent} | Status: {itinerary.status}",
                  styles["Normal"]),
        Spacer(1, 16),
    ]
    if itinerary.description:
        story += [Paragraph(itinerary.description, styles["BodyText"]), Spacer(1, 12)]
    for plan in itinerary.daily_plans.all():
        story.append(Paragraph(f"Day {plan.day_number} - {plan.date}: {plan.title}", styles["Heading3"]))
        if plan.notes:
            story.append(Paragraph(plan.notes, styles["BodyText"]))
        for act in plan.activities.all():
            story.append(Paragraph(f"&bull; {act.name} ({act.duration_hours}h, ${act.price})", styles["Normal"]))
        story.append(Spacer(1, 8))
    doc.build(story)
    return buffer.getvalue()
