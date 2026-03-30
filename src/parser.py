from dataclasses import dataclass
from typing import Optional, Mapping, OrderedDict, Union
from enum import Enum
import os
import errno


class ApproxFileSize:
    """Approximate file size in X MB/GB/etc"""
    def __init__(self, file_size: str):
        pass


class ItemStatus(Enum):
    """Item status (specified in [ ])"""
    NoStatus = 0   # [ ] Not installed
    TODO = 1       # [*] Item marked for future install
    Installed = 2  # [i] Generic installed status without specifying the install method

ITEM_STATUS_MAP = {' ': ItemStatus.NoStatus, '*': ItemStatus.TODO, 'i': ItemStatus.Installed}


@dataclass
class Item:
    """A single item in a group, a piece of software/knowledge/etc"""
    name: str             # Short item name, same as in Name:foo (without Name:)
    installed: ItemStatus # Status, which is specified in brackets [ ]
    size: ApproxFileSize  # Estimated item size
    attrs: Mapping[str, str]  # Key-value pairs of arguments (Priority:XYZ,Requires:FOO)
    # TODO check if str-str mappings are OK
    link: Optional[str]   # Project link, may be None

    desc: Optional[str]  # Item description, may be None
    warn: Optional[str]  # Warning if the item is missing
    repo: Mapping[str, str] # Repository information


@dataclass
class Include:
    """Include statement which links to another group in the current dir"""
    group: Group   # Included group object
    attrs: Mapping[str, str]  # Key-value pairs of arguments, may increase/decrease priority of the whole group


@dataclass
class Group:
    """Represents a single file (a/b/c.txt) with items"""
    name: str  # Short group name, same as the filename without .txt (foo.txt)
    desc: Optional[str]   # Group description, may be None
    items: OrderedDict[str, Union[Item, Include]]  # Items or include statements



class Repo:
    """Main repository object, stores the groups/items and handles main operations"""

    def __init__(self):
        self.group = Group()

    def load(self, path: str) -> None:
        """Load the repository from the directory"""
        try:
            with open(os.path.join(path, "index.txt"), 'r') as f:
                raw = f.readlines()
        except OSError as e:
            raise OSError(errno.ENOENT, f"Could not find {path}/index.txt. Are you sure that {path} is a repo?") from e


def _load_group(repo: Repo, path: str) -> Group:
    """Load the group from the file"""
    try:
        with open(path, 'r') as f:
            lines = f.readlines()
    except OSError as e:
        raise OSError(errno.ENOENT, f"Could not find {path}") from e

    # Parsing logic
    # =============
    for line in lines:
        l = line.strip()
        # Get the line type
        if len(l) == 0:
            continue  # Empty line

        elif l[0] == "[":
            # Item description
            # ----------------
            pass


def _parse_item_decl(line) -> Item:
    """Parse the item declaration without Desc/Warn/Repo fields"""

    tokens = line.split(' ')
    if len(tokens) != 5:
        raise ValueError(f"Bad item declaration: {line}")

    # Parse [ ]
    if len(tokens[0]) != 3 or tokens[2] != ']' or tokens[1] not in ITEM_STATUS_MAP:  # '[' is used as the item decl marker
        raise ValueError(f"Bad item status field: {line}")
    status = ITEM_STATUS_MAP[tokens[2]]

    # Parse Name:foo
    if not tokens[1].startswith("Name:"):
        raise ValueError(f"Bad name field: {tokens[1]}. Names must be specified in the format Name:foo")
    # TODO check for re-declarations in validate()
    # TODO check for valid symbols in validate()
