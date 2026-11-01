# SPDX-License-Identifier: Apache-2.0
"""Living-intent layer — thin client over naja's in-engine SNL↔source link.

Recovers the source-level facts erased by SystemVerilog lowering — enum/FSM state
names + encodings, declared type names, and symbolic parameter expressions — by
calling naja's curated intent API (`naja.intentTypeOf` / `intentParametersOf`
/ `intentPackageMember`). Those walk the live slang AST *in C++*, over the
SNL↔slang bimap naja built at lowering time (`keep_ast_link=True`), and return
plain Python data. There is NO pyslang here and no second elaboration: naja owns
the one AST and answers in dicts.

Warm-only (the slang Compilation never serializes): the link exists only while it
is alive in-process — i.e. after a SystemVerilog load with
`keep_ast_link`. `naja.intentAvailable()` reports it. A cold snapshot load has no
Compilation, so intent degrades to "not loaded" until a warm (re)load; the exact
relink-after-snapshot tier is deferred.

Resolution rides naja-scope's structural resolver: a ref is resolved to its SNL
object (`resolve.py`), then handed to `naja.intent_*`. This is why anonymous
lowered primitives (`#<id>`) now answer — they resolve to the FF instance, which
the bimap maps back to its declaring source symbol. Package members (`pkg::name`)
have no SNL object and go through the name-keyed `naja.intentPackageMember`.

VHDL uses the same `keep_ast_link` retention, but naja answers it with a separate
record schema and `naja.intentPackageMember` does not cover it. The `_vhdl_*`
helpers normalize those records to the keys above; package members come from
`naja.intentDescribe` declarations. Records carry no field bit offsets, so VHDL
fields report width only, and inferred registers have no source symbol: ask for
the signal, not its flop.
"""
from __future__ import annotations

import re

from najaeda import naja

from .errors import ScopeError
from .resolve import resolve_path

# A sized Verilog literal, e.g. "32'd1", "8'hff", "4'b0101" (optionally signed).
# Parameter values sometimes come back this way; agents (and the eval goldens)
# want the plain decimal. x/z literals and expressions never match -> left as-is.
_SIZED_LITERAL_RE = re.compile(r"^\d+'[sS]?([dDbBhHoO])([0-9a-fA-F_]+)$")
_LITERAL_BASE = {"d": 10, "b": 2, "h": 16, "o": 8}


def _decimal_value(value):
    """Reduce a sized Verilog literal to its plain decimal string; pass anything
    else (already-decimal, a formula, an x/z literal) through unchanged."""
    if not isinstance(value, str):
        return value
    m = _SIZED_LITERAL_RE.match(value.strip())
    if not m:
        return value
    try:
        return str(int(m.group(2).replace("_", ""), _LITERAL_BASE[m.group(1).lower()]))
    except ValueError:
        return value


def _vhdl_src(source) -> str | None:
    return f"{source['file']}:{source['line']}" if source else None


def _vhdl_range(constraint_or_range) -> str:
    """`3 downto 0` from a resolved range, or the symbolic `WIDTH-1 downto 0`
    from a declared constraint."""
    r = constraint_or_range
    left = r.get("left_expression", {}).get("text", r.get("left"))
    right = r.get("right_expression", {}).get("text", r.get("right"))
    return f"{left} {r.get('direction')} {right}"


def _vhdl_type_name(rec: dict) -> str | None:
    """Declared type name, package-qualified the way get_intent takes it back."""
    decl = rec.get("declaration") or {}
    if decl.get("owner_kind") == "package":
        return f"{decl['owner']}::{rec['name']}"
    return rec.get("name")


def _vhdl_enum(rec: dict) -> dict:
    width = rec.get("width", 0)
    return {"width": width,
            "decl": _vhdl_src((rec.get("declaration") or {}).get("source")),
            "members": [{"name": m["name"], "ordinal": m["ordinal"],
                         "encoding": format(m["representation"], f"0{width}b")}
                        for m in rec.get("literals", [])]}


def _vhdl_field(field: dict) -> dict:
    rec = field.get("type", {})
    out = {"name": field["name"], "type": _vhdl_type_name(rec),
           "width": rec.get("width")}
    # VHDL FSMs often keep their state in a record field.
    if rec.get("kind") == "enumeration":
        out["enum"] = _vhdl_enum(rec)
    return out


def _vhdl_type(rec: dict) -> dict:
    """A naja VHDL resolved type, in the SystemVerilog get_type shape."""
    kind = {"enumeration": "enum"}.get(rec.get("kind"), rec.get("kind"))
    out = {"type": _vhdl_type_name(rec), "canonical_kind": kind,
           "width": rec.get("width")}
    if kind == "enum":
        out["enum"] = _vhdl_enum(rec)
    elif kind == "record":
        out["struct"] = {
            "width": rec.get("width"),
            "decl": _vhdl_src((rec.get("declaration") or {}).get("source")),
            "fields": [_vhdl_field(f) for f in rec.get("fields", [])]}
    if rec.get("ranges"):
        out["ranges"] = [_vhdl_range(r) for r in rec["ranges"]]
    return out


def _vhdl_parameter(p: dict) -> dict:
    """A VHDL generic or constant, in the SystemVerilog parameter shape."""
    expr = p.get("expression") or p.get("default_expression") or {}
    out = {"name": p["name"], "kind": p.get("kind"), "owner": p.get("owner"),
           "value": str(p["effective_value"]) if "effective_value" in p else None,
           "expr": expr.get("text"), "localparam": p.get("kind") != "generic",
           "src": _vhdl_src(p.get("source"))}
    if p.get("overridden"):
        out["overridden"] = True
    return out


class IntentUnavailable(ScopeError):
    """Raised when an intent query is made but the live AST link is absent."""


class IntentProvider:
    """Query client over naja's curated intent API, bound to a Session for
    structural ref→object resolution.

    Stateless beyond the session handle: the live AST is owned by naja (kept
    alive by `keep_ast_link`), so "loaded" is simply `naja.intentAvailable()`.
    Plugs into Session as the IntentProvider seam.
    """

    def __init__(self, session):
        self.session = session

    @property
    def _vhdl(self) -> bool:
        return self.session.load_spec.get("language") == "vhdl"

    @property
    def loaded(self) -> bool:
        return bool(naja.intentAvailable())

    # -- public queries ------------------------------------------------------

    def get_type(self, ref: str) -> dict:
        """Declared type of a value (net/term), incl. enum members+encodings."""
        if "::" in ref:
            return self._package_record(ref)
        resolved = resolve_path(self.session, ref)[0]
        obj = self._intent_obj(resolved)
        rec = naja.intentTypeOf(obj)
        if rec is not None and self._vhdl:
            rec = self._vhdl_value_type(obj, rec)
        if rec is None:
            return {"ref": ref, "label": resolved.path.split(".")[-1],
                    "note": (f"no source type recovered for {ref} (non-enum "
                             "scalar, or no source symbol for this object).")}
        rec["ref"] = ref
        return rec

    def get_fsm_states(self, ref: str) -> dict:
        """Enum members+encodings for an enum-typed register (the FSM-state /
        package-typedef-enum gate). Notes clearly when the ref is not enum."""
        rec = self.get_type(ref)
        fields = rec.get("struct", {}).get("fields", [])
        if "enum" not in rec and not any("enum" in f for f in fields):
            rec.setdefault("note", (f"{ref} is not enum-typed "
                                    f"(type {rec.get('type', '?')}); no FSM states."))
        return rec

    def get_parameters(self, ref: str, symbolic: bool = True) -> dict:
        """Parameters + localparams of an instance/module, with their SYMBOLIC
        initializer text (lost in lowering) alongside the elaborated value."""
        rec = naja.intentParametersOf(self._resolve_instance_obj(ref))
        if rec is None or rec.get("status") == "unavailable":
            raise ScopeError(
                f"{ref!r}: no parameters recovered (not an instance/module with "
                "a source symbol, or the intent layer is not loaded).")
        if self._vhdl:
            # A design sees whole packages; those stay reachable as pkg::NAME.
            own = [p for p in rec["params"] if p.get("owner_kind") != "package"]
            return {"parameters": [_vhdl_parameter(p) for p in own],
                    "package_constants_omitted": len(rec["params"]) - len(own),
                    "ref": ref}
        for p in rec.get("parameters", []):
            if "value" in p:
                p["value"] = _decimal_value(p["value"])
        rec["ref"] = ref
        return rec

    def describe(self, ref: str) -> dict:
        """Auto-dispatch on the ref's kind, matching get_intent(want='auto')."""
        if "::" in ref:
            rec = self._package_record(ref)
            return {"intent": "type" if "canonical_kind" in rec else "parameter",
                    **rec}
        resolved = resolve_path(self.session, ref)[0]
        if resolved.kind == "instance":
            return {"intent": "parameters", **self.get_parameters(ref)}
        return {"intent": "type", **self.get_type(ref)}

    # -- VHDL records ---------------------------------------------------------

    def _vhdl_value_type(self, obj, rec: dict) -> dict:
        """Normalized type of a signal/port, plus what only its declaration
        keeps: the source line and the symbolic constraint."""
        out = _vhdl_type(rec)
        desc = naja.intentDescribe(obj)
        if desc.get("status") == "available":
            out["src"] = _vhdl_src(desc.get("source"))
            constraint = (desc.get("declared_type") or {}).get("constraint")
            if constraint:
                out["constraint"] = _vhdl_range(constraint)
        return out

    def _vhdl_package_record(self, ref: str, pkg: str, member: str) -> dict:
        """Package members are reached from the designs that see them: VHDL
        identifiers are case-insensitive, and naja keeps no name-keyed lookup."""
        from . import snl
        wanted = (pkg.lower(), member.lower())
        for design in snl.iter_designs():
            desc = naja.intentDescribe(design)
            for decl in desc.get("declarations", []):
                if (decl.get("owner_kind") == "package"
                        and (decl["owner"].lower(), decl["name"].lower()) == wanted):
                    if decl.get("kind") == "type":
                        return {"name": decl["name"], "ref": ref,
                                "src": _vhdl_src(decl.get("source")),
                                **_vhdl_type(decl["resolved_type"])}
                    return {**_vhdl_parameter(decl), "ref": ref}
        raise ScopeError(
            f"intent: {member!r} not found in package {pkg!r} (or no elaborated "
            f"design uses that package) — {ref!r}")

    # -- resolution helpers --------------------------------------------------

    def _intent_obj(self, resolved):
        """The SNL object to hand to naja.intentTypeOf for a resolved ref:
        the raw net/term, or — for an instance — its SNLInstance (top: design)."""
        if resolved.kind == "instance":
            node = resolved.obj
            return node.design if node.is_top else node.snl_instance
        return resolved.obj  # raw SNL net/term (or selected bit)

    def _resolve_instance_obj(self, ref: str):
        """SNLInstance / SNLDesign for a parameters query. Falls back to a bare
        module name not present in the instance hierarchy."""
        try:
            node = resolve_path(self.session, ref, kind="instance")[0].obj
            return node.design if node.is_top else node.snl_instance
        except ScopeError:
            from . import snl
            design = snl.find_design(ref)
            if design is None:
                raise
            return design

    def _package_record(self, ref: str) -> dict:
        """A package member (pkg::name) — name-keyed over the live compilation,
        since packages are not instantiated and have no SNL object."""
        pkg, _, member = ref.partition("::")
        if self._vhdl:
            return self._vhdl_package_record(ref, pkg, member)
        rec = naja.intentPackageMember(pkg, member)
        if rec is None:
            raise ScopeError(
                f"intent: {member!r} not found in package {pkg!r} (or the intent "
                f"layer is not loaded) — {ref!r}")
        if "value" in rec:
            rec["value"] = _decimal_value(rec["value"])
        rec["ref"] = ref
        return rec
