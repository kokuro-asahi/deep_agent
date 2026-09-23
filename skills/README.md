# Shared Skills

This directory is the single source of truth for reusable, knowledge-oriented
DeepAgents skills. Copy or mount this whole directory into another project that
uses the same agent architecture; do not scatter a skill's instructions among
role prompts, application code, and ad-hoc documents.

Each skill has its own subdirectory and a `SKILL.md` file. The YAML frontmatter
`name` must match the subdirectory name.

```text
skills/
  your-skill-name/
    SKILL.md
    scripts/
    references/
    assets/
```

## Use in another agent project

Place the directory below that project's `AGENT_FILESYSTEM_ROOT`, then add the
following to its `.env`:

```dotenv
AGENT_FILESYSTEM_ROOT=/absolute/path/to/that-project
AGENT_SKILLS_PATHS=skills
```

The receiving project's existing skill registry will discover every skill
folder. Restart the backend after changing `.env` or skill files, and enable
the required skill ID when a new conversation is created.

## Configuration and executable integrations

Keep reusable instructions, reference material, and static assets inside the
skill folder. A `SKILL.md` must never contain a secret or an environment-specific
endpoint. If a skill depends on backend tools or scripts, document the required
environment variables in `references/environment.md` inside that skill.

The application reads `.env` itself; a skill does not read `.env` directly.

To provide callable tools, a skill may add this explicit entrypoint:

```text
skills/your-skill-name/scripts/tools.py
```

That file must export `get_tools()`, returning a list of named Python callable
tools. The backend loads it only after its skill ID has been selected for a
conversation. Other files in `scripts/` may support the entrypoint, but are not
registered automatically. This makes the executable interface deliberate and
avoids running unrelated helper files as tools.
