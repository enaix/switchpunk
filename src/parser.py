from dataclasses import dataclass
from typing import Optional, Mapping, MutableMapping, OrderedDict, Union
from enum import Enum
import os
import errno
import re


class ApproxFileSize:
    """Approximate file size in X K/M/G/etc, the format: 0-N digits, 0-M unknown digits (?) and the size unit (any). All file sizes are in powers of 1024 (NIST KiB/MiB/... notation)"""
    regex = re.compile("^([0-9]*)(\?*)((?i:B|K|M|G|T)(?i:iB|B)?)$")

    def __init__(self, file_size: Optional[str] = None):
        if file_size is None:
            self.size: Optional[int] = None
            self.unknown: Optional[str] = None
            self.unit: Optional[str] = None
        else:
            m = re.fullmatch(self.regex, file_size)
            if m is None:
                raise ValueError(f"{file_size} is not a valid approximate file size. It should contain 0-N digits, 0-M unknown digits (?) and the size unit (K/M/G/etc)")
            self.size = int(m.group(1))
            self.unknown = m.group(2)
            self.unit = m.group(3)

    def __repr__(self) -> str:
        if self.size is None:
            return "?"
        return str(self.size) + self.unknown + self.unit



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
    status: ItemStatus # Status, which is specified in brackets [ ]
    size: ApproxFileSize  # Estimated item size
    attrs: MutableMapping[str, str]  # Key-value pairs of arguments (Priority:XYZ,Requires:FOO)
    # TODO check if str-str mappings are OK
    link: Optional[str]   # Project link, may be None

    desc: Optional[str]  # Item description, may be None
    warn: Optional[str]  # Warning if the item is missing
    repo: Optional[MutableMapping[str, str]] # Repository information


@dataclass
class Include:
    """Include statement which links to another group in the current dir"""
    group: Group   # Included group object
    attrs: MutableMapping[str, str]  # Key-value pairs of arguments, may increase/decrease priority of the whole group


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


# Parsing functions
# =================


def _load_group(repo: Repo, path: str, repo_folder: str) -> Group:
    """Load the group from the file"""
    try:
        with open(path, 'r') as f:
            lines = f.readlines()
    except OSError as e:
        raise OSError(errno.ENOENT, f"Could not find {path}") from e

    # Parsing logic
    # =============
    elems: OrderedDict[str, Union[Item, Include]] = OrderedDict()
    desc: Optional[str] = None
    last_elem_name: Optional[str] = None  # Need to check that extra fields match the correct elem
    for line in lines:
        l = line.strip()
        if len(l) == 0:
            continue  # Empty line

        elif l[0] == "[":
            # Item declaration
            item = _parse_item_decl(l)
            elems[item.name] = item
            last_elem_name = item.name

        elif l.startswith("Desc:"):
            # Group description
            pass


def _parse_item_decl(line) -> Item:
    """Parse the item declaration without Desc/Warn/Repo fields"""

    tokens = line.split(' ')
    if len(tokens) != 5:
        raise ValueError(f"Bad item declaration: {line}")

    # Parse [ ]
    if len(tokens[0]) != 3 or tokens[0][2] != ']' or tokens[0][1] not in ITEM_STATUS_MAP:  # '[' is used as the item decl marker
        raise ValueError(f"Bad item status field: {line}")
    status = ITEM_STATUS_MAP[tokens[0][1]]

    # Parse Name:foo
    if not tokens[1].startswith("Name:") and len(tokens[1]) < 6:
        raise ValueError(f"Bad name field: {tokens[1]}. Names must be specified in the format Name:foo")
    # TODO check for re-declarations in validate()
    # TODO check for valid symbols in validate()
    name = tokens[1][5:]

    # Parse approx file size
    try:
        size = ApproxFileSize(tokens[2])
    except ValueError as e:
        raise ValueError(f"Bad size field: {tokens[2]}") from e

    # Parse KV pairs
    pairs: MutableMapping[str, str] = {}
    if tokens[3].lower() != "none":
        pairs_raw = tokens[3].split(',')
        for pair in pairs_raw:
            kv = pair.split(':')
            if len(kv) != 2:
                raise ValueError(f"Bad key-value pairs: {tokens[2]}. Attributes should be specified as Key1:Value1,Key2:Value2")
            pairs[kv[0]] = kv[1]

    # Parse the link
    link = tokens[4]

    return Item(name=name, status=status, size=size, attrs=pairs, link=link, desc=None, warn=None, repo=None)
