# Changelog

## 0.2.0 (candidate)

- **Breaking for MCP clients:** all hierarchical paths and search patterns
  now use arrays of exact names; string paths are rejected. Bus selections
  use a separate `bit` field. Results return array paths, and cone subtree
  groups are lists of records. Schematic net/trace targets use `{path, bit}`
  records. See [migration examples](docs/paths.md).
