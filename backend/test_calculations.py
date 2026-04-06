"""Unit tests for the portion calculation logic."""

import unittest

from calculations import calculate_portions, generate_report_text


class TestCalculatePortions(unittest.TestCase):

    def test_empty_selections(self):
        result = calculate_portions([])
        self.assertEqual(result, {})

    def test_all_ambele(self):
        selections = [
            {"menu_name": "Lunch 1", "fel_selectat": "ambele"},
            {"menu_name": "Lunch 1", "fel_selectat": "ambele"},
            {"menu_name": "Lunch 1", "fel_selectat": "ambele"},
        ]
        result = calculate_portions(selections)
        self.assertEqual(result["Lunch 1"]["maxi"], 3)
        self.assertEqual(result["Lunch 1"]["standard"], 0)

    def test_all_felul2(self):
        selections = [
            {"menu_name": "Dieta", "fel_selectat": "felul2"},
            {"menu_name": "Dieta", "fel_selectat": "felul2"},
        ]
        result = calculate_portions(selections)
        self.assertEqual(result["Dieta"]["maxi"], 0)
        self.assertEqual(result["Dieta"]["standard"], 2)

    def test_two_felul1_combine_into_one_maxi(self):
        """Two felul1 selections should combine into 1 Maxi portion."""
        selections = [
            {"menu_name": "Lunch 1", "fel_selectat": "felul1"},
            {"menu_name": "Lunch 1", "fel_selectat": "felul1"},
        ]
        result = calculate_portions(selections)
        self.assertEqual(result["Lunch 1"]["maxi"], 1)
        self.assertEqual(result["Lunch 1"]["standard"], 0)

    def test_three_felul1_one_maxi_one_standard(self):
        """Three felul1: 2 combine into 1 Maxi, 1 remainder becomes Standard."""
        selections = [
            {"menu_name": "Lunch 1", "fel_selectat": "felul1"},
            {"menu_name": "Lunch 1", "fel_selectat": "felul1"},
            {"menu_name": "Lunch 1", "fel_selectat": "felul1"},
        ]
        result = calculate_portions(selections)
        self.assertEqual(result["Lunch 1"]["maxi"], 1)
        self.assertEqual(result["Lunch 1"]["standard"], 1)

    def test_four_felul1_two_maxi(self):
        selections = [
            {"menu_name": "Lunch 2", "fel_selectat": "felul1"},
            {"menu_name": "Lunch 2", "fel_selectat": "felul1"},
            {"menu_name": "Lunch 2", "fel_selectat": "felul1"},
            {"menu_name": "Lunch 2", "fel_selectat": "felul1"},
        ]
        result = calculate_portions(selections)
        self.assertEqual(result["Lunch 2"]["maxi"], 2)
        self.assertEqual(result["Lunch 2"]["standard"], 0)

    def test_mixed_selections_same_menu(self):
        """Mix of ambele, felul1, felul2 for same menu."""
        selections = [
            {"menu_name": "Lunch 1", "fel_selectat": "ambele"},
            {"menu_name": "Lunch 1", "fel_selectat": "ambele"},
            {"menu_name": "Lunch 1", "fel_selectat": "felul1"},
            {"menu_name": "Lunch 1", "fel_selectat": "felul1"},
            {"menu_name": "Lunch 1", "fel_selectat": "felul2"},
        ]
        result = calculate_portions(selections)
        # 2 ambele + 1 pair of felul1 = 3 maxi; 1 felul2 = 1 standard
        self.assertEqual(result["Lunch 1"]["maxi"], 3)
        self.assertEqual(result["Lunch 1"]["standard"], 1)

    def test_multiple_menus(self):
        selections = [
            {"menu_name": "Lunch 1", "fel_selectat": "ambele"},
            {"menu_name": "Lunch 2", "fel_selectat": "felul2"},
            {"menu_name": "Dieta", "fel_selectat": "felul1"},
            {"menu_name": "Post", "fel_selectat": "felul1"},
            {"menu_name": "Post", "fel_selectat": "felul1"},
        ]
        result = calculate_portions(selections)
        self.assertEqual(result["Lunch 1"]["maxi"], 1)
        self.assertEqual(result["Lunch 1"]["standard"], 0)
        self.assertEqual(result["Lunch 2"]["maxi"], 0)
        self.assertEqual(result["Lunch 2"]["standard"], 1)
        self.assertEqual(result["Dieta"]["maxi"], 0)
        self.assertEqual(result["Dieta"]["standard"], 1)
        self.assertEqual(result["Post"]["maxi"], 1)
        self.assertEqual(result["Post"]["standard"], 0)

    def test_single_felul1_becomes_standard(self):
        """A single felul1 with no pair becomes Standard."""
        selections = [
            {"menu_name": "Lunch 1", "fel_selectat": "felul1"},
        ]
        result = calculate_portions(selections)
        self.assertEqual(result["Lunch 1"]["maxi"], 0)
        self.assertEqual(result["Lunch 1"]["standard"], 1)

    def test_felul1_and_felul2_same_menu(self):
        """felul1 + felul2 do NOT combine into maxi — they are separate."""
        selections = [
            {"menu_name": "Lunch 1", "fel_selectat": "felul1"},
            {"menu_name": "Lunch 1", "fel_selectat": "felul2"},
        ]
        result = calculate_portions(selections)
        # 1 felul1 alone = 1 standard; 1 felul2 = 1 standard
        self.assertEqual(result["Lunch 1"]["maxi"], 0)
        self.assertEqual(result["Lunch 1"]["standard"], 2)


class TestGenerateReportText(unittest.TestCase):

    def test_report_format(self):
        selections = [
            {"menu_name": "Lunch 1", "fel_selectat": "ambele"},
            {"menu_name": "Lunch 1", "fel_selectat": "felul2"},
            {"menu_name": "Dieta", "fel_selectat": "felul1"},
            {"menu_name": "Dieta", "fel_selectat": "felul1"},
        ]
        report = generate_report_text(selections, "2024-03-15", "str. Test 1")
        self.assertIn("📅 2024-03-15", report)
        self.assertIn("📍 str. Test 1", report)
        self.assertIn("LUNCH 1 MAXI", report)
        self.assertIn("LUNCH 1 STANDARD", report)
        self.assertIn("DIETA MAXI", report)
        self.assertIn("TOTAL PORȚII: 3", report)

    def test_empty_report(self):
        report = generate_report_text([], "2024-01-01", "Office")
        self.assertIn("TOTAL PORȚII: 0", report)


if __name__ == "__main__":
    unittest.main()
