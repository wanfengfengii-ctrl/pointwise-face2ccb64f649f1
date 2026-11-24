import re
from fractions import Fraction


_METRES = re.compile(r'[+-]?(?:[0-9]+(?:/[0-9]+|\.[0-9]+)?|\.[0-9]+)')


def parse_metres(value: object) -> Fraction:
    """Parse an exact signed metre value from the public input vocabulary."""
    if isinstance(value, Fraction):
        return value
    if type(value) is int:
        return Fraction(value)
    if isinstance(value, str) and _METRES.fullmatch(value):
        try:
            return Fraction(value)
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError(f'invalid metre value {value!r}') from exc
    raise ValueError(f'invalid metre value {value!r}')


def encode_metres(value: object) -> str:
    return str(parse_metres(value))
