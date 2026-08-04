#!/usr/bin/env python3
"""Quick functional test of Chat Assistant and CSV data handling."""

import json
import urllib.request
import urllib.error
import time

def test_endpoints():
    """Test basic API endpoints."""
    print("=" * 70)
    print("QUICK FUNCTIONAL TEST - IFSP Chat Assistant")
    print("=" * 70)
    print()
    
    # Test health
    try:
        print("1. Testing health endpoint...")
        response = urllib.request.urlopen('http://127.0.0.1:8010/api/health', timeout=5)
        data = json.loads(response.read().decode())
        print(f"   ✓ Status: {data.get('status')}")
        print(f"   ✓ Service: {data.get('service')}")
        print()
    except Exception as e:
        print(f"   ✗ Error: {e}")
        print()
    
    # Test LLM models
    try:
        print("2. Testing LLM models endpoint...")
        response = urllib.request.urlopen('http://127.0.0.1:8010/api/llm/models', timeout=5)
        data = json.loads(response.read().decode())
        print(f"   ✓ Provider: {data.get('provider')}")
        print(f"   ✓ Model: {data.get('default_model')}")
        print(f"   ✓ Reachable: {data.get('reachable')}")
        print()
    except Exception as e:
        print(f"   ✗ Error: {e}")
        print()
    
    # Test datasets/CSV data endpoint
    try:
        print("3. Testing CSV data endpoint (datasets summary)...")
        response = urllib.request.urlopen('http://127.0.0.1:8010/api/datasets/summary', timeout=5)
        data = json.loads(response.read().decode())
        datasets = data.get('datasets', {})
        total_records = sum([d.get('record_count', 0) for d in datasets.values()])
        print(f"   ✓ Loaded datasets: {len(datasets)}")
        print(f"   ✓ Total records: {total_records}")
        for ds_name, ds_info in list(datasets.items())[:3]:
            print(f"      - {ds_name}: {ds_info.get('record_count', 0)} records")
        print()
    except Exception as e:
        print(f"   ✗ Error: {e}")
        print()

def test_chat_assistant():
    """Test Chat Assistant with natural language query."""
    print("4. Testing Chat Assistant with CSV data query...")
    print()
    
    # Simple chat query about inventory
    payload = {
        "question": "What is the total inventory value across all locations?",
        "week_id": "2025-W44",
        "scenario_id": "baseline",
        "llm_enabled": True,
        "history": []
    }
    
    req = urllib.request.Request(
        'http://127.0.0.1:8010/api/chat',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    
    try:
        print(f"   Query: {payload['question']}")
        print()
        print("   Sending to Chat Assistant...")
        with urllib.request.urlopen(req, timeout=120) as resp:
            response = json.loads(resp.read().decode())
            
            if 'error' in response:
                print(f"   ✗ Error: {response['error']}")
            else:
                assistant_reply = response.get('Assistant Reply', 'No reply')
                llm_provider = response.get('LLM Provider', 'Unknown')
                llm_model = response.get('LLM Model', 'Unknown')
                workflow = response.get('Workflow', 'Unknown')
                
                print(f"   ✓ LLM Provider: {llm_provider}")
                print(f"   ✓ Model: {llm_model}")
                print(f"   ✓ Workflow: {workflow}")
                print(f"   ✓ Response received ({len(assistant_reply)} chars)")
                print()
                print("   Assistant Reply:")
                print("   " + "-" * 65)
                # Print first 600 chars
                reply_preview = assistant_reply[:600]
                if len(assistant_reply) > 600:
                    reply_preview += "...\n   [response truncated for display]"
                for line in reply_preview.split('\n'):
                    print(f"   {line}")
                print()
    except urllib.error.HTTPError as e:
        try:
            error_data = json.loads(e.read().decode())
            detail = error_data.get('detail', e.reason)
        except:
            detail = e.reason
        print(f"   ✗ HTTP Error {e.code}: {detail}")
    except urllib.error.URLError as e:
        print(f"   ✗ Connection Error: {e.reason}")
    except TimeoutError:
        print(f"   ⏱ Request timed out (expected for LLM inference - this is normal)")
    except Exception as e:
        print(f"   ✗ Error: {type(e).__name__}: {e}")
    
    print()

def test_csv_data_loaded():
    """Check if CSV files are properly loaded."""
    print("5. Checking CSV data sources...")
    print()
    
    csv_files = {
        'inventory': 'by_input/if_snop_inventory-20251013165949.csv',
        'items': 'by_input/if_snop_items-20251013165949.csv',
        'customer_orders': 'by_input/if_snop_customerorder-20251013165949.csv',
        'bom': 'by_input/if_snop_billofmaterials-20251013165949.csv'
    }
    
    from pathlib import Path
    base_path = Path('c:\\Users\\jojha\\OneDrive - Intel Corporation\\Documents\\ifspstory')
    
    for name, file_path in csv_files.items():
        full_path = base_path / file_path
        if full_path.exists():
            size_mb = full_path.stat().st_size / (1024 * 1024)
            print(f"   ✓ {name:20s}: {size_mb:6.2f} MB")
        else:
            print(f"   ✗ {name:20s}: NOT FOUND")
    
    print()

if __name__ == "__main__":
    test_endpoints()
    test_csv_data_loaded()
    test_chat_assistant()
    
    print("=" * 70)
    print("Quick test complete!")
    print("=" * 70)
