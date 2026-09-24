"""Disposable process for untrusted PDF/DOCX parsers; never runs uploaded code."""
import json
import os
import sys


def main():
    if os.name != "nt":
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    from .knowledge import extract

    try:
        data = sys.stdin.buffer.read(5_000_001)
        if len(data) > 5_000_000:
            raise ValueError("Máximo 5 MB por archivo.")
        result = {"text": extract("document." + sys.argv[1], data)}
    except Exception:
        result = {"error": "No se pudo extraer texto. Comprueba el formato, tamaño y cifrado del documento."}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()
