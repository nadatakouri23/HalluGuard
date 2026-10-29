"""
Python AST Parser module using Tree-sitter.

Extracts imports, function calls, method calls, class definitions,
decorators and async functions from Python source code, together with
the information needed by the scorer to avoid false positives:

* **positions** – every import / call carries ``{name, line, col}``
  (1-based line, 0-based character column);
* **scope** – ``defined_names`` (functions, classes, parameters, assigned
  names, loop / ``with`` / ``except`` targets, imported bindings);
* **aliases** – ``local name -> qualified target`` (``np -> numpy``,
  ``OD -> collections.OrderedDict``);
* **relative imports** – kept apart from ``imports`` because they refer to
  the project itself, never to a registry package.

The scope analysis is file-level (flat): a name defined in *any* scope of the
file counts as known.  That trades a few false negatives for far fewer false
positives than treating every non-builtin call as suspicious.
"""
from __future__ import annotations

from typing import Any

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from core.parser._common import Source, make_location

# ── Language singleton ──────────────────────────────────────────────
PY_LANGUAGE = Language(tree_sitter_python.language())

_PATTERN_CONTAINERS = frozenset({
    "pattern_list", "tuple_pattern", "list_pattern", "tuple", "list",
    "list_splat_pattern", "dictionary_splat_pattern", "parenthesized_expression",
    "as_pattern_target",
})


def _add_targets(node: Node | None, src: Source, names: set[str]) -> None:
    """Collect the names *bound* by an assignment-like target."""
    if node is None:
        return
    if node.type == "identifier":
        names.add(src.text(node))
    elif node.type in _PATTERN_CONTAINERS:
        for child in node.children:
            _add_targets(child, src, names)
    # attribute / subscript targets (``self.x = 1``) bind nothing new.


def _add_parameters(node: Node, src: Source, names: set[str]) -> None:
    """Collect parameter names from a ``parameters`` / ``lambda_parameters``."""
    for child in node.children:
        if child.type == "identifier":
            names.add(src.text(child))
        elif child.type in ("default_parameter", "typed_default_parameter"):
            name = child.child_by_field_name("name")
            if name is not None:
                _add_targets(name, src, names)
        elif child.type == "typed_parameter":
            for sub in child.children:
                if sub.type in ("identifier", "list_splat_pattern",
                                "dictionary_splat_pattern"):
                    _add_targets(sub, src, names)
                    break
        elif child.type in ("list_splat_pattern", "dictionary_splat_pattern"):
            _add_targets(child, src, names)


def _dotted(src: Source, node: Node) -> str | None:
    """Return ``a.b.c`` if *node* is a pure dotted name, else ``None``."""
    if node.type == "identifier":
        return src.text(node)
    if node.type == "attribute":
        obj = node.child_by_field_name("object")
        attr = node.child_by_field_name("attribute")
        if obj is None or attr is None:
            return None
        head = _dotted(src, obj)
        return None if head is None else f"{head}.{src.text(attr)}"
    return None


def extract(code: str, language: str = "python") -> dict[str, Any]:
    """
    Parse a Python code snippet and extract structured token information.

    Args:
        code: The Python source code string.
        language: Must be ``"python"`` (validated at call site).

    Returns:
        A dictionary with the following keys:

        - **imports** – top-level module names of absolute imports.
        - **from_imports** – ``{"module", "names", "line", "relative"}`` dicts.
        - **function_calls** – bare function call identifiers.
        - **method_calls** – attribute-style calls (e.g. ``requests.get``).
        - **decorators** – decorator names.
        - **async_functions** – async function names.
        - **classes** – class names.
        - **import_locations / function_call_locations / method_call_locations**
          – every occurrence as ``{"name", "line", "col"}``.
        - **relative_imports** – ``{"module", "names", "line"}`` for ``from .x``.
        - **star_imports** – modules imported with ``*``.
        - **defined_names** – sorted names bound anywhere in the file.
        - **aliases** – local name → qualified target.
        - **assignments** – variable → callee texts of ``var = callee(...)``.
    """
    if language.lower() != "python":
        raise ValueError(
            f"Language '{language}' is not supported by the Python parser."
        )

    src = Source(code)
    tree = Parser(PY_LANGUAGE).parse(src.raw)

    imports: list[str] = []
    from_imports: list[dict[str, Any]] = []
    function_calls: list[str] = []
    method_calls: list[str] = []
    decorators: list[str] = []
    async_functions: list[str] = []
    classes: list[str] = []
    import_locations: list[dict[str, Any]] = []
    function_call_locations: list[dict[str, Any]] = []
    method_call_locations: list[dict[str, Any]] = []
    relative_imports: list[dict[str, Any]] = []
    star_imports: list[str] = []
    defined: set[str] = set()
    aliases: dict[str, str] = {}
    assignments: dict[str, list[str]] = {}

    def _unique_add(lst: list[str], value: str) -> None:
        if value and value not in lst:
            lst.append(value)

    def _loc(name: str, node: Node) -> dict[str, Any]:
        line, col = src.location(node)
        return make_location(name, line, col)

    def _handle_import(node: Node) -> None:
        for child in node.children_by_field_name("name"):
            if child.type == "aliased_import":
                target = child.child_by_field_name("name")
                alias = child.child_by_field_name("alias")
                if target is None:
                    continue
                full = src.text(target)
                root = full.split(".")[0]
                _unique_add(imports, root)
                import_locations.append(_loc(root, target))
                if alias is not None:
                    bound = src.text(alias)
                    aliases[bound] = full
                    defined.add(bound)
            else:
                full = src.text(child)
                root = full.split(".")[0]
                _unique_add(imports, root)
                import_locations.append(_loc(root, child))
                aliases.setdefault(root, root)
                defined.add(root)

    def _handle_from_import(node: Node) -> None:
        module_node = node.child_by_field_name("module_name")
        if module_node is None:
            return
        module = src.text(module_node)
        relative = module_node.type == "relative_import"
        names: list[str] = []
        for child in node.children_by_field_name("name"):
            if child.type == "aliased_import":
                target = child.child_by_field_name("name")
                alias = child.child_by_field_name("alias")
                if target is None:
                    continue
                original = src.text(target)
                names.append(original)
                bound = src.text(alias) if alias is not None else original
            else:
                original = src.text(child)
                names.append(original)
                bound = original
            defined.add(bound)
            if not relative:
                aliases[bound] = f"{module}.{original}"
        if any(c.type == "wildcard_import" for c in node.children):
            star_imports.append(module)
        line, _ = src.location(node)
        entry = {"module": module, "names": names, "line": line,
                 "relative": relative}
        from_imports.append(entry)
        if relative:
            relative_imports.append(
                {"module": module, "names": names, "line": line}
            )
        else:
            root = module.split(".")[0]
            _unique_add(imports, root)
            import_locations.append(_loc(root, module_node))

    def _handle_call(node: Node) -> None:
        func = node.child_by_field_name("function")
        if func is None:
            return
        if func.type == "identifier":
            name = src.text(func)
            _unique_add(function_calls, name)
            function_call_locations.append(_loc(name, func))
        elif func.type == "attribute":
            name = src.text(func)
            _unique_add(method_calls, name)
            method_call_locations.append(_loc(name, func))

    def _handle_decorator(node: Node) -> None:
        for child in node.children:
            if child.type in ("identifier", "attribute"):
                decorators.append(src.text(child))
            elif child.type == "call":
                inner = child.child_by_field_name("function")
                if inner is not None:
                    decorators.append(src.text(inner))

    def _handle_assignment(node: Node) -> None:
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        _add_targets(left, src, defined)
        if (left is not None and left.type == "identifier"
                and right is not None and right.type == "call"):
            func = right.child_by_field_name("function")
            callee = _dotted(src, func) if func is not None else None
            if callee:
                assignments.setdefault(src.text(left), []).append(callee)

    def traverse(node: Node) -> None:
        t = node.type
        if t == "import_statement":
            _handle_import(node)
        elif t == "import_from_statement":
            _handle_from_import(node)
        elif t == "call":
            _handle_call(node)
        elif t == "decorator":
            _handle_decorator(node)
        elif t == "function_definition":
            name = node.child_by_field_name("name")
            if name is not None:
                defined.add(src.text(name))
                if any(c.type == "async" for c in node.children):
                    async_functions.append(src.text(name))
            params = node.child_by_field_name("parameters")
            if params is not None:
                _add_parameters(params, src, defined)
        elif t == "class_definition":
            name = node.child_by_field_name("name")
            if name is not None:
                classes.append(src.text(name))
                defined.add(src.text(name))
        elif t == "lambda":
            params = node.child_by_field_name("parameters")
            if params is not None:
                _add_parameters(params, src, defined)
        elif t == "assignment":
            _handle_assignment(node)
        elif t == "augmented_assignment":
            _add_targets(node.child_by_field_name("left"), src, defined)
        elif t in ("for_statement", "for_in_clause"):
            _add_targets(node.child_by_field_name("left"), src, defined)
        elif t == "as_pattern":
            _add_targets(node.child_by_field_name("alias"), src, defined)
        elif t == "named_expression":
            _add_targets(node.child_by_field_name("name"), src, defined)
        elif t in ("global_statement", "nonlocal_statement"):
            for child in node.children:
                _add_targets(child, src, defined)

        for child in node.children:
            traverse(child)

    traverse(tree.root_node)

    return {
        "imports": imports,
        "from_imports": from_imports,
        "function_calls": function_calls,
        "method_calls": method_calls,
        "decorators": decorators,
        "async_functions": async_functions,
        "classes": classes,
        "import_locations": import_locations,
        "function_call_locations": function_call_locations,
        "method_call_locations": method_call_locations,
        "relative_imports": relative_imports,
        "star_imports": star_imports,
        "defined_names": sorted(defined),
        "aliases": aliases,
        "assignments": assignments,
    }
