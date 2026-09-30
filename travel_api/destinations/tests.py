
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from bookings.models import Booking
from core.testing import BaseAPITest, make_activity, make_destination, make_itinerary, make_user, pdf_file, png_file
from reviews.models import Review

from .models import Destination
from .serializers import DestinationDetailSerializer

URL = "/api/v1/destinations/"


class DestinationModelTests(APITestCase):
    def test_slug_generated_and_str(self):
        dest = make_destination("Cape Town", "South Africa")
        self.assertEqual(dest.slug, "cape-town")
        self.assertEqual(str(dest), "Cape Town, South Africa")

    def test_budget_category(self):
        self.assertEqual(make_destination("A", avg_daily_cost=50).budget_category(), "budget")
        self.assertEqual(make_destination("B", avg_daily_cost=150).budget_category(), "moderate")
        self.assertEqual(make_destination("C", avg_daily_cost=400).budget_category(), "luxury")

    def test_average_rating_from_reviews(self):
        dest = make_destination()
        for i, rating in enumerate((5, 3)):
            Review.objects.create(user=make_user(f"u{i}"), destination=dest, rating=rating, title="t",
                                  content="c", visit_date="2024-01-01")
        self.assertEqual(dest.average_rating, 4.0)
        self.assertEqual(dest.review_count, 2)

    def test_average_rating_zero_without_reviews(self):
        self.assertEqual(make_destination().average_rating, 0)


class DestinationSerializerTests(APITestCase):
    def test_detail_serializer_includes_computed_fields(self):
        dest = make_destination()
        make_activity(dest)
        data = DestinationDetailSerializer(dest).data
        self.assertEqual(data["total_itineraries"], 0)
        self.assertEqual(len(data["top_activities"]), 1)
        self.assertEqual(data["budget_category"], "moderate")


class DestinationAPITests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.paris = make_destination("Paris", "France", category="city", avg_daily_cost=200)
        self.bali = make_destination("Bali", "Indonesia", category="beach", climate="tropical", avg_daily_cost=60)
        self.dubai = make_destination("Dubai", "UAE", category="city", climate="dry", avg_daily_cost=400)

    def test_list_is_public(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 3)

    def test_filter_by_category_and_climate(self):
        self.assertEqual(self.client.get(URL, {"category": "beach"}).data["count"], 1)
        self.assertEqual(self.client.get(URL, {"climate": "dry"}).data["results"][0]["name"], "Dubai")

    def test_filter_budget_range(self):
        self.assertEqual(self.client.get(URL, {"budget_range": "budget"}).data["results"][0]["name"], "Bali")
        self.assertEqual(self.client.get(URL, {"budget_range": "luxury"}).data["results"][0]["name"], "Dubai")

    def test_filter_min_max_cost(self):
        self.assertEqual(self.client.get(URL, {"min_cost": 100, "max_cost": 300}).data["count"], 1)

    def test_search_and_ordering(self):
        self.assertEqual(self.client.get(URL, {"search": "indonesia"}).data["count"], 1)
        names = [d["name"] for d in self.client.get(URL, {"ordering": "-avg_daily_cost"}).data["results"]]
        self.assertEqual(names, ["Dubai", "Paris", "Bali"])

    def test_inactive_destinations_hidden(self):
        Destination.objects.filter(pk=self.bali.pk).update(is_active=False)
        self.assertEqual(self.client.get(URL).data["count"], 2)

    def test_retrieve_detail_and_slug(self):
        self.assertEqual(self.client.get(f"{URL}{self.paris.pk}/").status_code, 200)
        by_slug = self.client.get(f"{URL}slug/bali/")
        self.assertEqual(by_slug.data["name"], "Bali")
        self.assertEqual(self.client.get(f"{URL}slug/nowhere/").status_code, 404)

    def test_popular_activities_ranked_by_bookings(self):
        popular = make_activity(self.paris, name="Louvre")
        make_activity(self.paris, name="Seine Cruise")
        owner = make_user("booker")
        trip = make_itinerary(owner, self.paris)
        for _ in range(2):
            Booking.objects.create(user=owner, itinerary=trip, activity=popular, booking_date=trip.start_date, price=50)
        response = self.client.get(f"{URL}{self.paris.pk}/popular_activities/")
        self.assertEqual([a["name"] for a in response.data], ["Louvre", "Seine Cruise"])
        self.assertEqual(response.data[0]["booking_count"], 2)

    def test_weather_info(self):
        response = self.client.get(f"{URL}{self.bali.pk}/weather_info/")
        self.assertEqual(response.data["climate"], "tropical")
        self.assertIn("seasons", response.data)

    def test_search_view_ranks_name_matches_first(self):
        make_destination("Parisian Alps", "France", category="mountain")
        response = self.client.get(f"{URL}search/", {"q": "paris"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["name"], "Paris")

    def test_search_view_bad_number_400(self):
        self.assertEqual(self.client.get(f"{URL}search/", {"min_cost": "abc"}).status_code, 400)

    def test_search_view_sort_by_cost(self):
        names = [d["name"] for d in self.client.get(f"{URL}search/", {"sort": "cost"}).data["results"]]
        self.assertEqual(names[0], "Bali")

    def test_saving_search_requires_login(self):
        self.assertIn(self.client.post(f"{URL}search/", {"name": "x", "query_params": {}}, format="json").status_code, (401, 403))
        self.client.force_authenticate(make_user("saver"))
        response = self.client.post(f"{URL}search/", {"name": "Cheap beaches", "query_params": {"max_cost": 100}}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["search_type"], "destination")


class DestinationUploadTests(BaseAPITest):
    def setUp(self):
        super().setUp()
        self.admin = make_user("admin", is_staff=True)
        self.url = f"{URL}{self.destination.pk}/upload-image/"

    def test_regular_user_cannot_upload(self):
        response = self.client.post(self.url, {"image": png_file()}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_upload_image(self):
        self.login_as(self.admin)
        response = self.client.post(self.url, {"image": png_file()}, format="multipart")
        self.assertEqual(response.status_code, 200)
        self.destination.refresh_from_db()
        self.assertTrue(self.destination.image.name.startswith("destinations/"))

    def test_upload_rejects_pdf(self):
        self.login_as(self.admin)
        response = self.client.post(self.url, {"image": pdf_file("x.pdf")}, format="multipart")
        self.assertEqual(response.status_code, 400)


class RecommendationTests(APITestCase):
    def setUp(self):
        prefs = {"categories": ["beach"], "climates": ["tropical"], "max_daily_budget": 100}
        self.user = make_user("traveller", travel_preferences=prefs)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.bali = make_destination("Bali", "Indonesia", category="beach", climate="tropical", avg_daily_cost=60)
        self.paris = make_destination("Paris", "France", category="city", avg_daily_cost=200)

    def test_preferences_drive_ranking(self):
        response = self.client.get(f"{URL}recommendations/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["name"], "Bali")
        self.assertTrue(response.data[0]["reasons"])

    def test_visited_destinations_are_excluded(self):
        make_itinerary(self.user, self.bali)
        names = [d["name"] for d in self.client.get(f"{URL}recommendations/").data]
        self.assertNotIn("Bali", names)

    def test_limit_validation(self):
        self.assertEqual(self.client.get(f"{URL}recommendations/", {"limit": "x"}).status_code, 400)
        self.assertEqual(len(self.client.get(f"{URL}recommendations/", {"limit": 1}).data), 1)

    def test_requires_authentication(self):
        self.assertEqual(APIClient().get(f"{URL}recommendations/").status_code, 401)


class FavoritesTests(APITestCase):
    URL = "/api/v1/destinations/favorites/"

    def setUp(self):
        self.user = make_user("fan")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.bali = make_destination("Bali", "Indonesia", category="beach")

    def test_add_list_and_remove(self):
        self.assertEqual(self.client.get(self.URL).data, [])
        added = self.client.post(self.URL, {"destination": self.bali.id})
        self.assertEqual(added.status_code, 201)
        self.assertEqual(added.data[0]["name"], "Bali")
        self.assertEqual(self.client.delete(self.URL, {"destination": self.bali.id}).data, [])

    def test_unknown_destination_404(self):
        self.assertEqual(self.client.post(self.URL, {"destination": 999}).status_code, 404)

    def test_requires_login(self):
        self.assertEqual(APIClient().get(self.URL).status_code, 401)

    def test_favorites_influence_recommendations(self):
        self.client.post(self.URL, {"destination": self.bali.id})
        make_destination("Phuket", "Thailand", category="beach")
        make_destination("Oslo", "Norway", category="city")
        top = self.client.get("/api/v1/destinations/recommendations/").data[0]
        self.assertEqual(top["name"], "Phuket")
