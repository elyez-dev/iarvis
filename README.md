# iArvis

A modular, privacy-first, open-source personal AI assistant that runs entirely on your own hardware.

This my final degree project (TFG). It demonstrates that a useful personal AI assistant can be built without cloud dependencies, running on modest consumer-grade hardware.

## Motivation

Modern AI assistants (Copilot, Gemini, ChatGPT) are powerful but come with trade-offs: your data leaves your device, usage is metered, and you depend on third-party infrastructure. iArvis takes a different approach — everything runs locally, on hardware you control.

Key principles:
- **Privacy by design**: all data stays on your machine, under your control
- **Hardware-constrained first**: designed to run on a 4GB GPU (Nvidia T600) with 12-16GB RAM
- **Modular**: every component (LLM, vector DB, graph DB, frontend) is independently replaceable
- **Open source**: no black boxes, no vendor lock-in

## Architecture

```
      User
       │
  ┌────▼────┐      ┌──────────┐      ┌──────────────┐
  │ Frontend│────▶│ Backend  │────▶│  n8n (flows) │
  │Streamlit│      │ FastAPI  │      │  orchestrator│
  └─────────┘      └────┬─────┘      └──────┬───────┘
                        │                   │
               ┌────────▼────────┐   ┌──────▼───────┐
               │  Qdrant (RAG)   │   │ Ollama (LLM) │
               │  Dgraph (graph) │   │  + embeddings│
               │  PostgreSQL     │   └──────────────┘
               └─────────────────┘
```

### Stack

| Layer | Technology | Role |
|-------|-----------|------|
| Frontend | Streamlit | Chat UI with multi-session, settings, i18n |
| Backend | FastAPI + Python | API layer, business logic, DB queries |
| Orchestration | n8n | Workflow engine: routing, tool execution, LLM management |
| LLM | Ollama (Qwen2.5:3b) | Intent routing, data extraction, response generation |
| Embeddings | Ollama (nomic-embed-text) | Vector embeddings for RAG |
| Translation | Meta NLLB-200 (distilled 600M) | Multilingual support (206 languages) |
| Vector DB | Qdrant | Semantic search (RAG memory) |
| Graph DB | Dgraph | Entity relationship storage |
| Chat history | PostgreSQL | Conversation persistence |
| Security | Tailscale + LUKS | Encrypted tunnel + at-rest encryption |

## Requirements

### Hardware (recommended)
- **GPU**: NVIDIA with 4GB+ VRAM (for Ollama inference)
- **RAM**: 8GB minimum, 12-16GB recommended
- **Storage**: 30GB+ for Docker images + models + data
- **CPU**: any modern x86_64 processor

### Software
- Docker + Docker Compose plugin
- NVIDIA Container Toolkit (for GPU support)
- Optional: Tailscale (for secure remote access)
- Optional: SSH server (for headless setup)

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/elyez-dev/iarvis.git
cd iarvis
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with your settings. At minimum, update these:

- **`N8N_PUBLIC_URL`**: set to your server's address (see options below)
- **`QDRANT_API_KEY`**: generate a secure key with `openssl rand -base64 32`
- **`POSTGRES_PASSWORD`**: change the default password

#### N8N_PUBLIC_URL options

| Scenario | Example value |
|----------|--------------|
| Local only | `http://localhost:5678` |
| LAN access | `http://192.168.1.100:5678` |
| Tailscale | `http://100.x.x.x:5678` |
| Tailscale + MagicDNS | `http://server-name.tailnet-name.ts.net:5678` |

### 3. (Optional) LUKS encrypted volume

For at-rest encryption of all database files:

```bash
# Create a 100GB container file
sudo dd if=/dev/zero of=/var/lib/iarvis-secure.img bs=1M count=102400

# Encrypt with LUKS2
sudo cryptsetup luksFormat --type luks2 /var/lib/iarvis-secure.img

# Open and format
sudo cryptsetup open /var/lib/iarvis-secure.img iarvis-secure
sudo mkfs.ext4 /dev/mapper/iarvis-secure
sudo mount /dev/mapper/iarvis-secure /mnt/iarvis-secure

# Create data directories
mkdir -p /mnt/iarvis-secure/{qdrant-data,dgraph-data,postgres-data,ollama-data,n8n}

# Create symlinks in project root
ln -s /mnt/iarvis-secure/qdrant-data qdrant-data
ln -s /mnt/iarvis-secure/dgraph-data dgraph-data
ln -s /mnt/iarvis-secure/postgres-data postgres-data
ln -s /mnt/iarvis-secure/ollama-data ollama-data
ln -s /mnt/iarvis-secure/n8n n8n
```

After each reboot, re-mount before starting:

```bash
sudo cryptsetup open /var/lib/iarvis-secure.img iarvis-secure
sudo mount /dev/mapper/iarvis-secure /mnt/iarvis-secure
```

### 4. Start the infrastructure

```bash
docker compose up -d --build
```

### 5. Download LLM models

```bash
docker exec iarvis_ollama ollama pull qwen2.5:3b
docker exec iarvis_ollama ollama pull nomic-embed-text:latest
```

### 6. Initialize the Dgraph schema

```bash
docker cp scripts/init_dgraph_schema.py iarvis_backend:/tmp/init_schema.py
docker exec -w /app iarvis_backend python /tmp/init_schema.py
```

### 7. Import n8n workflows

Open `http://<your-server>:5678` in a browser, create a local account, and import the workflow JSONs from the `workflows/` directory one by one using the n8n UI:

- `iarvis_main.json` — main chat orchestration
- `iarvis_data_store.json` — memory storage (archivist)
- `iarvis_data_search.json` — memory retrieval (librarian)
- `iarvis_tool_router.json` — tool selection
- `iarvis_tool_send_email.json` — email tool
- `iarvis_tool_create_calendar_event.json` — calendar tool

### 8. Verify

```bash
docker compose ps
```

All services should show `(healthy)`. Then open `http://<your-server>:8501` to access the chat interface and send a test message. The first message will be slower as models load into VRAM.

## Usage

### Frontend
- **Chat**: send messages and receive AI responses
- **Multi-session**: create, rename, and delete conversations
- **Settings**: change assistant name, tone, language, theme (light/dark)
- **Memory management**: delete all stored data at once

### Memory
iArvis uses two complementary memory systems:
- **RAG (Qdrant)**: semantic vector search — retrieves facts by meaning
- **Knowledge Graph (Dgraph)**: structured entity relationships — answers "who", "where", "what" queries

The system stores facts when you provide information and retrieves them when you ask.

### Tools
iArvis can execute external actions via n8n workflows. Default tools include email and calendar integration. Custom tools can be added via `backend/config/tools_registry.json` and n8n workflows.

## Administration

### Changing the LLM model

1. Pull the new model: `docker exec iarvis_ollama ollama pull <model-name>`
2. In n8n UI, update each workflow's Ollama Chat Model node to use the new model
3. If using a different embedding model, update `EMBEDDING_MODEL` in `.env`

### Adding custom tools

1. Register the tool in `backend/config/tools_registry.json` (follow existing examples)
2. Create an n8n workflow with a Webhook trigger at `http://n8n:5678/webhook/<tool_id>`
3. The backend will route tool requests automatically

### Running tests

```bash
# Unit tests
python -m pytest backend/tests/unit/

# End-to-end tests (requires full stack running)
bash scripts/run_e2e_tests.sh
```

## License

The iArvis source code is available under the Apache 2.0 license. However, models downloaded at runtime have their own licenses:

- **Qwen2.5**: Apache 2.0 — commercial OK
- **nomic-embed-text**: Apache 2.0 — commercial OK
- **NLLB-200**: CC-BY-NC 4.0 — academic/non-commercial only (replaceable)
- **n8n**: Sustainable Use License — free for self-hosted use

## Project status

This is a final degree project (TFG). It is fully functional but not actively maintained. Feel free to fork and adapt.
