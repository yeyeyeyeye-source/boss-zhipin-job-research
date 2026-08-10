import unittest

from boss_app.strategy_model import StrategySpec


class StrategySpecTests(unittest.TestCase):
    def test_city_order_does_not_change_identity(self):
        first = StrategySpec.create(
            search_keyword=" 新媒体运营 ",
            target_role="新媒体运营",
            target_type="exact_role",
            cities=["北京", "上海", "北京"],
        )
        second = StrategySpec.create(
            search_keyword="新媒体运营",
            target_role=" 新媒体运营 ",
            target_type="exact_role",
            cities=["上海", "北京"],
        )

        self.assertEqual(first.signature, second.signature)
        self.assertEqual(first.ordered_cities, ("北京", "上海"))
        self.assertEqual(second.ordered_cities, ("上海", "北京"))
        self.assertEqual(first.city_set, ("上海", "北京"))

    def test_filter_or_target_change_creates_a_new_identity(self):
        baseline = StrategySpec.create(
            "AI产品", "AI产品相关岗位", "domain_scope", ["北京"],
        )
        filtered = StrategySpec.create(
            "AI产品", "AI产品相关岗位", "domain_scope", ["北京"],
            salary_filter="405",
        )
        exact = StrategySpec.create(
            "AI产品", "AI产品经理", "exact_role", ["北京"],
        )

        self.assertNotEqual(baseline.signature, filtered.signature)
        self.assertNotEqual(baseline.signature, exact.signature)

    def test_whitespace_and_case_are_normalized_for_identity(self):
        first = StrategySpec.create("AI 运营", "AI 运营", "exact_role", ["深圳"])
        second = StrategySpec.create("ai运营", "ai运营", "exact_role", ["深圳"])

        self.assertEqual(first.signature, second.signature)

    def test_invalid_or_empty_inputs_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "检索词"):
            StrategySpec.create("", "运营", "exact_role", ["北京"])
        with self.assertRaisesRegex(ValueError, "城市"):
            StrategySpec.create("运营", "运营", "exact_role", [])
        with self.assertRaisesRegex(ValueError, "目标类型"):
            StrategySpec.create("运营", "运营", "broad", ["北京"])


if __name__ == "__main__":
    unittest.main()
