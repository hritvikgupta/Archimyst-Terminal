# Security Policy

## Supported Versions

The following versions of ArchCode Terminal CLI are currently supported with security updates:

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability, please report it responsibly.

### How to Report

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, report them via:

- **Email**: [security@archimyst.com](mailto:security@archimyst.com)
- **Encrypted Email**: PGP key available upon request

### What to Include

Your report should include:

1. **Description**: Clear description of the vulnerability
2. **Impact**: What could an attacker accomplish?
3. **Steps to Reproduce**: Detailed instructions to reproduce the issue
4. **Affected Versions**: Which versions are impacted
5. **Environment**: OS, Python version, dependencies
6. **Proof of Concept**: If applicable, provide minimal code demonstrating the issue
7. **Suggested Fix**: If you have ideas for remediation

### Response Timeline

We aim to respond to security reports within:

- **24 hours**: Initial acknowledgment
- **72 hours**: Initial assessment and next steps
- **7 days**: Fix or mitigation plan provided
- **30 days**: Resolution or public disclosure plan

## Security Considerations

### Local Data Storage

ArchCode Terminal CLI stores the following locally:

- **Vector embeddings**: Stored in local Qdrant database (`.archcode/vector_store/`)
- **Indexed symbols**: Stored as JSON files (`.archcode/symbols/`)
- **Configuration**: Stored in environment variables or `.env` file

**Recommendations**:
- Do not commit `.archcode/` directory to version control
- Add `.archcode/` to `.gitignore`
- Protect your `.env` file with appropriate file permissions

### API Keys and Credentials

ArchCode supports multiple AI providers. When using your own API keys:

- Keys are stored in environment variables or `.env` files
- Never share your `.env` file or commit it to version control
- Use separate API keys for different environments
- Rotate keys periodically
- Monitor usage for unexpected spikes

### Code Indexing Security

When indexing a codebase:

- Only files within the project directory are indexed
- Binary files are automatically excluded
- File contents are processed locally, not sent to external services
- Embeddings are generated locally or via API depending on configuration

### Network Security

ArchCode Terminal CLI may make network connections for:

- **API calls**: To AI providers (OpenRouter, OpenAI, Anthropic) when in Private Mode
- **Embeddings**: To Voyage AI for code embeddings (if configured)
- **Updates**: Checking for CLI updates (optional)

**All connections use HTTPS/TLS encryption.**

## Security Best Practices for Users

1. **Keep dependencies updated**: Regularly update Python packages
2. **Use virtual environments**: Isolate project dependencies
3. **Review code before execution**: ArchCode may suggest shell commands - review before executing
4. **Limit file permissions**: Ensure only necessary users can read indexed code
5. **Audit indexed data**: Periodically review what's stored in `.archcode/`

## Security Features

### Private Mode

When using Private Mode with your own API keys:

- No code is sent to Archimyst servers
- API calls go directly to your chosen provider
- No usage analytics are collected
- All processing happens locally except LLM inference

### Skill Execution

Skills (MCP integrations) can execute commands:

- User confirmation is required for destructive operations
- Skills run with user's permissions
- Review skill permissions before installation

## Known Limitations

1. **Local storage**: Indexed data is stored locally and protected by OS file permissions
2. **API key exposure**: Keys in environment variables are accessible to processes with appropriate permissions
3. **Code execution**: Generated code suggestions should be reviewed before execution
4. **Network**: Internet required for AI provider API calls

## Disclosure Policy

When we receive a security report:

1. Confirm receipt and begin investigation
2. Develop and test a fix
3. Prepare a security advisory
4. Notify affected users if necessary
5. Publicly disclose after fix is available (coordinated disclosure)

## Acknowledgments

We acknowledge security researchers who responsibly disclose vulnerabilities:

- Security issues will be acknowledged in release notes
- Researchers may be credited by name if desired
- No monetary rewards currently offered (this is an educational project)

## Contact

For security-related questions or concerns:

- **Security Team**: [security@archimyst.com](mailto:security@archimyst.com)
- **General Inquiries**: [hello@archimyst.com](mailto:hello@archimyst.com)

---

This security policy is subject to change. Please refer to the latest version in the repository.
