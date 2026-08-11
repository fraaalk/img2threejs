# img2threejs: skill-to-plugin refactor research

**Status:** recommendation only — no production skill files were moved or rewritten.
**Research date:** 2026-08-09

## Decision

Refactor `img2threejs` into a **dual-manifest, skill-first plugin**:

1. Make the current repository the source for one plugin named `img2threejs`.
2. Put the portable Agent Plugins v1 package at the repository root.
3. Add the Codex/ChatGPT manifest in `.codex-plugin/plugin.json` for the current Codex marketplace and universal-plugin workflow.
4. Ship **one** plugin skill, `skills/img2threejs/`, containing the existing `SKILL.md`, `forge/`, `grimoire/`, `docs/`, `integrations/`, and needed `assets/` as its self-contained runtime.
5. Do **not** introduce an MCP server, hooks, connectors, or a browser extension in the first release.

This is the smallest migration that makes installation and discovery first-class while preserving the existing high-value behavior: a quality-gated, local, stdlib-only reconstruction workflow. MCP would add process startup, transport, auth, and trust responsibilities without solving a current requirement.

## What was assessed

The repository is not a simple prompt file. It contains:

- a 613-line primary `SKILL.md` with a staged sculpting/review contract;
- 162 Python files under `forge/`, used as local gates and generators;
- 34 `grimoire/` guidance artifacts and 32 `docs/` artifacts;
- optional local vision integrations and three distributable visual assets;
- CI, release, issue, and contribution policies that currently expect the skill at the repository root.

The architecture is an evidence loop: intake → assessment/spec → procedural build → render review → bounded correction. `SKILL.md` and `docs/ARCHITECTURE.md` are the orchestration layer; the Python commands are the enforcement layer. Therefore the migration must move the whole execution closure together, rather than placing only the Markdown file in a plugin.

## Standards and host findings

### Portable Agent Plugins v1

Agent Plugins v1.0.0 is an open, vendor-neutral package format, currently a Working Draft. Its portable components are intentionally limited to **Agent Skills** and **MCP servers**. A conforming package has a root `plugin.json`; skills are discovered only from immediate children of `skills/`, each with `SKILL.md`; MCP configuration, when present, is root `mcp.json`. Installation, marketplaces, permissions, UI, authentication, and hooks are explicitly client-managed.

Important implications:

- The root portable manifest is **not** a component registry. Do not put `skills`, `mcpServers`, hooks, or custom fields in it.
- Files referenced as package paths must remain inside the resolved plugin root. A symlink that escapes the plugin is invalid.
- Client-specific behavior belongs in a reverse-domain extension namespace, not in portable manifest fields.
- A bad portable manifest is fatal; a bad individual skill or MCP entry is isolated so other components may still load.

Sources: [Agent Plugins home](https://agent-plugins.org/), [build guide](https://agent-plugins.org/plugin-authors), [manifest reference](https://agent-plugins.org/plugin-authors/manifest), and the [v1 specification](https://agent-plugins.org/specification).

### Codex / ChatGPT plugin host

Codex and ChatGPT currently use a separate, host-specific plugin format: `.codex-plugin/plugin.json`, with `skills` normally pointing to `./skills/`. Codex supports local/repository marketplaces under `.agents/plugins/marketplace.json`, and its plugin browser requires a fresh session after installation to expose bundled skills.

This host format and the portable Agent Plugins manifest have different locations and schemas. They can coexist in one directory without ambiguity:

- root `plugin.json` — portable Agent Plugins v1;
- `.codex-plugin/plugin.json` — Codex/ChatGPT distribution metadata.

Sources: [OpenAI Docs: Plugins](https://learn.chatgpt.com/docs/plugins), [OpenAI Docs: Package your plugin](https://developers.openai.com/plugins/build/plugins).

### Cross-client reality

The standard’s compatibility page lists ChatGPT & Codex, VS Code/Copilot, Cursor, and Kiro as skill-capable clients. Their host-specific features differ. In particular, hooks are not a portable v1 component, and the Codex plugin manifest is not the portable root manifest. Treat the portable skill as the product; layer host integration around it.

Source: [compatible clients](https://agent-plugins.org/compatible-clients). VS Code’s implementation independently confirms the same root portable layout and clearly separates portable skills/MCP from client-specific agents, hooks, and slash commands: [VS Code Agent Plugins](https://code.visualstudio.com/docs/agent-customization/agent-plugins).

### Industry confirmation

AWS’s public plugin material supports the same design division: plugins package workflows, MCP connections, references, and sometimes hooks, but only introduce live service tooling where it is necessary. Its deployment example uses MCP for live AWS knowledge, pricing, and IaC guidance—capabilities this skill does not presently need. [AWS launch post](https://aws.amazon.com/blogs/developer/introducing-agent-plugins-for-aws/)

The supplied AAIF, Google, Vercel, AWS Open Source, and Facebook URLs were checked as research leads. The browser could not retrieve the AAIF/Google/Vercel/Facebook pages directly in this environment, so no unverified claims from them are used as normative input. The recommendation relies on the official standard and host documentation above.

## Recommended target tree

```text
img2threejs/                         # plugin root and repository root
├── plugin.json                      # portable Agent Plugins v1 manifest
├── .codex-plugin/
│   └── plugin.json                  # Codex/ChatGPT manifest
├── skills/
│   └── img2threejs/                 # the skill root
│       ├── SKILL.md
│       ├── forge/
│       ├── grimoire/
│       ├── docs/
│       ├── integrations/
│       ├── assets/
│       └── skills/                  # only if the four specialization docs remain runtime inputs
├── .agents/plugins/
│   └── marketplace.json             # optional repo-local testing/distribution catalog
├── tests/                            # retain or relocate tests consistently with CI
├── README.md
├── CHANGELOG.md
└── LICENSE
```

The key constraint is that `skills/img2threejs/` must be self-contained. Existing instructions repeatedly say to run `forge/...` from the skill root, so this layout preserves the command model exactly after a `cd skills/img2threejs` performed by the host/installer or documented invocation.

## Proposed manifests

### `plugin.json` — portable core

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
  "name": "img2threejs",
  "version": "1.4.4",
  "description": "Quality-gated image-to-procedural-Three.js reconstruction.",
  "license": "Apache-2.0",
  "repository": "https://github.com/<owner>/<repo>",
  "keywords": ["threejs", "image-to-3d", "procedural-modeling", "reconstruction"]
}
```

Do not add `skills`, `mcpServers`, hooks, marketplace fields, or Codex fields here. The name already meets the portable v1 restrictions (lowercase ASCII, 1–64 characters, no consecutive separators).

### `.codex-plugin/plugin.json` — Codex/ChatGPT host

```json
{
  "name": "img2threejs",
  "version": "1.4.4",
  "description": "Quality-gated image-to-procedural-Three.js reconstruction.",
  "skills": "./skills/"
}
```

Keep host-only fields here. Add `.mcp.json`, `.app.json`, or hooks only in a later release when their companion implementation exists.

### Optional local marketplace

```json
{
  "name": "img2threejs-local",
  "interface": { "displayName": "img2threejs Local" },
  "plugins": [
    {
      "name": "img2threejs",
      "source": { "source": "local", "path": "./plugins/img2threejs" },
      "policy": { "installation": "AVAILABLE", "authentication": "ON_INSTALL" },
      "category": "Productivity"
    }
  ]
}
```

This catalog is useful for a repo/team test path. It is not part of Agent Plugins portability and should not be required for use in another compatible host.

## Migration plan

### Phase 0 — lock behavior before moving files

1. Capture the current validation baseline: `forge/next.py`, targeted unit tests, and one representative generic reconstruction fixture.
2. Add a path-invariance test: from the future `skills/img2threejs/` directory, every documented `forge/...` command must resolve and produce the same result.
3. Record the current version and release policy; do not mix content changes with the package move.

### Phase 1 — create the self-contained skill

1. Create `skills/img2threejs/`.
2. Move the runtime closure into it: primary `SKILL.md`, `forge/`, `grimoire/`, runtime `docs/`, `integrations/`, assets, and specialized skill documents that the main skill references.
3. Update every internal relative reference and every CI/release/test path. Use `rg` to prove there are no stale root references.
4. Preserve licenses and provenance files at the plugin root. If any source data is intentionally not shipped, make that an explicit packaging exclusion with a test.

### Phase 2 — add discovery and distribution

1. Add the two manifests above.
2. Add a repository marketplace only for local/team testing; do not publish yet.
3. Scaffold/validate the Codex manifest using the plugin-creator validator, and validate the root portable manifest against Agent Plugins v1 schema.
4. Install from a clean local marketplace; start a new Codex session; verify the skill appears and runs its first mandatory state command.

### Phase 3 — publish without regressions

1. Release a dedicated packaging version (recommended `1.5.0`, because install/discovery changes are user-visible).
2. Keep a temporary migration note for existing `~/.codex/skills/img2threejs` users. Do not keep an escaping symlink inside the portable package.
3. Test at least Codex and one independent portable client before claiming cross-client support.
4. Publish a compatibility matrix showing exactly what was tested: skill loading, script execution, asset access, local state, optional adapters, and MCP/hook status.

## Risks and mitigations

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Broken relative paths | The documented CLI assumes the current skill root. | Move all runtime dependencies together; test every documented command after relocation. |
| Symlink escape | The portable spec rejects package files resolving outside the root. | Package real files, not `skills/` symlinks to this checkout. |
| Two manifests drift | Codex and portable metadata can diverge. | Add one version consistency test and release checklist. |
| Context bloat | The skill is already very large. | Keep progressive-disclosure references; do not duplicate `SKILL.md` in host manifests. |
| Unnecessary MCP | Adds security, process, auth, and maintenance surface. | Defer it until a required live tool cannot be delivered through existing host tools. |
| Release/CI breakage | Current workflows refer to root paths. | Update paths in the same atomic PR and retain a relocation test. |

## Validation gates for the implementation PR

- `plugin.json` validates as Agent Plugins v1.
- `.codex-plugin/plugin.json` validates with the Codex plugin validator.
- The plugin contains no package path escaping its root.
- `skills/img2threejs/SKILL.md` validates as an Agent Skill and its directory name matches frontmatter `name`.
- All Python tests pass from the relocated source tree.
- A fresh Codex plugin install exposes the skill in a fresh session.
- One full generic fixture completes from the installed plugin with the same generated artifacts as the pre-migration baseline.
- The marketplace path, version, description, and license are consistent across release files.

## What not to do

- Do not merely add `.codex-plugin/plugin.json` beside the existing root `SKILL.md`; that produces a Codex package but not the portable Agent Plugins layout.
- Do not put Codex-only `skills`, `apps`, or hook fields in root `plugin.json`.
- Do not split the current instructions, gates, and references into many skills in this refactor. That is a separate product-design change and would make behavioral regression hard to diagnose.
- Do not add MCP just to make the package look more complete.
- Do not claim every compatible client works until installation and script execution are exercised on it.

## Bottom line

Make `img2threejs` a plugin now, but preserve it as **one rigorous skill inside a portable package**. Ship both the Agent Plugins root manifest and the Codex-specific manifest, keep all executable/guidance dependencies inside `skills/img2threejs/`, and postpone MCP/hooks. That gives immediate Codex distribution while keeping the real reconstruction workflow portable and future-proof.
