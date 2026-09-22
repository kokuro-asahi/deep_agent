# Skills

Store reusable DeepAgents skills in this directory. Each skill must have its own
subdirectory and a `SKILL.md` file. The YAML frontmatter `name` must match the
subdirectory name.

```text
skills/
  your-skill-name/
    SKILL.md
    scripts/
    references/
    assets/
```

The backend loads this directory by default through `AGENT_SKILLS_PATHS=skills`.
