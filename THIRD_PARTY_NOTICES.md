# Third-party notices

## COLE Portable Core

The optional Succession Calibrator integration depends on:

- Project: `cole-portable-core`
- Repository: <https://github.com/terryncew/cole-portable-core>
- Pinned commit: `c7a2d63befa9105579ac28940f3de00cdc8d76cc`
- Declared package version: `0.1.1`
- License: MIT
- Algorithm identifier required at runtime: `cole-portable-core-2.1-draft`

The implementation is installed as a dependency. Its equations are not copied into Endurance Gate. The calibrator refuses a package that exposes a different algorithm identifier.

The dependency is a draft measurement implementation. Pinning makes builds reproducible; it does not turn the draft into an external standard or prove that its metrics predict deployed-agent outcomes.

