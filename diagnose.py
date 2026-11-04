"""Local import diagnostics. Does not alter security settings or print credentials."""
import importlib, importlib.metadata, platform, struct, sys
from pathlib import Path
lines=["India Quant diagnostics", "Python: "+sys.version.split()[0], "OS: "+platform.platform(), "Architecture: "+str(struct.calcsize("P")*8)+" bit"]
for name in ("fastapi","uvicorn","pydantic","numpy","scipy","sklearn","joblib","threadpoolctl"):
    try:
        mod=importlib.import_module(name)
        lines.append(name+": OK "+str(getattr(mod,"__version__","")))
    except Exception as exc:
        lines.append(name+": "+type(exc).__name__+": "+str(exc)[:400])
lines += ["No broker token, .env content or journal records are included.", "For Application Control blocks, review the exact blocked file with your authorized administrator; do not disable protection."]
text="\n".join(lines)
Path(__file__).with_name("diagnostic_report.txt").write_text(text,encoding="utf-8")
print(text)
