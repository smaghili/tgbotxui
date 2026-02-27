import unittest

from bot.pagination import chunk_buttons, paginate_window


class PaginationTests(unittest.TestCase):
    def test_paginate_window_bounds(self) -> None:
        page, total_pages, start, end = paginate_window(total=101, page=99, per_page=20)
        self.assertEqual(total_pages, 6)
        self.assertEqual(page, 6)
        self.assertEqual(start, 100)
        self.assertEqual(end, 120)

    def test_paginate_window_min_page(self) -> None:
        page, total_pages, start, end = paginate_window(total=0, page=-1, per_page=20)
        self.assertEqual(total_pages, 1)
        self.assertEqual(page, 1)
        self.assertEqual(start, 0)
        self.assertEqual(end, 20)

    def test_chunk_buttons_two_columns(self) -> None:
        rows = chunk_buttons([1, 2, 3, 4, 5], columns=2)
        self.assertEqual(rows, [[1, 2], [3, 4], [5]])


if __name__ == "__main__":
    unittest.main()
