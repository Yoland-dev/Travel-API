from datetime import timedelta

from django.core.exceptions import ValidationError
from rest_framework import status

from core.testing import TODAY, BaseAPITest, make_accommodation, make_activity

from .models import Review

URL = "/api/v1/reviews/"


class ReviewModelTests(BaseAPITest):
    def test_str_target_and_clean(self):
        review = Review.objects.create(user=self.owner, destination=self.destination, rating=5, title="Great",
                                       content="Loved it", visit_date=TODAY - timedelta(days=5))
        self.assertEqual(str(review), "Great by owner")
        self.assertEqual(review.target, self.destination)
        self.assertEqual(review.target_type, "destination")
        review.clean()

    def test_clean_rejects_no_target_and_future_visit(self):
        with self.assertRaises(ValidationError):
            Review(user=self.owner, rating=3, title="t", content="c", visit_date=TODAY).clean()
        with self.assertRaises(ValidationError):
            Review(user=self.owner, destination=self.destination, rating=3, title="t", content="c",
                   visit_date=TODAY + timedelta(days=3)).clean()


class ReviewAPITests(BaseAPITest):
    def setUp(self):
        super().setUp()
        self.activity = make_activity(self.destination)
        self.hotel = make_accommodation(self.destination)

    def _payload(self, **kw):
        data = {"destination": self.destination.id, "rating": 5, "title": "Wonderful", "content": "Would go again",
                "visit_date": str(TODAY - timedelta(days=10))}
        data.update(kw)
        return data

    def test_create_review_sets_user_and_target_info(self):
        response = self.client.post(URL, self._payload())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["username"], "owner")
        self.assertEqual(response.data["target_type"], "destination")
        self.assertEqual(response.data["target_name"], "Paris")

    def test_review_activity_and_accommodation(self):
        for field, obj in (("activity", self.activity), ("accommodation", self.hotel)):
            response = self.client.post(URL, self._payload(destination=None, **{field: obj.id}), format="json")
            self.assertEqual(response.status_code, 201, response.data)

    def test_rating_bounds(self):
        self.assertEqual(self.client.post(URL, self._payload(rating=0)).status_code, 400)
        self.assertEqual(self.client.post(URL, self._payload(rating=6)).status_code, 400)

    def test_future_visit_date_rejected(self):
        response = self.client.post(URL, self._payload(visit_date=str(TODAY + timedelta(days=5))))
        self.assertEqual(response.status_code, 400)

    def test_exactly_one_target_required(self):
        self.assertEqual(self.client.post(URL, self._payload(activity=self.activity.id)).status_code, 400)
        self.assertEqual(self.client.post(URL, self._payload(destination=None), format="json").status_code, 400)

    def test_duplicate_review_rejected(self):
        self.client.post(URL, self._payload())
        self.assertEqual(self.client.post(URL, self._payload()).status_code, 400)

    def test_anonymous_can_read_but_not_write(self):
        self.client.post(URL, self._payload())
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(URL).status_code, 200)
        self.assertEqual(self.client.post(URL, self._payload()).status_code, 401)

    def test_owner_can_edit_and_delete_but_not_change_target(self):
        review_id = self.client.post(URL, self._payload()).data["id"]
        self.assertEqual(self.client.patch(f"{URL}{review_id}/", {"rating": 3}).data["rating"], 3)
        change = self.client.patch(f"{URL}{review_id}/", {"destination": None, "activity": self.activity.id}, format="json")
        self.assertEqual(change.status_code, 400)
        self.assertEqual(self.client.delete(f"{URL}{review_id}/").status_code, 204)

    def test_others_cannot_edit_or_delete(self):
        review_id = self.client.post(URL, self._payload()).data["id"]
        self.login_as(self.other)
        self.assertEqual(self.client.patch(f"{URL}{review_id}/", {"rating": 1}).status_code, 403)
        self.assertEqual(self.client.delete(f"{URL}{review_id}/").status_code, 403)

    def test_helpful_increments_counter(self):
        review_id = self.client.post(URL, self._payload()).data["id"]
        self.login_as(self.other)
        self.client.post(f"{URL}{review_id}/helpful/")
        self.assertEqual(self.client.post(f"{URL}{review_id}/helpful/").data["helpful_count"], 2)

    def test_filters_and_mine(self):
        self.client.post(URL, self._payload(rating=2))
        self.login_as(self.other)
        self.client.post(URL, self._payload(rating=5))
        self.assertEqual(self.client.get(URL, {"min_rating": 4}).data["count"], 1)
        self.assertEqual(self.client.get(URL, {"search": "wonderful"}).data["count"], 2)
        self.assertEqual(self.client.get(f"{URL}mine/").data["count"], 1)

    def test_summary(self):
        self.client.post(URL, self._payload(rating=4))
        self.login_as(self.other)
        self.client.post(URL, self._payload(rating=2))
        data = self.client.get(f"{URL}summary/", {"destination": self.destination.id}).data
        self.assertEqual(data["average"], 3.0)
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["distribution"]["4"], 1)

    def test_target_reviews_view(self):
        self.client.post(URL, self._payload())
        self.client.force_authenticate(user=None)
        ok = self.client.get(f"{URL}target/destination/{self.destination.id}/")
        self.assertEqual(ok.data["count"], 1)
        self.assertEqual(self.client.get(f"{URL}target/planet/1/").status_code, 404)

    def test_review_shows_in_destination_rating(self):
        self.client.post(URL, self._payload(rating=4))
        data = self.client.get(f"/api/v1/destinations/{self.destination.id}/").data
        self.assertEqual(data["average_rating"], 4.0)
        self.assertEqual(data["review_count"], 1)
