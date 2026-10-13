# Agent Guidelines

## Language of code and comments

- Write all code comments, docstrings, commit messages, and developer
  documentation in English.
- Never write comments in Polish. Polish is allowed only inside
  user-facing strings where it is functionally required:
  - the `system_prompt` value in `config/params.yaml` (the robot speaks Polish),
  - test fixtures/payloads containing Polish utterances (e.g. `test/test_parser.py`),
  - example shell commands demonstrating Polish input.
- The same rule applies to debug/config files (`.code-workspace`,
  `.vscode/`, launch files): comments in English.

## Architecture integrity

- Treat `ARCHITECTURE.md` as the source of truth for system design.
- Read the relevant sections before changing code (structure, components,
  data flow, deployment).
- Keep code and architecture in sync: update `ARCHITECTURE.md` when a change
  affects structure, components, topics, services, actions, or launch
  composition.
- If a request conflicts with `ARCHITECTURE.md`, keep the existing design
  and point out the conflict instead of silently diverging.

## Testing

- Every behavior change needs a test: add or extend the `pytest` matrix
  in `test/` alongside the implementation (new file only if no existing
  one fits, e.g. `test/test_prompts.py` for a new pure module).
- Keep ROS out of unit tests: put logic in pure, framework-free functions
  (like `nao_agent/llm/prompts.py`) and test those; use fakes for NAOqi
  proxies (see `FakeSession`/`FakeLeds` patterns in `test/`).
- Always run the full suite (`python3 -m pytest test/ -q`) plus
  `py_compile` on touched files before reporting done; a failing new
  test means fixing the code (or the test), never deleting coverage.
- Do not commit with red tests.

## No gold plating

- Implement exactly what was asked. Do not add extra features, configs,
  nodes, or "nice to have" refactors beyond the request scope.
- Prefer editing existing files over creating new ones. Do not create
  files (docs, scripts, configs) unless they are necessary for the task.
- If you see an opportunity for a follow-up improvement, mention it in
  the final summary instead of implementing it.
- Keep changes minimal and verifiable: validate results (run tests,
  parse configs) before reporting done.
