# Contributing to Cadencia

Thank you for your interest in contributing to Cadencia.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/<your-username>/cadencia-magic-wallet.git`
3. Follow the setup guide in `README.md` (Local Development Setup section)
4. Create a feature branch: `git checkout -b feature/your-feature`

## Development Workflow

1. Make your changes in the feature branch
2. Run tests locally (see `TESTING.md` for commands)
3. Ensure linting passes: `cd backend && ruff check src/`
4. Commit with a descriptive message following conventional commits:
   - `feat:` for new features
   - `fix:` for bug fixes
   - `docs:` for documentation
   - `test:` for test additions
   - `refactor:` for code restructuring
5. Push to your fork and open a Pull Request

## Code Style

- **Backend**: Python 3.12, formatted with Ruff, type hints encouraged
- **Frontend**: TypeScript, formatted with ESLint + Prettier
- **Commits**: Conventional commit messages

## Architecture

The backend follows Hexagonal Architecture (Ports and Adapters). Each domain module under `backend/src/` has:
- `api/` — FastAPI routers (inbound adapters)
- `application/` — Use case services
- `domain/` — Pure domain models and business logic
- `infrastructure/` — ORM models, repositories, external adapters

Do not introduce cross-domain imports between `domain/` layers.

## Testing

See `TESTING.md` for the complete testing guide. All PRs should include tests for new functionality.

## Reporting Issues

Use the GitHub issue templates for bug reports and feature requests.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
