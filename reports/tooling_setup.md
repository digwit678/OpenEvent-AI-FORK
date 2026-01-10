# Second-Pass Audit Toolchain Setup Report

**Generated:** 2026-01-10
**Environment:** macOS Darwin 24.6.0 (arm64) / zsh

---

## 1. Detected Stack

### Operating System & Shell
| Component | Value |
|-----------|-------|
| OS | macOS Darwin 24.6.0 (arm64) |
| Shell | /bin/zsh |
| Architecture | ARM64 (Apple Silicon) |

### Package Managers
| Manager | Version | Status |
|---------|---------|--------|
| Homebrew | 5.0.9 | Available |
| pip3 | 25.3 (Python 3.9.6) | Available |
| pipx | 1.8.0 | Installed |
| npm | 11.6.2 (Node v25.2.1) | Available |
| Docker | - | Not installed |
| Go | - | Not installed |
| Cargo | - | Not installed |

### Repository Tech Stack

#### Python Backend (FastAPI)
- **Framework:** FastAPI >= 0.104.0
- **Server:** uvicorn >= 0.24.0
- **Data Validation:** pydantic >= 2.0.0
- **LLM Integration:** openai >= 1.0.0, google-genai >= 0.1.0
- **Testing:** pytest, pytest-cov, freezegun, faker, hypothesis
- **Type Hints:** Present (using `typing` module)
- **Package Format:** requirements.txt (no pyproject.toml)

#### TypeScript/React Frontend (Next.js)
- **Framework:** Next.js 15.5.4 (with Turbopack)
- **React:** 19.1.0
- **Styling:** Tailwind CSS 4
- **Testing:** Vitest 4.0.7, @testing-library/react
- **TypeScript:** 5.x (strict mode enabled)
- **Build:** next build
- **Linting:** No ESLint configured (opportunity for improvement)

#### CI/CD (GitHub Actions)
- `ci-smoke.yml` - Runs pytest smoke tests on feature branches
- `agent-canary.yml` - Agent testing workflow
- `sdk-probe.yml` - SDK probing workflow
- `workflow-tests.yml` - Workflow-specific tests

### Existing Quality Tools (Pre-installed)
| Tool | Version | Purpose |
|------|---------|---------|
| pyright | 1.1.407 | Python type checking |
| pytest | (in requirements-dev.txt) | Python testing |
| vitest | 4.0.7 | Frontend testing |
| TypeScript | 5.x | Type checking |

---

## 2. Tooling Selected & Installed

### A. Secrets Scanning
| Tool | Version | Install Method | Purpose |
|------|---------|----------------|---------|
| gitleaks | 8.30.0 | brew | Scan for secrets in git history and files |

### B. Dependency Vulnerability Scanning
| Tool | Version | Install Method | Purpose |
|------|---------|----------------|---------|
| pip-audit | 2.10.0 | pipx | Python dependency vulnerability scanning |
| npm audit | (built-in) | npm | Node.js dependency vulnerability scanning |

### C. Static Security Analysis (SAST)
| Tool | Version | Install Method | Purpose |
|------|---------|----------------|---------|
| semgrep | 1.146.0 | brew | Multi-language SAST with file/line evidence |
| bandit | 1.9.2 | pipx | Python-specific security linter |

### D. Linting & Type Checking
| Tool | Version | Install Method | Purpose |
|------|---------|----------------|---------|
| ruff | 0.14.11 | brew | Ultra-fast Python linter (replaces flake8/isort) |
| pyright | 1.1.407 | (pre-installed) | Python type checking |

### E. Not Installed (Not Applicable)
| Tool | Reason |
|------|--------|
| trivy | No Dockerfiles or container configs found |
| terraform validate | No Terraform/IaC files found |
| eslint | Frontend has no ESLint config; could be added later |
| trufflehog | gitleaks covers secrets scanning needs |
| osv-scanner | pip-audit + npm audit provide sufficient coverage |

---

## 3. MCP/Plugin Configuration

### Claude Code MCP Servers (Active)
| Server | Purpose | Status |
|--------|---------|--------|
| mcp:refactor | Code search and refactoring | Working |
| mcp:ide | IDE diagnostics | Timeout (requires LSP) |
| plugin:playwright:playwright | Browser automation | Available |
| plugin:context7:context7 | Documentation lookup | Available |

### Claude Code Plugins
| Plugin | Status |
|--------|--------|
| code-simplifier@claude-plugins-official | Enabled |

### LSP Configuration (.claude/lsp.json)
```json
{
  "servers": {
    "python": {
      "command": "pyright-langserver",
      "args": ["--stdio"],
      "extensions": [".py"]
    }
  }
}
```

---

## 4. Codex CLI Configuration

### Global Config (~/.codex/config.toml)
| Setting | Value | Required |
|---------|-------|----------|
| model | gpt-5.2-codex | Already correct |
| model_reasoning_effort | xhigh | Already correct |
| sandbox_mode | workspace-write | - |
| approval_policy | on-failure | - |

### Project Trust Level
The project `/Users/nico/PycharmProjects/OpenEvent-AI` is set to `trusted`.

### Codex MCP Servers
| Server | Purpose |
|--------|---------|
| filesystem | File system access |
| context7 | Documentation lookup |
| lsp | Language Server Protocol (pyright) |
| playwright | Browser automation |

---

## 5. Usage Commands

### Run All Audit Tools

```bash
# Secrets scanning (entire repo)
gitleaks detect --source . --redact

# Python dependency vulnerabilities
pip-audit -r requirements.txt

# Node dependency vulnerabilities
cd atelier-ai-frontend && npm audit

# Python SAST (security issues)
bandit -r . -x ./atelier-ai-frontend,./DEPRECATED,./.npm-cache

# Multi-language SAST
semgrep scan --config auto .

# Python linting
ruff check .

# Python type checking
pyright .

# Frontend type checking
cd atelier-ai-frontend && npx tsc --noEmit
```

### Quick Smoke Test
```bash
# Run existing pytest smoke suite
./scripts/tests/test-smoke.sh

# Run frontend tests
cd atelier-ai-frontend && npm test
```

---

## 6. Blockers & Missing Items

### Blockers
None identified.

### Potential Improvements (Not Blockers)
| Item | Description | Priority |
|------|-------------|----------|
| ESLint for frontend | No ESLint config in `atelier-ai-frontend/` | Low |
| IDE diagnostics timeout | MCP IDE diagnostics timed out; may need LSP running | Low |
| npm audit fix | 1 critical vulnerability in Next.js 15.5.4 (upgrade to 15.5.9 available) | Medium |

### Notes
- All tools installed at user level (no sudo required)
- Codex CLI config already meets requirements (gpt-5.2-codex, xhigh reasoning)
- gitleaks detected 21 potential secrets - review recommended but may include false positives
- Package-lock.json was generated for npm audit support

---

## 7. Verification Checklist

- [x] gitleaks installed and working
- [x] pip-audit installed and working
- [x] npm audit working (package-lock.json generated)
- [x] semgrep installed and working
- [x] bandit installed and working
- [x] ruff installed and working
- [x] pyright pre-installed and working
- [x] pipx installed for Python CLI tools
- [x] Codex CLI functional (v0.79.0)
- [x] Codex config correct (gpt-5.2-codex, xhigh)
- [x] Claude Code MCP servers available
