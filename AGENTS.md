# AGENTS.md

## Cursor Cloud specific instructions

This is a Node.js/Express REST API for managing capital improvement projects and their routing workflows. It uses SQLite (via `better-sqlite3`) as a file-based database.

### Key commands

| Action | Command |
|--------|---------|
| Dev server (hot-reload) | `npm run dev` |
| Start server | `npm start` |
| Run tests | `npm test` |
| Lint | `npm run lint` |

### Non-obvious notes

- The `.env` file must exist before starting the server; copy from `.env.example` if missing: `cp .env.example .env`
- `DATABASE_FILE` in `.env` controls the SQLite path; defaults to `./dev.db` (auto-created on first run).
- Tests use in-memory SQLite via `jest.mock()` of `src/database.js`, so no file-based DB is created during testing.
- The server listens on `PORT` from `.env` (default 3000).
- Express 5 is used (async error handling built-in).
- `nodemon` watches `src/` for changes when using `npm run dev`.
