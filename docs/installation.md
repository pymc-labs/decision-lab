# Installation

## Requirements

- **Python 3.10+**
- **Docker** — must be installed and running
- **API Keys** — for the LLM provider you want to use (e.g., `OPENCODE_API_KEY`)

## Install from Source

```bash
git clone <repo-url>
cd decision-lab
pip install -e ".[dev]"
```

## Verify Installation

```bash
# Check CLI is available
dlab --help

# Check Docker is running
docker info
```

## Getting Started

The easiest way to get started is the interactive wizard:

```bash
dlab create-dpack
```

This creates a complete decision-pack directory with Dockerfile, config, agent prompts, and a `.env.example` with the required API keys.

## Environment Variables

API keys are passed to the Docker container via `--env-file`. The create-dpack wizard generates a `.env.example` with the required keys for your chosen model:

```bash
# Copy and fill in your keys
cp my-dpack/.env.example my-dpack/.env

# The CLI auto-detects .env in the decision-pack directory
dlab --dpack ./my-dpack --data ./data --prompt "Analyze"
```

## Platform Support

| Platform | Status |
|----------|--------|
| Linux | Supported |
| macOS | Supported |
| Windows | WSL2 recommended |

## Docker Setup

### Linux

```bash
sudo apt-get update
sudo apt-get install docker.io
sudo systemctl start docker
sudo usermod -aG docker $USER  # Run Docker without sudo
# Log out and back in
```

### macOS

Install [Docker Desktop for Mac](https://docs.docker.com/desktop/install/mac-install/).

### Windows

Install [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/) with WSL2 backend.

## Troubleshooting

### Docker daemon not running

```
Error: Cannot connect to the Docker daemon
```

Start Docker Desktop or the Docker service:
```bash
sudo systemctl start docker  # Linux
```

### Permission denied

```bash
sudo usermod -aG docker $USER
# Log out and back in
```

### Image build fails

```bash
# Test building manually
docker build -t test ./path/to/dpack/docker/
```
