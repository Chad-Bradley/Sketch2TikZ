"""
Focused prompt optimisation loop — analyse specific images you choose.

Usage:
  python -m train.dev_loop_focused --images train/data/easy/0016.png train/data/easy/0027.png
  python -m train.dev_loop_focused --images train/data/easy/0016.png,train/data/easy/0027.png,train/data/easy/0045.png
  python -m train.dev_loop_focused --dir train/data/easy --num 3   (random 3 from dir)
"""
import os, sys, glob, time, json, argparse
from datetime import datetime
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(override=True)

from train.llm_caller import image_to_text, _create, VISION_MODELS, VISION_PLATFORMS
from train.pipeline import generate as pipeline_generate
from train.pipeline import _internal_critic, _encode_img
from train.prompts import load_prompts


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


def _get_next_iter_dir(base_dir="iteration_logs"):
    os.makedirs(base_dir, exist_ok=True)
    existing = [d for d in os.listdir(base_dir) if d.startswith("iter_")]
    nums = [int(d.split("_")[1]) for d in existing if d.split("_")[1].isdigit()]
    next_num = max(nums) + 1 if nums else 1
    iter_dir = os.path.join(base_dir, f"iter_{next_num:03d}")
    os.makedirs(iter_dir, exist_ok=True)
    return iter_dir, next_num


def _save_json(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def resolve_images(args):
    """Resolve which images to process based on command-line args."""
    if args.images:
        # Support both comma-separated and space-separated
        imgs = []
        for part in args.images:
            imgs.extend([p.strip() for p in part.split(",")])
        imgs = [p for p in imgs if p]
    elif args.dir:
        pattern = os.path.join(args.dir, "????.png")
        all_imgs = sorted(glob.glob(pattern))
        if args.skip:
            all_imgs = [p for p in all_imgs if os.path.basename(p) not in args.skip]
        import random
        random.seed(int(time.time()))
        random.shuffle(all_imgs)
        imgs = all_imgs[:args.num]
    else:
        safe_print("Error: specify --images or --dir")
        sys.exit(1)

    # Validate all images exist
    valid = []
    for p in imgs:
        if os.path.exists(p):
            valid.append(p)
        else:
            safe_print(f"Warning: image not found, skipping: {p}")
    return valid


def main():
    parser = argparse.ArgumentParser(description="Focused prompt optimisation on specific images.")
    parser.add_argument("--images", nargs="*", default=None,
                        help="Specific images to analyse (space or comma separated)")
    parser.add_argument("--dir", default=None,
                        help="Directory to pick images from (e.g. train/data/easy)")
    parser.add_argument("--num", type=int, default=3,
                        help="Number of images to randomly pick from --dir (default: 3)")
    parser.add_argument("--skip", nargs="*", default=None,
                        help="Image filenames to skip (used with --dir)")
    parser.add_argument("--tag", default=None,
                        help="Optional tag for this run (saved in summary)")
    parser.add_argument("--difficulty", default="easy",
                        help="Prompt difficulty to use (easy, medium, difficult, chart_plot, etc.)")
    args = parser.parse_args()

    imgs = resolve_images(args)
    if not imgs:
        safe_print("Error: no valid images to process")
        sys.exit(1)

    # ── Prepare iteration log ──
    iter_dir, iter_num = _get_next_iter_dir()
    tag_str = f" [{args.tag}]" if args.tag else ""
    safe_print(f"=== Focused Prompt Optimisation [Iteration {iter_num}]{tag_str} ===")
    safe_print(f"Logs: {iter_dir}")
    safe_print(f"Samples ({len(imgs)}):")
    for p in imgs:
        safe_print(f"  - {os.path.basename(p)}")
    safe_print()

    # ── Load prompts for selected difficulty ──
    difficulty = args.difficulty
    prompts = load_prompts(difficulty)
    vision_prompt = prompts["vision_prompt"]
    code_system = prompts["code_system"]

    # ── Save current prompts ──
    with open(os.path.join(iter_dir, "VISION_PROMPT.txt"), "w", encoding="utf-8") as f:
        f.write(vision_prompt)
    with open(os.path.join(iter_dir, "CODE_SYSTEM.txt"), "w", encoding="utf-8") as f:
        f.write(code_system)

    samples = []
    for i, png in enumerate(imgs):
        base_name = os.path.splitext(os.path.basename(png))[0]
        safe_print(f"[{i+1}/{len(imgs)}] {base_name}")
        t0 = time.time()
        r = pipeline_generate(png, i, output_dir="output", difficulty=difficulty)
        elapsed = time.time() - t0

        # Find GT code (same dir, .tikz extension)
        tikz_path = png.replace(".png", ".tikz")
        gt_code = ""
        if os.path.exists(tikz_path):
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
            safe_print(f"  Diagnosis: {diag[:200]}")
        safe_print()

    # ── Save samples results ──
    _save_json(samples, os.path.join(iter_dir, "samples.json"))

    # ── Phase 2: AI Review of worst samples ──
    safe_print("=== AI Review ===")
    bad = [s for s in samples if s["critic"] and s["critic"]["score"] < 4.0]
    if not bad:
        safe_print("All samples score >= 4.0. No review needed.")
        summary = {
            "iteration": iter_num,
            "tag": args.tag,
            "timestamp": datetime.now().isoformat(),
            "total_samples": len(samples),
            "reviewed_samples": 0,
            "message": "All samples score >= 4.0",
            "reviewer_platform": None,
            "reviewer_model": None,
        }
        _save_json(summary, os.path.join(iter_dir, "summary.json"))
        return

    safe_print(f"Reviewing {len(bad)} sample(s) with score < 4.0")
    safe_print()

    reviews = []
    actual_platform = None
    actual_model = None

    for i, s in enumerate(bad):
        safe_print(f"--- Review {i+1}/{len(bad)}: {os.path.basename(s['png'])} ---")
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
        actual_platform = critic_platform
        actual_model = critic_model

        review_entry = {
            "sample": os.path.basename(s["png"]),
            "score": score,
            "diagnosis": diag,
            "reviewer_platform": actual_platform,
            "reviewer_model": actual_model,
            "success": False,
            "result": None,
            "error": None,
        }

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
            review_entry["success"] = True
            review_entry["result"] = review
            safe_print(f"  Reviewer: {actual_platform}/{actual_model}")
            safe_print(f"  Root cause: {review.get('root_cause', 'N/A')}")
            safe_print(f"  Vision prompt fix: {review.get('vision_prompt_fix', 'N/A')}")
            safe_print(f"  Code system fix: {review.get('code_system_fix', 'N/A')}")
        except Exception as e:
            review_entry["error"] = str(e)
            safe_print(f"  Review failed: {e}")

        reviews.append(review_entry)
        safe_print()

    # ── Save reviews ──
    _save_json(reviews, os.path.join(iter_dir, "reviews.json"))

    # ── Save summary ──
    summary = {
        "iteration": iter_num,
        "tag": args.tag,
        "timestamp": datetime.now().isoformat(),
        "input_images": [os.path.basename(p) for p in imgs],
        "total_samples": len(samples),
        "reviewed_samples": len(bad),
        "compile_ok_count": sum(1 for s in samples if s["compile_ok"]),
        "avg_score": round(
            sum(s["critic"]["score"] for s in samples if s["critic"])
            / max(len([s for s in samples if s["critic"]]), 1), 2),
        "reviewer_platform": actual_platform if bad else None,
        "reviewer_model": actual_model if bad else None,
    }
    _save_json(summary, os.path.join(iter_dir, "summary.json"))

    # ── Print summary ──
    safe_print("=== Summary ===")
    safe_print(f"Iteration: {iter_num}{tag_str}")
    safe_print(f"Reviewer: {actual_platform}/{actual_model}")
    safe_print(f"Compile OK: {summary['compile_ok_count']}/{len(samples)}")
    safe_print(f"Avg critic score: {summary['avg_score']}")
    safe_print(f"Reviews saved to: {iter_dir}")
    safe_print()
    safe_print("Apply suggested fixes to train/pipeline.py, then re-run to measure improvement.")


if __name__ == "__main__":
    main()
