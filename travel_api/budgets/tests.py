from decimal import Decimal

from rest_framework import status

from core.testing import TODAY, BaseAPITest, make_itinerary, png_file, pdf_file

from .models import Budget, Expense
from .serializers import BudgetSerializer

URL = "/api/v1/expenses/"


class BudgetModelTests(BaseAPITest):
    def test_budget_auto_created_for_itinerary(self):
        self.assertTrue(Budget.objects.filter(itinerary=self.itinerary).exists())
        self.assertEqual(str(self.itinerary.budget_detail), "Budget for Paris Trip")

    def test_total_and_category_budget(self):
        b = self.itinerary.budget_detail
        b.food_budget, b.transport_budget = Decimal("300"), Decimal("150")
        self.assertEqual(b.total_budget, Decimal("450"))
        self.assertEqual(b.category_budget("food"), Decimal("300"))

    def test_spent_by_category(self):
        Expense.objects.create(itinerary=self.itinerary, category="food", description="a", amount=30, date=TODAY)
        Expense.objects.create(itinerary=self.itinerary, category="food", description="b", amount=20, date=TODAY)
        spent = self.itinerary.budget_detail.spent_by_category()
        self.assertEqual(spent["food"], Decimal("50"))
        self.assertEqual(spent["transport"], Decimal("0"))

    def test_expense_str(self):
        e = Expense.objects.create(itinerary=self.itinerary, category="food", description="Lunch", amount=12, date=TODAY)
        self.assertEqual(str(e), "Lunch - $12")


class ExpenseAPITests(BaseAPITest):
    def _payload(self, **kw):
        data = {"itinerary": self.itinerary.id, "category": "food", "description": "Dinner", "amount": "45.50",
                "date": str(TODAY)}
        data.update(kw)
        return data

    def test_create_expense_updates_trip_total(self):
        response = self.client.post(URL, self._payload())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["amount_display"], "$45.50")
        self.assertEqual(response.data["paid_by_username"], "owner")
        self.itinerary.refresh_from_db()
        self.assertEqual(self.itinerary.actual_spent, Decimal("45.50"))

    def test_update_and_delete_keep_total_in_sync(self):
        expense_id = self.client.post(URL, self._payload()).data["id"]
        self.client.patch(f"{URL}{expense_id}/", {"amount": "100.00"})
        self.itinerary.refresh_from_db()
        self.assertEqual(self.itinerary.actual_spent, Decimal("100.00"))
        self.client.delete(f"{URL}{expense_id}/")
        self.itinerary.refresh_from_db()
        self.assertEqual(self.itinerary.actual_spent, Decimal("0"))

    def test_invalid_amounts_rejected(self):
        self.assertEqual(self.client.post(URL, self._payload(amount="0")).status_code, 400)
        self.assertEqual(self.client.post(URL, self._payload(amount="-5")).status_code, 400)

    def test_invalid_category_rejected(self):
        self.assertEqual(self.client.post(URL, self._payload(category="gambling")).status_code, 400)

    def test_cannot_move_expense_between_trips(self):
        expense_id = self.client.post(URL, self._payload()).data["id"]
        second = make_itinerary(self.owner, self.destination, title="Other")
        self.assertEqual(self.client.patch(f"{URL}{expense_id}/", {"itinerary": second.id}).status_code, 400)

    def test_viewer_can_read_but_not_write(self):
        self.client.post(URL, self._payload())
        self.itinerary.add_collaborator(self.other, "viewer")
        self.login_as(self.other)
        self.assertEqual(self.client.get(URL).data["count"], 1)
        self.assertEqual(self.client.post(URL, self._payload()).status_code, 403)

    def test_editor_can_add_expenses(self):
        self.itinerary.add_collaborator(self.other, "editor")
        self.login_as(self.other)
        response = self.client.post(URL, self._payload())
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["paid_by_username"], "other")

    def test_stranger_sees_nothing_and_cannot_add(self):
        self.client.post(URL, self._payload())
        self.login_as(self.other)
        self.assertEqual(self.client.get(URL).data["count"], 0)
        self.assertEqual(self.client.post(URL, self._payload()).status_code, 403)

    def test_filters_search_ordering(self):
        self.client.post(URL, self._payload(category="food", amount="20"))
        self.client.post(URL, self._payload(category="transport", description="Taxi", amount="80"))
        self.assertEqual(self.client.get(URL, {"category": "transport"}).data["count"], 1)
        self.assertEqual(self.client.get(URL, {"min_amount": 50}).data["count"], 1)
        self.assertEqual(self.client.get(URL, {"search": "taxi"}).data["count"], 1)
        self.assertEqual(self.client.get(URL, {"ordering": "-amount"}).data["results"][0]["description"], "Taxi")

    def test_summary_action(self):
        self.client.post(URL, self._payload(amount="20"))
        self.client.post(URL, self._payload(category="transport", amount="80"))
        data = self.client.get(f"{URL}summary/", {"itinerary": self.itinerary.id}).data
        self.assertEqual(Decimal(str(data["total"])), Decimal("100"))
        self.assertEqual(data["by_category"][0]["category"], "transport")

    def test_receipt_upload_validation(self):
        good = self.client.post(URL, self._payload(receipt=png_file("r.png")), format="multipart")
        self.assertEqual(good.status_code, 201)
        bad = self.client.post(URL, self._payload(receipt=pdf_file("r.pdf")), format="multipart")
        self.assertEqual(bad.status_code, 400)


class BudgetDetailTests(BaseAPITest):
    def setUp(self):
        super().setUp()
        self.url = f"/api/v1/budgets/itinerary/{self.itinerary.id}/"

    def test_get_budget(self):
        data = self.client.get(self.url).data
        self.assertEqual(Decimal(data["total_budget"]), Decimal("0"))
        self.assertEqual(Decimal(data["unallocated"]), Decimal("2000"))

    def test_patch_allocations(self):
        response = self.client.patch(self.url, {"food_budget": "400", "transport_budget": "300"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(response.data["total_budget"]), Decimal("700"))

    def test_allocations_cannot_exceed_trip_budget(self):
        self.assertEqual(self.client.patch(self.url, {"food_budget": "3000"}).status_code, 400)

    def test_viewer_cannot_change_budget(self):
        self.itinerary.add_collaborator(self.other, "viewer")
        self.login_as(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.client.patch(self.url, {"food_budget": "10"}).status_code, 403)

    def test_stranger_gets_404(self):
        self.login_as(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_spent_by_category_in_response(self):
        Expense.objects.create(itinerary=self.itinerary, category="shopping", description="Gifts", amount=60, date=TODAY)
        self.assertEqual(self.client.get(self.url).data["spent_by_category"]["shopping"], "60.00")

    def test_serializer_unallocated(self):
        self.assertEqual(BudgetSerializer(self.itinerary.budget_detail).data["unallocated"], "2000.00")
