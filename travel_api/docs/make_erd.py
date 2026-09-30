"""Generate docs/erd.svg. Run: python docs/make_erd.py"""
BOX_W, LINE_H = 210, 16
ENTITIES = {
    "User": ("accounts", ["id PK", "username, email (unique)", "travel_preferences (JSON)", "favorite_destinations M2M"]),
    "SavedSearch": ("accounts", ["id PK", "user FK", "search_type, query_params"]),
    "Destination": ("destinations", ["id PK", "name, slug (unique)", "category, climate", "avg_daily_cost"]),
    "Itinerary": ("itineraries", ["id PK", "owner FK, destination FK", "start_date, end_date", "budget, actual_spent", "status, is_public"]),
    "Collaboration": ("itineraries", ["itinerary FK, user FK (unique pair)", "role: viewer/editor/admin"]),
    "DailyPlan": ("itineraries", ["itinerary FK", "day_number, date", "activities M2M"]),
    "ItineraryDocument": ("itineraries", ["itinerary FK, uploaded_by FK", "file (PDF/JPG/PNG)"]),
    "ActivityLog": ("itineraries", ["user FK, itinerary FK", "action, description"]),
    "Accommodation": ("bookings", ["destination FK", "price_per_night, max_guests"]),
    "Activity": ("bookings", ["destination FK", "price, max_participants"]),
    "Booking": ("bookings", ["user FK, itinerary FK", "accommodation FK | activity FK", "price, status"]),
    "Review": ("reviews", ["user FK", "destination | accommodation | activity FK", "rating 1-5"]),
    "Budget": ("budgets", ["itinerary 1:1", "6 category budgets"]),
    "Expense": ("budgets", ["itinerary FK, paid_by FK", "category, amount, date"]),
}
POS = {  # x, y  (Itinerary sits in the middle; its satellites surround it)
    "SavedSearch": (30, 50), "User": (340, 50), "Destination": (650, 50), "Review": (960, 50),
    "Collaboration": (30, 210), "Accommodation": (960, 210),
    "ActivityLog": (30, 340), "Itinerary": (340, 320), "DailyPlan": (650, 240), "Activity": (960, 350),
    "ItineraryDocument": (30, 470), "Booking": (650, 430),
    "Budget": (340, 600), "Expense": (650, 620),
}
COLORS = {"accounts": "#dbeafe", "destinations": "#dcfce7", "itineraries": "#fef3c7", "bookings": "#fce7f3",
          "reviews": "#ede9fe", "budgets": "#ffedd5"}
RELS = [("SavedSearch", "User", "N:1"), ("User", "Destination", "M2M favorites"), ("Itinerary", "User", "owner N:1"),
        ("Itinerary", "Destination", "N:1"), ("Collaboration", "Itinerary", "N:1"), ("Collaboration", "User", "N:1"),
        ("DailyPlan", "Itinerary", "N:1"), ("DailyPlan", "Activity", "M2M"), ("ItineraryDocument", "Itinerary", "N:1"),
        ("ActivityLog", "Itinerary", "N:1"), ("Accommodation", "Destination", "N:1"), ("Activity", "Destination", "N:1"),
        ("Booking", "Itinerary", "N:1"), ("Booking", "Accommodation", "N:1"), ("Booking", "Activity", "N:1"),
        ("Review", "Destination", "N:1"), ("Budget", "Itinerary", "1:1"), ("Expense", "Itinerary", "N:1"),
        ("Booking", "User", "N:1")]


def box(name):
    x, y = POS[name]
    return x, y, BOX_W, 30 + LINE_H * len(ENTITIES[name][1])


def centre(name):
    x, y, w, h = box(name)
    return x + w / 2, y + h / 2


def edge(name, toward):
    """Point where the centre-to-centre line leaves the box (so lines end on borders)."""
    x, y, w, h = box(name)
    cx, cy = centre(name)
    dx, dy = toward[0] - cx, toward[1] - cy
    scale = min((w / 2) / abs(dx) if dx else 1e9, (h / 2) / abs(dy) if dy else 1e9)
    return cx + dx * scale, cy + dy * scale


DASHED = {("Booking", "User"), ("Collaboration", "User")}
out = ['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" font-family="Helvetica,Arial,sans-serif" font-size="12">',
       '<rect width="100%" height="100%" fill="white"/>',
       '<text x="30" y="28" font-size="16" font-weight="bold">Travel Itinerary API - Entity Relationship Diagram</text>',
       '<text x="30" y="784" font-size="10" fill="#64748b">Dashed lines: secondary links to User (Review.user also links to User). '
       'Booking targets one of Accommodation/Activity; Review targets one of Destination/Accommodation/Activity.</text>']
labels = []
for a, b, label in RELS:
    p1, p2 = edge(a, centre(b)), edge(b, centre(a))
    dash = ' stroke-dasharray="5,4"' if (a, b) in DASHED else ""
    out.append(f'<line x1="{p1[0]:.1f}" y1="{p1[1]:.1f}" x2="{p2[0]:.1f}" y2="{p2[1]:.1f}" stroke="#64748b" stroke-width="1.4"{dash}/>')
    labels.append(((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2, label))
for mx, my, label in labels:
    w = 6.2 * len(label) + 8
    out.append(f'<rect x="{mx - w / 2:.1f}" y="{my - 8:.1f}" width="{w:.1f}" height="14" rx="7" fill="white" stroke="#cbd5e1"/>')
    out.append(f'<text x="{mx:.1f}" y="{my + 3:.1f}" fill="#334155" font-size="10" text-anchor="middle">{label}</text>')
for name, (app, fields) in ENTITIES.items():
    x, y, w, h = box(name)
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{COLORS[app]}" stroke="#334155"/>')
    out.append(f'<text x="{x + 8}" y="{y + 18}" font-weight="bold">{name}</text>')
    out.append(f'<text x="{x + w - 8}" y="{y + 18}" font-size="10" fill="#64748b" text-anchor="end">{app}</text>')
    out.append(f'<line x1="{x}" y1="{y + 24}" x2="{x + w}" y2="{y + 24}" stroke="#334155"/>')
    for i, f in enumerate(fields):
        out.append(f'<text x="{x + 8}" y="{y + 40 + i * LINE_H}" font-size="11">{f}</text>')
out.append("</svg>")
open("docs/erd.svg", "w").write("\n".join(out))
print("wrote docs/erd.svg")
