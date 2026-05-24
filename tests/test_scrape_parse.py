import unittest

from quantcheck.scrape_parse import extract_pick_date, rows_from_card_texts, rows_from_matrix


class ScrapeParseTests(unittest.TestCase):
    def test_rows_from_new_monthly_table_header(self):
        matrix = [
            ["Company", "Symbol", "Held Since", "Return", "Sector", "Rating", "GT Score"],
            ["Acme Corp", "ACME", "05/01/26", "+12.5%", "Technology", "Buy", "87"],
            ["$123.45 P/E (TTM) 20 Market Cap $10B", "", "", "", "", "", ""],
        ]

        self.assertEqual(
            rows_from_matrix(matrix, "monthly"),
            [{
                "company": "Acme Corp",
                "symbol": "ACME",
                "held_since": "05/01/26",
                "return": "+12.5%",
                "sector": "Technology",
                "rating": "Buy",
                "gt_score": "87",
            }],
        )

    def test_rows_from_new_weekly_table_header(self):
        matrix = [
            ["Company", "Symbol", "Sector", "Rating", "GT Score"],
            ["Beta Inc", "BETA", "Healthcare", "Strong Buy", "91"],
        ]

        self.assertEqual(
            rows_from_matrix(matrix, "weekly"),
            [{"company": "Beta Inc", "symbol": "BETA", "sector": "Healthcare", "rating": "Strong Buy", "gt_score": "91"}],
        )

    def test_rows_from_card_layout(self):
        cards = ["Company: Gamma Ltd Symbol: GAMA Sector: Energy Rating: Buy GT Score: 82"]

        self.assertEqual(
            rows_from_card_texts(cards, "weekly"),
            [{"company": "Gamma Ltd", "symbol": "GAMA", "sector": "Energy", "rating": "Buy", "gt_score": "82"}],
        )

    def test_monthly_holdings_date_is_supported(self):
        text = "Portfolio Return May Holdings 05/01/26 - now Company Symbol Held Since"

        self.assertEqual(extract_pick_date(text, "monthly"), "May Holdings 05/01/26 - now")


if __name__ == "__main__":
    unittest.main()
