"""Run every engine suite, each in its own process on its own fresh database,
then the evaluation gate. Exit code 1 if anything fails.

Run:  .venv/Scripts/python engine/tests/run_tests.py          (all suites + gate)
      .venv/Scripts/python engine/tests/run_tests.py policy   (suites whose name contains "policy")
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
EVALUATE = os.path.join(HERE, "..", "evaluation", "evaluate.py")
SUITES = ["test_engine", "test_identity", "test_knowledge", "test_regressions", "test_seed_data",
          "test_edge_cases", "test_policy", "test_access", "test_workflow", "test_gateway", "test_quota",
          "test_documents", "test_compliance", "test_ai_shapes", "test_image_text", "test_logos", "test_docx_fix", "test_review_r3", "test_api", "test_publisher",
          "test_reliability", "test_slow_ai_lock", "test_understanding"]


def main() -> int:
    only = sys.argv[1:]
    suites = [s for s in SUITES if os.path.exists(os.path.join(HERE, s + ".py"))
              and (not only or any(o in s for o in only))]
    steps = [(s, [sys.executable, s + ".py"]) for s in suites]
    if not only:
        steps.append(("evaluation gate", [sys.executable, EVALUATE, "--check"]))
    failed = []
    for name, cmd in steps:
        t = time.perf_counter()
        # no suite may spend a real AI key: read no .env, drop provider settings
        env = {k: v for k, v in os.environ.items()
               if k not in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "OLLAMA_URL")}
        env["CANONRY_ENV_FILE"] = ""
        env["PYTHONIOENCODING"] = "utf-8"  # suites print ₹, ΔE and quotes; a Windows console must not fail them
        r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        ok = r.returncode == 0
        print(f"{'PASS' if ok else 'FAIL'}  {name}  ({time.perf_counter() - t:.1f}s)")
        if not ok:
            failed.append(name)
            out = (r.stdout + r.stderr).strip().splitlines()
            print("\n".join("      " + line for line in out if "FAIL" in line or "Error" in line or "Traceback" in line)
                  or "\n".join("      " + line for line in out[-15:]))
    print(f"\n{len(steps) - len(failed)}/{len(steps)} passed" + (f"; failed: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
