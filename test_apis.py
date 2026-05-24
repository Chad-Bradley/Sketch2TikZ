#!/usr/bin/env python3
"""
Test all registered LLM APIs for availability.

Usage:
    python test_apis.py                  # test all models
    python test_apis.py --text-only      # skip vision models
    python test_apis.py --image path.jpg # test vision models with a given image
"""
import os
import argparse

from dotenv import load_dotenv
load_dotenv(override=True)

from train.llm_caller import (
    call_text_model,
    call_vision_model,
    image_to_text,
    text_to_text,
    iter_models,
    PLATFORM_ENV_KEY,
    list_models,
)

# ── helpers ──────────────────────────────────────────────────────

RESET   = "\033[0m"
GREEN   = "\033[92m"
RED     = "\033[91m"
YELLOW  = "\033[93m"
BOLD    = "\033[1m"

_SIMPLE_PROMPT = "Reply with exactly: OK"
_API_TIMEOUT = 120  # seconds — model is considered dead after this
_TEST_MAX_TOKENS = 256  # generous enough for reasoning models' internal CoT overhead


def ok(msg: str = "OK") -> None:
    print(f"  {GREEN}✓{RESET} {msg}")

def fail(msg: str) -> None:
    print(f"  {RED}✗{RESET} {msg}")

def warn(msg: str) -> None:
    print(f"  {YELLOW}!{RESET} {msg}")


def test_platform_key(platform: str) -> bool:
    """Check whether an API key is configured for *platform*."""
    env_key = PLATFORM_ENV_KEY.get(platform, "")
    key = os.getenv(env_key, "")
    if not key or key.startswith("your_"):
        warn(f"{platform}: no API key set ({env_key})")
        return False
    print(f"  {GREEN}✓{RESET} {platform}: key found ({env_key}={key[:8]}...)")
    return True


# ── text model tests ─────────────────────────────────────────────

def test_text_model(model_name: str) -> bool:
    """Call a single text model and report result."""
    try:
        result = call_text_model(
            model_name,
            messages=[{"role": "user", "content": _SIMPLE_PROMPT}],
            max_tokens=_TEST_MAX_TOKENS,
            timeout=_API_TIMEOUT,
        )
        preview = result.strip()[:80].replace("\n", " ")
        ok(f"{model_name}  →  {preview}")
        return True
    except Exception as e:
        fail(f"{model_name}  ({type(e).__name__}: {str(e)[:120]})")
        return False


def test_all_text_models() -> dict:
    """Test every registered code/text model. Returns {model: success}."""
    print(f"\n{BOLD}── Text / Code Models ──{RESET}")
    results: dict = {}
    tested_platforms: set = set()

    for platform, model_name, call_type in iter_models():
        if call_type != "code":
            continue
        if platform not in tested_platforms:
            tested_platforms.add(platform)
            print(f"\n  {BOLD}[{platform}]{RESET}")
            if not test_platform_key(platform):
                results[f"{platform}/{model_name}"] = False
                continue

        results[f"{platform}/{model_name}"] = test_text_model(model_name)
    return results


# ── vision model tests ───────────────────────────────────────────

def test_vision_model(model_name: str, image_path: str) -> bool:
    """Call a single vision model and report result."""
    try:
        result = call_vision_model(
            model_name,
            image_path,
            prompt="Describe this image in one short sentence.",
            max_tokens=_TEST_MAX_TOKENS,
            timeout=_API_TIMEOUT,
        )
        preview = result.strip()[:80].replace("\n", " ")
        ok(f"{model_name}  →  {preview}")
        return True
    except Exception as e:
        fail(f"{model_name}  ({type(e).__name__}: {str(e)[:120]})")
        return False


def test_all_vision_models(image_path: str) -> dict:
    """Test every registered vision model. Returns {model: success}."""
    if not os.path.exists(image_path):
        print(f"\n{BOLD}── Vision Models ──{RESET}")
        warn(f"Image not found: {image_path}. Skipping vision tests.")
        return {}
    print(f"\n{BOLD}── Vision Models (image: {image_path}) ──{RESET}")
    results: dict = {}
    tested_platforms: set = set()

    for platform, model_name, call_type in iter_models():
        if call_type != "vision":
            continue
        if platform not in tested_platforms:
            tested_platforms.add(platform)
            print(f"\n  {BOLD}[{platform}]{RESET}")
            if not test_platform_key(platform):
                results[f"{platform}/{model_name}"] = False
                continue

        results[f"{platform}/{model_name}"] = test_vision_model(model_name, image_path)
    return results


# ── fallback tests ───────────────────────────────────────────────

def test_fallback_text() -> bool:
    """Test the text_to_text fallback mechanism."""
    print(f"\n{BOLD}── Fallback: text_to_text() ──{RESET}")
    try:
        result = text_to_text(
            messages=[{"role": "user", "content": _SIMPLE_PROMPT}],
            max_tokens=_TEST_MAX_TOKENS,
            timeout=_API_TIMEOUT,
        )
        preview = result.strip()[:80].replace("\n", " ")
        ok(f"text_to_text()  →  {preview}")
        return True
    except Exception as e:
        fail(f"text_to_text()  ({type(e).__name__}: {str(e)[:200]})")
        return False


def test_fallback_vision(image_path: str) -> bool:
    """Test the image_to_text fallback mechanism."""
    print(f"\n{BOLD}── Fallback: image_to_text() ──{RESET}")
    if not os.path.exists(image_path):
        warn(f"No image at {image_path}, skipping vision fallback test.")
        return False
    try:
        result = image_to_text(
            image_path,
            prompt="Describe this image in one short sentence.",
            max_tokens=_TEST_MAX_TOKENS,
            timeout=_API_TIMEOUT,
        )
        preview = result.strip()[:80].replace("\n", " ")
        ok(f"image_to_text()  →  {preview}")
        return True
    except Exception as e:
        fail(f"image_to_text()  ({type(e).__name__}: {str(e)[:200]})")
        return False


def print_model_registry() -> None:
    """Print the model registry."""
    print(f"\n{BOLD}── Registered Models ──{RESET}")
    models = list_models()
    for platform in sorted(models.keys()):
        print(f"\n  {BOLD}[{platform}]{RESET}")
        for m in models[platform]:
            print(f"    {m}")


# ── main ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Test all LLM API endpoints")
    parser.add_argument("--text-only", action="store_true",
                        help="Skip vision model tests")
    parser.add_argument("--image", type=str, default=None,
                        help="Path to an image for vision model testing")
    parser.add_argument("--skip-fallback", action="store_true",
                        help="Skip the fallback mechanism tests")
    parser.add_argument("--platform", type=str, default=None,
                        help="Only test models from a specific platform "
                             "(e.g. nvidia, openrouter)")
    args = parser.parse_args()

    print(f"{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  Sketch2TikZ LLM API Tester  (timeout={_API_TIMEOUT}s){RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    print_model_registry()

    text_results: dict = {}
    vision_results: dict = {}
    fallback_text_ok = None
    fallback_vision_ok = None

    # Text models
    text_results = test_all_text_models()

    # Vision models
    if not args.text_only:
        image_path = args.image
        if image_path is None:
            warn("No --image provided. Vision tests will be skipped.")
            warn("Use: python test_apis.py --image /path/to/image.jpg")
        vision_results = test_all_vision_models(image_path or "/nonexistent")

    # Fallback tests
    if not args.skip_fallback:
        fallback_text_ok = test_fallback_text()
        if not args.text_only and args.image:
            fallback_vision_ok = test_fallback_vision(args.image)

    # ── Summary ──────────────────────────────────────────────────
    print(f"\n\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  Summary{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    all_results = {**text_results, **vision_results}
    if fallback_text_ok is not None:
        all_results["text_to_text (fallback)"] = fallback_text_ok
    if fallback_vision_ok is not None:
        all_results["image_to_text (fallback)"] = fallback_vision_ok

    passed = sum(1 for v in all_results.values() if v)
    total = len(all_results)
    failed = total - passed

    for name, success in all_results.items():
        if success:
            ok(name)
        else:
            fail(name)

    print(f"\n{BOLD}{passed}/{total} passed, {failed} failed{RESET}")

    if failed > 0:
        print(f"\n{YELLOW}Tip: Ensure the corresponding API keys are set in .env{RESET}")


if __name__ == "__main__":
    main()
