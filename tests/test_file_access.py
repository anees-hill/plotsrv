import os

import pytest

from plotsrv.file_access import open_regular_file
from plotsrv.runtime import read_head_bytes, read_tail_bytes


@pytest.mark.parametrize("ancestor", [False, True])
def test_replaced_symlink_is_not_followed(tmp_path, ancestor):
    selected = tmp_path / "selected"
    selected.mkdir()
    source = selected / "report.txt"
    source.write_text("original")
    private = tmp_path / "private"
    private.mkdir()
    (private / "report.txt").write_text("private fixture")
    if ancestor:
        selected.rename(tmp_path / "old")
        selected.symlink_to(private, target_is_directory=True)
    else:
        source.unlink()
        source.symlink_to(private / "report.txt")
    for read in (read_head_bytes, read_tail_bytes):
        with pytest.raises(OSError):
            read(source, max_bytes=100)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO")
def test_fifo_is_rejected_without_waiting_for_writer(tmp_path):
    source = tmp_path / "source"
    os.mkfifo(source)
    with pytest.raises(OSError):
        open_regular_file(source)


def test_regular_file_rotation_is_supported_and_open_descriptor_is_stable(tmp_path):
    source = tmp_path / "report.txt"
    source.write_text("first")
    with open_regular_file(source) as opened:
        source.rename(tmp_path / "old.txt")
        source.write_text("second")
        assert opened.read() == b"first"
    with open_regular_file(source) as opened:
        assert opened.read() == b"second"
