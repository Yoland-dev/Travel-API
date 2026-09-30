# Travel Itinerary Planning & Booking API

A RESTful backend built with Django and Django REST Framework. Users search destinations, plan day-by-day itineraries, book stays and activities, track budgets, and collaborate with companions using owner/editor/viewer roles.

## Technologies
Django 5.2, Django REST Framework, Simple JWT (auth), django-filter, drf-spectacular (Swagger/ReDoc), python-decouple (env config), Pillow (uploads), ReportLab (PDF export), pytest + pytest-django + pytest-cov. SQLite by default; PostgreSQL supported.

## Installation
```bash
git clone <your-repo-url> && cd travel_api
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                              # then edit values
```

## Environment variables (`.env`)
| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django secret (required in production) |
| `DEBUG` | `True` for development |
| `ALLOWED_HOSTS` | Comma-separated hosts |
| `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | Database (default SQLite) |
| `EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL` | Email (console backend by default) |

Settings are split: `travel_api/settings/{base,development,production}.py`. `manage.py` uses development; WSGI/ASGI use production.

## Database setup
SQLite needs nothing. For PostgreSQL create a database, then set `DB_ENGINE=django.db.backends.postgresql` and the `DB_*` values.
```bash
python manage.py migrate            # apply migrations
python manage.py createsuperuser    # admin account (/admin/)
python manage.py seed_data          # optional demo data + user demo / DemoPass123!
python manage.py runserver          # http://127.0.0.1:8000
```

## Running tests
```bash
pytest                 # 215 tests, ~97% coverage (report printed automatically)
python manage.py test  # unittest runner also works
```

## API documentation
Swagger UI `/api/docs/` - ReDoc `/api/redoc/` - OpenAPI schema `/api/schema/`. The full endpoint list with HTTP methods is in [PLANNING.md](PLANNING.md).

## Authentication flow
1. `POST /api/v1/accounts/register/` or `/login/` returns `access` (1 h) and `refresh` (7 d) tokens.
2. Send `Authorization: Bearer <access>` on every request.
3. `POST /api/v1/accounts/token/refresh/` with the refresh token when access expires.
4. `POST /api/v1/accounts/logout/` blacklists the refresh token.
5. Password reset: `password/reset/` emails a uid and token; `password/reset/confirm/` sets the new password.

## Example requests
```bash
# Log in
curl -X POST http://127.0.0.1:8000/api/v1/accounts/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "demo", "password": "DemoPass123!"}'

# Browse beach destinations (public)
curl "http://127.0.0.1:8000/api/v1/destinations/?category=beach&ordering=avg_daily_cost"

# Create an itinerary
curl -X POST http://127.0.0.1:8000/api/v1/itineraries/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title": "Bali escape", "destination": 2, "start_date": "2027-03-01", "end_date": "2027-03-08", "budget": 1800}'

# Share it with a friend as an editor
curl -X POST http://127.0.0.1:8000/api/v1/itineraries/1/share/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"email": "friend@example.com", "role": "editor"}'

# Upload an itinerary PDF
curl -X POST http://127.0.0.1:8000/api/v1/itineraries/1/documents/ \
  -H "Authorization: Bearer $TOKEN" -F "title=Flight plan" -F "file=@plan.pdf"
```
Uploads accept PDF/JPG/PNG up to 5 MB.

## Project structure
```
travel_api/            project: settings/, urls.py, wsgi/asgi
core/                  shared validators, pagination, exception handler, test factories
accounts/              custom User, JWT auth, profile, saved searches
destinations/          destinations, search, recommendations, favourites
itineraries/           trips, day plans, collaboration, documents, audit log, analytics
bookings/              accommodations, activities, bookings, bulk update
reviews/               ratings and reviews
budgets/               category budgets and expenses (signals keep totals in sync)
docs/                  ERD (erd.svg) and its generator
```
Each app holds `models.py`, `serializers.py`, `views.py`, `urls.py`, `tests.py`; some add `permissions.py` and `filters.py`.

## Design notes
- Server-computed values: booking price, status and confirmation code cannot be set by clients.
- A signal creates each trip's `Budget` and refreshes `actual_spent` whenever an expense changes.
- Role checks use prefetched collaborations, avoiding extra queries in list views.

## ERD
![ERD](docs/erd.svg)
