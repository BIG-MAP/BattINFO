"""RFC 8785 canonical JSON: the text a BPX file's IRI is hashed from.

The IRI names the parameters, not the bytes (IDENTIFIER_POLICY 6.3), so the
canonical form has to agree with every other JCS implementation: the number
vectors are RFC 8785 Appendix B, and the worked example is section 3.2.4.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo._jcs import canonical_json, canonical_json_bytes, es_number  # noqa: E402

# RFC 8785 Appendix B: IEEE-754 bit patterns and their canonical text.
APPENDIX_B = [
    ("0000000000000000", "0"),
    ("8000000000000000", "0"),
    ("0000000000000001", "5e-324"),
    ("8000000000000001", "-5e-324"),
    ("7fefffffffffffff", "1.7976931348623157e+308"),
    ("ffefffffffffffff", "-1.7976931348623157e+308"),
    ("4340000000000000", "9007199254740992"),
    ("c340000000000000", "-9007199254740992"),
    ("4430000000000000", "295147905179352830000"),
    ("44b52d02c7e14af5", "9.999999999999997e+22"),
    ("44b52d02c7e14af6", "1e+23"),
    ("44b52d02c7e14af7", "1.0000000000000001e+23"),
    ("444b1ae4d6e2ef4e", "999999999999999700000"),
    ("444b1ae4d6e2ef4f", "999999999999999900000"),
    ("444b1ae4d6e2ef50", "1e+21"),
    ("3eb0c6f7a0b5ed8c", "9.999999999999997e-7"),
    ("3eb0c6f7a0b5ed8d", "0.000001"),
    ("41b3de4355555553", "333333333.3333332"),
    ("41b3de4355555554", "333333333.33333325"),
    ("41b3de4355555555", "333333333.3333333"),
    ("41b3de4355555556", "333333333.3333334"),
    ("41b3de4355555557", "333333333.33333343"),
    ("becbf647612f3696", "-0.0000033333333333333333"),
    ("43143ff3c1cb0959", "1424953923781206.2"),
]


def _double(bits: str) -> float:
    return struct.unpack(">d", bytes.fromhex(bits))[0]


@pytest.mark.parametrize(("bits", "expected"), APPENDIX_B)
def test_appendix_b_numbers(bits: str, expected: str) -> None:
    assert es_number(_double(bits)) == expected
    assert canonical_json([_double(bits)]) == f"[{expected}]"


@pytest.mark.parametrize("bits", ["7fffffffffffffff", "7ff0000000000000", "fff0000000000000"])
def test_appendix_b_nan_and_infinity_are_refused(bits: str) -> None:
    with pytest.raises(ValueError, match="no NaN or Infinity"):
        canonical_json(_double(bits))


def test_section_3_2_4_example() -> None:
    source = r"""{
      "numbers": [333333333.33333329, 1E30, 4.50, 2e-3, 0.000000000000000000000000001],
      "string": "\u20ac$\u000F\u000aA'\u0042\u0022\u005c\\\"\/",
      "literals": [null, true, false]
    }"""
    expected = r"""{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],"string":"€$\u000f\nA'B\"\\\\\"/"}"""
    assert canonical_json(json.loads(source)) == expected
    assert canonical_json_bytes(json.loads(source)) == expected.encode("utf-8")


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("1", "1.0"),
        ("-0.0", "0.0"),
        ("-0", "0"),
        ("1e-05", "0.00001"),
        ("1e21", "1e+21"),
        ("1E21", "1000000000000000000000"),
        ("4.50", "4.5"),
        ("100", "1e2"),
        ("0.1", "0.10000000000000000555"),
    ],
)
def test_equal_numbers_spelled_differently_are_one_number(first: str, second: str) -> None:
    assert canonical_json(json.loads(first)) == canonical_json(json.loads(second))


def test_number_forms() -> None:
    # Plain notation from 1e-6 up to 1e21, exponents outside, never a ".0".
    assert canonical_json([1.0, -0.0, 1e-05, 1e-06, 1e-07, 1e20, 1e21, 123.0, 0.5]) == (
        "[1,0,0.00001,0.000001,1e-7,100000000000000000000,1e+21,123,0.5]"
    )
    # Integers are doubles too, so beyond 2**53 they round like any double.
    assert canonical_json(2**53 + 1) == "9007199254740992"


def test_keys_sort_by_utf16_code_units() -> None:
    # The RFC 8785 3.2.3 ordering, with U+10000 standing in for the RFC's
    # astral character: it is a surrogate pair in UTF-16, so it sorts before
    # U+FB33 there even though its code point is larger.
    keys = [chr(0x20AC), "\r", chr(0xFB33), "1", chr(0x10000), chr(0x80), chr(0xF6)]
    canonical = canonical_json({key: index for index, key in enumerate(keys)})
    order = [key for key, _ in json.loads(canonical, object_pairs_hook=list)]
    assert order == ["\r", "1", chr(0x80), chr(0xF6), chr(0x20AC), chr(0x10000), chr(0xFB33)]
    assert sorted(keys)[-1] == chr(0x10000)  # code-point order would differ


def test_member_order_and_whitespace_do_not_matter() -> None:
    a = json.loads('{"b": [1, 2, {"y": 1, "x": 2}], "a": "z"}')
    b = json.loads('{\n  "a": "z",\n  "b": [1.0, 2.0, {"x": 2, "y": 1}]\n}')
    assert canonical_json(a) == canonical_json(b) == '{"a":"z","b":[1,2,{"x":2,"y":1}]}'


def test_strings_get_minimal_escaping() -> None:
    value = "Tops\N{LATIN SMALL LETTER O WITH STROKE}e \N{EURO SIGN} \N{LINE SEPARATOR}" + '"\\\n\t\x1f\x7f/'
    expected = (
        '"Tops\N{LATIN SMALL LETTER O WITH STROKE}e \N{EURO SIGN} \N{LINE SEPARATOR}' + r"\"\\\n\t\u001f" + '\x7f/"'
    )
    assert canonical_json(value) == expected
    # Non-ASCII stays literal and is encoded as UTF-8.
    assert canonical_json_bytes("\N{EURO SIGN}") == b'"\xe2\x82\xac"'


def test_unrepresentable_values_name_their_path() -> None:
    with pytest.raises(ValueError, match=r"\['Parameterisation'\]\['Separator'\]\['Porosity'\]"):
        canonical_json({"Parameterisation": {"Separator": {"Porosity": float("nan")}}})
    with pytest.raises(ValueError, match=r"\['y'\]\[1\]"):
        canonical_json({"y": [1.0, float("-inf")]})
    with pytest.raises(ValueError, match="too large"):
        canonical_json(10**400)
    with pytest.raises(ValueError, match="surrogate"):
        canonical_json({"Title": json.loads(r'"\ud800"')})
    with pytest.raises(ValueError, match="key 1"):
        canonical_json({1: "one"})
    with pytest.raises(TypeError, match="set"):
        canonical_json({"x": {1, 2}})


def test_numpy_values_count_as_what_they_hold() -> None:
    np = pytest.importorskip("numpy")
    with_numpy = {
        "f32": np.float32(0.47),
        "f64": np.float64(0.25),
        "i64": np.int64(20),
        "flag": np.bool_(True),
        "table": {"x": np.array([0.0, 0.5, 1.0]), "y": np.array([[1, 2], [3, 4]])},
        "zero_d": np.array(2.5),
    }
    plain = {
        "f32": float(np.float32(0.47)),
        "f64": 0.25,
        "i64": 20,
        "flag": True,
        "table": {"x": [0, 0.5, 1], "y": [[1, 2], [3, 4]]},
        "zero_d": 2.5,
    }
    assert canonical_json(with_numpy) == canonical_json(plain)
    with pytest.raises(ValueError, match=r"\['v'\]"):
        canonical_json({"v": np.float64("nan")})
