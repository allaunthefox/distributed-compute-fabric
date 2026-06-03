# Contributing to GGUF-Ray-VCN-LUPINE

**Version:** 1.0.0  
**Last Updated:** 2026-06-01

---

## Overview

Thank you for your interest in contributing to GGUF-Ray-VCN-LUPINE! This document provides guidelines for contributing to the project.

---

## Getting Started

### Prerequisites

Before you can contribute, ensure you have the following installed:

- **Python** 3.11 or higher
- **Docker** 24.x or higher
- **Kubernetes** (k3s, minikube, or other distribution)
- **Helm** 3.14 or higher
- **Ray** 2.9.0 or higher
- **Tailscale** 1.6.x or higher
- **Git**
- **curl**

### Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-org/gguf-ray-vcn-lupine.git
   cd gguf-ray-vcn-lupine
   ```

2. **Set up Python environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```

3. **Set up Kubernetes for local development:**
   ```bash
   # Option 1: minikube (single node)
   minikube start --driver=docker --cpus=4 --memory=8g
   
   # Option 2: k3d (multi-node)
   k3d cluster create mycluster --agents=3 --servers=1
   
   # Option 3: k3s (production-like)
   # See deployment documentation
   ```

4. **Install dependencies:**
   ```bash
   # Install Ray
   pip install "ray[default]"
   
   # Install other dependencies
   pip install fastapi uvicorn gunicorn
   pip install prometheus-client opentelemetry-api opentelemetry-sdk
   ```

---

## Development Workflow

### Making Changes

1. **Create a feature branch:**
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Make your changes:**
   - Follow code style guidelines (see below)
   - Add tests for new functionality
   - Update documentation as needed

3. **Run tests:**
   ```bash
   pytest tests/ -v
   ```

4. **Run linting:**
   ```bash
   pre-commit run --all-files
   ```

5. **Commit your changes:**
   ```bash
   git add .
   git commit -m "Add my feature"
   ```
   - Use clear, descriptive commit messages
   - Follow [Conventional Commits](https://www.conventionalcommits.org/) format
   - Reference relevant issues (e.g., "Fixes #123")

6. **Push to the branch:**
   ```bash
   git push origin feature/my-feature
   ```

7. **Open a Pull Request:**
   - Use the GitHub Pull Request template
   - Include a clear description of changes
   - Link to relevant issues
   - Include screenshots if UI changes
   - Request review from appropriate team members

---

## Pull Request Process

1. **Ensure all tests pass:**
   ```bash
   pytest tests/ -v --cov=code --cov-report=term
   ```

2. **Ensure code is properly linted:**
   ```bash
   pre-commit run --all-files
   ```

3. **Include a clear description:**
   - What problem does this PR solve?
   - What changes were made?
   - How was it tested?
   - Any breaking changes?

4. **Link to relevant issues:**
   - Reference the issue number in the PR description
   - Use "Fixes #123" or "Resolves #123" if applicable

5. **Wait for code review:**
   - Address all feedback from reviewers
   - Push changes as additional commits (not force push)
   - Request re-review when ready

6. **Merge when approved:**
   - Ensure CI passes
   - Squash and merge (preferred)
   - Or rebase and merge

---

## Code Style Guidelines

### Python

- **Follow PEP 8:** Use consistent indentation, spacing, and naming
- **Type Hints:** Use type hints for all function parameters and return values
- **String Formatting:** Use f-strings instead of .format() or % formatting
- **Imports:** Group imports (stdlib, third-party, local) with blank lines between
- **Naming:**
  - Variables and functions: `snake_case`
  - Classes: `PascalCase`
  - Constants: `UPPER_SNAKE_CASE`
  - Private: `_leading_underscore`
  - Protected: `_single_leading_underscore` (convention)
  - Private: `__double_leading_underscore` (name mangling)
- **Docstrings:** Use Google-style docstrings for all public functions and classes
- **Line Length:** Maximum 88 characters (PEP 8 default)
- **Quotes:** Use single quotes for strings, double quotes for strings containing single quotes

### Kubernetes

- **Naming:** Use kebab-case for resource names (e.g., `ray-cluster`, `hermes-api`)
- **Labels:** Use consistent labels for resource selection
- **Annotations:** Use annotations for non-identifying metadata
- **Indentation:** Use 2 spaces for YAML indentation
- **Comments:** Use `#` for comments in YAML files
- **Health Checks:** Always include liveness and readiness probes
- **Resource Limits:** Always set resource requests and limits
- **ConfigMaps/Secrets:** Use ConfigMaps for configuration, Secrets for sensitive data

### Markdown

- **Headings:** Use ATX-style headings (e.g., `# Heading`, `## Subheading`)
- **Lists:** Use hyphens for unordered lists, numbers for ordered lists
- **Code Blocks:** Use triple backticks with language specification
- **Links:** Use descriptive link text
- **Images:** Include alt text
- **Tables:** Use pipes and hyphens for table formatting

---

## Testing

### Unit Tests

All new functionality should be covered by unit tests.

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_actors.py

# Run specific test
pytest tests/test_actors.py::test_coder_actor

# Run with coverage
pytest --cov=code tests/

# Run with verbose output
pytest -v tests/

# Run only failed tests
pytest --lf tests/
```

### Integration Tests

Integration tests verify that components work together correctly.

```bash
# Run integration tests
pytest tests/integration/

# Test full deployment
kubectl apply -f kubernetes/
```

### Load Tests

Load tests verify performance under load.

```bash
# Install Locust
pip install locust

# Run load tests
locust -f tests/locustfile.py --host=https://api.yourdomain.com

# Run headless
locust -f tests/locustfile.py --host=https://api.yourdomain.com --headless --users=50 --spawn-rate=10
```

---

## Code of Conduct

We expect all contributors to follow our Code of Conduct. Be respectful, inclusive, and professional in all interactions.

---

## Architecture Decision Records (ADRs)

Significant architectural decisions are documented in `docs/adr/`.

### Creating a New ADR

1. Create a new file `docs/adr/ADR-00X-title.md` (use next available number)
2. Use the ADR template (see `docs/adr/ADR-TEMPLATE.md`)
3. Document:
   - **Title**: Short descriptive title
   - **Status**: Proposed, Accepted, Rejected, Deprecated, Superseded
   - **Context**: The problem being solved
   - **Decision**: The chosen solution
   - **Consequences**: Positive and negative consequences
   - **Alternatives**: Other options considered
4. Submit for review via Pull Request

---

## Versioning

This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html):

- **MAJOR**: Breaking changes, incompatible API changes
- **MINOR**: New features, backwards compatible
- **PATCH**: Bug fixes, backwards compatible

### Release Process

1. **Update version:**
   - Update `pyproject.toml`
   - Update `__version__` in relevant files

2. **Update CHANGELOG:**
   - Document all changes since last release
   - Group by type (Added, Changed, Fixed, Deprecated, Removed, Security)

3. **Create Git tag:**
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```

4. **Create GitHub Release:**
   - Use the GitHub Releases page
   - Include release notes
   - Attach any binaries or assets

5. **Deploy to production:**
   - Update deployment manifests if needed
   - Apply changes to production cluster

---

## Reporting Issues

When reporting issues, please include the following information:

1. **Description:** Clear description of the issue
2. **Steps to Reproduce:** Detailed steps to reproduce the issue
3. **Expected Behavior:** What you expected to happen
4. **Actual Behavior:** What actually happened
5. **Screenshots:** If applicable
6. **Logs:** Relevant log output
7. **Environment:**
   - Python version
   - Ray version
   - Kubernetes version
   - OS
   - Hardware
   - Any other relevant information

---

## Getting Help

- **Documentation:** See `docs/` directory
- **API Documentation:** See `docs/API.md`
- **Architecture:** See `docs/ARCHITECTURE.md`
- **Issues:** Check existing issues on GitHub
- **Discussions:** Join the discussion on GitHub Discussions
- **Email:** Contact the maintainers at maintainers@yourdomain.com

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

---

*Thank you for contributing to GGUF-Ray-VCN-LUPINE!*
