# OpenWorker Agent Guide

## Verification

Run backend checks from the repository root:

```bash
.venv/bin/pytest tests -q
.venv/bin/python -m compileall -q coworker
```

The desktop GUI is a separate Node project. Run its checks from
`surfaces/gui/`, not the repository root:

```bash
npx tsc --noEmit
npm test
npm run check:i18n
```

The full backend suite currently has one pre-existing failure:

```text
tests/test_provider_router.py::test_set_provider_auto_adds_recommended_when_pulled
```

Do not attribute these failures to an unrelated change without checking the
failure output and the baseline.

## Remote execution

The engine, LLM/provider interaction, tool orchestration, approval policy, and
session state stay client-side in OpenWorker. An RVM is an execution surface,
not a second OpenWorker server. If a selected remote host is unavailable or
unauthorized, return an explicit error; never silently fall back to Local.

Remote paths must use the existing remote path algebra and root-containment
checks. Never call local `Path.resolve()` on a remote path.

RVM credentials belong in `SecretStore` and are sent only in Bearer
`Authorization` headers. Never put tokens in URLs, logs, `repr`, exceptions, or
tool output.

## GUI and i18n

`surfaces/gui` owns the user-facing translations. `npm run check:i18n` must
pass. Keep system prompts and tool descriptions in English; translate UI
strings through the GUI i18n layer.
