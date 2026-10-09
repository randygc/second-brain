# Issue tracker: GitHub

Issues and specs live in `randygc/second-brain`.
Use the `gh` CLI with `--repo randygc/second-brain`.

- Create: gh issue create --repo randygc/second-brain --title "..." --body-file <file>
- Read: gh issue view <number> --repo randygc/second-brain --json number,title,body,labels,comments
- List: gh issue list --repo randygc/second-brain --state open
- Comment: gh issue comment <number> --repo randygc/second-brain --body-file <file>
- Apply labels: gh issue edit <number> --repo randygc/second-brain --add-label "<label>"
- Remove labels: gh issue edit <number> --repo randygc/second-brain --remove-label "<label>"
- Close: gh issue close <number> --repo randygc/second-brain

When a skill says “publish to the issue tracker,” create a GitHub issue.
When it says “fetch the relevant ticket,” read the referenced GitHub issue.

## Pull requests as a triage surface

PRs as a request surface: no.
