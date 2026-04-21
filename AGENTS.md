# AGENTS.md

This repository welcomes agent assistance, but changes should follow the same working practices as a careful human contributor.

## Scope

- These instructions apply to the whole repository.
- Prefer small, focused changes over broad refactors unless the task explicitly asks for a larger rewrite.
- Preserve existing behavior unless the change is intentionally fixing a bug or changing a documented feature.
- Keep changes aligned with the existing Python package, Docker, and GitHub Actions structure.

## Branching

- Always create a new branch before starting a new feature, fix, refactor, or documentation task.
- Do not work directly on `master`.
- Use a branch name that reflects the change, for example:
  - `fix/config-reload`
  - `feat/telegram-reminders`
  - `docs/update-deployment`
  - `chore/dependency-updates`

## Commits

- Always use Conventional Commits.
- Commit messages must be compatible with semantic-release.
- Create commits in logical groups.
- Each commit should represent one coherent change or one tightly related set of changes.
- Prefer clear commit types such as:
  - `fix(...)` for bug fixes
  - `feat(...)` for user-facing functionality
  - `docs(...)` for documentation-only changes
  - `test(...)` for test-only changes
  - `ci(...)` for GitHub Actions or workflow changes
  - `chore(...)` for maintenance work
  - `refactor(...)` for code restructuring without behavior changes
- Keep commit messages concise and specific.
- Commit messages should explain why the change was made when that is not already obvious from the diff.
- Do not use vague commit messages like `updates`, `misc fixes`, or `work in progress`.
- Never mention AI, agents, or automated authorship in commit messages.

## Testing And Verification

- Tests must always be run before committing when code or behavior changes.
- Functionality must be verified before committing, not just the tests.
- At minimum, run the most relevant validation for the change:
  - `make test`
  - `make lint`
  - `make build`
  - targeted manual verification for affected configuration loading, MQTT payload handling, notification delivery, persistence, CLI behavior, or Docker behavior
- If a change affects runtime behavior, verify the real behavior as directly as practical, not only through unit tests.
- If something cannot be tested locally, say so clearly in the final summary and in the pull request description.

## Documentation

- Update documentation whenever behavior, configuration, CLI flags, environment variables, notification backend settings, Docker usage, or operational expectations change.
- Documentation updates commonly belong in:
  - `README.md`
  - `sample_config.yml`
  - `docs/configuration.md`
  - `docs/deployment.md`
  - `docs/backends.md`
  - `docs/examples.md`
  - `docs/development.md`
- Do not leave docs behind after changing code or configuration behavior.

## Implementation Guidelines

- Add or update tests alongside code changes whenever practical.
- Prefer focused fixes over unrelated cleanup.
- Keep logging and error handling helpful for operators, especially because this project runs as a daemon and handles MQTT, persistence, and external notification backends.
- Be careful with alert lifecycle behavior, acknowledgement state, reminders, config reloads, retry paths, and persistence migrations. Reliability is more important than cleverness.
- Keep notification backend behavior explicit and testable.
- Avoid changing packaging, Docker, or release configuration unless the task requires it.

## Pull Requests

- Push the branch to the remote repository after the work is ready.
- Summarize what changed, why it changed, and how it was validated.
- Pull request descriptions should explain the reason for the change, not only list the code changes.
- Mention any manual verification performed.
- Call out any limitations, follow-up work, or areas that could not be tested.
- Never add advertising or attribution that the work was done by an AI agent.

## Final Check Before Commit

- Confirm the work is on a dedicated branch.
- Confirm tests were run.
- Confirm changed functionality was verified.
- Confirm relevant documentation was updated.
- Confirm the commit message follows Conventional Commits and semantic-release expectations.
- Confirm the local commit message hook is installed with `make install-hooks` when working in this repository.

## Final Check Before Opening A Pull Request

- Confirm the commits are logically grouped.
- Confirm the branch has been pushed to the remote.
- Confirm the pull request description clearly explains both what changed and why it changed.
- Confirm validation steps are included.
- Confirm there is no AI attribution, marketing, or automated authorship language in the branch, commits, or pull request text.
