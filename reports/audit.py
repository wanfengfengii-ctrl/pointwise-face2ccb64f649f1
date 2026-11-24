from reports.receipts import Receipt, make_receipt
from reports.snapshots import ReportSnapshot


def verify_report_receipt(report: ReportSnapshot, receipt: Receipt) -> None:
    expected = make_receipt(report.report_id, report.request.request_id)
    if receipt != expected:
        raise ValueError('report and receipt are not from the same publication')
