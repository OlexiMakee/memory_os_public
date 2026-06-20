# Plan: <Title>

Status: draft
Feature: <feature-id>

## Technical Context

- Runtime:
- Data touched:
- Interfaces:
- Dependencies:

## Constitution Check

- [ ] Single responsibility: each changed module has one reason to change.
- [ ] Open/closed: extension points are used before changing stable contracts.
- [ ] Liskov/interface safety: existing callers keep working.
- [ ] Interface segregation: commands and helpers expose narrow responsibilities.
- [ ] Dependency inversion: high-level workflow code does not depend on concrete external tools.
- [ ] Unix fit: files are plain text, commands are composable, and structured output is available where useful.

## Architecture

Describe the minimal design. Prefer small modules, file-backed contracts, and
clear boundaries over broad rewrites.

## Verification Plan

- Command:
- Expected result:

## Migration And Compatibility

- Existing behavior preserved:
- Backward-compatible data changes:
- Rollback path:

## Complexity Ledger

List every added abstraction or dependency and why it is justified.
