"""SigV4 against the AWS S3 examples (query-string auth and header-based auth)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.media.sigv4 import presign_url, signed_headers

KEY = "AKIAIOSFODNN7EXAMPLE"
SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
AT = datetime(2013, 5, 24, tzinfo=UTC)


def test_presigned_get_matches_the_aws_example() -> None:
    url = presign_url(
        method="GET",
        scheme="https",
        host="examplebucket.s3.amazonaws.com",
        path="/test.txt",
        access_key=KEY,
        secret=SECRET,
        region="us-east-1",
        expires_seconds=86400,
        at=AT,
    )
    assert url.endswith(
        "X-Amz-Signature=aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"
    )
    assert "X-Amz-Credential=AKIAIOSFODNN7EXAMPLE%2F20130524%2Fus-east-1%2Fs3%2Faws4_request" in url


def test_header_signed_get_matches_the_aws_example() -> None:
    headers = signed_headers(
        method="GET",
        host="examplebucket.s3.amazonaws.com",
        path="/test.txt",
        access_key=KEY,
        secret=SECRET,
        region="us-east-1",
        at=AT,
        extra_headers={"Range": "bytes=0-9"},
    )
    assert headers["authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
        "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, "
        "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    )
