# Docker Integration

dlab uses Docker to provide isolated, reproducible environments for running opencode.

## How Images Are Built

When you run dlab, it builds a Docker image in two stages:

### Stage 1: Base Image

Your decision-pack's `docker/Dockerfile` is built as `{image_name}-base`:

```dockerfile
FROM python:3.11-slim
WORKDIR /workspace
RUN pip install pandas numpy
CMD ["/bin/bash"]
```

### Stage 2: Wrapper Image

dlab creates a wrapper Dockerfile that adds opencode and its dependencies:

```dockerfile
FROM {image_name}-base

RUN apt-get update && apt-get install -y git ripgrep curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN npm install -g opencode-ai@{version}
RUN opencode --version
```

The final image is tagged as `{image_name}` (from your config.yaml) and labeled with a source hash for cache invalidation.

## What Gets Installed

| Tool | Purpose |
|------|---------|
| git | Version control (used by coding agents) |
| ripgrep | Required by opencode for grep/glob/list tools |
| curl | Needed to install Node.js |
| Node.js 20.x | Required to run opencode |
| opencode | The AI coding agent |

## Image Caching

Images are cached based on a hash of the `docker/` directory contents and the `opencode_version`. A rebuild is triggered when:

- Files in `docker/` change (Dockerfile, requirements, etc.)
- The `opencode_version` in config.yaml changes
- The `--rebuild` flag is passed

```bash
# First run: builds the image
dlab --dpack ./my-dpack --data ./data --prompt "Test"
# [1/4] Setting up environment
#       Building image: my-dpack-img

# Second run: uses cached image
dlab --dpack ./my-dpack --data ./data --prompt "Test"
# [1/4] Setting up environment
#       Image: my-dpack-img (cached)
```

### Dangling Images

When an image is rebuilt, the old image becomes "dangling" (untagged). dlab cleans up the immediately previous image, but older dangling images from failed builds may accumulate. The CLI warns when dangling images exist:

```
      Warning: 3 dangling Docker image(s) using disk space
      Clean up with: docker image prune -f
```

## Container Lifecycle

### Starting

Containers run in detached mode with the work directory mounted:

```bash
docker run -d \
    --name {session-name} \
    -v {work_dir}:/workspace \
    -v {work_dir}/_opencode_logs:/_opencode_logs \
    -w /workspace \
    [--env-file {env_file}] \
    {image_name} \
    tail -f /dev/null
```

### Executing

Commands run via `docker exec`:

```bash
# Hooks
docker exec {container} bash -c "/workspace/_hooks/deploy_modal.sh"

# opencode
docker exec {container} opencode run --model {model} --prompt "{prompt}"
```

### File Ownership

Files created inside the container are owned by root. Before stopping, dlab runs `chown` inside the container to fix ownership:

```bash
docker exec {container} chown -R {uid}:{gid} /workspace /_opencode_logs
```

### Stopping

Containers are stopped and removed when:
1. **Normal completion**: opencode finishes
2. **Error**: opencode crashes
3. **Interrupt**: Ctrl+C (SIGINT)
4. **Termination**: SIGTERM

Signal handlers ensure cleanup even on interrupts.

## Volume Mounts

| Host Path | Container Path | Purpose |
|-----------|----------------|---------|
| `{work_dir}` | `/workspace` | Session data, config, hooks |
| `{work_dir}/_opencode_logs` | `/_opencode_logs` | Log output |

## Environment Variables

The `--env-file` flag passes an environment file to the container via Docker's `--env-file` flag. If not specified, the CLI auto-detects a `.env` file in the decision-pack directory.

For Modal integration, Modal credentials are also loaded from the env file into the host environment for `modal deploy` commands.

## Troubleshooting

### Build fails

```bash
# Test building manually
cd my-dpack/docker
docker build -t test .
```

### Disk full

Docker images can be large. Check space:
```bash
docker system df
docker image prune -f  # Remove dangling images
```

### Orphaned containers

```bash
docker ps -a              # List all containers
docker rm -f {name}       # Remove specific
docker container prune    # Remove all stopped
```

### Permission errors on session files

If a session was interrupted before the chown cleanup:
```bash
sudo chown -R $(id -u):$(id -g) ./analysis-001
```

## Advanced: Custom Base Images

Any base image that supports apt-get works:

```dockerfile
FROM ubuntu:22.04
FROM debian:bookworm-slim
FROM python:3.11-slim
FROM continuumio/miniconda3:latest
```

For images without apt-get (Alpine, etc.), pre-install git, ripgrep, and Node.js in your Dockerfile.
