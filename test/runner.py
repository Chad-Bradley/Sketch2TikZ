"""Sealed benchmark runner. Only reads test/data/ PNGs. No code access."""
import os, sys, time, glob, argparse

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from train.pipeline import generate
from test.judge import evaluate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def safe_print(*args, **kwargs):
    try: print(*args, **kwargs)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", errors="replace").decode("ascii") for a in args), **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--difficulty", choices=["easy","medium","difficult"], default="easy")
    parser.add_argument("--num-samples", type=int, default=10)
    parser.add_argument("--skip-judge", action="store_true")
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

    results = []
    for i, png_path in enumerate(samples):
        safe_print(f"\n[{i+1}/{n}] {os.path.basename(png_path)}")
        t0 = time.time()

        r = generate(png_path, i, output_dir=out_dir)

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

    compile_ok = sum(1 for r in results if r.compile_ok)
    judged = [r for r in results if r.compile_ok]
    scores = [r.critic_score for r in judged]
    passes = sum(1 for r in judged if r.critic_pass)
    avg_score = sum(scores) / len(scores) if scores else 0.0
    avg_s = sum(r.compile_attempts for r in results) / n

    safe_print(f"\n{'=' * 55}")
    safe_print(f"  Benchmark — {args.difficulty.upper()}  (n={n})")
    safe_print(f"{'=' * 55}")
    safe_print(f"  Compile rate:          {compile_ok}/{n}  ({100*compile_ok/n:.1f}%)")
    safe_print(f"  Avg compile attempts:  {avg_s:.1f}")
    safe_print(f"  Critic pass rate:      {passes}/{max(1,len(judged))}  "
               f"({100*passes/max(1,len(judged)):.1f}%)")
    safe_print(f"  Avg fidelity score:    {avg_score:.2f} / 5.0")
    safe_print(f"{'=' * 55}")


if __name__ == "__main__":
    main()
