from src.main import build_parser


def test_parser_accepts_cdp_url_override() -> None:
    parser = build_parser()

    args = parser.parse_args(["--cdp-url", "http://127.0.0.1:9222", "--order-id", "A017X680406286"])

    assert args.cdp_url == "http://127.0.0.1:9222"
    assert args.order_id == "A017X680406286"


def test_parser_accepts_resume_results_argument() -> None:
    parser = build_parser()

    args = parser.parse_args(["--batch", "--resume-results", "runtime/reports/job_20260309/results.jsonl"])

    assert args.batch is True
    assert args.resume_results == "runtime/reports/job_20260309/results.jsonl"
