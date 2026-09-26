import pytest

from plotsrv import runtime


def test_oversized_tail_header_stops_at_small_byte_budget(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("column," * 30 + "\n1,2\n")
    with pytest.raises(ValueError, match="header exceeds"):
        runtime._read_csv_tail_rows(source, encoding="utf-8", max_bytes=32, max_rows=2, max_columns=2)


@pytest.mark.parametrize("mode", ["head", "tail"])
def test_appended_rows_do_not_extend_current_preview(tmp_path, monkeypatch, mode):
    source = tmp_path / "source.csv"
    source.write_text("id,value\n1,first\n2,second\n")
    original_size = source.stat().st_size
    real_reader = runtime._LimitedBinaryReader

    class AppendAfterBudget(real_reader):
        def __init__(self, raw, max_bytes):
            super().__init__(raw, max_bytes)
            with source.open("a") as writer:
                writer.write("3,new row\n")

    monkeypatch.setattr(runtime, "_LimitedBinaryReader", AppendAfterBudget)
    reader = getattr(runtime, f"_read_csv_{mode}_rows")
    header, rows, consumed, _ = reader(source, encoding="utf-8", max_bytes=None, max_rows=10, max_columns=2)
    assert header == ["id", "value"]
    assert rows == [["1", "first"], ["2", "second"]]
    assert consumed <= original_size


def test_tail_budget_includes_header_and_partial_row_skip(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("id,value\n1," + "x" * 200 + "\n2,last\n")
    header, rows, consumed, _ = runtime._read_csv_tail_rows(source, encoding="utf-8", max_bytes=40, max_rows=2, max_columns=2)
    assert header == ["id", "value"]
    assert rows == [["2", "last"]]
    assert consumed <= 40


def test_quoted_header_newline_still_works(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text('"multi\nline",value\n1,first\n')
    header, rows, _, _ = runtime._read_csv_tail_rows(source, encoding="utf-8", max_bytes=100, max_rows=2, max_columns=2)
    assert header == ["multi\nline", "value"]
    assert rows == [["1", "first"]]
