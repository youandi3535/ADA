"""
tools/minio_setup.py  -  MinIO 첫 기동 후 버킷 초기화

사용:
    docker compose --profile core run --rm api python tools/minio_setup.py
    # 또는 호스트에서 (boto3 설치된 환경)
    python tools/minio_setup.py

작업지시서 §7 (Day02), §1 인벤토리
"""

from __future__ import annotations

import os
import sys

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


def get_client():
    endpoint = os.environ.get("MINIO_ENDPOINT", "minio:9000")
    if not endpoint.startswith("http"):
        endpoint = f"http://{endpoint}"
    access_key = os.environ["MINIO_ACCESS_KEY"]
    secret_key = os.environ["MINIO_SECRET_KEY"]

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def ensure_bucket(s3, bucket: str) -> None:
    try:
        s3.head_bucket(Bucket=bucket)
        print(f"[skip] bucket already exists: {bucket}")
        return
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code not in ("404", "NoSuchBucket", "NotFound"):
            raise
    s3.create_bucket(Bucket=bucket)
    print(f"[ok]   created bucket:        {bucket}")


def ensure_prefixes(s3, bucket: str, prefixes: list[str]) -> None:
    """빈 객체로 prefix 생성(폴더 구조 시각화용). 실제 데이터는 아님."""
    for p in prefixes:
        key = p if p.endswith("/") else f"{p}/"
        s3.put_object(Bucket=bucket, Key=key + ".keep", Body=b"")
        print(f"[ok]   prefix:                {bucket}/{key}")


def main() -> int:
    bucket = os.environ.get("MINIO_BUCKET", "autoai-artifacts")
    s3 = get_client()

    ensure_bucket(s3, bucket)
    ensure_prefixes(
        s3,
        bucket,
        [
            "eda",                       # EDA 산출물 (이미지/HTML)
            "models",                    # 학습된 모델 가중치
            "mlflow",                    # MLflow artifact root
            "reports",                   # 13종 산출물
            "self_learning/prompts",     # Day16 KB
            "self_learning/snapshots",   # Day16 체크포인트
        ],
    )
    print("[done] MinIO bootstrap complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
