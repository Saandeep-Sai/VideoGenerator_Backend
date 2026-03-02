"""
OpenRouter API Key Validator
=============================

This script validates all OpenRouter API keys to check if they are valid and active.
Tests each key by making a minimal API request to OpenRouter.

Usage:
    python validate_openrouter_keys.py

Keys are loaded from:
1. Environment variable: OPENROUTER_API_KEY (single key)
2. Environment variables: OPENROUTER_API_KEY_1, OPENROUTER_API_KEY_2, etc.
3. Or edit the KEYS list below directly
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Tuple
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables
load_dotenv(override=True)

# Color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'
BOLD = '\033[1m'


def load_api_keys() -> List[str]:
    """Load all OpenRouter API keys from environment variables."""
    keys = []
    
    # Try loading from single key
    single_key = os.getenv('OPENROUTER_API_KEY')
    if single_key:
        single_key = single_key.strip().strip('"').strip()  # Remove quotes and whitespace
        if single_key:
            keys.append(single_key)
            print(f"{BLUE}📌 Found OPENROUTER_API_KEY{RESET}")
    
    # Try loading numbered keys (OPENROUTER_API_KEY_2, _3, _4, etc.)
    for index in range(2, 20):  # Check up to 20 keys
        key = os.getenv(f'OPENROUTER_API_KEY_{index}')
        if key:
            key = key.strip().strip('"').strip()  # Remove quotes and whitespace
            if key:
                keys.append(key)
                print(f"{BLUE}📌 Found OPENROUTER_API_KEY_{index}{RESET}")
    
    if not keys:
        print(f"{RED}❌ No API keys found in environment variables{RESET}")
        print(f"{YELLOW}💡 Add keys to .env file:{RESET}")
        print(f"   OPENROUTER_API_KEY=sk-or-v1-xxx")
        print(f"   OPENROUTER_API_KEY_2=sk-or-v1-xxx")
        print(f"   OPENROUTER_API_KEY_3=sk-or-v1-xxx")
    
    return keys


def validate_single_key(key: str, index: int) -> Tuple[bool, str, Dict]:
    """
    Validate a single OpenRouter API key.
    
    Args:
        key: The API key to validate
        index: Index number for display
    
    Returns:
        Tuple of (is_valid, error_message, details)
    """
    # Mask key for display (show first 10 and last 4 characters)
    masked_key = f"{key[:10]}...{key[-4:]}" if len(key) > 14 else "***"
    
    try:
        # Create OpenAI client with OpenRouter base URL
        client = OpenAI(
            api_key=key,
            base_url="https://openrouter.ai/api/v1"
        )
        
        # Make a minimal test request (using a free model)
        print(f"{YELLOW}   Testing key #{index}: {masked_key}...{RESET}")
        
        response = client.chat.completions.create(
            model="qwen/qwen-2-7b-instruct:free",  # Free model for testing
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=5,
            temperature=0.1
        )
        
        # If we get here, the key is valid
        details = {
            "model": "qwen/qwen-2-7b-instruct:free",
            "response_id": response.id if hasattr(response, 'id') else "N/A",
            "usage": response.usage.total_tokens if hasattr(response, 'usage') else 0
        }
        
        return True, "Key is valid and working", details
        
    except Exception as e:
        error_str = str(e)
        
        # Parse specific error types
        if "401" in error_str:
            return False, "Invalid API key (401 Unauthorized)", {"error_code": 401}
        elif "404" in error_str or "User not found" in error_str:
            return False, "User not found (404) - Key may be expired or deleted", {"error_code": 404}
        elif "429" in error_str:
            return False, "Rate limit exceeded (429)", {"error_code": 429}
        elif "403" in error_str:
            return False, "Access forbidden (403)", {"error_code": 403}
        elif "quota" in error_str.lower():
            return False, "Quota exceeded - No credits remaining", {"error_code": "quota"}
        else:
            return False, f"Error: {error_str[:100]}", {"error_type": type(e).__name__}


def main():
    """Main validation function."""
    print(f"\n{BOLD}{BLUE}{'='*60}{RESET}")
    print(f"{BOLD}{BLUE}OpenRouter API Key Validator{RESET}")
    print(f"{BOLD}{BLUE}{'='*60}{RESET}\n")
    
    # Load keys
    keys = load_api_keys()
    
    if not keys:
        sys.exit(1)
    
    print(f"\n{BOLD}Found {len(keys)} API key(s) to validate{RESET}\n")
    
    # Validate each key
    results = []
    valid_count = 0
    invalid_count = 0
    
    for i, key in enumerate(keys, 1):
        print(f"{BOLD}Validating Key #{i}:{RESET}")
        is_valid, message, details = validate_single_key(key, i)
        
        results.append({
            "index": i,
            "key": f"{key[:10]}...{key[-4:]}" if len(key) > 14 else "***",
            "valid": is_valid,
            "message": message,
            "details": details
        })
        
        if is_valid:
            valid_count += 1
            print(f"{GREEN}   ✅ VALID: {message}{RESET}")
            if details:
                print(f"{GREEN}      Model: {details.get('model', 'N/A')}{RESET}")
                print(f"{GREEN}      Response ID: {details.get('response_id', 'N/A')}{RESET}")
        else:
            invalid_count += 1
            print(f"{RED}   ❌ INVALID: {message}{RESET}")
            if details:
                print(f"{RED}      Details: {details}{RESET}")
        
        print()
    
    # Summary
    print(f"{BOLD}{BLUE}{'='*60}{RESET}")
    print(f"{BOLD}Validation Summary{RESET}")
    print(f"{BOLD}{BLUE}{'='*60}{RESET}\n")
    
    print(f"Total Keys Tested: {BOLD}{len(keys)}{RESET}")
    print(f"{GREEN}Valid Keys: {BOLD}{valid_count}{RESET}")
    print(f"{RED}Invalid Keys: {BOLD}{invalid_count}{RESET}\n")
    
    # Detailed results table
    if len(keys) > 1:
        print(f"{BOLD}Detailed Results:{RESET}\n")
        print(f"{'Key #':<8} {'Status':<12} {'Message':<50}")
        print(f"{'-'*70}")
        
        for result in results:
            status = f"{GREEN}VALID{RESET}" if result['valid'] else f"{RED}INVALID{RESET}"
            print(f"{result['index']:<8} {status:<20} {result['message'][:45]}")
        
        print()
    
    # Recommendations
    if invalid_count > 0:
        print(f"{YELLOW}💡 Recommendations:{RESET}")
        print(f"   1. Check if invalid keys have expired")
        print(f"   2. Verify keys are copied correctly (no extra spaces)")
        print(f"   3. Check OpenRouter dashboard: https://openrouter.ai/keys")
        print(f"   4. Ensure account has credits remaining")
        print()
    
    # Exit code
    if invalid_count > 0:
        sys.exit(1)
    else:
        print(f"{GREEN}{BOLD}✅ All keys are valid!{RESET}\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
