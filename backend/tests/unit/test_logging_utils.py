from app.logging_utils import safe


def test_safe_passthrough_plain():
    assert safe("abc") == "abc"


def test_safe_escapes_crlf():
    assert safe("a\nb\rc") == "a\\nb\\rc"  # подделку строк лога (CWE-117) гасим


def test_safe_truncates_to_maxlen():
    assert safe("x" * 300) == "x" * 200
    assert safe("x" * 300, maxlen=5) == "xxxxx"


def test_safe_stringifies_non_str():
    assert safe((7, 7)) == "(7, 7)"
    assert safe(42) == "42"


def test_safe_escape_then_truncate_order():
    # экранирование идёт ДО обрезки: '\n'→'\\n' (2 символа), потом срез по maxlen
    assert safe("\n" * 200, maxlen=4) == "\\n\\n"
