# img2threejs shared-agent contract

This repository is the canonical source for the `img2threejs` skill used by both Claude and Codex.

- Canonical checkout: `/Users/nhonh/Documents/personal/img2threejs`
- Claude entrypoint: `/Users/nhonh/.claude/skills/img2threejs`
- Codex entrypoint: `/Users/nhonh/.codex/skills/img2threejs`

The two entrypoints must be symlinks to this checkout. Never maintain independent copies.

## Change rules

- Preserve the code-only procedural Three.js contract; do not silently download meshes or art packs.
- Keep claims honest: distinguish implemented capability from roadmap or design-only documentation.
- Treat `forge/` as deterministic tooling and `grimoire/` as routed reference material.
- Keep backward compatibility for existing sculpt specs unless a migration is explicitly planned.
- When changing schema, gates, generators, or review behavior, add or update focused tests.
- Keep `SKILL.md`, `README.md`, `CHANGELOG.md`, `ROADMAP.md`, and `agents/openai.yaml` consistent when
  release-facing behavior changes.
- Keep the companion showcase separate at
  `/Users/nhonh/Documents/personal/img2threejs-showcase`; validate integrations in both repositories.

## Verification

Run from this repository:

```bash
python3 -m unittest discover -s forge/tests -p 'test_*.py'
python3 /Users/nhonh/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```

Do not report completion without reading the fresh outputs. For visual reconstruction changes,
structural tests and screenshot/reference-loop validation are separate required gates.

## Mandatory visual screenshot gate

For every visual reconstruction task, a readable screenshot is a hard prerequisite
for visual implementation claims and completion:

1. Before accepting visual results, verify that the browser/screenshot MCP is
   installed, authenticated, reachable, and able to capture the running showcase.
2. Save fresh PNG/JPEG screenshots inside the workspace, including the fixed
   reference view and the required orbit views. Inline previews alone are not
   evidence.
3. Read the saved screenshots back with an image-capable tool and verify that
   they contain the rendered model at the expected dimensions. A screenshot that
   cannot be opened or visually read is a failed gate.
4. Produce and retain a side-by-side reference/render comparison, semantic image
   scoring, pixel/feature comparison, and the `diagnose_render.py` output for the
   saved render before reporting visual validation.
5. If capture, file write, readback, comparison, scoring, or diagnosis fails,
   stop the visual workflow. Tell the user to install, authenticate, or repair
   the relevant MCP/tooling and rerun the check. Do not infer visual evidence
   from runtime readiness, structural tests, inline screenshots, or code review,
   and do not claim the visual gate passed.
