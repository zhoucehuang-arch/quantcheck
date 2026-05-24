import unittest

from quantcheck.scrape_parse import extract_pick_date, rows_from_card_texts, rows_from_matrix


class ScrapeParseTests(unittest.TestCase):
    def test_rows_from_new_monthly_table_header(self):
        matrix = [
            ["Company", "Symbol", "Held Since", "Price", "Return", "Sector", "Rating", "GT Score"],
            ["Acme Corp", "ACME", "05/01/26", "$123.45", "+12.5%", "Technology", "Buy", "87"],
            ["$123.45 P/E (TTM) 20 Market Cap $10B", "", "", "", "", "", "", ""],
        ]

        self.assertEqual(
            rows_from_matrix(matrix, "monthly"),
            [{
                "company": "Acme Corp",
                "symbol": "ACME",
                "held_since": "05/01/26",
                "current_price": "$123.45",
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

    def test_rows_from_logged_in_monthly_table_header(self):
        matrix = [
            ["COMPANY", "SYMBOL", "HELD SINCE", "PRICE", "RETURN", "SECTOR", "RATING", "GT SCORE", ""],
            [
                "Applied Optoelectronics, Inc.",
                "AAOI",
                "2026-04-01",
                "$181.49",
                "+101.31%",
                "Electronic Technology",
                "Strong Buy",
                "4.98/5",
                "",
            ],
        ]

        self.assertEqual(
            rows_from_matrix(matrix, "monthly"),
            [{
                "company": "Applied Optoelectronics, Inc.",
                "symbol": "AAOI",
                "held_since": "2026-04-01",
                "current_price": "$181.49",
                "return": "+101.31%",
                "sector": "Electronic Technology",
                "rating": "Strong Buy",
                "gt_score": "4.98/5",
            }],
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

    def test_week_of_date_is_supported(self):
        text = "Weekly Picks Guidance only Week of May 25, 2026 COMPANY SYMBOL SECTOR"

        self.assertEqual(extract_pick_date(text, "weekly"), "Week of May 25, 2026")


if __name__ == "__main__":
    unittest.main()
