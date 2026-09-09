"""Follow a logfile written independently; never modify its producer/logger."""

import argparse
import time

from plotsrv import stream_view


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logfile")
    parser.add_argument("--destination", default=None)
    args = parser.parse_args()
    handle = stream_view(
        source=args.logfile,
        format="uvicorn",
        view_id="web:access",
        label="HTTP log",
        destination=args.destination,
    )
    try:
        while handle.is_observing:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        handle.stop()


if __name__ == "__main__":
    main()
