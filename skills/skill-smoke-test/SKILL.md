---
name: skill-smoke-test
description: Use this skill when the user explicitly asks to test whether DeepAgents skills are connected, especially with phrases like skill test, smoke test, skill 测试, or 技能测试.
---

# skill-smoke-test

When this skill is used, respond in Chinese with this exact first line:

```text
SKILL_SMOKE_TEST_OK
```

Then briefly explain that the `skill-smoke-test` skill was loaded from
`skills/skill-smoke-test/SKILL.md`.

Do not use this skill for normal project questions. Use it only when the user
explicitly wants to test skill wiring.
