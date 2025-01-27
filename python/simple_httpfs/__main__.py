import argparse
import logging
import os.path as op
import sys

from fuse import FUSE

from .httpfs import HttpFs


def main():
    parser = argparse.ArgumentParser(
        description="""usage: simple-httpfs <mountpoint>"""
    )

    parser.add_argument("mountpoint")

    parser.add_argument(
        "-f",
        "--foreground",
        action="store_true",
        default=False,
        help="Run in the foreground",
    )

    parser.add_argument("--schema", default=None, type=str)

    parser.add_argument("--block-size", default=2 ** 20, type=int)

    parser.add_argument("--disk-cache-size", default=2 ** 30, type=int)

    parser.add_argument("--disk-cache-dir", default="/tmp/xx")

    parser.add_argument(
        "--allow-other",
        action="store_true",
        default=False,
        help="Allow other users to access this fuse",
    )

    parser.add_argument("-l", "--log", default=None, type=str)

    args = vars(parser.parse_args())

    if not op.isdir(args["mountpoint"]):
        print(
            "Mount point must be a directory: {}".format(args["mountpoint"]),
            file=sys.stderr,
        )
        sys.exit(1)

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("simple-httpfs")

    logger.setLevel(logging.DEBUG)

    if args["log"]:
        hdlr = logging.FileHandler(args["log"])
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(module)s: %(message)s"
        )
        hdlr.setFormatter(formatter)
        logger.addHandler(hdlr)

    if args["schema"] is None:
        schema = op.split(args["mountpoint"].strip("/"))[-1]
    else:
        schema = args["schema"]

    if schema not in ["http", "https"]:
        print(
            "Could not infer schema. Try specifying either http, "
            "https or using the --schema argument",
            file=sys.stderr,
        )
        sys.exit(1)

    start_msg = """
Mounting HTTP Filesystem...
    schema: {schema}
    mountpoint: {mountpoint}
    foreground: {foreground}
    allow others: {allow_other}
""".format(
        schema=schema,
        mountpoint=args["mountpoint"],
        foreground=args["foreground"],
        allow_other=args["allow_other"],
    )
    print(start_msg, file=sys.stderr)

    fuse = FUSE(
        HttpFs(
            schema,
            logger=logger,
        ),
        args["mountpoint"],
        foreground=args["foreground"],
        allow_other=args["allow_other"],
        ro=True,
        nothreads=True,
        max_read=262144,
        max_write=262144
    )


if __name__ == "__main__":
    main()
