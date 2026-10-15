"""Tests for hep_index.pyast (static Python API extraction, stdlib ast only)."""
from pathlib import Path

from hep_index.pyast import extract_file, module_name


def write(root: Path, rel: str, text: str) -> str:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    return rel


def rows_by_qual(info):
    return {r.qualname: r for r in info.rows}


def test_module_name_climbs_packages(tmp_path):
    write(tmp_path, "src/pkg/__init__.py", "")
    write(tmp_path, "src/pkg/sub/__init__.py", "")
    write(tmp_path, "src/pkg/sub/mod.py", "")
    write(tmp_path, "scripts/run.py", "")
    assert module_name(tmp_path, "src/pkg/sub/mod.py") == "pkg.sub.mod"
    assert module_name(tmp_path, "src/pkg/sub/__init__.py") == "pkg.sub"
    assert module_name(tmp_path, "src/pkg/__init__.py") == "pkg"
    assert module_name(tmp_path, "scripts/run.py") == "run"   # not a package


def test_signatures_docs_bases_decorators(tmp_path):
    write(tmp_path, "pkg/__init__.py", "")
    rel = write(tmp_path, "pkg/scan.py", '''"""Scan module.

Longer text."""
import numpy as np
from .core import Scan as Base

LIMIT: int = 5
SETTINGS = {"Points": "Int", "Valid Points": "Int", "Merge Results": "Boolean",
            "Initial Sample": "Path"}

def helper(a, /, b: int = 2, *args, c=None, **kw) -> float:
    """Help."""

async def fetch(*, url: str): ...

class MyScan(Base, metaclass=Meta):
    """A scan."""
    kind = "mcmc"

    def __init__(self, inputs, log=None):
        def nested(): pass

    @staticmethod
    def make(x): ...

    @property
    def size(self) -> int: ...

    class Inner:
        pass

try:
    from fast import impl
except ImportError:
    def impl(x): ...
''')
    info = extract_file(tmp_path, rel)
    assert info.module == "pkg.scan"
    assert info.doc.startswith("Scan module.")
    q = rows_by_qual(info)
    assert q["pkg.scan"].kind == "module"
    assert q["pkg.scan.helper"].signature == \
        "(a, /, b: int = 2, *args, c=None, **kw) -> float"
    assert q["pkg.scan.helper"].doc == "Help."
    assert q["pkg.scan.fetch"].signature == "async (*, url: str)"
    cls = q["pkg.scan.MyScan"]
    assert cls.kind == "class"
    assert cls.signature == "(inputs, log=None)"          # __init__ minus self
    assert cls.bases == ["Base", "metaclass=Meta"]
    assert cls.doc == "A scan."
    assert q["pkg.scan.MyScan.make"].decorators == ["staticmethod"]
    assert q["pkg.scan.MyScan.size"].signature == "(self) -> int"
    assert q["pkg.scan.MyScan.kind"].kind == "attribute"
    assert q["pkg.scan.MyScan.Inner"].parent == "pkg.scan.MyScan"
    assert "pkg.scan.MyScan.__init__.nested" not in q      # bodies not walked
    assert q["pkg.scan.LIMIT"].signature == ": int = 5"
    assert q["pkg.scan.impl"].kind == "function"          # found inside try/except
    # long literal values kept in full; short ones only in the signature
    assert q["pkg.scan.SETTINGS"].signature.endswith("...")
    assert "'Initial Sample': 'Path'" in q["pkg.scan.SETTINGS"].value
    assert q["pkg.scan.LIMIT"].value == ""
    # imports resolved (relative -> absolute)
    imps = {(n, t) for n, t, _ in info.imports}
    assert ("np", "numpy") in imps
    assert ("Base", "pkg.core.Scan") in imps
    assert ("impl", "fast.impl") in imps


def test_package_reexports_and_all(tmp_path):
    rel = write(tmp_path, "pkg/__init__.py",
                "from .core import Scan\nfrom . import tools\n"
                "from ..up import thing\n__all__ = ['Scan', 'tools']\n")
    info = extract_file(tmp_path, rel)
    assert info.module == "pkg"
    assert info.all_names == ["Scan", "tools"]
    imps = {(n, t) for n, t, _ in info.imports}
    assert ("Scan", "pkg.core.Scan") in imps
    assert ("tools", "pkg.tools") in imps
    assert ("thing", "up.thing") in imps
    assert "pkg.__all__" not in rows_by_qual(info)


def test_dataclass_signature(tmp_path):
    rel = write(tmp_path, "dc.py",
                "from dataclasses import dataclass\nfrom typing import ClassVar\n"
                "@dataclass(frozen=True)\nclass Point:\n"
                "    x: float\n    y: float = 0.0\n    n: ClassVar[int] = 0\n")
    q = rows_by_qual(extract_file(tmp_path, rel))
    assert q["dc.Point"].signature == "(x: float, y: float = 0.0)"
    assert q["dc.Point"].decorators == ["dataclass(frozen=True)"]


def test_unparseable_returns_none(tmp_path):
    rel = write(tmp_path, "py2.py", "print 'hello'\n")
    assert extract_file(tmp_path, rel) is None


def test_instance_attributes(tmp_path):
    rel = write(tmp_path, "c.py",
                "class C:\n"
                "    level = 1\n"
                "    def setup(self):\n"
                "        self.late = 3\n"
                "        self.a = 99\n"
                "    def __init__(self, x):\n"
                "        self.a = x\n"
                "        self.b: int = 2\n"
                "        self.c, self.d = 1, 2\n"
                "        self.level = 5\n"
                "        other.z = 0\n"
                "    @staticmethod\n"
                "    def s(obj):\n"
                "        obj.nope = 1\n")
    q = rows_by_qual(extract_file(tmp_path, rel))
    attrs = {r.name: r for r in q.values() if r.kind == "instance_attribute"}
    assert set(attrs) == {"a", "b", "c", "d", "late"}   # level is class-level
    assert attrs["a"].signature == " = x"               # __init__ wins
    assert attrs["a"].doc == "Set in __init__()."
    assert attrs["b"].signature == ": int = 2"
    assert attrs["late"].doc == "Set in setup()."


def test_key_uses(tmp_path):
    rel = write(tmp_path, "k.py",
                "import os\n"
                "def f(cfg, name):\n"
                "    a = cfg['Setup']['Cores']\n"
                "    b = cfg['Setup'].get('Resume', 'False')\n"
                "    if 'Seed' not in cfg['Setup']: pass\n"
                "    cfg['Codes'][name]['Run'] = 1\n"
                "    del cfg['Tmp']\n"
                "    home = os.environ.get('HOME')\n"
                "    x = cfg[cfg['Key']]\n"
                "    y = items[0]\n")
    uses = {(u.base, "/".join(u.keys), u.access, u.default)
            for u in extract_file(tmp_path, rel).keys}
    assert uses == {
        ("cfg", "Setup/Cores", "index", ""),
        ("cfg", "Setup/Resume", "get", "'False'"),
        ("cfg", "Setup/Seed", "in", ""),
        ("cfg", "Codes/*/Run", "set", ""),
        ("cfg", "Tmp", "del", ""),
        ("os.environ", "HOME", "get", ""),
        ("cfg", "Key", "index", ""),                    # inner chain in a slice
    }                                                   # items[0]: no str key
    assert {u.scope for u in extract_file(tmp_path, rel).keys} == {"k.f"}


def test_key_uses_local_alias(tmp_path):
    rel = write(tmp_path, "a.py",
                "def f(cfg):\n"
                "    s = cfg['Setup']\n"
                "    n = s['Cores']\n"
                "    r = s.get('Resume', 0)\n"
                "    s = other()\n"
                "    m = s['Gone']\n"
                "def g(s):\n"
                "    return s['Local']\n")
    uses = {(u.base, "/".join(u.keys), u.scope)
            for u in extract_file(tmp_path, rel).keys}
    assert ("cfg", "Setup/Cores", "a.f") in uses
    assert ("cfg", "Setup/Resume", "a.f") in uses
    assert ("s", "Gone", "a.f") in uses          # alias dropped on rebind
    assert ("s", "Local", "a.g") in uses         # aliases are function-local


def test_calls_collected_with_local_resolution(tmp_path):
    write(tmp_path, "pkg/__init__.py", "")
    rel = write(tmp_path, "pkg/m.py",
                "import numpy as np\n"
                "from .core import Scan, helper\n"
                "setup()\n"
                "def top():\n"
                "    def inner():\n"
                "        np.zeros(3)\n"
                "    helper(1)\n"
                "    local_fn()\n"
                "class S(Scan):\n"
                "    def run(self):\n"
                "        self.step()\n"
                "        self.RunManager.run_batch([])\n"
                "        super().run()\n"
                "        S(1)\n"
                "        f()()\n")
    calls = {(c.caller, c.callee, c.target)
             for c in extract_file(tmp_path, rel).calls}
    assert calls == {
        ("pkg.m", "setup", ""),
        ("pkg.m.top", "np.zeros", "numpy.zeros"),        # nested def -> top
        ("pkg.m.top", "helper", "pkg.core.helper"),
        ("pkg.m.top", "local_fn", ""),
        ("pkg.m.S.run", "self.step", "pkg.m.S.step"),
        ("pkg.m.S.run", "self.RunManager.run_batch", "pkg.m.S#RunManager.run_batch"),
        ("pkg.m.S.run", "super().run", ""),
        ("pkg.m.S.run", "S", "pkg.m.S"),
        ("pkg.m.S.run", "f", ""),                          # f()() outer: computed
    }


def test_staticmethod_first_arg_not_receiver(tmp_path):
    write(tmp_path, "pkg/__init__.py", "")
    rel = write(tmp_path, "pkg/m.py",
                "class C:\n"
                "    @staticmethod\n"
                "    def build(other):\n"
                "        other.save()\n")
    calls = {(c.caller, c.callee, c.target)
             for c in extract_file(tmp_path, rel).calls}
    assert calls == {("pkg.m.C.build", "other.save", "")}


def test_module_end_line_counts_lines(tmp_path):
    write(tmp_path, "pkg/__init__.py", "")
    trailing = extract_file(tmp_path, write(tmp_path, "pkg/m.py",
                                            "def f():\n    pass\n"))
    assert rows_by_qual(trailing)["pkg.m"].end_line == 2
    no_trailing = extract_file(tmp_path, write(tmp_path, "pkg/n.py", "x = 1"))
    assert rows_by_qual(no_trailing)["pkg.n"].end_line == 1
