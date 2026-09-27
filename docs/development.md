# Development

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/pytest tests -q
.venv/bin/ruff check custom_components tests
.venv/bin/mypy custom_components/ai_pool
```

The Home Assistant test harness imports `fcntl` and therefore **only runs on
Linux and macOS**. On Windows the provider-independent tests still run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/test_errors.py tests/test_strategies.py -q --noconftest
```

Docker is the local stand-in for CI (Python 3.14, same harness pin as
`requirements-test.txt`). See `AGENTS.md`.

CI runs the full suite on Ubuntu, with `--cov-fail-under=95`, plus `hassfest`
and HACS validation. Pull requests also run `mkdocs build --strict`.

## Quality scale

Progress is tracked in
[`quality_scale.yaml`](https://github.com/FiveElements/ha-ai-pool/blob/main/custom_components/ai_pool/quality_scale.yaml)
against Home Assistant's
[integration quality scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/).
The manifest currently declares **platinum**. Silver needs `test-coverage`
(≥95 %) in CI (`--cov-fail-under=95`). Platinum adds `mypy --strict` on
`custom_components/ai_pool`.

Every entity uses `has_entity_name`. The pool entity takes its device's name,
except on `tts`, where a translation key names it because the tts manager
refuses an engine whose `entity.name` is None. The pool entity is
`unavailable` only when no member could answer at all.

Exemptions: `reauthentication-flow`, `test-before-configure` and
`test-before-setup` (a pool holds no credentials and opens no connection), and
the discovery and device rules (a pool is one service device, created and
removed with its entry).

## Supported Home Assistant versions

Requires **2026.9.0** or newer (`hacs.json` and the CI matrix).

## Releasing

Bump `version` in `custom_components/ai_pool/manifest.json` **and**
`pyproject.toml`, then push a matching tag:

```bash
git tag v0.7.2 && git push origin v0.7.2
```

The release workflow refuses to publish when the tag and the manifest disagree,
builds `ai_pool.zip`, and attaches it to a GitHub release.

## This documentation site

```bash
pip install -r requirements-docs.txt
mkdocs serve
```

Pushes to `main` publish [GitHub Pages](https://fiveelements.github.io/ha-ai-pool/)
with Material for MkDocs.

How routing is split across modules is documented under
[Architecture](architecture.md).
