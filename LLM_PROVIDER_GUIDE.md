# LLM Provider Configuration Guide

## Overview

The IFSP application now supports multiple LLM providers through a flexible configuration system. You can easily switch between local (Nollama, OpenVINO), cloud (OpenAI), or custom OpenAI-compatible APIs.

## Supported Providers

### 1. **Nollama** (Default - Local Development)
- **Use Case**: Local development, testing, low-latency requirements
- **API Format**: OpenAI-compatible v1 API
- **Authentication**: None required
- **Cost**: Free (self-hosted)

**Configuration:**
```bash
LLM_PROVIDER=nollama
NOLLAMA_BASE_URL=http://localhost:8000
NOLLAMA_MODEL=qwen2@GPU
```

**Requirements:**
- Nollama service running at `http://localhost:8000`
- No API key needed

---

### 2. **OpenVINO** (Optimized Local - GPU/CPU)
- **Use Case**: High-performance local inference with GPU/CPU acceleration
- **API Format**: Direct Python library (not HTTP)
- **Authentication**: None required
- **Cost**: Free (self-hosted, offline)
- **Performance**: Optimized with latency/throughput hints

**Configuration:**
```bash
LLM_PROVIDER=openvino
OPENVINO_MODEL_PATH=./DeepSeek-R1-Distill-Qwen-7B-int4-ov
OPENVINO_DEVICE=GPU  # GPU, CPU, or NPU
OPENVINO_PERFORMANCE_HINT=LATENCY  # LATENCY or THROUGHPUT
OPENVINO_NUM_STREAMS=1  # For THROUGHPUT mode
OPENVINO_MODEL=deepseek-r1-distill-qwen-7b
```

**Requirements:**
- OpenVINO Runtime installed: `pip install openvino-genai`
- Quantized model files (e.g., DeepSeek-R1-Distill-Qwen-7B-int4-ov)
- GPU drivers (optional, for GPU acceleration)
- Minimum 8GB RAM recommended

**Setup Steps:**
1. Install OpenVINO: `pip install openvino-genai`
2. Download or prepare quantized model
3. Set `LLM_PROVIDER=openvino`
4. Set `OPENVINO_MODEL_PATH=/path/to/model`
5. Restart the application

**Performance Tuning:**
```bash
# For latency-sensitive applications (default)
OPENVINO_PERFORMANCE_HINT=LATENCY
OPENVINO_DEVICE=GPU

# For throughput (batch processing)
OPENVINO_PERFORMANCE_HINT=THROUGHPUT
OPENVINO_NUM_STREAMS=4
OPENVINO_DEVICE=GPU
```

**Advantages:**
- 🚀 GPU acceleration (2-10x faster than CPU)
- 🔒 Complete offline operation
- 💰 Zero operational cost
- 🎯 Precise latency control
- 📊 Quantized models use less memory

---

### 3. **OpenAI** (Production Cloud)
- **Use Case**: Production environments, highest quality models
- **API Format**: OpenAI v1 API with authentication
- **Authentication**: API key required
- **Cost**: Pay-per-token (See OpenAI pricing)

**Configuration:**
```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4
OPENAI_JUDGE_MODEL=gpt-4
OPENAI_VISION_MODEL=gpt-4-vision-preview
```

**Requirements:**
- OpenAI API key (from https://platform.openai.com/api-keys)
- Active OpenAI account with billing enabled
- Internet connectivity

**Setup Steps:**
1. Get your API key from OpenAI platform
2. Set `LLM_PROVIDER=openai`
3. Set `OPENAI_API_KEY=sk-...`
4. Restart the application

---

### 3. **Custom OpenAI-Compatible APIs** (Flexible Production)
- **Use Case**: Azure OpenAI, Anthropic Claude via proxy, LM Studio, other compatible APIs
- **API Format**: OpenAI-compatible v1 API
- **Authentication**: Depends on provider
- **Cost**: Varies by provider

**Configuration:**
```bash
LLM_PROVIDER=custom
CUSTOM_LLM_BASE_URL=https://your-provider.com/v1
CUSTOM_LLM_API_KEY=your-api-key
CUSTOM_LLM_MODEL=model-name
```

**Examples:**

**Azure OpenAI:**
```bash
LLM_PROVIDER=custom
CUSTOM_LLM_BASE_URL=https://{resource-name}.openai.azure.com/v1
CUSTOM_LLM_API_KEY=your-azure-api-key
CUSTOM_LLM_MODEL=your-deployment-name
```

**LM Studio (Local):**
```bash
LLM_PROVIDER=custom
CUSTOM_LLM_BASE_URL=http://localhost:1234/v1
CUSTOM_LLM_MODEL=local-model
```

**Anthropic Claude via Proxy:**
```bash
LLM_PROVIDER=custom
CUSTOM_LLM_BASE_URL=https://your-claude-proxy.com/v1
CUSTOM_LLM_API_KEY=your-proxy-api-key
CUSTOM_LLM_MODEL=claude-3-opus
```

---

## Environment Variable Reference

| Variable | Provider | Required | Default | Description |
|----------|----------|----------|---------|-------------|
| `LLM_PROVIDER` | All | Yes | `nollama` | Which provider to use: `nollama`, `openai`, `custom`, `openvino` |
| `JUDGE_LLM_ENABLED` | All | No | `true` | Enable/disable LLM-based output judging |
| `NOLLAMA_BASE_URL` | Nollama | No | `http://localhost:8000` | Nollama service URL |
| `NOLLAMA_MODEL` | Nollama | No | `qwen2@GPU` | Model name to use |
| `OPENVINO_MODEL_PATH` | OpenVINO | **Yes** | - | Path to quantized model (required if LLM_PROVIDER=openvino) |
| `OPENVINO_DEVICE` | OpenVINO | No | `GPU` | Device: GPU, CPU, or NPU |
| `OPENVINO_PERFORMANCE_HINT` | OpenVINO | No | `LATENCY` | Performance mode: LATENCY or THROUGHPUT |
| `OPENVINO_NUM_STREAMS` | OpenVINO | No | `1` | Number of streams for THROUGHPUT mode |
| `OPENVINO_MODEL` | OpenVINO | No | - | Model identifier |
| `OPENAI_API_KEY` | OpenAI | **Yes** | - | OpenAI API key (required if LLM_PROVIDER=openai) |
| `OPENAI_BASE_URL` | OpenAI | No | `https://api.openai.com/v1` | OpenAI API endpoint |
| `OPENAI_MODEL` | OpenAI | No | `gpt-4` | Model to use |
| `CUSTOM_LLM_BASE_URL` | Custom | **Yes** | - | Custom provider API endpoint (required if LLM_PROVIDER=custom) |
| `CUSTOM_LLM_API_KEY` | Custom | No | - | Custom provider API key (if needed) |
| `CUSTOM_LLM_MODEL` | Custom | **Yes** | - | Model name at custom provider (required if LLM_PROVIDER=custom) |

---

## Production Migration Checklist

### Development → Production (Nollama → OpenAI)

- [ ] **Get OpenAI API Key**
  - Visit https://platform.openai.com/api-keys
  - Create new API key
  - Store securely (use secrets manager in production)

- [ ] **Update Configuration**
  ```bash
  LLM_PROVIDER=openai
  OPENAI_API_KEY=sk-your-key
  ```

- [ ] **Test Connectivity**
  ```bash
  curl https://api.openai.com/v1/models \
    -H "Authorization: Bearer $OPENAI_API_KEY"
  ```

- [ ] **Verify Application**
  - Restart application
  - Check `/api/llm/models` endpoint
  - Test chat functionality

- [ ] **Monitor Costs**
  - Set up OpenAI usage alerts
  - Monitor `/api/llm/models` response
  - Review OpenAI dashboard regularly

### Staging → Production (Azure/Custom)

- [ ] Configure custom provider credentials
- [ ] Test in staging environment
- [ ] Verify request/response format compatibility
- [ ] Monitor latency and errors
- [ ] Set up backup provider configuration

---

## Troubleshooting

### "LLM Configuration Error: OPENAI_API_KEY not set"
**Solution:** Set the `OPENAI_API_KEY` environment variable with your API key.

### Models list is empty
**For Nollama:** Ensure Nollama service is running at configured URL
**For OpenAI:** API key may be invalid or account has no quota

### Timeout errors
- **Nollama:** Check local service is running
- **OpenAI:** Check internet connectivity and API status
- **Custom:** Verify endpoint URL and network access

### Authentication failures
- **OpenAI:** Verify API key is correct and not expired
- **Custom:** Check API key format for your provider
- **Headers:** Ensure `Authorization: Bearer` format is correct

---

## API Response Examples

### Health Check
```bash
curl http://127.0.0.1:8010/api/health
```

### List Available Models
```bash
curl http://127.0.0.1:8010/api/llm/models
```

**Response (OpenAI):**
```json
{
  "provider": "OpenAI",
  "reachable": true,
  "default_model": "gpt-4",
  "best_available": "gpt-4",
  "recommended_models": ["gpt-4"],
  "models": ["gpt-4"],
  "model_info": {}
}
```

**Response (Nollama):**
```json
{
  "provider": "Nollama",
  "reachable": true,
  "default_model": "qwen2@GPU",
  "best_available": "qwen2@GPU",
  "models": ["qwen2@GPU"],
  "model_info": {
    "qwen2@GPU": {
      "recommended": true,
      "note": "Qwen2 - High performance reasoning model"
    }
  }
}
```

---

## Advanced Configuration

### Using Environment Files
Create `.env` file in project root:
```bash
# .env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-your-key
OPENAI_MODEL=gpt-4
```

Load with:
```bash
python webapp/run.py
```

### Docker Deployment
```dockerfile
FROM python:3.14
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt

# Build-time configuration
ENV LLM_PROVIDER=openai
ENV OPENAI_API_KEY=sk-your-key

CMD ["python", "webapp/run.py"]
```

### Kubernetes Secrets
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: llm-config
type: Opaque
data:
  OPENAI_API_KEY: c2ste-eW91ci1rZXk=  # base64 encoded
  LLM_PROVIDER: b3BlbmFp  # base64 encoded
```

---

## Backward Compatibility

The application maintains backward compatibility with Ollama environment variables:

```bash
OLLAMA_BASE_URL      → NOLLAMA_BASE_URL
OLLAMA_MODEL         → NOLLAMA_MODEL
OLLAMA_JUDGE_MODEL   → NOLLAMA_JUDGE_MODEL
OLLAMA_JUDGE_ENABLED → JUDGE_LLM_ENABLED
OLLAMA_VISION_MODEL  → NOLLAMA_VISION_MODEL
```

These are automatically mapped to the new configuration system.

---

## Cost Optimization

### Development
- Use **Nollama** (free, local)
- Best for testing and development

### Production
- **OpenAI GPT-3.5**: Best cost/performance ratio for most tasks
- **OpenAI GPT-4**: Higher quality, needed for complex planning scenarios
- **Azure OpenAI**: Good for enterprise customers with existing Azure subscriptions

### Monitoring
```python
# Track token usage from API responses
# Set up alerts for unexpected cost increases
# Regularly review usage patterns
```

---

## Support

For issues or questions:
1. Check application logs for detailed error messages
2. Verify provider connectivity and credentials
3. Check provider status page (OpenAI, Azure, etc.)
4. Review LLM configuration in `/api/llm/models` endpoint
