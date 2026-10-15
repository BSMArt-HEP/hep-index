"""Python API extraction via the stdlib `ast` module (CONTRACT.md §pyast).

  extract_file(root, rel) -> PyFileInfo | None   (None = unparseable, keep ctags)

Static only: nothing is imported or executed. Captures the *usable surface* of
a module — qualified names, signatures with defaults, docstrings, base classes,
decorators, `__all__`, imports (for re-export resolution) and `self.x`
instance attributes. Nested defs are not indexed as API.

Calls made in each function/method are recorded (PyCall) with a best-effort
resolved target, giving a static call graph (callers/callees).

Separately, every chain of string-key lookups (`cfg["A"]["B"]`,
`cfg["A"].get("B", dflt)`, `"B" in cfg["A"]`, writes) is recorded as a
PyKeyUse — for config-driven codes, the valid input keys and their defaults.
"""
from __future__ import annotations

import ast
import json
import warnings
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

_MAX_DEFAULT = 60     # truncate long default / value reprs in signatures
_MAX_DOC = 8000       # cap stored docstrings
_MAX_VALUE = 4000     # cap stored literal values (settings dicts, option tables)


@dataclass
class PyApiRow:
    qualname: str          # dotted, module-qualified: pkg.mod.Class.method
    name: str
    kind: str              # module | class | function | method | variable |
                           # attribute | instance_attribute
    path: str              # relative posix
    line: int
    end_line: int
    parent: str            # qualname of enclosing module/class
    signature: str         # "(a, b=1) -> int"; class: __init__ minus self; var: ": T = v"
    doc: str
    bases: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    value: str = ""        # full source of a literal variable value (untruncated)

    def as_tuple(self) -> tuple:
        return (self.qualname, self.name, self.kind, self.path, self.line,
                self.end_line, self.parent, self.signature, self.doc,
                json.dumps(self.bases), json.dumps(self.decorators), self.value)


@dataclass
class PyKeyUse:
    scope: str             # qualname of enclosing function/class/module
    base: str              # receiver as written: "inputs", "self.inputs", "os.environ"
    keys: list[str]        # constant keys; "*" for a non-constant subscript
    access: str            # index | get | in | set | del
    default: str           # .get() default (source), else ""
    path: str
    line: int

    def as_tuple(self) -> tuple:
        norm = self.base.removeprefix("self.").removeprefix("cls.")
        return (norm, self.base, json.dumps(self.keys), self.access,
                self.default, self.scope, self.path, self.line)


@dataclass
class PyCall:
    caller: str            # qualname of the enclosing indexed function/method/module
    callee: str            # call target as written: "self.RunManager.run_batch"
    target: str            # best-effort absolute dotted target ("" = unknown);
                           # file-local here, canonicalised across files by indexer;
                           # "Cls#attr.meth" = self.attr.meth(), typed by the indexer
    path: str
    line: int

    def as_tuple(self) -> tuple:
        name = self.callee.rsplit(".", 1)[-1]
        return (self.caller, self.callee, name, self.target, self.path, self.line)


@dataclass
class PyFileInfo:
    module: str
    path: str
    doc: str
    all_names: list[str] | None                       # __all__ if statically given
    rows: list[PyApiRow]
    imports: list[tuple[str, str, int]]               # (local name, target dotted, line)
    keys: list[PyKeyUse] = field(default_factory=list)
    calls: list[PyCall] = field(default_factory=list)


def module_name(root: Path, rel: str) -> str:
    """Dotted module name: climb while parent dirs are packages (__init__.py)."""
    p = PurePosixPath(rel)
    parts = [] if p.stem == "__init__" else [p.stem]
    d = PurePosixPath(*p.parts[:-1]) if len(p.parts) > 1 else None
    while d is not None and (root / d / "__init__.py").is_file():
        parts.insert(0, d.name)
        d = PurePosixPath(*d.parts[:-1]) if len(d.parts) > 1 else None
    return ".".join(parts) or p.stem


def _short(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        s = ast.unparse(node)
    except Exception:  # pragma: no cover - unparse is total on parsed trees
        return "..."
    return s if len(s) <= _MAX_DEFAULT else s[:_MAX_DEFAULT - 3] + "..."


def _format_args(a: ast.arguments, drop_first: bool = False) -> str:
    out: list[str] = []
    pos = list(a.posonlyargs) + list(a.args)
    defaults = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
    for i, (arg, dflt) in enumerate(zip(pos, defaults)):
        s = arg.arg + (f": {_short(arg.annotation)}" if arg.annotation else "")
        if dflt is not None:
            s += (" = " if arg.annotation else "=") + _short(dflt)
        out.append(s)
        if a.posonlyargs and i == len(a.posonlyargs) - 1:
            out.append("/")
    if a.vararg:
        out.append("*" + a.vararg.arg +
                   (f": {_short(a.vararg.annotation)}" if a.vararg.annotation else ""))
    elif a.kwonlyargs:
        out.append("*")
    for arg, dflt in zip(a.kwonlyargs, a.kw_defaults):
        s = arg.arg + (f": {_short(arg.annotation)}" if arg.annotation else "")
        if dflt is not None:
            s += (" = " if arg.annotation else "=") + _short(dflt)
        out.append(s)
    if a.kwarg:
        out.append("**" + a.kwarg.arg +
                   (f": {_short(a.kwarg.annotation)}" if a.kwarg.annotation else ""))
    if drop_first and out and out[0] not in ("/", "*") and not out[0].startswith("*"):
        out = out[1:]
        if out and out[0] == "/":
            out = out[1:]
    return "(" + ", ".join(out) + ")"


def _func_sig(fn: ast.FunctionDef | ast.AsyncFunctionDef, drop_first=False) -> str:
    sig = _format_args(fn.args, drop_first)
    if fn.returns is not None:
        sig += f" -> {_short(fn.returns)}"
    return ("async " if isinstance(fn, ast.AsyncFunctionDef) else "") + sig


def _doc(node) -> str:
    d = ast.get_docstring(node, clean=True) or ""
    return d[:_MAX_DOC]


def _decorators(node) -> list[str]:
    return [_short(d) for d in node.decorator_list]


def _flatten(body: list[ast.stmt]):
    """Yield statements, descending into module/class-level if/try/with blocks
    (TYPE_CHECKING guards, try-import fallbacks) but not into defs."""
    for st in body:
        if isinstance(st, ast.If):
            yield from _flatten(st.body)
            yield from _flatten(st.orelse)
        elif isinstance(st, ast.Try) or type(st).__name__ == "TryStar":
            yield from _flatten(st.body)
            for h in st.handlers:
                yield from _flatten(h.body)
            yield from _flatten(st.orelse)
            yield from _flatten(st.finalbody)
        elif isinstance(st, (ast.With, ast.AsyncWith)):
            yield from _flatten(st.body)
        else:
            yield st


def _literal_value(node: ast.AST | None) -> str:
    """Full source of a literal value too long for the signature, else ""."""
    if node is None:
        return ""
    try:
        ast.literal_eval(node)
        s = ast.unparse(node)
    except Exception:
        return ""
    return s if _MAX_DEFAULT < len(s) <= _MAX_VALUE else ""


def _assign_targets(st) -> list[tuple[str, str, str]]:
    """(name, signature, literal value) for simple Name targets of an assignment."""
    if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
        sig = f": {_short(st.annotation)}"
        if st.value is not None:
            sig += f" = {_short(st.value)}"
        return [(st.target.id, sig, _literal_value(st.value))]
    if isinstance(st, ast.Assign):
        return [(t.id, f" = {_short(st.value)}", _literal_value(st.value))
                for t in st.targets if isinstance(t, ast.Name)]
    return []


def _resolve_relative(module: str, is_pkg: bool, level: int, target: str | None) -> str:
    if level == 0:
        return target or ""
    base = module.split(".") if is_pkg else module.split(".")[:-1]
    if level > 1:
        base = base[:len(base) - (level - 1)] if level - 1 <= len(base) else []
    return ".".join(base + ([target] if target else []))


def _dataclass_sig(cls: ast.ClassDef) -> str | None:
    if not any("dataclass" in _short(d) for d in cls.decorator_list):
        return None
    fields = []
    for st in cls.body:
        if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
            if "ClassVar" in _short(st.annotation):
                continue
            s = f"{st.target.id}: {_short(st.annotation)}"
            if st.value is not None:
                s += f" = {_short(st.value)}"
            fields.append(s)
    return "(" + ", ".join(fields) + ")"


def _self_assignments(fn) -> list[tuple[str, str, int]]:
    """(attr, signature, line) for `self.attr = ...` in a method, first wins."""
    a = fn.args
    pos = list(a.posonlyargs) + list(a.args)
    if not pos or any(_short(d) == "staticmethod" for d in fn.decorator_list):
        return []
    me = pos[0].arg
    out: dict[str, tuple[str, str, int]] = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            pairs = [(t, f" = {_short(node.value)}") for t in node.targets]
        elif isinstance(node, ast.AnnAssign):
            pairs = [(node.target, f": {_short(node.annotation)}" +
                      (f" = {_short(node.value)}" if node.value else ""))]
        elif isinstance(node, ast.AugAssign):
            pairs = [(node.target, "")]  # self.x += ...: exists, no value
        else:
            continue
        flat = []
        for t, sig in pairs:  # unpack `self.a, self.b = ...`
            if isinstance(t, (ast.Tuple, ast.List)):
                flat.extend((e, " = ...") for e in t.elts)
            else:
                flat.append((t, sig))
        for t, sig in flat:
            if (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                    and t.value.id == me and t.attr not in out):
                out[t.attr] = (t.attr, sig, node.lineno)
    return sorted(out.values(), key=lambda x: x[2])


def _walk_class(cls: ast.ClassDef, qual: str, parent: str, rel: str,
                rows: list[PyApiRow]):
    init_sig = None
    body_rows: list[PyApiRow] = []
    for st in _flatten(cls.body):
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decos = _decorators(st)
            static = any(d in ("staticmethod",) for d in decos)
            body_rows.append(PyApiRow(
                qualname=f"{qual}.{st.name}", name=st.name, kind="method",
                path=rel, line=st.lineno, end_line=st.end_lineno or st.lineno,
                parent=qual, signature=_func_sig(st), doc=_doc(st),
                decorators=decos))
            if st.name == "__init__":
                init_sig = _func_sig(st, drop_first=not static)
        elif isinstance(st, ast.ClassDef):
            _walk_class(st, f"{qual}.{st.name}", qual, rel, body_rows)
        else:
            for name, sig, value in _assign_targets(st):
                body_rows.append(PyApiRow(
                    qualname=f"{qual}.{name}", name=name, kind="attribute",
                    path=rel, line=st.lineno, end_line=st.end_lineno or st.lineno,
                    parent=qual, signature=sig, doc="", value=value))
    known = {r.name for r in body_rows if r.parent == qual}
    methods = [st for st in _flatten(cls.body)
               if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef))]
    methods.sort(key=lambda m: m.name != "__init__")  # __init__ wins, then order
    for m in methods:
        for name, sig, line in _self_assignments(m):
            if name in known:
                continue
            known.add(name)
            body_rows.append(PyApiRow(
                qualname=f"{qual}.{name}", name=name, kind="instance_attribute",
                path=rel, line=line, end_line=line, parent=qual, signature=sig,
                doc=f"Set in {m.name}()."))
    if init_sig is not None:
        init_sig = init_sig.split(" -> ")[0]  # __init__ returns None
    sig = init_sig or _dataclass_sig(cls) or ""
    rows.append(PyApiRow(
        qualname=qual, name=cls.name, kind="class", path=rel, line=cls.lineno,
        end_line=cls.end_lineno or cls.lineno, parent=parent, signature=sig,
        doc=_doc(cls), bases=[_short(b) for b in cls.bases] +
        [f"{k.arg}={_short(k.value)}" for k in cls.keywords if k.arg],
        decorators=_decorators(cls)))
    rows.extend(body_rows)


def _dotted(node) -> str | None:
    """`a`, `a.b.c` -> dotted string; anything else (calls, subscripts) -> None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.insert(0, node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return ".".join([node.id, *parts])
    return None


def _str_const(node) -> str | None:
    return node.value if isinstance(node, ast.Constant) and \
        isinstance(node.value, str) else None


def _is_get(node) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get" and 1 <= len(node.args) <= 2
            and not node.keywords)


class _KeyCollector(ast.NodeVisitor):
    """Record maximal string-key lookup chains with their enclosing scope."""

    def __init__(self, module: str, rel: str):
        self.scope = [module]
        self.aliases: list[dict[str, tuple[str, list[str]]]] = [{}]
        self.rel = rel
        self.uses: list[PyKeyUse] = []

    def _scoped(self, node):
        self.scope.append(f"{self.scope[-1]}.{node.name}")
        self.aliases.append({})
        self.generic_visit(node)
        self.aliases.pop()
        self.scope.pop()

    def visit_Assign(self, node):
        """`s = cfg["Setup"]` makes later `s["Cores"]` report as cfg/Setup/Cores
        (function-local, flow-insensitive after the assignment)."""
        self.visit(node.value)
        for t in node.targets:
            self.visit(t)
        res = self._chain(node.value)
        for t in node.targets:
            if isinstance(t, ast.Name):
                if res is not None:
                    base, keys = self._unalias(res[0], res[1])
                    self.aliases[-1][t.id] = (base, keys)
                else:
                    self.aliases[-1].pop(t.id, None)

    def _unalias(self, base: str, keys: list[str]) -> tuple[str, list[str]]:
        head, _, rest = base.partition(".")
        if not rest and head in self.aliases[-1]:
            abase, akeys = self.aliases[-1][head]
            return abase, akeys + keys
        return base, keys

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scoped

    def _chain(self, node):
        """-> (base, keys, default, spine_nodes, side_nodes) or None."""
        keys, default, side = [], "", []
        cur = node
        if _is_get(cur):
            k = _str_const(cur.args[0])
            keys.insert(0, k if k is not None else "*")
            if len(cur.args) == 2:
                default = _short(cur.args[1])
            side.extend(cur.args)
            cur = cur.func.value
        while True:
            if isinstance(cur, ast.Subscript):
                k = _str_const(cur.slice)
                keys.insert(0, k if k is not None else "*")
                side.append(cur.slice)
                cur = cur.value
            elif _is_get(cur):
                k = _str_const(cur.args[0])
                keys.insert(0, k if k is not None else "*")
                side.extend(cur.args)
                cur = cur.func.value
            else:
                break
        base = _dotted(cur)
        if base is None or not any(k != "*" for k in keys):
            return None
        return base, keys, default, side

    def _record(self, node, access, extra_key=None) -> bool:
        res = self._chain(node)
        if res is None:
            if extra_key is None:
                return False
            base = _dotted(node)  # `"k" in cfg` with a bare receiver
            if base is None:
                return False
            keys, default, side = [], "", []
        else:
            base, keys, default, side = res
        if extra_key is not None:
            keys = keys + [extra_key]
        base, keys = self._unalias(base, keys)
        self.uses.append(PyKeyUse(self.scope[-1], base, keys, access, default,
                                  self.rel, node.lineno))
        for s in side:
            self.visit(s)
        return True

    def visit_Subscript(self, node):
        ctx = {ast.Store: "set", ast.Del: "del"}.get(type(node.ctx), "index")
        if not self._record(node, ctx):
            self.generic_visit(node)

    def visit_Call(self, node):
        if not (_is_get(node) and self._record(node, "get")):
            self.generic_visit(node)

    def visit_Compare(self, node):
        k = _str_const(node.left)
        if (k is not None and len(node.ops) == 1
                and isinstance(node.ops[0], (ast.In, ast.NotIn))
                and self._record(node.comparators[0], "in", extra_key=k)):
            return
        self.generic_visit(node)


def _callee_text(func) -> str | None:
    """`f`, `a.b.f`, `self.x.f`, `super().f`; None for computed callees."""
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Call) \
            and isinstance(func.value.func, ast.Name) \
            and func.value.func.id == "super":
        return f"super().{func.attr}"
    return _dotted(func)


def _walk_no_defs(node):
    """ast.walk that does not enter def/class bodies (module-level code only)."""
    _defs = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    todo = [] if isinstance(node, _defs) else [node]
    while todo:
        n = todo.pop()
        yield n
        todo.extend(c for c in ast.iter_child_nodes(n)
                    if not isinstance(c, _defs))


def _collect_calls(fn, caller: str, cls_qual: str | None, local: dict[str, str],
                   rel: str, out: list[PyCall]):
    """Every call in fn's body (nested defs/lambdas attributed to fn)."""
    pos = list(fn.args.posonlyargs) + list(fn.args.args) \
        if hasattr(fn, "args") else []
    me = pos[0].arg if (cls_qual and pos) else None
    seen: set[tuple[str, int]] = set()
    body = fn.body if isinstance(fn.body, list) else [fn.body]
    walk = _walk_no_defs if isinstance(fn, ast.Module) else ast.walk
    for st in body:
        for node in walk(st):
            if not isinstance(node, ast.Call):
                continue
            text = _callee_text(node.func)
            if text is None or text == "super" or (text, node.lineno) in seen:
                continue
            seen.add((text, node.lineno))
            head, _, rest = text.partition(".")
            if text.startswith("super()."):
                target = ""
            elif me and head == me and rest and "." not in rest:
                target = f"{cls_qual}.{rest}"   # self.method(): this class (or a base)
            elif me and head == me and rest.count(".") == 1:
                target = f"{cls_qual}#{rest}"   # self.attr.method(): via attr's type
            elif head in local:
                target = local[head] + (f".{rest}" if rest else "")
            else:
                target = ""
            out.append(PyCall(caller, text, target, rel, node.lineno))


def extract_file(root: Path, rel: str) -> PyFileInfo | None:
    """Parse one .py file; None on syntax error / unreadable (caller keeps ctags)."""
    try:
        src = (root / rel).read_bytes()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # invalid escape sequences etc.
            tree = ast.parse(src, filename=rel)
    except (OSError, SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    mod = module_name(root, rel)
    is_pkg = PurePosixPath(rel).stem == "__init__"
    rows: list[PyApiRow] = []
    imports: list[tuple[str, str, int]] = []
    all_names: list[str] | None = None

    for st in _flatten(tree.body):
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            rows.append(PyApiRow(
                qualname=f"{mod}.{st.name}", name=st.name, kind="function",
                path=rel, line=st.lineno, end_line=st.end_lineno or st.lineno,
                parent=mod, signature=_func_sig(st), doc=_doc(st),
                decorators=_decorators(st)))
        elif isinstance(st, ast.ClassDef):
            _walk_class(st, f"{mod}.{st.name}", mod, rel, rows)
        elif isinstance(st, ast.Import):
            for a in st.names:
                local = a.asname or a.name.split(".")[0]
                imports.append((local, a.name if a.asname else local, st.lineno))
        elif isinstance(st, ast.ImportFrom):
            src_mod = _resolve_relative(mod, is_pkg, st.level, st.module)
            for a in st.names:
                if a.name == "*":
                    imports.append(("*", src_mod, st.lineno))
                else:
                    imports.append((a.asname or a.name,
                                    f"{src_mod}.{a.name}" if src_mod else a.name,
                                    st.lineno))
        else:
            for name, sig, value in _assign_targets(st):
                if name == "__all__":
                    val = st.value
                    if isinstance(val, (ast.List, ast.Tuple)):
                        all_names = [e.value for e in val.elts
                                     if isinstance(e, ast.Constant)
                                     and isinstance(e.value, str)]
                    continue
                rows.append(PyApiRow(
                    qualname=f"{mod}.{name}", name=name, kind="variable",
                    path=rel, line=st.lineno, end_line=st.end_lineno or st.lineno,
                    parent=mod, signature=sig, doc="", value=value))

    n_lines = src.count(b"\n") + 1
    rows.insert(0, PyApiRow(
        qualname=mod, name=mod.rsplit(".", 1)[-1], kind="module", path=rel,
        line=1, end_line=n_lines, parent=mod.rsplit(".", 1)[0] if "." in mod else "",
        signature="", doc=_doc(tree)))
    # call graph: local names -> absolute targets (imports + own definitions)
    local = {n: t for n, t, _ in imports if n != "*"}
    for r in rows:
        if r.parent == mod and r.kind in ("function", "class"):
            local[r.name] = r.qualname
    calls: list[PyCall] = []
    _collect_calls(ast.Module(body=tree.body, type_ignores=[]), mod, None,
                   local, rel, calls)

    def walk_defs(body, parent: str, cls_qual: str | None):
        for st in _flatten(body):
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _collect_calls(st, f"{parent}.{st.name}", cls_qual, local, rel,
                               calls)
            elif isinstance(st, ast.ClassDef):
                q = f"{parent}.{st.name}"
                walk_defs(st.body, q, q)
    walk_defs(tree.body, mod, None)

    kc = _KeyCollector(mod, rel)
    try:
        kc.visit(tree)
    except RecursionError:
        kc.uses = []
    return PyFileInfo(module=mod, path=rel, doc=_doc(tree), all_names=all_names,
                      rows=rows, imports=imports, keys=kc.uses, calls=calls)
