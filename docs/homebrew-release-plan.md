# Homebrew release plan (publication held)

Keep Python for 2.0. The implementation already shares tested CLI/MCP services and SQLite contracts. [Homebrew officially supports Python CLI applications](https://docs.brew.sh/Language-Specific-Formulae), including isolated virtualenv installation and checksummed transitive resources. A rewrite is not necessary to get a normal `brew install` experience.

Recommend a first-party tap, initially one `mb` formula that includes MCP support. The PyPI base installation can still keep `mcp` optional; Homebrew users should get both CLI and MCP with one install. Avoid asking users to inject `pip install` into a Homebrew-owned virtualenv. A separate `mb-mcp` formula would duplicate runtime/state expectations; an optional tap flag adds maintenance and is unsupported in core formulae. Consider a lightweight separate formula only if measured install cost warrants it.

## Release artifacts and gates

1. Finish candidate review and coordinated 1.x adoption; select the stable version, immutable tag and exact source archive. Build once, publish that exact sdist/wheel only when authorized, record SHA-256 and dependency manifest. No current candidate tag or release URL exists as part of this work.
2. Use `Language::Python::Virtualenv`, a declared supported versioned Python and `virtualenv_install_with_resources`. Install into `libexec` and link `mb` into `bin`; never modify the user's Python, MB config, credentials, receipt database or client registration. Preserve state outside the Cellar across upgrades.
3. Pin every runtime transitive source resource and checksum, including the optional MCP tree. Generate resource blocks using `brew update-python-resources` and its documented `pypi_packages package_name: "mb[mcp]"` configuration against the exact release source, then compare to the reviewed lockfile. Do not include dev-only Ruff/mypy/pytest. No runtime dependency downloads. A build backend resource/build dependency may also be required when build isolation is disabled.
4. Source builds need explicit native dependencies: Pillow JPEG/WebP support; MCP's cryptography/cffi and Rust-backed Pydantic/RPDS packages. Resolve and test actual Homebrew formula/build dependencies rather than relying on developer wheels. Review `openssl@3`, `libffi`, Rust build tooling, `jpeg-turbo` and `webp` requirements; this list is a verification checklist, not a tested formula. Build bottles for supported macOS architectures and Linux so users usually avoid source builds.
5. Test the installed keg with isolated `HOME`/config and synthetic HTTP: CLI help/guide, no-auth structured refusal, static MCP catalog/resource handshake without tokens, and a mocked image->draft lifecycle. The test must run installed files, not the checkout, and use no live writes. Run `brew audit`, `brew test`, a clean source build and bottle install/upgrade verification before tap publication.
6. Coordinate PATH/adoption so the Homebrew executable and existing `uv tool`/project 1.x installation are unambiguous. Keep the previous executable available for rollback; do not erase operation receipts or move authentication implicitly. Register clients separately only when authorized.

The candidate's existing CI checks optional/base wheel isolation and synthetic stdio behavior. Homebrew source/bottle builds and tap publication remain release gates; no formula has been installed or published.

## Language tradeoffs

Python provides the established HTTP, Typer, MCP SDK, tests and SQLite implementation; Homebrew can hide its runtime/dependency installation. Its remaining cost is a larger dependency tree and native package builds, best addressed with checksummed resources and bottles first.

Rust could provide a compact native executable with explicit compilation and cross-platform binaries, but would replace the shared services, MCP integration and tested contracts. SQLite/image/TLS still need packaging choices. Consider it only if measured startup/installation/reliability problems survive the Homebrew work, or a concrete single-binary requirement emerges.

TypeScript has a mature MCP ecosystem, but adds Node/npm packaging and dependency maintenance while replacing working Python services; it offers no demonstrated reliability advantage for this local CLI/MCP use case. Permission to change languages gives flexibility, not evidence that a rewrite is currently useful.
