"""Unit tests pentru logica de raport (Șezătoare + Andy's)."""

import unittest

from calculations import (
    _portii,
    _comenzi,
    build_andys_report,
    build_sezatoare_report,
    count_andys,
    count_sezatoare,
)


def sez(felul1_menu=None, felul1_text="", sort1=0,
        felul2_menu=None, felul2_text="", sort2=0):
    """Construiește un `row` de Șezătoare (oricare fel poate lipsi)."""
    row = {}
    if felul1_menu:
        row.update({"felul1_menu": felul1_menu, "felul1_text": felul1_text,
                    "sort_order_1": sort1})
    if felul2_menu:
        row.update({"felul2_menu": felul2_menu, "felul2_text": felul2_text,
                    "sort_order_2": sort2})
    return row


def andy(menu="Business Lunch 1", felul2_text="Pilaf cu carne",
         felul1_text="Zeamă de găină", sort_order=0, option_sort=0):
    """Construiește un `row` de Andy's."""
    return {
        "menu": menu,
        "sort_order": sort_order,
        "felul2_text": felul2_text,
        "felul1_text": felul1_text,
        "felul1_option_sort": option_sort,
    }


class TestCountSezatoare(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(count_sezatoare([]), {})

    def test_counts_per_menu_and_per_fel(self):
        rows = [
            sez("Lunch 1", "Zeamă", 0, "Lunch 1", "Friptură", 0),
            sez("Lunch 1", "Zeamă", 0, "Lunch 1", "Friptură", 0),
            sez(felul2_menu="Lunch 1", felul2_text="Friptură", sort2=0),
        ]
        counts = count_sezatoare(rows)
        self.assertEqual(counts["Lunch 1"]["felul1"]["count"], 2)
        self.assertEqual(counts["Lunch 1"]["felul2"]["count"], 3)
        self.assertEqual(counts["Lunch 1"]["felul1"]["text"], "Zeamă")
        self.assertEqual(counts["Lunch 1"]["felul2"]["text"], "Friptură")

    def test_mixed_selection_counts_on_both_menus(self):
        """Felul 1 din Lunch 1 + Felul 2 din Lunch 2 → se numără la meniuri diferite."""
        rows = [sez("Lunch 1", "Zeamă", 0, "Lunch 2", "Pilaf", 1)]
        counts = count_sezatoare(rows)
        self.assertEqual(counts["Lunch 1"]["felul1"]["count"], 1)
        self.assertEqual(counts["Lunch 1"]["felul2"]["count"], 0)
        self.assertEqual(counts["Lunch 2"]["felul1"]["count"], 0)
        self.assertEqual(counts["Lunch 2"]["felul2"]["count"], 1)

    def test_only_felul1(self):
        counts = count_sezatoare([sez("Lunch 1", "Zeamă", 0)])
        self.assertEqual(counts["Lunch 1"]["felul1"]["count"], 1)
        self.assertEqual(counts["Lunch 1"]["felul2"]["count"], 0)

    def test_only_felul2(self):
        counts = count_sezatoare([sez(felul2_menu="Lunch 2", felul2_text="Pilaf", sort2=1)])
        self.assertEqual(counts["Lunch 2"]["felul2"]["count"], 1)
        self.assertEqual(counts["Lunch 2"]["felul1"]["count"], 0)
        self.assertNotIn("Lunch 1", counts)


class TestSezatoareReport(unittest.TestCase):

    def test_report_format(self):
        rows = [
            sez("Lunch 1", "Zeamă de găină", 0, "Lunch 1", "Friptură", 0),
            sez("Lunch 1", "Zeamă de găină", 0, "Lunch 2", "Pilaf", 1),
            sez("Lunch 2", "Borș roșu", 1, "Lunch 2", "Pilaf", 1),
        ]
        report = build_sezatoare_report(rows, "2026-07-10", "str. Exemplu 123")
        self.assertIn("🍲 LA ȘEZĂTOARE", report)
        self.assertIn("📅 2026-07-10", report)
        self.assertIn("📍 str. Exemplu 123", report)
        self.assertIn("LUNCH 1", report)
        self.assertIn("  Felul 1: Zeamă de găină — 2 porții", report)
        self.assertIn("  Felul 2: Friptură — 1 porție", report)
        self.assertIn("LUNCH 2", report)
        self.assertIn("  Felul 1: Borș roșu — 1 porție", report)
        self.assertIn("  Felul 2: Pilaf — 2 porții", report)

    def test_total_portii_is_sum_of_all_feluri(self):
        rows = [
            sez("Lunch 1", "Zeamă", 0, "Lunch 1", "Friptură", 0),  # 2 porții
            sez("Lunch 1", "Zeamă", 0),                            # 1 porție
            sez(felul2_menu="Lunch 2", felul2_text="Pilaf", sort2=1),  # 1 porție
        ]
        report = build_sezatoare_report(rows, "2026-07-10", "Office")
        self.assertIn("TOTAL PORȚII: 4", report)

    def test_menu_without_orders_absent_and_fel_with_zero_omitted(self):
        """Meniul necomandat nu apare; felul cu 0 comenzi se omite din meniul care apare."""
        rows = [sez("Lunch 1", "Zeamă de găină", 0)]  # doar felul 1, doar Lunch 1
        report = build_sezatoare_report(rows, "2026-07-10", "Office")
        self.assertIn("LUNCH 1", report)
        self.assertIn("Felul 1: Zeamă de găină — 1 porție", report)
        self.assertNotIn("Felul 2:", report)
        self.assertNotIn("LUNCH 2", report)
        self.assertIn("TOTAL PORȚII: 1", report)

    def test_empty_report_is_valid_with_zero_total(self):
        report = build_sezatoare_report([], "2026-07-10", "Office")
        self.assertIn("🍲 LA ȘEZĂTOARE", report)
        self.assertIn("📅 2026-07-10", report)
        self.assertIn("TOTAL PORȚII: 0", report)

    def test_menus_ordered_by_sort_order(self):
        rows = [
            sez("Lunch 2", "Borș", 1),
            sez("Lunch 1", "Zeamă", 0),
            sez("Dieta", "Supă", 2),
        ]
        report = build_sezatoare_report(rows, "2026-07-10", "Office")
        self.assertLess(report.index("LUNCH 1"), report.index("LUNCH 2"))
        self.assertLess(report.index("LUNCH 2"), report.index("DIETA"))


class TestCountAndys(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(count_andys([]), {})

    def test_felul2_equals_orders_and_options_sum_to_same(self):
        rows = [
            andy(felul1_text="Zeamă de găină", option_sort=0),
            andy(felul1_text="Zeamă de găină", option_sort=0),
            andy(felul1_text="Borș roșu", option_sort=1),
            andy(felul1_text="Supă cremă de linte", option_sort=2),
        ]
        counts = count_andys(rows)
        entry = counts["Business Lunch 1"]
        self.assertEqual(entry["orders"], 4)
        self.assertEqual(entry["felul2"]["count"], 4)
        self.assertEqual(sum(o["count"] for o in entry["felul1_options"]), 4)
        self.assertEqual([o["text"] for o in entry["felul1_options"]],
                         ["Zeamă de găină", "Borș roșu", "Supă cremă de linte"])
        self.assertEqual([o["count"] for o in entry["felul1_options"]], [2, 1, 1])

    def test_multiple_business_lunches(self):
        rows = [
            andy(menu="Business Lunch 1", felul2_text="Pilaf", felul1_text="Zeamă", sort_order=0),
            andy(menu="Business Lunch 1", felul2_text="Pilaf", felul1_text="Borș", sort_order=0),
            andy(menu="Business Lunch 2", felul2_text="Friptură", felul1_text="Ciorbă", sort_order=1),
        ]
        counts = count_andys(rows)
        self.assertEqual(counts["Business Lunch 1"]["orders"], 2)
        self.assertEqual(counts["Business Lunch 2"]["orders"], 1)
        self.assertEqual(counts["Business Lunch 2"]["felul2"]["text"], "Friptură")


class TestAndysReport(unittest.TestCase):

    def test_report_format(self):
        rows = (
            [andy(felul1_text="Zeamă de găină", option_sort=0)] * 5
            + [andy(felul1_text="Borș roșu", option_sort=1)] * 4
            + [andy(felul1_text="Supă cremă de linte", option_sort=2)] * 3
        )
        report = build_andys_report(rows, "2026-07-10", "str. Exemplu 123")
        self.assertIn("🍛 ANDY'S", report)
        self.assertIn("📅 2026-07-10", report)
        self.assertIn("📍 str. Exemplu 123", report)
        self.assertIn("BUSINESS LUNCH 1 — 12 comenzi", report)
        self.assertIn("  Felul 2 (inclus): Pilaf cu carne — 12 porții", report)
        self.assertIn("  Felul 1:", report)
        self.assertIn("    Zeamă de găină — 5 porții", report)
        self.assertIn("    Borș roșu — 4 porții", report)
        self.assertIn("    Supă cremă de linte — 3 porții", report)
        self.assertIn("TOTAL COMENZI: 12", report)

    def test_empty_report_is_valid_with_zero_total(self):
        report = build_andys_report([], "2026-07-10", "Office")
        self.assertIn("🍛 ANDY'S", report)
        self.assertIn("TOTAL COMENZI: 0", report)

    def test_business_lunches_ordered_by_sort_order(self):
        rows = [
            andy(menu="Business Lunch 2", sort_order=1),
            andy(menu="Business Lunch 1", sort_order=0),
        ]
        report = build_andys_report(rows, "2026-07-10", "Office")
        self.assertLess(report.index("BUSINESS LUNCH 1"), report.index("BUSINESS LUNCH 2"))


class TestPersonList(unittest.TestCase):

    PERSONS = [
        {
            "name": "Ion Popescu",
            "sort_order": 0,
            "items": [
                {"menu": "Lunch 1", "menu_ru": "Обед 1",
                 "text": "Zeamă de găină", "text_ru": "Куриная зама"},
                {"menu": "Lunch 2", "menu_ru": "Обед 2",
                 "text": "Pilaf", "text_ru": "Плов"},
            ],
        },
        {
            "name": "Ana Rusu",
            "sort_order": 1,
            "items": [
                {"menu": "Lunch 2", "menu_ru": "Обед 2",
                 "text": "Pilaf", "text_ru": "Плов"},
            ],
        },
    ]

    def test_person_list_ro_and_ru_present(self):
        rows = [sez("Lunch 1", "Zeamă de găină", 0, "Lunch 2", "Pilaf", 1)]
        report = build_sezatoare_report(rows, "2026-07-10", "Office", persons=self.PERSONS)
        self.assertIn("👤 COMENZI PER PERSOANĂ (RO):", report)
        self.assertIn("  Ion Popescu — Lunch 1: Zeamă de găină | Lunch 2: Pilaf", report)
        self.assertIn("👤 ЗАКАЗЫ ПО ПЕРСОНАМ (RU):", report)
        self.assertIn("  Ion Popescu — Обед 1: Куриная зама | Обед 2: Плов", report)

    def test_person_list_absent_when_no_persons(self):
        report = build_sezatoare_report([], "2026-07-10", "Office")
        self.assertNotIn("COMENZI PER PERSOANĂ", report)
        self.assertNotIn("ЗАКАЗЫ ПО ПЕРСОНАМ", report)

    def test_person_list_ordered_by_sort_order(self):
        report = build_sezatoare_report([], "2026-07-10", "Office", persons=self.PERSONS)
        self.assertLess(report.index("Ion Popescu"), report.index("Ana Rusu"))

    def test_person_list_also_in_andys_report(self):
        persons = [{
            "name": "Ana Rusu",
            "sort_order": 0,
            "items": [{"menu": "Business Lunch 1", "menu_ru": "Бизнес Ланч 1",
                       "text": "Zeamă de găină | Pilaf cu carne",
                       "text_ru": "Куриная зама | Плов с мясом"}],
        }]
        report = build_andys_report([andy()], "2026-07-10", "Office", persons=persons)
        self.assertIn("👤 COMENZI PER PERSOANĂ (RO):", report)
        self.assertIn("  Ana Rusu — Business Lunch 1: Zeamă de găină | Pilaf cu carne", report)
        self.assertIn("  Ana Rusu — Бизнес Ланч 1: Куриная зама | Плов с мясом", report)

    def test_ru_falls_back_to_ro_when_translation_missing(self):
        persons = [{
            "name": "Vlad Ciobanu",
            "sort_order": 0,
            "items": [{"menu": "Lunch 1", "text": "Zeamă de găină"}],
        }]
        report = build_sezatoare_report([], "2026-07-10", "Office", persons=persons)
        ru_block = report.split("ЗАКАЗЫ ПО ПЕРСОНАМ (RU):")[1]
        self.assertIn("  Vlad Ciobanu — Lunch 1: Zeamă de găină", ru_block)


class TestAcordGramatical(unittest.TestCase):
    """Raportul ajunge la furnizor — „1 porții" arată neîngrijit."""

    def test_singular(self):
        self.assertEqual(_portii(1), "1 porție")
        self.assertEqual(_comenzi(1), "1 comandă")

    def test_plural_pana_la_19(self):
        self.assertEqual(_portii(2), "2 porții")
        self.assertEqual(_portii(19), "19 porții")

    def test_de_peste_19(self):
        """Româna cere «de» de la 20 în sus."""
        self.assertEqual(_portii(20), "20 de porții")
        self.assertEqual(_comenzi(20), "20 de comenzi")
        self.assertEqual(_portii(100), "100 de porții")

    def test_exceptia_101(self):
        """Dar NU la 101: restul la 100 e sub 20."""
        self.assertEqual(_portii(101), "101 porții")
        self.assertEqual(_portii(120), "120 de porții")


if __name__ == "__main__":
    unittest.main()
