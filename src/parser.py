from dataclasses import dataclass, field
from typing import Optional, Mapping, MutableMapping, OrderedDict, Sequence, MutableSequence, Tuple, Union
import collections
from enum import Enum
from pathlib import Path
import os
import errno
import re
import weakref
import logging

logger = logging.getLogger(__name__)


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
            self.unknown = m.group(2)
            self.size = 10 ** len(self.unknown)  # No ambiguity means 1, '?' means 10, '??' means 100
            if m.group(1):
                self.size *= int(m.group(1))
            self.unit = m.group(3)

    def __repr__(self) -> str:
        if self.size is None or self.unknown is None or self.unit is None:
            return "?"
        return str(self.size) + self.unknown + self.unit



class ItemStatus(Enum):
    """Item status (specified in [ ])"""
    NoStatus = 0   # [.] Not installed
    TODO = 1       # [*] Item marked for future install
    Installed = 2  # [i] Generic installed status without specifying the install method

ITEM_STATUS_MAP: Mapping = {'.': ItemStatus.NoStatus, '*': ItemStatus.TODO, 'i': ItemStatus.Installed}


class Priority(Enum):
    """Priority status (specified in Priority:xyz)"""
    # Priority:None corresponds to None object
    Low = 1        # Priority:Low
    Medium = 2     # Priority:Medium
    High = 3       # Priority:High
    Extreme = 4    # Priority:Extreme

PRIORITY_MAP: Mapping = {"Low": Priority.Low, "Medium": Priority.Medium, "High": Priority.High, "Extreme": Priority.Extreme}  # str -> Priority enum map, has no Priority:None in order to avoid broken references


class RequiresAttr:
    """Requires:foo/RequiresAny:bar/RequiresAll:xyz item attribute"""
    def __init__(self, name: str, requires_all: bool = False):
        self.name = name   # Name of the item or group
        self.requires_all = requires_all  # (Only for groups) Require all items in the group, otherwise require only one

    def __repr__(self) -> str:
        return f"Requires(name={self.name}, all={self.requires_all})"



class Item:
    """A single item in a group, a piece of software/knowledge/etc"""
    def __init__(self, name: str, repo: Repo, status: ItemStatus, size: ApproxFileSize, link: Optional[str], requires: Optional[MutableSequence[RequiresAttr]] = None, priority: Optional[Priority] = None):
        self.name = name             # Short item name, same as in Name:foo (without Name:)
        self._repo = weakref.ref(repo) # Ref to the repo object
        self.status = status     # Status, which is specified in brackets [ ]
        self.size = size  # Estimated item size
        #attrs: MutableMapping[str, str]  # Key-value pairs of arguments (Priority:XYZ,Requires:FOO)
        self.link = link   # Project link, may be None

        if requires is None:
            self.requires: MutableSequence[RequiresAttr] = []
        else:
            self.requires = requires  # List of Requires: attributes
        self.priority = priority  # Priority attribute

        self.desc: Optional[str] = None  # Item description, may be None
        self.warn: Optional[str] = None  # Warning if the item is missing
        self.install_info: Optional[MutableMapping[str, str]] = None  # Installation information (package names)

    def __repr__(self) -> str:
        return f"Item(name={self.name}, status={self.status}, size={self.size}, link={self.link}, requires={self.requires}, priority={self.priority})"

    def tree(self, depth=0) -> str:
        return '   ' * depth + self.__repr__()


class Group:
    """Represents a single file (a/b/c.txt) with items"""
    def __init__(self, name: str, repo: Repo, desc: Optional[str], warn: Optional[str], items: OrderedDict[str, Union[Item, Group]], priority: Optional[Priority] = None):
        self.name = name  # Full group name without .txt (foo.txt)
        self._repo = weakref.ref(Repo)  # Ref to the repo object
        self.desc = desc   # Group description, may be None
        self.warn = warn   # Group warning, may be None
        self.items = items  # Items or subgroups
        self.priority = priority  # Priority override
        self.default: Optional[str] = None  # Default item in current group

    def __repr__(self) -> str:
        return f"Group(name={self.name}, priority={self.priority}, default={self.default})"

    def tree(self, depth=0) -> str:
        return '   ' * depth + self.__repr__() + '\n' + '\n'.join([x.tree(depth + 1) for x in self.items.values()])



class Repo:
    """Main repository object, stores the groups/items and handles main operations"""

    def __init__(self, path: str):
        self.group = _load_group(self, path, path)


# Parsing functions
# =================


def _fmt_line(line: str, path: str, l: int):
    """Format the line where a parsing error occured"""
    return f"At {path}:{l+1}:\n{line}\n{'^' * len(line)}"


def _load_group(repo: Repo, repo_path: str, path: str, priority: Optional[Priority] = None) -> Group:
    """Load the group from the file/dir. Path should be absolute"""
    if not path.endswith(".txt"):
        # Get full group path from folder (foo/bar -> foo/bar/bar.txt OR foo/bar -> foo/bar.txt)
        # Group index should be located in foo/bar/xyz/xyz.txt
        _group_path = path + ".txt"
        _group_short_name = os.path.split(path)[1]  # bar
        _group_folder = os.path.join(path, _group_short_name + '.txt')  # get group path in a subfolder
        if os.path.exists(_group_path):
            if os.path.exists(_group_folder):
                raise ValueError(f"The group file {_group_path} and the group folder {_group_folder} cannot exist at the same time")
            path = _group_path
        else:
            path = _group_folder

    # Convert actual path to group name
    path_base_abs = os.path.splitext(path)[0]  # Absolute path
    _path_base_split = os.path.split(path_base_abs)
    if _path_base_split[0].endswith(_path_base_split[1]):
        # Check if this is top-level group file (foo/bar/bar.txt)
        path_base_abs = _path_base_split[0]  # foo/bar/bar -> foo/bar
    path_base = os.path.relpath(path_base_abs, start=repo_path)  # Relative path (from repo)
    full_group_name = Path(path_base).as_posix()

    #print(path, '->', full_group_name)

    try:
        with open(path, 'r') as f:
            lines = f.readlines()
    except OSError as e:
        raise OSError(errno.ENOENT, f"Could not find {path}") from e


    # Parsing logic
    # =============
    elems: OrderedDict[str, Union[Item, Group]] = OrderedDict()
    desc: Optional[str] = None
    warn: Optional[str] = None
    last_elem_name: Optional[str] = None  # Need to check that extra fields match the correct elem
    default: Optional[str] = None
    for i, line in enumerate(lines):
        l = line.strip()
        if len(l) == 0:
            continue  # Empty line

        elif l[0] == "[":
            # Item declaration
            try:
                item, is_default = _parse_item_decl(repo, l)
            except ValueError as e:
                raise ValueError(f"{_fmt_line(l, path, i+1)}") from e
            if item.name in elems:
                raise ValueError(f"{_fmt_line(l, path, i+1)}\nRedefinition of {item.name}") from e
            if is_default and default is not None:
                raise ValueError(f"{_fmt_line(l, path, i+1)}\nMore than one default value in group") from e
            elems[item.name] = item
            last_elem_name = item.name
            if is_default:
                default = item.name

        elif l.startswith("Desc:"):
            # Group or item description
            desc_tok = l.split(' ', maxsplit=1)  # The second token is the description itself
            if len(desc_tok) != 2 or len(desc_tok[0]) < 6:
                raise ValueError(f"{_fmt_line(l, path, i+1)}\nDescription should be defined as either Desc:path/to/group ... or Desc:name ...")
            desc_name = desc_tok[0][5:]
            if desc_name == full_group_name:
                # This is the group desc
                desc = desc_tok[1]
            else:
                # This is an item desc
                if desc_name not in elems or type(elems[desc_name]) is not Item or last_elem_name is None or desc_name != last_elem_name:
                    raise ValueError(f"{_fmt_line(l, path, i+1)}\nNo such item {desc_name}. Descriptions must always follow the item declaration")
                elems[desc_name].desc = desc_tok[1]

        elif l.startswith("Warn:"):
            # Group or item warning
            warn_tok = l.split(' ', maxsplit=1)  # The second token is the description itself
            if len(warn_tok) != 2 or len(warn_tok[0]) < 6:
                raise ValueError(f"{_fmt_line(l, path, i+1)}\nWarning should be defined as Warn:path/to/group ... or Desc:name ...")
            warn_name = warn_tok[0][5:]
            if warn_name == full_group_name:
                # This is the group warn
                warn = warn_tok[1]
            else:
                if warn_name not in elems or type(elems[warn_name]) is not Item or last_elem_name is None or warn_name != last_elem_name:
                    raise ValueError(f"{_fmt_line(l, path, i+1)}\nNo such item {warn_name}. Warnings must always follow the item declaration")
                elems[warn_name].warn = warn_tok[1]  # always an Item due to the check above

        elif l.startswith("Repo:"):
            continue  # Skip this field for now

        elif l.startswith("Include:"):
            # Group include statement
            incl_priority: Optional[Priority] = None
            include_tok = l.split(' ', maxsplit=1)

            if len(include_tok[0]) < 9:
                raise ValueError(f"{_fmt_line(l, path, i+1)}\nInclude should be defined as Include:foo Priority:xyz (optional)")
            group_name = include_tok[0][8:]
            if group_name in elems:
                raise ValueError(f"{_fmt_line(l, path, i+1)}\n{group_name} already declared")
            if len(include_tok) == 2:
                # Parse priority
                if not include_tok[1].startswith("Priority:") or len(include_tok[1]) < 10 or include_tok[1][9:] not in list(PRIORITY_MAP.keys()) + ["None"]:
                    raise ValueError(f"{_fmt_line(l, path, i+1)}\nInclude should be defined as Include:foo Priority:xyz (optional). Valid priority values are None, {', '.join([x for x in PRIORITY_MAP.keys()])}")
                priority_value = include_tok[1][9:]
                if priority_value != "None":
                    incl_priority = PRIORITY_MAP[priority_value]

            # Load group
            group_path = os.path.join(path_base_abs, group_name)
            try:
                new_group = _load_group(repo, repo_path, group_path, incl_priority)
            except (ValueError, OSError) as e:
                raise ValueError(f"Failed to import at {path}:{i+1}") from e

            elems[group_name] = new_group

    return Group(name=full_group_name, repo=repo, desc=desc, warn=warn, items=elems, priority=priority)


def _parse_item_decl(repo: Repo, line: str) -> Tuple[Item, bool]:
    """Parse the item declaration without Desc/Warn/Repo fields"""

    tokens = line.split(' ')
    if len(tokens) != 5:
        raise ValueError(f"Bad item declaration: {line}. Item should be defined as [.] Name:foo SIZE Argument1:foo,Argument2:bar LINK")

    # Parse [ ]
    if len(tokens[0]) != 3 or tokens[0][2] != ']' or tokens[0][1] not in ITEM_STATUS_MAP:  # '[' is used as the item decl marker
        raise ValueError(f"Bad item status field: {tokens[0]}. Status should be one of \'.\', \'*\' (selected) or \'i\' (installed)")
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
    priority: Optional[Priority] = None
    requires: MutableSequence[RequiresAttr] = []
    default = False

    if tokens[3] != "None":
        pairs_raw = tokens[3].split(',')
        for pair in pairs_raw:
            kv = pair.split(':')
            if len(kv) != 2:
                raise ValueError(f"Bad key-value pairs: {tokens[3]}. Attributes should be specified as Key1:Value1,Key2:Value2")

            # Parse actual attributes
            if kv[0] == "Priority":
                if kv[1] != "None":
                    if kv[1] not in PRIORITY_MAP:
                        raise ValueError(f"Bad priority value: {kv[1]}. Valid priority values are None, {', '.join([x for x in PRIORITY_MAP.keys()])}")
                    priority = PRIORITY_MAP[kv[1]]
                # else it's None
            elif kv[0] == "Requires":
                # We assume that this is an item
                # We may check that this is not a group by checking that this is a full path
                if '/' in kv[1]:
                    raise ValueError(f"Bad Requires value: {kv[1]}. Requires should reference an item, not a group. Use RequiresAny/RequiresAll instead")
                requires.append(RequiresAttr(kv[1]))
            elif kv[0] == "RequiresAny":
                # We assume that this is the group
                # All groups should have the full path, and this check assumes that requiring the base category (RequiresAny:software) is ill-formed
                if '/' not in kv[1]:
                    raise ValueError(f"Bad RequiresAny value: {kv[1]}. RequiresAny should reference a full group name abc/xyz/name")
                requires.append(RequiresAttr(kv[1], requires_all=False))
            elif kv[0] == "RequiresAll":
                # Same as the RequiresAny
                if '/' not in kv[1]:
                    raise ValueError(f"Bad RequiresAll value: {kv[1]}. RequiresAll should reference a full group name abc/xyz/name")
                requires.append(RequiresAttr(kv[1], requires_all=True))
            elif kv[0] == "Default":
                if kv[1] == "True":
                    default = True
                elif kv[1] != "False":
                    raise ValueError(f"Bad Default value: {kv[1]}. Default should be either True or False")
            else:
                raise ValueError(f"Bad attribute: {kv[0]}. Attribute should be one of Priority, Requires, RequiresAny, RequiresAll, Default. Empty attributes should be None")

    # Parse the link
    link = tokens[4]

    return Item(name=name, repo=repo, status=status, size=size, link=link, requires=requires, priority=priority), default
