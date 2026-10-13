"""JSON Canonicalization Scheme (RFC 8785): one byte string per JSON value.

A parameter file's IRI names its parameters, not the bytes it happened to be
written with (IDENTIFIER_POLICY 6.3), so two copies that say the same thing
must hash the same. ``json.dumps(sort_keys=True)`` falls short of that: Python
keeps the spelling of a number (``1`` and ``1.0``, ``-0.0`` and ``0.0`` stay
different) and sorts keys by code point. RFC 8785 settles every choice a
serialiser can make:

- every number is an IEEE-754 double written the way ECMAScript's
  ``Number.prototype.toString`` writes it, so ``1``, ``1.0`` and ``1e0`` all
  become ``1`` and ``1e-05`` becomes ``0.00001``;
- object members are sorted by the UTF-16 code units of their keys;
- strings get the minimal JSON escaping and everything else stays literal;
- there is no whitespace, and the text is encoded as UTF-8.

The input is a parsed JSON value. numpy scalars and arrays count as the plain
values they hold (numpy is never imported here). Anything JCS cannot express
(NaN, infinities, lone surrogates, non-string keys, other Python types) is
refused with the path of the offending value.

:func:`loads` parses JSON text the way RFC 8785 expects its input (I-JSON,
RFC 7493): an object that repeats a key is refused, since JSON parsers
disagree on which of the two values counts, and so are a number too large for
a double and the non-JSON literals NaN and Infinity. A UTF-8 byte order mark
is skipped.

This is vendored rather than taken from a package so that the uids minted
from it cannot move with someone else's release. The battinfo-registry
vendors this module verbatim, so it imports the standard library only.
Reference: https://www.rfc-editor.org/rfc/rfc8785
"""

from __future__ import annotations

import json
import math
import re
from decimal import Decimal
from typing import Any, Mapping

__all__ = ["canonical_json", "canonical_json_bytes", "es_number", "loads"]


def canonical_json(value: Any) -> str:
    """The RFC 8785 canonical text of ``value`` (encode it as UTF-8 to hash it)."""
    parts: list[str] = []
    _write(value, "", parts)
    return "".join(parts)


def canonical_json_bytes(value: Any) -> bytes:
    """The RFC 8785 canonical form of ``value`` as UTF-8 bytes."""
    return canonical_json(value).encode("utf-8")


def es_number(value: float | int, path: str = "") -> str:
    """Write a number as ECMAScript ``Number.prototype.toString`` does (RFC 8785 3.2.2.3).

    JSON numbers are doubles in JCS, so an int goes through ``float`` first:
    ``1`` and ``1.0`` are the same number and print as ``1``.
    """
    try:
        number = float(value)
    except OverflowError:
        raise ValueError(f"{_where(path)} is {value!r}, too large for a JSON number (RFC 8785).") from None
    if not math.isfinite(number):
        raise ValueError(f"{_where(path)} is {number!r}; RFC 8785 JSON has no NaN or Infinity.")
    if number == 0:
        return "0"  # -0.0 prints as 0 too
    # repr() gives the shortest digit string that reads back as the same
    # double, choosing the closest one when several are equally short. That
    # is exactly the digit string ECMAScript's Number::toString picks,
    # so only the layout of those digits is left to do.
    text = repr(number)
    if "e" not in text:
        # Python writes plain notation for 1e-4 <= |x| < 1e16, a range where
        # ECMAScript does too, with the same digits; only the ".0" Python puts
        # on integral values differs. This is the common case, so take it
        # without the general layout below.
        return text[:-2] if text.endswith(".0") else text
    sign = "-" if number < 0 else ""
    decimal = Decimal(text.lstrip("-")).as_tuple()
    digits = "".join(str(d) for d in decimal.digits).rstrip("0")
    k = len(digits)
    # The value is 0.<digits> x 10^n, i.e. int(digits) x 10^(n - k).
    # Only NaN and infinities have a string exponent, and they were refused above.
    if not isinstance(decimal.exponent, int):
        raise ValueError(f"{_where(path)} is {number!r}; RFC 8785 JSON has no NaN or Infinity.")
    n = decimal.exponent + len(decimal.digits)
    # The four layouts Number::toString chooses between. Python already
    # wrote everything in 1e-4 <= |x| < 1e16 above, so the second branch is
    # kept only so the function follows the specification as written.
    if k <= n <= 21:
        text = digits + "0" * (n - k)  # an integer, written out in full: 1e+20 -> 100000000000000000000
    elif 0 < n <= 21:
        text = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        text = "0." + "0" * -n + digits  # 1e-05 -> 0.00001, but 1e-07 stays an exponent
    else:
        exponent = n - 1
        mantissa = digits if k == 1 else digits[0] + "." + digits[1:]
        text = f"{mantissa}e{'+' if exponent >= 0 else '-'}{abs(exponent)}"  # 1e+21, 5e-324
    return sign + text


# The escapes JSON requires, in their short forms where JSON has one; every
# other control character is written \u00xx with lowercase hex, and nothing
# else is escaped (RFC 8785 3.2.2.2).
_SHORT_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}
_NEEDS_ESCAPE = re.compile(r'[\x00-\x1f"\\]')


def _escape(match: re.Match[str]) -> str:
    char = match.group()
    return _SHORT_ESCAPES.get(char) or f"\\u{ord(char):04x}"


def _string(text: str, path: str) -> str:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        # A lone surrogate (JSON "\ud800" parses into one) is not Unicode text,
        # and I-JSON, which JCS builds on, rejects it.
        raise ValueError(f"{_where(path)} holds a lone UTF-16 surrogate, which RFC 8785 rejects.") from None
    return '"' + _NEEDS_ESCAPE.sub(_escape, text) + '"'


def _from_numpy(value: Any) -> Any:
    """A numpy scalar or array as the plain Python value it holds; anything else as-is."""
    module = type(value).__module__
    if module != "numpy" and not module.startswith("numpy."):
        return value
    if getattr(value, "ndim", None) == 0 and hasattr(value, "item"):
        return value.item()  # np.float32(0.5) -> 0.5, np.int64(1) -> 1, np.bool_ -> bool
    if hasattr(value, "tolist"):
        return value.tolist()  # an ndarray, as nested lists of plain values
    return value


def _write(value: Any, path: str, out: list[str]) -> None:
    value = _from_numpy(value)
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, str):
        out.append(_string(value, path))
    elif isinstance(value, (int, float)):
        out.append(es_number(value, path))
    elif isinstance(value, Mapping):
        members: list[tuple[str, Any]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{_where(path)} has the key {key!r}; JSON object keys are strings.")
            members.append((key, item))
        # Sort by UTF-16 code units, as RFC 8785 3.2.3 says. Big-endian UTF-16
        # bytes compare in code-unit order; plain str order (code points)
        # differs once a key holds characters beyond U+FFFF.
        encoded = [(_string(key, f"{path}[{key!r}]"), key, item) for key, item in members]
        encoded.sort(key=lambda entry: entry[1].encode("utf-16-be"))
        out.append("{")
        for index, (key_text, key, item) in enumerate(encoded):
            if index:
                out.append(",")
            out.append(key_text)
            out.append(":")
            _write(item, f"{path}[{key!r}]", out)
        out.append("}")
    elif isinstance(value, (list, tuple)):
        out.append("[")
        for index, item in enumerate(value):
            if index:
                out.append(",")
            _write(item, f"{path}[{index}]", out)
        out.append("]")
    else:
        raise TypeError(f"{_where(path)} is a {type(value).__name__}, which is not a JSON value.")


def _where(path: str) -> str:
    return f"the value at {path}" if path else "the document"


# ── Parsing ──────────────────────────────────────────────────────────────────


class _Members(list):  # type: ignore[type-arg]
    """One JSON object's members in file order, duplicates kept, until :func:`_checked` reads them."""


class _Refused:
    """A literal that has no RFC 8785 form, kept until its path is known."""

    def __init__(self, text: str, reason: str) -> None:
        self.text = text
        self.reason = reason


# A double holds at most about 1.8e308, so an integer literal of more digits
# cannot be one (and int() refuses very long literals on its own).
_MAX_DOUBLE_DIGITS = 309


def _parse_float(text: str) -> Any:
    value = float(text)
    if math.isinf(value):
        return _Refused(text, "too large")
    return value


def _parse_int(text: str) -> Any:
    if len(text.lstrip("-")) > _MAX_DOUBLE_DIGITS:
        return _Refused(text, "too large")
    value = int(text)
    try:
        float(value)
    except OverflowError:
        return _Refused(text, "too large")
    return value


def _parse_constant(name: str) -> Any:
    return _Refused(name, "not JSON")


def loads(data: bytes | bytearray | str) -> Any:
    """Parse JSON text into the values RFC 8785 canonicalizes (I-JSON, RFC 7493).

    Bytes must be UTF-8; a leading byte order mark is skipped (the bytes'
    own checksum is the caller's business). Refused with a ``ValueError``
    that says where: an object repeating a key, a number too large for a
    double, the non-JSON literals NaN, Infinity and -Infinity, and text that
    is not JSON. Objects come back as dicts in file order.
    """
    if isinstance(data, (bytes, bytearray)):
        raw = bytes(data)
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"the bytes are not UTF-8 text: {exc}") from None
    elif isinstance(data, str):
        text = data[1:] if data.startswith("﻿") else data
    else:
        raise TypeError(f"loads() reads bytes or str, not {type(data).__name__}.")
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_Members,
            parse_float=_parse_float,
            parse_int=_parse_int,
            parse_constant=_parse_constant,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}") from None
    return _checked(parsed, "")


def _checked(value: Any, path: str) -> Any:
    """``value`` with every object a dict, refusing repeated keys and unrepresentable literals."""
    if isinstance(value, _Members):
        out: dict[str, Any] = {}
        for key, item in value:
            if key in out:
                raise ValueError(
                    f"{_where(path)} repeats the key {key!r}. JSON parsers disagree on which of the "
                    "two values counts, so RFC 8785 (I-JSON) refuses an object with a repeated key."
                )
            out[key] = _checked(item, f"{path}[{key!r}]")
        return out
    if isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, (list, _Refused)):  # _Members is a list too
                value[index] = _checked(item, f"{path}[{index}]")
        return value
    if isinstance(value, _Refused):
        if value.reason == "too large":
            raise ValueError(f"{_where(path)} is {value.text[:40]}, too large for a JSON number (RFC 8785).")
        raise ValueError(
            f"{_where(path)} is {value.text}, which is not JSON (RFC 8259): RFC 8785 JSON has no NaN or Infinity."
        )
    return value
