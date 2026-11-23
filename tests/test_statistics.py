from app.services.statistics import parse_line


def test_parse_tab_log():
    line = "2026-11-23T14:21:03\talice\t10.0.0.2\t1.1.1.1\t123\t456\t"
    result = parse_line(line)
    assert result is not None
    assert result["username"] == "alice"
    assert result["bytes_in"] == 123
    assert result["bytes_out"] == 456


def test_reject_malformed_log():
    assert parse_line("garbage") is None
