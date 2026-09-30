from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import RequestFactory
from rest_framework import status

from bookings.models import Booking
from budgets.models import Expense
from core.testing import (
    TODAY, BaseAPITest, make_accommodation, make_activity, make_destination, make_itinerary, make_user, pdf_file,
)

from .models import ActivityLog, Collaboration, DailyPlan, Itinerary
from .permissions import CanEditItinerary, CanEditRelatedItinerary, IsTripOwner, IsTripOwnerOrCollaborator
from .serializers import ItinerarySerializer, SetStatusSerializer

URL = "/api/v1/itineraries/"


class ItineraryModelTests(BaseAPITest):
    def test_str_duration_and_budget_remaining(self):
        self.assertEqual(str(self.itinerary), "Paris Trip - Paris")
        self.assertEqual(self.itinerary.duration_days, 7)
        self.assertEqual(self.itinerary.budget_remaining, Decimal("2000"))

    def test_clean_rejects_reversed_dates(self):
        self.itinerary.end_date = self.itinerary.start_date - timedelta(days=1)
        with self.assertRaises(ValidationError):
            self.itinerary.clean()

    def test_add_collaborator_and_roles(self):
        self.itinerary.add_collaborator(self.other, role="editor")
        self.assertEqual(self.itinerary.get_user_role(self.owner), "owner")
        self.assertEqual(self.itinerary.get_user_role(self.other), "editor")
        self.assertIsNone(self.itinerary.get_user_role(make_user("stranger")))
        self.assertTrue(self.itinerary.can_edit(self.other))

    def test_add_collaborator_twice_updates_role(self):
        self.itinerary.add_collaborator(self.other, "viewer")
        self.itinerary.add_collaborator(self.other, "admin")
        self.assertEqual(Collaboration.objects.filter(itinerary=self.itinerary).count(), 1)
        self.assertEqual(self.itinerary.get_user_role(self.other), "admin")

    def test_owner_cannot_be_collaborator(self):
        with self.assertRaises(ValidationError):
            Collaboration(itinerary=self.itinerary, user=self.owner).clean()

    def test_status_transitions(self):
        self.assertTrue(self.itinerary.can_transition_to("booked"))
        self.assertFalse(self.itinerary.can_transition_to("completed"))

    def test_daily_plan_date_must_be_in_range(self):
        plan = DailyPlan(itinerary=self.itinerary, day_number=1, title="x", date=TODAY - timedelta(days=100))
        with self.assertRaises(ValidationError):
            plan.clean()

    def test_recalculate_spent_and_over_budget(self):
        Expense.objects.create(itinerary=self.itinerary, category="food", description="d", amount=2500, date=TODAY)
        self.itinerary.refresh_from_db()
        self.assertEqual(self.itinerary.actual_spent, Decimal("2500"))
        self.assertTrue(self.itinerary.is_over_budget)


class ItineraryCRUDTests(BaseAPITest):
    def test_list_itineraries(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["my_role"], "owner")

    def test_create_itinerary(self):
        data = {"title": "Rome Adventure", "destination": self.destination.id,
                "start_date": str(TODAY + timedelta(days=60)), "end_date": str(TODAY + timedelta(days=70)), "budget": 3000}
        response = self.client.post(URL, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Itinerary.objects.count(), 2)
        created = Itinerary.objects.get(title="Rome Adventure")
        self.assertEqual(created.owner, self.owner)
        self.assertTrue(hasattr(created, "budget_detail"))  # auto-created by signal
        self.assertTrue(ActivityLog.objects.filter(itinerary=created, action="created").exists())

    def test_create_rejects_bad_dates(self):
        data = {"title": "Bad", "destination": self.destination.id, "start_date": "2030-05-10",
                "end_date": "2030-05-01", "budget": 100}
        response = self.client.post(URL, data)
        self.assertEqual(response.status_code, 400)
        self.assertIn("end_date", response.data)

    def test_create_rejects_non_positive_budget(self):
        data = {"title": "Free", "destination": self.destination.id, "start_date": "2030-05-01",
                "end_date": "2030-05-05", "budget": 0}
        self.assertEqual(self.client.post(URL, data).status_code, 400)

    def test_status_cannot_be_set_on_create(self):
        data = {"title": "Sneaky", "destination": self.destination.id, "start_date": "2030-05-01",
                "end_date": "2030-05-05", "budget": 100, "status": "completed"}
        self.client.post(URL, data)
        self.assertEqual(Itinerary.objects.get(title="Sneaky").status, "planning")

    def test_retrieve_has_nested_objects(self):
        response = self.client.get(f"{URL}{self.itinerary.id}/")
        self.assertEqual(response.data["destination"]["name"], "Paris")
        self.assertIn("daily_plans", response.data)
        self.assertEqual(response.data["bookings_count"], 0)

    def test_update_itinerary(self):
        response = self.client.patch(f"{URL}{self.itinerary.id}/", {"budget": 2500})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.itinerary.refresh_from_db()
        self.assertEqual(self.itinerary.budget, 2500)
        self.assertTrue(ActivityLog.objects.filter(action="updated").exists())

    def test_delete_itinerary(self):
        response = self.client.delete(f"{URL}{self.itinerary.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Itinerary.objects.count(), 0)

    def test_unauthorized_access(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(URL).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_cannot_update_others_itinerary(self):
        self.login_as(self.other)
        response = self.client.patch(f"{URL}{self.itinerary.id}/", {"budget": 5000})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_only_shows_accessible_trips(self):
        make_itinerary(self.other, self.destination, title="Private")
        titles = [t["title"] for t in self.client.get(URL).data["results"]]
        self.assertEqual(titles, ["Paris Trip"])

    def test_filters_search_and_ordering(self):
        make_itinerary(self.owner, self.destination, title="Cheap Rome", budget=500, status="booked")
        self.assertEqual(self.client.get(URL, {"status": "booked"}).data["count"], 1)
        self.assertEqual(self.client.get(URL, {"min_budget": 1000}).data["count"], 1)
        self.assertEqual(self.client.get(URL, {"search": "rome"}).data["count"], 1)
        first = self.client.get(URL, {"ordering": "budget"}).data["results"][0]
        self.assertEqual(first["title"], "Cheap Rome")

    def test_mine_list_and_create_view(self):
        make_itinerary(self.other, self.destination, title="Not mine")
        self.assertEqual(self.client.get(f"{URL}mine/").data["count"], 1)
        data = {"title": "Via CBV", "destination": self.destination.id, "start_date": "2030-01-01",
                "end_date": "2030-01-05", "budget": 900}
        self.assertEqual(self.client.post(f"{URL}mine/", data).status_code, 201)


class RolePermissionTests(BaseAPITest):
    def setUp(self):
        super().setUp()
        self.editor, self.viewer = make_user("editor"), make_user("viewer")
        self.itinerary.add_collaborator(self.editor, "editor")
        self.itinerary.add_collaborator(self.viewer, "viewer")

    def test_owner_can_edit(self):
        self.assertEqual(self.client.patch(f"{URL}{self.itinerary.id}/", {"title": "Updated"}).status_code, 200)

    def test_editor_can_edit(self):
        self.login_as(self.editor)
        response = self.client.patch(f"{URL}{self.itinerary.id}/", {"title": "Updated by Collab"})
        self.assertEqual(response.status_code, 200)

    def test_viewer_can_read_but_not_edit(self):
        self.login_as(self.viewer)
        self.assertEqual(self.client.get(f"{URL}{self.itinerary.id}/").status_code, 200)
        self.assertEqual(self.client.patch(f"{URL}{self.itinerary.id}/", {"title": "x"}).status_code, 403)

    def test_only_owner_can_delete(self):
        self.login_as(self.editor)
        self.assertEqual(self.client.delete(f"{URL}{self.itinerary.id}/").status_code, 403)
        self.assertTrue(Itinerary.objects.filter(pk=self.itinerary.pk).exists())

    def test_shared_trip_appears_in_collaborator_list(self):
        self.login_as(self.viewer)
        self.assertEqual(self.client.get(URL).data["results"][0]["my_role"], "viewer")

    def test_public_trip_is_readable_by_anyone(self):
        Itinerary.objects.filter(pk=self.itinerary.pk).update(is_public=True)
        self.login_as(self.other)
        self.assertEqual(self.client.get(f"{URL}{self.itinerary.id}/").status_code, 200)
        # public trips are read-only for strangers: they are not in the write queryset
        self.assertEqual(self.client.patch(f"{URL}{self.itinerary.id}/", {"title": "x"}).status_code, 404)

    def test_permission_classes_directly(self):
        rf = RequestFactory()
        get, patch = rf.get("/"), rf.patch("/")
        get.user = patch.user = self.viewer
        self.assertTrue(IsTripOwnerOrCollaborator().has_object_permission(get, None, self.itinerary))
        self.assertFalse(IsTripOwnerOrCollaborator().has_object_permission(patch, None, self.itinerary))
        self.assertFalse(CanEditItinerary().has_object_permission(patch, None, self.itinerary))
        self.assertFalse(IsTripOwner().has_object_permission(patch, None, self.itinerary))
        patch.user = self.editor
        self.assertTrue(CanEditRelatedItinerary().has_object_permission(patch, None, self.itinerary))


class ItineraryActionTests(BaseAPITest):
    def test_duplicate_copies_days_and_shifts_dates(self):
        activity = make_activity(self.destination)
        plan = DailyPlan.objects.create(itinerary=self.itinerary, day_number=1, date=self.itinerary.start_date, title="Arrive")
        plan.activities.add(activity)
        new_start = TODAY + timedelta(days=90)
        response = self.client.post(f"{URL}{self.itinerary.id}/duplicate/", {"start_date": str(new_start)})
        self.assertEqual(response.status_code, 201)
        copy = Itinerary.objects.get(pk=response.data["id"])
        self.assertEqual(copy.start_date, new_start)
        self.assertEqual(copy.status, "planning")
        self.assertEqual(copy.daily_plans.get().activities.count(), 1)

    def test_duplicate_bad_date_400(self):
        self.assertEqual(self.client.post(f"{URL}{self.itinerary.id}/duplicate/", {"start_date": "nope"}).status_code, 400)

    def test_export_pdf(self):
        response = self.client.get(f"{URL}{self.itinerary.id}/export-pdf/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_export_pdf_with_daily_plans_and_activities(self):
        self.itinerary.description = "Spring break in Paris"
        self.itinerary.save()
        plan = DailyPlan.objects.create(itinerary=self.itinerary, day_number=1, date=self.itinerary.start_date,
                                        title="Arrive", notes="Check in early")
        plan.activities.add(make_activity(self.destination))
        response = self.client.get(f"{URL}{self.itinerary.id}/export-pdf/")
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.content), 500)

    def test_share_action(self):
        response = self.client.post(f"{URL}{self.itinerary.id}/share/", {"email": "other@example.com", "role": "editor"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.itinerary.get_user_role(self.other), "editor")

    def test_share_unknown_user_and_owner(self):
        self.assertEqual(self.client.post(f"{URL}{self.itinerary.id}/share/", {"email": "ghost@example.com"}).status_code, 400)
        self.assertEqual(self.client.post(f"{URL}{self.itinerary.id}/share/", {"email": "owner@example.com"}).status_code, 400)

    def test_only_owner_can_share(self):
        self.itinerary.add_collaborator(self.other, "editor")
        self.login_as(self.other)
        response = self.client.post(f"{URL}{self.itinerary.id}/share/", {"email": "owner@example.com"})
        self.assertEqual(response.status_code, 403)

    def test_upcoming_trips(self):
        make_itinerary(self.owner, self.destination, title="Past", start_date=TODAY - timedelta(days=40))
        titles = [t["title"] for t in self.client.get(f"{URL}upcoming/").data["results"]]
        self.assertEqual(titles, ["Paris Trip"])

    def test_set_status_valid_and_invalid(self):
        ok = self.client.post(f"{URL}{self.itinerary.id}/status/", {"status": "booked"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.data["status"], "booked")
        bad = self.client.post(f"{URL}{self.itinerary.id}/status/", {"status": "completed"})
        self.assertEqual(bad.status_code, 400)

    def test_status_serializer_uses_transition_rules(self):
        s = SetStatusSerializer(data={"status": "completed"}, context={"itinerary": self.itinerary})
        self.assertFalse(s.is_valid())


class ItinerarySerializerTests(BaseAPITest):
    def test_write_serializer_rejects_inactive_destination(self):
        self.destination.is_active = False
        self.destination.save()
        rf = RequestFactory().post("/")
        rf.user = self.owner
        s = ItinerarySerializer(data={"title": "t", "destination": self.destination.id, "start_date": "2030-01-01",
                                      "end_date": "2030-01-02", "budget": 10}, context={"request": rf})
        self.assertFalse(s.is_valid())
        self.assertIn("destination", s.errors)


class TripSearchAndReportTests(BaseAPITest):
    def test_search_by_text_ranks_title_first(self):
        make_itinerary(self.owner, self.destination, title="Weekend away", description="Trip to Paris")
        response = self.client.get(f"{URL}search/", {"q": "paris"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["results"][0]["title"], "Paris Trip")

    def test_search_filters(self):
        make_itinerary(self.owner, self.destination, title="Pricey", budget=9000)
        self.assertEqual(self.client.get(f"{URL}search/", {"min_budget": 5000}).data["count"], 1)
        self.assertEqual(self.client.get(f"{URL}search/", {"status": "booked"}).data["count"], 0)
        self.assertEqual(self.client.get(f"{URL}search/", {"ordering": "-budget"}).data["results"][0]["title"], "Pricey")

    def test_search_invalid_filter_400(self):
        self.assertEqual(self.client.get(f"{URL}search/", {"min_budget": "abc"}).status_code, 400)
        self.assertEqual(self.client.get(f"{URL}search/", {"start_after": "not-a-date"}).status_code, 400)

    def test_search_includes_public_trips(self):
        make_itinerary(self.other, self.destination, title="Shared publicly", is_public=True)
        self.assertEqual(self.client.get(f"{URL}search/", {"q": "publicly"}).data["count"], 1)

    def test_post_saves_search(self):
        response = self.client.post(f"{URL}search/", {"name": "Cheap trips", "query_params": {"max_budget": 500}}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.owner.saved_searches.count(), 1)
        self.assertEqual(self.client.post(f"{URL}search/", {"query_params": {}}, format="json").status_code, 400)

    def test_report_combines_budget_bookings_and_plans(self):
        acc = make_accommodation(self.destination)
        Booking.objects.create(user=self.owner, itinerary=self.itinerary, accommodation=acc, booking_date=TODAY,
                               check_in=TODAY, check_out=TODAY + timedelta(days=2), price=200)
        Expense.objects.create(itinerary=self.itinerary, category="food", description="Dinner", amount=100, date=TODAY)
        DailyPlan.objects.create(itinerary=self.itinerary, day_number=1, date=self.itinerary.start_date, title="Arrive")
        response = self.client.get(f"{URL}{self.itinerary.id}/report/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["budget"]["spent"], Decimal("100"))
        self.assertEqual(response.data["bookings"]["active_total"], Decimal("200"))
        self.assertEqual(response.data["budget"]["percent_used"], 5.0)
        self.assertEqual(len(response.data["daily_plans"]), 1)

    def test_report_hidden_from_strangers(self):
        self.login_as(self.other)
        self.assertEqual(self.client.get(f"{URL}{self.itinerary.id}/report/").status_code, 404)


class CollaborationViewTests(BaseAPITest):
    def setUp(self):
        super().setUp()
        self.base = f"{URL}{self.itinerary.id}/collaborators/"

    def test_owner_adds_lists_updates_and_removes(self):
        add = self.client.post(self.base, {"email": "other@example.com", "role": "viewer"})
        self.assertEqual(add.status_code, 201)
        self.assertEqual(len(self.client.get(self.base).data), 1)
        patch = self.client.patch(f"{self.base}{self.other.id}/", {"role": "editor"})
        self.assertEqual(patch.data["role"], "editor")
        self.assertEqual(self.client.delete(f"{self.base}{self.other.id}/").status_code, 204)
        self.assertEqual(Collaboration.objects.count(), 0)
        self.assertTrue(ActivityLog.objects.filter(action="unshared").exists())

    def test_adding_twice_is_rejected(self):
        self.itinerary.add_collaborator(self.other)
        self.assertEqual(self.client.post(self.base, {"email": "other@example.com"}).status_code, 400)

    def test_collaborator_can_list_but_not_manage(self):
        self.itinerary.add_collaborator(self.other, "editor")
        self.login_as(self.other)
        self.assertEqual(self.client.get(self.base).status_code, 200)
        self.assertEqual(self.client.post(self.base, {"email": "owner@example.com"}).status_code, 403)
        self.assertEqual(self.client.delete(f"{self.base}{self.other.id}/").status_code, 403)

    def test_stranger_gets_404(self):
        self.login_as(self.other)
        self.assertEqual(self.client.get(self.base).status_code, 404)

    def test_patch_unknown_collaborator_404(self):
        self.assertEqual(self.client.patch(f"{self.base}{self.other.id}/", {"role": "editor"}).status_code, 404)


class DocumentTests(BaseAPITest):
    def setUp(self):
        super().setUp()
        self.url = f"{URL}{self.itinerary.id}/documents/"

    def test_upload_pdf(self):
        response = self.client.post(self.url, {"title": "Plan", "file": pdf_file()}, format="multipart")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["file_type"], "pdf")
        self.assertEqual(self.client.get(self.url).data["count"], 1)

    def test_upload_rejects_wrong_type(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        bad = SimpleUploadedFile("run.exe", b"MZ", content_type="application/octet-stream")
        response = self.client.post(self.url, {"title": "Bad", "file": bad}, format="multipart")
        self.assertEqual(response.status_code, 400)

    def test_upload_rejects_oversized_file(self):
        response = self.client.post(self.url, {"title": "Big", "file": pdf_file(size=6 * 1024 * 1024)}, format="multipart")
        self.assertEqual(response.status_code, 400)

    def test_viewer_cannot_upload_or_delete(self):
        doc = self.client.post(self.url, {"title": "Plan", "file": pdf_file()}, format="multipart").data
        self.itinerary.add_collaborator(self.other, "viewer")
        self.login_as(self.other)
        self.assertEqual(self.client.post(self.url, {"title": "x", "file": pdf_file()}, format="multipart").status_code, 403)
        self.assertEqual(self.client.get(f"{self.url}{doc['id']}/").status_code, 200)
        self.assertEqual(self.client.delete(f"{self.url}{doc['id']}/").status_code, 403)

    def test_owner_can_delete_document(self):
        doc = self.client.post(self.url, {"title": "Plan", "file": pdf_file()}, format="multipart").data
        self.assertEqual(self.client.delete(f"{self.url}{doc['id']}/").status_code, 204)

    def test_stranger_cannot_list(self):
        self.login_as(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)


class DailyPlanTests(BaseAPITest):
    URL = "/api/v1/daily-plans/"

    def _data(self, **kw):
        data = {"itinerary": self.itinerary.id, "day_number": 1, "date": str(self.itinerary.start_date), "title": "Arrival"}
        data.update(kw)
        return data

    def test_create_and_list(self):
        self.assertEqual(self.client.post(self.URL, self._data(), format="json").status_code, 201)
        self.assertEqual(self.client.get(self.URL, {"itinerary": self.itinerary.id}).data["count"], 1)

    def test_date_outside_trip_rejected(self):
        response = self.client.post(self.URL, self._data(date="2001-01-01"), format="json")
        self.assertEqual(response.status_code, 400)

    def test_activity_from_other_destination_rejected(self):
        rome_activity = make_activity(make_destination("Rome", "Italy"))
        response = self.client.post(self.URL, self._data(activities=[rome_activity.id]), format="json")
        self.assertEqual(response.status_code, 400)

    def test_duplicate_day_number_rejected(self):
        self.client.post(self.URL, self._data(), format="json")
        self.assertEqual(self.client.post(self.URL, self._data(), format="json").status_code, 400)

    def test_viewer_cannot_create(self):
        self.itinerary.add_collaborator(self.other, "viewer")
        self.login_as(self.other)
        self.assertEqual(self.client.post(self.URL, self._data(), format="json").status_code, 403)

    def test_editor_can_update(self):
        plan = DailyPlan.objects.create(itinerary=self.itinerary, day_number=1, date=self.itinerary.start_date, title="A")
        self.itinerary.add_collaborator(self.other, "editor")
        self.login_as(self.other)
        self.assertEqual(self.client.patch(f"{self.URL}{plan.id}/", {"title": "Changed"}).status_code, 200)


class AnalyticsAndLogTests(BaseAPITest):
    def test_overall_stats(self):
        make_itinerary(self.owner, self.destination, title="Second", budget=1000, status="booked")
        data = self.client.get("/api/v1/analytics/").data
        self.assertEqual(data["trips"], 2)
        self.assertEqual(data["total_budget"], Decimal("3000"))
        self.assertEqual(data["avg_duration_days"], 7)
        self.assertEqual(len(data["by_status"]), 2)

    def test_budget_summary_lists_over_budget_trips(self):
        Expense.objects.create(itinerary=self.itinerary, category="food", description="Feast", amount=2500, date=TODAY)
        data = self.client.get("/api/v1/analytics/budget-summary/").data
        self.assertEqual(data["over_budget_trips"][0]["title"], "Paris Trip")
        self.assertEqual(data["spending_by_category"][0]["category"], "food")

    def test_destination_preferences(self):
        data = self.client.get("/api/v1/analytics/destination-preferences/").data
        self.assertEqual(data["favorite_category"], "city")
        self.assertEqual(data["top_destinations"][0]["destination__name"], "Paris")

    def test_empty_analytics(self):
        self.login_as(self.other)
        self.assertEqual(self.client.get("/api/v1/analytics/").data["trips"], 0)
        self.assertIsNone(self.client.get("/api/v1/analytics/destination-preferences/").data["favorite_category"])

    def test_activity_log_visible_to_collaborators_only(self):
        self.client.patch(f"{URL}{self.itinerary.id}/", {"title": "Renamed"})
        logs = "/api/v1/activity-logs/"
        self.assertEqual(self.client.get(logs, {"action": "updated"}).data["count"], 1)
        self.login_as(self.other)
        self.assertEqual(self.client.get(logs).data["count"], 0)
        self.itinerary.add_collaborator(self.other, "viewer")
        self.assertGreaterEqual(self.client.get(logs).data["count"], 1)
