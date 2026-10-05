# Homebrew packaging notes

`mb` is distributed through the first-party tap [jthingelstad/homebrew-tap](https://github.com/jthingelstad/homebrew-tap) (`brew install jthingelstad/tap/mb`). This note records why it is packaged that way and what each release has to check.

## Decisions

- **Stay on Python.** [Homebrew supports Python CLI applications](https://docs.brew.sh/Language-Specific-Formulae) with an isolated virtualenv and checksummed transitive resources, so users get a normal `brew install` without a rewrite. The CLI and MCP server already share tested services and SQLite contracts.
- **One formula, MCP included.** The PyPI-style install keeps `mcp` as an optional extra so the base CLI stays light, but Homebrew users get CLI and MCP in one install. A separate `mb-mcp` formula would duplicate runtime and state expectations, and core formulae do not support optional build flags. Revisit only if measured install cost warrants it.
- **Bottles for every Homebrew-bottled platform** (Apple Silicon macOS and Linux x86_64/arm64), so users rarely build from source.

## Release checklist

1. Tag the release and build the sdist and wheel once from that tag. Record their SHA-256.
2. Use `Language::Python::Virtualenv` with a declared Python version and `virtualenv_install_with_resources`. Install into `libexec` and link only `mb` into `bin`. Never touch the user's Python, config, token, state file or client registrations; state lives outside the Cellar and survives upgrades.
3. Pin every runtime resource with a checksum, including the MCP tree. Generate resource blocks with `brew update-python-resources` (configured for `mb[mcp]`) against the exact release source and compare them with `uv.lock`. Exclude dev-only tools (Ruff, mypy, pytest). Nothing is downloaded at runtime.
4. Check native build dependencies for source builds (MCP pulls in cryptography/cffi and Rust-backed pydantic-core/rpds). Resolve them from actual formula builds, not developer wheels.
5. The formula test should run the installed keg with an isolated `HOME` and no network: `mb --version`, `mb --help`, `mb guide`, a structured refusal without a token, and the MCP catalog over stdio. No live writes.
6. Run `brew audit`, `brew test`, a clean source build and a bottle install/upgrade before updating the tap. `mb doctor` on an upgraded machine should show the Homebrew executable first on `PATH`.

## Language tradeoffs

Python provides the HTTP client, Typer CLI, MCP SDK, tests and SQLite implementation; Homebrew hides the runtime. Its cost is a larger dependency tree, handled with checksummed resources and bottles.

Rust could ship a compact native binary but would replace the shared services, MCP integration and tested contracts. TypeScript has a mature MCP ecosystem but adds Node packaging while replacing working code. Neither is worth a rewrite unless measured startup, install or reliability problems survive the Homebrew packaging, or a concrete single-binary requirement appears.
