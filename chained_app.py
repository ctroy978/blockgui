#!/usr/bin/env python
import sys


def main() -> None:
    if len(sys.argv) > 1:
        command = sys.argv[1]
        print(f"Received command: {command}")
    else:
        print("No command provided")


if __name__ == "__main__":
    main()
