from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import unittest


@dataclass(frozen=True)
class Line:
    price: Decimal
    quantity: int


def invoice_total(lines, tax=Decimal("0.10"), discount=Decimal("0")):
    if tax < 0 or not Decimal("0") <= discount <= Decimal("1"):
        raise ValueError("Invalid tax or discount")
    if any(line.quantity < 0 or line.price < 0 for line in lines):
        raise ValueError("Line items cannot be negative")
    subtotal = sum((line.price * line.quantity for line in lines), Decimal("0"))
    amount = subtotal * (1 - discount) * (1 + tax)
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class InvoiceTests(unittest.TestCase):
    def test_normal_total(self):
        items = [Line(Decimal("12.50"), 2), Line(Decimal("3"), 1)]
        self.assertEqual(invoice_total(items), Decimal("30.80"))

    def test_half_cent_rounds_up(self):
        self.assertEqual(invoice_total([Line(Decimal("0.05"), 1)]), Decimal("0.06"))

    def test_discount(self):
        value = invoice_total([Line(Decimal("19.99"), 2)], discount=Decimal("0.15"))
        self.assertEqual(value, Decimal("37.38"))

    def test_negative_quantity_rejected(self):
        with self.assertRaises(ValueError):
            invoice_total([Line(Decimal("4"), -1)])

    def test_empty_invoice(self):
        self.assertEqual(invoice_total([]), Decimal("0.00"))


if __name__ == "__main__":
    unittest.main()
