#!/usr/bin/env python3

import sys
import os

from .parser import *


def main():
    if len(sys.argv) == 1:
        print("usage: switchpunk PATH_TO_REPO")
        sys.exit(0)
    repo = Repo(sys.argv[1])
    print(repo.group.tree())


if __name__ == "__main__":
    main()
