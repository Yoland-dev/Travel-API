# Planning Document - Travel Itinerary Planning & Booking API

## 1. ERD
![ERD](docs/erd.svg)

14 models in 6 apps. Key relations: `Itinerary` 1:1 `Budget`; `Itinerary` M2M `User` through `Collaboration` (role); `DailyPlan` M2M `Activity`; `User` M2M `Destination` (favourites). A `Booking` targets one accommodation *or* activity; a `Review` targets exactly one of three items.

## 2. Endpoints (all under `/api/v1/`)
| Area | Endpoints |
|---|---|
| Accounts | POST `accounts/register/`, `login/`, `logout/`, `token/refresh/`, `password/change/`, `password/reset/`, `password/reset/confirm/`; GET/PUT/PATCH `accounts/profile/`; CRUD `saved-searches/` |
| Destinations | GET `destinations/` (+ `{id}/`, `slug/{slug}/`, `search/`, `recommendations/`, `{id}/popular_activities/`, `{id}/weather_info/`); POST `{id}/upload-image/` (admin); GET/POST/DELETE `destinations/favorites/` |
| Catalogue | GET `accommodations/`, `activities/` |
| Itineraries | CRUD `itineraries/`; POST `{id}/duplicate/`, `{id}/share/`, `{id}/status/`; GET `{id}/export-pdf/`, `upcoming/`, `search/`, `{id}/report/`, `mine/`; GET/POST `{id}/collaborators/`, PATCH/DELETE `{id}/collaborators/{user}/`; GET/POST `{id}/documents/`, GET/DELETE `{id}/documents/{doc}/`; CRUD `daily-plans/`; GET `activity-logs/`, `analytics/` (+ `budget-summary/`, `destination-preferences/`) |
| Bookings | CRUD `bookings/`; POST `{id}/confirm/`, `{id}/cancel/`, `bulk-update/`; GET/PUT/PATCH/DELETE `bookings/items/{id}/` |
| Reviews | CRUD `reviews/`; POST `{id}/helpful/`; GET `mine/`, `summary/`, `reviews/target/{type}/{id}/` |
| Budgets | CRUD `expenses/` (+ `summary/`); GET/PUT/PATCH `budgets/itinerary/{trip}/` |

## 3. Authentication flow
1. Register or login -> `{access (1h), refresh (7d)}`.
2. Send `Authorization: Bearer <access>`.
3. On expiry POST refresh token to `token/refresh/`.
4. Logout blacklists the refresh token.
5. Reset: request emails uid+token; confirm sets the password.

## 4. Permission matrix
| Action | Owner | Admin | Editor | Viewer | Stranger |
|---|---|---|---|---|---|
| Read trip | yes | yes | yes | yes | public trips only |
| Edit trip, days, budget, expenses, bookings, documents | yes | yes | yes | no (403) | no (404) |
| Change status | yes | yes | yes | no | no |
| Share / manage collaborators, delete trip | yes | no | no | no | no |

Bookings, reviews and saved searches: only their author modifies them. Destinations and catalogue: public read; uploads admin-only.

## 5. URL structure
App routes (`itineraries/search/`, nested collaborators/documents) sit **before** the `DefaultRouter`, so fixed words are never read as a pk. Each app has `app_name` for namespacing.

## 6. Testing strategy
| Layer | Approach |
|---|---|
| Models | Validation (`clean`), business methods, refund/price maths |
| Serializers | Field/object validation, read-only enforcement |
| Views | `APITestCase` + `force_authenticate`: status codes, filters, pagination |
| Permissions | Every role against every write endpoint; direct class tests |
| Uploads | Valid, wrong type, oversize (temp `MEDIA_ROOT`, cleaned in `tearDown`) |
| Errors | 400/401/403/404 shapes; DB errors mapped by handler |

Goal: 200+ tests, 90%+ coverage; separate test DB; MD5 hasher for speed.
