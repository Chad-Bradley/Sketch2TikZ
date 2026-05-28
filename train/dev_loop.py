"""
Iterative prompt optimisation loop.

1. Generate TikZ from train images (GT code available)
2. Compile + internal critic comparison
3. For low-score samples: send GT code + generated code + critic diagnosis
   to vision model for academic review
4. Output actionable prompt improvement suggestions
"""
import os, sys, glob, time, json, base64
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(override=True)

from train.llm_caller import image_to_text, _create, VISION_MODELS, VISION_PLATFORMS
from train.pipeline import generate as pipeline_generate
from train.pipeline import _internal_critic, _encode_img


REVIEW_PROMPT = """You are a TikZ prompt engineering expert. I will show you:

1. The GROUND TRUTH TikZ code (correct output)
2. The GENERATED TikZ code (model output)
3. The CRITIC DIAGNOSIS (what went wrong visually)

Analyze the gap between generated and ground truth. Identify the ROOT CAUSE:
- Was the vision description missing key details?
- Was the code generation prompt missing specific rules?
- Did the model consistently fail on a specific pattern (arrows, formulas, shapes)?

Output a JSON with CONCRETE prompt fixes:
{
  "vision_prompt_fix": "<exact sentence to add to VISION_PROMPT>",
  "code_system_fix": "<exact rule to add to CODE_SYSTEM>",
  "root_cause": "<one-line summary>"
}

Be SPECIFIC. No vague suggestions. Every fix must be a copy-pasteable sentence."""


def safe_print(*a, **kw):
    try: print(*a, **kw)
    except UnicodeEncodeError:
        print(*(str(x).encode("ascii","replace").decode("ascii") for x in a), **kw)


def main():
    import random
    all_imgs = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "data", "easy", "????.png")))
    random.seed(int(time.time()))
    random.shuffle(all_imgs)
    imgs = all_imgs[:3]

    safe_print(f"=== Iterative Prompt Optimisation ===")
    safe_print(f"Samples: {len(imgs)}")
    safe_print()

    samples = []
    for i, png in enumerate(imgs):
        safe_print(f"[{i+1}/{len(imgs)}] {os.path.basename(png)}")
        t0 = time.time()
        r = pipeline_generate(png, i, output_dir="output")
        elapsed = time.time() - t0

        # Find GT code
        tikz_path = png.replace(".png", ".tikz")
        with open(tikz_path, "r", encoding="utf-8") as f:
            gt_code = f.read()

        # Internal critic
        critic = None
        if r.compile_ok and r.gen_pdf_path:
            critic = _internal_critic(png, r.gen_pdf_path, "output")

        samples.append({
            "png": png,
            "gt_code": gt_code,
            "gen_code": r.gen_code if hasattr(r, 'gen_code') else "",
            "compile_ok": r.compile_ok,
            "compile_attempts": r.compile_attempts,
            "critic": critic,
            "vision_time": r.vision_time,
            "codegen_time": r.codegen_time,
            "elapsed": elapsed,
        })

        score = critic["score"] if critic else 0.0
        diag = critic.get("diagnosis", "") if critic else ""
        safe_print(f"  Compile: {'OK' if r.compile_ok else 'FAIL'} ({r.compile_attempts} att) | Critic: {score:.1f}")
        if score < 3.0 and diag:
            safe_print(f"  Diagnosis: {diag[:150]}")
        safe_print()

    # --- Phase 2: AI Review of worst samples ---
    safe_print("=== AI Review ===")
    bad = [s for s in samples if s["critic"] and s["critic"]["score"] < 4.0]
    if not bad:
        safe_print("All samples score >= 4.0. No review needed.")
        return

    safe_print(f"Reviewing {len(bad)} sample(s) with score < 4.0")
    safe_print()

    for i, s in enumerate(bad):
        safe_print(f"--- Review {i+1}/{len(bad)} ---")
        score = s["critic"]["score"]
        diag = s["critic"]["diagnosis"]

        # Send GT code + generated code + critic diagnosis to vision model
        review_input = (
            f"GROUND TRUTH TikZ code:\n```\n{s['gt_code'][:3000]}\n```\n\n"
            f"GENERATED TikZ code:\n```\n{s['gen_code'][:3000]}\n```\n\n"
            f"CRITIC DIAGNOSIS (score {score}/5.0): {diag}"
        )

        # Also include the original image for visual context
        b64 = _encode_img(s["png"])
        critic_platform = VISION_PLATFORMS[0]
        critic_model = VISION_MODELS[critic_platform]

        try:
            raw = _create(
                critic_platform, critic_model,
                [{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": b64}},
                    {"type": "text", "text": review_input},
                    {"type": "text", "text": REVIEW_PROMPT},
                ]}],
                temperature=0.0, max_tokens=600,
            )
            raw = raw.strip()
            if raw.startswith("```"): raw = raw.split("\n", 1)[-1].replace("```", "").strip()
            review = json.loads(raw)
            safe_print(f"Root cause: {review.get('root_cause', 'N/A')}")
            safe_print(f"Vision prompt fix: {review.get('vision_prompt_fix', 'N/A')}")
            safe_print(f"Code system fix: {review.get('code_system_fix', 'N/A')}")
        except Exception as e:
            safe_print(f"Review failed: {e}")
        safe_print()

    safe_print("=== Done ===")
    safe_print("Apply suggested fixes to train/pipeline.py, then re-run to measure improvement.")


if __name__ == "__main__":
    main()
