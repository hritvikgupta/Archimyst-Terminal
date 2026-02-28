# 🌌 ArchCode Terminal CLI
### *The Council of Agents for Your Codebase*

[![Release](https://img.shields.io/badge/release-v1.0.9-blue.svg)](https://github.com/hritvikgupta/Archimyst)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-yellow.svg)](https://www.python.org/)

ArchCode Terminal is a professional-grade AI CLI designed for instant understanding and coordinated modifications across million-line codebases. It orchestrates a **Council of Agents** powered by world-class LLMs, high-fidelity symbol indexing, and a versatile Skill system.

---

## 🚀 Quick Start

Get ArchCode up and running in seconds with our one-liner installer:

```bash
curl -fsSL https://www.archimyst.com/install.sh | bash
```

*This script detects your OS/Architecture, installs dependencies like `ripgrep`, sets up the environment, and adds `archcode` to your PATH.*

---

## ✨ Key Features

- **🧠 Council of Agents**: Specialized agents (Supervisor, Coder, Reviewer, Executor) working together to solve complex tasks.
- **🔍 Deep Code Indexing**: High-fidelity AST parsing using `tree-sitter` and semantic search with `voyage-code-3` embeddings.
- **🛠️ Extensible Skills**: Native support for Model Context Protocol (MCP) and a modular Skill Manager to extend functionality.
- **🔒 Private Mode**: Use your own API keys (OpenRouter/OpenAI/Anthropic) for zero token limits and maximum privacy—no usage data is stored.
- **⚡ Performance First**: Local vector storage with `Qdrant` (in-memory persistent mode) for lightning-fast retrieval without Docker overhead.

---

## ⚙️ Configuration

ArchCode is flexible. You can use our managed backend or bring your own keys.

### 1. Environment Variables
Add your keys to your `.env` file in the project root:

```env
# Primary AI Provider (OpenRouter recommended for 200+ models)
OPENROUTER_API_KEY=sk-or-...

# Semantic Search (Required for deep indexing)
VOYAGE_API_KEY=your_voyage_key_here

# Optional Direct Providers
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
TAVILY_API_KEY=tvly-...
```

### 2. In-CLI Configuration
Manage your setup directly from the terminal:
- `/login`: Sync with your Archimyst account.
- `/config`: Open interactive configuration manager.
- `/model`: Switch between optimized models on the fly.

---

## 📖 Usage Guide

After installation, simply run:
```bash
archcode
```

### Core Commands
- `/index`: Recursively index the current directory for semantic search.
- `/connect`: Install new skills or MCP servers.
- `/reset`: Clear the current session history and context.
- `/help`: Show all available commands and agents.

### Example Interaction
> **User:** "Explain how the authentication flow works in the backend."
>
> **Supervisor:** *Coordinates with the Coder to search symbols, analyzes `auth_logic.py`, and provides a step-by-step walkthrough.*

---

## 🏗️ Architecture

- **Embeddings**: `voyage-code-3` — Optimized for code understanding.
- **Symbol Extraction**: `tree-sitter` — High-fidelity parsing of `.py`, `.js`, `.ts`, `.tsx`, `.go`, and more.
- **Vector Engine**: `Qdrant` — Fast similarity search with local persistence.
- **Agent Framework**: Built on a custom orchestration layer for low-latency multi-agent collaboration.

---

## 🤝 Contributing

We welcome contributions! To get started:

1. **Clone the repo**: `git clone https://github.com/hritvikgupta/Archimyst`
2. **Setup Venv**: `python3 -m venv venv && source venv/bin/activate`
3. **Install Deps**: `pip install -r requirements.txt`
4. **Run Tests**: `pytest backend/archcode-terminal/archcode-cli/`

Please read our [Contribution Guidelines](CONTRIBUTING.md) for more details.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

Built with ❤️ by the **Archimyst** team.
