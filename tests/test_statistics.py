import gzip
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.tables import UsageDaily
from app.services.statistics import collect_usage, get_recent_websites, parse_line


def test_parse_tab_log():
    line = "2026-11-23T14:21:03\talice\t10.0.0.2\t1.1.1.1\t123\t456\t"
    result = parse_line(line)
    assert result is not None
    assert result["username"] == "alice"
    assert result["bytes_in"] == 123
    assert result["bytes_out"] == 456


def test_reject_malformed_log():
    assert parse_line("garbage") is None


def test_parse_3proxy_literal_tabs_and_epoch_timestamp():
    line = r" 1795690934\talice\t10.0.0.2\t93.184.216.34\t123\t456\t00000\t3128\tCONNECT example.com:443 HTTP/1.1"

    result = parse_line(line)

    assert result is not None
    assert result["timestamp"] == datetime.fromtimestamp(1795690934)
    assert result["username"] == "alice"
    assert result["bytes_in"] == 123
    assert result["bytes_out"] == 456
    assert result["website"] == "example.com"


def test_extract_website_from_connect_and_absolute_http_request():
    connect = parse_line(
        r" 1795690934\talice\t10.0.0.2\t93.184.216.34\t123\t456\t00000\t3128\tCONNECT Example.COM:443 HTTP/1.1"
    )
    request = parse_line(
        r" 1795690935\talice\t10.0.0.2\t93.184.216.34\t123\t456\t00000\t3128\tGET https://www.Example.com/path?q=secret HTTP/1.1"
    )

    assert connect is not None
    assert request is not None
    assert connect["website"] == "example.com"
    assert request["website"] == "www.example.com"


def test_ignore_ip_targets_and_origin_form_requests():
    ip_target = parse_line(
        r" 1795690934\talice\t10.0.0.2\t93.184.216.34\t123\t456\t00000\t3128\tCONNECT 93.184.216.34:443 HTTP/1.1"
    )
    origin_form = parse_line(
        r" 1795690935\talice\t10.0.0.2\t93.184.216.34\t123\t456\t00000\t3128\tGET /path HTTP/1.1"
    )

    assert ip_target is not None
    assert origin_form is not None
    assert ip_target["website"] is None
    assert origin_form["website"] is None


def test_ignore_3proxy_startup_event():
    line = r" 1795690883\t-\t0.0.0.0\t0.0.0.0\t0\t0\t00000\t3128\tAccepting connections"

    assert parse_line(line) is None


def test_collect_usage_reads_base_and_rotated_logs(tmp_path):
    log_file = tmp_path / "3proxy.log"
    log_file.write_text("", encoding="utf-8")
    epoch = int(datetime(2026, 11, 26, 12, 0).timestamp())
    rotated_log = tmp_path / "3proxy.log.2026.11.26"
    rotated_log.write_text(
        rf" {epoch}\talice\t10.0.0.2\t93.184.216.34\t100\t200\t00000\t3128\tCONNECT example"
        "\n",
        encoding="utf-8",
    )
    compressed_log = tmp_path / "3proxy.log.1.gz"
    with gzip.open(compressed_log, "wt", encoding="utf-8") as handle:
        handle.write(
            rf" {epoch}\talice\t10.0.0.2\t93.184.216.34\t300\t400\t00000\t3128\tCONNECT example"
            "\n"
        )
    (tmp_path / "3proxy.log.backup").write_text(
        rf" {epoch}\talice\t10.0.0.2\t93.184.216.34\t999\t999\t00000\t3128\tCONNECT example"
        "\n",
        encoding="utf-8",
    )

    engine = create_engine("sqlite://")
    UsageDaily.__table__.create(engine)
    with Session(engine) as db:
        rows_updated = collect_usage(db, str(log_file))
        row = db.get(UsageDaily, ("alice", datetime.fromtimestamp(epoch).date()))
        rows_updated_again = collect_usage(db, str(log_file))
        assert row is not None
        db.refresh(row)

    assert rows_updated == 1
    assert rows_updated_again == 1
    assert row.bytes_in == 400
    assert row.bytes_out == 600
    assert row.sessions == 2


def test_get_recent_websites_deduplicates_sorts_and_limits(tmp_path):
    log_file = tmp_path / "3proxy.log"
    entries = [
        (100, "alice", "CONNECT Example.com:443 HTTP/1.1"),
        (200, "alice", "GET http://example.com/new HTTP/1.1"),
        (150, "alice", "CONNECT second.example:443 HTTP/1.1"),
        (300, "bob", "CONNECT other.example:443 HTTP/1.1"),
    ]
    entries.extend(
        (time, "alice", f"GET https://site{time}.example/path HTTP/1.1")
        for time in range(400, 409)
    )
    log_file.write_text(
        "".join(
            rf" {timestamp}\t{username}\t10.0.0.2\t93.184.216.34\t1\t2\t00000\t3128\t{request}"
            "\n"
            for timestamp, username, request in entries
        ),
        encoding="utf-8",
    )
    rotated_log = tmp_path / "3proxy.log.2026.11.26"
    rotated_log.write_text(
        r" 300\talice\t10.0.0.2\t93.184.216.34\t1\t2\t00000\t3128\tCONNECT EXAMPLE.COM:443 HTTP/1.1"
        "\n",
        encoding="utf-8",
    )

    websites = get_recent_websites("alice", str(log_file))

    assert len(websites) == 10
    assert websites[0]["domain"] == "site408.example"
    assert websites[0]["last_accessed"] == datetime.fromtimestamp(408).isoformat()
    assert {site["domain"] for site in websites}.isdisjoint({"other.example"})
    example = next(site for site in websites if site["domain"] == "example.com")
    assert example["last_accessed"] == datetime.fromtimestamp(300).isoformat()
    assert len({site["domain"] for site in websites}) == len(websites)
