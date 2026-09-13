"""Sinh cặp khoá VAPID dạng base64url thô (không PEM — PEM có xuống dòng, đặt vào biến môi
trường/GitHub Secret sẽ hỏng). Chép từ kingstock/scripts/gen_vapid.py.

Chạy: venv\\Scripts\\python -m job.gen_vapid
"""
from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def main() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    priv = key.private_numbers().private_value.to_bytes(32, "big")
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    print("VAPID_PUBLIC_KEY=" + b64(pub))
    print("VAPID_PRIVATE_KEY=" + b64(priv))
    print("VAPID_SUBJECT=mailto:you@example.com")
    print("\nDán 3 dòng trên vào .env (local) và vào GitHub → Settings → Secrets (Actions).")
    print("VAPID_PUBLIC_KEY cũng phải đặt vào docs/config.js (biến VAPID_PUBLIC) để điện thoại đăng ký.")


if __name__ == "__main__":
    main()
