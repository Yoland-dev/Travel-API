from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from rest_framework import status

from core.testing import TODAY, BaseAPITest, make_accommodation, make_activity, make_destination

from .models import Booking
from .serializers import BookingSerializer

URL = "/api/v1/bookings/"


class BookingModelTests(BaseAPITest):
    def setUp(self):
        super().setUp()
        self.hotel = make_accommodation(self.destination)
        self.tour = make_activity(self.destination)
        start = TODAY + timedelta(days=40)
        self.stay = Booking.objects.create(
            user=self.owner, itinerary=self.itinerary, accommodation=self.hotel, booking_date=start, check_in=start,
            check_out=start + timedelta(days=3), guests_count=2, price=300)

    def test_str(self):
        self.assertEqual(str(self.stay), "Booking: Hotel Lumiere")

    def test_clean_requires_exactly_one_target(self):
        with self.assertRaises(ValidationError):
            Booking(user=self.owner, itinerary=self.itinerary, booking_date=TODAY).clean()
        with self.assertRaises(ValidationError):
            Booking(user=self.owner, itinerary=self.itinerary, booking_date=TODAY, accommodation=self.hotel,
                    activity=self.tour).clean()

    def test_clean_checks_dates_capacity_and_destination(self):
        bad_dates = Booking(itinerary=self.itinerary, accommodation=self.hotel, booking_date=TODAY, check_in=TODAY,
                            check_out=TODAY)
        with self.assertRaises(ValidationError):
            bad_dates.clean()
        too_many = Booking(itinerary=self.itinerary, accommodation=self.hotel, booking_date=TODAY, check_in=TODAY,
                           check_out=TODAY + timedelta(days=1), guests_count=9)
        with self.assertRaises(ValidationError):
            too_many.clean()
        elsewhere = make_activity(make_destination("Rome", "Italy"))
        with self.assertRaises(ValidationError):
            Booking(itinerary=self.itinerary, activity=elsewhere, booking_date=TODAY).clean()

    def test_price_calculation(self):
        self.assertEqual(self.stay.nights, 3)
        self.assertEqual(self.stay.calculate_price(), Decimal("300.00"))
        group = Booking(activity=self.tour, guests_count=3, booking_date=TODAY)
        self.assertEqual(group.calculate_price(), Decimal("150.00"))

    def test_refund_policy(self):
        self.assertEqual(self.stay.calculate_refund(today=self.stay.check_in - timedelta(days=10)), Decimal("300.00"))
        self.assertEqual(self.stay.calculate_refund(today=self.stay.check_in - timedelta(days=3)), Decimal("150.00"))
        self.assertEqual(self.stay.calculate_refund(today=self.stay.check_in - timedelta(days=1)), Decimal("0.00"))

    def test_confirm_and_cancel_lifecycle(self):
        self.stay.confirm()
        self.assertEqual(self.stay.status, "confirmed")
        self.assertTrue(self.stay.confirmation_code.startswith("TRV-"))
        with self.assertRaises(ValidationError):
            self.stay.confirm()
        self.assertEqual(self.stay.cancel(), Decimal("300.00"))
        with self.assertRaises(ValidationError):
            self.stay.cancel()


class BookingSerializerTests(BaseAPITest):
    def _ctx(self, user):
        from django.test import RequestFactory
        request = RequestFactory().post("/")
        request.user = user
        return {"request": request}

    def test_accommodation_booking_date_defaults_to_check_in(self):
        hotel = make_accommodation(self.destination)
        data = {"itinerary": self.itinerary.id, "accommodation": hotel.id, "check_in": str(TODAY + timedelta(days=35)),
                "check_out": str(TODAY + timedelta(days=37))}
        s = BookingSerializer(data=data, context=self._ctx(self.owner))
        self.assertTrue(s.is_valid(), s.errors)
        self.assertEqual(s.validated_data["booking_date"], TODAY + timedelta(days=35))

    def test_activity_requires_booking_date(self):
        tour = make_activity(self.destination)
        s = BookingSerializer(data={"itinerary": self.itinerary.id, "activity": tour.id}, context=self._ctx(self.owner))
        self.assertFalse(s.is_valid())

    def test_viewer_cannot_book_for_trip(self):
        self.itinerary.add_collaborator(self.other, "viewer")
        tour = make_activity(self.destination)
        s = BookingSerializer(data={"itinerary": self.itinerary.id, "activity": tour.id, "booking_date": str(TODAY)},
                              context=self._ctx(self.other))
        self.assertFalse(s.is_valid())
        self.assertIn("itinerary", s.errors)


class BookingAPITests(BaseAPITest):
    def setUp(self):
        super().setUp()
        self.hotel = make_accommodation(self.destination)
        self.tour = make_activity(self.destination)
        self.check_in = TODAY + timedelta(days=35)

    def _stay(self, **kw):
        data = {"itinerary": self.itinerary.id, "accommodation": self.hotel.id, "check_in": str(self.check_in),
                "check_out": str(self.check_in + timedelta(days=2)), "guests_count": 2}
        data.update(kw)
        return self.client.post(URL, data)

    def _activity(self, **kw):
        data = {"itinerary": self.itinerary.id, "activity": self.tour.id, "booking_date": str(self.check_in), "guests_count": 2}
        data.update(kw)
        return self.client.post(URL, data)

    def test_create_accommodation_booking_computes_price(self):
        response = self._stay()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(response.data["price"]), Decimal("200.00"))
        self.assertEqual(response.data["status"], "pending")
        self.assertEqual(response.data["item_name"], "Hotel Lumiere")

    def test_create_activity_booking(self):
        response = self._activity()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Decimal(response.data["price"]), Decimal("100.00"))

    def test_client_cannot_set_price_or_status(self):
        response = self._activity(price=1, status="confirmed")
        self.assertEqual(response.data["status"], "pending")
        self.assertEqual(Decimal(response.data["price"]), Decimal("100.00"))

    def test_both_targets_rejected(self):
        self.assertEqual(self._activity(accommodation=self.hotel.id).status_code, 400)

    def test_neither_target_rejected(self):
        response = self.client.post(URL, {"itinerary": self.itinerary.id, "booking_date": str(TODAY)})
        self.assertEqual(response.status_code, 400)

    def test_too_many_guests_rejected(self):
        self.assertEqual(self._stay(guests_count=10).status_code, 400)

    def test_unavailable_item_rejected(self):
        self.tour.is_available = False
        self.tour.save()
        self.assertEqual(self._activity().status_code, 400)

    def test_list_shows_only_own_bookings(self):
        self._activity()
        self.login_as(self.other)
        self.assertEqual(self.client.get(URL).data["count"], 0)

    def test_editor_collaborator_can_book(self):
        self.itinerary.add_collaborator(self.other, "editor")
        self.login_as(self.other)
        self.assertEqual(self._activity().status_code, 201)

    def test_viewer_collaborator_cannot_book(self):
        self.itinerary.add_collaborator(self.other, "viewer")
        self.login_as(self.other)
        self.assertEqual(self._activity().status_code, 400)

    def test_filters(self):
        self._stay()
        self._activity()
        self.assertEqual(self.client.get(URL, {"booking_type": "activity"}).data["count"], 1)
        self.assertEqual(self.client.get(URL, {"status": "confirmed"}).data["count"], 0)

    def test_confirm_action(self):
        booking_id = self._activity().data["id"]
        response = self.client.post(f"{URL}{booking_id}/confirm/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "confirmed")
        self.assertEqual(self.client.post(f"{URL}{booking_id}/confirm/").status_code, 400)

    def test_cancel_action_returns_refund(self):
        booking_id = self._activity().data["id"]
        response = self.client.post(f"{URL}{booking_id}/cancel/")
        self.assertEqual(response.data["refund_amount"], "100.00")
        self.assertEqual(self.client.post(f"{URL}{booking_id}/cancel/").status_code, 400)

    def test_cannot_modify_cancelled_booking(self):
        booking_id = self._activity().data["id"]
        self.client.post(f"{URL}{booking_id}/cancel/")
        self.assertEqual(self.client.patch(f"{URL}{booking_id}/", {"notes": "x"}).status_code, 400)

    def test_update_recomputes_price(self):
        booking_id = self._activity().data["id"]
        response = self.client.patch(f"{URL}{booking_id}/", {"guests_count": 4})
        self.assertEqual(Decimal(response.data["price"]), Decimal("200.00"))

    def test_other_user_cannot_touch_booking(self):
        booking_id = self._activity().data["id"]
        self.login_as(self.other)
        self.assertEqual(self.client.post(f"{URL}{booking_id}/cancel/").status_code, 404)

    def test_retrieve_has_nested_details_and_refund_estimate(self):
        booking_id = self._activity().data["id"]
        data = self.client.get(f"{URL}{booking_id}/").data
        self.assertEqual(data["activity"]["name"], "Eiffel Tour")
        self.assertEqual(data["refund_estimate"], "100.00")

    def test_delete_booking(self):
        booking_id = self._activity().data["id"]
        self.assertEqual(self.client.delete(f"{URL}{booking_id}/").status_code, 204)

    def test_detail_view_get_patch_delete(self):
        booking_id = self._activity().data["id"]
        url = f"{URL}items/{booking_id}/"
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.patch(url, {"notes": "window seat"}).data["notes"], "window seat")
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.login_as(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_unauthenticated_rejected(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(URL).status_code, 401)


class BulkUpdateTests(BaseAPITest):
    def setUp(self):
        super().setUp()
        tour = make_activity(self.destination)
        self.ids = [Booking.objects.create(user=self.owner, itinerary=self.itinerary, activity=tour,
                                           booking_date=TODAY + timedelta(days=30), price=50).id for _ in range(3)]
        self.url = f"{URL}bulk-update/"

    def test_bulk_confirm_all(self):
        payload = {"updates": [{"id": i, "action": "confirm"} for i in self.ids]}
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["success_count"], 3)
        self.assertEqual(Booking.objects.filter(status="confirmed").count(), 3)

    def test_partial_failure_is_reported(self):
        Booking.objects.filter(pk=self.ids[0]).update(status="cancelled")
        payload = {"updates": [{"id": i, "action": "confirm"} for i in self.ids] + [{"id": 9999, "action": "cancel"}]}
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.data["success_count"], 2)
        self.assertEqual(response.data["failure_count"], 2)

    def test_all_or_nothing_rolls_back(self):
        payload = {"updates": [{"id": self.ids[0], "action": "confirm"}, {"id": 9999, "action": "confirm"}],
                   "all_or_nothing": True}
        response = self.client.post(self.url, payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.data["rolled_back"])
        self.assertEqual(Booking.objects.get(pk=self.ids[0]).status, "pending")

    def test_cannot_update_someone_elses_booking(self):
        self.login_as(self.other)
        response = self.client.post(self.url, {"updates": [{"id": self.ids[0], "action": "cancel"}]}, format="json")
        self.assertEqual(response.data["success_count"], 0)
        self.assertEqual(Booking.objects.get(pk=self.ids[0]).status, "pending")

    def test_validation_errors(self):
        self.assertEqual(self.client.post(self.url, {"updates": []}, format="json").status_code, 400)
        bad_action = {"updates": [{"id": 1, "action": "explode"}]}
        self.assertEqual(self.client.post(self.url, bad_action, format="json").status_code, 400)
        too_many = {"updates": [{"id": 1, "action": "confirm"}] * 51}
        self.assertEqual(self.client.post(self.url, too_many, format="json").status_code, 400)

    def test_notes_are_saved(self):
        payload = {"updates": [{"id": self.ids[0], "action": "confirm", "notes": "vegetarian"}]}
        self.client.post(self.url, payload, format="json")
        self.assertEqual(Booking.objects.get(pk=self.ids[0]).notes, "vegetarian")


class CatalogueTests(BaseAPITest):
    def test_accommodations_public_with_filters(self):
        make_accommodation(self.destination, name="Cheap", price_per_night=40)
        make_accommodation(self.destination, name="Fancy", price_per_night=500, accommodation_type="resort")
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get("/api/v1/accommodations/").data["count"], 2)
        self.assertEqual(self.client.get("/api/v1/accommodations/", {"max_price": 100}).data["results"][0]["name"], "Cheap")
        self.assertEqual(self.client.get("/api/v1/accommodations/", {"accommodation_type": "resort"}).data["count"], 1)

    def test_unavailable_accommodation_hidden(self):
        make_accommodation(self.destination, is_available=False)
        self.assertEqual(self.client.get("/api/v1/accommodations/").data["count"], 0)

    def test_activities_public_with_filters(self):
        make_activity(self.destination, name="Museum", category="attraction", price=20)
        make_activity(self.destination, name="Kayak", category="outdoor", price=80)
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get("/api/v1/activities/", {"category": "outdoor"}).data["count"], 1)
        self.assertEqual(self.client.get("/api/v1/activities/", {"ordering": "-price"}).data["results"][0]["name"], "Kayak")

    def test_catalogue_is_read_only(self):
        response = self.client.post("/api/v1/activities/", {"name": "x"})
        self.assertEqual(response.status_code, 405)
