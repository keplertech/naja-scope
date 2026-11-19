# Hierarchical paths

Paths are JSON arrays of exact names. The top name is optional; `[]` denotes
the top. No element is split, unescaped, trimmed, or interpreted as a bit
select or glob by `resolve`. Use names exactly as returned by the tools.
Verilog's source escape delimiter and trailing whitespace are not part of the
name stored by the frontend: source `\d_in[0] ` has the name `d_in[0]`.

```json
{"path": ["top", "u_core", "d_in"], "bit": 0, "kind": "term"}
```

A returned descriptor's `path`, `bit`, and `kind` can be passed directly to
`resolve`. The bit is an integer (including negative bus indices) or null.
For a scalar literally named `d_in[0]`, use `["u_core", "d_in[0]"]` and omit
`bit`. `["a.b"]` and `["a", "b"]` identify different instance occurrences.
Names containing `/`, `$`, brackets, or spaces remain single elements.
VHDL generate labels containing dots likewise occupy one element.

Missing names report the original zero-based element index, its value,
the exact parent path, and close names visible at that level.

## Search

`find` takes an array of per-element case-sensitive fnmatch patterns.
`*` and `?` never cross hierarchy levels. A dedicated `"**"` element matches
zero or more levels. For example:

```json
{"pattern": ["**", "*state*"], "kind": "net"}
{"pattern": ["top", "u_*", "data*"], "kind": "port"}
```

Use fnmatch bracket escaping for literal pattern metacharacters, e.g.
`"d_in[[]0]"` matches the literal name `d_in[0]`. Exact `resolve` needs no
such escaping. Regex-like text is treated as a glob; `$` is literal.

## Tool and result changes

All path-taking tools require arrays, including hierarchy, statistics,
source, connectivity, cones, and schematic focus. `get_intent(ref=...)` also
takes a list: `["u_core", "PARAM"]`, `["pkg::NAME"]`, or `["pkg"]`.
Module-card and content-hash arguments remain model names; filesystem paths
remain strings. A human display label is never an address accepted as input.

Drivers and loads retain instance descriptors for leaf endpoints, with
`kind: "instance"` and `bit: null`. `pin` and `pin_bit` identify the endpoint
pin; `queried_bit` identifies the seed bit. Top endpoints are term descriptors
with a separate bit field. Unnamed primitive pins have no exact-name address;
use their containing instance descriptor. `find` omits unnamed terms/nets.

Cone frontier paths use the same descriptors. `root`, `object`, `port`,
subtree paths, and example paths are arrays too. Cone `by_subtree` is a list
of records with `path`, `count`, and `examples`, replacing a string-keyed
mapping. Examples use actual addressable instance names, including `#id`
for anonymous instances (additional `#` prefixes disambiguate collisions with
literal names). The adjacent `label` field remains human-readable.

```python
open_schematic(path=["top", "u_core"])
show_schematic_net(path=["top", "u_core", "D"], bit=3)
export_schematic(
    file="cone.svg",
    instances=[["top", "u_core"]],
    nets=[{"path": ["top", "u_core", "D"], "bit": 3}],
    traces=[{"path": ["top", "u_core", "Q"], "bit": 0}],
)
annotate_schematic(items=[{
    "path": ["top", "u_core"], "kind": "instance", "message": "Check reset"
}])
```

Annotations apply to whole instances or ports; non-null bit selections are
rejected. Schematic selections return an instance descriptor with an array
path. Nested targets have explicit MCP schemas for `path` and `bit`.

## Migrating clients

This is a breaking change with no string-path compatibility layer. Construct
name arrays from known hierarchy names. Do not automatically split saved
strings: their boundaries may already be ambiguous. Rediscover saved targets
through hierarchy/search tools and store their returned descriptors. Replace
recursive name patterns like `"*state*"` with `["**", "*state*"]`.
