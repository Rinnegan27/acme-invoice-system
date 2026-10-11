from __future__ import annotations

import argparse
from dotenv import load_dotenv
from pipeline import Pipeline

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(description="Galatiq Invoice Pipeline")
    parser.add_argument("--invoice_path", type=str)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--llm", choices=["stub", "grok"], default="stub")
    args = parser.parse_args()

    pipe = Pipeline(use_grok=(args.llm == "grok"))

    if args.all:
        pipe.process_directory("../data/invoices")
    elif args.invoice_path:
        result = pipe.process_file(args.invoice_path)
        print(result)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
