"""Append a small synthetic traffic/traceback fixture to a separately followed log."""

import argparse
from datetime import datetime, timezone


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logfile")
    args = parser.parse_args()
    with open(args.logfile, "a", encoding="utf-8") as output:
        for index in range(30):
            status = (200, 200, 201, 404, 503)[index % 5]
            stamp = datetime.now(timezone.utc).isoformat()
            output.write(
                f'{stamp} INFO: 127.0.0.1:54321 - "GET /items/{index % 12}?demo=1 HTTP/1.1" {status} {index + 0.5}ms\n'
            )
        output.write(
            'Traceback (most recent call last):\n  File "demo.py", line 1, in example\n    raise RuntimeError("synthetic example")\nRuntimeError: synthetic example\n'
        )
        output.write("INFO: Synthetic demo batch complete\n")


if __name__ == "__main__":
    main()
