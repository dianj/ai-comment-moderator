"""Deterministic detectors: exact, so they are tested case by case."""
import pytest

from moderator.detectors import egn_is_valid, iban_is_valid, is_trivially_empty, looks_bulgarian, scan


def kinds(text):
    return [(f.kind, f.value) for f in scan(text)]


@pytest.mark.parametrize("egn", ["8503154126", "9207015367", "0041010002"])  # the last: born 2000-01-01
def test_valid_egn(egn):
    assert egn_is_valid(egn)


@pytest.mark.parametrize("egn, why", [
    ("4102938475", "month 02, day 93 and a wrong checksum"),
    ("8503154127", "wrong checksum"),
    ("8513154120", "month 13 does not exist"),
    ("123", "too short"),
])
def test_invalid_egn(egn, why):
    assert not egn_is_valid(egn), why


def test_egn_found_in_text_but_order_number_is_not():
    assert kinds("ЕГН-то на съседа: 8503154126") == [("egn", "8503154126")]
    assert kinds("Номерът на поръчката ми е 4102938475") == []


def test_iban():
    assert iban_is_valid("BG80BNBG96611020345678")
    assert iban_is_valid("BG80 BNBG 9661 1020 3456 78")
    assert not iban_is_valid("BG81BNBG96611020345678")
    assert kinds("сметка BG80BNBG96611020345678.") == [("iban", "BG80BNBG96611020345678")]


@pytest.mark.parametrize("text, number", [
    ("Обадете се на 0888 123 456, моля", "0888 123 456"),
    ("Моят телефон е +359 87 654 3210", "+359 87 654 3210"),
    ("Офисът: 02 123 4567", "02 123 4567"),
    ("UK office +44 20 7946 0958", "+44 20 7946 0958"),
])
def test_phone_numbers(text, number):
    assert kinds(text) == [("phone", number)]


@pytest.mark.parametrize("text", [
    "The 2025 survey of 1200 companies",
    "Running a 26B model on 16 GB VRAM",
    "Версия 4.2.1 излезе на 12.11.2026",
])
def test_numbers_that_are_not_phones(text):
    assert kinds(text) == []


def test_email_and_links():
    assert kinds("Mail john.doe.1990@gmail.com or see https://example.org/x") == [
        ("email", "john.doe.1990@gmail.com"), ("url", "https://example.org/x")]


@pytest.mark.parametrize("text, empty", [
    (".", True), ("?!...", True), ("   ", True), ("аааааааа", True), ("!!!!!!", True),
    ("Thanks!", False), ("+1", False), ("👍", False), ("ok", False), ("aaa", False),
])
def test_trivially_empty(text, empty):
    assert is_trivially_empty(text) is empty


def test_language_guess():
    assert looks_bulgarian("Чакам втората част 👍")
    assert not looks_bulgarian("Great article, thanks")
