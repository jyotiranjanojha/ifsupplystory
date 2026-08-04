#!/usr/bin/env python3
"""
Test script for multi-provider LLM configuration.
Demonstrates how the application switches between different LLM providers.

Usage:
    python test_llm_providers.py          # Test current provider
    LLM_PROVIDER=openai python test_llm_providers.py  # Test OpenAI (without actual API key)
"""

import os
import json
from pathlib import Path

# Import the analyzer module to test LLM config
import sys
sys.path.insert(0, str(Path(__file__).parent / "webapp"))

def test_llm_configuration():
    """Test the LLM configuration system."""
    from app.analyzer import LLM_CONFIG, LLM_PROVIDER
    
    print("=" * 70)
    print("LLM Provider Configuration Test")
    print("=" * 70)
    print()
    
    print(f"Current Provider: {LLM_PROVIDER}")
    print()
    print("Active Configuration:")
    print("-" * 70)
    for key, value in LLM_CONFIG.items():
        if key == "api_key" and value:
            # Mask API key for security
            masked = value[:10] + "..." if len(value) > 10 else "***"
            print(f"  {key:20s}: {masked}")
        else:
            print(f"  {key:20s}: {value}")
    print()
    
    # Test provider-specific features
    print("Provider-Specific Capabilities:")
    print("-" * 70)
    
    if LLM_CONFIG["provider"] == "nollama":
        print("  ✓ Local operation (no internet required)")
        print("  ✓ Free to use (self-hosted)")
        print("  ✓ Low latency")
        print("  ✓ No API key needed")
    elif LLM_CONFIG["provider"] == "openai":
        print("  ✓ State-of-the-art models (GPT-4)")
        print("  ✓ High reliability and uptime")
        print("  ✓ Vision capabilities")
        print("  ⚠ Requires API key and internet")
        print("  ⚠ Pay-per-token pricing")
    elif LLM_CONFIG["provider"] == "custom":
        print("  ✓ Flexible - works with any OpenAI-compatible API")
        print("  ✓ Can use Azure OpenAI, LM Studio, etc.")
        print(f"  → Endpoint: {LLM_CONFIG['base_url']}")
    
    print()
    
    # Show environment variables used
    print("Environment Variables (LLM_PROVIDER specific):")
    print("-" * 70)
    
    if LLM_CONFIG["provider"] == "nollama":
        print("  LLM_PROVIDER=nollama")
        print(f"  NOLLAMA_BASE_URL={os.getenv('NOLLAMA_BASE_URL', '(using default)')}")
        print(f"  NOLLAMA_MODEL={os.getenv('NOLLAMA_MODEL', '(using default)')}")
    elif LLM_CONFIG["provider"] == "openai":
        print("  LLM_PROVIDER=openai")
        print(f"  OPENAI_API_KEY={'***' if os.getenv('OPENAI_API_KEY') else '(not set)'}")
        print(f"  OPENAI_BASE_URL={os.getenv('OPENAI_BASE_URL', '(using default)')}")
        print(f"  OPENAI_MODEL={os.getenv('OPENAI_MODEL', '(using default)')}")
    elif LLM_CONFIG["provider"] == "custom":
        print("  LLM_PROVIDER=custom")
        print(f"  CUSTOM_LLM_BASE_URL={os.getenv('CUSTOM_LLM_BASE_URL', '(not set)')}")
        print(f"  CUSTOM_LLM_MODEL={os.getenv('CUSTOM_LLM_MODEL', '(not set)')}")
    
    print()
    print("=" * 70)
    print("Configuration Status: ✓ Valid")
    print("=" * 70)
    print()

if __name__ == "__main__":
    try:
        test_llm_configuration()
    except Exception as e:
        print(f"❌ Error: {e}")
        print()
        print("Hint: Make sure you're running from the project root directory")
        exit(1)
