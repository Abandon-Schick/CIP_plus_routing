# Project Structure

## Directory Layout

## Directory Descriptions

### `/src`
Contains all source code for the project. Organized by modules for maintainability.

### `/tests`
Contains test suites including:
- **unit/** - Unit tests for individual components
- **integration/** - Integration tests for system components

### `/docs`
Documentation including setup guides, API references, and project structure information.

### `/config`
Environment-specific configuration files:
- `development.json` - Local development settings
- `test.json` - Test environment settings
- `production.json` - Production environment settings

### `/.github`
GitHub-specific files including CI/CD workflow definitions.

## Naming Conventions

- Files: Use lowercase with hyphens (e.g., `api-handler.js`)
- Directories: Use lowercase (e.g., `src/modules/`)
- Constants: Use UPPERCASE with underscores (e.g., `MAX_RETRIES`)
- Functions: Use camelCase (e.g., `getUserData()`)
- Classes: Use PascalCase (e.g., `UserManager`)

## Development Workflow

1. Create feature branches from `main`
2. Add code to `/src`
3. Add tests to `/tests`
4. Update documentation in `/docs`
5. Submit pull request for review
