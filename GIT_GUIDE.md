# Git in a few steps

Git records local snapshots of your code. GitHub stores a shared online copy.
Run the commands below from the `codex-ollama` folder in PowerShell.

## What the commands mean

| Command | Purpose |
| --- | --- |
| `git status` | Show changed files and files ready for the next snapshot. |
| `git diff` | Show changes that have not been staged yet. |
| `git add <file>` | Stage a file for the next snapshot. |
| `git diff --cached` | Review the staged changes. |
| `git commit -m "Describe the change"` | Save a local snapshot. |
| `git push` | Send local commits to GitHub. |
| `git pull --ff-only` | Download updates when they can be applied without a merge. |

## First upload

The local repository uses `main` and the GitHub URL is named `origin`:

```powershell
git remote -v
git status
```

Set your commit identity once, using your own name and email. A GitHub-provided
private commit email also works. These values are recorded in commits.

```powershell
git config user.name "Your Name"
git config user.email "YOUR_GITHUB_COMMIT_EMAIL"
```

Check whether GitHub already has commits before the first upload:

```powershell
git ls-remote --heads origin
```

If this succeeds with no output, the remote repository is empty. Review the
files, stage them, create your first commit, then upload:

```powershell
git add .gitignore .gitattributes app.py src tests requirements.txt README.md GIT_GUIDE.md AGENTS.md
git diff --cached --stat
git diff --cached
git commit -m "Add local Ollama document chat"
git push -u origin main
```

If `git ls-remote` lists branches, the remote already has history. Preserve it:
fetch it and inspect it before combining the local project with that history.
Do not force-push over it. A failed connection does not mean the repository is empty.

GitHub may open a browser for sign-in when you push. Use Git Credential Manager
or a personal access token if asked; do not put a token in files or the remote URL.

## Later changes

```powershell
git status
git diff
git add app.py src README.md
git diff --cached
git commit -m "Describe your change"
git push
```

Stage the files you actually changed; the example above is not a required list.

## What is shared

The repository includes the root launcher, `src/`, `tests/`, dependency list and
documentation. `.gitignore` excludes uploaded documents, SQLite indexes and
embeddings, model weights, `.venv/`, `.tmp/`, logs, caches and local secrets.
Those files stay on your computer. A fresh clone needs its own Python environment,
Ollama models and document uploads; follow [README.md](README.md).

`.gitignore` only excludes untracked files. If a secret was already committed,
adding it to `.gitignore` does not remove it from Git history.
