"""
JavaScript / TypeScript AST Parser module using Tree-sitter.

Extracts ES6 imports, CommonJS ``require()`` calls, dynamic ``import()``,
function calls and method calls (including ``fetch`` / ``axios`` patterns),
with ``{name, line, col}`` positions and the file-level scope information
(``defined_names``, ``aliases``) needed to avoid false positives.
"""
from __future__ import annotations

from typing import Any

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from core.parser._common import Source, make_location

# ── Language singletons ─────────────────────────────────────────────
JS_LANGUAGE = Language(tree_sitter_javascript.language())
TS_LANGUAGE = Language(tree_sitter_typescript.language_typescript())

_BINDING_CONTAINERS = frozenset({
    "object_pattern", "array_pattern", "rest_pattern", "formal_parameters",
    "required_parameter", "optional_parameter",
})


def _get_language(language: str) -> Language:
    """Resolve language string to a tree-sitter Language object."""
    lang = language.lower()
    if lang in ("javascript", "js"):
        return JS_LANGUAGE
    elif lang in ("typescript", "ts"):
        return TS_LANGUAGE
    else:
        raise ValueError(
            f"Language '{language}' is not supported by the JS/TS parser. "
            "Use 'javascript' or 'typescript'."
        )


def _add_bindings(node: Node | None, src: Source, names: set[str]) -> None:
    """Collect the names bound by a declaration / parameter pattern."""
    if node is None:
        return
    t = node.type
    if t in ("identifier", "shorthand_property_identifier_pattern"):
        names.add(src.text(node))
    elif t in ("assignment_pattern", "object_assignment_pattern"):
        _add_bindings(node.child_by_field_name("left"), src, names)
    elif t == "pair_pattern":
        _add_bindings(node.child_by_field_name("value"), src, names)
    elif t in ("required_parameter", "optional_parameter"):
        _add_bindings(node.child_by_field_name("pattern"), src, names)
    elif t in _BINDING_CONTAINERS:
        for child in node.children:
            _add_bindings(child, src, names)


def extract(code: str, language: str = "javascript") -> dict[str, Any]:
    """
    Parse a JavaScript or TypeScript snippet and extract structured tokens.

    Args:
        code: The JS/TS source code string.
        language: ``"javascript"`` / ``"js"`` or ``"typescript"`` / ``"ts"``.

    Returns:
        A dictionary with the following keys:

        - **imports** – module specifiers from ES6 imports / ``import()``.
        - **require_calls** – module specifiers from ``require()``.
        - **function_calls** – bare function call identifiers.
        - **method_calls** – attribute-style calls (e.g. ``axios.get``).
        - **fetch_calls** – URLs or expressions passed to ``fetch()``.
        - **import_locations / function_call_locations / method_call_locations**
          – every occurrence as ``{"name", "line", "col"}`` (import locations
          cover both ``imports`` and ``require_calls``).
        - **defined_names** – sorted names bound anywhere in the file.
        - **aliases** – local binding → module specifier
          (``axios -> axios`` for ``const axios = require('axios')``).
    """
    lang_obj = _get_language(language)
    src = Source(code)
    tree = Parser(lang_obj).parse(src.raw)

    imports: list[str] = []
    require_calls: list[str] = []
    function_calls: list[str] = []
    method_calls: list[str] = []
    fetch_calls: list[str] = []
    import_locations: list[dict[str, Any]] = []
    function_call_locations: list[dict[str, Any]] = []
    method_call_locations: list[dict[str, Any]] = []
    defined: set[str] = set()
    aliases: dict[str, str] = {}

    def _unique_add(lst: list[str], value: str) -> None:
        if value and value not in lst:
            lst.append(value)

    def _loc(name: str, node: Node) -> dict[str, Any]:
        line, col = src.location(node)
        return make_location(name, line, col)

    def _string_value(node: Node) -> str:
        return src.text(node).strip("'\"`")

    def _handle_import(node: Node) -> None:
        source = node.child_by_field_name("source")
        if source is None:
            return
        spec = _string_value(source)
        _unique_add(imports, spec)
        import_locations.append(_loc(spec, source))
        for clause in node.children:
            if clause.type != "import_clause":
                continue
            for part in clause.children:
                if part.type == "identifier":
                    defined.add(src.text(part))
                    aliases[src.text(part)] = spec
                elif part.type == "namespace_import":
                    for ident in part.children:
                        if ident.type == "identifier":
                            defined.add(src.text(ident))
                            aliases[src.text(ident)] = spec
                elif part.type == "named_imports":
                    for item in part.children:
                        if item.type != "import_specifier":
                            continue
                        alias = item.child_by_field_name("alias")
                        name = item.child_by_field_name("name")
                        bound = alias if alias is not None else name
                        if bound is not None:
                            defined.add(src.text(bound))

    def _handle_declarator(node: Node) -> None:
        name = node.child_by_field_name("name")
        _add_bindings(name, src, defined)
        value = node.child_by_field_name("value")
        if (name is not None and name.type == "identifier"
                and value is not None and value.type == "call_expression"):
            func = value.child_by_field_name("function")
            args = value.child_by_field_name("arguments")
            if func is not None and src.text(func) == "require" and args:
                for arg in args.children:
                    if arg.type == "string":
                        aliases[src.text(name)] = _string_value(arg)
                        break

    def _handle_call(node: Node) -> None:
        func = node.child_by_field_name("function")
        if func is None:
            return
        func_text = src.text(func)
        args = node.child_by_field_name("arguments")

        if func_text == "require" or func.type == "import":
            if args:
                for arg in args.children:
                    if arg.type == "string":
                        spec = _string_value(arg)
                        target = require_calls if func_text == "require" else imports
                        _unique_add(target, spec)
                        import_locations.append(_loc(spec, arg))
                        break
        elif func_text == "fetch":
            _unique_add(function_calls, "fetch")
            function_call_locations.append(_loc("fetch", func))
            if args:
                for arg in args.children:
                    if arg.type in ("string", "template_string"):
                        fetch_calls.append(src.text(arg).strip("'\"`"))
                        break
                    elif arg.type == "identifier":
                        fetch_calls.append(src.text(arg))
                        break
        elif func.type == "identifier":
            _unique_add(function_calls, func_text)
            function_call_locations.append(_loc(func_text, func))
        elif func.type == "member_expression":
            _unique_add(method_calls, func_text)
            method_call_locations.append(_loc(func_text, func))

    def traverse(node: Node) -> None:
        t = node.type
        if t == "import_statement":
            _handle_import(node)
        elif t == "call_expression":
            _handle_call(node)
        elif t == "variable_declarator":
            _handle_declarator(node)
        elif t in ("function_declaration", "generator_function_declaration",
                   "class_declaration", "function_expression", "class"):
            name = node.child_by_field_name("name")
            if name is not None:
                defined.add(src.text(name))
        elif t == "catch_clause":
            _add_bindings(node.child_by_field_name("parameter"), src, defined)
        elif t == "for_in_statement":
            _add_bindings(node.child_by_field_name("left"), src, defined)

        if t in ("function_declaration", "generator_function_declaration",
                 "function_expression", "arrow_function", "method_definition"):
            _add_bindings(node.child_by_field_name("parameters"), src, defined)
            _add_bindings(node.child_by_field_name("parameter"), src, defined)

        for child in node.children:
            traverse(child)

    traverse(tree.root_node)

    return {
        "imports": imports,
        "require_calls": require_calls,
        "function_calls": function_calls,
        "method_calls": method_calls,
        "fetch_calls": fetch_calls,
        "import_locations": import_locations,
        "function_call_locations": function_call_locations,
        "method_call_locations": method_call_locations,
        "defined_names": sorted(defined),
        "aliases": aliases,
    }
