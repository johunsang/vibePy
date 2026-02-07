import unittest

from vibeweb.conditions import ConditionError, eval_condition, lookup_path


class TestConditions(unittest.TestCase):
    def test_lookup_path(self) -> None:
        ctx = {"row": {"stage": "Closed Won"}, "steps": {"a": {"ok": True}}}
        self.assertEqual(lookup_path("row.stage", ctx), "Closed Won")
        self.assertEqual(lookup_path("steps.a.ok", ctx), True)
        self.assertIsNone(lookup_path("row.missing", ctx))
        self.assertIsNone(lookup_path("", ctx))

    def test_equality_map_and(self) -> None:
        ctx = {"row": {"stage": "Closed Won", "amount": 10}}
        self.assertTrue(eval_condition({"row.stage": "Closed Won", "row.amount": 10}, ctx))
        self.assertFalse(eval_condition({"row.stage": "Closed Won", "row.amount": 11}, ctx))

    def test_and_or_not(self) -> None:
        ctx = {"row": {"stage": "Closed Won", "amount": 10}}
        self.assertTrue(eval_condition({"$and": [{"row.stage": "Closed Won"}, {"$gt": ["row.amount", 0]}]}, ctx))
        self.assertTrue(eval_condition({"$or": [{"row.stage": "Nope"}, {"row.stage": "Closed Won"}]}, ctx))
        self.assertTrue(eval_condition({"$not": {"row.stage": "Nope"}}, ctx))
        self.assertFalse(eval_condition({"$not": {"row.stage": "Closed Won"}}, ctx))

    def test_comparisons(self) -> None:
        ctx = {"row": {"amount": 10}}
        self.assertTrue(eval_condition({"$gt": ["row.amount", 9]}, ctx))
        self.assertTrue(eval_condition({"$gte": ["row.amount", 10]}, ctx))
        self.assertTrue(eval_condition({"$lt": ["row.amount", 11]}, ctx))
        self.assertTrue(eval_condition({"$lte": ["row.amount", 10]}, ctx))
        self.assertFalse(eval_condition({"$gt": ["row.amount", 10]}, ctx))

    def test_in_contains_regex(self) -> None:
        ctx = {"row": {"stage": "Closed Won", "tags": ["a", "b"], "meta": {"k": 1}}}
        self.assertTrue(eval_condition({"$in": ["row.stage", ["Closed Won", "Open"]]}, ctx))
        self.assertTrue(eval_condition({"$contains": ["row.stage", "Won"]}, ctx))
        self.assertTrue(eval_condition({"$contains": ["row.tags", "a"]}, ctx))
        self.assertTrue(eval_condition({"$contains": ["row.meta", "k"]}, ctx))
        self.assertTrue(eval_condition({"$regex": ["row.stage", "Closed\\s+Won"]}, ctx))

    def test_startswith_endswith(self) -> None:
        ctx = {"row": {"stage": "Closed Won"}}
        self.assertTrue(eval_condition({"$startsWith": ["row.stage", "Closed"]}, ctx))
        self.assertFalse(eval_condition({"$startsWith": ["row.stage", "Won"]}, ctx))
        self.assertTrue(eval_condition({"$endsWith": ["row.stage", "Won"]}, ctx))
        self.assertFalse(eval_condition({"$endsWith": ["row.stage", "Closed"]}, ctx))

    def test_list_is_implicit_and(self) -> None:
        ctx = {"row": {"stage": "Closed Won", "amount": 10}}
        self.assertTrue(eval_condition([{"row.stage": "Closed Won"}, {"$gt": ["row.amount", 0]}], ctx))
        self.assertFalse(eval_condition([{"row.stage": "Nope"}, {"$gt": ["row.amount", 0]}], ctx))

    def test_any_all_with_item(self) -> None:
        ctx = {"row": {"tags": ["vip", "new"], "items": [{"n": 1}, {"n": 2}]}}
        self.assertTrue(eval_condition({"$any": ["row.tags", {"$eq": ["item", "vip"]}]}, ctx))
        self.assertFalse(eval_condition({"$all": ["row.tags", {"$eq": ["item", "vip"]}]}, ctx))
        self.assertTrue(eval_condition({"$all": ["row.items", {"$gte": ["item.n", 1]}]}, ctx))
        self.assertFalse(eval_condition({"$all": ["row.items", {"$gt": ["item.n", 1]}]}, ctx))

    def test_exists_truthy(self) -> None:
        ctx = {"row": {"stage": "Closed Won", "empty": ""}}
        self.assertTrue(eval_condition({"$exists": "row.stage"}, ctx))
        self.assertFalse(eval_condition({"$exists": "row.missing"}, ctx))
        self.assertTrue(eval_condition({"$exists": ["row.stage", True]}, ctx))
        self.assertTrue(eval_condition({"$exists": ["row.missing", False]}, ctx))
        self.assertTrue(eval_condition({"$truthy": "row.stage"}, ctx))
        self.assertFalse(eval_condition({"$truthy": "row.empty"}, ctx))

    def test_invalid_operator(self) -> None:
        with self.assertRaises(ConditionError):
            eval_condition({"$wat": 123}, {"row": {"x": 1}})


if __name__ == "__main__":
    unittest.main()
