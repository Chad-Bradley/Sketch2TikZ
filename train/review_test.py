"""Review test-set results via AI, without seeing GT code."""
import os, sys, glob, time, json, base64
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(override=True)

from train.llm_caller import _create, VISION_MODELS, VISION_PLATFORMS
from train.pipeline import generate as pipeline_generate

REVIEW_PROMPT = """You are a TikZ quality inspector. Given:
1. A REFERENCE image
2. GENERATED code and its compile status
3. INTERNAL CRITIC score + diagnosis

Identify PATTERNS of failure across samples. Output JSON:
{
  "patterns": ["pattern1", "pattern2"],
  "vision_prompt_fix": "<concrete sentence>",
  "code_system_fix": "<concrete rule>",
  "severity": "low|medium|high"
}"""


def main():
    test_dir = os.path.join(os.path.dirname(__file__), "..", "test", "data", "easy")
    imgs = sorted(glob.glob(os.path.join(test_dir, "????.png")))[:5]
    print(f"=== Test Review ({len(imgs)} samples) ===")

    results = []
    for i, png in enumerate(imgs):
        print(f"[{i+1}/{len(imgs)}] {os.path.basename(png)}")
        t0 = time.time()
        r = pipeline_generate(png, i, output_dir="output")
        elapsed = time.time() - t0
        status = "OK" if r.compile_ok else "FAIL"
        score = r.critic_score
        diagnosis = r.diagnosis
        print(f"  Compile: {status} ({r.compile_attempts} att) | Critic: {score:.1f} | {elapsed:.1f}s")
        if r.compile_ok and score < 4.0:
            print(f"  Diagnosis: {diagnosis[:150]}")
        results.append({"png": png, "r": r, "score": score, "diagnosis": diagnosis})
        print()

    # AI Review
    print("=== AI Pattern Analysis ===")
    bad = [s for s in results if s["r"].compile_ok and s["score"] < 4.0]
    if not bad:
        print("All samples >= 4.0. No patterns to fix.")
        return

    print(f"Reviewing {len(bad)} low-score sample(s)")
    inputs = []
    for s in bad:
        base = os.path.basename(s["png"])
        tex = os.path.join("output", f"gen_{s['r'].index:04d}.tex")
        code = ""
        if os.path.exists(tex):
            with open(tex, encoding="utf-8") as f:
                code = f.read()[:2000]
        inputs.append(f"Sample {base}: Critic={s['score']:.1f}. {s['diagnosis']}\nCode:\n{code[:500]}")

    review_text = "PATTERNS ACROSS FAILURES:\n" + "\n---\n".join(inputs)
    platform = VISION_PLATFORMS[0]
    model = VISION_MODELS[platform]

    # Include worst-scoring image for visual context
    worst = min(bad, key=lambda x: x["score"])
    from train.pipeline import _encode_img
    b64 = _encode_img(worst["png"])

    try:
        raw = _create(platform, model, [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": b64}},
            {"type": "text", "text": review_text},
            {"type": "text", "text": REVIEW_PROMPT},
        ]}], temperature=0.0, max_tokens=500)
        raw = raw.strip()
        if raw.startswith("```"): raw = raw.split("\n", 1)[-1].replace("```", "").strip()
        review = json.loads(raw)
        print(f"\nSeverity: {review.get('severity', 'N/A')}")
        print(f"Patterns: {review.get('patterns', [])}")
        print(f"Vision fix: {review.get('vision_prompt_fix', 'N/A')}")
        print(f"Code fix:   {review.get('code_system_fix', 'N/A')}")
    except Exception as e:
        print(f"Review failed: {e}")


if __name__ == "__main__":
    main()
