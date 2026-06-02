"""Sealed benchmark runner. Only reads test/data/ PNGs. No code access."""
import os, sys, time, glob, argparse, json
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from train.pipeline import generate, get_vision_prompt, get_code_system
from test.judge import evaluate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def safe_print(*args, **kwargs):
    try: print(*args, **kwargs)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", errors="replace").decode("ascii") for a in args), **kwargs)


def _init_bench_dir(args):
    """Initialize or find the current benchmark directory."""
    base_dir = os.path.join(ROOT, "iteration_logs")
    os.makedirs(base_dir, exist_ok=True)
    
    # If resume, find latest bench dir
    if args.resume:
        existing = [d for d in os.listdir(base_dir) if d.startswith("bench_")]
        nums = [int(d.split("_")[1]) for d in existing if d.split("_")[1].isdigit()]
        if nums:
            latest = f"bench_{max(nums):03d}"
            return os.path.join(base_dir, latest)
    
    # Check if there's a running benchmark session
    running_file = os.path.join(base_dir, ".running_bench")
    if os.path.exists(running_file):
        with open(running_file, "r") as f:
            bench_dir = f.read().strip()
        if os.path.isdir(bench_dir):
            return bench_dir
    
    # Create new bench directory
    existing = [d for d in os.listdir(base_dir) if d.startswith("bench_")]
    nums = [int(d.split("_")[1]) for d in existing if d.split("_")[1].isdigit()]
    next_num = max(nums) + 1 if nums else 1
    bench_dir = os.path.join(base_dir, f"bench_{next_num:03d}")
    os.makedirs(bench_dir, exist_ok=True)
    
    # Save current prompts (use the correct difficulty)
    with open(os.path.join(bench_dir, "VISION_PROMPT.txt"), "w", encoding="utf-8") as f:
        f.write(get_vision_prompt(args.difficulty))
    with open(os.path.join(bench_dir, "CODE_SYSTEM.txt"), "w", encoding="utf-8") as f:
        f.write(get_code_system(args.difficulty))
    
    # Mark as running
    with open(running_file, "w") as f:
        f.write(bench_dir)
    
    return bench_dir


def _load_existing_results(bench_dir, n):
    """Load existing results for resume mode."""
    results_path = os.path.join(bench_dir, "results.json")
    if os.path.exists(results_path):
        with open(results_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("samples", [])
    return []


def _save_single_sample(bench_dir, i, n, r, args, png_path):
    """Save result after each single sample completes."""
    results_path = os.path.join(bench_dir, "results.json")
    if os.path.exists(results_path):
        with open(results_path, "r", encoding="utf-8") as f:
            all_results = json.load(f)
    else:
        all_results = {
            "timestamp": datetime.now().isoformat(),
            "difficulty": args.difficulty,
            "num_samples": n,
            "skip_judge": args.skip_judge,
            "samples": [],
        }
    
    sample_result = {
        "sample": os.path.basename(png_path),
        "index": i,
        "compile_ok": r.compile_ok,
        "compile_attempts": r.compile_attempts,
        "score": r.critic_score if r.compile_ok else None,
        "diagnosis": r.diagnosis if r.compile_ok else None,
        "vision_time": r.vision_time,
        "codegen_time": r.codegen_time,
    }
    
    # Update or append
    found = False
    for idx, s in enumerate(all_results["samples"]):
        if s.get("index") == i:
            all_results["samples"][idx] = sample_result
            found = True
            break
    if not found:
        all_results["samples"].append(sample_result)
    
    all_results["samples"].sort(key=lambda x: x.get("index", 0))
    
    completed = [s for s in all_results["samples"] if s.get("compile_ok") is not None]
    n_done = len(completed)
    compile_ok_count = sum(1 for s in completed if s["compile_ok"])
    judged = [s for s in completed if s.get("score") is not None]
    scores = [s["score"] for s in judged if s["score"] is not None]
    
    all_results["progress"] = f"{n_done}/{n}"
    all_results["compile_rate"] = f"{compile_ok_count}/{n_done}" if n_done > 0 else "0/0"
    all_results["avg_fidelity_score"] = round(sum(scores) / len(scores), 2) if scores else None
    
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    
    safe_print(f"  [Saved] progress: {n_done}/{n}")


def _finalize_bench(bench_dir, args, results):
    """Save final summary and clean up running marker."""
    base_dir = os.path.join(ROOT, "iteration_logs")
    running_file = os.path.join(base_dir, ".running_bench")
    if os.path.exists(running_file):
        os.remove(running_file)
    
    compile_ok = sum(1 for r in results if r.compile_ok)
    judged = [r for r in results if r.compile_ok]
    scores = [r.critic_score for r in judged]
    passes = sum(1 for r in judged if r.critic_pass)
    avg_score = sum(scores) / len(scores) if scores else 0.0
    avg_s = sum(r.compile_attempts for r in results) / len(results) if results else 0
    
    final = {
        "timestamp": datetime.now().isoformat(),
        "difficulty": args.difficulty,
        "num_samples": len(results),
        "skip_judge": args.skip_judge,
        "compile_rate": f"{compile_ok}/{len(results)}",
        "compile_rate_pct": round(100 * compile_ok / len(results), 1) if results else 0,
        "avg_compile_attempts": round(avg_s, 1),
        "critic_pass_rate": f"{passes}/{max(1, len(judged))}",
        "critic_pass_rate_pct": round(100 * passes / max(1, len(judged)), 1),
        "avg_fidelity_score": round(avg_score, 2),
        "status": "completed" if len(results) == args.num_samples else f"interrupted_at_{len(results)}",
    }
    
    final_path = os.path.join(bench_dir, "bench_result.json")
    with open(final_path, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)
    safe_print(f"\nFinal result saved to: {final_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--difficulty", choices=["easy","medium","difficult","chart_plot","math_formula","math_geometry","pure_drawing"], default="easy")
    parser.add_argument("--num-samples", type=int, default=10)
    parser.add_argument("--skip-judge", action="store_true")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from last completed sample in existing bench dir")
    parser.add_argument("--start-from", type=int, default=0,
                        help="Skip samples before this index (0-based)")
    args = parser.parse_args()

    test_dir = os.path.join(ROOT, "test", "data", args.difficulty)
    out_dir = os.path.join(ROOT, "output")
    os.makedirs(out_dir, exist_ok=True)

    if not os.path.isdir(test_dir):
        safe_print(f"Test data not found: {test_dir}")
        return

    samples = sorted(glob.glob(os.path.join(test_dir, "*.png")))[:args.num_samples]
    n = len(samples)
    safe_print(f"Benchmark: {args.difficulty}  samples: {n}")
    safe_print(f"Test data: {test_dir}")
    safe_print(f"Output: {out_dir}")

    # Init bench dir
    bench_dir = _init_bench_dir(args)
    
    # Load existing results for resume
    start_from = args.start_from
    existing_results = []
    if args.resume or args.start_from > 0:
        existing_results = _load_existing_results(bench_dir, n)
        # Find the highest completed index
        completed_indices = [s.get("index", -1) for s in existing_results if s.get("compile_ok") is not None]
        if completed_indices:
            resume_start = max(completed_indices) + 1
            if args.resume and resume_start > start_from:
                start_from = resume_start
                safe_print(f"Resuming from sample index {start_from} (use --start-from N to override)")
    
    safe_print(f"Starting from sample index: {start_from}")

    results = []
    # Pre-fill results with existing data for samples before start_from
    for s in existing_results:
        if s.get("index", -1) < start_from:
            # Create a dummy SampleResult-like object
            class DummyResult:
                pass
            dummy = DummyResult()
            dummy.compile_ok = s.get("compile_ok", False)
            dummy.compile_attempts = s.get("compile_attempts", 0)
            dummy.critic_score = s.get("score")
            dummy.critic_pass = s.get("score", 0) >= 3.0 if s.get("score") else False
            dummy.diagnosis = s.get("diagnosis", "")
            dummy.vision_time = s.get("vision_time", 0)
            dummy.codegen_time = s.get("codegen_time", 0)
            dummy.gen_pdf_path = ""
            results.append(dummy)

    for i, png_path in enumerate(samples):
        if i < start_from:
            safe_print(f"\n[{i+1}/{n}] {os.path.basename(png_path)} [SKIP]")
            continue
            
        safe_print(f"\n[{i+1}/{n}] {os.path.basename(png_path)}")
        t0 = time.time()

        r = generate(png_path, i, output_dir=out_dir, difficulty=args.difficulty)

        if r.compile_ok and not args.skip_judge:
            j = evaluate(png_path, r.gen_pdf_path, out_dir)
            r.critic_score = j["score"]
            r.critic_pass = j["is_pass"]
            r.diagnosis = j["diagnosis"]
            safe_print(f"  Compile: OK ({r.compile_attempts} att) | "
                       f"Score: {r.critic_score:.1f} | {j['diagnosis']}")
        elif r.compile_ok:
            safe_print(f"  Compile: OK ({r.compile_attempts} att) | Judge skipped")
        else:
            safe_print(f"  Compile: FAIL ({r.compile_attempts} att)")
        safe_print(f"  vision: {r.vision_time}s  codegen: {r.codegen_time}s")
        results.append(r)
        
        # Save after each sample
        _save_single_sample(bench_dir, i, n, r, args, png_path)

    # Print summary
    compile_ok = sum(1 for r in results if r.compile_ok)
    judged = [r for r in results if r.compile_ok]
    scores = [r.critic_score for r in judged]
    passes = sum(1 for r in judged if r.critic_pass)
    avg_score = sum(scores) / len(scores) if scores else 0.0
    avg_s = sum(r.compile_attempts for r in results) / n if n > 0 else 0

    safe_print(f"\n{'=' * 55}")
    safe_print(f"  Benchmark — {args.difficulty.upper()}  (n={n})")
    safe_print(f"{'=' * 55}")
    safe_print(f"  Compile rate:          {compile_ok}/{n}  ({100*compile_ok/n:.1f}%)")
    safe_print(f"  Avg compile attempts:  {avg_s:.1f}")
    safe_print(f"  Critic pass rate:      {passes}/{max(1,len(judged))}  "
               f"({100*passes/max(1,len(judged)):.1f}%)")
    safe_print(f"  Avg fidelity score:    {avg_score:.2f} / 5.0")
    safe_print(f"{'=' * 55}")

    # Save final results
    _finalize_bench(bench_dir, args, results)


if __name__ == "__main__":
    main()