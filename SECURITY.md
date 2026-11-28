# Security

## Reporting a problem

Please report security problems privately through GitHub:
**[Report a vulnerability](https://github.com/JR91387/THE_INDEX_FILE_SEARCH/security/advisories/new)**
(the repository's Security tab → "Report a vulnerability"). Do not open a public issue for them.

Say what you found, how to reproduce it, and what an attacker could do with it. You will get a reply on the
advisory; fixes are released as a new snapshot of `main` and credited to you unless you prefer otherwise.

## Supported versions

THE INDEX is pre-alpha. Only the latest `main` is supported.

## Scope notes

- `the-index serve` listens on 127.0.0.1 only and requires the token in the link it prints.
- `the-index mcp` is read-only.
- File names, titles and paths in the catalog are written by whoever made the files. Agents and pages treat
  them as data, never as instructions; a way around that is a security bug.
