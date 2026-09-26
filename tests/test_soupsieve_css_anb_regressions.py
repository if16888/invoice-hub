"""Regression tests for CSS An+B selector boundaries in SoupSieve."""

from __future__ import annotations

import unittest

from bs4 import BeautifulSoup


class SoupSieveAnPlusBRegressionTests(unittest.TestCase):
    def test_an_plus_b_sequences_touching_zero_use_positive_indices(self) -> None:
        html = "<ul>" + "".join(
            f'<li id="{index}">{index}</li>' for index in range(1, 7)
        ) + "</ul>"
        soup = BeautifulSoup(html, "html.parser")
        selectors_and_expected = (
            ("li:nth-child(2n-2)", ["2", "4", "6"]),
            ("li:nth-of-type(2n-2)", ["2", "4", "6"]),
            ("li:nth-last-child(2n-2)", ["1", "3", "5"]),
            ("li:nth-child(n-1)", ["1", "2", "3", "4", "5", "6"]),
        )

        for selector, expected in selectors_and_expected:
            with self.subTest(selector=selector):
                actual = [node["id"] for node in soup.select(selector)]
                self.assertEqual(expected, actual)
